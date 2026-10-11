"""Single-owner loopback application service; desktop clients never open SQLite.

LAN listening is deliberately unavailable until project/source authorization and
transport protection are implemented. Tokens are supplied in memory, not logged.
"""
from __future__ import annotations

import hmac
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit

from .item_contracts import STATUSES
from .items import ConflictError, ItemLedger
from .project_export import project_workbook_bytes

MAX_REQUEST_BYTES = 1_048_576


class LocalService:
    def __init__(self, server, thread):
        self.server = server
        self.thread = thread
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def start_local_service(store, token: str) -> LocalService:
    if not isinstance(token, str) or len(token) < 16 or not token.isascii():
        raise ValueError("A bounded ASCII owner token of at least 16 characters is required")
    if len(token) > 512 or any(c.isspace() for c in token):
        raise ValueError("Invalid owner token")
    ledger = ItemLedger(store)

    class Handler(BaseHTTPRequestHandler):
        server_version = "FYP-LocalService/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            # Request paths may contain private search terms. No default logs.
            pass

        def respond(self, status, data, *, binary=False):
            payload = data if binary else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if binary else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            if binary:
                self.send_header("Content-Disposition", 'attachment; filename="project-items.xlsx"')
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True

        def trusted(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get_all("Host", []) != [host] or self.headers.get("Origin") is not None:
                self.respond(403, {"error": "Untrusted client origin or host"})
                return False
            authorization = self.headers.get_all("Authorization", [])
            if len(authorization) != 1 or not authorization[0].isascii() or not hmac.compare_digest(authorization[0], "Bearer " + token):
                self.respond(401, {"error": "Owner authentication required"})
                return False
            return True

        def read_body(self):
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                raise ValueError("Missing or ambiguous length")
            length = int(lengths[0])
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Request exceeds limit")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("JSON required")
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("Incomplete request")
            # Reject duplicate keys instead of silently changing a review intent.
            def object_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON key")
                    result[key] = value
                return result
            value = json.loads(data, object_pairs_hook=object_pairs)
            if not isinstance(value, dict):
                raise ValueError("Object required")
            return value

        def dispatch(self, method):
            if not self.trusted():
                return
            try:
                parsed = urlsplit(self.path)
                if parsed.scheme or parsed.netloc or len(self.path) > 8192:
                    raise ValueError("Invalid path")
                path = unquote(parsed.path)
                if method == "GET":
                    if path == "/api/emails":
                        # Single authorized archive owner. No LAN or role claim.
                        result = {"emails": store.list_emails()}
                    elif path == "/api/candidates":
                        result = {"candidates": ledger.list_candidates()}
                    elif path == "/api/items":
                        query = parse_qs(parsed.query)
                        if set(query) - {"search", "status"} or any(len(v) != 1 for v in query.values()):
                            raise ValueError("Invalid filters")
                        status = query.get("status", [""])[0]
                        if status and status not in STATUSES:
                            raise ValueError("Invalid status")
                        search = query.get("search", [""])[0].casefold()
                        items = ledger.list_items()
                        result = {"items": [item for item in items if
                            (not status or item["fields"]["status"] == status) and
                            (not search or any(search in value.casefold() for value in item["fields"].values()))]}
                    elif path.startswith("/api/items/"):
                        result = ledger.get_item(path[len("/api/items/"):])
                        if result is None:
                            self.respond(404, {"error": "Item not found"})
                            return
                    else:
                        self.respond(404, {"error": "Endpoint not found"})
                        return
                else:
                    body = self.read_body()
                    routes = {
                        "/api/suggest": (ledger.suggest, {"source_id"}),
                        "/api/propose": (ledger.propose, {"source_id", "fields", "evidence", "target_item_id"}),
                        "/api/decide": (ledger.decide, {"candidate_id", "decision", "expected_version", "fields", "note"}),
                        "/api/undo": (ledger.undo, {"item_id", "expected_version", "note"}),
                    }
                    if path == "/api/export":
                        if body:
                            raise ValueError("Export has no path or body arguments")
                        self.respond(200, project_workbook_bytes(ledger), binary=True)
                        return
                    if path not in routes:
                        self.respond(404, {"error": "Endpoint not found"})
                        return
                    operation, allowed = routes[path]
                    if set(body) - allowed:
                        raise ValueError("Unexpected fields")
                    result = operation(**body)
                    if path == "/api/suggest":
                        result = {"candidates": result}
                self.respond(200, result)
            except ConflictError:
                self.respond(409, {"error": "Source or review version changed; reload and review"})
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                self.respond(400, {"error": "Invalid review request or evidence"})
            except sqlite3.OperationalError:
                self.respond(503, {"error": "Storage temporarily unavailable; retry after reload"})
            except Exception:
                self.respond(500, {"error": "Operation failed; no result was confirmed"})

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, name="fyp-local-service", daemon=True)
    thread.start()
    return LocalService(server, thread)

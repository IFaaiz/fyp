"""Small, offline review dashboard for FYP Structured Annotation V1."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = Path(__file__).resolve().parent / "web"
FIXTURE_PATH = ROOT / "ai" / "annotation" / "fyp_structured_v1_synthetic_examples.jsonl"
DATA_ROOT = ROOT / "ai" / "data" / "product_review"
MAX_REQUEST_BYTES = 1_000_000
MAX_SOURCE_CHARS = 500_000
MAX_NOTE_CHARS = 4_000
RECORD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PORT_DEFAULT = 8765

sys.path.insert(0, str(ROOT / "ai" / "src"))
from fyp_structured_v1.mapper import derive_labels  # noqa: E402
from fyp_structured_v1.validation import validate_annotation  # noqa: E402


@dataclass
class ReviewSession:
    original_packet: dict[str, Any]
    record_id: str | None
    synthetic_demo: bool
    base_revision: int | None


SESSIONS: dict[str, ReviewSession] = {}
SESSION_LOCK = threading.RLock()
SAVE_LOCK = threading.RLock()


class PacketError(ValueError):
    pass


class StorageError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PacketError("JSON object has a repeated key")
        value[key] = item
    return value


def _decode_json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError("The request must contain valid UTF-8 JSON.") from exc


def _check_packet(packet: Any) -> dict[str, Any]:
    if not isinstance(packet, dict) or set(packet) != {"source", "annotation"}:
        raise PacketError("Packet must contain exactly source and annotation objects.")
    source, annotation = packet.get("source"), packet.get("annotation")
    if not isinstance(source, dict) or not isinstance(annotation, dict):
        raise PacketError("source and annotation must both be JSON objects.")
    source_id = source.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 500:
        raise PacketError("source.source_id must be a non-empty identifier of at most 500 characters.")
    if not isinstance(source.get("subject"), str) or not isinstance(source.get("current_message"), str):
        raise PacketError("source must include string subject and current_message fields.")
    if len(source["subject"]) > MAX_SOURCE_CHARS or len(source["current_message"]) > MAX_SOURCE_CHARS:
        raise PacketError("Source text exceeds the 500,000 character limit.")
    if not isinstance(source.get("authored_ranges"), list):
        raise PacketError("source.authored_ranges must be an array; current-message evidence needs authored ranges.")
    if annotation.get("current_source_id") != source_id:
        raise PacketError("annotation.current_source_id must match source.source_id.")
    return packet


def _validate_for_session(annotation: Any, session: ReviewSession) -> dict[str, Any]:
    if not isinstance(annotation, dict):
        return {"valid": False, "errors": ["Annotation must be a JSON object."], "warnings": [], "needs_review": True, "labels": []}
    original_annotation = session.original_packet["annotation"]
    baseline = original_annotation.get("provenance")
    if isinstance(baseline, dict) and baseline.get("annotation_tier") == "GOLD" and annotation != original_annotation:
        return {
            "valid": False,
            "errors": ["Imported GOLD packets are read-only in this prototype; editing would make the prior human-review claim stale."],
            "warnings": [],
            "needs_review": True,
            "labels": [],
        }
    if annotation.get("provenance") != baseline:
        return {
            "valid": False,
            "errors": ["Provenance is locked to the original packet in this prototype. Annotation tier and human-review claims cannot be promoted here."],
            "warnings": [],
            "needs_review": True,
            "labels": [],
        }
    source = session.original_packet["source"]
    result = validate_annotation(annotation, {source["source_id"]: source})
    labels = derive_labels(annotation) if result.valid else []
    return {
        "valid": result.valid,
        "errors": list(result.errors),
        "warnings": list(result.warnings),
        "needs_review": result.needs_review,
        "labels": labels,
    }


def _storage_directories() -> dict[str, Path]:
    try:
        data_parent = ROOT / "ai" / "data"
        if data_parent.is_symlink():
            raise StorageError("Local review storage cannot be placed through a symbolic link.")
        if DATA_ROOT.is_symlink():
            raise StorageError("Local review storage cannot be a symbolic link.")
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        resolved_root = DATA_ROOT.resolve()
        expected_parent = (ROOT / "ai" / "data").resolve()
        if resolved_root.parent != expected_parent:
            raise StorageError("Local review storage path is not a direct child of ai/data.")
        directories: dict[str, Path] = {"root": resolved_root}
        for name in ("originals", "records", "audit"):
            directory = DATA_ROOT / name
            if directory.is_symlink():
                raise StorageError("Local review storage contains a symbolic link.")
            directory.mkdir(exist_ok=True)
            resolved = directory.resolve()
            if resolved.parent != resolved_root:
                raise StorageError("Local review storage contains an unexpected path link.")
            directories[name] = resolved
        return directories
    except OSError as exc:
        raise StorageError("Local review storage could not be prepared.") from exc


def _safe_record_path(directory: Path, record_id: str, suffix: str = ".json") -> Path:
    if not RECORD_ID_RE.fullmatch(record_id):
        raise PacketError("Invalid local record identifier.")
    path = directory / f"{record_id}{suffix}"
    try:
        if path.is_symlink():
            raise StorageError("Symbolic links are not valid local record files.")
        resolved_parent = directory.resolve()
        if path.exists() and path.resolve().parent != resolved_parent:
            raise StorageError("A local record path resolves outside its storage directory.")
        if not path.exists() and path.parent.resolve() != resolved_parent:
            raise StorageError("A local record path resolves outside its storage directory.")
    except OSError as exc:
        raise StorageError("Local record path could not be checked.") from exc
    return path


def _read_stored_json(path: Path, directory: Path) -> Any:
    if path.is_symlink():
        raise StorageError("Symbolic links are not valid local record files.")
    if path.resolve().parent != directory.resolve():
        raise StorageError("Stored record path is outside its storage directory.")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise StorageError("Local record could not be read.") from exc
    if len(data) > MAX_REQUEST_BYTES:
        raise StorageError("Stored record exceeds the local size limit.")
    return _decode_json(data)


def _read_fixture_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    if not FIXTURE_PATH.is_file():
        return catalog
    try:
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
            fixture_id = row.get("fixture_id")
            packet = {"source": row.get("source"), "annotation": row.get("annotation")}
            packet = _check_packet(packet)
            validation = validate_annotation(packet["annotation"], {packet["source"]["source_id"]: packet["source"]})
            if isinstance(fixture_id, str) and validation.valid:
                catalog[fixture_id] = packet
    except (OSError, json.JSONDecodeError, PacketError):
        return {}
    return catalog


FIXTURES = _read_fixture_catalog()


def _new_session(
    packet: dict[str, Any], *, record_id: str | None, synthetic_demo: bool,
    base_revision: int | None = None,
) -> str:
    session_id = uuid4().hex
    with SESSION_LOCK:
        SESSIONS[session_id] = ReviewSession(packet, record_id, synthetic_demo, base_revision)
    return session_id


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Source text and request details stay out of terminal and local logs.
        return

    def _headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

    def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        data = payload if isinstance(payload, bytes) else _json_bytes(payload)
        self.send_response(status)
        self._headers(content_type, len(data))
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send(status, {"error": message})

    def _origin_ok(self) -> bool:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host") == expected_host and self.headers.get("Origin") == f"http://{expected_host}"

    def _read_body(self) -> Any:
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise PacketError("Use application/json for local dashboard changes.")
        if self.headers.get("Transfer-Encoding"):
            raise PacketError("Chunked request bodies are not accepted.")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            raise PacketError("A valid Content-Length is required.")
        length = int(raw_length)
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise PacketError("Request body must be between 1 byte and 1,000,000 bytes.")
        return _decode_json(self.rfile.read(length))

    def _host_ok(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._send_error_json(400, "Use the loopback dashboard address shown at startup.")
            return
        path = urlsplit(self.path).path
        try:
            if path == "/":
                self._static("index.html", "text/html; charset=utf-8")
            elif path == "/assets/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
            elif path == "/assets/style.css":
                self._static("style.css", "text/css; charset=utf-8")
            elif path == "/api/demos":
                demos = []
                for fixture_id, packet in FIXTURES.items():
                    demos.append({"fixture_id": fixture_id, "subject": packet["source"]["subject"]})
                self._send(200, {"demos": demos})
            elif path == "/api/records":
                self._list_records()
            else:
                match = re.fullmatch(r"/api/records/([0-9a-f]{32})", path)
                if match:
                    self._open_record(match.group(1))
                else:
                    self._send_error_json(404, "Not found.")
        except PacketError as exc:
            self._send_error_json(400, str(exc))
        except StorageError as exc:
            self._send_error_json(500, str(exc))
        except Exception:
            self._send_error_json(500, "The local read operation failed.")

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_ok():
            self._send_error_json(403, "Dashboard changes must come from this loopback page.")
            return
        try:
            body = self._read_body()
            path = urlsplit(self.path).path
            if path == "/api/open":
                self._open_packet(body)
            elif path == "/api/open-demo":
                self._open_demo(body)
            elif path == "/api/validate":
                self._validate_edit(body)
            elif path == "/api/save":
                self._save(body)
            else:
                self._send_error_json(404, "Not found.")
        except PacketError as exc:
            self._send_error_json(400, str(exc))
        except StorageError as exc:
            self._send_error_json(500, str(exc))
        except Exception:
            self._send_error_json(500, "The local operation failed. No source text was written to a log.")

    def _static(self, filename: str, content_type: str) -> None:
        try:
            path = WEB_ROOT / filename
            data = path.read_bytes()
        except OSError:
            self._send_error_json(404, "Dashboard asset not found.")
            return
        self._send(200, data, content_type)

    def _session(self, value: Any) -> ReviewSession:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
            raise PacketError("Local review session is missing or expired. Reload the packet.")
        with SESSION_LOCK:
            session = SESSIONS.get(value)
        if session is None:
            raise PacketError("Local review session is missing or expired. Reload the packet.")
        return session

    def _open_packet(self, body: Any) -> None:
        packet = _check_packet(body)
        provenance = packet["annotation"].get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        read_only_gold = provenance.get("annotation_tier") == "GOLD"
        session_id = _new_session(packet, record_id=None, synthetic_demo=False)
        self._send(200, {
            "session_id": session_id,
            "packet": packet,
            "record_id": None,
            "synthetic_demo": False,
            "read_only_gold": read_only_gold,
            "validation": _validate_for_session(packet["annotation"], SESSIONS[session_id]),
        })

    def _open_demo(self, body: Any) -> None:
        if not isinstance(body, dict) or set(body) != {"fixture_id"} or not isinstance(body.get("fixture_id"), str):
            raise PacketError("Choose one available synthetic fixture.")
        packet = FIXTURES.get(body["fixture_id"])
        if packet is None:
            raise PacketError("That synthetic fixture is not available as a standalone packet.")
        session_id = _new_session(packet, record_id=None, synthetic_demo=True)
        session = SESSIONS[session_id]
        self._send(200, {
            "session_id": session_id,
            "packet": packet,
            "record_id": None,
            "synthetic_demo": True,
            "read_only_gold": False,
            "validation": _validate_for_session(packet["annotation"], session),
        })

    def _validate_edit(self, body: Any) -> None:
        if not isinstance(body, dict) or set(body) != {"session_id", "annotation"}:
            raise PacketError("Validation requires session_id and annotation.")
        session = self._session(body["session_id"])
        self._send(200, {"validation": _validate_for_session(body["annotation"], session), "record_id": session.record_id})

    def _list_records(self) -> None:
        directories = _storage_directories()
        records: list[dict[str, Any]] = []
        try:
            files = sorted(directories["records"].glob("*.json"), key=lambda item: item.name)
        except OSError as exc:
            raise StorageError("Local records could not be listed.") from exc
        for path in files:
            if not RECORD_ID_RE.fullmatch(path.stem):
                continue
            try:
                value = _read_stored_json(path, directories["records"])
                packet = value.get("current_packet") if isinstance(value, dict) else None
                source = packet.get("source") if isinstance(packet, dict) else None
                annotation = packet.get("annotation") if isinstance(packet, dict) else None
                if not isinstance(source, dict) or not isinstance(annotation, dict):
                    continue
                records.append({
                    "record_id": path.stem,
                    "created_at": value.get("created_at"),
                    "saved_at": value.get("saved_at"),
                    "source_id": source.get("source_id", ""),
                    "subject": source.get("subject", ""),
                    "needs_review": bool(annotation.get("needs_review")),
                    "annotation_tier": annotation.get("provenance", {}).get("annotation_tier"),
                })
            except (StorageError, PacketError, AttributeError):
                continue
        self._send(200, {"records": records})

    def _open_record(self, record_id: str) -> None:
        directories = _storage_directories()
        record_path = _safe_record_path(directories["records"], record_id)
        original_path = _safe_record_path(directories["originals"], record_id)
        record = _read_stored_json(record_path, directories["records"])
        original = _check_packet(_read_stored_json(original_path, directories["originals"]))
        if not isinstance(record, dict) or not isinstance(record.get("current_packet"), dict):
            raise StorageError("Local record has an invalid shape.")
        current = _check_packet(record["current_packet"])
        revision = record.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise StorageError("Saved local record has an invalid revision number.")
        if current["source"] != original["source"]:
            raise StorageError("Saved source does not match the immutable original packet.")
        if current["annotation"].get("provenance") != original["annotation"].get("provenance"):
            raise StorageError("Saved provenance does not match the immutable original packet.")
        session_id = _new_session(
            original,
            record_id=record_id,
            synthetic_demo=False,
            base_revision=revision,
        )
        session = SESSIONS[session_id]
        self._send(200, {
            "session_id": session_id,
            "packet": current,
            "record_id": record_id,
            "created_at": record.get("created_at"),
            "synthetic_demo": session.synthetic_demo,
            "read_only_gold": original["annotation"].get("provenance", {}).get("annotation_tier") == "GOLD",
            "review_note": record.get("review_note", ""),
            "validation": _validate_for_session(current["annotation"], session),
        })

    def _save(self, body: Any) -> None:
        with SAVE_LOCK:
            self._save_locked(body)

    def _save_locked(self, body: Any) -> None:
        if not isinstance(body, dict) or set(body) != {"session_id", "annotation", "review_note"}:
            raise PacketError("Save requires session_id, annotation and review_note.")
        session = self._session(body["session_id"])
        note = body["review_note"]
        if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS:
            raise PacketError("Review notes must be plain text of at most 4,000 characters.")
        validation = _validate_for_session(body["annotation"], session)
        if not validation["valid"]:
            self._send(422, {"validation": validation})
            return
        provenance = session.original_packet["annotation"].get("provenance", {})
        if provenance.get("annotation_tier") == "GOLD":
            self._send_error_json(403, "Imported GOLD packets are read-only and cannot be saved as edited reviews.")
            return
        directories = _storage_directories()
        record_id = session.record_id or uuid4().hex
        original_path = _safe_record_path(directories["originals"], record_id)
        record_path = _safe_record_path(directories["records"], record_id)
        audit_path = _safe_record_path(directories["audit"], record_id, ".jsonl")
        now = _now()
        current_packet = {"source": session.original_packet["source"], "annotation": body["annotation"]}
        original_bytes = _json_bytes(session.original_packet)
        digest = hashlib.sha256(_json_bytes(body["annotation"])).hexdigest()
        audit_entry = {
            "saved_at": now,
            "record_id": record_id,
            "action": "created" if session.record_id is None else "updated",
            "annotation_sha256": digest,
            "needs_review": validation["needs_review"],
            "validation_error_count": len(validation["errors"]),
            "validation_warning_count": len(validation["warnings"]),
            "review_note_sha256": hashlib.sha256(note.encode("utf-8")).hexdigest(),
        }
        record = {
            "record_id": record_id,
            "created_at": now,
            "saved_at": now,
            "revision": 1 if session.record_id is None else None,
            "immutable_original_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "current_packet": current_packet,
            "review_note": note,
        }
        if len(original_bytes) > MAX_REQUEST_BYTES:
            raise PacketError("Saved packet would exceed the local record size limit.")

        created: list[Path] = []
        try:
            if session.record_id is None:
                record_bytes = _json_bytes(record)
                if len(record_bytes) > MAX_REQUEST_BYTES:
                    raise PacketError("Saved packet would exceed the local record size limit.")
                with original_path.open("xb") as handle:
                    created.append(original_path)
                    handle.write(original_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                with audit_path.open("x", encoding="utf-8", newline="\n") as handle:
                    created.append(audit_path)
                    handle.write(json.dumps(audit_entry, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                with record_path.open("xb") as handle:
                    created.append(record_path)
                    handle.write(record_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
            else:
                original = _check_packet(_read_stored_json(original_path, directories["originals"]))
                if original != session.original_packet:
                    raise StorageError("Immutable original packet changed during this review session.")
                existing_record = _read_stored_json(record_path, directories["records"])
                if not isinstance(existing_record, dict) or not isinstance(existing_record.get("created_at"), str):
                    raise StorageError("Saved local record has an invalid creation timestamp.")
                existing_packet = _check_packet(existing_record.get("current_packet"))
                if existing_packet["source"] != original["source"] or existing_packet["annotation"].get("provenance") != original["annotation"].get("provenance"):
                    raise StorageError("Saved source or provenance no longer matches the immutable original packet.")
                stored_revision = existing_record.get("revision")
                if session.base_revision is None or stored_revision != session.base_revision:
                    self._send(409, {"error": "This saved review changed in another tab or session. Reload it before saving again."})
                    return
                record["created_at"] = existing_record["created_at"]
                previous_revision = existing_record.get("revision")
                if not isinstance(previous_revision, int) or isinstance(previous_revision, bool) or previous_revision < 1:
                    raise StorageError("Saved local record has an invalid revision number.")
                record["revision"] = previous_revision + 1
                record_bytes = _json_bytes(record)
                if len(record_bytes) > MAX_REQUEST_BYTES:
                    raise PacketError("Saved packet would exceed the local record size limit.")
                with audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(audit_entry, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary = _safe_record_path(directories["records"], uuid4().hex, ".tmp")
                with temporary.open("xb") as handle:
                    handle.write(record_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, record_path)
        except FileExistsError as exc:
            for path in reversed(created):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise StorageError("A local record identifier already exists. Reload saved records and try again.") from exc
        except Exception:
            for path in reversed(created):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        session.record_id = record_id
        session.base_revision = record["revision"]
        self._send(200, {"record_id": record_id, "saved_at": now, "validation": validation})


def main() -> int:
    port = PORT_DEFAULT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Usage: offline_dashboard.py [port]", file=sys.stderr)
            return 2
    if not 1024 <= port <= 65535:
        print("Port must be between 1024 and 65535.", file=sys.stderr)
        return 2
    try:
        server = DashboardServer(("127.0.0.1", port), DashboardHandler)
    except OSError as exc:
        print(f"Could not bind the local dashboard on 127.0.0.1:{port}: {exc}", file=sys.stderr)
        return 1
    print(f"Offline FYP review dashboard: http://127.0.0.1:{port}/")
    print("Loopback only. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

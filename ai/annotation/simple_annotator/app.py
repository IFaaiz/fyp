"""Loopback-only Flask application and CLI for the simple annotator."""

from __future__ import annotations

import argparse
import ipaddress
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AI_ROOT = PROJECT_ROOT / "ai"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

if __package__:
    from .store import AnnotationStore, DEFAULT_OUTPUT_DIR, DEFAULT_SEED_PATH
else:  # support: python ai/annotation/simple_annotator/app.py
    from ai.annotation.simple_annotator.store import (
        AnnotationStore,
        DEFAULT_OUTPUT_DIR,
        DEFAULT_SEED_PATH,
    )


def create_app(
    reviewer: str,
    limit: int | None = None,
    seed_path: str | Path = DEFAULT_SEED_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Flask:
    """Build the reviewer app without writing output until the first PUT."""
    store = AnnotationStore(
        reviewer,
        limit=limit,
        seed_path=seed_path,
        output_dir=output_dir,
    )
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["ANNOTATOR_STORE"] = store
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

    @app.before_request
    def require_loopback_client():
        remote = request.remote_addr or ""
        try:
            is_loopback = ipaddress.ip_address(remote).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            return jsonify({"error": "This annotator accepts local connections only."}), 403
        return None

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def api_state():
        return jsonify(store.state())

    @app.get("/api/email/<int:index>")
    def api_get_email(index: int):
        try:
            return jsonify(store.get_email(index))
        except IndexError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.put("/api/email/<int:index>")
    def api_save_email(index: int):
        try:
            payload: Any = request.get_json(silent=True)
            return jsonify(store.save(index, payload))
        except BadRequest:
            return jsonify({"error": "Request body must be valid JSON."}), 400
        except IndexError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.errorhandler(BadRequest)
    def handle_bad_request(exc):
        return jsonify({"error": "Request body must be valid JSON."}), 400

    @app.errorhandler(413)
    def handle_too_large(_exc):
        return jsonify({"error": "Request body is too large."}), 413

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return jsonify({"error": "Not found."}), 404

    return app


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local FYP email annotator.")
    parser.add_argument("--reviewer", required=True, help="reviewer identifier")
    parser.add_argument(
        "--pilot", choices=("original", "project"), default="original",
        help="original 250-email seed or separate screened 50-email project pilot",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="review only the first N seed records (default: all 250)",
    )
    parser.add_argument("--port", type=int, default=5000, help="loopback port (default: 5000)")
    parser.add_argument(
        "--seed-path",
        type=Path,
        default=DEFAULT_SEED_PATH,
        help="Label Studio seed task JSON file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory for reviewer JSONL and draft files",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the browser automatically",
    )
    args = parser.parse_args(argv)
    if args.port < 1 or args.port > 65535:
        parser.error("--port must be between 1 and 65535")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer")
    return args


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    seed_path = args.seed_path
    output_dir = args.output_dir
    if args.pilot == "project":
        if args.seed_path != DEFAULT_SEED_PATH:
            raise SystemExit("--seed-path cannot be combined with --pilot project")
        from ai.scripts.build_project_pilot import build_project_pilot_seed

        seed_path = build_project_pilot_seed()
        if args.output_dir == DEFAULT_OUTPUT_DIR:
            output_dir = seed_path.parent / "reviewers"
    app = create_app(
        reviewer=args.reviewer,
        limit=args.limit,
        seed_path=seed_path,
        output_dir=output_dir,
    )
    url = f"http://127.0.0.1:{args.port}/"
    store: AnnotationStore = app.config["ANNOTATOR_STORE"]
    print(f"Annotator ready at {url}")
    print(f"Reviewer output: {store.output_path}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url, new=2)).start()
    app.run(
        host="127.0.0.1",
        port=args.port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()

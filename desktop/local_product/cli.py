"""Command-line entry points for the local email foundation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .adapters import OutlookAdapter, iter_path_records
from .classification import ExistingAISilverClassifier
from .excel_export import export_excel
from .store import EmailStore, default_database_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_local_product.py",
        description="Import local project email into SQLite and export an Excel archive.",
    )
    commands = parser.add_subparsers(dest="command")

    import_cmd = commands.add_parser("import", help="import .eml, .msg, JSONL files, or directories")
    import_cmd.add_argument("sources", nargs="+", type=Path)
    import_cmd.add_argument("--db", type=Path, default=default_database_path())
    import_cmd.add_argument("--source-name", default=None)
    import_cmd.add_argument(
        "--ai-silver",
        action="store_true",
        help="also run the existing frozen diagnostic classifier; outputs remain REVIEW and are not human gold",
    )

    outlook_cmd = commands.add_parser("import-outlook", help="read recent classic Outlook Inbox messages through COM")
    outlook_cmd.add_argument("--db", type=Path, default=default_database_path())
    outlook_cmd.add_argument("--limit", type=int, default=200, help="newest messages to read (1–5000; default: 200)")

    export_cmd = commands.add_parser("export", help="write Emails, Threads, and review-only extraction sheets")
    export_cmd.add_argument("--db", type=Path, default=default_database_path())
    export_cmd.add_argument("--xlsx", type=Path, required=True)

    commands.add_parser("gui", help="open the PySide6 local archive browser").add_argument(
        "--db", type=Path, default=default_database_path()
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command is None or args.command == "gui":
        db_path = getattr(args, "db", default_database_path())
        try:
            from .ui import run_gui
        except ImportError as exc:
            raise SystemExit("PySide6 is missing. Install desktop/requirements.txt and run again.") from exc
        return run_gui(str(db_path))

    store = EmailStore(args.db)
    if args.command == "import":
        classifier = None
        if args.ai_silver:
            repository_root = Path(__file__).resolve().parents[2]
            classifier = ExistingAISilverClassifier.from_repository(repository_root)
        counts = store.import_records(
            iter_path_records(args.sources, source_name=args.source_name), classifier=classifier
        )
        print(json.dumps({"database": str(store.path), **counts}, ensure_ascii=False))
        return 0
    if args.command == "import-outlook":
        counts = store.import_records(OutlookAdapter(limit=args.limit).iter_records())
        print(json.dumps({"database": str(store.path), **counts}, ensure_ascii=False))
        return 0
    if args.command == "export":
        path = export_excel(store, args.xlsx)
        print(json.dumps({"database": str(store.path), "xlsx": str(path), "messages": store.count()}, ensure_ascii=False))
        return 0
    raise SystemExit("Unknown command")

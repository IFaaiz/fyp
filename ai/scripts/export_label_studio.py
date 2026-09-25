"""Export canonical JSONL records as blank Label Studio tasks."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.annotation.label_studio import records_to_tasks
from src.annotation.label_studio_config import make_label_studio_config
from src.datasets.schemas import read_jsonl


def known_gold_records(extra_paths: list[Path] | None = None) -> list[dict]:
    paths = set(extra_paths or [])
    human_dir = AI_DIR / "data" / "annotated" / "human"
    if human_dir.exists():
        paths.update(human_dir.rglob("*.jsonl"))
    rows = []
    for path in sorted(paths):
        if path.exists():
            rows.extend(row for row in read_jsonl(path)
                        if row.get("annotation", {}).get("status") == "gold")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="canonical JSONL records")
    parser.add_argument("--output", type=Path, required=True, help="Label Studio tasks JSON")
    parser.add_argument("--assignment", choices=("A", "B"), required=True)
    parser.add_argument("--gold-records", type=Path, action="append", default=[], help="additional canonical JSONL files to scan for gold thread IDs")
    parser.add_argument("--config-output", type=Path, help="also write a Label Studio XML project configuration")
    args = parser.parse_args()
    records = list(read_jsonl(args.input))
    if len({row.get("email_id") for row in records}) != len(records):
        raise ValueError("input contains duplicate email_id values")
    tasks = records_to_tasks(records, assignment=args.assignment,
                             gold_records=known_gold_records(args.gold_records))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.config_output:
        args.config_output.parent.mkdir(parents=True, exist_ok=True)
        args.config_output.write_text(make_label_studio_config(AI_DIR / "annotation" / "label_schema.json"), encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "output": str(args.output), "assignment": args.assignment}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

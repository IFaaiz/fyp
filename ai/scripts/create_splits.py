"""Split a validated canonical JSONL file by conversation thread."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datasets.schemas import read_jsonl, write_jsonl
from src.datasets.splitting import split_by_thread
from src.datasets.validation import validate_records, validate_split_isolation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "splits")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    records = list(read_jsonl(args.input))
    report = validate_records(records)
    if report["errors"]:
        raise ValueError("input failed validation: " + "; ".join(report["errors"][:10]))
    splits = split_by_thread(records, seed=args.seed)
    for name, items in splits.items():
        write_jsonl(args.output_dir / f"{name}.jsonl", items)
    print(json.dumps({
        "records": {name: len(items) for name, items in splits.items()},
        "threads": {name: len({(item["source_dataset"], item["thread_id"]) for item in items}) for name, items in splits.items()},
        "isolation_errors": validate_split_isolation(splits),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Import Label Studio task JSON as canonical annotated JSONL."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.annotation.label_studio import task_to_annotated_canonical_jsonl
from src.datasets.schemas import write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Label Studio task export JSON")
    parser.add_argument("--output", type=Path, required=True, help="canonical output JSONL")
    parser.add_argument("--annotator", required=True, help="human reviewer identifier recorded in canonical annotation metadata")
    parser.add_argument("--annotation-id", type=int, help="select this annotation ID when a task has multiple completed annotations")
    parser.add_argument("--allow-unannotated", action="store_true", help="preserve embedded canonical records for unfinished tasks; useful for lossless transport checks")
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("tasks")
    if not isinstance(value, list) or any(not isinstance(task, dict) for task in value):
        raise ValueError("Label Studio export must be a list of task objects")
    records = task_to_annotated_canonical_jsonl(
        value, annotator=args.annotator, annotation_id=args.annotation_id,
        allow_unannotated=args.allow_unannotated,
    )
    count = write_jsonl(args.output, records)
    print(json.dumps({"records": count, "output": str(args.output), "annotator": args.annotator,
                      "gold_promotions": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

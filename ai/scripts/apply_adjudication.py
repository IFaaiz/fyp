"""Apply manually completed adjudication decisions to canonical records."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.annotation.adjudication import apply_adjudication_decisions
from src.datasets.schemas import read_jsonl, write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="canonical JSONL containing the adjudicated email records")
    parser.add_argument("--decisions", type=Path, required=True, help="completed decisions based on the generated template")
    parser.add_argument("--output", type=Path, required=True, help="human-reviewed canonical JSONL output")
    args = parser.parse_args()
    records = apply_adjudication_decisions(read_jsonl(args.base), read_jsonl(args.decisions))
    count = write_jsonl(args.output, records)
    print(json.dumps({"adjudicated_records": count, "output": str(args.output),
                      "status": "human_reviewed", "gold_promotions": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

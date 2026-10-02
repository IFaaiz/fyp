"""Prepare private, blinded A/B packets for structured annotation review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.structured_annotation.workflow import prepare_run  # noqa: E402


def parse_record_indices(value: str) -> list[int]:
    """Parse a comma-separated ordered list of zero-based JSONL record offsets."""
    parts = value.split(",")
    if not value.strip() or any(not part.strip() for part in parts):
        raise argparse.ArgumentTypeError("record indices must be a non-empty comma-separated list of integers")
    try:
        return [int(part.strip(), 10) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("record indices must be a comma-separated list of integers") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Private, unreviewed candidate JSONL under ai/data")
    parser.add_argument("--output-dir", type=Path, required=True, help="New private run directory under ai/data/structured_review")
    parser.add_argument("--purpose", choices=("TRAIN", "TRAIN_SCREEN", "EVAL", "CHALLENGE"), required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--reviewer-a", required=True)
    parser.add_argument("--reviewer-b", required=True)
    parser.add_argument("--boundary", type=Path, required=True, help="Actual source partition boundary manifest JSON")
    parser.add_argument("--index", type=Path, help="Global index path; defaults to index_path in --boundary")
    parser.add_argument("--partition", help="Expected boundary partition; defaults to TRAIN_SCREEN for TRAIN, EVAL_RESERVED for EVAL, or purpose otherwise")
    parser.add_argument("--record-offset", type=int, default=0, help="Zero-based source-file record offset; binds a contiguous packet slice")
    parser.add_argument("--record-limit", type=int, help="Positive number of records to include from the selected offset; never truncates record text")
    parser.add_argument("--record-indices", type=parse_record_indices,
                        help="Optional ordered comma-separated zero-based source-file record offsets (for example: 0,3,5); mutually exclusive with non-default --record-offset/--record-limit")
    args = parser.parse_args()
    result = prepare_run(
        source_path=args.source,
        output_dir=args.output_dir,
        purpose=args.purpose,
        dataset_id=args.dataset_id,
        reviewer_a=args.reviewer_a,
        reviewer_b=args.reviewer_b,
        index_path=args.index,
        assignments_path=args.boundary,
        partition_name=args.partition,
        record_offset=args.record_offset,
        record_limit=args.record_limit,
        record_indices=args.record_indices,
    )
    source_manifest = json.loads((args.output_dir / "source_manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "status": result["status"],
        "run_id": result["run_id"],
        "purpose": result["purpose"],
        "source_count": source_manifest["source_count"],
        "input_record_count": source_manifest["input_record_count"],
        "record_offset": source_manifest["record_offset"],
        "record_indices": source_manifest.get("record_indices"),
        "selection_policy": source_manifest["selection_policy"],
        "record_count": source_manifest["record_count"],
        "source_manifest_sha256": result["source_manifest_sha256"],
        "source_bundle_sha256": result["source_bundle_sha256"],
        "reviewer_packets": {role: item["packet_sha256"] for role, item in result["reviewers"].items()},
        "text_printed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

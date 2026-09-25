"""Prepare MailEx full_data as canonical JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.mailex import (  # noqa: E402
    DEFAULT_FULL_DATA,
    DEFAULT_MAPPING,
    DEFAULT_RAW_THREADS,
    prepare_mailex,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert the official MailEx full_data thread JSON files to canonical JSONL."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_FULL_DATA)
    parser.add_argument("--raw-threads-dir", type=Path, default=DEFAULT_RAW_THREADS)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument(
        "--output",
        type=Path,
        default=AI_ROOT / "data" / "processed" / "mailex.jsonl",
    )
    parser.add_argument(
        "--stats",
        type=Path,
        default=AI_ROOT / "reports" / "mailex_stats.json",
    )
    args = parser.parse_args()

    stats = prepare_mailex(
        data_dir=args.data_dir,
        raw_threads_dir=args.raw_threads_dir,
        mapping_path=args.mapping,
        output_path=args.output,
        stats_path=args.stats,
    )
    summary = {
        "threads": stats["threads"],
        "messages": stats["messages"],
        "usable_messages": stats["usable_messages"],
        "source_event_count": stats["source_event_count"],
        "mapped_event_count": stats["mapped_event_count"],
        "unmapped_event_count": stats["unmapped_event_count"],
        "canonical_span_count": stats["canonical_span_count"],
        "empty_messages": stats["empty_messages"],
        "output": str(args.output),
        "stats": str(args.stats),
    }
    print(json.dumps(summary, indent=2))
    return 1 if stats["source_file_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

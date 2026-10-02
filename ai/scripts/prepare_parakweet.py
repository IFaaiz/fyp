"""Prepare pinned Parakweet sentence-level intent data as auxiliary JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.parakweet import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    DEFAULT_OUTPUT,
    DEFAULT_REVIEW_OUTPUT,
    DEFAULT_STATS,
    prepare_parakweet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and prepare Parakweet source splits and binary labels.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_OUTPUT)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    args = parser.parse_args()
    stats = prepare_parakweet(
        data_root=args.data_root,
        output_path=args.output,
        review_output_path=args.review_output,
        stats_path=args.stats,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Prepare RADAR Action-Item judgments and spans as local auxiliary JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.radar_action import (  # noqa: E402
    ARCHIVE_SHA256,
    DEFAULT_MESSAGE_ROOT,
    DEFAULT_OUTPUT,
    DEFAULT_REVIEW_OUTPUT,
    DEFAULT_STATS,
    write_radar_action_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and prepare the full-file-offset RADAR Action-Item auxiliary corpus."
    )
    parser.add_argument("--message-root", type=Path, default=DEFAULT_MESSAGE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_OUTPUT)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--source-archive-sha256", default=ARCHIVE_SHA256)
    args = parser.parse_args()
    stats = write_radar_action_outputs(
        message_root=args.message_root,
        output_path=args.output,
        review_output_path=args.review_output,
        stats_path=args.stats,
        source_archive_sha256=args.source_archive_sha256,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

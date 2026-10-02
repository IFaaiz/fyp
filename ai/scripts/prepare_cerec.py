"""Prepare CEREC aggregate counts and a local source/coreference review sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.cerec import (  # noqa: E402
    ARCHIVE_SHA256,
    DEFAULT_CONLL_ROOT,
    DEFAULT_REVIEW_OUTPUT,
    DEFAULT_STATS,
    prepare_cerec,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the pinned CEREC CoNLL files locally; this does not authorize training."
    )
    parser.add_argument("--conll-root", type=Path, default=DEFAULT_CONLL_ROOT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_OUTPUT)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--source-archive-sha256", default=ARCHIVE_SHA256)
    parser.add_argument("--review-limit", type=int, default=50)
    args = parser.parse_args()
    stats = prepare_cerec(
        conll_root=args.conll_root,
        review_output_path=args.review_output,
        stats_path=args.stats,
        source_archive_sha256=args.source_archive_sha256,
        review_limit=args.review_limit,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

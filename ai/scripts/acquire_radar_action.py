"""Download/check and safely extract the official CMU RADAR Action-Item data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.radar_action import (  # noqa: E402
    DEFAULT_ARCHIVE,
    DEFAULT_DOC,
    DEFAULT_EXTRACTED_ROOT,
    DEFAULT_RAW_ROOT,
    acquire_radar_action,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire the SHA-256-pinned official RADAR Action-Item release into ignored ai/data/raw."
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--documentation", type=Path, default=DEFAULT_DOC)
    parser.add_argument("--extracted-root", type=Path, default=DEFAULT_EXTRACTED_ROOT)
    args = parser.parse_args()
    result = acquire_radar_action(
        raw_root=args.raw_root,
        archive_path=args.archive,
        doc_path=args.documentation,
        extracted_root=args.extracted_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

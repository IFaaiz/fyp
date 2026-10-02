"""Acquire pinned Parakweet data and provenance files into ignored raw storage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.parakweet import DEFAULT_RAW_ROOT, acquire_parakweet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire Parakweet at a pinned author commit.")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    args = parser.parse_args()
    print(json.dumps(acquire_parakweet(raw_root=args.raw_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

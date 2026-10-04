"""Build separate native MailEx views excluding protected FYP components."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT / "src"))

from datasets.mailex_native import DEFAULT_OUTPUT, PROTECTED_V2_INDEX, build_fyp_safe_views  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--boundary-path", type=Path)
    parser.add_argument("--index-path", type=Path)
    args = parser.parse_args()
    result = build_fyp_safe_views(
        rows_dir=args.rows_dir,
        output_dir=args.output_dir,
        boundary_path=args.boundary_path,
        index_path=args.index_path or PROTECTED_V2_INDEX,
    )
    print({
        "fyp_safe_split_counts": result["fyp_safe_split_counts"],
        "fyp_safe_row_file_sha256": result["fyp_safe_row_file_sha256"],
        "link_or_group_expanded_record_count": result["link_or_group_expanded_record_count"],
        "globally_excluded_thread_count": result["globally_excluded_thread_count"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

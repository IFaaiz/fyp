"""Prepare private native MailEx extraction rows and aggregate-only audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT / "src"))

from datasets.mailex_native import (  # noqa: E402
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    convert_splits,
    write_audit_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--report-path",
        type=Path,
        default=AI_ROOT / "reports" / "mailex_native_extraction_audit.md",
    )
    parser.add_argument("--splits", nargs="+", default=["train", "dev", "test"])
    args = parser.parse_args()
    manifest = convert_splits(args.source_dir, args.output_dir, args.splits)
    write_audit_report(manifest, args.report_path)
    print({
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "split_counts": manifest["summary"]["split_counts"],
        "source_hashes_sha256": manifest["source_split_hashes_sha256"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

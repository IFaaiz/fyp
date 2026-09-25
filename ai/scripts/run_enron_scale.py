"""Run deterministic Enron ingestion at staged limits and/or over the full corpus."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import subprocess
import sys
from pathlib import Path


AI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AI_DIR.parent
PREPARE_SCRIPT = AI_DIR / "scripts" / "prepare_enron.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maildir", type=Path,
        default=AI_DIR / "data" / "raw" / "enron" / "full" / "maildir",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=AI_DIR / "data" / "interim" / "enron_scale",
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--include-full", action="store_true")
    parser.add_argument(
        "--summary", type=Path,
        default=AI_DIR / "reports" / "enron_scale_runs.json",
    )
    args = parser.parse_args()
    if any(size <= 0 for size in args.sizes):
        parser.error("all staged sizes must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, object]] = []
    sizes: list[int | None] = list(dict.fromkeys(args.sizes))
    if args.include_full:
        sizes.append(None)

    for size in sizes:
        label = "full" if size is None else str(size)
        output = args.output_dir / f"enron_{label}.jsonl"
        stats_path = args.output_dir / f"enron_{label}.stats.json"
        command = [
            sys.executable,
            str(PREPARE_SCRIPT),
            "--maildir",
            str(args.maildir),
            "--output",
            str(output),
            "--stats-output",
            str(stats_path),
        ]
        if size is not None:
            command.extend(["--max-messages", str(size)])
        print(f"Running {label}: {' '.join(command)}", flush=True)
        subprocess.run(command, check=True)
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        stats["stage"] = label
        runs.append(stats)

    try:
        maildir_path = args.maildir.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        maildir_path = args.maildir.resolve().as_posix()
    summary = {
        "source": "CMU CALO Enron May 7, 2015 release",
        "maildir_path": maildir_path,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": runs,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.summary), "runs": runs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

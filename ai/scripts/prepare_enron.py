"""Prepare canonical unlabelled Enron records from a local maildir."""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import sys
import time
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AI_DIR.parent
sys.path.insert(0, str(AI_DIR))

from src.datasets.enron import prepare_enron_jsonl  # noqa: E402


def _peak_working_set_bytes() -> int | None:
    """Return this process's peak working set on Windows, or None elsewhere."""
    if sys.platform != "win32":
        return None

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("PageFaultCount", ctypes.c_uint32),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.WinDLL("kernel32", use_last_error=True).GetCurrentProcess()
    get_memory = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCountersEx), ctypes.c_uint32]
    get_memory.restype = ctypes.c_int
    if not get_memory(process, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.PeakWorkingSetSize)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maildir", type=Path,
        default=AI_DIR / "data" / "raw" / "enron" / "full" / "maildir",
        help="full extracted CMU CALO maildir (default: %(default)s)",
    )
    parser.add_argument(
        "--output", type=Path,
        default=AI_DIR / "data" / "interim" / "enron.jsonl",
        help="canonical JSONL output (default: %(default)s)",
    )
    parser.add_argument("--max-messages", type=int, help="limit input files for a quick local sample")
    parser.add_argument("--context-limit-chars", type=int, default=6000)
    parser.add_argument(
        "--stats-output", type=Path,
        help="optional JSON file for portable run statistics",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    stats = prepare_enron_jsonl(
        args.maildir,
        args.output,
        max_messages=args.max_messages,
        context_limit_chars=args.context_limit_chars,
    )
    output = args.output.resolve()
    try:
        portable_output = output.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        portable_output = output.as_posix()
    result = {
        **stats,
        "output_path": portable_output,
        "output_bytes": output.stat().st_size,
        "max_messages_requested": args.max_messages,
        "context_limit_chars": args.context_limit_chars,
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "peak_working_set_bytes": _peak_working_set_bytes(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    if args.stats_output:
        args.stats_output.parent.mkdir(parents=True, exist_ok=True)
        args.stats_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

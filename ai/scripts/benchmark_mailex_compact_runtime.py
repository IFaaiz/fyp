"""Measure deployment runtime on safe DEV messages; never opens TEST."""
from __future__ import annotations

import argparse
import ctypes
import json
import platform
import statistics
import time
from pathlib import Path

PROCESS_STARTED = time.perf_counter()
from predict_mailex_compact import load_checkpoint
from mailex_extraction.compact import canonical_rows, encode_features, predict, read_rows, sha256
import torch


def memory_info():
    if platform.system() != "Windows":
        return {"peak_process_ram_bytes": None, "reason": "Windows counter unavailable"}
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    *[(name, ctypes.c_size_t) for name in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                        "PagefileUsage", "PeakPagefileUsage")]]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    ok = psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return {"peak_process_ram_bytes": counters.PeakWorkingSetSize if ok else None,
            "current_process_ram_bytes": counters.WorkingSetSize if ok else None,
            "peak_process_commit_bytes": counters.PeakPagefileUsage if ok else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = canonical_rows(read_rows(args.input))
    if any(row["split"] != "dev" for row in rows):
        raise ValueError("Runtime benchmark is DEV-only")
    started = time.perf_counter()
    model, tokenizer, config = load_checkpoint(args.checkpoint, args.device)
    if args.device == "cuda":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    load_seconds = time.perf_counter() - started
    process_ready_seconds = time.perf_counter() - PROCESS_STARTED
    features = [encode_features(row, tokenizer, config["max_length"], config["stride"]) for row in rows]
    ordered = sorted((i for i, row in enumerate(rows) if row["tokens"]), key=lambda i: len(rows[i]["tokens"]))
    selected = [ordered[0], ordered[len(ordered)//2], ordered[-1]]
    measurements = []
    # Warm-up is excluded; measurements include per-message tokenization.
    predict(model, [rows[selected[1]]], [features[selected[1]]], args.device, args.threshold)
    for label, i in zip(("short", "median", "long"), selected):
        timings = []
        for _ in range(5):
            if args.device == "cuda": torch.cuda.synchronize()
            started = time.perf_counter()
            fs = encode_features(rows[i], tokenizer, config["max_length"], config["stride"])
            predict(model, [rows[i]], [fs], args.device, args.threshold)
            if args.device == "cuda": torch.cuda.synchronize()
            timings.append(time.perf_counter() - started)
        measurements.append({"length_group": label, "source_words": len(rows[i]["tokens"]),
                             "windows": len(features[i]), "latency_seconds": timings,
                             "median_seconds": statistics.median(timings)})
    batch_indices = [ordered[int((len(ordered)-1)*fraction/7)] for fraction in range(8)]
    started = time.perf_counter()
    batch = [rows[i] for i in batch_indices]
    batch_features = [encode_features(row, tokenizer, config["max_length"], config["stride"]) for row in batch]
    predict(model, batch, batch_features, args.device, args.threshold, batch_size=8)
    if args.device == "cuda": torch.cuda.synchronize()
    batch_seconds = time.perf_counter() - started
    result = {"schema_version": 1, "device": args.device, "platform": platform.platform(),
              "processor": platform.processor(), "torch_cpu_threads": torch.get_num_threads(),
              "torch_version": torch.__version__, "cuda_device": torch.cuda.get_device_name(0) if args.device == "cuda" else None,
              "cold_model_load_seconds": load_seconds, "process_import_plus_ready_seconds": process_ready_seconds,
              "cold_load_policy": "fresh process; OS filesystem cache not flushed",
              "weight_bytes": (Path(args.checkpoint)/"model.pt").stat().st_size,
              "parameter_count": sum(p.numel() for p in model.parameters()),
              "weight_sha256": sha256(Path(args.checkpoint)/"model.pt"), "dev_sha256": sha256(args.input),
              "single_email": measurements, "batch_emails": len(batch), "batch_seconds": batch_seconds,
              "batch_emails_per_second": len(batch)/batch_seconds,
              "window_wordpiece_limit": config["max_length"], "window_stride": config["stride"],
              "dev_multiple_window_messages": sum(len(f or []) > 1 for f in features),
              "dev_messages": len(rows), "dev_max_windows": max(len(f or []) for f in features),
              "dev_max_source_words": max(len(r["tokens"]) for r in rows),
              "silently_truncated_messages": 0, "coverage_policy": "encode_features asserts every nonempty source word represented",
              "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated() if args.device == "cuda" else None,
              **memory_info()}
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()

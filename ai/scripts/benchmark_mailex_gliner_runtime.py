"""Measure frozen GLiNER2.5 full-pipeline latency on safe DEV only.

Writes aggregate timings only: no message text, IDs, predictions, or sampled
row indices are saved. Each timed message runs every TRAIN-derived schema pack
and the production windowing/overlap merge path.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import platform
import statistics
import sys
import time
from pathlib import Path

PROCESS_STARTED = time.perf_counter()

import torch

ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = ROOT / "ai"
sys.path.insert(0, str(AI_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mailex_extraction.gliner_backend import (  # noqa: E402
    CHECKPOINT_DIR,
    DATA_DIR,
    DEV_SHA256,
    TRAIN_SHA256,
    derive_ontology,
    iter_jsonl,
    load_extractor,
    prediction_row,
    sha256_file,
    verify_sha256,
)
from mailex_extraction.compact import canonical_rows  # noqa: E402
from run_mailex_gliner import MAX_ENCODER_POSITIONS, _infer_one_group, _pack_event_types  # noqa: E402


def memory_info() -> dict[str, int | None]:
    if platform.system() != "Windows":
        return {"peak_process_ram_bytes": None, "current_process_ram_bytes": None}

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            *[(name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage",
            )],
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    ok = psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return {
        "peak_process_ram_bytes": int(counters.PeakWorkingSetSize) if ok else None,
        "current_process_ram_bytes": int(counters.WorkingSetSize) if ok else None,
    }


def infer_native_row(
    model, packs, row, ontology, threshold: float
) -> tuple[int, int, dict[str, int]]:
    """Run the production schema passes and construct/ground a native row.

    Prediction rows are intentionally discarded after conversion. This makes
    the timing include field-to-role mapping and strict source-offset checks,
    while this benchmark still writes aggregate metadata only.
    """
    text = str(row.get("text", ""))
    windows = 0
    max_subwords = 0
    combined_output = {}
    for event_types, schema, _schema_subwords in packs:
        output, chunk_count, encoded_max, _chunks = _infer_one_group(
            model, text, schema, event_types, threshold
        )
        combined_output.update(output)
        windows += chunk_count
        max_subwords = max(max_subwords, encoded_max)
    _native_row, conversion_diagnostics = prediction_row(row, combined_output, ontology)
    return windows, max_subwords, conversion_diagnostics


def timed_infer(
    model, packs, row, ontology, threshold: float, device: str
) -> tuple[float, int, int, dict[str, int]]:
    if device == "cuda":
        torch.cuda.synchronize()
    started = time.perf_counter()
    windows, max_subwords, diagnostics = infer_native_row(
        model, packs, row, ontology, threshold
    )
    if device == "cuda":
        torch.cuda.synchronize()
    return time.perf_counter() - started, windows, max_subwords, diagnostics


def add_diagnostics(target: dict[str, int], values: dict[str, int]) -> None:
    for key, value in values.items():
        target[key] = target.get(key, 0) + value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--output", required=True, help="Aggregate JSON output path")
    parser.add_argument(
        "--checkpoint", type=Path, default=CHECKPOINT_DIR,
        help="Local model checkpoint directory (defaults to the pinned base model)",
    )
    parser.add_argument(
        "--model-label", default=None,
        help="Source-free label for the selected checkpoint in the aggregate output",
    )
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    if args.repetitions < 1 or args.batch_size != 8:
        raise ValueError("Use at least one repetition and batch size 8")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    checkpoint = args.checkpoint.resolve(strict=True)

    train_path = DATA_DIR / "train_fyp_safe.jsonl"
    dev_path = DATA_DIR / "dev_fyp_safe.jsonl"
    verify_sha256(train_path, TRAIN_SHA256)
    verify_sha256(dev_path, DEV_SHA256)
    rows = canonical_rows(list(iter_jsonl(dev_path)))
    nonempty = [(index, len(row["tokens"])) for index, row in enumerate(rows) if row["tokens"]]
    ordered = sorted(nonempty, key=lambda item: item[1])
    if len(ordered) < args.batch_size:
        raise ValueError("Safe DEV has too few nonempty messages for batch 8")

    # Match benchmark_mailex_compact_runtime.py exactly: minimum, median, and
    # maximum nonempty rows, plus eight evenly spaced rows from that same
    # ordered list. Both runners consume the same frozen safe DEV JSONL.
    selected_indices = [ordered[0], ordered[len(ordered) // 2], ordered[-1]]
    selected = [(name, *item) for name, item in zip(("short", "median", "long"), selected_indices)]
    batch_selected = [ordered[int((len(ordered) - 1) * index / 7)] for index in range(args.batch_size)]

    load_started = time.perf_counter()
    model = load_extractor(device=args.device, checkpoint=checkpoint)
    load_seconds = time.perf_counter() - load_started
    model_loaded_seconds = time.perf_counter() - PROCESS_STARTED
    if args.device == "cuda":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    ontology = derive_ontology(train_path, verify_fingerprint=False)
    schema_started = time.perf_counter()
    packs = _pack_event_types(model, ontology)
    schema_prepare_seconds = time.perf_counter() - schema_started
    if len(packs) != 7:
        raise RuntimeError(f"Expected 7 production schema packs, found {len(packs)}")
    schemas_ready_seconds = time.perf_counter() - PROCESS_STARTED

    # One complete p50 pass warms model kernels/caches and is excluded.
    timed_infer(model, packs, rows[selected[1][1]], ontology, args.threshold, args.device)
    single = []
    for group_name, row_index, source_words in selected:
        repetitions = []
        total_windows = 0
        max_subwords = 0
        conversion_diagnostics = {}
        for _ in range(args.repetitions):
            seconds, windows, encoded_max, row_diagnostics = timed_infer(
                model, packs, rows[row_index], ontology, args.threshold, args.device
            )
            repetitions.append(seconds)
            total_windows = windows
            max_subwords = max(max_subwords, encoded_max)
            conversion_diagnostics = row_diagnostics
        single.append({
            "length_group": group_name,
            "source_word_count": source_words,
            "repetitions_seconds": repetitions,
            "median_seconds": statistics.median(repetitions),
            "schema_packs": len(packs),
            "windows_across_schema_packs": total_windows,
            "max_encoder_subwords": max_subwords,
            "native_conversion_diagnostics": conversion_diagnostics,
        })

    batch_seconds_samples = []
    batch_windows = []
    batch_conversion_diagnostics = {}
    for _ in range(args.repetitions):
        if args.device == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        windows = 0
        conversion_diagnostics = {}
        for row_index, _word_count in batch_selected:
            row_windows, _max_subwords, row_diagnostics = infer_native_row(
                model, packs, rows[row_index], ontology, args.threshold
            )
            windows += row_windows
            add_diagnostics(conversion_diagnostics, row_diagnostics)
        if args.device == "cuda":
            torch.cuda.synchronize()
        batch_seconds_samples.append(time.perf_counter() - started)
        batch_windows.append(windows)
        batch_conversion_diagnostics = conversion_diagnostics
    batch_median = statistics.median(batch_seconds_samples)
    weights_path = checkpoint / "model.safetensors"
    if not weights_path.is_file():
        raise FileNotFoundError(f"checkpoint has no model.safetensors: {checkpoint}")
    result = {
        "schema_version": 2,
        "model": "fastino/gliner2.5-small-v1",
        "model_label": args.model_label or checkpoint.name,
        "revision": "7132dc4561c3f94563c6147e75ffa8ef34c4964a",
        "device": args.device,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "torch_version": str(torch.__version__),
        "torch_cpu_threads": torch.get_num_threads(),
        "cuda_device": torch.cuda.get_device_name(0) if args.device == "cuda" else None,
        "safe_dev_sha256": sha256_file(dev_path),
        "safe_train_sha256": sha256_file(train_path),
        "weight_sha256": sha256_file(weights_path),
        "weight_bytes": weights_path.stat().st_size,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "cold_model_load_seconds": load_seconds,
        "process_start_to_model_loaded_seconds": model_loaded_seconds,
        "process_start_to_schemas_ready_seconds": schemas_ready_seconds,
        "schema_prepare_seconds": schema_prepare_seconds,
        "schema_pack_count": len(packs),
        "native_prediction_row_conversion_included": True,
        "prediction_rows_retained": False,
        "timing_includes": "per-message schema-specific window building, all 7 schema passes, model extraction, overlap record merge, native event/argument mapping, and strict source-offset grounding checks",
        "warmup_policy": "one excluded full median inference pass; filesystem cache not flushed",
        "threshold": args.threshold,
        "single_email": single,
        "batch_size": args.batch_size,
        "batch_seconds_samples": batch_seconds_samples,
        "batch_median_seconds": batch_median,
        "batch_emails_per_second": args.batch_size / batch_median,
        "batch_window_counts": batch_windows,
        "batch_native_conversion_diagnostics": batch_conversion_diagnostics,
        "batch_word_count_min": min(word_count for _, word_count in batch_selected),
        "batch_word_count_max": max(word_count for _, word_count in batch_selected),
        "sample_selection": "same min/median/max and evenly spaced batch-eight indices as the compact benchmark over canonical safe DEV rows",
        "encoder_position_limit": MAX_ENCODER_POSITIONS,
        "silently_truncated_messages": 0,
        "peak_cuda_allocated_bytes": int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else None,
        **memory_info(),
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()

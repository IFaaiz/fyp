"""Export source-free, matched runtime summaries for the final MailEx candidates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = ROOT / "ai"
EXPERIMENT_DIR = AI_ROOT / "data" / "experiments" / "mailex_extraction_v1"
PRIVATE_RUNTIME = EXPERIMENT_DIR / "runtime"
REPORT_DIR = AI_ROOT / "reports"
REPORTS = REPORT_DIR / "mailex_extraction_results"
DEV_SHA256 = "fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d"

# Retained from the earlier aggregate-only report. These are actual historical
# measurements; GLiNER's older timer excludes native prediction conversion.
HISTORICAL_MEASUREMENTS: dict[str, Any] = {
    "compact_categorical_seed17": {
        "parameter_count": 66601862,
        "weight_bytes": 266443579,
        "cpu": {
            "cold_model_load_seconds": 1.0879718,
            "short_median_seconds": 0.0158776,
            "median_median_seconds": 0.0362609,
            "long_median_seconds": 0.6075234,
            "batch_seconds": 2.0466415,
            "batch_emails_per_second": 3.9088429,
            "peak_process_ram_bytes": 1412337664,
        },
        "cuda_rtx_5070": {
            "cold_model_load_seconds": 1.3402332,
            "short_median_seconds": 0.0079504,
            "median_median_seconds": 0.0129814,
            "long_median_seconds": 0.0785509,
            "batch_seconds": 0.1481371,
            "batch_emails_per_second": 54.0040274,
            "peak_process_ram_bytes": 1900933120,
            "peak_cuda_allocated_bytes": 427107328,
        },
    },
    "gliner2_5_small_zero_shot": {
        "revision": "7132dc4561c3f94563c6147e75ffa8ef34c4964a",
        "weight_sha256": "4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b",
        "parameter_count": 73881879,
        "weight_bytes": 295567700,
        "cpu": {
            "cold_model_load_seconds": 6.7933692,
            "process_start_to_result_serialization_seconds": 69.1590027,
            "short_median_seconds": 0.9249908,
            "median_median_seconds": 1.1301228,
            "long_median_seconds": 8.58315755,
            "batch_median_seconds": 16.2594756,
            "batch_emails_per_second": 0.4920208,
            "peak_process_ram_bytes": 1467899904,
            "timing_scope": "historical; excludes native prediction-row conversion and grounding",
        },
        "cuda_rtx_5070": {
            "status": "not_measured",
            "reason": "GPU time was reserved for the final selected checkpoint.",
        },
    },
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload


def compact_summary(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if raw.get("dev_sha256") != DEV_SHA256 or raw.get("dev_messages") != 361:
        raise ValueError(f"unexpected compact runtime DEV fingerprint: {path.name}")
    return {
        "device": raw["device"],
        "cuda_device": raw.get("cuda_device"),
        "cold_model_load_seconds": raw["cold_model_load_seconds"],
        "process_import_plus_ready_seconds": raw["process_import_plus_ready_seconds"],
        "cold_load_policy": raw["cold_load_policy"],
        "warmup_policy": "one median-message predict call before timing; verified from benchmark_mailex_compact_runtime.py",
        "batch_execution": "encoder windows batched; event decoding runs per message; verified from compact.py",
        "runtime_grounding_counter_recorded": False,
        "weight_sha256": raw["weight_sha256"],
        "weight_bytes": raw["weight_bytes"],
        "parameter_count": raw["parameter_count"],
        "single_email": [
            {
                "length_group": row["length_group"],
                "source_words": row["source_words"],
                "windows": row["windows"],
                "repetitions_seconds": row["latency_seconds"],
                "median_seconds": row["median_seconds"],
            }
            for row in raw["single_email"]
        ],
        "batch_size": raw["batch_emails"],
        "batch_seconds": raw["batch_seconds"],
        "batch_emails_per_second": raw["batch_emails_per_second"],
        "dev_messages": raw["dev_messages"],
        "dev_max_source_words": raw["dev_max_source_words"],
        "silently_truncated_messages": raw["silently_truncated_messages"],
        "peak_cuda_allocated_bytes": raw["peak_cuda_allocated_bytes"],
        "peak_process_ram_bytes": raw["peak_process_ram_bytes"],
        "peak_process_commit_bytes": raw["peak_process_commit_bytes"],
    }


def gliner_summary(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if raw.get("safe_dev_sha256") != DEV_SHA256 or raw.get("device") not in ("cpu", "cuda"):
        raise ValueError(f"unexpected GLiNER runtime DEV fingerprint: {path.name}")
    keys = (
        "model", "model_label", "revision", "device", "platform", "processor",
        "torch_version", "torch_cpu_threads", "cuda_device", "safe_dev_sha256",
        "safe_train_sha256", "weight_sha256", "weight_bytes", "parameter_count",
        "cold_model_load_seconds", "process_start_to_model_loaded_seconds",
        "process_start_to_schemas_ready_seconds", "schema_prepare_seconds",
        "schema_pack_count", "native_prediction_row_conversion_included",
        "prediction_rows_retained", "timing_includes", "warmup_policy", "threshold",
        "single_email", "batch_size", "batch_seconds_samples", "batch_median_seconds",
        "batch_emails_per_second", "batch_window_counts",
        "batch_native_conversion_diagnostics", "batch_word_count_min",
        "batch_word_count_max", "sample_selection", "encoder_position_limit",
        "silently_truncated_messages", "peak_cuda_allocated_bytes",
        "peak_process_ram_bytes", "current_process_ram_bytes",
    )
    return {key: raw[key] for key in keys}


def _timing_row(label: str, metrics: dict[str, Any], device_key: str) -> list[str]:
    device = metrics[device_key]
    points = {row["length_group"]: row for row in device["single_email"]}
    return [
        f"{label}, " + ("CPU" if device["device"] == "cpu" else device.get("cuda_device", "CUDA")),
        f"{device['cold_model_load_seconds']:.3f} s",
        f"{points['short']['median_seconds'] * 1000:.1f} ms",
        f"{points['median']['median_seconds'] * 1000:.1f} ms",
        f"{points['long']['median_seconds']:.3f} s",
        f"{device['batch_median_seconds']:.3f} s",
        f"{device['batch_emails_per_second']:.2f}",
    ]


def _compact_timing_row(label: str, metrics: dict[str, Any]) -> list[str]:
    points = {row["length_group"]: row for row in metrics["single_email"]}
    return [
        f"{label}, " + ("CPU" if metrics["device"] == "cpu" else metrics.get("cuda_device", "CUDA")),
        f"{metrics['cold_model_load_seconds']:.3f} s",
        f"{points['short']['median_seconds'] * 1000:.1f} ms",
        f"{points['median']['median_seconds'] * 1000:.1f} ms",
        f"{points['long']['median_seconds']:.3f} s",
        f"{metrics['batch_seconds']:.3f} s",
        f"{metrics['batch_emails_per_second']:.2f}",
    ]


def write_report() -> None:
    prior_report = read_json(REPORT_DIR / "mailex_extraction_runtime.json")
    historical_measurements = (
        prior_report.get("historical_measurements")
        or prior_report.get("models")
        or HISTORICAL_MEASUREMENTS
    )
    compact_cpu = compact_summary(REPORTS / "compact_selected_cpu_runtime.json")
    compact_cuda = compact_summary(REPORTS / "compact_selected_cuda_runtime.json")
    gliner_cpu = gliner_summary(PRIVATE_RUNTIME / "final_gliner_seed42_best_record_020_cpu.json")
    gliner_cuda = gliner_summary(PRIVATE_RUNTIME / "final_gliner_seed42_best_record_020_cuda.json")

    result = {
        "schema_version": 2,
        "split": "fyp_safe_dev",
        "safe_dev_sha256": DEV_SHA256,
        "messages": 361,
        "test_rows_read": False,
        "source_text_or_message_ids_included": False,
        "absolute_checkpoint_paths_included": False,
        "final_runtime_candidates": {
            "compact_categorical_seed23_threshold_0.7": {
                "selection_status": "selected compact checkpoint",
                "weight_sha256": compact_cpu["weight_sha256"],
                "weight_bytes": compact_cpu["weight_bytes"],
                "parameter_count": compact_cpu["parameter_count"],
                "sample_selection": "same canonical safe DEV minimum, median, maximum, and batch-eight messages as GLiNER",
                "cpu": compact_cpu,
                "cuda_rtx_5070": compact_cuda,
            },
            "gliner2_5_small_seed42_best_threshold_0.2": {
                "selection_status": "fine-tuned GLiNER runtime candidate",
                "weight_sha256": gliner_cpu["weight_sha256"],
                "weight_bytes": gliner_cpu["weight_bytes"],
                "parameter_count": gliner_cpu["parameter_count"],
                "threshold": 0.2,
                "schema_pack_count": 7,
                "sample_selection": gliner_cpu["sample_selection"],
                "cpu": gliner_cpu,
                "cuda_rtx_5070": gliner_cuda,
            },
        },
        "historical_measurements": historical_measurements,
        "measurement_notes": {
            "final_compact_device_outputs_share_selected_weight_hash": (
                compact_cpu["weight_sha256"] == compact_cuda["weight_sha256"]
            ),
            "final_gliner_device_outputs_share_selected_weight_hash": (
                gliner_cpu["weight_sha256"] == gliner_cuda["weight_sha256"]
            ),
            "all_four_final_measurements_use_same_safe_dev_split": True,
            "gliner_timing_includes_native_record_conversion_and_source_offset_validation": True,
            "gliner_prediction_rows_retained": False,
            "batch8_execution": {
                "compact": "encoder windows batched; event decoding per message",
                "gliner": "sequential message inference through the seven-schema path",
            },
            "filesystem_cache_flushed": False,
        },
    }
    json_path = REPORT_DIR / "mailex_extraction_runtime.json"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    table_rows = [
        ["Compact categorical seed23", compact_cpu],
        ["Compact categorical seed23", compact_cuda],
    ]
    markdown = [
        "# MailEx extractor runtime measurements",
        "",
        "## Final runtime candidates",
        "",
        "These are measured fresh-process inference timings on the FYP-safe DEV split only.",
        "Both models use the same 1-, 39-, and 721-word messages and same evenly spaced",
        "eight-message cohort. The compact model uses its selected seed23 checkpoint at",
        "threshold 0.7. GLiNER uses its best seed42 fine-tuned checkpoint at threshold 0.2.",
        "No TEST rows were read. Public results contain aggregate timings and source-grounding",
        "diagnostic counts only; no text, IDs, predictions, or checkpoint paths are included.",
        "",
        "| Model and device | Cold model load | 1-word message | 39-word message | 721-word message | Batch 8 | Emails/s |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, metrics in table_rows:
        markdown.append("| " + " | ".join(_compact_timing_row(label, metrics)) + " |")
    markdown.append("| " + " | ".join(_timing_row(
        "GLiNER fine-tuned seed42 best", {"cpu": gliner_cpu}, "cpu"
    )) + " |")
    markdown.append("| " + " | ".join(_timing_row(
        "GLiNER fine-tuned seed42 best", {"cuda": gliner_cuda}, "cuda"
    )) + " |")

    markdown.extend([
        "",
        "GLiNER timing includes all seven TRAIN-derived schema passes, per-message window",
        "selection, extraction, overlap merge, native event/argument mapping, and strict",
        "source-offset grounding diagnostics. Its longest message spans 31 windows across",
        "the seven packs; the batch-eight run spans 80 windows. The measured sample had zero",
        "ungrounded prediction segments and zero messages silently truncated. Batch-eight",
        "inference is sequential through the current production API, not parallel batching.",
        "Compact batches encoder windows, then decodes events per message. Its benchmark",
        "excludes one warm-up call; these scope details are verified from the benchmark",
        "and compact encoder code. Its runtime runner does not record a grounding counter.",
        "",
        "The selected compact checkpoint has 66,601,862 parameters and 266,443,579 weight",
        "bytes. The fine-tuned GLiNER checkpoint has 73,881,879 parameters and 295,567,700",
        "weight bytes. The machine-readable JSON includes per-device repeated timings,",
        "startup/readiness boundaries, window counts, memory peaks, and aggregate grounding",
        "diagnostics. It contains no absolute checkpoint path.",
        "",
        "## Historical baseline measurements",
        "",
        "The earlier seed17 compact and zero-shot GLiNER CPU results are retained below as",
        "historical measurements. Their GLiNER timer predates the native event/argument",
        "mapping and grounding addition, so it is not directly equivalent to the final",
        "fine-tuned GLiNER timings above. Its old 69.159-second process duration was sampled",
        "after inference while serializing the report; it was not model readiness time.",
        "",
        "| Historical model and device | Cold model load | Short | Median | Long | Batch 8 | Emails/s |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    historical = historical_measurements
    for model_key, label in (
        ("compact_categorical_seed17", "Compact categorical seed17"),
        ("gliner2_5_small_zero_shot", "GLiNER2.5 Small zero-shot"),
    ):
        model = historical.get(model_key)
        if not model:
            continue
        for device_key, device_label in (("cpu", "CPU"), ("cuda_rtx_5070", "RTX 5070")):
            device = model.get(device_key)
            if not device or device.get("status") == "not_measured":
                continue
            median_load = device.get("cold_model_load_seconds")
            short = device.get("short_median_seconds")
            middle = device.get("median_median_seconds")
            long = device.get("long_median_seconds")
            batch = device.get("batch_seconds", device.get("batch_median_seconds"))
            rate = device.get("batch_emails_per_second")
            markdown.append(
                f"| {label}, {device_label} | {median_load:.3f} s | "
                f"{short * 1000:.1f} ms | {middle * 1000:.1f} ms | "
                f"{long:.3f} s | {batch:.3f} s | {rate:.2f} |"
            )
    markdown.extend([
        "",
        "The earlier pretrained GLiNER Small GPU timing remains not measured. Historical measurements",
        "also use the same message lengths, but the pretrained Small CPU record excludes native",
        "conversion and must be treated as a narrower timing scope.",
        "",
        "Machine-readable aggregates: [`mailex_extraction_runtime.json`](mailex_extraction_runtime.json).",
        "",
    ])
    markdown_path = REPORT_DIR / "mailex_extraction_runtime.md"
    markdown_path.write_text("\n".join(markdown), encoding="utf-8")
    print(json.dumps({
        "json": json_path.name,
        "markdown": markdown_path.name,
        "compact_weight_sha256": compact_cpu["weight_sha256"],
        "gliner_weight_sha256": gliner_cpu["weight_sha256"],
        "safe_dev_sha256": DEV_SHA256,
        "no_source_rows_exported": True,
    }, indent=2))


if __name__ == "__main__":
    write_report()

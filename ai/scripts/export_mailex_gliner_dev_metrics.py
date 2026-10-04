"""Export safe-DEV GLiNER aggregate metrics without private row data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = ROOT / "ai"
EXPERIMENT_DIR = AI_ROOT / "data" / "experiments" / "mailex_extraction_v1"
PRIVATE_DIR = EXPERIMENT_DIR / "private_dev_audit"
PREDICTION_DIR = EXPERIMENT_DIR / "predictions"
REPORT_DIR = AI_ROOT / "reports"
DEV_SHA256 = "fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d"

THRESHOLDS = {
    "0.20": (
        "gliner_seed42_independent_dev_020.metrics.json",
        "gliner_small_seed42_batch4_best_dev_record_threshold_020.jsonl",
    ),
    "0.50": (
        "gliner_seed42_independent_dev_050.metrics.json",
        "gliner_small_seed42_batch4_best_dev_record_threshold_050.jsonl",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_metrics(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("split") != "dev":
        raise ValueError(f"expected safe DEV metrics in {path.name}")
    return payload


def build_report() -> dict[str, Any]:
    results: dict[str, Any] = {}
    message_count: int | None = None
    gold_event_count: int | None = None
    for threshold, (metrics_name, prediction_name) in THRESHOLDS.items():
        metrics_path = PRIVATE_DIR / metrics_name
        prediction_path = PREDICTION_DIR / prediction_name
        before = _sha256(prediction_path)
        metrics = _read_metrics(metrics_path)
        after = _sha256(prediction_path)
        if before != after:
            raise RuntimeError(f"prediction changed during export: {prediction_path.name}")

        role_exact = metrics["argument_records"]["role_exact"]["micro"]
        role_partial = metrics["argument_records"]["role_partial"]["micro"]
        events = metrics["events"]
        args = metrics["argument_records"]
        triggers = metrics["triggers"]
        current_message_count = int(metrics["messages"]["evaluated_union"])
        current_gold_event_count = int(events["gold"])
        if message_count is None:
            message_count = current_message_count
            gold_event_count = current_gold_event_count
        elif (current_message_count, current_gold_event_count) != (
            message_count, gold_event_count
        ):
            raise ValueError("threshold artifacts do not cover the same safe DEV set")
        results[threshold] = {
            "predicted_events": events["predicted"],
            "predicted_argument_spans": args["predicted"],
            "event_type_micro_f1": events["type_identification"]["micro"]["f1"],
            "event_record_exact_f1": events["record_exact"]["f1"],
            "event_record_partial_f1": events["record_partial"]["f1"],
            "argument_role_exact_micro_f1": role_exact["f1"],
            "argument_role_partial_micro_f1": role_partial["f1"],
            "argument_span_exact_f1": args["span_exact"]["f1"],
            "argument_span_overlap_f1": args["span_overlap"]["f1"],
            "trigger_exact_f1": triggers["exact"]["f1"],
            "trigger_partial_f1": triggers["partial"]["f1"],
            "empty_prediction_rate": metrics["messages"]["empty_prediction_rate"],
            "non_source_prediction_segments": metrics["source_validation"][
                "non_source_prediction_segments"
            ],
            "prediction_sha256": before,
        }

    return {
        "schema_version": 1,
        "split": "fyp_safe_dev",
        "safe_dev_sha256": DEV_SHA256,
        "messages": message_count,
        "gold_events": gold_event_count,
        "model": "GLiNER2.5 Small fine-tuned, best epoch 3",
        "thresholds": results,
        "independent_scoring": {
            "evaluator": "native MailEx message-level evaluator",
            "prediction_hashes_stable_during_export": True,
            "test_rows_read": False,
            "export_contains_source_text_or_message_ids": False,
            "absolute_checkpoint_path_included": False,
        },
    }


def write_report() -> None:
    report = build_report()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "mailex_extraction_gliner_dev_metrics.json"
    markdown_path = REPORT_DIR / "mailex_extraction_gliner_dev_metrics.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# GLiNER MailEx safe DEV metrics",
        "",
        "These scores are from the frozen FYP-safe DEV view only: 361 messages and 828",
        "gold event records. The native MailEx evaluator independently rescored both",
        "prediction files. Their SHA-256 values were stable during this export. No TEST",
        "rows were read. This report contains aggregate counts only, without message text,",
        "identifiers, or local checkpoint paths.",
        "",
        "| Confidence threshold | Predicted events | Predicted argument spans | Type F1 | Exact record F1 | Partial record F1 | Role exact F1 | Role partial F1 | Trigger exact F1 | Trigger partial F1 | Empty-message rate |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for threshold, values in report["thresholds"].items():
        lines.append(
            "| {threshold} | {predicted_events:,} | {predicted_argument_spans:,} | "
            "{event_type_micro_f1:.4f} | {event_record_exact_f1:.4f} | "
            "{event_record_partial_f1:.4f} | {argument_role_exact_micro_f1:.4f} | "
            "{argument_role_partial_micro_f1:.4f} | {trigger_exact_f1:.4f} | "
            "{trigger_partial_f1:.4f} | {empty_prediction_rate:.4f} |".format(
                threshold=threshold, **values
            )
        )
    lines.extend([
        "",
        "Threshold 0.20 predicts more records and arguments, with higher partial record",
        "and role scores. Threshold 0.50 has higher event-type and trigger scores. All",
        "prediction segments passed source-offset validation at both thresholds.",
        "These are DEV threshold diagnostics; they do not use TEST or imply final model",
        "selection.",
        "",
        "Aggregate values are also available in",
        "[`mailex_extraction_gliner_dev_metrics.json`](mailex_extraction_gliner_dev_metrics.json).",
        "",
    ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": json_path.name, "markdown": markdown_path.name,
                      "thresholds": list(report["thresholds"]), "messages": report["messages"]},
                     indent=2))


if __name__ == "__main__":
    write_report()

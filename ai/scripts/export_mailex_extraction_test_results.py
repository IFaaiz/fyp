"""Export completed one-time TEST receipts without reopening or rescoring examples."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "ai/config/mailex_extraction_selection_lock.json"
PRIVATE = ROOT / "ai/data/experiments/mailex_extraction_v1/private_test"
PUBLIC = ROOT / "ai/reports/mailex_extraction_results"
SCORE_KEYS = {"schema_version", "split", "messages", "events", "triggers",
              "argument_records", "source_validation", "matching"}
RECEIPT_KEYS = {"schema_version", "status", "run_id", "selection_lock_sha256",
                "gold_sha256", "predictions_sha256", "metrics"}
STRING_KEYS = {"definition", "gold_policy", "prediction_policy", "offset_convention",
               "diagnostic_event_assignment", "primary_record_assignment", "span_overlap",
               "text_recovery", "trigger_assignment"}
EVENT_TYPES = {"Amend_Action_Data", "Amend_Data", "Amend_Meeting_Data",
               "Deliver_Action_Data", "Deliver_Data", "Deliver_Meeting_Data",
               "Request_Action", "Request_Action_Data", "Request_Data",
               "Request_Meeting", "Request_Meeting_Data"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_metrics(value, key=""):
    """Only numerical aggregates, fixed evaluator descriptions and ontology values."""
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key in {"text", "email_id", "message_id", "thread_id", "source_text",
                             "body", "content", "predictions", "segments", "start", "end"}:
                raise ValueError(f"Source-bearing metric key: {child_key}")
            check_metrics(child, child_key)
    elif isinstance(value, list):
        for child in value:
            check_metrics(child, key)
    elif isinstance(value, str):
        if key == "split" and value == "test":
            return
        if key in {"gold", "predicted", "not_applicable_event_types"} and value in EVENT_TYPES:
            return
        if key not in STRING_KEYS or "@" in value or "E:\\" in value or "C:\\" in value:
            raise ValueError(f"Unexpected string metric field: {key}")
    elif value is not None and not isinstance(value, (int, float, bool)):
        raise ValueError(f"Unexpected metric value: {key}")


def main():
    committed = subprocess.check_output(
        ["git", "show", "f6b4bde:ai/config/mailex_extraction_selection_lock.json"], cwd=ROOT)
    if committed != LOCK.read_bytes():
        raise ValueError("Selection lock differs from the pre-TEST commit")
    PUBLIC.mkdir(parents=True, exist_ok=True)
    exported = []
    for run_id in ("compact_selected", "gliner_small_selected"):
        receipt = json.loads((PRIVATE / f"{run_id}.receipt.json").read_text(encoding="utf-8"))
        metrics = json.loads((PRIVATE / f"{run_id}_metrics.json").read_text(encoding="utf-8"))
        if set(receipt) != RECEIPT_KEYS or set(metrics) != SCORE_KEYS:
            raise ValueError("Unexpected receipt/metric structure")
        if receipt["status"] != "complete" or receipt["run_id"] != run_id:
            raise ValueError("Receipt is incomplete or belongs to another finalist")
        if receipt["metrics"] != metrics or metrics["split"] != "test":
            raise ValueError("Receipt does not match the saved one-time TEST scores")
        if receipt["selection_lock_sha256"] != digest(LOCK):
            raise ValueError("Receipt is not bound to the committed lock")
        gold = ROOT / "ai/data/experiments/mailex_extraction_v1/test_fyp_safe.jsonl"
        prediction = PRIVATE / f"{run_id}_predictions.jsonl"
        if receipt["gold_sha256"] != digest(gold) or receipt["predictions_sha256"] != digest(prediction):
            raise ValueError("Gold or prediction bytes changed after scoring")
        check_metrics(metrics)
        for suffix, value in (("metrics.json", metrics), ("receipt.json", receipt)):
            destination = PUBLIC / f"{run_id}_test.{suffix}"
            destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            exported.append(destination.name)
    print(json.dumps({"exported": exported, "rescoring_performed": False,
                      "source_rows_decoded": False, "pre_test_lock_commit": "f6b4bde"}))


if __name__ == "__main__":
    main()

"""Export selected transformer candidate probabilities and registry fields.

This exporter reads only the approved TRAIN/DEV partitions through their
hash-checking helper. It never opens or resolves the TEST partition.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

AI_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = AI_DIR.parent
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.models import optimization_benchmark as benchmark  # noqa: E402
from src.models.optimization_transformer import predict  # noqa: E402
from src.models.silver_classifier import LABEL_ORDER  # noqa: E402

EXPERIMENT_DIR = AI_DIR / "data/experiments/optimization_20261002"
RESULTS_DIR = EXPERIMENT_DIR / "transformer"
REPORT_PATH = AI_DIR / "reports/optimization_transformer.json"
MODEL_ROOT = AI_DIR / "data/models/optimization/transformer"
ROLES = ("capped5", "flat", "hierarchical")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    train = benchmark.load_partition("train")
    dev = benchmark.load_partition("dev")
    train_ids = [str(row["email_id"]) for row in train]
    dev_ids = [str(row["email_id"]) for row in dev]
    train_id_set, dev_id_set = set(train_ids), set(dev_ids)
    if len(train_id_set) != len(train_ids) or len(dev_id_set) != len(dev_ids):
        raise ValueError("benchmark helper returned duplicate frozen IDs")
    if train_id_set & dev_id_set:
        raise ValueError("TRAIN and DEV IDs are not disjoint")

    candidate_runs = {row["run_id"]: row for row in report.get("runs", [])}
    candidate_registry = report.get("train_oof_thresholds", {}).get("candidates", {})
    final_candidates = []
    for role in ROLES:
        if role not in candidate_registry:
            raise ValueError(f"missing grouped TRAIN OOF candidate: {role}")
        summary = candidate_registry[role]
        run = candidate_runs[summary["run_id"]]
        bundle = (REPO_DIR / summary["candidate_bundle"]).resolve()
        if not bundle.is_relative_to(MODEL_ROOT.resolve()) or not bundle.is_dir():
            raise ValueError(f"candidate bundle is missing or outside model root: {bundle}")
        metadata_path = bundle / "candidate.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("threshold_source") not in (None, "TRAIN only"):
            raise ValueError(f"candidate threshold source is not TRAIN only: {role}")
        thresholds = [float(summary["thresholds_by_label_order"][label]) for label in LABEL_ORDER]
        if len(thresholds) != len(LABEL_ORDER):
            raise ValueError(f"incorrect number of thresholds for {role}")

        # Re-index OOF output by immutable email_id, then write the exact
        # benchmark helper order so root can safely align it with other models.
        oof_source = RESULTS_DIR / f"train_oof_{role}.jsonl"
        oof_records = _read_jsonl(oof_source)
        oof_by_id = {str(row["email_id"]): row["probabilities"] for row in oof_records}
        if len(oof_by_id) != len(oof_records) or set(oof_by_id) != train_id_set:
            raise ValueError(f"TRAIN OOF IDs do not exactly match frozen TRAIN for {role}")
        train_probs = np.asarray([
            [float(oof_by_id[email_id][label]) for label in LABEL_ORDER]
            for email_id in train_ids
        ], dtype=np.float32)
        if train_probs.shape != (len(train), len(LABEL_ORDER)) or not np.isfinite(train_probs).all():
            raise ValueError(f"invalid TRAIN OOF probability matrix for {role}: {train_probs.shape}")

        # Warm local files/tokenizer caches once, then take the median of three
        # end-to-end calls. Each call includes model load, tokenization, and
        # forward pass, matching the public callable contract.
        predict(bundle, dev)
        inference_samples = []
        dev_probs = None
        for _ in range(3):
            started = time.perf_counter()
            dev_probs = np.asarray(predict(bundle, dev), dtype=np.float32)
            inference_samples.append(time.perf_counter() - started)
        inference_seconds = float(np.median(inference_samples))
        assert dev_probs is not None
        if dev_probs.shape != (len(dev), len(LABEL_ORDER)) or not np.isfinite(dev_probs).all():
            raise ValueError(f"invalid DEV prediction matrix for {role}: {dev_probs.shape}")
        recomputed_metrics = benchmark.score_probabilities(
            [row["labels"] for row in dev], dev_probs.tolist(),
            thresholds=thresholds, mode=summary["mode"], fallback=False,
        )
        recorded = summary["dev_metrics_train_oof_thresholds"]
        for metric in ("macro_f1", "micro_f1"):
            if not math.isclose(recomputed_metrics[metric], recorded[metric], abs_tol=1e-6):
                raise ValueError(f"saved bundle failed DEV {metric} reproduction for {role}")

        train_out = RESULTS_DIR / f"train_oof_probabilities_{role}.npy"
        dev_out = RESULTS_DIR / f"dev_probabilities_{role}.npy"
        np.save(train_out, train_probs, allow_pickle=False)
        np.save(dev_out, dev_probs, allow_pickle=False)
        order_path = RESULTS_DIR / f"probability_order_{role}.json"
        _write_json(order_path, {
            "label_order": list(LABEL_ORDER),
            "train_email_ids": train_ids,
            "dev_email_ids": dev_ids,
            "train_partition_sha256": report["data"]["train_sha256"],
            "dev_partition_sha256": report["data"]["dev_sha256"],
        })

        bundle_bytes = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
        hyper = run.get("hyperparameters", {})
        if summary["mode"] == "hierarchical":
            loss_description = "scope BCE for all rows + project-function BCE on PROJECT fit rows"
        elif hyper.get("imbalance") == "focal":
            loss_description = f"sigmoid focal loss (gamma={hyper.get('focal_gamma')})"
        else:
            loss_description = "binary cross-entropy with logits"
        final_candidates.append({
            "run_id": summary["run_id"],
            "model_path": str(bundle.relative_to(REPO_DIR)),
            "predictor": "src.models.optimization_transformer.predict(bundlepath, canonicalrows)",
            "mode": summary["mode"],
            "fallback": False,
            "thresholds": thresholds,
            "threshold_label_order": list(LABEL_ORDER),
            "threshold_method": "5-fold grouped TRAIN OOF binary F1; no DEV-tuned cutoffs used",
            "dev_metrics": recorded,
            "train_oof_probabilities_path": str(train_out.relative_to(REPO_DIR)),
            "dev_probabilities_path": str(dev_out.relative_to(REPO_DIR)),
            "probability_order_path": str(order_path.relative_to(REPO_DIR)),
            "model_size_bytes": bundle_bytes,
            "weights_size_bytes": summary["refit_reproduction_check"]["weights_size_bytes"],
            "inference_seconds_per_record": inference_seconds / max(1, len(dev)),
            "inference_seconds_total_for_dev_batch": inference_seconds,
            "inference_seconds_per_record_samples": [value / max(1, len(dev)) for value in inference_samples],
            "inference_device": "CUDA" if __import__("torch").cuda.is_available() else "CPU",
            "inference_measurement": "median of three warm-cache end-to-end callable invocations; each includes bundle load, tokenization, and forward pass",
            "hyperparameters": hyper,
            "loss": loss_description,
            "class_weighting": {
                "method": hyper.get("imbalance", "none"),
                "weight_cap": hyper.get("weight_cap"),
                "focal_gamma": hyper.get("focal_gamma"),
            },
            "training_seconds_dev_refit": run.get("training_seconds"),
            "selected_epoch": summary["selected_epoch"],
            "grouped_oof_fold_count": len(summary["oof_fold_metrics"]),
            "train_oof_records": len(train_ids),
            "dev_records": len(dev_ids),
            "test_opened": False,
        })

    report["final_candidates"] = final_candidates
    report["probability_alignment"] = {
        "matrix_shape": ["N", len(LABEL_ORDER)],
        "matrix_columns": list(LABEL_ORDER),
        "rows_ordered_by": "email_id sequence returned by optimization_benchmark.load_partition(train|dev)",
        "test_opened": False,
    }
    tmp = REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(REPORT_PATH)
    runs_report = RESULTS_DIR / "runs.json"
    runs_tmp = runs_report.with_suffix(runs_report.suffix + ".tmp")
    runs_tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    runs_tmp.replace(runs_report)
    print(json.dumps({
        "final_candidates": [
            {key: candidate[key] for key in (
                "run_id", "model_path", "mode", "dev_metrics", "model_size_bytes",
                "inference_seconds_per_record", "train_oof_probabilities_path", "dev_probabilities_path",
            )}
            for candidate in final_candidates
        ],
        "test_opened": False,
        "report": str(REPORT_PATH.relative_to(REPO_DIR)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluate cached long-email embedding representations without changing core bundles."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

AI_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = AI_DIR.parent
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.models.optimization_benchmark import LABEL_ORDER, benchmark_hash, cv_splits, load_partition, oof_thresholds, score_probabilities, targets
from src.models.optimization_embeddings import IndependentBinaryHead
from src.models.transfer_diagnostic import sha256_file

EXP = AI_DIR / "data/experiments/optimization_20261002/embeddings"
MODELS = AI_DIR / "data/models/optimization/embeddings"
REGISTRY_PATH = AI_DIR / "reports/optimization_embeddings.json"
FEATURES = ("minilm_subject_body_head_tail", "minilm_subject_body_two_chunks")
SEED = 20261004


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def git_revision() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, check=True, text=True, capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    started = time.perf_counter()
    train_rows = load_partition("train")
    dev_rows = load_partition("dev")
    feature_manifest = json.loads((EXP / "frozen_feature_manifest.json").read_text(encoding="utf-8"))
    matrices = np.load(EXP / "frozen_features.npz")
    helper_sha = sha256_file(AI_DIR / "src/models/optimization_embeddings.py")
    for key in FEATURES:
        if f"{key}__train" not in matrices.files or f"{key}__dev" not in matrices.files:
            raise FileNotFoundError(f"feature matrix is not cached: {key}")
        if feature_manifest["features"][key].get("encoder_implementation_sha256") != helper_sha:
            raise ValueError(f"feature cache is stale for updated encoder behavior: {key}")
    y_train, y_dev = targets(train_rows), targets(dev_rows)
    expected_train = [row["labels"] for row in train_rows]
    expected_dev = [row["labels"] for row in dev_rows]
    folds = cv_splits(train_rows)
    checkpoint_manifest = json.loads((AI_DIR / "data/cache/sentence-transformers/optimization_embedding_checkpoints.json").read_text(encoding="utf-8"))
    checkpoint = next(row for row in checkpoint_manifest if row["model_id"] == "sentence-transformers/all-MiniLM-L6-v2")
    encoder_dir = MODELS / "encoders/minilm"
    results = []
    oof_matrices: dict[str, list[list[float]]] = {}
    dev_matrices: dict[str, list[list[float]]] = {}

    for feature_key in FEATURES:
        run_id = f"{feature_key}_lr_c1"
        x_train = matrices[f"{feature_key}__train"].astype(np.float32, copy=False)
        x_dev = matrices[f"{feature_key}__dev"].astype(np.float32, copy=False)
        oof = np.zeros((len(train_rows), 9), dtype=np.float64)
        oof_started = time.perf_counter()
        for fold_number, (fit_indices, held_indices) in enumerate(folds, 1):
            head = IndependentBinaryHead({"method": "logistic", "C": 1.0, "weighting": "none", "seed": SEED + fold_number})
            head.fit(x_train[fit_indices], y_train[fit_indices])
            oof[held_indices] = head.predict_proba(x_train[held_indices])
        thresholds, threshold_report = oof_thresholds(expected_train, oof, mode="flat")
        oof_seconds = time.perf_counter() - oof_started
        final_head = IndependentBinaryHead({"method": "logistic", "C": 1.0, "weighting": "none", "seed": SEED})
        fit_started = time.perf_counter()
        final_head.fit(x_train, y_train)
        dev_started = time.perf_counter()
        dev_probs = final_head.predict_proba(x_dev)
        dev_seconds = time.perf_counter() - dev_started
        training_seconds = time.perf_counter() - fit_started - dev_seconds
        metrics = score_probabilities(expected_dev, dev_probs, thresholds, mode="flat")

        candidate_path = MODELS / "candidates" / f"{run_id}.joblib"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(final_head, candidate_path, compress=3)
        bundle_path = MODELS / "bundles" / run_id
        bundle_path.mkdir(parents=True, exist_ok=True)
        bundle_head = bundle_path / "heads.joblib"
        joblib.dump(final_head, bundle_head, compress=3)
        bundle = {
            "scope": "AI-SILVER DIAGNOSTIC PERFORMANCE; not human/gold/production accuracy",
            "bundle_type": "single",
            "model_family": "frozen MiniLM + logistic heads",
            "prediction_mode": "flat",
            "fallback": False,
            "encoder_path": "../../encoders/minilm",
            "text_view": "subject_body",
            "sequence_mode": "head_tail" if "head_tail" in feature_key else "two_chunks",
            "thresholds_train_oof_only": {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
            "dev_metrics": metrics,
            "checkpoint_id": checkpoint["model_id"],
            "checkpoint_revision": checkpoint["revision"],
            "checkpoint_files_sha256": checkpoint["files"],
            "head_sha256": sha256_file(bundle_head),
            "benchmark_sha256": benchmark_hash(),
        }
        write_json(bundle_path / "bundle.json", bundle)
        encoder_bytes = int(checkpoint["size_bytes"])
        head_bytes = bundle_head.stat().st_size
        results.append({
            "run_id": run_id,
            "model": checkpoint["model_id"],
            "features": {
                "text_view": "subject_body",
                "sequence_mode": bundle["sequence_mode"],
                "max_seq_length": feature_manifest["features"][feature_key]["max_seq_length"],
                "embedding_dim": feature_manifest["features"][feature_key]["dimension"],
                "pooling": feature_manifest["features"][feature_key]["pooling"],
            },
            "training_records": len(train_rows),
            "dev_records": len(dev_rows),
            "seed": SEED,
            "hyperparameters": {"head": "LogisticRegression", "C": 1.0, "class_weight": None},
            "loss": "log loss",
            "threshold_method": "five-fold leakage-group TRAIN OOF per-label F1",
            "thresholds_train_oof_only": {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
            "threshold_details": threshold_report,
            "oof_cv_training_seconds": oof_seconds,
            "full_train_seconds": training_seconds,
            "dev_head_inference_ms_per_record": 1000 * dev_seconds / max(len(dev_rows), 1),
            "encoder_size_bytes": encoder_bytes,
            "head_size_bytes": head_bytes,
            "package_size_bytes": encoder_bytes + head_bytes,
            "dev_metrics": metrics,
            "bundle_path": str(bundle_path.resolve()),
            "candidate_head_sha256": sha256_file(candidate_path),
            "dev_probabilities_path": str((EXP / "dev_probabilities_long_ablation.json").resolve()),
            "train_oof_probabilities_path": str((EXP / "train_oof_probabilities_long_ablation.json").resolve()),
            "prediction_mode": "flat",
            "fallback": False,
            "test_used_or_read": False,
        })
        oof_matrices[run_id] = oof.tolist()
        dev_matrices[run_id] = dev_probs.tolist()
        print(f"{run_id}: DEV macro={metrics['macro_f1']:.4f} micro={metrics['micro_f1']:.4f}", flush=True)

    dev_path = EXP / "dev_probabilities_long_ablation.json"
    oof_path = EXP / "train_oof_probabilities_long_ablation.json"
    write_json(dev_path, {
        "row_ids": [row["email_id"] for row in dev_rows],
        "run_ids": list(dev_matrices),
        "probabilities": dev_matrices,
        "thresholds_train_oof_only": {run["run_id"]: run["thresholds_train_oof_only"] for run in results},
    })
    write_json(oof_path, {
        "row_ids": [row["email_id"] for row in train_rows],
        "run_ids": list(oof_matrices),
        "probabilities": oof_matrices,
        "scope": "TRAIN-only grouped OOF; no DEV/TEST labels in fitting or threshold selection",
    })

    registry_path = AI_DIR / "reports/optimization_embeddings.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["additional_ablations"] = [row for row in registry.get("additional_ablations", []) if row["run_id"] not in {run["run_id"] for run in results}] + results
    new_names = {run["run_id"] for run in results}
    registry["bundles"] = [row for row in registry.get("bundles", []) if row.get("bundle_name") not in new_names]
    registry["bundles"] += [
        {
            "bundle_name": result["run_id"],
            "bundle_path": result["bundle_path"],
            "prediction_mode": "flat",
            "fallback": False,
            "thresholds_train_oof_only": result["thresholds_train_oof_only"],
            "dev_probabilities_path": str(dev_path.resolve()),
            "train_oof_probabilities_path": str(oof_path.resolve()),
            "package_size_bytes": result["package_size_bytes"],
        }
        for result in results
    ]
    registry["additional_ablation_probabilities"] = {
        "dev_path": str(dev_path.resolve()), "train_oof_path": str(oof_path.resolve()),
    }
    registry["additional_ablation_seconds"] = time.perf_counter() - started
    registry["additional_ablation_source_commit_sha"] = git_revision()
    write_json(registry_path, registry)
    write_json(EXP / "long_email_ablation.json", {"benchmark_sha256": benchmark_hash(), "runs": results})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

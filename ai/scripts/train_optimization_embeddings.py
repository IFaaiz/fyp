"""Run bounded frozen sentence-encoder experiments on TRAIN and DEV only.

Encoding is a separate phase so the GPU can be handed to the partial-transformer
experiment immediately after the fixed feature cache is written. Head fitting,
OOF threshold selection and all resulting metrics run on CPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
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

from src.models.optimization_benchmark import (
    LABEL_ORDER, benchmark_hash, cv_splits, load_partition, oof_thresholds,
    score_probabilities, targets, texts,
)
from src.models.optimization_embeddings import (
    HierarchicalBinaryHead, IndependentBinaryHead, LabelSpecialistHead,
    encode_texts,
)
from src.models.transfer_diagnostic import sha256_file

EXPERIMENT_DIR = AI_DIR / "data/experiments/optimization_20261002/embeddings"
MODEL_DIR = AI_DIR / "data/models/optimization/embeddings"
CACHE_MANIFEST = AI_DIR / "data/cache/sentence-transformers/optimization_embedding_checkpoints.json"
FEATURE_FILE = EXPERIMENT_DIR / "frozen_features.npz"
FEATURE_METADATA = EXPERIMENT_DIR / "frozen_feature_manifest.json"
RESULTS_FILE = EXPERIMENT_DIR / "head_experiments.json"
REGISTRY_FILE = AI_DIR / "reports/optimization_embeddings.json"
SEED = 20261004


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _file_sha(path: Path) -> str:
    return sha256_file(path)


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_DIR,
            check=True, text=True, capture_output=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _load_checkpoints(*, require_both: bool = True) -> dict[str, dict[str, Any]]:
    if not CACHE_MANIFEST.is_file():
        raise FileNotFoundError(f"run {AI_DIR / 'scripts/prefetch_optimization_embedding_checkpoints.py'} first")
    manifest = json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
    result = {}
    for item in manifest:
        model_id = item["model_id"]
        if model_id == "sentence-transformers/all-MiniLM-L6-v2":
            result["minilm"] = item
        elif model_id == "sentence-transformers/all-mpnet-base-v2":
            result["mpnet"] = item
    if not result or (require_both and set(result) != {"minilm", "mpnet"}):
        raise ValueError("official MiniLM and MPNet checkpoints are both required")
    return result


def _feature_plan() -> list[dict[str, str]]:
    return [
        {"key": "minilm_subject_body", "encoder": "minilm", "text_view": "subject_body", "sequence_mode": "head"},
        {"key": "minilm_subject_body_head_tail", "encoder": "minilm", "text_view": "subject_body", "sequence_mode": "head_tail"},
        {"key": "minilm_subject_body_two_chunks", "encoder": "minilm", "text_view": "subject_body", "sequence_mode": "two_chunks"},
        {"key": "minilm_body", "encoder": "minilm", "text_view": "body", "sequence_mode": "head"},
        {"key": "minilm_subject", "encoder": "minilm", "text_view": "subject", "sequence_mode": "head"},
        {"key": "minilm_subject_twice", "encoder": "minilm", "text_view": "subject_twice", "sequence_mode": "head"},
        {"key": "mpnet_subject_body", "encoder": "mpnet", "text_view": "subject_body", "sequence_mode": "head"},
    ]


def _encode_phase(encoder_key: str, feature_key: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    train_rows = load_partition("train")
    dev_rows = load_partition("dev")
    checkpoints = _load_checkpoints(require_both=encoder_key == "all")
    if encoder_key != "all" and encoder_key not in checkpoints:
        raise ValueError(f"checkpoint not downloaded yet: {encoder_key}")
    plans = _feature_plan()
    if feature_key is not None and feature_key not in {plan["key"] for plan in plans}:
        raise ValueError(f"unknown feature key: {feature_key}")
    if FEATURE_FILE.is_file() and FEATURE_METADATA.is_file():
        prior_features = {key: value for key, value in np.load(FEATURE_FILE).items()}
        prior_meta = json.loads(FEATURE_METADATA.read_text(encoding="utf-8"))
    else:
        prior_features = {}
        prior_meta = {"features": {}}
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    features: dict[str, np.ndarray] = dict(prior_features)
    reports: dict[str, Any] = dict(prior_meta.get("features", {}))
    for plan in plans:
        if feature_key is not None and plan["key"] != feature_key:
            continue
        if encoder_key != "all" and plan["encoder"] != encoder_key:
            continue
        checkpoint = checkpoints[plan["encoder"]]
        checkpoint_dir = Path(checkpoint["snapshot_path"])
        all_texts = texts(train_rows, view=plan["text_view"]) + texts(dev_rows, view=plan["text_view"])
        matrix, report = encode_texts(
            all_texts, checkpoint_dir=checkpoint_dir, batch_size=24,
            sequence_mode=plan["sequence_mode"],
        )
        cut = len(train_rows)
        features[f"{plan['key']}__train"] = matrix[:cut]
        features[f"{plan['key']}__dev"] = matrix[cut:]
        reports[plan["key"]] = {
            **report,
            "encoder_implementation_sha256": _file_sha(AI_DIR / "src/models/optimization_embeddings.py"),
            "encoder_key": plan["encoder"],
            "model_id": checkpoint["model_id"],
            "revision": checkpoint["revision"],
            "official_model_repository_file_sha256": checkpoint["files"],
            "text_view": plan["text_view"],
            "train_records": cut,
            "dev_records": len(dev_rows),
        }
        print(f"encoded {plan['key']}: {matrix.shape}; {report['encode_seconds']:.1f}s", flush=True)
        del matrix

    np.savez_compressed(FEATURE_FILE, **features)
    feature_meta = {
        "scope": "AI-SILVER DIAGNOSTIC PERFORMANCE; no human/gold claim",
        "benchmark_sha256": benchmark_hash(),
        "train_email_ids": [row["email_id"] for row in train_rows],
        "dev_email_ids": [row["email_id"] for row in dev_rows],
        "train_file_sha256": _file_sha(EXPERIMENT_DIR.parent / "train.jsonl"),
        "dev_file_sha256": _file_sha(EXPERIMENT_DIR.parent / "dev.jsonl"),
        "feature_file_sha256": _file_sha(FEATURE_FILE),
        "features": reports,
        "source_commit_sha": _git_revision(),
        "encoder_implementation_sha256": _file_sha(AI_DIR / "src/models/optimization_embeddings.py"),
        "records_text_written_to_cache": False,
        "phase_seconds": time.perf_counter() - started,
    }
    _json_write(FEATURE_METADATA, feature_meta)
    print(json.dumps({
        "feature_file": str(FEATURE_FILE), "feature_sha256": feature_meta["feature_file_sha256"],
        "phase_seconds": feature_meta["phase_seconds"], "feature_keys": list(reports),
    }, indent=2), flush=True)
    return feature_meta


def _head_configs() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for c_value in (0.1, 1.0, 4.0):
        weightings = ("none", "sqrt", "cap3", "cap5", "cap8") if c_value == 1.0 else ("none", "sqrt", "cap3")
        for weighting in weightings:
            configs.append({"key": f"minilm_flat_lr_c{c_value:g}_{weighting}", "feature": "minilm_subject_body", "mode": "flat", "method": "logistic", "C": c_value, "weighting": weighting})
    configs.extend([
        {"key": "minilm_flat_svm_c1", "feature": "minilm_subject_body", "mode": "flat", "method": "linear_svm", "C": 1.0, "weighting": "none"},
        {"key": "minilm_flat_mlp64", "feature": "minilm_subject_body", "mode": "flat", "method": "mlp", "hidden_layer_sizes": (64,), "alpha": 0.001, "max_iter": 120, "weighting": "none"},
        {"key": "minilm_hier_lr_c0.1", "feature": "minilm_subject_body", "mode": "hierarchical", "method": "logistic", "C": 0.1, "weighting": "none"},
        {"key": "minilm_hier_lr_c1", "feature": "minilm_subject_body", "mode": "hierarchical", "method": "logistic", "C": 1.0, "weighting": "none"},
        {"key": "minilm_hier_lr_c4", "feature": "minilm_subject_body", "mode": "hierarchical", "method": "logistic", "C": 4.0, "weighting": "none"},
        {"key": "minilm_flat_body_lr_c1", "feature": "minilm_body", "mode": "flat", "method": "logistic", "C": 1.0, "weighting": "none"},
        {"key": "minilm_flat_subject_lr_c1", "feature": "minilm_subject", "mode": "flat", "method": "logistic", "C": 1.0, "weighting": "none"},
        {"key": "minilm_flat_subject_twice_lr_c1", "feature": "minilm_subject_twice", "mode": "flat", "method": "logistic", "C": 1.0, "weighting": "none"},
        {"key": "minilm_flat_head_tail_lr_c1", "feature": "minilm_subject_body_head_tail", "mode": "flat", "method": "logistic", "C": 1.0, "weighting": "none"},
        {"key": "minilm_flat_two_chunks_lr_c1", "feature": "minilm_subject_body_two_chunks", "mode": "flat", "method": "logistic", "C": 1.0, "weighting": "none"},
        {"key": "mpnet_flat_lr_c1", "feature": "mpnet_subject_body", "mode": "flat", "method": "logistic", "C": 1.0, "weighting": "none"},
    ])
    for config in configs:
        config["seed"] = SEED
    return configs


def _fit_model(config: dict[str, Any], x: np.ndarray, y: np.ndarray) -> Any:
    if config["mode"] == "flat":
        return IndependentBinaryHead(config).fit(x, y)
    return HierarchicalBinaryHead(config).fit(x, y)


def _metric_summary(expected_rows: list[list[str]], probs: np.ndarray, thresholds: list[float], mode: str) -> dict[str, Any]:
    return score_probabilities(expected_rows, probs, thresholds, mode=mode)


def _scope_metrics(expected_rows: list[list[str]], probs: np.ndarray, nonproject_threshold: float) -> dict[str, Any]:
    actual_project = np.array(["NON_PROJECT" not in row for row in expected_rows], dtype=bool)
    predicted_project = np.asarray(probs[:, 8] < nonproject_threshold, dtype=bool)
    tp = int(np.sum(actual_project & predicted_project))
    fp = int(np.sum(~actual_project & predicted_project))
    fn = int(np.sum(actual_project & ~predicted_project))
    tn = int(np.sum(~actual_project & ~predicted_project))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    nonproject_precision = tn / (tn + fn) if tn + fn else 0.0
    nonproject_recall = tn / (tn + fp) if tn + fp else 0.0
    nonproject_f1 = (
        2 * nonproject_precision * nonproject_recall / (nonproject_precision + nonproject_recall)
        if nonproject_precision + nonproject_recall else 0.0
    )
    return {
        "scope_accuracy": (tp + tn) / max(len(expected_rows), 1),
        "project_precision": precision,
        "project_recall": recall,
        "project_f1": f1,
        "project_support": int(actual_project.sum()),
        "non_project_f1": nonproject_f1,
    }


def _head_size(path: Path, head: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(head, path, compress=3)
    return path.stat().st_size


def _ensure_model_encoders(checkpoints: dict[str, dict[str, Any]]) -> dict[str, str]:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for key, item in checkpoints.items():
        target = MODEL_DIR / "encoders" / key
        target.mkdir(parents=True, exist_ok=True)
        for name, expected_hash in item["files"].items():
            source = Path(item["snapshot_path"]) / name
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.is_file() or _file_sha(destination) != expected_hash:
                shutil.copy2(source, destination)
            if _file_sha(destination) != expected_hash:
                raise ValueError(f"copied encoder file SHA-256 mismatch: {destination}")
        result[key] = str(target.resolve())
    return result


def _write_bundle(
    *, name: str, bundle_type: str, encoder_locations: dict[str, str],
    feature_specs: dict[str, dict[str, str]], head: Any,
    mode: str, thresholds: list[float], metric: dict[str, Any],
    checkpoint_metadata: dict[str, Any],
) -> dict[str, Any]:
    bundle_dir = MODEL_DIR / "bundles" / name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    joblib_path = bundle_dir / "heads.joblib"
    joblib.dump(head, joblib_path, compress=3)
    relative_specs = {}
    encoder_rows = {}
    for key, spec in feature_specs.items():
        encoder_key = spec["encoder"]
        encoder_path = Path(encoder_locations[encoder_key])
        relative_specs[key] = {
            "encoder_path": os.path.relpath(encoder_path, bundle_dir),
            "text_view": spec["text_view"],
            "sequence_mode": spec["sequence_mode"],
        }
        encoder_rows[encoder_key] = checkpoint_metadata[encoder_key]
    payload = {
        "scope": "AI-SILVER DIAGNOSTIC PERFORMANCE; not human/gold/production accuracy",
        "bundle_type": bundle_type,
        "model_family": "frozen official sentence-transformer encoder + scikit-learn heads",
        "prediction_mode": mode,
        "probability_semantics": "conditional project-function probabilities in columns 0..7; NON_PROJECT scope probability in column 8" if mode == "hierarchical" else "independent label probabilities",
        "fallback": False,
        "feature_specs": relative_specs,
        "encoder_path": relative_specs.get("default", {}).get("encoder_path"),
        "text_view": relative_specs.get("default", {}).get("text_view"),
        "sequence_mode": relative_specs.get("default", {}).get("sequence_mode", "head"),
        "thresholds_train_oof_only": {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
        "dev_metrics": metric,
        "benchmark_sha256": benchmark_hash(),
        "encoder_checkpoints": encoder_rows,
        "heads_file_sha256": _file_sha(joblib_path),
        "inference_batch_size": 24,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    _json_write(bundle_dir / "bundle.json", payload)
    return {
        "bundle_name": name,
        "bundle_path": str(bundle_dir.resolve()),
        "prediction_mode": mode,
        "fallback": False,
        "thresholds_train_oof_only": {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
        "dev_probabilities_path": str((EXPERIMENT_DIR / "dev_probabilities.json").resolve()),
        "train_oof_probabilities_path": str((EXPERIMENT_DIR / "train_oof_probabilities.json").resolve()),
        "head_file_sha256": _file_sha(joblib_path),
        "head_size_bytes": joblib_path.stat().st_size,
        "encoder_size_bytes": sum(
            path.stat().st_size for key in encoder_rows
            for path in Path(encoder_locations[key]).rglob("*") if path.is_file()
        ),
        "package_size_bytes": joblib_path.stat().st_size + sum(
            path.stat().st_size for key in encoder_rows
            for path in Path(encoder_locations[key]).rglob("*") if path.is_file()
        ),
        "bundle_sha256": _file_sha(bundle_dir / "bundle.json"),
    }


def _fit_phase() -> dict[str, Any]:
    started = time.perf_counter()
    train_rows = load_partition("train")
    dev_rows = load_partition("dev")
    if not FEATURE_FILE.is_file() or not FEATURE_METADATA.is_file():
        raise FileNotFoundError("frozen feature cache missing; run --encode-only first")
    feature_meta = json.loads(FEATURE_METADATA.read_text(encoding="utf-8"))
    if feature_meta.get("benchmark_sha256") != benchmark_hash():
        raise ValueError("feature cache benchmark hash does not match current frozen benchmark")
    if feature_meta["train_email_ids"] != [row["email_id"] for row in train_rows] or feature_meta["dev_email_ids"] != [row["email_id"] for row in dev_rows]:
        raise ValueError("feature cache row order differs from the frozen TRAIN/DEV partitions")
    if feature_meta["train_file_sha256"] != _file_sha(EXPERIMENT_DIR.parent / "train.jsonl") or feature_meta["dev_file_sha256"] != _file_sha(EXPERIMENT_DIR.parent / "dev.jsonl"):
        raise ValueError("frozen train/dev input changed after embedding extraction")
    all_checkpoints = _load_checkpoints(require_both=False)
    matrices = np.load(FEATURE_FILE)
    y_train, y_dev = targets(train_rows), targets(dev_rows)
    expected_dev = [row["labels"] for row in dev_rows]
    train_cv = cv_splits(train_rows)
    candidate_results: dict[str, Any] = {}
    candidate_heads: dict[str, Any] = {}
    probabilities: dict[str, np.ndarray] = {}
    oof_probabilities: dict[str, np.ndarray] = {}
    oof_labels = [row["labels"] for row in train_rows]

    helper_sha = _file_sha(AI_DIR / "src/models/optimization_embeddings.py")
    active_configs = [
        config for config in _head_configs()
        if f"{config['feature']}__train" in matrices.files
        and (
            config["feature"] != "minilm_subject_body_head_tail"
            or feature_meta["features"][config["feature"]].get("encoder_implementation_sha256") == helper_sha
        )
    ]
    for config in active_configs:
        key = config["key"]
        x_train = matrices[f"{config['feature']}__train"].astype(np.float32, copy=False)
        x_dev = matrices[f"{config['feature']}__dev"].astype(np.float32, copy=False)
        oof = np.zeros((len(train_rows), len(LABEL_ORDER)), dtype=np.float64)
        oof_started = time.perf_counter()
        for fold_number, (fit_indices, held_indices) in enumerate(train_cv, 1):
            fold_config = {**config, "seed": SEED + fold_number}
            fitted = _fit_model(fold_config, x_train[fit_indices], y_train[fit_indices])
            oof[held_indices] = fitted.predict_proba(x_train[held_indices])
        threshold_values, threshold_report = oof_thresholds(oof_labels, oof, mode=config["mode"])
        oof_seconds = time.perf_counter() - oof_started
        full_started = time.perf_counter()
        fitted_all = _fit_model(config, x_train, y_train)
        dev_started = time.perf_counter()
        dev_probs = fitted_all.predict_proba(x_dev)
        dev_inference_seconds = time.perf_counter() - dev_started
        full_training_seconds = time.perf_counter() - full_started - dev_inference_seconds
        metrics = _metric_summary(expected_dev, dev_probs, threshold_values, config["mode"])
        scope_summary = _scope_metrics(expected_dev, dev_probs, threshold_values[8]) if config["mode"] == "hierarchical" else None
        candidate_path = MODEL_DIR / "candidates" / f"{key}.joblib"
        head_size = _head_size(candidate_path, fitted_all)
        encoder_key = feature_meta["features"][config["feature"]]["encoder_key"]
        encoder_size = int(all_checkpoints[encoder_key]["size_bytes"])
        feature_encode = feature_meta["features"][config["feature"]]
        encoder_encode_ms_per_record = 1000 * float(feature_encode["encode_seconds"]) / max(int(feature_encode["train_records"]) + int(feature_encode["dev_records"]), 1)
        descriptor = {
            **config,
            "run_id": key,
            "model": f"{config['method']} on frozen {feature_meta['features'][config['feature']]['model_id']}",
            "features": {
                "text_view": feature_meta["features"][config["feature"]]["text_view"],
                "sequence_mode": feature_meta["features"][config["feature"]]["sequence_mode"],
                "embedding_dim": feature_meta["features"][config["feature"]]["dimension"],
                "pooling": "attention-mask mean; L2 normalized",
            },
            "training_records": len(train_rows),
            "dev_records": len(dev_rows),
            "seed": SEED,
            "loss": "log loss" if config["method"] in {"logistic", "mlp"} else "squared hinge",
            "score_output": "LinearSVC margins mapped by fixed sigmoid; uncalibrated; threshold selected on grouped TRAIN OOF" if config["method"] == "linear_svm" else "independent binary positive-class probabilities",
            "class_weighting": config["weighting"],
            "threshold_method": "five-fold leakage-group TRAIN OOF per-label F1; no DEV calibration",
            "probability_semantics": "conditional Stage-2 function probabilities + Stage-1 NON_PROJECT probability" if config["mode"] == "hierarchical" else "independent label probabilities",
            "oof_thresholds": {label: float(threshold_values[i]) for i, label in enumerate(LABEL_ORDER)},
            "oof_threshold_details": threshold_report,
            "oof_cv_training_seconds": oof_seconds,
            "full_train_seconds": full_training_seconds,
            "dev_inference_seconds": dev_inference_seconds,
            "head_inference_ms_per_record": 1000 * dev_inference_seconds / max(len(dev_rows), 1),
            "encoder_load_plus_feature_encode_ms_per_record": encoder_encode_ms_per_record,
            "estimated_end_to_end_ms_per_record": encoder_encode_ms_per_record + 1000 * dev_inference_seconds / max(len(dev_rows), 1),
            "encoder_size_bytes": encoder_size,
            "head_size_bytes": head_size,
            "model_package_size_bytes": encoder_size + head_size,
            "dev_metrics": metrics,
            "scope_metrics": scope_summary,
            "candidate_head_file": str(candidate_path.resolve()),
            "candidate_head_sha256": _file_sha(candidate_path),
            "threshold_selection_training_only": True,
            "dev_used_for_encoder_training": False,
        }
        candidate_results[key] = descriptor
        candidate_heads[key] = fitted_all
        probabilities[key] = dev_probs
        oof_probabilities[key] = oof
        print(f"fit {key}: dev macro={metrics['macro_f1']:.4f} micro={metrics['micro_f1']:.4f}; OOF {oof_seconds:.1f}s", flush=True)

    # A transparent per-label specialist selection using the same DEV metrics
    # used for all family selection; every selected cutoff remains TRAIN OOF.
    specialist_descriptors: list[dict[str, Any]] = []
    specialist_estimators: list[Any] = []
    specialist_dev = np.zeros((len(dev_rows), 9), dtype=np.float64)
    specialist_oof = np.zeros((len(train_rows), 9), dtype=np.float64)
    specialist_thresholds = np.full(9, 0.5, dtype=np.float64)
    for label_index, label in enumerate(LABEL_ORDER):
        options = []
        for key, result in candidate_results.items():
            if result["mode"] != "flat":
                continue
            label_metrics = result["dev_metrics"]["per_label"][label]
            options.append((label_metrics["f1"], result["dev_metrics"]["macro_f1"], key))
        _, _, selected_key = max(options)
        result = candidate_results[selected_key]
        feature_key = result["feature"]
        estimator = candidate_heads[selected_key].estimators[result["label_indices"].index(label_index)] if "label_indices" in result else candidate_heads[selected_key].estimators[label_index]
        specialist_estimators.append(estimator)
        specialist_descriptors.append({"label_index": label_index, "label": label, "feature_key": feature_key, "selected_run_id": selected_key})
        specialist_dev[:, label_index] = probabilities[selected_key][:, label_index]
        specialist_oof[:, label_index] = oof_probabilities[selected_key][:, label_index]
        specialist_thresholds[label_index] = result["oof_thresholds"][label]

    # Flatten outputs in exact frozen row order. These artifacts are text-free.
    dev_payload = {
        "row_ids": [row["email_id"] for row in dev_rows],
        "run_ids": list(probabilities),
        "probabilities": {key: probabilities[key].tolist() for key in probabilities},
        "thresholds_oof_train_only": {key: candidate_results[key]["oof_thresholds"] for key in candidate_results},
        "prediction_modes": {key: candidate_results[key]["mode"] for key in candidate_results},
    }
    oof_payload = {
        "row_ids": [row["email_id"] for row in train_rows],
        "run_ids": list(oof_probabilities),
        "probabilities": {key: oof_probabilities[key].tolist() for key in oof_probabilities},
        "scope": "TRAIN-only grouped OOF probabilities; no DEV or TEST labels used",
    }
    _json_write(EXPERIMENT_DIR / "dev_probabilities.json", dev_payload)
    _json_write(EXPERIMENT_DIR / "train_oof_probabilities.json", oof_payload)

    best_flat = max((r for r in candidate_results.values() if r["mode"] == "flat"), key=lambda r: (r["dev_metrics"]["macro_f1"], r["dev_metrics"]["micro_f1"]))
    best_hierarchical = max((r for r in candidate_results.values() if r["mode"] == "hierarchical"), key=lambda r: (r["dev_metrics"]["macro_f1"], r["dev_metrics"]["micro_f1"]))
    used_encoder_keys = {
        feature_meta["features"][config["feature"]]["encoder_key"]
        for config in active_configs
    }
    checkpoints = {key: value for key, value in all_checkpoints.items() if key in used_encoder_keys}
    encoder_locations = _ensure_model_encoders(checkpoints)
    feature_specs = {plan["key"]: {"encoder": plan["encoder"], "text_view": plan["text_view"], "sequence_mode": plan["sequence_mode"]} for plan in _feature_plan()}
    bundle_rows = []
    flat_result = candidate_results[best_flat["run_id"]]
    bundle_rows.append(_write_bundle(
        name="best_flat", bundle_type="single", encoder_locations=encoder_locations,
        feature_specs={"default": feature_specs[flat_result["feature"]]},
        head=candidate_heads[best_flat["run_id"]], mode="flat",
        thresholds=[best_flat["oof_thresholds"][label] for label in LABEL_ORDER],
        metric=best_flat["dev_metrics"], checkpoint_metadata=checkpoints,
    ))
    hier_result = candidate_results[best_hierarchical["run_id"]]
    bundle_rows.append(_write_bundle(
        name="best_hierarchical", bundle_type="single", encoder_locations=encoder_locations,
        feature_specs={"default": feature_specs[hier_result["feature"]]},
        head=candidate_heads[best_hierarchical["run_id"]], mode="hierarchical",
        thresholds=[best_hierarchical["oof_thresholds"][label] for label in LABEL_ORDER],
        metric=best_hierarchical["dev_metrics"], checkpoint_metadata=checkpoints,
    ))
    specialist_head = LabelSpecialistHead(specialist_descriptors, specialist_estimators)
    specialist_metrics = _metric_summary(expected_dev, specialist_dev, specialist_thresholds.tolist(), "flat")
    specialist_specs = {
        descriptor["feature_key"]: feature_specs[descriptor["feature_key"]]
        for descriptor in specialist_descriptors
    }
    bundle_rows.append(_write_bundle(
        name="per_label_specialists", bundle_type="specialists", encoder_locations=encoder_locations,
        feature_specs=specialist_specs, head=specialist_head, mode="flat",
        thresholds=specialist_thresholds.tolist(), metric=specialist_metrics,
        checkpoint_metadata=checkpoints,
    ))

    try:
        import sklearn
        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = None
    registry = {
        "scope": "AI-SILVER DIAGNOSTIC PERFORMANCE; not human, gold, or production accuracy",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "family": "frozen sentence-transformer embeddings with small sklearn heads",
        "benchmark": {
            "benchmark_sha256": benchmark_hash(),
            "train_file_sha256": feature_meta["train_file_sha256"],
            "dev_file_sha256": feature_meta["dev_file_sha256"],
            "train_records": len(train_rows),
            "dev_records": len(dev_rows),
            "train_label_support": {label: int(y_train[:, index].sum()) for index, label in enumerate(LABEL_ORDER)},
            "dev_label_support": {label: int(y_dev[:, index].sum()) for index, label in enumerate(LABEL_ORDER)},
            "dev_used_for_fit": False,
            "test_used_or_read": False,
        },
        "baseline_reference": {"old_tfidf_micro_f1": 0.626, "old_tfidf_macro_f1": 0.363, "split_comparable": False},
        "checkpoints": {key: {k: item[k] for k in ("model_id", "revision", "size_bytes", "files")} for key, item in checkpoints.items()},
        "feature_cache": {
            "path": str(FEATURE_FILE.resolve()),
            "sha256": _file_sha(FEATURE_FILE),
            "features": feature_meta["features"],
            "raw_email_text_saved": False,
        },
        "runtime": {"python": platform.python_version(), "sklearn": sklearn_version, "numpy": np.__version__, "source_commit_sha": _git_revision()},
        "runs": list(candidate_results.values()),
        "per_label_specialists": {
            "run_id": "per_label_specialists",
            "dev_metrics": specialist_metrics,
            "oof_thresholds": {label: float(specialist_thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
            "selected_heads": specialist_descriptors,
            "train_only_oof_thresholds": True,
        },
        "bundles": bundle_rows,
        "dev_probability_artifact": str((EXPERIMENT_DIR / "dev_probabilities.json").resolve()),
        "train_oof_probability_artifact": str((EXPERIMENT_DIR / "train_oof_probabilities.json").resolve()),
        "phase_seconds": time.perf_counter() - started,
    }
    _json_write(RESULTS_FILE, registry)
    _json_write(REGISTRY_FILE, registry)
    print(json.dumps({
        "best_flat": {"run_id": best_flat["run_id"], "dev_macro_f1": best_flat["dev_metrics"]["macro_f1"], "dev_micro_f1": best_flat["dev_metrics"]["micro_f1"]},
        "best_hierarchical": {"run_id": best_hierarchical["run_id"], "dev_macro_f1": best_hierarchical["dev_metrics"]["macro_f1"], "dev_micro_f1": best_hierarchical["dev_metrics"]["micro_f1"]},
        "specialist_dev_macro_f1": specialist_metrics["macro_f1"],
        "registry": str(REGISTRY_FILE.resolve()),
        "phase_seconds": registry["phase_seconds"],
    }, indent=2), flush=True)
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--encode-only", action="store_true")
    group.add_argument("--fit-only", action="store_true")
    parser.add_argument("--encoder-key", choices=("minilm", "mpnet", "all"), default="all")
    parser.add_argument("--feature-key")
    args = parser.parse_args()
    if args.encode_only:
        _encode_phase(args.encoder_key, args.feature_key)
    else:
        _fit_phase()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Controlled partial DistilBERT ablations on the new AI-silver benchmark.

This runner reads only the frozen `train.jsonl` and `dev.jsonl` partitions.
It verifies the local upstream checkpoint manifest, tunes/early-stops on DEV,
and never opens a TEST path. All outputs are text-free run records, probabilities,
and model weights under the optimization experiment directories.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import random
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

AI_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = AI_DIR.parent
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.models.optimization_transformer import (  # noqa: E402
    MAX_LENGTH, _batch_inputs, canonical_text, encode_layout,
)
from src.models import optimization_benchmark as benchmark  # noqa: E402
from src.models.silver_classifier import LABEL_ORDER  # noqa: E402
from src.models.transfer_diagnostic import (  # noqa: E402
    exclusive_predictions, full_diagnostic_metrics, tune_thresholds,
)

EXPERIMENT_DIR = AI_DIR / "data/experiments/optimization_20261002"
TRAIN_PATH = EXPERIMENT_DIR / "train.jsonl"
DEV_PATH = EXPERIMENT_DIR / "dev.jsonl"
CHECKPOINT_DIR = AI_DIR / "data/cache/distilbert-base-uncased"
CHECKPOINT_REVISION = "12040accade4e8a0f71eabdb258fecc2e7e948be"
CHECKPOINT_MANIFEST = CHECKPOINT_DIR / "checkpoint_manifest.json"
RESULTS_DIR = EXPERIMENT_DIR / "transformer"
MODEL_ROOT = AI_DIR / "data/models/optimization/transformer"
REPORT_PATH = AI_DIR / "reports/optimization_transformer.json"
SEED = 20261002
EXACT_AGREEMENT_RULE = "exact_unflagged_blind_agreement_third_audit_gate"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _read_partition(path: Path, expected_path: Path, name: str) -> list[dict[str, Any]]:
    if path.resolve() != expected_path.resolve():
        raise ValueError(f"{name} input must be the approved file {expected_path}")
    # The shared helper checks the frozen benchmark hashes, text-free manifest,
    # provenance fields, and exact partition membership. Its public API refuses
    # to load TEST, so this runner has no path that can inspect it.
    rows = benchmark.load_partition(name)
    for row in rows:
        canonical_text(row)
    return rows


def _group_values(row: dict[str, Any]) -> tuple[tuple[str, str] | None, str | None]:
    source = row.get("source_dataset")
    thread_id = row.get("thread_id")
    thread = (str(source or ""), str(thread_id)) if thread_id else None
    provenance = row.get("snapshot_provenance")
    leakage = row.get("leakage_group_id")
    if not leakage and isinstance(provenance, dict):
        leakage = provenance.get("leakage_group_id")
    return thread, str(leakage) if leakage else None


def _uses_exact_agreement_rule(row: dict[str, Any]) -> bool:
    provenance = row.get("snapshot_provenance")
    rule = row.get("acceptance_rule")
    if not rule and isinstance(provenance, dict):
        rule = provenance.get("acceptance_rule")
    return rule == EXACT_AGREEMENT_RULE


def _validate_partition_boundary(train: list[dict[str, Any]], dev: list[dict[str, Any]]) -> None:
    train_ids = {str(row["email_id"]) for row in train}
    dev_ids = {str(row["email_id"]) for row in dev}
    if train_ids.intersection(dev_ids):
        raise ValueError("an email_id appears in both train and dev")
    train_threads, dev_threads = set(), set()
    train_groups, dev_groups = set(), set()
    for row in train:
        thread, group = _group_values(row)
        if thread:
            train_threads.add(thread)
        if group:
            train_groups.add(group)
    for row in dev:
        thread, group = _group_values(row)
        if thread:
            dev_threads.add(thread)
        if group:
            dev_groups.add(group)
    if train_threads.intersection(dev_threads):
        raise ValueError("a thread crosses the train/dev boundary")
    if train_groups.intersection(dev_groups):
        raise ValueError("a leakage group crosses the train/dev boundary")


def _verify_upstream_checkpoint() -> dict[str, Any]:
    if not CHECKPOINT_MANIFEST.is_file():
        raise FileNotFoundError(f"missing upstream checkpoint manifest: {CHECKPOINT_MANIFEST}")
    manifest = json.loads(CHECKPOINT_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("model_id") != "distilbert-base-uncased" or manifest.get("revision") != CHECKPOINT_REVISION:
        raise ValueError("the local DistilBERT checkpoint is not the approved immutable upstream revision")
    files: dict[str, str] = {}
    for item in manifest.get("files", []):
        path = CHECKPOINT_DIR / item["filename"]
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise ValueError(f"missing or size-mismatched pretrained checkpoint file: {path}")
        digest = sha256_file(path)
        if digest != item["sha256"]:
            raise ValueError(f"pretrained checkpoint hash mismatch: {path}")
        files[item["filename"]] = digest
    if "model.safetensors" not in files:
        raise ValueError("upstream checkpoint manifest does not contain model.safetensors")
    return {"model_id": manifest["model_id"], "revision": manifest["revision"], "file_sha256": files}


def _seed_everything(seed: int, torch: Any) -> None:
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=False)


def _encode_rows(tokenizer: Any, rows: list[dict[str, Any]], layout: str) -> tuple[list[list[list[int]]], dict[str, Any]]:
    encoded: list[list[list[int]]] = []
    lengths: list[int] = []
    for row in rows:
        text = canonical_text(row)
        raw = tokenizer.encode(text, add_special_tokens=False, truncation=False)
        lengths.append(len(raw) + 2)
        encoded.append(encode_layout(tokenizer, text, layout))
    effective_limit = 2 * (MAX_LENGTH - 2) + 2 if layout == "two_chunk" else MAX_LENGTH
    clipped = sum(length > effective_limit for length in lengths)
    return encoded, {
        "records": len(rows), "truncated_records": clipped,
        "truncated_fraction": clipped / len(rows) if rows else 0.0,
        "p50_tokens": sorted(lengths)[max(0, (len(lengths) - 1) * 50 // 100)],
        "p90_tokens": sorted(lengths)[max(0, (len(lengths) - 1) * 90 // 100)],
        "p95_tokens": sorted(lengths)[max(0, (len(lengths) - 1) * 95 // 100)],
        "max_tokens": max(lengths, default=0),
    }


def _fit_class_weights(rows: list[dict[str, Any]], mode: str, cap: float | None) -> tuple[list[float], dict[str, Any]]:
    weights, counts = [], {}
    total = len(rows)
    for label in LABEL_ORDER:
        positive = sum(label in row["labels"] for row in rows)
        negative = total - positive
        raw = negative / positive if positive else 1.0
        if mode == "sqrt":
            value = raw ** 0.5
        elif mode == "capped":
            value = min(raw, float(cap))
        else:
            value = 1.0
        weights.append(value)
        counts[label] = {"positive": positive, "negative": negative, "raw_pos_weight": raw, "applied_pos_weight": value}
    return weights, counts


def _sampling_weights(rows: list[dict[str, Any]], views: list[tuple[int, int]]) -> list[float]:
    totals = {label: sum(label in row["labels"] for row in rows) for label in LABEL_ORDER}
    row_weights: list[float] = []
    for row in rows:
        active = row["labels"]
        rarity = [len(rows) / max(totals[label], 1) for label in active]
        row_weights.append(min(5.0, sum(rarity) / max(len(rarity), 1)))
    counts_per_row = Counter(row_index for row_index, _ in views)
    return [row_weights[row_index] / counts_per_row[row_index] for row_index, _ in views]


def _torch_inputs(tokenizer: Any, sequences: list[list[int]], device: Any, torch: Any) -> dict[str, Any]:
    return _batch_inputs(tokenizer, sequences, device, torch)


def _make_model(checkpoint: Path, trainable: str, seed: int, torch: Any) -> Any:
    from transformers import AutoModelForSequenceClassification

    _seed_everything(seed, torch)
    id2label = {index: label for index, label in enumerate(LABEL_ORDER)}
    label2id = {label: index for index, label in enumerate(LABEL_ORDER)}
    model = AutoModelForSequenceClassification.from_pretrained(
        str(checkpoint), local_files_only=True, num_labels=len(LABEL_ORDER),
        id2label=id2label, label2id=label2id, problem_type="multi_label_classification",
        attn_implementation="eager",
    )
    for parameter in model.parameters():
        parameter.requires_grad = False
    encoder = model.distilbert
    layers = encoder.transformer.layer
    if trainable == "head_only":
        pass
    elif trainable in {"last_block", "last_2_blocks"}:
        amount = 1 if trainable == "last_block" else 2
        for layer in layers[-amount:]:
            for parameter in layer.parameters():
                parameter.requires_grad = True
    elif trainable == "full_encoder":
        for parameter in encoder.parameters():
            parameter.requires_grad = True
    else:
        raise ValueError(f"unknown trainable region: {trainable}")
    for module_name in ("pre_classifier", "classifier"):
        module = getattr(model, module_name, None)
        if module is not None:
            for parameter in module.parameters():
                parameter.requires_grad = True
    return model


def _probabilities(model: Any, tokenizer: Any, encoded: list[list[list[int]]], device: Any,
                   torch: Any, batch_size: int, pooling: str = "mean") -> list[list[float]]:
    flat: list[list[int]] = []
    owners: list[int] = []
    for row_index, views in enumerate(encoded):
        for sequence in views:
            owners.append(row_index)
            flat.append(sequence)
    row_probabilities: list[list[list[float]]] = [[] for _ in encoded]
    use_amp = device.type == "cuda"
    model.eval()
    with torch.no_grad():
        for start in range(0, len(flat), batch_size):
            stop = min(start + batch_size, len(flat))
            batch = _torch_inputs(tokenizer, flat[start:stop], device, torch)
            with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(**batch).logits
            values = logits.float().sigmoid().cpu().tolist()
            for owner, probabilities in zip(owners[start:stop], values):
                row_probabilities[owner].append(probabilities)
    aggregated = []
    for views in row_probabilities:
        if len(views) == 1:
            aggregated.append(views[0])
        elif pooling == "max":
            aggregated.append([max(column) for column in zip(*views)])
        else:
            aggregated.append([sum(column) / len(column) for column in zip(*views)])
    return aggregated


def _metrics(rows: list[dict[str, Any]], probs: list[list[float]], mode: str = "flat") -> dict[str, Any]:
    expected = [row["labels"] for row in rows]
    report = benchmark.score_probabilities(expected, probs, mode=mode, fallback=False)
    if mode == "hierarchical":
        decoded = benchmark.decode(probs, mode="hierarchical", fallback=False)
        actual_project = ["NON_PROJECT" not in labels for labels in expected]
        guessed_project = ["NON_PROJECT" not in labels for labels in decoded]
        tp = sum(actual and guess for actual, guess in zip(actual_project, guessed_project))
        fp = sum(not actual and guess for actual, guess in zip(actual_project, guessed_project))
        fn = sum(actual and not guess for actual, guess in zip(actual_project, guessed_project))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        report["hierarchical_scope_metrics"] = {
            "accuracy": sum(actual == guess for actual, guess in zip(actual_project, guessed_project)) / len(expected),
            "project_precision": precision,
            "project_recall": recall,
            "project_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "non_project_f1": report["per_label"]["NON_PROJECT"]["f1"],
        }
    return report


def _loss_for(logits: Any, targets: Any, criterion: Any, mode: str, gamma: float,
              task_mode: str, torch: Any) -> Any:
    import torch.nn.functional as F
    if mode == "focal":
        base = F.binary_cross_entropy_with_logits(logits.float(), targets.float(), reduction="none")
        probabilities = logits.float().sigmoid()
        correct_probability = probabilities * targets + (1.0 - probabilities) * (1.0 - targets)
        return ((1.0 - correct_probability).pow(gamma) * base).mean()
    if task_mode == "hierarchical":
        scope = F.binary_cross_entropy_with_logits(logits[:, 8].float(), targets[:, 8].float())
        project_rows = targets[:, 8] < 0.5
        if project_rows.any():
            functions = criterion(logits[project_rows, :8].float(), targets[project_rows, :8].float())
        else:
            functions = logits[:, :8].sum() * 0.0
        return (scope + functions) / 2.0
    return criterion(logits.float(), targets.float())


def _score_candidate(*, rows: list[dict[str, Any]], tokenizer: Any, encoded: list[list[list[int]]],
                     model: Any, device: Any, torch: Any, batch_size: int,
                     allow_pooling: bool, mode: str = "flat") -> tuple[dict[str, Any], list[list[float]], str]:
    if allow_pooling:
        probabilities_by_pool = {
            pooling: _probabilities(model, tokenizer, encoded, device, torch, batch_size, pooling)
            for pooling in ("mean", "max")
        }
        metrics_by_pool = {key: _metrics(rows, value, mode) for key, value in probabilities_by_pool.items()}
        selected_pool = max(
            ("mean", "max"),
            key=lambda key: (metrics_by_pool[key]["macro_f1"], metrics_by_pool[key]["micro_f1"], key == "mean"),
        )
        return metrics_by_pool[selected_pool], probabilities_by_pool[selected_pool], selected_pool
    probabilities = _probabilities(model, tokenizer, encoded, device, torch, batch_size)
    return _metrics(rows, probabilities, mode), probabilities, "mean"


def _save_bundle(bundle: Path, model: Any, tokenizer: Any, spec: dict[str, Any], pooling: str,
                 checkpoint: dict[str, Any], results: dict[str, Any]) -> tuple[int, int]:
    bundle.parent.mkdir(parents=True, exist_ok=True)
    if bundle.exists():
        # This is an experiment-owned candidate directory, verified to stay
        # under the optimization model root before replacing its contents.
        if bundle.resolve().parent != MODEL_ROOT.resolve():
            raise ValueError(f"refusing to replace a path outside transformer model root: {bundle}")
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    model.save_pretrained(bundle, safe_serialization=True)
    tokenizer.save_pretrained(bundle)
    metadata = {
        **spec,
        "label_order": list(LABEL_ORDER),
        "input_layout": spec["input_layout"],
        "prediction_mode": spec.get("task_mode", "flat"),
        "two_chunk_pooling": pooling,
        "checkpoint": checkpoint,
        "dev_metrics": results["dev_metrics_fixed_0_5"],
        "inference_batch_size": 16,
    }
    write_json(bundle / "candidate.json", metadata)
    files = [path for path in bundle.rglob("*") if path.is_file()]
    size_bytes = sum(path.stat().st_size for path in files)
    weights_bytes = sum(path.stat().st_size for path in files if path.name in {"model.safetensors", "pytorch_model.bin"})
    return weights_bytes, size_bytes


def _save_winner(model: Any, tokenizer: Any, spec: dict[str, Any], pooling: str,
                 checkpoint: dict[str, Any], results: dict[str, Any]) -> tuple[int, int]:
    return _save_bundle(MODEL_ROOT / "best", model, tokenizer, spec, pooling, checkpoint, results)


def _candidate_run(*, spec: dict[str, Any], train: list[dict[str, Any]], dev: list[dict[str, Any]],
                   train_encoded: list[list[list[int]]], dev_encoded: list[list[list[int]]],
                   tokenizer: Any, checkpoint: dict[str, Any], args: argparse.Namespace,
                   torch: Any, monitor_dev: bool = True,
                   fixed_pooling: str | None = None) -> tuple[dict[str, Any], list[list[float]], Any, str]:
    _seed_everything(args.seed, torch)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _make_model(CHECKPOINT_DIR, spec["trainable_region"], args.seed, torch).to(device)
    train_targets_cpu = torch.tensor(
        [[int(label in row["labels"]) for label in LABEL_ORDER] for row in train], dtype=torch.float32,
    )
    train_targets = train_targets_cpu.to(device)
    applied_weights, fit_weight_report = _fit_class_weights(train, spec["imbalance"], spec.get("weight_cap"))
    pos_weight = torch.tensor(applied_weights, dtype=torch.float32, device=device)
    criterion = torch.nn.BCEWithLogitsLoss(
        pos_weight=pos_weight[:8] if spec.get("task_mode") == "hierarchical" else pos_weight,
    )
    train_views = [(row_index, view_index) for row_index, views in enumerate(train_encoded)
                   for view_index in range(len(views))]
    if not train_views:
        raise ValueError("no encoded training views")
    sample_weights = _sampling_weights(train, train_views) if spec["imbalance"] == "balanced_batch" else None
    curriculum_mask = [_uses_exact_agreement_rule(row) for row in train]
    curriculum_view_indices = [index for index, (row_index, _) in enumerate(train_views)
                               if curriculum_mask[row_index]]
    curriculum_initial_epochs = int(spec.get("curriculum_initial_epochs", 2))
    if spec.get("curriculum") and not curriculum_view_indices:
        raise ValueError("no TRAIN rows match the exact-agreement curriculum acceptance rule")
    fit_tensors = {"views": train_views}
    trainable_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable_parameters, lr=spec["learning_rate"], weight_decay=0.01)
    generator = torch.Generator().manual_seed(args.seed)
    use_amp = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    expected_dev = [row["labels"] for row in dev]
    best_state = None
    best_metrics = None
    best_probs: list[list[float]] = []
    best_pooling = "mean"
    best_epoch = 0
    best_score = -1.0
    epochs_without_improvement = 0
    epoch_losses: list[float] = []
    epoch_dev: list[dict[str, float]] = []
    training_started = time.perf_counter()
    best_inference_seconds = 0.0

    for epoch in range(args.max_epochs):
        model.train()
        use_curriculum_subset = bool(spec.get("curriculum")) and epoch < curriculum_initial_epochs
        if use_curriculum_subset:
            epoch_views = [train_views[index] for index in curriculum_view_indices]
            epoch_weights = ([sample_weights[index] for index in curriculum_view_indices]
                             if sample_weights is not None else None)
        else:
            epoch_views = train_views
            epoch_weights = sample_weights
        if epoch_weights is None:
            order = torch.randperm(len(epoch_views), generator=generator).tolist()
        else:
            order = torch.multinomial(
                torch.tensor(epoch_weights, dtype=torch.double), len(epoch_views),
                replacement=True, generator=generator,
            ).tolist()
        epoch_loss = 0.0
        batch_count = 0
        for start in range(0, len(order), args.batch_size):
            selected = [epoch_views[order[index]] for index in range(start, min(start + args.batch_size, len(order)))]
            selected_sequences = [train_encoded[row_index][view_index] for row_index, view_index in selected]
            row_indices = [row_index for row_index, _ in selected]
            batch = _torch_inputs(tokenizer, selected_sequences, device, torch)
            targets = train_targets[row_indices]
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(**batch).logits
                loss = _loss_for(
                    logits, targets, criterion, spec["imbalance"],
                    float(spec.get("focal_gamma", 0.0)), spec.get("task_mode", "flat"), torch,
                )
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            epoch_loss += float(loss.detach().cpu())
            batch_count += 1
        epoch_losses.append(epoch_loss / max(batch_count, 1))

        if monitor_dev:
            evaluation_started = time.perf_counter()
            metrics, probabilities, pooling = _score_candidate(
                rows=dev, tokenizer=tokenizer, encoded=dev_encoded, model=model,
                device=device, torch=torch, batch_size=args.batch_size,
                allow_pooling=spec["input_layout"] == "two_chunk",
                mode=spec.get("task_mode", "flat"),
            )
            inference_seconds = time.perf_counter() - evaluation_started
            score = float(metrics["macro_f1"])
            epoch_dev.append({"epoch": epoch + 1, "macro_f1": score, "micro_f1": float(metrics["micro_f1"]), "pooling": pooling})
            stage = "exact-agreement" if use_curriculum_subset else "all-train"
            print(f"{spec['run_id']} epoch {epoch + 1}/{args.max_epochs} ({stage}): loss={epoch_losses[-1]:.5f} dev_macro_f1={score:.4f} dev_micro_f1={metrics['micro_f1']:.4f}", flush=True)
            if score > best_score + 1e-9:
                best_score = score
                best_epoch = epoch + 1
                best_metrics = metrics
                best_probs = probabilities
                best_pooling = pooling
                best_inference_seconds = inference_seconds
                best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1
            if epoch + 1 >= args.min_epochs and epochs_without_improvement >= args.patience:
                break
        else:
            print(f"{spec['run_id']} fixed TRAIN-fold epoch {epoch + 1}/{args.max_epochs}: loss={epoch_losses[-1]:.5f}", flush=True)

    training_seconds = time.perf_counter() - training_started
    if not monitor_dev:
        best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        best_epoch = args.max_epochs
        best_pooling = fixed_pooling or "mean"
    if best_state is None:
        raise RuntimeError("no checkpoint state was captured")
    model.load_state_dict(best_state)
    model.to(device)
    if not monitor_dev:
        best_metrics = None
        best_probs = _probabilities(model, tokenizer, dev_encoded, device, torch, args.batch_size, best_pooling)
        best_metrics = _metrics(dev, best_probs, spec.get("task_mode", "flat"))
    if best_metrics is None:
        raise RuntimeError("no checkpoint metrics were captured")
    if monitor_dev:
        if spec.get("task_mode") == "hierarchical":
            thresholds, threshold_report = benchmark.oof_thresholds(expected_dev, best_probs, mode="hierarchical")
        else:
            thresholds, threshold_report = tune_thresholds(expected_dev, best_probs)
        tuned_metrics = benchmark.score_probabilities(
            expected_dev, best_probs, thresholds=thresholds,
            mode=spec.get("task_mode", "flat"), fallback=False,
        )
    else:
        thresholds = [0.5] * len(LABEL_ORDER)
        threshold_report = {"method": "held-out fold labels not used for epoch or pooling selection"}
        tuned_metrics = best_metrics
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    trainable_count = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    report = {
        "run_id": spec["run_id"], "model": "distilbert-base-uncased multilabel sequence classifier",
        "features": {"input_layout": spec["input_layout"], "text": "subject + authored current message",
                     "prediction_mode": spec.get("task_mode", "flat")},
        "training_records": len(train), "dev_records": len(dev), "seed": args.seed,
        "hyperparameters": {**spec, "max_epochs": args.max_epochs, "selected_epoch": best_epoch,
                            "early_stopping": {"metric": "DEV macro F1 at fixed 0.5 thresholds" if monitor_dev else "none; fixed from full-train DEV selection",
                                               "patience": args.patience,
                                               "minimum_epochs": args.min_epochs}},
        "loss": ("hierarchical scope BCE plus project-only function BCE" if spec.get("task_mode") == "hierarchical"
                 else "binary focal loss" if spec["imbalance"] == "focal" else "BCEWithLogitsLoss"),
        "fit_only_weight_report": fit_weight_report,
        "curriculum": ({
            "enabled": True,
            "initial_epochs": curriculum_initial_epochs,
            "initial_acceptance_rule": EXACT_AGREEMENT_RULE,
            "initial_fit_records": sum(curriculum_mask),
            "subsequent_stage": "all TRAIN records",
            "total_epoch_budget": args.max_epochs,
        } if spec.get("curriculum") else {"enabled": False}),
        "threshold_method": "fixed_0.5; DEV-tuned independent F1 thresholds recorded for exploration only",
        "dev_metrics_fixed_0_5": best_metrics,
        "dev_metrics_dev_tuned": tuned_metrics,
        "dev_thresholds": {label: value for label, value in zip(LABEL_ORDER, thresholds)},
        "threshold_detail": threshold_report,
        "epoch_losses": epoch_losses, "epoch_dev": epoch_dev,
        "training_seconds": training_seconds,
        "inference_seconds_dev": best_inference_seconds if monitor_dev else None,
        "inference_ms_per_record_dev": (
            1000 * best_inference_seconds / len(dev) if monitor_dev and dev else None
        ),
        "selected_two_chunk_pooling": best_pooling,
        "trainable_parameters": trainable_count, "total_parameters": parameter_count,
        "model_weights_size_bytes": None, "model_package_size_bytes": None,
        "device": str(device), "attention_implementation": "eager",
        "checkpoint_revision": checkpoint["revision"],
    }
    return report, best_probs, model, best_pooling


def _grid() -> list[dict[str, Any]]:
    result = []
    for region in ("head_only", "last_block", "last_2_blocks", "full_encoder"):
        for learning_rate in (1e-5, 2e-5, 3e-5):
            run_id = f"{region}_lr{learning_rate:.0e}_unweighted_head512"
            result.append({"run_id": run_id, "trainable_region": region, "learning_rate": learning_rate,
                           "imbalance": "none", "input_layout": "head512"})
    return result


def _best_key(run: dict[str, Any]) -> tuple[float, float, float]:
    metrics = run["dev_metrics_fixed_0_5"]
    return (metrics["macro_f1"], metrics["micro_f1"], metrics["exact_set_accuracy"])


def _run_grouped_oof_thresholds(train: list[dict[str, Any]], tokenizer: Any,
                                checkpoint: dict[str, Any], args: argparse.Namespace,
                                torch: Any) -> dict[str, Any]:
    if not REPORT_PATH.is_file():
        raise FileNotFoundError("complete DEV selection before generating TRAIN-only OOF thresholds")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    champion = next((run for run in report.get("runs", [])
                     if run.get("run_id") == report.get("selected_run_id")), None)
    if champion is None:
        raise ValueError("transformer registry has no selected DEV candidate")
    bundle = MODEL_ROOT / "best"
    metadata_path = bundle / "candidate.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"selected candidate bundle is missing: {bundle}")
    candidate_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if candidate_metadata.get("run_id") != champion["run_id"]:
        raise ValueError("saved candidate bundle does not match the DEV-selected registry run")

    hyper = champion["hyperparameters"]
    spec = {key: hyper[key] for key in (
        "run_id", "trainable_region", "learning_rate", "imbalance", "input_layout",
        "weight_cap", "focal_gamma", "task_mode",
    ) if key in hyper}
    fixed_epochs = int(hyper["selected_epoch"])
    layout = spec["input_layout"]
    train_encoded, train_profile = _encode_rows(tokenizer, train, layout)
    folds = benchmark.cv_splits(train)
    oof_probabilities: list[list[float] | None] = [None] * len(train)
    fold_reports = []
    for fold_number, (fit_indices, heldout_indices) in enumerate(folds, 1):
        fit_rows = [train[int(index)] for index in fit_indices]
        heldout_rows = [train[int(index)] for index in heldout_indices]
        _validate_partition_boundary(fit_rows, heldout_rows)
        fit_encoded = [train_encoded[int(index)] for index in fit_indices]
        heldout_encoded = [train_encoded[int(index)] for index in heldout_indices]
        fold_args = argparse.Namespace(
            seed=args.seed + fold_number, batch_size=args.batch_size,
            max_epochs=fixed_epochs, min_epochs=fixed_epochs, patience=999,
        )
        fold_run, fold_probs, fold_model, _ = _candidate_run(
            spec=spec, train=fit_rows, dev=heldout_rows,
            train_encoded=fit_encoded, dev_encoded=heldout_encoded,
            tokenizer=tokenizer, checkpoint=checkpoint, args=fold_args,
            torch=torch, monitor_dev=False,
            fixed_pooling=candidate_metadata.get("two_chunk_pooling", "mean"),
        )
        for index, probabilities in zip(heldout_indices, fold_probs):
            oof_probabilities[int(index)] = probabilities
        fold_report = {
            "fold": fold_number,
            "fit_records": len(fit_rows),
            "heldout_train_records": len(heldout_rows),
            "heldout_fixed_0_5_metrics": fold_run["dev_metrics_fixed_0_5"],
            "training_seconds": fold_run["training_seconds"],
            "epochs": fixed_epochs,
            "selection": "epoch and input pooling fixed from full TRAIN/DEV run; heldout fold labels did not control training",
        }
        fold_reports.append(fold_report)
        partial = [
            {"email_id": row["email_id"], "probabilities": dict(zip(LABEL_ORDER, values))}
            for row, values in zip(train, oof_probabilities) if values is not None
        ]
        write_jsonl(RESULTS_DIR / "train_oof.partial.jsonl", partial)
        print(f"TRAIN OOF fold {fold_number}/{len(folds)}: macro_f1={fold_run['dev_metrics_fixed_0_5']['macro_f1']:.4f} records={len(heldout_rows)}", flush=True)
        del fold_model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    if any(values is None for values in oof_probabilities):
        raise RuntimeError("grouped CV did not produce an OOF prediction for every TRAIN row")
    complete_probs = [values for values in oof_probabilities if values is not None]
    expected = [row["labels"] for row in train]
    thresholds, threshold_detail = benchmark.oof_thresholds(
        expected, complete_probs, mode=spec.get("task_mode", "flat"),
    )
    fixed_metrics = benchmark.score_probabilities(expected, complete_probs, mode=spec.get("task_mode", "flat"))
    thresholded_metrics = benchmark.score_probabilities(
        expected, complete_probs, thresholds=thresholds,
        mode=spec.get("task_mode", "flat"), fallback=False,
    )
    prediction_rows = [
        {"email_id": row["email_id"], "probabilities": dict(zip(LABEL_ORDER, values))}
        for row, values in zip(train, complete_probs)
    ]
    write_jsonl(RESULTS_DIR / "train_oof.jsonl", prediction_rows)
    (RESULTS_DIR / "train_oof.partial.jsonl").unlink(missing_ok=True)
    oof_report = {
        "method": "5-fold grouped TRAIN out-of-fold probabilities; thresholds optimized on the combined OOF probabilities",
        "rows": len(train), "folds": fold_reports,
        "token_profile_train": train_profile,
        "fixed_0_5_metrics_on_oof_rows": fixed_metrics,
        "thresholded_metrics_on_same_oof_rows_not_an_unbiased_score": thresholded_metrics,
        "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
        "threshold_detail": threshold_detail,
        "probabilities_path": str((RESULTS_DIR / "train_oof.jsonl").relative_to(REPO_DIR)),
        "threshold_source": "TRAIN only",
        "test_opened": False,
    }
    report["train_oof_thresholds"] = oof_report
    candidate_metadata["threshold_method"] = "grouped_5fold_train_oof_binary_f1"
    candidate_metadata["thresholds_by_label_order"] = dict(zip(LABEL_ORDER, thresholds))
    candidate_metadata["threshold_prediction_mode"] = spec.get("task_mode", "flat")
    candidate_metadata["fallback"] = False
    write_json(metadata_path, candidate_metadata)
    write_json(REPORT_PATH, report)
    write_json(RESULTS_DIR / "runs.json", report)
    return oof_report


def _run_oof_shortlisted_candidates(train: list[dict[str, Any]], dev: list[dict[str, Any]],
                                    tokenizer: Any, checkpoint: dict[str, Any],
                                    args: argparse.Namespace, torch: Any) -> dict[str, Any]:
    """Refit DEV-shortlisted flat/hierarchical candidates and calibrate on TRAIN OOF."""
    if not REPORT_PATH.is_file():
        raise FileNotFoundError("complete DEV model selection before generating TRAIN-only OOF thresholds")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if report.get("data", {}).get("train_sha256") != sha256_file(TRAIN_PATH):
        raise ValueError("TRAIN partition hash differs from the model-selection registry")
    if report.get("data", {}).get("dev_sha256") != sha256_file(DEV_PATH):
        raise ValueError("DEV partition hash differs from the model-selection registry")
    runs = report.get("runs", [])
    def tuned_key(run: dict[str, Any]) -> tuple[float, float, float]:
        metrics = run["dev_metrics_dev_tuned"]
        return (metrics["macro_f1"], metrics["micro_f1"], metrics["exact_set_accuracy"])

    candidates: list[tuple[str, dict[str, Any]]] = []
    for mode, role in (("flat", "flat"), ("hierarchical", "hierarchical")):
        eligible = [run for run in runs
                    if run.get("features", {}).get("prediction_mode", "flat") == mode
                    and run.get("hyperparameters", {}).get("task_mode", "flat") == mode]
        if eligible:
            candidates.append((role, max(eligible, key=tuned_key)))
    if not candidates:
        raise ValueError("no flat or hierarchical DEV candidate is available for OOF calibration")

    folds = benchmark.cv_splits(train)
    candidate_results: dict[str, Any] = {}
    candidate_refs: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for candidate_index, (role, selected) in enumerate(candidates):
        hyper = selected["hyperparameters"]
        spec = {key: hyper[key] for key in (
            "run_id", "trainable_region", "learning_rate", "imbalance", "input_layout",
            "weight_cap", "focal_gamma", "task_mode", "curriculum",
            "curriculum_initial_epochs", "high_confidence_acceptance_rule", "curriculum_baseline_run_id",
        ) if key in hyper}
        layout = spec["input_layout"]
        train_encoded, train_profile = _encode_rows(tokenizer, train, layout)
        dev_encoded, dev_profile = _encode_rows(tokenizer, dev, layout)
        full_args = argparse.Namespace(
            seed=int(selected["seed"]), batch_size=args.batch_size,
            max_epochs=int(hyper["max_epochs"]),
            min_epochs=int(hyper.get("early_stopping", {}).get("minimum_epochs", 3)),
            patience=int(hyper.get("early_stopping", {}).get("patience", 2)),
        )
        refit_run, dev_probs, model, pooling = _candidate_run(
            spec=spec, train=train, dev=dev,
            train_encoded=train_encoded, dev_encoded=dev_encoded,
            tokenizer=tokenizer, checkpoint=checkpoint,
            args=full_args, torch=torch, monitor_dev=True,
        )
        same_epoch = refit_run["hyperparameters"]["selected_epoch"] == hyper["selected_epoch"]
        same_dev_macro = abs(
            refit_run["dev_metrics_fixed_0_5"]["macro_f1"]
            - selected["dev_metrics_fixed_0_5"]["macro_f1"]
        ) < 1e-6
        bundle = MODEL_ROOT / f"{role}_candidate"
        weights_bytes, package_bytes = _save_bundle(bundle, model, tokenizer, spec, pooling, checkpoint, refit_run)
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        oof_probabilities: list[list[float] | None] = [None] * len(train)
        fold_reports = []
        fixed_epochs = int(refit_run["hyperparameters"]["selected_epoch"])
        for fold_number, (fit_indices, heldout_indices) in enumerate(folds, 1):
            fit_rows = [train[int(index)] for index in fit_indices]
            heldout_rows = [train[int(index)] for index in heldout_indices]
            _validate_partition_boundary(fit_rows, heldout_rows)
            fit_encoded = [train_encoded[int(index)] for index in fit_indices]
            heldout_encoded = [train_encoded[int(index)] for index in heldout_indices]
            fold_args = argparse.Namespace(
                seed=int(selected["seed"]) + fold_number, batch_size=args.batch_size,
                max_epochs=fixed_epochs, min_epochs=fixed_epochs, patience=999,
            )
            fold_run, fold_probs, fold_model, _ = _candidate_run(
                spec=spec, train=fit_rows, dev=heldout_rows,
                train_encoded=fit_encoded, dev_encoded=heldout_encoded,
                tokenizer=tokenizer, checkpoint=checkpoint, args=fold_args,
                torch=torch, monitor_dev=False, fixed_pooling=pooling,
            )
            for index, probabilities in zip(heldout_indices, fold_probs):
                oof_probabilities[int(index)] = probabilities
            fold_reports.append({
                "fold": fold_number, "fit_records": len(fit_rows),
                "heldout_train_records": len(heldout_rows), "epochs": fixed_epochs,
                "fixed_0_5_metrics": fold_run["dev_metrics_fixed_0_5"],
                "training_seconds": fold_run["training_seconds"],
                "heldout_labels_not_used_for_epoch_or_pooling_selection": True,
            })
            partial = [
                {"email_id": row["email_id"], "probabilities": dict(zip(LABEL_ORDER, values))}
                for row, values in zip(train, oof_probabilities) if values is not None
            ]
            write_jsonl(RESULTS_DIR / f"train_oof_{role}.partial.jsonl", partial)
            print(f"{role} TRAIN OOF fold {fold_number}/{len(folds)}: macro_f1={fold_run['dev_metrics_fixed_0_5']['macro_f1']:.4f}", flush=True)
            del fold_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        if any(values is None for values in oof_probabilities):
            raise RuntimeError(f"{role} grouped CV missed one or more TRAIN rows")
        complete_probs = [values for values in oof_probabilities if values is not None]
        expected_train = [row["labels"] for row in train]
        mode = spec.get("task_mode", "flat")
        thresholds, threshold_detail = benchmark.oof_thresholds(expected_train, complete_probs, mode=mode)
        train_oof_fixed = benchmark.score_probabilities(expected_train, complete_probs, mode=mode)
        train_oof_at_thresholds = benchmark.score_probabilities(
            expected_train, complete_probs, thresholds=thresholds, mode=mode, fallback=False,
        )
        dev_oof_threshold_metrics = benchmark.score_probabilities(
            [row["labels"] for row in dev], dev_probs,
            thresholds=thresholds, mode=mode, fallback=False,
        )
        oof_path = RESULTS_DIR / f"train_oof_{role}.jsonl"
        write_jsonl(oof_path, [
            {"email_id": row["email_id"], "probabilities": dict(zip(LABEL_ORDER, values))}
            for row, values in zip(train, complete_probs)
        ])
        (RESULTS_DIR / f"train_oof_{role}.partial.jsonl").unlink(missing_ok=True)
        candidate_metadata = json.loads((bundle / "candidate.json").read_text(encoding="utf-8"))
        candidate_metadata.update({
            "threshold_method": "grouped_5fold_train_oof_binary_f1",
            "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
            "threshold_prediction_mode": mode,
            "fallback": False,
        })
        write_json(bundle / "candidate.json", candidate_metadata)
        selected["train_oof_thresholds"] = {
            "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
            "threshold_detail": threshold_detail,
            "threshold_source": "TRAIN only",
            "grouped_folds": len(folds),
            "fixed_0_5_metrics_on_oof_rows": train_oof_fixed,
            "thresholded_metrics_on_same_oof_rows_not_an_unbiased_score": train_oof_at_thresholds,
            "heldout_dev_metrics_at_train_oof_thresholds": dev_oof_threshold_metrics,
            "dev_exploratory_tuned_thresholds_not_used": True,
            "probabilities_path": str(oof_path.relative_to(REPO_DIR)),
        }
        selected["dev_metrics_train_oof_thresholds"] = dev_oof_threshold_metrics
        selected["refit_reproduction_check"] = {
            "selected_epoch_matches_recorded_dev_run": same_epoch,
            "fixed_threshold_dev_macro_matches_recorded_run": same_dev_macro,
            "package_size_bytes": package_bytes,
            "weights_size_bytes": weights_bytes,
        }
        candidate_results[role] = {
            "run_id": selected["run_id"],
            "candidate_bundle": str(bundle.relative_to(REPO_DIR)),
            "mode": mode,
            "selected_epoch": fixed_epochs,
            "dev_metrics_fixed_0_5": refit_run["dev_metrics_fixed_0_5"],
            "dev_metrics_train_oof_thresholds": dev_oof_threshold_metrics,
            "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
            "oof_fold_metrics": fold_reports,
            "train_oof_probability_count": len(complete_probs),
            "refit_reproduction_check": selected["refit_reproduction_check"],
            "test_opened": False,
        }
        candidate_refs.append((selected, role, candidate_results[role]))

    champion, role, champion_summary = max(
        candidate_refs,
        key=lambda item: (item[2]["dev_metrics_train_oof_thresholds"]["macro_f1"],
                          item[2]["dev_metrics_train_oof_thresholds"]["micro_f1"]),
    )
    oof_report = {
        "method": "5-fold grouped TRAIN OOF probabilities; per-label cutoffs learned on combined TRAIN OOF only",
        "shortlist_method": "best flat and best hierarchical candidate by exploratory DEV-tuned macro F1; DEV-tuned cutoffs are not final",
        "candidates": candidate_results,
        "selected_after_train_oof_threshold_dev_comparison": {
            "run_id": champion["run_id"], "mode": role,
            "candidate_bundle": champion_summary["candidate_bundle"],
            "dev_macro_f1": champion_summary["dev_metrics_train_oof_thresholds"]["macro_f1"],
            "dev_micro_f1": champion_summary["dev_metrics_train_oof_thresholds"]["micro_f1"],
        },
        "threshold_source": "TRAIN only",
        "test_opened": False,
    }
    report["train_oof_thresholds"] = oof_report
    report["selected_run_id"] = champion["run_id"]
    report["candidate_bundle"] = champion_summary["candidate_bundle"]
    write_json(REPORT_PATH, report)
    write_json(RESULTS_DIR / "runs.json", report)
    return oof_report


def _run_cap5_oof_candidate(train: list[dict[str, Any]], dev: list[dict[str, Any]],
                            tokenizer: Any, checkpoint: dict[str, Any],
                            args: argparse.Namespace, torch: Any) -> dict[str, Any]:
    """Add the controlled full-encoder capped-5 candidate to TRAIN OOF results."""
    if not REPORT_PATH.is_file():
        raise FileNotFoundError("run the transformer core and ablation phases before cap5 OOF")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if report.get("data", {}).get("train_sha256") != sha256_file(TRAIN_PATH):
        raise ValueError("TRAIN partition hash differs from the model-selection registry")
    if report.get("data", {}).get("dev_sha256") != sha256_file(DEV_PATH):
        raise ValueError("DEV partition hash differs from the model-selection registry")
    matches = [run for run in report.get("runs", [])
               if run.get("hyperparameters", {}).get("trainable_region") == "full_encoder"
               and float(run.get("hyperparameters", {}).get("learning_rate", 0)) == 3e-5
               and run.get("hyperparameters", {}).get("imbalance") == "capped"
               and float(run.get("hyperparameters", {}).get("weight_cap", 0)) == 5.0
               and not run.get("hyperparameters", {}).get("curriculum")
               and run.get("hyperparameters", {}).get("task_mode", "flat") == "flat"]
    if len(matches) != 1:
        raise ValueError(f"expected one no-curriculum full-encoder cap5 run, found {len(matches)}")
    selected = matches[0]
    role = "capped5"
    hyper = selected["hyperparameters"]
    spec = {key: hyper[key] for key in (
        "run_id", "trainable_region", "learning_rate", "imbalance", "input_layout",
        "weight_cap", "focal_gamma", "task_mode", "curriculum",
        "curriculum_initial_epochs", "high_confidence_acceptance_rule",
    ) if key in hyper}
    train_encoded, _ = _encode_rows(tokenizer, train, spec["input_layout"])
    dev_encoded, _ = _encode_rows(tokenizer, dev, spec["input_layout"])
    full_args = argparse.Namespace(
        seed=int(selected["seed"]), batch_size=args.batch_size,
        max_epochs=int(hyper["max_epochs"]),
        min_epochs=int(hyper.get("early_stopping", {}).get("minimum_epochs", 3)),
        patience=int(hyper.get("early_stopping", {}).get("patience", 2)),
    )
    refit_run, dev_probs, model, pooling = _candidate_run(
        spec=spec, train=train, dev=dev,
        train_encoded=train_encoded, dev_encoded=dev_encoded,
        tokenizer=tokenizer, checkpoint=checkpoint,
        args=full_args, torch=torch, monitor_dev=True,
    )
    same_epoch = refit_run["hyperparameters"]["selected_epoch"] == hyper["selected_epoch"]
    same_dev_macro = abs(
        refit_run["dev_metrics_fixed_0_5"]["macro_f1"] - selected["dev_metrics_fixed_0_5"]["macro_f1"]
    ) < 1e-6
    bundle = MODEL_ROOT / f"{role}_candidate"
    weights_bytes, package_bytes = _save_bundle(bundle, model, tokenizer, spec, pooling, checkpoint, refit_run)
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    folds = benchmark.cv_splits(train)
    fixed_epochs = int(refit_run["hyperparameters"]["selected_epoch"])
    oof_probabilities: list[list[float] | None] = [None] * len(train)
    fold_reports = []
    for fold_number, (fit_indices, heldout_indices) in enumerate(folds, 1):
        fit_rows = [train[int(index)] for index in fit_indices]
        heldout_rows = [train[int(index)] for index in heldout_indices]
        _validate_partition_boundary(fit_rows, heldout_rows)
        fold_args = argparse.Namespace(
            seed=int(selected["seed"]) + fold_number, batch_size=args.batch_size,
            max_epochs=fixed_epochs, min_epochs=fixed_epochs, patience=999,
        )
        fold_run, fold_probs, fold_model, _ = _candidate_run(
            spec=spec, train=fit_rows, dev=heldout_rows,
            train_encoded=[train_encoded[int(index)] for index in fit_indices],
            dev_encoded=[train_encoded[int(index)] for index in heldout_indices],
            tokenizer=tokenizer, checkpoint=checkpoint, args=fold_args,
            torch=torch, monitor_dev=False, fixed_pooling=pooling,
        )
        for index, probabilities in zip(heldout_indices, fold_probs):
            oof_probabilities[int(index)] = probabilities
        fold_reports.append({
            "fold": fold_number, "fit_records": len(fit_rows),
            "heldout_train_records": len(heldout_rows), "epochs": fixed_epochs,
            "fixed_0_5_metrics": fold_run["dev_metrics_fixed_0_5"],
            "training_seconds": fold_run["training_seconds"],
            "heldout_labels_not_used_for_epoch_or_pooling_selection": True,
        })
        partial = [
            {"email_id": row["email_id"], "probabilities": dict(zip(LABEL_ORDER, values))}
            for row, values in zip(train, oof_probabilities) if values is not None
        ]
        write_jsonl(RESULTS_DIR / f"train_oof_{role}.partial.jsonl", partial)
        print(f"{role} TRAIN OOF fold {fold_number}/{len(folds)}: macro_f1={fold_run['dev_metrics_fixed_0_5']['macro_f1']:.4f}", flush=True)
        del fold_model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    if any(values is None for values in oof_probabilities):
        raise RuntimeError("capped5 grouped CV missed one or more TRAIN rows")
    complete_probs = [values for values in oof_probabilities if values is not None]
    expected_train = [row["labels"] for row in train]
    thresholds, threshold_detail = benchmark.oof_thresholds(expected_train, complete_probs, mode="flat")
    train_oof_fixed = benchmark.score_probabilities(expected_train, complete_probs, mode="flat")
    train_oof_thresholded = benchmark.score_probabilities(
        expected_train, complete_probs, thresholds=thresholds, mode="flat", fallback=False,
    )
    dev_oof_threshold_metrics = benchmark.score_probabilities(
        [row["labels"] for row in dev], dev_probs,
        thresholds=thresholds, mode="flat", fallback=False,
    )
    oof_path = RESULTS_DIR / f"train_oof_{role}.jsonl"
    write_jsonl(oof_path, [
        {"email_id": row["email_id"], "probabilities": dict(zip(LABEL_ORDER, values))}
        for row, values in zip(train, complete_probs)
    ])
    (RESULTS_DIR / f"train_oof_{role}.partial.jsonl").unlink(missing_ok=True)
    candidate_metadata = json.loads((bundle / "candidate.json").read_text(encoding="utf-8"))
    candidate_metadata.update({
        "threshold_method": "grouped_5fold_train_oof_binary_f1",
        "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
        "threshold_prediction_mode": "flat", "fallback": False,
    })
    write_json(bundle / "candidate.json", candidate_metadata)
    selected["train_oof_thresholds"] = {
        "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
        "threshold_detail": threshold_detail, "threshold_source": "TRAIN only",
        "grouped_folds": len(folds), "fixed_0_5_metrics_on_oof_rows": train_oof_fixed,
        "thresholded_metrics_on_same_oof_rows_not_an_unbiased_score": train_oof_thresholded,
        "heldout_dev_metrics_at_train_oof_thresholds": dev_oof_threshold_metrics,
        "dev_exploratory_tuned_thresholds_not_used": True,
        "probabilities_path": str(oof_path.relative_to(REPO_DIR)),
    }
    selected["dev_metrics_train_oof_thresholds"] = dev_oof_threshold_metrics
    selected["refit_reproduction_check"] = {
        "selected_epoch_matches_recorded_dev_run": same_epoch,
        "fixed_threshold_dev_macro_matches_recorded_run": same_dev_macro,
        "package_size_bytes": package_bytes, "weights_size_bytes": weights_bytes,
    }
    capped5_result = {
        "run_id": selected["run_id"],
        "candidate_bundle": str(bundle.relative_to(REPO_DIR)), "mode": "flat",
        "selected_epoch": fixed_epochs,
        "dev_metrics_fixed_0_5": refit_run["dev_metrics_fixed_0_5"],
        "dev_metrics_train_oof_thresholds": dev_oof_threshold_metrics,
        "thresholds_by_label_order": dict(zip(LABEL_ORDER, thresholds)),
        "oof_fold_metrics": fold_reports,
        "train_oof_probability_count": len(complete_probs),
        "refit_reproduction_check": selected["refit_reproduction_check"],
        "test_opened": False,
    }
    previous_oof = report.setdefault("train_oof_thresholds", {})
    previous_candidates = previous_oof.setdefault("candidates", {})
    previous_candidates[role] = capped5_result
    champion_role, champion_summary = max(
        previous_candidates.items(),
        key=lambda item: (item[1]["dev_metrics_train_oof_thresholds"]["macro_f1"],
                          item[1]["dev_metrics_train_oof_thresholds"]["micro_f1"]),
    )
    champion = next(run for run in report["runs"] if run["run_id"] == champion_summary["run_id"])
    previous_oof["shortlist_method"] += "; capped-5 full-encoder ablation added by controlled request"
    previous_oof["selected_after_train_oof_threshold_dev_comparison"] = {
        "run_id": champion["run_id"], "mode": champion_summary["mode"],
        "candidate_bundle": champion_summary["candidate_bundle"],
        "dev_macro_f1": champion_summary["dev_metrics_train_oof_thresholds"]["macro_f1"],
        "dev_micro_f1": champion_summary["dev_metrics_train_oof_thresholds"]["micro_f1"],
    }
    previous_oof["threshold_source"] = "TRAIN only"
    previous_oof["test_opened"] = False
    report["selected_run_id"] = champion["run_id"]
    report["candidate_bundle"] = champion_summary["candidate_bundle"]
    write_json(REPORT_PATH, report)
    write_json(RESULTS_DIR / "runs.json", report)
    return {"threshold_source": "TRAIN only", "capped5_candidate": capped5_result,
            "selected_after_train_oof_threshold_dev_comparison": previous_oof["selected_after_train_oof_threshold_dev_comparison"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=TRAIN_PATH)
    parser.add_argument("--dev", type=Path, default=DEV_PATH)
    parser.add_argument("--phase", choices=("core", "ablations", "curriculum", "oof", "cap5_oof"), default="core")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-epochs", type=int, default=8)
    parser.add_argument("--min-epochs", type=int, default=3)
    parser.add_argument("--patience", type=int, default=2)
    args = parser.parse_args()
    if args.max_epochs < args.min_epochs or args.min_epochs < 1:
        raise ValueError("epoch limits must satisfy max_epochs >= min_epochs >= 1")
    if args.train.resolve() != TRAIN_PATH.resolve():
        raise ValueError("only ai/data/experiments/optimization_20261002/train.jsonl is a training input")
    if not args.train.is_file():
        raise FileNotFoundError("the approved train.jsonl partition is not ready")
    if args.phase != "oof":
        if args.dev.resolve() != DEV_PATH.resolve() or not args.dev.is_file():
            raise ValueError("only the approved ai/data/experiments/optimization_20261002/dev.jsonl is a DEV input")
        train = _read_partition(args.train, TRAIN_PATH, "train")
        dev = _read_partition(args.dev, DEV_PATH, "dev")
        _validate_partition_boundary(train, dev)
    else:
        train = _read_partition(args.train, TRAIN_PATH, "train")
        if args.dev.resolve() != DEV_PATH.resolve() or not args.dev.is_file():
            raise ValueError("OOF-threshold DEV scoring may load only the approved DEV partition")
        dev = _read_partition(args.dev, DEV_PATH, "dev")
        _validate_partition_boundary(train, dev)
    checkpoint = _verify_upstream_checkpoint()
    try:
        import torch
        import transformers
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install the configured optional torch/transformers runtime before training") from exc

    _seed_everything(args.seed, torch)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT_DIR, use_fast=True, local_files_only=True)
    if args.phase == "oof":
        oof_report = _run_oof_shortlisted_candidates(train, dev, tokenizer, checkpoint, args, torch)
        print(json.dumps({"threshold_source": oof_report["threshold_source"],
                          "selected_after_oof": oof_report["selected_after_train_oof_threshold_dev_comparison"],
                          "report": str(REPORT_PATH.relative_to(REPO_DIR))}, indent=2), flush=True)
        return 0
    if args.phase == "cap5_oof":
        oof_report = _run_cap5_oof_candidate(train, dev, tokenizer, checkpoint, args, torch)
        print(json.dumps(oof_report, indent=2), flush=True)
        return 0
    report = {
        "scope": "AI-SILVER DIAGNOSTIC PERFORMANCE; not human, gold, or production accuracy.",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "family": "partial DistilBERT fine-tuning",
        "checkpoint": checkpoint,
        "data": {
            "train_path": str(TRAIN_PATH.relative_to(REPO_DIR)), "train_sha256": sha256_file(TRAIN_PATH),
            "dev_path": str(DEV_PATH.relative_to(REPO_DIR)), "dev_sha256": sha256_file(DEV_PATH),
            "text_free_benchmark_sha256": benchmark.benchmark_hash(),
            "train_records": len(train), "dev_records": len(dev),
            "train_labels": {label: sum(label in row["labels"] for row in train) for label in LABEL_ORDER},
            "dev_labels": {label: sum(label in row["labels"] for row in dev) for label in LABEL_ORDER},
            "train_dev_email_ids_disjoint": True,
            "train_dev_threads_disjoint": True,
            "train_dev_leakage_groups_disjoint": True,
            "text_source": "canonical authored subject + current message from approved train/dev partitions only",
            "test_opened": False,
        },
        "runtime": {"python": platform.python_version(), "torch": torch.__version__,
                    "transformers": transformers.__version__, "cuda": torch.version.cuda,
                    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                    "seed": args.seed, "attention_implementation": "eager"},
        "grid": {"phase": args.phase, "regions": ["head_only", "last_block", "last_2_blocks", "full_encoder"],
                 "learning_rates": [1e-5, 2e-5, 3e-5], "epochs": [args.min_epochs, args.max_epochs],
                 "early_stopping": "DEV macro F1, fixed 0.5 thresholds"},
        "runs": [],
        "selected_run_id": None,
        "candidate_bundle": None,
    }
    all_specs = _grid()
    if args.phase == "core":
        specs = all_specs
    elif args.phase == "ablations":
        previous = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        previous_runs = previous.get("runs", [])
        core_runs = [row for row in previous_runs if row.get("features", {}).get("input_layout") == "head512"
                     and row.get("hyperparameters", {}).get("imbalance") == "none"
                     and row.get("hyperparameters", {}).get("task_mode", "flat") == "flat"]
        if not core_runs:
            raise ValueError("run the core phase before imbalance/long-input ablations")
        champion = max(core_runs, key=_best_key)
        champion_hp = champion["hyperparameters"]
        base = {"trainable_region": champion_hp["trainable_region"],
                "learning_rate": champion_hp["learning_rate"]}
        specs = []
        for imbalance, cap, gamma in (("sqrt", None, None), ("capped", 3.0, None),
                                      ("capped", 5.0, None), ("capped", 8.0, None),
                                      ("focal", None, 1.0), ("focal", None, 2.0),
                                      ("balanced_batch", None, None)):
            extra = {"trainable_region": base["trainable_region"], "learning_rate": base["learning_rate"],
                     "imbalance": imbalance, "input_layout": "head512"}
            if cap is not None:
                extra["weight_cap"] = cap
            if gamma is not None:
                extra["focal_gamma"] = gamma
            extra["run_id"] = f"{base['trainable_region']}_lr{base['learning_rate']:.0e}_{imbalance}{cap or gamma or ''}_head512"
            specs.append(extra)
        specs.extend([
            {**base, "run_id": f"{base['trainable_region']}_lr{base['learning_rate']:.0e}_none_headtail",
             "imbalance": "none", "input_layout": "head_tail_320_192"},
            {**base, "run_id": f"{base['trainable_region']}_lr{base['learning_rate']:.0e}_none_twochunk",
             "imbalance": "none", "input_layout": "two_chunk"},
            {**base, "run_id": f"{base['trainable_region']}_lr{base['learning_rate']:.0e}_hierarchical_head512",
             "imbalance": "none", "input_layout": "head512", "task_mode": "hierarchical"},
        ])
        report = previous
    elif args.phase == "curriculum":
        previous = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        eligible = [row for row in previous.get("runs", [])
                    if row.get("features", {}).get("input_layout") == "head512"
                    and row.get("features", {}).get("prediction_mode", "flat") == "flat"
                    and row.get("hyperparameters", {}).get("task_mode", "flat") == "flat"
                    and not row.get("hyperparameters", {}).get("curriculum")]
        if not eligible:
            raise ValueError("core and head512 imbalance ablations must be complete before curriculum")
        baseline = max(eligible, key=_best_key)
        prior_hyperparameters = baseline["hyperparameters"]
        spec = {key: prior_hyperparameters[key] for key in (
            "trainable_region", "learning_rate", "imbalance", "input_layout", "weight_cap", "focal_gamma",
        ) if key in prior_hyperparameters}
        spec.update({
            "run_id": f"{baseline['run_id']}_exact_agreement_curriculum",
            "curriculum": True,
            "curriculum_initial_epochs": 2,
            "high_confidence_acceptance_rule": EXACT_AGREEMENT_RULE,
            "curriculum_baseline_run_id": baseline["run_id"],
        })
        specs = [spec]
        report = previous
    else:
        specs = all_specs
    print(json.dumps({"train_records": len(train), "dev_records": len(dev), "runs": len(specs),
                      "checkpoint_revision": checkpoint["revision"],
                      "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"}, indent=2), flush=True)

    winner = None
    if REPORT_PATH.is_file() and args.phase in {"ablations", "curriculum"}:
        old = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        winner = next((item for item in old.get("runs", []) if item["run_id"] == old.get("selected_run_id")), None)
    elif REPORT_PATH.is_file() and args.phase == "core":
        old = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        if old.get("data", {}).get("train_sha256") == sha256_file(TRAIN_PATH) and old.get("data", {}).get("dev_sha256") == sha256_file(DEV_PATH):
            # A resumed core phase does not silently rerun already-recorded IDs.
            report["runs"] = old.get("runs", [])
            winner = next((item for item in report["runs"] if item["run_id"] == old.get("selected_run_id")), None)
    if winner is not None:
        # Retaining the selected bundle allows the next bounded phase to compare
        # its actual state with newly trained ablations.
        model_bundle = MODEL_ROOT / "best"
        if not model_bundle.is_dir():
            winner = None

    done_ids = {row["run_id"] for row in report.get("runs", [])}
    encoded_cache: dict[str, tuple[list[list[list[int]]], list[list[list[int]]], dict[str, Any], dict[str, Any]]] = {}
    for spec in specs:
        if spec["run_id"] in done_ids:
            print(f"Skipping recorded run {spec['run_id']}", flush=True)
            continue
        layout = spec["input_layout"]
        if layout not in encoded_cache:
            train_encoded, train_profile = _encode_rows(tokenizer, train, layout)
            dev_encoded, dev_profile = _encode_rows(tokenizer, dev, layout)
            encoded_cache[layout] = (train_encoded, dev_encoded, train_profile, dev_profile)
        train_encoded, dev_encoded, train_profile, dev_profile = encoded_cache[layout]
        started = time.perf_counter()
        run, dev_probs, model, pooling = _candidate_run(
            spec=spec, train=train, dev=dev, train_encoded=train_encoded,
            dev_encoded=dev_encoded, tokenizer=tokenizer, checkpoint=checkpoint,
            args=args, torch=torch,
        )
        run["token_profile"] = {"train": train_profile, "dev": dev_profile}
        run["wall_seconds_including_preprocessing"] = time.perf_counter() - started
        probabilities_path = RESULTS_DIR / "devprobs" / f"{spec['run_id']}.jsonl"
        write_jsonl(probabilities_path, [
            {"email_id": row["email_id"], "probabilities": {label: value for label, value in zip(LABEL_ORDER, probs)}}
            for row, probs in zip(dev, dev_probs)
        ])
        run["dev_probabilities_path"] = str(probabilities_path.relative_to(REPO_DIR))
        if winner is None or _best_key(run) > _best_key(winner):
            weights_bytes, package_bytes = _save_winner(model, tokenizer, spec, pooling, checkpoint, run)
            run["model_weights_size_bytes"] = weights_bytes
            run["model_package_size_bytes"] = package_bytes
            winner = run
            report["selected_run_id"] = spec["run_id"]
            report["candidate_bundle"] = str((MODEL_ROOT / "best").relative_to(REPO_DIR))
            print(f"New DEV champion: {spec['run_id']} macro_f1={run['dev_metrics_fixed_0_5']['macro_f1']:.4f}", flush=True)
        report["runs"].append(run)
        report["created_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(REPORT_PATH, report)
        write_json(RESULTS_DIR / "runs.json", report)
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # Make the within-phase winner explicit if an existing champion beat every
    # new run. The per-run records and saved bundle still reflect the same split.
    if report.get("runs"):
        if winner is None:
            winner = max(report["runs"], key=_best_key)
        report["selected_run_id"] = winner["run_id"]
        report["candidate_bundle"] = str((MODEL_ROOT / "best").relative_to(REPO_DIR))
    write_json(REPORT_PATH, report)
    write_json(RESULTS_DIR / "runs.json", report)
    print(json.dumps({"selected_run_id": report.get("selected_run_id"),
                      "selected_dev_macro_f1": _best_key(winner)[0] if winner else None,
                      "report": str(REPORT_PATH.relative_to(REPO_DIR)),
                      "model_bundle": report.get("candidate_bundle")}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

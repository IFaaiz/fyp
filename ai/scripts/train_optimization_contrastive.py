"""TRAIN-only SetFit-style supervised contrastive MiniLM ablation.

The encoder is reinitialized from the pinned official checkpoint for every
grouped TRAIN OOF fold. This keeps each OOF probability independent of that
row's labels; the same fixed one-epoch recipe is then refit on all TRAIN before
the single DEV evaluation. No TEST data is accessed.
"""
from __future__ import annotations

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

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

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
    IndependentBinaryHead, checkpoint_max_seq_length,
)
from src.models.transfer_diagnostic import sha256_file

EXPERIMENT_DIR = AI_DIR / "data/experiments/optimization_20261002/embeddings"
MODEL_DIR = AI_DIR / "data/models/optimization/embeddings"
CHECKPOINT_MANIFEST = AI_DIR / "data/cache/sentence-transformers/optimization_embedding_checkpoints.json"
RUN_ID = "minilm_supervised_contrastive_1epoch"
SEED = 20261004
TEMPERATURE = 0.07
EPOCHS = 1
BATCH_SIZE = 16
LEARNING_RATE = 2e-5


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _source_revision() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, check=True, text=True, capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _checkpoint() -> dict[str, Any]:
    rows = json.loads(CHECKPOINT_MANIFEST.read_text(encoding="utf-8"))
    for row in rows:
        if row["model_id"] == "sentence-transformers/all-MiniLM-L6-v2":
            return row
    raise FileNotFoundError("pinned MiniLM checkpoint is absent")


def _tokenize(rows: list[dict[str, Any]], tokenizer: Any, max_length: int) -> dict[str, Any]:
    import torch
    return tokenizer(
        texts(rows, view="subject_body"), add_special_tokens=True,
        truncation=True, max_length=max_length, padding="max_length",
        return_tensors="pt",
    )


def _encode(model: Any, encoded: dict[str, Any], *, device: Any, batch_size: int = 32) -> np.ndarray:
    import torch
    import torch.nn.functional as F

    model.eval()
    pieces = []
    with torch.inference_mode():
        for start in range(0, encoded["input_ids"].shape[0], batch_size):
            stop = min(start + batch_size, encoded["input_ids"].shape[0])
            batch = {key: value[start:stop].to(device) for key, value in encoded.items()}
            hidden = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pieces.append(F.normalize(pooled, p=2, dim=1).float().cpu().numpy())
    return np.concatenate(pieces, axis=0) if pieces else np.zeros((0, 0), dtype=np.float32)


def _train_one_epoch(
    model: Any, encoded: dict[str, Any], label_matrix: np.ndarray, *,
    torch: Any, device: Any, seed: int,
) -> dict[str, Any]:
    import torch.nn.functional as F

    random_state = torch.Generator().manual_seed(seed)
    labels = torch.as_tensor(label_matrix, dtype=torch.float32, device=device)
    cpu_inputs = {key: value for key, value in encoded.items()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
    model.train()
    total_loss = 0.0
    batches_with_positive = 0
    steps = 0
    order = torch.randperm(len(label_matrix), generator=random_state)
    for start in range(0, len(label_matrix), BATCH_SIZE):
        indices_cpu = order[start:start + BATCH_SIZE]
        if len(indices_cpu) < 2:
            continue
        indices = indices_cpu.to(device)
        batch = {key: value[indices_cpu].to(device) for key, value in cpu_inputs.items()}
        optimizer.zero_grad(set_to_none=True)
        hidden = model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        vectors = F.normalize(pooled, p=2, dim=1)
        logits = vectors @ vectors.T / TEMPERATURE
        diagonal = torch.eye(len(indices), dtype=torch.bool, device=device)
        logits = logits.masked_fill(diagonal, -1e9)

        batch_labels = labels[indices]
        intersection = batch_labels @ batch_labels.T
        totals = batch_labels.sum(dim=1)
        union = totals[:, None] + totals[None, :] - intersection
        positive_weight = torch.where(union > 0, intersection / union.clamp(min=1), torch.zeros_like(union))
        positive_weight = positive_weight.masked_fill(diagonal, 0.0)
        normalizer = torch.logsumexp(logits, dim=1, keepdim=True)
        log_probability = logits - normalizer
        positive_sum = positive_weight.sum(dim=1, keepdim=True)
        anchor_mask = positive_sum.squeeze(1) > 0
        if not bool(anchor_mask.any()):
            continue
        weights = positive_weight / positive_sum.clamp(min=1e-12)
        loss = -(weights * log_probability).sum(dim=1)[anchor_mask].mean()
        loss.backward()
        optimizer.step()
        total_loss += float(loss.detach().cpu())
        batches_with_positive += 1
        steps += 1
    return {
        "mean_loss": total_loss / max(batches_with_positive, 1),
        "optimizer_steps": steps,
        "batches_with_positive_pairs": batches_with_positive,
        "epoch": 1,
    }


def _new_tokenizer(checkpoint_dir: Path) -> Any:
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir, use_fast=True, local_files_only=True)
    return tokenizer


def _fit_phase() -> dict[str, Any]:
    import torch
    from transformers import AutoModel

    if not torch.cuda.is_available():
        raise RuntimeError("supervised contrastive MiniLM run is scheduled for the available CUDA GPU")
    train_rows = load_partition("train")
    dev_rows = load_partition("dev")
    y_train = targets(train_rows)
    expected_train = [row["labels"] for row in train_rows]
    expected_dev = [row["labels"] for row in dev_rows]
    checkpoint = _checkpoint()
    checkpoint_dir = Path(checkpoint["snapshot_path"])
    max_length, max_length_source = checkpoint_max_seq_length(checkpoint_dir)
    tokenizer = _new_tokenizer(checkpoint_dir)
    device = torch.device("cuda")
    encoded_train = _tokenize(train_rows, tokenizer, max_length)
    encoded_dev = _tokenize(dev_rows, tokenizer, max_length)
    cv_folds = cv_splits(train_rows)
    oof_probs = np.zeros((len(train_rows), len(LABEL_ORDER)), dtype=np.float64)
    fold_reports = []
    oof_started = time.perf_counter()

    for fold_number, (fit_indices, held_indices) in enumerate(cv_folds, 1):
        torch.manual_seed(SEED + fold_number)
        torch.cuda.manual_seed_all(SEED + fold_number)
        model = AutoModel.from_pretrained(checkpoint_dir, local_files_only=True)
        model.to(device)
        fold_started = time.perf_counter()
        loss_report = _train_one_epoch(
            model,
            {key: value[fit_indices] for key, value in encoded_train.items()},
            y_train[fit_indices], torch=torch, device=device, seed=SEED + fold_number,
        )
        fitted_features = _encode(model, {key: value[fit_indices] for key, value in encoded_train.items()}, device=device)
        held_features = _encode(model, {key: value[held_indices] for key, value in encoded_train.items()}, device=device)
        head = IndependentBinaryHead({"method": "logistic", "C": 1.0, "weighting": "none", "seed": SEED + fold_number})
        head.fit(fitted_features, y_train[fit_indices])
        oof_probs[held_indices] = head.predict_proba(held_features)
        fold_reports.append({
            "fold": fold_number,
            "train_records": len(fit_indices),
            "heldout_records": len(held_indices),
            "contrastive": loss_report,
            "fold_seconds": time.perf_counter() - fold_started,
            "encoder_refit_only_on_fold_train": True,
        })
        print(f"contrastive OOF fold {fold_number}/5: {loss_report['mean_loss']:.4f}; {fold_reports[-1]['fold_seconds']:.1f}s", flush=True)
        del model, head, fitted_features, held_features
        torch.cuda.empty_cache()
    oof_seconds = time.perf_counter() - oof_started
    thresholds, threshold_report = oof_thresholds(expected_train, oof_probs, mode="flat")

    final_started = time.perf_counter()
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    final_model = AutoModel.from_pretrained(checkpoint_dir, local_files_only=True)
    final_model.to(device)
    final_loss = _train_one_epoch(
        final_model, encoded_train, y_train, torch=torch, device=device, seed=SEED,
    )
    final_train_features = _encode(final_model, encoded_train, device=device)
    final_dev_features = _encode(final_model, encoded_dev, device=device)
    final_head = IndependentBinaryHead({"method": "logistic", "C": 1.0, "weighting": "none", "seed": SEED})
    final_head.fit(final_train_features, y_train)
    dev_started = time.perf_counter()
    dev_probs = final_head.predict_proba(final_dev_features)
    dev_inference_seconds = time.perf_counter() - dev_started
    final_training_seconds = time.perf_counter() - final_started - dev_inference_seconds
    dev_metrics = score_probabilities(expected_dev, dev_probs, thresholds, mode="flat")
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    latency_start = time.perf_counter()
    for _ in range(10):
        _ = _encode(final_model, {key: value[:1] for key, value in encoded_dev.items()}, device=device)
    single_record_latency_ms = (time.perf_counter() - latency_start) * 100.0

    encoder_dir = MODEL_DIR / "encoders" / "minilm_contrastive"
    encoder_dir.mkdir(parents=True, exist_ok=True)
    final_model.save_pretrained(encoder_dir, safe_serialization=True)
    tokenizer.save_pretrained(encoder_dir)
    for name in ("sentence_bert_config.json", "modules.json", "1_Pooling/config.json", "2_Normalize/config.json", "config_sentence_transformers.json"):
        source = checkpoint_dir / name
        if source.is_file():
            destination = encoder_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    bundle_dir = MODEL_DIR / "bundles" / "setfit_style_contrastive"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    heads_path = bundle_dir / "heads.joblib"
    joblib.dump(final_head, heads_path, compress=3)
    bundle_payload = {
        "scope": "AI-SILVER DIAGNOSTIC PERFORMANCE; not human/gold/production accuracy",
        "bundle_type": "single",
        "model_family": "TRAIN-only supervised contrastive MiniLM + independent logistic heads",
        "training_method": "in-batch supervised contrastive objective using Jaccard similarity between multi-label sets; SetFit-style equivalent; no DEV gradients",
        "encoder_path": os.path.relpath(encoder_dir, bundle_dir),
        "text_view": "subject_body",
        "sequence_mode": "head",
        "max_seq_length": max_length,
        "max_seq_length_source": max_length_source,
        "prediction_mode": "flat",
        "fallback": False,
        "thresholds_train_oof_only": {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
        "dev_metrics": dev_metrics,
        "checkpoint_id": checkpoint["model_id"],
        "checkpoint_revision": checkpoint["revision"],
        "checkpoint_files_sha256": checkpoint["files"],
        "head_sha256": sha256_file(heads_path),
        "benchmark_sha256": benchmark_hash(),
        "inference_batch_size": 24,
        "contrastive": {
            "temperature": TEMPERATURE,
            "epochs": EPOCHS,
            "batch_size": BATCH_SIZE,
            "learning_rate": LEARNING_RATE,
            "weight_decay": 0.01,
            "seed": SEED,
            "train_records": len(train_rows),
            "loss": final_loss,
            "cv_refit_per_fold": True,
            "folds": 5,
            "optimizer": "torch AdamW",
        },
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    _json_write(bundle_dir / "bundle.json", bundle_payload)

    dev_artifact_path = EXPERIMENT_DIR / "dev_probabilities_contrastive.json"
    oof_artifact_path = EXPERIMENT_DIR / "train_oof_probabilities_contrastive.json"
    _json_write(dev_artifact_path, {
        "row_ids": [row["email_id"] for row in dev_rows],
        "run_ids": [RUN_ID],
        "probabilities": {RUN_ID: dev_probs.tolist()},
        "thresholds_train_oof_only": {RUN_ID: {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)}},
        "prediction_modes": {RUN_ID: "flat"},
        "benchmark_sha256": benchmark_hash(),
    })
    _json_write(oof_artifact_path, {
        "row_ids": [row["email_id"] for row in train_rows],
        "run_ids": [RUN_ID],
        "probabilities": {RUN_ID: oof_probs.tolist()},
        "scope": "TRAIN-only grouped OOF; each fold's encoder was freshly fine-tuned without that fold's labels",
        "benchmark_sha256": benchmark_hash(),
    })

    versions = {
        "python": platform.python_version(), "torch": torch.__version__,
        "transformers": __import__("transformers").__version__,
        "numpy": np.__version__, "device": torch.cuda.get_device_name(0),
    }
    model_files = [path for path in encoder_dir.rglob("*") if path.is_file()]
    run = {
        "run_id": RUN_ID,
        "model": checkpoint["model_id"],
        "features": {"text_view": "subject_body", "pooling": "official attention-mask mean pooling + L2 normalize", "max_seq_length": max_length, "max_seq_length_source": max_length_source},
        "training_records": len(train_rows),
        "dev_records": len(dev_rows),
        "seed": SEED,
        "hyperparameters": {"epochs": EPOCHS, "batch_size": BATCH_SIZE, "learning_rate": LEARNING_RATE, "temperature": TEMPERATURE, "contrastive_loss": "pairwise supervised contrastive; Jaccard-weighted positive pairs"},
        "loss": "in-batch supervised contrastive loss followed by logistic-head log loss",
        "class_weighting": "none",
        "threshold_method": "five-fold leakage-group TRAIN OOF; encoder refit from the official base checkpoint inside each fold",
        "oof_thresholds": {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
        "oof_threshold_details": threshold_report,
        "oof_cv_training_seconds": oof_seconds,
        "final_training_seconds": final_training_seconds,
        "training_seconds_including_oof": oof_seconds + final_training_seconds,
        "dev_inference_ms_per_record": 1000 * dev_inference_seconds / max(len(dev_rows), 1),
        "single_record_encoder_latency_ms": single_record_latency_ms,
        "model_size_bytes": sum(path.stat().st_size for path in model_files),
        "head_size_bytes": heads_path.stat().st_size,
        "package_size_bytes": sum(path.stat().st_size for path in model_files) + heads_path.stat().st_size,
        "dev_metrics": dev_metrics,
        "versions": versions,
        "checkpoint_revision": checkpoint["revision"],
        "checkpoint_files_sha256": checkpoint["files"],
        "bundle_path": str(bundle_dir.resolve()),
        "dev_probabilities_path": str(dev_artifact_path.resolve()),
        "train_oof_probabilities_path": str(oof_artifact_path.resolve()),
        "prediction_mode": "flat",
        "fallback": False,
        "test_used_or_read": False,
    }
    run["encoder_implementation_sha256"] = sha256_file(AI_DIR / "src/models/optimization_embeddings.py")
    run["training_script_sha256"] = sha256_file(Path(__file__).resolve())
    registry_path = AI_DIR / "reports/optimization_embeddings.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["bundles"] = [item for item in registry.get("bundles", []) if item.get("bundle_name") != "setfit_style_contrastive"]
    registry["bundles"].append({
        "bundle_name": "setfit_style_contrastive",
        "bundle_path": str(bundle_dir.resolve()),
        "prediction_mode": "flat",
        "fallback": False,
        "thresholds_train_oof_only": run["oof_thresholds"],
        "dev_probabilities_path": str(dev_artifact_path.resolve()),
        "train_oof_probabilities_path": str(oof_artifact_path.resolve()),
        "package_size_bytes": run["package_size_bytes"],
        "model_size_bytes": run["model_size_bytes"],
        "head_size_bytes": run["head_size_bytes"],
    })
    registry["contrastive_fewshot"] = {
        "run": run,
        "train_fold_encoder_refit_for_oof": True,
        "oof_folds": fold_reports,
        "dev_probabilities_path": str(dev_artifact_path.resolve()),
        "train_oof_probabilities_path": str(oof_artifact_path.resolve()),
        "test_used_or_read": False,
    }
    registry["versions_contrastive"] = versions
    _json_write(registry_path, registry)
    print(json.dumps({
        "run_id": RUN_ID,
        "dev_macro_f1": dev_metrics["macro_f1"],
        "dev_micro_f1": dev_metrics["micro_f1"],
        "training_seconds_including_oof": run["training_seconds_including_oof"],
        "bundle_path": str(bundle_dir.resolve()),
    }, indent=2), flush=True)
    return run


def main() -> int:
    _fit_phase()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

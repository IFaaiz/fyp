"""Train the fixed-split DistilBERT AI-silver diagnostic.

The model is fit only on the split's `fit` partition. Per-label thresholds are
selected on its separate `tuning` partition, and the final `validation`
partition remains untouched until both predictions are finalized. The
PyTorch/Transformers imports are lazy so normal repository tools do not need
the optional neural dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
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

from src.models.silver_classifier import LABEL_ORDER
from src.models.transfer_diagnostic import (
    exclusive_predictions,
    full_diagnostic_metrics,
    load_shared_partitions,
    positive_weights,
    record_text,
    sha256_file,
    target_matrix,
    tune_thresholds,
    validate_snapshot,
)


DEFAULT_ROOT = AI_DIR / "data/experiments/tonight_20261002"
DEFAULT_SNAPSHOT = DEFAULT_ROOT / "corrected_silver_snapshot.jsonl"
DEFAULT_MANIFEST = AI_DIR / "annotation/training_silver_v2_manifest.jsonl"
DEFAULT_SPLIT = AI_DIR / "data/splits/tonight_silver_v2_shared_split.json"
DEFAULT_OUTPUT = DEFAULT_ROOT / "transfer_results.json"
DEFAULT_PREDICTIONS = DEFAULT_ROOT / "transfer_predictions.jsonl"
DEFAULT_MODELS = AI_DIR / "data/models/tonight"
DEFAULT_CACHE = AI_DIR / "data/cache/huggingface"
MODEL_NAME = "distilbert-base-uncased"
SEED = 20261002
EPOCHS = 3
BATCH_SIZE = 8
LEARNING_RATE = 5e-5


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"expected an object at {path}:{line_number}")
            rows.append(value)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temp.replace(path)


def _quantile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


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


def _version_report(torch: Any, transformers: Any, tokenizer: Any) -> dict[str, Any]:
    try:
        import numpy as np
        numpy_version = np.__version__
    except ImportError:
        numpy_version = None
    try:
        import tokenizers
        tokenizers_version = tokenizers.__version__
    except ImportError:
        tokenizers_version = None
    try:
        import safetensors
        safetensors_version = safetensors.__version__
    except ImportError:
        safetensors_version = None
    try:
        import huggingface_hub
        huggingface_hub_version = huggingface_hub.__version__
    except ImportError:
        huggingface_hub_version = None
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "tokenizers": tokenizers_version,
        "safetensors": safetensors_version,
        "huggingface_hub": huggingface_hub_version,
        "numpy": numpy_version,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "tokenizer_class": type(tokenizer).__name__,
    }


def _select_max_length(train_rows: list[dict[str, Any]], tokenizer: Any) -> tuple[int, dict[str, Any]]:
    texts = [record_text(row) for row in train_rows]
    token_lists = tokenizer(texts, add_special_tokens=True, truncation=False)["input_ids"]
    lengths = [len(tokens) for tokens in token_lists]
    p95 = _quantile(lengths, 0.95)
    selected = min(512, max(64, int(math.ceil(p95 / 32) * 32)))
    return selected, {
        "measured_on_partition": "fit",
        "records": len(lengths),
        "with_special_tokens": True,
        "p50_tokens": _quantile(lengths, 0.50),
        "p90_tokens": _quantile(lengths, 0.90),
        "p95_tokens": p95,
        "p99_tokens": _quantile(lengths, 0.99),
        "max_tokens": max(lengths, default=0),
        "chosen_max_length": selected,
        "selection_rule": "round the fit-partition p95 token length up to the next 32; clamp to 64..512",
    }


def _tokenize_partitions(
    tokenizer: Any, partitions: dict[str, list[dict[str, Any]]], max_length: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    encoded: dict[str, dict[str, Any]] = {}
    truncation: dict[str, Any] = {}
    for name, rows in partitions.items():
        texts = [record_text(row) for row in rows]
        full = tokenizer(texts, add_special_tokens=True, truncation=False)["input_ids"]
        lengths = [len(tokens) for tokens in full]
        clipped = tokenizer(
            texts, add_special_tokens=True, truncation=True,
            max_length=max_length, padding="max_length",
        )
        encoded[name] = {key: value for key, value in clipped.items()}
        count = sum(length > max_length for length in lengths)
        truncation[name] = {
            "records": len(rows),
            "truncated_records": count,
            "truncated_fraction": count / len(rows) if rows else 0.0,
            "token_p50": _quantile(lengths, 0.50),
            "token_p90": _quantile(lengths, 0.90),
            "token_p95": _quantile(lengths, 0.95),
            "token_max": max(lengths, default=0),
        }
    return encoded, truncation


def _train_one(
    *, variant: str, weighted: bool, model_directory: Path,
    partitions: dict[str, list[dict[str, Any]]], encoded: dict[str, dict[str, Any]],
    max_length: int, seed: int, epochs: int, batch_size: int, learning_rate: float,
    model_name: str, checkpoint_path: Path, checkpoint_revision: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Transfer training requires the optional torch and transformers packages. "
            "Install them in the active project runtime before launching this script."
        ) from exc

    _seed_everything(seed, torch)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(checkpoint_path, use_fast=True, local_files_only=True)
    id2label = {index: label for index, label in enumerate(LABEL_ORDER)}
    label2id = {label: index for index, label in enumerate(LABEL_ORDER)}
    model = AutoModelForSequenceClassification.from_pretrained(
        str(checkpoint_path),
        local_files_only=True,
        num_labels=len(LABEL_ORDER),
        id2label=id2label,
        label2id=label2id,
        problem_type="multi_label_classification",
        attn_implementation="eager",
    )
    model.to(device)
    model.train()

    fit_rows = partitions["fit"]
    fit_targets = torch.tensor(target_matrix([row["labels"] for row in fit_rows]), dtype=torch.float32, device=device)
    weights, weight_report = positive_weights([row["labels"] for row in fit_rows])
    pos_weight = torch.tensor(weights if weighted else [1.0] * len(LABEL_ORDER), dtype=torch.float32, device=device)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    fit_tensors = {
        key: torch.tensor(value, dtype=torch.long)
        for key, value in encoded["fit"].items()
    }
    use_amp = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    epoch_losses: list[float] = []
    training_started = time.perf_counter()
    generator = torch.Generator().manual_seed(seed)
    for epoch in range(epochs):
        model.train()
        permutation = torch.randperm(len(fit_rows), generator=generator)
        epoch_loss = 0.0
        batches = 0
        for start in range(0, len(fit_rows), batch_size):
            selected = permutation[start:start + batch_size]
            batch = {key: tensor[selected].to(device) for key, tensor in fit_tensors.items()}
            labels = fit_targets[selected.to(device)]
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(**batch).logits
                loss = criterion(logits.float(), labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            epoch_loss += float(loss.detach().cpu())
            batches += 1
        epoch_losses.append(epoch_loss / max(batches, 1))
        print(
            f"{variant} epoch {epoch + 1}/{epochs}: mean_loss={epoch_losses[-1]:.5f}",
            flush=True,
        )
    training_seconds = time.perf_counter() - training_started

    @torch.no_grad()
    def predict_probabilities(partition_name: str) -> list[list[float]]:
        model.eval()
        rows = partitions[partition_name]
        data = encoded[partition_name]
        outputs: list[list[float]] = []
        for start in range(0, len(rows), batch_size):
            stop = min(start + batch_size, len(rows))
            batch = {
                key: torch.tensor(value[start:stop], dtype=torch.long, device=device)
                for key, value in data.items()
            }
            with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(**batch).logits
            outputs.extend(logits.float().sigmoid().cpu().tolist())
        return outputs

    evaluation_started = time.perf_counter()
    tune_probs = predict_probabilities("tuning")
    validation_probs = predict_probabilities("validation")
    tune_expected = [row["labels"] for row in partitions["tuning"]]
    thresholds, threshold_report = tune_thresholds(tune_expected, tune_probs)
    validation_expected = [row["labels"] for row in partitions["validation"]]
    fixed_predictions = exclusive_predictions(validation_probs, [0.5] * len(LABEL_ORDER))
    tuned_predictions = exclusive_predictions(validation_probs, thresholds)
    evaluation_seconds = time.perf_counter() - evaluation_started

    model_directory.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(model_directory, safe_serialization=True)
    tokenizer.save_pretrained(model_directory)
    model_files = sorted(path for path in model_directory.rglob("*") if path.is_file())
    model_hashes = {path.relative_to(model_directory).as_posix(): sha256_file(path) for path in model_files}
    model_size_bytes = sum(path.stat().st_size for path in model_files)
    weights_size_bytes = sum(
        path.stat().st_size for path in model_files
        if path.name in {"model.safetensors", "pytorch_model.bin"}
    )

    latency_rows = partitions["validation"][: min(24, len(partitions["validation"]))]
    model.eval()
    if latency_rows:
        sample_texts = [record_text(row) for row in latency_rows]
        sample_data = tokenizer(
            sample_texts, add_special_tokens=True, truncation=True,
            max_length=max_length, padding="max_length", return_tensors="pt",
        )
        sample_data = {key: value.to(device) for key, value in sample_data.items()}
        one_data = {key: value[:1] for key, value in sample_data.items()}
        with torch.no_grad():
            with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                _ = model(**one_data)
            if device.type == "cuda":
                torch.cuda.synchronize()
            single_repetitions = 10
            single_start = time.perf_counter()
            for _ in range(single_repetitions):
                with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                    _ = model(**one_data)
            if device.type == "cuda":
                torch.cuda.synchronize()
            single_forward_seconds = time.perf_counter() - single_start
            latency_start = time.perf_counter()
            repetitions = 3
            for _ in range(repetitions):
                with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                    _ = model(**sample_data)
            if device.type == "cuda":
                torch.cuda.synchronize()
            forward_seconds = time.perf_counter() - latency_start
            encode_start = time.perf_counter()
            for text in sample_texts:
                _ = tokenizer(
                    text, add_special_tokens=True, truncation=True,
                    max_length=max_length, padding="max_length", return_tensors="pt",
                )
            encode_seconds = time.perf_counter() - encode_start
        latency = {
            "sample_records": len(latency_rows),
            "single_record_repetitions": single_repetitions,
            "single_record_forward_ms": 1000 * single_forward_seconds / single_repetitions,
            "repetitions": repetitions,
            "batch_forward_ms_per_record": 1000 * forward_seconds / (repetitions * len(latency_rows)),
            "tokenization_ms_per_record": 1000 * encode_seconds / len(latency_rows),
            "single_record_tokenization_plus_forward_ms": (
                1000 * single_forward_seconds / single_repetitions + 1000 * encode_seconds / len(latency_rows)
            ),
            "device": str(device),
            "batch_size": len(latency_rows),
        }
    else:
        latency = {"sample_records": 0, "single_record_forward_ms": None, "batch_forward_ms_per_record": None}

    trainable_parameters = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    total_parameters = sum(parameter.numel() for parameter in model.parameters())
    config = model.config
    report = {
        "variant": variant,
        "loss": "BCEWithLogitsLoss" if weighted else "BCEWithLogitsLoss with unit pos_weight",
        "pos_weight_applied": weighted,
        "fit_only_class_weights": weight_report if weighted else None,
        "optimizer": "AdamW",
        "weight_decay": 0.01,
        "mixed_precision_fp16": use_amp,
        "attention_implementation": "eager",
        "seed": seed,
        "epochs": epochs,
        "epoch_mean_loss": epoch_losses,
        "training_seconds": training_seconds,
        "training_records": len(partitions["fit"]),
        "threshold_tuning_records": len(partitions["tuning"]),
        "validation_records": len(partitions["validation"]),
        "training_record_prevalence": {
            label: sum(label in row["labels"] for row in fit_rows) / len(fit_rows)
            for label in LABEL_ORDER
        },
        "partition_label_prevalence": {
            name: {
                label: sum(label in row["labels"] for row in rows) / len(rows) if rows else 0.0
                for label in LABEL_ORDER
            }
            for name, rows in partitions.items()
        },
        "thresholds_tuned_on_tuning_only": threshold_report,
        "validation_metrics": {
            "threshold_0_5": full_diagnostic_metrics(validation_expected, fixed_predictions),
            "threshold_tuned": full_diagnostic_metrics(validation_expected, tuned_predictions),
        },
        "trainable_parameters": trainable_parameters,
        "total_parameters": total_parameters,
        "model_weights_size_bytes": weights_size_bytes,
        "model_package_size_bytes_including_tokenizer": model_size_bytes,
        "checkpoint_directory": str(model_directory),
        "checkpoint_file_sha256": model_hashes,
        "pretrained_model": model_name,
        "checkpoint_revision": checkpoint_revision or getattr(config, "_commit_hash", None),
        "config_model_type": getattr(config, "model_type", None),
        "inference_latency": latency,
        "evaluation_seconds": evaluation_seconds,
        "device": str(device),
    }
    prediction_rows = []
    for row, probs, fixed, tuned in zip(partitions["validation"], validation_probs, fixed_predictions, tuned_predictions):
        prediction_rows.append({
            "email_id": row["email_id"],
            "source_dataset": row["source_dataset"],
            "thread_id": row["thread_id"],
            "leakage_group_id": row["snapshot_provenance"]["leakage_group_id"],
            "expected_ai_silver_labels": row["labels"],
            "probabilities": {label: probs[index] for index, label in enumerate(LABEL_ORDER)},
            "threshold_0_5_prediction": fixed,
            "threshold_tuned_prediction": tuned,
        })
    return report, prediction_rows


def _source_commit_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_DIR,
            check=True, text=True, capture_output=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def prefetch_pretrained_checkpoint(
    model_name: str, cache_dir: Path, checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    """Resolve and hash a cached official checkpoint without importing PyTorch."""
    try:
        from huggingface_hub import snapshot_download
        from transformers import AutoConfig, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Checkpoint prefetch requires transformers and huggingface_hub") from exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = (
        checkpoint_dir.resolve() if checkpoint_dir is not None
        else Path(snapshot_download(repo_id=model_name, cache_dir=str(cache_dir)))
    )
    if not snapshot_path.is_dir():
        raise FileNotFoundError(f"checkpoint directory does not exist: {snapshot_path}")
    config = AutoConfig.from_pretrained(snapshot_path, local_files_only=True)
    tokenizer = AutoTokenizer.from_pretrained(snapshot_path, local_files_only=True, use_fast=True)
    revision = getattr(config, "_commit_hash", None)
    pinned_manifest = snapshot_path / "checkpoint_manifest.json"
    if not revision and pinned_manifest.is_file():
        pinned = json.loads(pinned_manifest.read_text(encoding="utf-8"))
        if pinned.get("model_id") == model_name:
            revision = pinned.get("revision")
    if not revision and snapshot_path.parent.name == "snapshots":
        revision = snapshot_path.name
    hashes = {
        path.relative_to(snapshot_path).as_posix(): sha256_file(path)
        for path in sorted(snapshot_path.rglob("*"))
        if path.is_file()
    }
    return {
        "model_name": model_name,
        "snapshot_path": str(snapshot_path),
        "revision": revision,
        "config_model_type": getattr(config, "model_type", None),
        "tokenizer_class": type(tokenizer).__name__,
        "files_sha256": hashes,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--split-manifest", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--checkpoint-dir", type=Path, help="already-downloaded Hugging Face snapshot directory")
    parser.add_argument("--cache-only", action="store_true", help="download/hash checkpoint and tokenizer, without reading data or training")
    parser.add_argument("--model-name", default=MODEL_NAME)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE)
    parser.add_argument("--compare-unweighted", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.cache_only:
        cache_report = prefetch_pretrained_checkpoint(args.model_name, args.cache_dir, args.checkpoint_dir)
        print(json.dumps(cache_report, ensure_ascii=False, indent=2), flush=True)
        return 0
    for path in (args.snapshot, args.manifest, args.split_manifest):
        if not path.is_file():
            raise FileNotFoundError(f"required experiment input does not exist: {path}")
    snapshot_rows = read_jsonl(args.snapshot)
    manifest_rows = read_jsonl(args.manifest)
    snapshot_report = validate_snapshot(snapshot_rows, manifest_rows)
    snapshot_hash = sha256_file(args.snapshot)
    manifest_hash = sha256_file(args.manifest)
    split_payload = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    partitions, split_report = load_shared_partitions(
        snapshot_rows, split_payload,
        snapshot_sha256=snapshot_hash,
        silver_manifest_sha256=manifest_hash,
    )

    try:
        import torch
        import transformers
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install torch and transformers before running the transfer diagnostic") from exc
    _seed_everything(args.seed, torch)
    checkpoint_report = prefetch_pretrained_checkpoint(args.model_name, args.cache_dir, args.checkpoint_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        str(checkpoint_report["snapshot_path"]), use_fast=True, local_files_only=True,
    )
    max_length, token_profile = _select_max_length(partitions["fit"], tokenizer)
    encoded, truncation_report = _tokenize_partitions(tokenizer, partitions, max_length)
    versions = _version_report(torch, transformers, tokenizer)
    print(json.dumps({
        "snapshot_records": snapshot_report["records"],
        "partition_records": split_report["partition_records"],
        "max_length": max_length,
        "truncated_by_partition": {key: value["truncated_records"] for key, value in truncation_report.items()},
        "device": versions["gpu_name"] or "cpu",
    }, indent=2), flush=True)

    variants = [("weighted", True)]
    if args.compare_unweighted:
        variants.append(("unweighted", False))
    reports: dict[str, Any] = {}
    predictions_by_variant: dict[str, list[dict[str, Any]]] = {}
    for variant, weighted in variants:
        model_directory = args.model_dir / variant
        print(f"Starting {variant} DistilBERT run", flush=True)
        reports[variant], predictions_by_variant[variant] = _train_one(
            variant=variant,
            weighted=weighted,
            model_directory=model_directory,
            partitions=partitions,
            encoded=encoded,
            max_length=max_length,
            seed=args.seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            model_name=args.model_name,
            checkpoint_path=Path(checkpoint_report["snapshot_path"]),
            checkpoint_revision=checkpoint_report["revision"],
        )
        print(json.dumps({
            "variant": variant,
            "training_seconds": reports[variant]["training_seconds"],
            "validation_threshold_0_5": reports[variant]["validation_metrics"]["threshold_0_5"]["micro_f1"],
            "validation_threshold_tuned": reports[variant]["validation_metrics"]["threshold_tuned"]["micro_f1"],
        }, indent=2), flush=True)

    prediction_rows = []
    reference = predictions_by_variant["weighted"]
    for index, weighted_row in enumerate(reference):
        row = dict(weighted_row)
        if "unweighted" in predictions_by_variant:
            unweighted = predictions_by_variant["unweighted"][index]
            row["unweighted_threshold_0_5_prediction"] = unweighted["threshold_0_5_prediction"]
            row["unweighted_threshold_tuned_prediction"] = unweighted["threshold_tuned_prediction"]
            row["unweighted_probabilities"] = unweighted["probabilities"]
        prediction_rows.append(row)
    _write_jsonl(args.predictions, prediction_rows)
    report = {
        "scope": "AI-silver diagnostic metrics; not gold, final, or production accuracy.",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "model_family": "direct transfer learning: pretrained DistilBERT with 9-output multilabel head",
        "pretrained_model": args.model_name,
        "pretrained_cache_directory": checkpoint_report["snapshot_path"],
        "pretrained_checkpoint_revision": checkpoint_report["revision"],
        "pretrained_checkpoint_file_sha256": checkpoint_report["files_sha256"],
        "label_order": list(LABEL_ORDER),
        "seed": args.seed,
        "training": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "optimizer": "AdamW",
            "weight_decay": 0.01,
            "loss": "BCEWithLogitsLoss",
            "reproducibility": "Python, NumPy, PyTorch and CUDA seeds set; cuDNN deterministic; strict deterministic algorithms; eager attention",
            "input_format": (
                "[SUBJECT] subject\\n[BODY] hash-validated authored_message matching "
                "extract_authored_prefix(current_message), then remove pure separator lines of 20+ *, -, _, =, or ~ characters"
            ),
            "token_distribution": token_profile,
            "truncation_by_partition": truncation_report,
            "fit_partition_only_for_gradient_updates": True,
            "tuning_partition_only_for_thresholds": True,
            "final_validation_used_for_training_or_model_selection": False,
            "early_stopping": False,
            "non_project_exclusivity": "if NON_PROJECT crosses its threshold, retain it only when its probability is at least the strongest project-label probability",
        },
        "data": {
            "snapshot": str(args.snapshot),
            "snapshot_sha256": snapshot_hash,
            "text_free_manifest": str(args.manifest),
            "text_free_manifest_sha256": manifest_hash,
            "split_manifest": str(args.split_manifest),
            "split_manifest_sha256": sha256_file(args.split_manifest),
            "source_commit_sha": _source_commit_sha(),
            "implementation_sha256": {
                "train_transfer_diagnostic.py": sha256_file(Path(__file__).resolve()),
                "transfer_diagnostic.py": sha256_file(AI_DIR / "src/models/transfer_diagnostic.py"),
            },
            "snapshot_validation": snapshot_report,
            "split_validation": split_report,
            "provenance": "AI silver only; human/gold rows excluded and rejected",
            "gold_or_human_rows_used": 0,
        },
        "versions": versions,
        "variants": reports,
        "prediction_file": str(args.predictions),
        "prediction_file_sha256": sha256_file(args.predictions),
        "gold_test_evaluated": False,
    }
    _write_json(args.output, report)
    print(json.dumps({
        "results": str(args.output),
        "predictions": str(args.predictions),
        "model_variants": list(reports),
        "scope": report["scope"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""Frozen sentence-transformer encoding and portable prediction bundles.

The checkpoint is loaded through Transformers, while pooling follows the
official Sentence-Transformers mean-pooling and L2-normalization config shipped
with each pinned checkpoint. No encoder weights are updated by this module.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _positive_weight(labels: np.ndarray, weighting: str) -> dict[int, float] | None:
    if weighting == "none":
        return None
    positive = int(np.asarray(labels).sum())
    negative = int(len(labels) - positive)
    if not positive or not negative:
        return None
    ratio = negative / positive
    if weighting == "sqrt":
        value = math.sqrt(ratio)
    elif weighting.startswith("cap"):
        value = min(ratio, float(weighting.removeprefix("cap")))
    else:
        raise ValueError(f"unknown weighting: {weighting}")
    return {0: 1.0, 1: value}


class ConstantBinaryHead:
    def __init__(self, probability: float):
        self.probability = float(probability)

    def predict_positive(self, features: np.ndarray) -> np.ndarray:
        return np.full(len(features), self.probability, dtype=np.float64)


def _new_estimator(config: dict[str, Any], labels: np.ndarray) -> Any:
    method = config["method"]
    weight = None if method == "mlp" else _positive_weight(labels, config.get("weighting", "none"))
    if method == "logistic":
        from sklearn.linear_model import LogisticRegression
        estimator = LogisticRegression(
            C=float(config.get("C", 1.0)), max_iter=2000, solver="lbfgs",
            class_weight=weight, random_state=int(config.get("seed", 20261004)),
        )
    elif method == "linear_svm":
        from sklearn.svm import LinearSVC
        estimator = LinearSVC(
            C=float(config.get("C", 1.0)), class_weight=weight,
            max_iter=10000, random_state=int(config.get("seed", 20261004)),
        )
    elif method == "mlp":
        from sklearn.neural_network import MLPClassifier
        estimator = MLPClassifier(
            hidden_layer_sizes=tuple(config.get("hidden_layer_sizes", (64,))),
            alpha=float(config.get("alpha", 0.001)), max_iter=int(config.get("max_iter", 150)),
            early_stopping=True, validation_fraction=0.15, n_iter_no_change=12,
            random_state=int(config.get("seed", 20261004)),
        )
    else:
        raise ValueError(f"unknown embedding head: {method}")
    return estimator


def _fit_binary(features: np.ndarray, labels: np.ndarray, config: dict[str, Any]) -> Any:
    labels = np.asarray(labels, dtype=np.int64)
    unique = np.unique(labels)
    if len(unique) < 2:
        return ConstantBinaryHead(float(unique[0]) if len(unique) else 0.0)
    estimator = _new_estimator(config, labels)
    estimator.fit(features, labels)
    return estimator


def _positive_scores(estimator: Any, features: np.ndarray) -> np.ndarray:
    if isinstance(estimator, ConstantBinaryHead):
        return estimator.predict_positive(features)
    if hasattr(estimator, "predict_proba"):
        return estimator.predict_proba(features)[:, 1]
    # LinearSVC has no probabilistic output. Use a fixed sigmoid map so the
    # result is bounded; every decision threshold is still fit on TRAIN OOF.
    from scipy.special import expit
    return expit(estimator.decision_function(features))


class IndependentBinaryHead:
    """One flat binary classifier per canonical label."""

    def __init__(self, config: dict[str, Any], label_indices: list[int] | None = None):
        self.config = dict(config)
        self.label_indices = list(range(9)) if label_indices is None else list(label_indices)
        self.estimators: list[Any] = []

    def fit(self, features: np.ndarray, targets: np.ndarray) -> "IndependentBinaryHead":
        self.estimators = [
            _fit_binary(features, targets[:, index], self.config)
            for index in self.label_indices
        ]
        return self

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        output = np.zeros((len(features), 9), dtype=np.float64)
        for index, estimator in zip(self.label_indices, self.estimators):
            output[:, index] = _positive_scores(estimator, features)
        return output


class HierarchicalBinaryHead:
    """Project-scope model followed by conditional project-function models."""

    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)
        self.scope_estimator: Any | None = None
        self.function_estimators: list[Any] = []

    def fit(self, features: np.ndarray, targets: np.ndarray) -> "HierarchicalBinaryHead":
        project = (targets[:, :8].sum(axis=1) > 0).astype(np.int64)
        self.scope_estimator = _fit_binary(features, project, self.config)
        project_indices = np.flatnonzero(project)
        self.function_estimators = [
            _fit_binary(features[project_indices], targets[project_indices, index], self.config)
            for index in range(8)
        ]
        return self

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        if self.scope_estimator is None:
            raise RuntimeError("hierarchical head has not been fitted")
        scope_probability = _positive_scores(self.scope_estimator, features)
        output = np.zeros((len(features), 9), dtype=np.float64)
        for index, estimator in enumerate(self.function_estimators):
            # Preserve conditional Stage-2 probabilities. The shared
            # hierarchical decoder gates them when NON_PROJECT is selected.
            output[:, index] = _positive_scores(estimator, features)
        output[:, 8] = 1.0 - scope_probability
        return output


class LabelSpecialistHead:
    """Per-label selected estimators with their own encoder and text view."""

    def __init__(self, descriptors: list[dict[str, Any]], estimators: list[Any]):
        self.descriptors = descriptors
        self.estimators = estimators

    def predict_with_features(self, feature_by_key: dict[str, np.ndarray]) -> np.ndarray:
        output = np.zeros((len(self.descriptors) and len(next(iter(feature_by_key.values()))) or 0, 9))
        for descriptor, estimator in zip(self.descriptors, self.estimators):
            key = descriptor["feature_key"]
            index = int(descriptor["label_index"])
            output[:, index] = _positive_scores(estimator, feature_by_key[key])
        return output


def checkpoint_max_seq_length(checkpoint_dir: Path) -> tuple[int, str]:
    """Return the model's official Sentence-Transformers max_seq_length."""
    pooling_path = checkpoint_dir / "1_Pooling/config.json"
    if not pooling_path.is_file():
        raise ValueError(f"official pooling config is missing in {checkpoint_dir}")
    pooling = json.loads(pooling_path.read_text(encoding="utf-8"))
    if pooling.get("pooling_mode_mean_tokens") is not True or pooling.get("pooling_mode_cls_token") is True or pooling.get("pooling_mode_max_tokens") is True:
        raise ValueError("encoder pooling config is not the expected mean-token setup")
    modules_path = checkpoint_dir / "modules.json"
    if modules_path.is_file():
        module_names = [row.get("type", "") for row in json.loads(modules_path.read_text(encoding="utf-8"))]
        if not any(name.endswith(".Normalize") for name in module_names):
            raise ValueError("official sentence-transformer module graph does not include Normalize")
    for name in ("sentence_bert_config.json", "config_sentence_transformers.json"):
        path = checkpoint_dir / name
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("max_seq_length")
        if isinstance(value, int) and value > 0:
            return value, name
    raise ValueError(f"official max_seq_length is absent in {checkpoint_dir}")


def _device_name(torch: Any) -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def encode_texts(
    texts: list[str], *, checkpoint_dir: Path, batch_size: int = 32,
    device: str | None = None, sequence_mode: str = "head",
) -> tuple[np.ndarray, dict[str, Any]]:
    """Encode texts with official ST mean pooling, L2 normalization, no fitting.

    `head_tail` keeps the initial two thirds and final third within the
    checkpoint's published maximum. `two_chunks` encodes the first and last
    full windows, then averages normalized vectors. `head` is the official
    tokenizer truncation default. Output rows are unit-normalized vectors.
    """
    import torch
    import torch.nn.functional as F
    from transformers import AutoModel, AutoTokenizer

    if sequence_mode not in {"head", "head_tail", "two_chunks"}:
        raise ValueError("sequence_mode must be 'head', 'head_tail', or 'two_chunks'")
    max_seq_length, config_source = checkpoint_max_seq_length(checkpoint_dir)
    tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir, local_files_only=True, use_fast=True)
    if sequence_mode in {"head_tail", "two_chunks"}:
        # We tokenize the full string to choose explicit head/tail IDs below;
        # the tokenizer's generic 512-token warning does not describe the
        # checkpoint's smaller published max_seq_length.
        tokenizer.model_max_length = max(tokenizer.model_max_length, 1_000_000)
    model = AutoModel.from_pretrained(checkpoint_dir, local_files_only=True)
    chosen_device = device or _device_name(torch)
    model.to(chosen_device)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)

    results: list[np.ndarray] = []
    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        raise ValueError("encoder tokenizer has no pad_token_id")
    cls_id = tokenizer.cls_token_id
    sep_id = tokenizer.sep_token_id
    if sequence_mode in {"head_tail", "two_chunks"} and (cls_id is None or sep_id is None):
        raise ValueError("chunked token selection requires CLS and SEP token IDs")
    lengths: list[int] = []
    started = __import__("time").perf_counter()
    for start in range(0, len(texts), batch_size):
        batch_texts = texts[start:start + batch_size]
        if sequence_mode == "head":
            encoded = tokenizer(
                batch_texts, add_special_tokens=True, truncation=True,
                max_length=max_seq_length, padding=True, return_tensors="pt",
            )
            input_ids = encoded["input_ids"]
            attention_mask = encoded["attention_mask"]
            lengths.extend(int(value) for value in attention_mask.sum(dim=1).tolist())
            batch = {key: value.to(chosen_device) for key, value in encoded.items()}
        elif sequence_mode == "head_tail":
            rows: list[list[int]] = []
            budget = max_seq_length - 2
            head_size = math.ceil(budget * 2 / 3)
            tail_size = budget - head_size
            for text in batch_texts:
                token_ids = tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"]
                if len(token_ids) <= budget:
                    body = token_ids
                else:
                    body = token_ids[:head_size]
                    if tail_size:
                        body.extend(token_ids[-tail_size:])
                ids = [cls_id, *body, sep_id]
                lengths.append(len(ids))
                rows.append(ids + [pad_id] * (max_seq_length - len(ids)))
            input_ids = torch.tensor(rows, dtype=torch.long)
            attention_mask = (input_ids != pad_id).long()
            batch = {
                "input_ids": input_ids.to(chosen_device),
                "attention_mask": attention_mask.to(chosen_device),
            }
        else:
            rows: list[list[int]] = []
            token_sequences: list[tuple[list[int], list[int]]] = []
            budget = max_seq_length - 2
            for text in batch_texts:
                token_ids = tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"]
                first = token_ids[:budget]
                second = first if len(token_ids) <= budget else token_ids[-budget:]
                token_sequences.append((first, second))
                lengths.append(min(len(token_ids) + 2, max_seq_length))
                for chunk in (first, second):
                    ids = [cls_id, *chunk, sep_id]
                    rows.append(ids + [pad_id] * (max_seq_length - len(ids)))
            input_ids = torch.tensor(rows, dtype=torch.long)
            attention_mask = (input_ids != pad_id).long()
            batch = {
                "input_ids": input_ids.to(chosen_device),
                "attention_mask": attention_mask.to(chosen_device),
            }
        with torch.inference_mode():
            outputs = model(**batch)
            token_embeddings = outputs.last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1).to(token_embeddings.dtype)
            pooled = (token_embeddings * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pooled = F.normalize(pooled, p=2, dim=1)
        if sequence_mode == "two_chunks":
            pooled = F.normalize((pooled[0::2] + pooled[1::2]) / 2, p=2, dim=1)
        results.append(pooled.float().cpu().numpy())
    del model
    if chosen_device.startswith("cuda"):
        torch.cuda.empty_cache()
    matrix = np.concatenate(results, axis=0) if results else np.zeros((0, 0), dtype=np.float32)
    return matrix, {
        "records": len(texts),
        "dimension": int(matrix.shape[1]) if matrix.ndim == 2 and matrix.size else 0,
        "max_seq_length": max_seq_length,
        "max_seq_length_source": config_source,
        "sequence_mode": sequence_mode,
        "pooling": "attention-mask-weighted mean of last_hidden_state; official checkpoint mean-token pooling",
        "normalize_embeddings": True,
        "actual_token_p50": int(np.quantile(lengths, 0.5)) if lengths else 0,
        "actual_token_p95": int(np.quantile(lengths, 0.95)) if lengths else 0,
        "device": chosen_device,
        "encode_seconds": __import__("time").perf_counter() - started,
    }


def probabilities_from_head(head: Any, features: np.ndarray) -> np.ndarray:
    """Call a trained independent-label head and return exactly Nx9 scores."""
    values = head.predict_proba(features)
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 9:
        raise ValueError(f"head returned shape {values.shape}, expected Nx9")
    return np.clip(values, 0.0, 1.0)


def _texts(rows: list[dict[str, Any]], view: str) -> list[str]:
    # Keep canonical formatting and validation in the shared benchmark helper.
    from .optimization_benchmark import texts
    return texts(rows, view=view)


def predict(bundlepath: str | Path, canonicalrows: list[dict[str, Any]]) -> np.ndarray:
    """Load an exported family bundle and return Nx9 probabilities.

    Each bundle directory contains `bundle.json`, a local `encoder/` snapshot,
    and a joblib `heads.joblib`. The function intentionally takes canonical
    rows only; it has no path or partition-discovery behavior that could read
    sealed benchmark records.
    """
    import joblib

    root = Path(bundlepath)
    metadata = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    head = joblib.load(root / "heads.joblib")
    batch_size = int(metadata.get("inference_batch_size", 32))
    if metadata.get("bundle_type") == "specialists":
        feature_by_key: dict[str, np.ndarray] = {}
        for key, spec in metadata["feature_specs"].items():
            encoder_dir = (root / spec["encoder_path"]).resolve()
            feature_by_key[key], _ = encode_texts(
                _texts(canonicalrows, spec["text_view"]), checkpoint_dir=encoder_dir,
                batch_size=batch_size, sequence_mode=spec.get("sequence_mode", "head"),
            )
        return head.predict_with_features(feature_by_key)

    encoder_dir = (root / metadata.get("encoder_path", "encoder")).resolve()
    vectors, _ = encode_texts(
        _texts(canonicalrows, metadata["text_view"]), checkpoint_dir=encoder_dir,
        batch_size=batch_size, sequence_mode=metadata.get("sequence_mode", "head"),
    )
    return probabilities_from_head(head, vectors)

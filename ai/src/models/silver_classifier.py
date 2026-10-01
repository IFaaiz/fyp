"""TF-IDF + one-vs-rest logistic regression prototype.

The implementation uses sparse Python dictionaries and deterministic full-batch
gradient descent. It follows logistic-regression loss with L2 regularization;
The optional scikit-learn optimizer fits the same vectors and exports weights
into the same JSON format; prediction never requires NumPy/SciPy.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ..datasets.cleaning import clean_email_body
from ..datasets.schemas import LABELS


LABEL_ORDER = (
    "MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT",
    "ACTION_REQUEST", "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE",
    "NON_PROJECT",
)
MODEL_FORMAT = "fyp-tfidf-ovr-logistic-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.IGNORECASE)
HEADER_FIELD_RE = re.compile(r"^(from|sent|date|to|cc|subject):\s*\S", re.IGNORECASE)
DATE_HEADER_RE = re.compile(
    r"^(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?:\s+\d{1,2}:\d{2}\s*(?:am|pm)?)?"
    r"|(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+.{5,30}\d{4}\s+\d{1,2}:\d{2})$",
    re.IGNORECASE,
)
SENDER_DATE_HEADER_RE = re.compile(
    r"^(?:[^<>\n]{1,120}<[^<>\s]+@[^<>\s]+>|[^\s<>]+@[^\s<>]+)\s+on\s+"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?$",
    re.IGNORECASE,
)


def extract_authored_prefix(text: str) -> str:
    """Trim standard quote markers and obvious embedded mail-header blocks.

    Lotus Enron exports sometimes place an older message after a short reply
    without a From: line or dashed separator. A nearby date and multiple
    standard header fields mark that boundary. Unmarked quoted prose remains
    intrinsically ambiguous and should be included in the semantic audit.
    """
    _, current = clean_email_body(text)
    lines = current.split("\n")
    for index, line in enumerate(lines):
        # Column-aligned Lotus exports place To/Subject beside sender/date.
        block = "\n".join(lines[max(0, index - 1):index + 5])
        if (re.search(r"\bTo:\s*\S", line, re.I)
                and re.search(r"\bSubject:\s*\S", block, re.I)
                and re.search(r"\bcc:", block, re.I)
                and re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", block)
                and "@" in block):
            cutoff = index
            previous = index - 1
            while previous >= 0 and not lines[previous].strip():
                previous -= 1
            if previous >= 0 and "@" in lines[previous]:
                cutoff = previous
            return "\n".join(lines[:cutoff]).strip()
    for index in range(1, len(lines)):
        fields: set[str] = set()
        starts: list[int] = []
        for cursor in range(index, min(len(lines), index + 12)):
            stripped = lines[cursor].strip()
            if not stripped:
                continue
            field_match = HEADER_FIELD_RE.match(stripped)
            if field_match:
                fields.add(field_match.group(1).lower())
                starts.append(cursor)
            elif DATE_HEADER_RE.match(stripped) or SENDER_DATE_HEADER_RE.match(stripped):
                fields.add("date")
                starts.append(cursor)
        has_anchor = bool(fields.intersection({"from", "sent", "date"}))
        has_address_or_subject = bool(fields.intersection({"to", "cc", "subject"}))
        enough_headers = len(fields) >= 3 or (len(fields) >= 2 and "subject" in fields)
        if has_anchor and has_address_or_subject and enough_headers:
            cutoff = min(starts)
            previous = cutoff - 1
            while previous >= 0 and not lines[previous].strip():
                previous -= 1
            # Lotus often places the sender name alone above its timestamp.
            if previous >= 0 and "@" in lines[previous] and len(lines[previous]) < 160:
                cutoff = previous
            return "\n".join(lines[:cutoff]).strip()
    return current


def record_features(record: dict[str, Any]) -> Counter[str]:
    """Count word/bigram features from subject and the authored body prefix."""
    subject = str(record.get("subject") or "")
    current_message = extract_authored_prefix(str(record.get("current_message") or ""))
    features: Counter[str] = Counter()
    for prefix, text in (("body", current_message), ("subject", subject)):
        tokens = [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text)]
        features.update(f"{prefix}:w:{token}" for token in tokens)
        features.update(
            f"{prefix}:b:{left}_{right}"
            for left, right in zip(tokens, tokens[1:])
        )
    return features


class TfidfVectorizer:
    """Deterministic sublinear-TF, smoothed-IDF sparse vectorizer."""

    def __init__(self):
        self.vocabulary: list[str] = []
        self.idf: list[float] = []
        self._indices: dict[str, int] = {}

    def fit(self, documents: list[Counter[str]]) -> "TfidfVectorizer":
        if not documents:
            raise ValueError("cannot fit TF-IDF without training documents")
        document_frequency: Counter[str] = Counter()
        for document in documents:
            document_frequency.update(document.keys())
        self.vocabulary = sorted(document_frequency)
        if not self.vocabulary:
            raise ValueError("training documents produced no features")
        total_documents = len(documents)
        self.idf = [
            math.log((1 + total_documents) / (1 + document_frequency[feature])) + 1.0
            for feature in self.vocabulary
        ]
        self._indices = {feature: index for index, feature in enumerate(self.vocabulary)}
        return self

    def transform(self, documents: Iterable[Counter[str]]) -> list[dict[int, float]]:
        if not self.vocabulary:
            raise ValueError("vectorizer has not been fitted")
        vectors = []
        for document in documents:
            vector = {}
            for feature, count in document.items():
                index = self._indices.get(feature)
                if index is not None and count > 0:
                    vector[index] = (1.0 + math.log(count)) * self.idf[index]
            norm = math.sqrt(sum(value * value for value in vector.values()))
            if norm:
                vector = {index: value / norm for index, value in vector.items()}
            vectors.append(vector)
        return vectors

    def to_dict(self) -> dict[str, Any]:
        return {"vocabulary": self.vocabulary, "idf": self.idf}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TfidfVectorizer":
        vectorizer = cls()
        vectorizer.vocabulary = list(payload["vocabulary"])
        vectorizer.idf = [float(value) for value in payload["idf"]]
        if len(vectorizer.vocabulary) != len(vectorizer.idf):
            raise ValueError("invalid TF-IDF vocabulary/idf lengths")
        vectorizer._indices = {feature: index for index, feature in enumerate(vectorizer.vocabulary)}
        return vectorizer


class TfidfOneVsRestLogisticRegression:
    """Independent binary logistic regressions over shared sparse TF-IDF."""

    def __init__(
        self, *, c: float = 1.0, threshold: float = 0.5,
        max_iter: int = 200, learning_rate: float = 1.0, tolerance: float = 1e-5,
        seed: int = 42, optimizer: str = "python",
    ):
        if c <= 0 or not 0 < threshold < 1 or max_iter < 1 or learning_rate <= 0:
            raise ValueError("c, max_iter, and learning_rate must be positive; threshold must be in (0, 1)")
        if optimizer not in {"python", "sklearn"}:
            raise ValueError("optimizer must be python or sklearn")
        self.c = float(c)
        self.threshold = float(threshold)
        self.max_iter = int(max_iter)
        self.learning_rate = float(learning_rate)
        self.tolerance = float(tolerance)
        self.seed = int(seed)
        self.optimizer = optimizer
        self.optimizer_versions: dict[str, str] = {}
        self.vectorizer = TfidfVectorizer()
        self.classifiers: dict[str, dict[str, Any]] = {}
        self.training_records = 0
        self.metadata: dict[str, Any] = {}

    @staticmethod
    def encode_targets(labels: list[list[str]]) -> list[list[int]]:
        targets = []
        for row_labels in labels:
            if not isinstance(row_labels, list) or any(label not in LABELS for label in row_labels):
                raise ValueError("training labels must be lists of known classification labels")
            if len(row_labels) != len(set(row_labels)):
                raise ValueError("training labels contain duplicates")
            if "NON_PROJECT" in row_labels and len(row_labels) > 1:
                raise ValueError("NON_PROJECT cannot co-occur with project labels")
            active = set(row_labels)
            targets.append([int(label in active) for label in LABEL_ORDER])
        return targets

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            return 1.0 / (1.0 + math.exp(-min(value, 700)))
        exp_value = math.exp(max(value, -700))
        return exp_value / (1.0 + exp_value)

    def fit(self, records: list[dict[str, Any]]) -> "TfidfOneVsRestLogisticRegression":
        if not records:
            raise ValueError("cannot fit without training records")
        raw_documents = [record_features(record) for record in records]
        target_rows = self.encode_targets([record.get("labels", []) for record in records])
        self.vectorizer.fit(raw_documents)
        vectors = self.vectorizer.transform(raw_documents)
        self.training_records = len(records)
        self.classifiers = {}
        if self.optimizer == "sklearn":
            return self._fit_sklearn(vectors, target_rows)
        document_count = len(records)
        # The objective is mean binary cross-entropy + ||w||^2/(2*C*n),
        # matching the usual C-style inverse regularization convention.
        l2 = 1.0 / (self.c * document_count)

        for label_index, label in enumerate(LABEL_ORDER):
            targets = [row[label_index] for row in target_rows]
            positive_count = sum(targets)
            prior = (positive_count + 0.5) / (document_count + 1.0)
            bias = math.log(prior / (1.0 - prior))
            weights: dict[int, float] = {}
            converged = positive_count in {0, document_count}
            iterations = 0
            if not converged:
                for iteration in range(self.max_iter):
                    bias_gradient = 0.0
                    gradients: dict[int, float] = {}
                    for vector, target in zip(vectors, targets):
                        margin = bias + sum(weights.get(index, 0.0) * value for index, value in vector.items())
                        error = self._sigmoid(margin) - target
                        bias_gradient += error
                        for index, value in vector.items():
                            gradients[index] = gradients.get(index, 0.0) + error * value
                    scale = 1.0 / document_count
                    bias_step = self.learning_rate * bias_gradient * scale
                    bias -= bias_step
                    max_step = abs(bias_step)
                    for index, gradient in gradients.items():
                        old_weight = weights.get(index, 0.0)
                        step = self.learning_rate * (gradient * scale + l2 * old_weight)
                        new_weight = old_weight - step
                        if new_weight:
                            weights[index] = new_weight
                        else:
                            weights.pop(index, None)
                        max_step = max(max_step, abs(step))
                    iterations = iteration + 1
                    if max_step < self.tolerance:
                        converged = True
                        break
            self.classifiers[label] = {
                "bias": bias,
                "weights": {str(index): value for index, value in sorted(weights.items())},
                "training_positive": positive_count,
                "training_negative": document_count - positive_count,
                "iterations": iterations,
                "converged": converged,
            }
        return self

    def _fit_sklearn(self, vectors, target_rows):
        """Fit standard binary logistic regressions, exporting portable weights."""
        import warnings
        import numpy
        import scipy
        import sklearn
        from scipy.sparse import csr_matrix
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LogisticRegression

        self.optimizer_versions = {
            "scikit_learn": sklearn.__version__,
            "numpy": numpy.__version__, "scipy": scipy.__version__,
        }
        data, indices, indptr = [], [], [0]
        for vector in vectors:
            for index, value in sorted(vector.items()):
                indices.append(index)
                data.append(value)
            indptr.append(len(data))
        matrix = csr_matrix(
            (data, indices, indptr),
            shape=(len(vectors), len(self.vectorizer.vocabulary)), dtype="float64",
        )
        for label_index, label in enumerate(LABEL_ORDER):
            targets = [row[label_index] for row in target_rows]
            positive_count = sum(targets)
            prior = (positive_count + 0.5) / (len(vectors) + 1.0)
            bias, weights, iterations, converged = math.log(prior / (1 - prior)), {}, 0, True
            if 0 < positive_count < len(vectors):
                estimator = LogisticRegression(
                    C=self.c, solver="lbfgs", max_iter=self.max_iter,
                    tol=self.tolerance, random_state=self.seed,
                )
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ConvergenceWarning)
                    estimator.fit(matrix, targets)
                converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
                bias = float(estimator.intercept_[0])
                weights = {str(i): float(w) for i, w in enumerate(estimator.coef_[0]) if w}
                iterations = int(estimator.n_iter_[0])
            self.classifiers[label] = {
                "bias": bias, "weights": weights,
                "training_positive": positive_count,
                "training_negative": len(vectors) - positive_count,
                "iterations": iterations, "converged": converged,
            }
        return self

    def predict_proba(self, record: dict[str, Any]) -> dict[str, float]:
        if not self.classifiers:
            raise ValueError("model has not been fitted")
        vector = self.vectorizer.transform([record_features(record)])[0]
        probabilities = {}
        for label in LABEL_ORDER:
            classifier = self.classifiers[label]
            weights = classifier["weights"]
            margin = classifier["bias"] + sum(
                float(weights.get(str(index), 0.0)) * value
                for index, value in vector.items()
            )
            probabilities[label] = self._sigmoid(margin)
        return probabilities

    def predict(self, record: dict[str, Any]) -> dict[str, Any]:
        probabilities = self.predict_proba(record)
        labels = [label for label in LABEL_ORDER if probabilities[label] >= self.threshold]
        if "NON_PROJECT" in labels and len(labels) > 1:
            strongest_project = max(
                probabilities[label] for label in LABEL_ORDER if label != "NON_PROJECT"
            )
            if probabilities["NON_PROJECT"] >= strongest_project:
                labels = ["NON_PROJECT"]
            else:
                labels.remove("NON_PROJECT")
        return {"labels": labels, "probabilities": probabilities}

    def to_dict(self) -> dict[str, Any]:
        if not self.classifiers:
            raise ValueError("model has not been fitted")
        return {
            "format": MODEL_FORMAT,
            "model_type": "TF-IDF + one-vs-rest logistic regression",
            "solver": (
                "scikit-learn binary logistic regression with lbfgs"
                if self.optimizer == "sklearn" else
                "deterministic full-batch gradient descent on sparse vectors"
            ),
            "optimizer_versions": self.optimizer_versions,
            "regularization": "mean binary cross-entropy + L2 ||w||^2/(2*C*n)",
            "hyperparameters": {
                "C": self.c,
                "threshold": self.threshold,
                "max_iter": self.max_iter,
                "learning_rate": self.learning_rate,
                "tolerance": self.tolerance,
                "seed": self.seed,
                "optimizer": self.optimizer,
            },
            "labels": list(LABEL_ORDER),
            "vectorizer": self.vectorizer.to_dict(),
            "training_records": self.training_records,
            "classifiers": self.classifiers,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TfidfOneVsRestLogisticRegression":
        if payload.get("format") != MODEL_FORMAT or payload.get("labels") != list(LABEL_ORDER):
            raise ValueError("unsupported or incompatible model format")
        hyperparameters = payload["hyperparameters"]
        model = cls(
            c=float(hyperparameters["C"]),
            threshold=float(hyperparameters["threshold"]),
            max_iter=int(hyperparameters["max_iter"]),
            learning_rate=float(hyperparameters["learning_rate"]),
            tolerance=float(hyperparameters["tolerance"]),
            seed=int(hyperparameters["seed"]),
            optimizer=hyperparameters.get("optimizer", "python"),
        )
        model.optimizer_versions = dict(payload.get("optimizer_versions", {}))
        model.vectorizer = TfidfVectorizer.from_dict(payload["vectorizer"])
        model.training_records = int(payload["training_records"])
        model.classifiers = dict(payload["classifiers"])
        model.metadata = dict(payload.get("metadata", {}))
        if any(label not in model.classifiers for label in LABEL_ORDER):
            raise ValueError("model is missing one or more label classifiers")
        return model

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", newline="\n", dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = stream.name
                stream.write(encoded)
            os.replace(temporary_path, target)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    @classmethod
    def load(cls, path: str | Path) -> "TfidfOneVsRestLogisticRegression":
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("model file must contain a JSON object")
        return cls.from_dict(payload)


def classify_record(
    model: TfidfOneVsRestLogisticRegression, record: dict[str, Any],
) -> dict[str, Any]:
    prediction = model.predict(record)
    return {
        "email_id": record.get("email_id"),
        **prediction,
        "intended_use": "silver_classification_prototype_only",
    }


def calculate_multilabel_metrics(
    expected: list[list[str]], predicted: list[list[str]],
) -> dict[str, Any]:
    """Calculate diagnostic multilabel metrics without making any claims.

    The training CLI calls this only when explicitly asked to evaluate after
    the leakage and silver-data gates.
    """
    if len(expected) != len(predicted) or not expected:
        raise ValueError("expected and predicted must have equal nonzero lengths")
    counts = {label: {"tp": 0, "fp": 0, "fn": 0} for label in LABEL_ORDER}
    exact = 0
    hamming_errors = 0
    for actual_row, predicted_row in zip(expected, predicted):
        actual, guess = set(actual_row), set(predicted_row)
        exact += actual == guess
        hamming_errors += len(actual.symmetric_difference(guess))
        for label in LABEL_ORDER:
            if label in actual and label in guess:
                counts[label]["tp"] += 1
            elif label in guess:
                counts[label]["fp"] += 1
            elif label in actual:
                counts[label]["fn"] += 1
    total_tp = sum(item["tp"] for item in counts.values())
    total_fp = sum(item["fp"] for item in counts.values())
    total_fn = sum(item["fn"] for item in counts.values())
    micro_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall else 0.0
    )
    per_label = {}
    for label, item in counts.items():
        tp, fp, fn = item["tp"], item["fp"], item["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {
            "support": tp + fn,
            "predicted": tp + fp,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "records": len(expected),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "macro_f1": sum(item["f1"] for item in per_label.values()) / len(LABEL_ORDER),
        "subset_match_rate": exact / len(expected),
        "hamming_loss": hamming_errors / (len(expected) * len(LABEL_ORDER)),
        "per_label": per_label,
    }

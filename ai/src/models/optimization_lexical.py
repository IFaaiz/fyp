"""Lexical and shallow structured models for the AI-silver optimization sprint.

This module is intentionally separate from the existing prototype. It supports
word/character TF-IDF combinations, modest domain indicators, independent
label specialists, and a PROJECT -> function hierarchy. Artifacts are saved by
the experiment runner under the ignored optimization data directories.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
from scipy import sparse
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import normalize
from sklearn.svm import LinearSVC

from .silver_classifier import LABEL_ORDER, extract_authored_prefix


PROJECT_LABELS = LABEL_ORDER[:-1]
FUNCTION_LABELS = LABEL_ORDER[:-1]
SCOPE_LABELS = ("PROJECT", "NON_PROJECT")

PROFILES: dict[str, dict[str, tuple[int, int]]] = {
    "word_1_1": {"word": (1, 1)},
    "word_1_2": {"word": (1, 2)},
    "word_1_3": {"word": (1, 3)},
    "char_3_5": {"char": (3, 5)},
    "char_3_6": {"char": (3, 6)},
    "char_4_6": {"char": (4, 6)},
    "word_1_2_char_3_5": {"word": (1, 2), "char": (3, 5)},
    "word_1_2_char_3_6": {"word": (1, 2), "char": (3, 6)},
    "word_1_3_char_4_6": {"word": (1, 3), "char": (4, 6)},
}

_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}\s*(?:am|pm)?)\b", re.I,
)
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\b")
_DOMAIN_PATTERNS: dict[str, tuple[str, ...]] = {
    "meeting": (r"\bmeet(?:ing|ings)?\b", r"\bconference\b", r"\bagenda\b", r"\bminutes\b", r"\bcall\b", r"\bschedule\b", r"\breschedul\w*\b"),
    "deadline": (r"\bdeadline\b", r"\bdue\b", r"\bby\s+(?:monday|tuesday|wednesday|thursday|friday|\d{1,2}[/-])", r"\b(?:eod|cob|asap)\b", r"\b(?:tomorrow|today|next week)\b"),
    "report": (r"\breport\w*\b", r"\bspreadsheet\b", r"\bsummary\b", r"\bmetrics\b", r"\bstatus\b", r"\bprovide\b", r"\bsend me\b"),
    "action": (r"\bplease\b", r"\bcould you\b", r"\bwould you\b", r"\bneed you to\b", r"\baction item\b", r"\brequest\w*\b", r"\bsubmit\b", r"\bcomplete\b"),
    "approval": (r"\bapprov\w*\b", r"\bauthoriz\w*\b", r"\bconsent\b", r"\bconfirm\b", r"\bsign[- ]off\b"),
    "follow_up": (r"\bfollow(?:ing)?[- ]?up\b", r"\bcircling back\b", r"\bremind\w*\b", r"\bchecking in\b", r"\bper my (?:last )?email\b"),
    "department": (r"\bdepartment\b", r"\bteam\b", r"\bdivision\b", r"\bcommittee\b", r"\bgroup\b", r"\binput\b", r"\bfeedback\b"),
}
_COMPILED_DOMAIN = {
    key: tuple(re.compile(pattern, re.I) for pattern in patterns)
    for key, patterns in _DOMAIN_PATTERNS.items()
}


def _get_text(record: dict[str, Any], field_name: str) -> str:
    if field_name == "subject":
        return str(record.get("subject") or "")
    if field_name == "body":
        if record.get("authored_message") is not None:
            return str(record.get("authored_message") or "")
        return extract_authored_prefix(str(record.get("current_message") or ""))
    raise ValueError(f"unsupported text field: {field_name}")


def _domain_features(subject: str, body: str) -> dict[str, float]:
    full_text = f"{subject}\n{body}"
    lowered = full_text.lower()
    features: dict[str, float] = {
        "shape:subject_chars": min(len(subject), 500) / 500.0,
        "shape:body_chars_log": float(np.log1p(min(len(body), 20000))),
        "shape:subject_question": float("?" in subject),
        "shape:body_question": float("?" in body),
        "shape:has_date_or_time": float(bool(_DATE_RE.search(full_text))),
        "shape:number_count_log": float(np.log1p(len(_NUMBER_RE.findall(full_text)))),
        "shape:url_count_log": float(np.log1p(len(_URL_RE.findall(full_text)))),
        "shape:all_caps_subject": float(bool(subject) and subject.isupper()),
        "shape:has_bullet": float(bool(re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", body))),
        "shape:has_attachment_word": float(bool(re.search(r"\b(?:attached|attachment|enclosed)\b", lowered))),
    }
    for family, patterns in _COMPILED_DOMAIN.items():
        hits = [pattern.findall(full_text) for pattern in patterns]
        features[f"domain:{family}:matched_patterns"] = float(sum(bool(items) for items in hits))
        features[f"domain:{family}:mention_count"] = float(min(sum(len(items) for items in hits), 12))
    return features


class LexicalFeatureEncoder:
    """Fit-only feature vocabulary with separate subject/body channels."""

    def __init__(
        self, profile: str, *, text_mode: str = "subject_body", use_domain: bool = True,
        min_df: int = 1, max_features: int = 120_000, subject_weight: float = 1.5,
    ):
        if profile not in PROFILES:
            raise ValueError(f"unknown feature profile: {profile}")
        if text_mode not in {"subject_body", "subject_only", "body_only"}:
            raise ValueError(f"unknown text mode: {text_mode}")
        self.profile = profile
        self.text_mode = text_mode
        self.use_domain = bool(use_domain)
        self.min_df = min_df
        self.max_features = max_features
        self.subject_weight = subject_weight
        self.vectorizers: dict[str, TfidfVectorizer] = {}
        self.domain_vectorizer: DictVectorizer | None = None

    def _active_fields(self) -> tuple[str, ...]:
        if self.text_mode == "subject_only":
            return ("subject",)
        if self.text_mode == "body_only":
            return ("body",)
        return ("subject", "body")

    def _feature_docs(self, records: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
        return {field_name: [_get_text(record, field_name) for record in records]
                for field_name in self._active_fields()}

    def _domain_docs(self, records: Sequence[dict[str, Any]]) -> list[dict[str, float]]:
        return [
            _domain_features(
                _get_text(record, "subject") if self.text_mode != "body_only" else "",
                _get_text(record, "body") if self.text_mode != "subject_only" else "",
            )
            for record in records
        ]

    def fit(self, records: Sequence[dict[str, Any]]) -> "LexicalFeatureEncoder":
        if not records:
            raise ValueError("cannot fit feature encoder without training records")
        self.vectorizers = {}
        feature_docs = self._feature_docs(records)
        for field_name, texts in feature_docs.items():
            for analyzer, ngram_range in PROFILES[self.profile].items():
                key = f"{field_name}_{analyzer}"
                kwargs: dict[str, Any] = {
                    "ngram_range": ngram_range,
                    "sublinear_tf": True,
                    "min_df": self.min_df if analyzer == "word" else max(2, self.min_df),
                    "max_features": self.max_features,
                    "dtype": np.float32,
                    "strip_accents": "unicode",
                    "norm": "l2",
                }
                if analyzer == "word":
                    kwargs.update(analyzer="word", token_pattern=r"(?u)\b\w+\b", lowercase=True)
                else:
                    kwargs.update(analyzer="char_wb", lowercase=True)
                vectorizer = TfidfVectorizer(**kwargs)
                try:
                    vectorizer.fit(texts)
                except ValueError as exc:
                    # Empty subject-only corpora can occur in malformed rows;
                    # keep an empty channel out of the final matrix.
                    if "empty vocabulary" not in str(exc).lower():
                        raise
                    continue
                self.vectorizers[key] = vectorizer
        if self.use_domain:
            domain_docs = self._domain_docs(records)
            self.domain_vectorizer = DictVectorizer(dtype=np.float32, sparse=True)
            self.domain_vectorizer.fit(domain_docs)
        else:
            self.domain_vectorizer = None
        if not self.vectorizers and self.domain_vectorizer is None:
            raise ValueError("no usable lexical features were generated")
        return self

    def transform(self, records: Sequence[dict[str, Any]]) -> sparse.csr_matrix:
        if not self.vectorizers and self.domain_vectorizer is None:
            raise ValueError("feature encoder has not been fitted")
        feature_docs = self._feature_docs(records)
        matrices: list[sparse.spmatrix] = []
        for field_name, texts in feature_docs.items():
            weight = self.subject_weight if field_name == "subject" else 1.0
            for analyzer in PROFILES[self.profile]:
                key = f"{field_name}_{analyzer}"
                vectorizer = self.vectorizers.get(key)
                if vectorizer is not None:
                    matrix = vectorizer.transform(texts).tocsr()
                    if weight != 1.0:
                        matrix = matrix * weight
                    matrices.append(matrix)
        if self.domain_vectorizer is not None:
            domain_docs = self._domain_docs(records)
            domain_matrix = self.domain_vectorizer.transform(domain_docs)
            domain_matrix = normalize(domain_matrix, norm="l2", copy=False) * 0.5
            matrices.append(domain_matrix.tocsr())
        if not matrices:
            return sparse.csr_matrix((len(records), 0), dtype=np.float32)
        return sparse.hstack(matrices, format="csr", dtype=np.float32)


def _encode_targets(records: Sequence[dict[str, Any]], labels: Sequence[str]) -> np.ndarray:
    matrix = np.zeros((len(records), len(labels)), dtype=np.int8)
    for row_index, record in enumerate(records):
        active = record.get("labels", [])
        if not isinstance(active, list) or any(item not in LABEL_ORDER for item in active):
            raise ValueError("each record must contain a list of recognized labels")
        if "NON_PROJECT" in active and len(active) > 1:
            raise ValueError("NON_PROJECT cannot co-occur with project-function labels")
        active_set = set(active)
        matrix[row_index] = [int(label in active_set) for label in labels]
    return matrix


def _positive_weight(y: np.ndarray, class_weight: str, cap: float | None) -> float:
    positives = int(np.sum(y))
    negatives = int(len(y) - positives)
    if positives == 0 or negatives == 0 or class_weight == "none":
        return 1.0
    if class_weight == "sqrt":
        value = float(np.sqrt(negatives / positives))
        return min(float(cap), value) if cap is not None else value
    raise ValueError(f"unknown class weight mode: {class_weight}")


@dataclass
class BinaryHead:
    estimator: Any
    positive_weight: float = 1.0
    constant_probability: float | None = None
    calibration: Any = None

    def score(self, matrix: sparse.csr_matrix) -> np.ndarray:
        if self.constant_probability is not None:
            return np.full(matrix.shape[0], self.constant_probability, dtype=np.float64)
        if isinstance(self.estimator, LogisticRegression):
            return self.estimator.predict_proba(matrix)[:, 1]
        margins = self.estimator.decision_function(matrix)
        if self.calibration is not None:
            return self.calibration.predict_proba(np.asarray(margins).reshape(-1, 1))[:, 1]
        margins = np.clip(margins, -30, 30)
        return 1.0 / (1.0 + np.exp(-margins))

    def raw_score(self, matrix: sparse.csr_matrix) -> np.ndarray:
        if self.constant_probability is not None:
            return np.full(matrix.shape[0], self.constant_probability, dtype=np.float64)
        if isinstance(self.estimator, LogisticRegression):
            return self.estimator.predict_proba(matrix)[:, 1]
        return np.asarray(self.estimator.decision_function(matrix), dtype=np.float64)


@dataclass
class LexicalModel:
    """Serializable predictor returning probabilities in canonical LABEL_ORDER."""

    encoder: LexicalFeatureEncoder
    algorithm: str
    c: float
    class_weight: str = "none"
    weight_cap: float | None = None
    task: str = "flat"
    decode_mode: str = ""
    fallback: bool = False
    heads: dict[str, BinaryHead] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def fit(self, records: Sequence[dict[str, Any]]) -> "LexicalModel":
        if self.algorithm not in {"logistic", "linear_svc"}:
            raise ValueError(f"unknown algorithm: {self.algorithm}")
        if self.task not in {"flat", "hierarchical"}:
            raise ValueError(f"unknown task: {self.task}")
        self.decode_mode = self.decode_mode or self.task
        if self.c <= 0:
            raise ValueError("C must be positive")
        self.encoder.fit(records)
        matrix = self.encoder.transform(records)
        self.heads = {}
        if self.task == "flat":
            labels = LABEL_ORDER
            training_records = list(records)
            targets = _encode_targets(training_records, labels)
            self._fit_heads(matrix, targets, labels)
        else:
            targets_scope = np.asarray([int("NON_PROJECT" not in row.get("labels", [])) for row in records], dtype=np.int8)
            self._fit_head(matrix, targets_scope, "PROJECT")
            self.heads["NON_PROJECT"] = BinaryHead(None)
            project_rows = [row for row in records if "NON_PROJECT" not in row.get("labels", [])]
            project_matrix = matrix[np.asarray(["NON_PROJECT" not in row.get("labels", []) for row in records])]
            targets_functions = _encode_targets(project_rows, FUNCTION_LABELS)
            self._fit_heads(project_matrix, targets_functions, FUNCTION_LABELS)
        return self

    def _fit_heads(self, matrix: sparse.csr_matrix, targets: np.ndarray, labels: Sequence[str]) -> None:
        for index, label in enumerate(labels):
            self._fit_head(matrix, targets[:, index], label)

    def _fit_head(self, matrix: sparse.csr_matrix, y: np.ndarray, label: str) -> None:
        if len(y) == 0:
            self.heads[label] = BinaryHead(None, constant_probability=0.0)
            return
        positives = int(np.sum(y))
        if positives == 0 or positives == len(y):
            self.heads[label] = BinaryHead(None, constant_probability=float(positives / len(y)))
            return
        pos_weight = _positive_weight(y, self.class_weight, self.weight_cap)
        sample_weight = np.where(y == 1, pos_weight, 1.0)
        if self.algorithm == "logistic":
            estimator = LogisticRegression(C=self.c, solver="liblinear", max_iter=1200, tol=1e-4, random_state=42)
        else:
            estimator = LinearSVC(C=self.c, dual="auto", max_iter=3000, tol=1e-4, random_state=42)
        estimator.fit(matrix, y, sample_weight=sample_weight)
        self.heads[label] = BinaryHead(estimator, positive_weight=pos_weight)

    def predict_proba(self, records: Sequence[dict[str, Any]]) -> np.ndarray:
        matrix = self.encoder.transform(records)
        return self.predict_proba_matrix(matrix)

    def predict_proba_matrix(self, matrix: sparse.csr_matrix) -> np.ndarray:
        if self.task == "flat":
            return np.column_stack([self.heads[label].score(matrix) for label in LABEL_ORDER])
        project_probability = self.heads["PROJECT"].score(matrix)
        probabilities = np.zeros((matrix.shape[0], len(LABEL_ORDER)), dtype=np.float64)
        probabilities[:, -1] = 1.0 - project_probability
        for index, label in enumerate(FUNCTION_LABELS):
            probabilities[:, index] = self.heads[label].score(matrix)
        return probabilities

    def raw_proba_matrix(self, matrix: sparse.csr_matrix) -> np.ndarray:
        """Scores before optional SVC Platt calibration, for strict group OOF."""
        if self.task == "flat":
            return np.column_stack([self.heads[label].raw_score(matrix) for label in LABEL_ORDER])
        project_score = self.heads["PROJECT"].raw_score(matrix)
        if isinstance(self.heads["PROJECT"].estimator, LogisticRegression) or self.heads["PROJECT"].constant_probability is not None:
            project_probability = project_score
        else:
            project_probability = 1.0 / (1.0 + np.exp(-np.clip(project_score, -30, 30)))
        probabilities = np.zeros((matrix.shape[0], len(LABEL_ORDER)), dtype=np.float64)
        probabilities[:, -1] = 1.0 - project_probability
        for index, label in enumerate(FUNCTION_LABELS):
            head = self.heads[label]
            raw = head.raw_score(matrix)
            conditional = raw if isinstance(head.estimator, LogisticRegression) or head.constant_probability is not None else 1.0 / (1.0 + np.exp(-np.clip(raw, -30, 30)))
            probabilities[:, index] = conditional
        return probabilities

    def predict(self, records: Sequence[dict[str, Any]], thresholds: dict[str, float] | None = None) -> list[list[str]]:
        probability_matrix = self.predict_proba(records)
        selected_thresholds = thresholds or self.thresholds or {label: 0.5 for label in LABEL_ORDER}
        from .optimization_benchmark import decode
        threshold_vector = [selected_thresholds.get(label, 0.5) for label in LABEL_ORDER]
        return decode(probability_matrix, threshold_vector, mode=self.task)


@dataclass
class LexicalSpecialistBundle:
    """Assemble one TRAIN/DEV-selected independent model per canonical label."""

    models: dict[str, LexicalModel]
    source_labels: dict[str, str]
    thresholds: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)
    decode_mode: str = "flat"
    fallback: bool = False

    def predict_proba(self, records: Sequence[dict[str, Any]]) -> np.ndarray:
        output = np.zeros((len(records), len(LABEL_ORDER)), dtype=np.float64)
        cache: dict[str, np.ndarray] = {}
        for label_index, label in enumerate(LABEL_ORDER):
            model_key = self.source_labels[label]
            if model_key not in cache:
                cache[model_key] = self.models[model_key].predict_proba(records)
            output[:, label_index] = cache[model_key][:, LABEL_ORDER.index(label)]
        return output


@dataclass
class LabelDependencyModel:
    """Second-stage OVR LR over strictly grouped-OOF base probabilities."""

    c: float
    heads: dict[str, BinaryHead] = field(default_factory=dict)

    def fit(self, base_probabilities: np.ndarray, target_matrix: np.ndarray) -> "LabelDependencyModel":
        matrix = sparse.csr_matrix(np.asarray(base_probabilities, dtype=np.float32))
        targets = np.asarray(target_matrix, dtype=np.int8)
        self.heads = {}
        for index, label in enumerate(LABEL_ORDER):
            y = targets[:, index]
            if not np.any(y) or np.all(y):
                probability = float(np.mean(y)) if len(y) else 0.0
                self.heads[label] = BinaryHead(None, constant_probability=probability)
                continue
            estimator = LogisticRegression(C=self.c, solver="liblinear", max_iter=1200, tol=1e-4, random_state=42)
            estimator.fit(matrix, y)
            self.heads[label] = BinaryHead(estimator)
        return self

    def predict_proba(self, base_probabilities: np.ndarray) -> np.ndarray:
        matrix = sparse.csr_matrix(np.asarray(base_probabilities, dtype=np.float32))
        return np.column_stack([self.heads[label].score(matrix) for label in LABEL_ORDER])


@dataclass
class LexicalDependencyBundle:
    """Callable base model plus OOF-trained label-dependency correction."""

    base_model: Any
    dependency_model: LabelDependencyModel
    thresholds: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    decode_mode: str = "flat"
    fallback: bool = False

    def predict_proba(self, records: Sequence[dict[str, Any]]) -> np.ndarray:
        return self.dependency_model.predict_proba(self.base_model.predict_proba(records))


def make_model(
    *, profile: str, algorithm: str, c: float, task: str = "flat",
    text_mode: str = "subject_body", use_domain: bool = True,
    class_weight: str = "none", weight_cap: float | None = None,
) -> LexicalModel:
    encoder = LexicalFeatureEncoder(profile, text_mode=text_mode, use_domain=use_domain)
    return LexicalModel(encoder, algorithm, c, class_weight, weight_cap, task)


def predict(model: Any, records: Sequence[dict[str, Any]]) -> np.ndarray:
    """Shared bundle contract: records in, one Nx9 canonical probability array out."""
    output = model.predict_proba(records)
    if output.shape != (len(records), len(LABEL_ORDER)):
        raise ValueError("lexical predictor returned an invalid probability shape")
    return output


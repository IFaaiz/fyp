"""Source-grounded metrics for native MailEx event extraction.

Rows are message-level dictionaries with ``message_id``, ``text`` and an
``events`` list. Each event owns its trigger and argument records. Span offsets
are half-open Python character offsets into ``text``; discontinuous spans are
represented as a list of segments. The evaluator never searches text to repair
or relocate an annotation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


IOU_THRESHOLD = 0.5


class EvaluationDataError(ValueError):
    """Raised when gold/prediction rows are structurally unsafe to score."""


@dataclass(frozen=True)
class Segment:
    start: int | None
    end: int | None
    text: str | None
    valid_offsets: bool
    source_exact: bool

    @property
    def signature(self) -> tuple[int | None, int | None]:
        return (self.start, self.end)


@dataclass(frozen=True)
class SpanGroup:
    segments: tuple[Segment, ...]

    @property
    def has_geometry(self) -> bool:
        return any(segment.valid_offsets for segment in self.segments)

    @property
    def source_exact(self) -> bool:
        return bool(self.segments) and all(segment.source_exact for segment in self.segments)

    @property
    def exact_key(self) -> tuple[tuple[int | None, int | None], ...]:
        return tuple(sorted(segment.signature for segment in self.segments))


@dataclass(frozen=True)
class Argument:
    role: str
    qualifier: str | None
    span: SpanGroup
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Event:
    event_type: str
    trigger: SpanGroup
    arguments: tuple[Argument, ...]
    flags: tuple[str, ...] = ()
    event_id: str | None = None

    @property
    def has_geometry(self) -> bool:
        return self.trigger.has_geometry or any(arg.span.has_geometry for arg in self.arguments)


@dataclass(frozen=True)
class Message:
    message_id: str
    split: str
    text: str
    events: tuple[Event, ...]


def _as_flags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _span_object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise EvaluationDataError(f"span segment must be an object, got {type(value).__name__}")


def _span_segments(value: Any) -> list[Mapping[str, Any]]:
    """Accept canonical segment arrays plus a single start/end segment."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        segments = value.get("segments", value.get("spans"))
        if segments is not None:
            if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
                raise EvaluationDataError("span 'segments' must be a list")
            return [_span_object(segment) for segment in segments]
        if "start" in value or "char_start" in value:
            return [value]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_span_object(segment) for segment in value]
    raise EvaluationDataError(f"span must be an object or segment list, got {type(value).__name__}")


def _parse_span(value: Any, text: str, *, gold: bool, where: str,
                source_counts: Counter[str]) -> SpanGroup:
    parsed: list[Segment] = []
    for index, raw in enumerate(_span_segments(value)):
        start = raw.get("start", raw.get("char_start"))
        end = raw.get("end", raw.get("char_end"))
        label = f"{where}[{index}]"
        valid_offsets = (
            isinstance(start, int) and not isinstance(start, bool)
            and isinstance(end, int) and not isinstance(end, bool)
            and 0 <= start < end <= len(text)
        )
        if not valid_offsets:
            source_counts["invalid_offset_segments"] += 1
            if gold:
                raise EvaluationDataError(
                    f"malformed gold span at {label}: expected 0 <= start < end <= len(text); "
                    f"got start={start!r}, end={end!r}, text_length={len(text)}"
                )
            parsed.append(Segment(start if isinstance(start, int) else None,
                                  end if isinstance(end, int) else None,
                                  raw.get("text") if isinstance(raw.get("text"), str) else None,
                                  False, False))
            continue
        supplied = raw.get("text")
        expected = text[start:end]
        if gold and supplied is None:
            raise EvaluationDataError(f"gold span at {label} has no source text field")
        source_exact = isinstance(supplied, str) and supplied == expected
        if not source_exact:
            source_counts["text_offset_mismatches"] += supplied is not None
            if gold and supplied is not None:
                raise EvaluationDataError(
                    f"gold span text disagrees with text[{start}:{end}] at {label}; "
                    "the evaluator will not relocate or repair it"
                )
        if supplied is None:
            source_counts["missing_span_text"] += 1
        if not source_exact:
            source_counts["non_source_segments"] += 1
            if gold:
                raise EvaluationDataError(f"gold span at {label} has no source text field")
        parsed.append(Segment(start, end, supplied if isinstance(supplied, str) else None,
                              True, source_exact))
    return SpanGroup(tuple(parsed))


def _event_type(raw: Mapping[str, Any]) -> str:
    value = raw.get("event_type", raw.get("type"))
    if not isinstance(value, str) or not value:
        raise EvaluationDataError("each event needs a non-empty event_type string")
    return value


def _parse_message(raw: Mapping[str, Any], *, gold: bool,
                   source_counts: Counter[str]) -> Message:
    message_id = raw.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise EvaluationDataError("each message row needs a non-empty message_id")
    split = raw.get("split")
    if not isinstance(split, str) or not split:
        raise EvaluationDataError(f"message {message_id!r} has no split label")
    text = raw.get("text", raw.get("body"))
    if not isinstance(text, str):
        raise EvaluationDataError(f"message {message_id!r} has no text/body string")
    raw_events = raw.get("events", [])
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
        raise EvaluationDataError(f"message {message_id!r} events must be a list")
    parsed_events: list[Event] = []
    for event_index, raw_event in enumerate(raw_events):
        if not isinstance(raw_event, Mapping):
            raise EvaluationDataError(f"message {message_id!r} event {event_index} must be an object")
        etype = _event_type(raw_event)
        prefix = f"{message_id}/event[{event_index}]"
        trigger = _parse_span(raw_event.get("trigger", raw_event.get("triggers")), text,
                              gold=gold, where=prefix + "/trigger", source_counts=source_counts)
        raw_args = raw_event.get("arguments", raw_event.get("args", []))
        if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes)):
            raise EvaluationDataError(f"{prefix} arguments must be a list")
        arguments: list[Argument] = []
        for arg_index, raw_arg in enumerate(raw_args):
            if not isinstance(raw_arg, Mapping):
                raise EvaluationDataError(f"{prefix}/argument[{arg_index}] must be an object")
            role = raw_arg.get("role", raw_arg.get("argument_role"))
            if not isinstance(role, str) or not role:
                raise EvaluationDataError(f"{prefix}/argument[{arg_index}] needs a non-empty role")
            qualifier = raw_arg.get("qualifier")
            if qualifier is not None and not isinstance(qualifier, str):
                qualifier = str(qualifier)
            span = _parse_span(raw_arg.get("segments", raw_arg.get("span", raw_arg.get("spans"))),
                               text, gold=gold, where=f"{prefix}/argument[{arg_index}]",
                               source_counts=source_counts)
            flags = _as_flags(raw_arg.get("flags"))
            source_counts["flagged_gold_arguments" if gold else "flagged_prediction_arguments"] += bool(flags)
            arguments.append(Argument(role, qualifier, span, flags))
        flags = _as_flags(raw_event.get("flags"))
        source_counts["flagged_gold_events" if gold else "flagged_prediction_events"] += bool(flags)
        parsed_events.append(Event(etype, trigger, tuple(arguments), flags,
                                  str(raw_event["event_id"]) if raw_event.get("event_id") is not None else None))
    return Message(message_id, split, text, tuple(parsed_events))


def _merge_intervals(span: SpanGroup) -> list[tuple[int, int]]:
    intervals = sorted((s.start, s.end) for s in span.segments
                       if s.valid_offsets and s.source_exact and s.start is not None and s.end is not None)
    merged: list[list[int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def span_iou(left: SpanGroup, right: SpanGroup) -> float:
    """Character interval IoU, unioning internal overlaps to avoid double credit."""
    a, b = _merge_intervals(left), _merge_intervals(right)
    if not a or not b:
        return 0.0
    i = j = intersection = 0
    while i < len(a) and j < len(b):
        intersection += max(0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    len_a = sum(end - start for start, end in a)
    len_b = sum(end - start for start, end in b)
    union = len_a + len_b - intersection
    return intersection / union if union else 0.0


def _span_exact(left: SpanGroup, right: SpanGroup) -> bool:
    if not all(s.valid_offsets and s.source_exact for s in left.segments + right.segments):
        return False
    return left.exact_key == right.exact_key


def _hungarian_max(weights: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Deterministic maximum assignment for a rectangular, nonnegative matrix."""
    rows = len(weights)
    cols = len(weights[0]) if rows else 0
    if not rows or not cols:
        return []
    n = max(rows, cols)
    max_weight = max((value for row in weights for value in row), default=0.0)
    # Hungarian minimization with stable ascending scans for deterministic ties.
    costs = [[max_weight - (weights[i][j] if i < rows and j < cols else 0.0)
              for j in range(n)] for i in range(n)]
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = costs[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = []
    for j in range(1, n + 1):
        i = p[j] - 1
        jj = j - 1
        if i < rows and jj < cols and weights[i][jj] > 0:
            assignment.append((i, jj))
    return sorted(assignment)


def _thresholded_assignment(weights: Sequence[Sequence[float]], threshold: float
                            ) -> list[tuple[int, int, float]]:
    """Maximize a one-to-one assignment after removing sub-threshold edges."""
    eligible = [[value if value >= threshold else 0.0 for value in row] for row in weights]
    return [(i, j, weights[i][j]) for i, j in _hungarian_max(eligible)]


def _groups_score(left: Sequence[SpanGroup], right: Sequence[SpanGroup], *,
                  threshold: float = IOU_THRESHOLD) -> tuple[float, list[tuple[int, int, float]]]:
    raw_weights = [[span_iou(a, b) for b in right] for a in left]
    pairs = _thresholded_assignment(raw_weights, threshold)
    return sum(score for _, _, score in pairs), pairs


def _arg_span_affinity(left: Event, right: Event) -> tuple[float, int]:
    left_spans = [arg.span for arg in left.arguments if arg.span.has_geometry]
    right_spans = [arg.span for arg in right.arguments if arg.span.has_geometry]
    if not left_spans or not right_spans:
        return 0.0, 0
    score, matches = _groups_score(left_spans, right_spans, threshold=0.0)
    return score, len(matches)


def _primary_record_affinity(left: Event, right: Event) -> float:
    """Same-type record alignment, dominated by attached argument spans."""
    if left.event_type != right.event_type:
        return 0.0
    overlap, _ = _arg_span_affinity(left, right)
    if overlap > 0:
        denom = max(sum(arg.span.has_geometry for arg in left.arguments),
                    sum(arg.span.has_geometry for arg in right.arguments), 1)
        return 1.0 + overlap / denom
    left_has_geometry = any(arg.span.has_geometry for arg in left.arguments)
    right_has_geometry = any(arg.span.has_geometry for arg in right.arguments)
    if not left_has_geometry and not right_has_geometry:
        # Direct records with no mention offsets are aligned by event type and
        # matching attached role/qualifier records, then stable input order.
        left_records = Counter((arg.role, arg.qualifier, arg.span.exact_key) for arg in left.arguments)
        right_records = Counter((arg.role, arg.qualifier, arg.span.exact_key) for arg in right.arguments)
        common = sum((left_records & right_records).values())
        denom = max(len(left.arguments), len(right.arguments), 1)
        return 1.0 + common / denom
    return 0.0


def _diagnostic_affinity(left: Event, right: Event) -> float:
    """Residual event identity alignment for type errors and event detection."""
    trigger = span_iou(left.trigger, right.trigger)
    args, _ = _arg_span_affinity(left, right)
    denom = max(sum(arg.span.has_geometry for arg in left.arguments),
                sum(arg.span.has_geometry for arg in right.arguments), 1)
    arg_score = args / denom
    score = 0.5 * trigger + 0.5 * arg_score
    if score > 0 and left.event_type == right.event_type:
        score += 0.0001
    if score > 0:
        return score
    if left.event_type == right.event_type and not left.has_geometry and not right.has_geometry:
        return 0.0001
    return 0.0


def _assign_primary_records(gold: Sequence[Event], pred: Sequence[Event]) -> list[tuple[int, int]]:
    if not gold or not pred:
        return []
    weights = [[_primary_record_affinity(g, p) for p in pred] for g in gold]
    return _hungarian_max(weights)


def _assign_diagnostic_events(gold: Sequence[Event], pred: Sequence[Event]) -> list[tuple[int, int]]:
    if not gold or not pred:
        return []
    weights = [[_diagnostic_affinity(g, p) for p in pred] for g in gold]
    return _hungarian_max(weights)


def _prf(tp: float, predicted: float, support: float) -> dict[str, float | None]:
    precision = tp / predicted if predicted else None
    recall = tp / support if support else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else
          0.0 if precision == 0 or recall == 0 else None)
    return {"precision": precision, "recall": recall, "f1": f1,
            "true_positive_credit": tp, "predicted": predicted, "support": support}


def _per_label_report(gold_counts: Counter[str], pred_counts: Counter[str],
                      true_counts: Counter[str]) -> dict[str, Any]:
    labels = sorted(set(gold_counts) | set(pred_counts) | set(true_counts))
    per_label: dict[str, Any] = {}
    for label in labels:
        metric = _prf(true_counts[label], pred_counts[label], gold_counts[label])
        if gold_counts[label] and not pred_counts[label]:
            metric["precision"] = 0.0
            metric["f1"] = 0.0
        per_label[label] = {**metric, "support": gold_counts[label]}
    supported = [per_label[label] for label in labels if gold_counts[label] > 0]
    macro = {}
    for key in ("precision", "recall", "f1"):
        defined = [row[key] for row in supported if row[key] is not None]
        macro[key] = sum(defined) / len(defined) if defined else None
    return {"micro": _prf(sum(true_counts.values()), sum(pred_counts.values()), sum(gold_counts.values())),
            "macro_over_gold_supported_labels": macro, "by_label": per_label}


def _exact_argument_matches(gold: Sequence[Argument], pred: Sequence[Argument]) -> list[tuple[int, int]]:
    weights = [[1.0 if (a.role == b.role and a.qualifier == b.qualifier and _span_exact(a.span, b.span)) else 0.0
                for b in pred] for a in gold]
    return _hungarian_max(weights)


def _exact_span_matches(gold: Sequence[Argument], pred: Sequence[Argument]) -> list[tuple[int, int]]:
    weights = [[1.0 if _span_exact(a.span, b.span) else 0.0 for b in pred] for a in gold]
    return _hungarian_max(weights)


def _label_aware_span_matches(gold: Sequence[Argument], pred: Sequence[Argument], *,
                              label: str, threshold: float,
                              exact: bool = False) -> list[tuple[int, int, float]]:
    raw_iou = [[span_iou(a.span, b.span) for b in pred] for a in gold]
    # Cardinality is primary, overlap is secondary, and label agreement breaks
    # ties. The base weight exceeds the maximum possible aggregate secondary
    # difference, preserving maximum cardinality before maximizing overlap.
    cardinality_weight = max(len(gold), len(pred), 1) + 1.0
    weights = []
    for i, row in enumerate(raw_iou):
        weighted_row = []
        for j, overlap in enumerate(row):
            eligible = _span_exact(gold[i].span, pred[j].span) if exact else overlap >= threshold
            if not eligible:
                weighted_row.append(0.0)
                continue
            left = getattr(gold[i], label)
            right = getattr(pred[j], label)
            weighted_row.append(cardinality_weight + overlap + (0.000001 if left == right else 0.0))
        weights.append(weighted_row)
    pairs = _hungarian_max(weights)
    return [(i, j, raw_iou[i][j]) for i, j in pairs]


def _partial_argument_matches(gold: Sequence[Argument], pred: Sequence[Argument]) -> list[tuple[int, int, float]]:
    weights = []
    for a in gold:
        row = []
        for b in pred:
            if a.role != b.role or a.qualifier != b.qualifier:
                row.append(0.0)
            elif not a.span.segments and not b.span.segments:
                row.append(1.0)
            else:
                overlap = span_iou(a.span, b.span)
                row.append(overlap if overlap >= IOU_THRESHOLD else 0.0)
        weights.append(row)
    return _thresholded_assignment(weights, IOU_THRESHOLD)


def _span_only_matches(gold: Sequence[Argument], pred: Sequence[Argument]) -> list[tuple[int, int, float]]:
    raw_weights = [[span_iou(a.span, b.span) for b in pred] for a in gold]
    return _thresholded_assignment(raw_weights, IOU_THRESHOLD)


def _event_exact(gold: Event, pred: Event) -> bool:
    if gold.event_type != pred.event_type:
        return False
    if len(_exact_argument_matches(gold.arguments, pred.arguments)) != len(gold.arguments) or len(gold.arguments) != len(pred.arguments):
        return False
    return True


def _partial_event_credit(gold: Event, pred: Event) -> tuple[float, float]:
    if gold.event_type != pred.event_type:
        return 0.0, 0.0
    matches = _partial_argument_matches(gold.arguments, pred.arguments)
    p_arg = len(matches) / len(pred.arguments) if pred.arguments else (1.0 if not gold.arguments else 0.0)
    r_arg = len(matches) / len(gold.arguments) if gold.arguments else (1.0 if not pred.arguments else 0.0)
    return p_arg, r_arg


def _validate_rows(rows: Iterable[Mapping[str, Any]], *, gold: bool,
                   source_counts: Counter[str]) -> dict[str, Message]:
    result: dict[str, Message] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise EvaluationDataError(f"row {index} must be an object")
        message = _parse_message(raw, gold=gold, source_counts=source_counts)
        if message.message_id in result:
            raise EvaluationDataError(f"duplicate message_id {message.message_id!r}")
        result[message.message_id] = message
    return result


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCK_FORBIDDEN_KEYS = {
    "text", "body", "prediction_rows", "messages", "source_text",
    "raw_message", "examples",
}


def validate_test_authorization(lock: Mapping[str, Any]) -> None:
    """Validate the text-only shape required for TEST scoring.

    The CLI additionally proves the manifest is committed/clean and checks
    every listed file against its digest before reading TEST rows.
    """
    if lock.get("schema_version") != 1 or lock.get("status") != "locked" or lock.get("split") != "test":
        raise EvaluationDataError("TEST requires a schema_version=1 locked selection manifest for split=test")
    if not isinstance(lock.get("gold_sha256"), str) or not _SHA256_RE.fullmatch(lock["gold_sha256"]):
        raise EvaluationDataError("selection manifest needs a frozen 64-character gold_sha256")
    if not isinstance(lock.get("gold_path"), str) or not lock["gold_path"]:
        raise EvaluationDataError("selection manifest needs the frozen gold_path")
    finalists = lock.get("finalists")
    if not isinstance(finalists, list) or not finalists:
        raise EvaluationDataError("selection manifest must contain at least one finalist")
    run_ids: set[str] = set()
    for index, finalist in enumerate(finalists):
        if not isinstance(finalist, Mapping):
            raise EvaluationDataError(f"selection finalist {index} must be an object")
        run_id = finalist.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id in run_ids:
            raise EvaluationDataError("finalist run_id values must be non-empty and unique")
        run_ids.add(run_id)
        if not isinstance(finalist.get("architecture"), str) or not finalist["architecture"]:
            raise EvaluationDataError(f"finalist {run_id!r} needs a frozen architecture")
        if not isinstance(finalist.get("config"), Mapping):
            raise EvaluationDataError(f"finalist {run_id!r} needs a frozen config object")
        if not isinstance(finalist.get("thresholds"), Mapping):
            raise EvaluationDataError(f"finalist {run_id!r} needs frozen thresholds")
        expected = finalist.get("expected_output_path", finalist.get("expected_private_output_path"))
        if not isinstance(expected, str) or not expected:
            raise EvaluationDataError(f"finalist {run_id!r} needs an expected private output path")
        schema_hash = finalist.get("schema_sha256")
        if schema_hash is not None and (not isinstance(schema_hash, str) or not _SHA256_RE.fullmatch(schema_hash)):
            raise EvaluationDataError(f"finalist {run_id!r} schema_sha256 must be a SHA-256 digest")
        for key in ("model_weights", "code", "preprocessing", "evaluator", "schema"):
            values = finalist.get(key)
            if key == "schema" and values is None and schema_hash is not None:
                # Single-file schema form; schema_path is still hash-checked.
                schema_path = finalist.get("schema_path")
                if isinstance(schema_path, str) and schema_path:
                    values = {schema_path: schema_hash}
            if not isinstance(values, Mapping) or not values:
                raise EvaluationDataError(f"finalist {run_id!r} needs a non-empty {key} path-to-SHA256 map")
            for artifact_path, digest in values.items():
                if not isinstance(artifact_path, str) or not artifact_path:
                    raise EvaluationDataError(f"finalist {run_id!r} has an invalid {key} path")
                if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                    raise EvaluationDataError(f"finalist {run_id!r} has an invalid {key} SHA-256 for {artifact_path!r}")
    def reject_source_content(value: Any, location: str = "manifest") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).casefold() in _LOCK_FORBIDDEN_KEYS:
                    raise EvaluationDataError(f"selection manifest must be text-only metadata; forbidden field {location}.{key}")
                reject_source_content(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                reject_source_content(child, f"{location}[{index}]")
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise EvaluationDataError(f"selection manifest contains non-text metadata at {location}")
    reject_source_content(lock)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_relative_file(root: Path, value: str, *, context: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise EvaluationDataError(f"{context} must resolve within the repository: {value!r}") from exc
    if not candidate.is_file():
        raise EvaluationDataError(f"{context} file does not exist: {value!r}")
    return candidate


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_artifact_map(root: Path, artifacts: Mapping[str, str], *, context: str) -> None:
    for relative, expected in artifacts.items():
        path = _repo_relative_file(root, relative, context=context)
        actual = _sha256_bytes(path.read_bytes())
        if actual != expected:
            raise EvaluationDataError(f"{context} digest changed for {relative!r}")


def validate_committed_test_lock(selection_lock_path: str | Path) -> dict[str, Any]:
    """Load a committed, clean selection lock and verify its frozen files."""
    root = _repository_root()
    candidate = Path(selection_lock_path)
    lock_path = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        relative = lock_path.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise EvaluationDataError("selection lock must be inside the repository") from exc
    if lock_path.suffix.casefold() != ".json":
        raise EvaluationDataError("selection lock must be a JSON text manifest")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", relative], cwd=root,
                             capture_output=True, text=True)
    if tracked.returncode:
        raise EvaluationDataError("selection lock is not tracked by git")
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", relative],
                            cwd=root, capture_output=True, text=True)
    if status.returncode or status.stdout.strip():
        raise EvaluationDataError("selection lock must be committed and clean")
    committed = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=root,
                              capture_output=True)
    if committed.returncode:
        raise EvaluationDataError("selection lock has no committed HEAD version")
    raw = lock_path.read_bytes()
    if committed.stdout != raw:
        raise EvaluationDataError("selection lock bytes differ from committed HEAD")
    try:
        lock = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationDataError("selection lock must be valid UTF-8 JSON") from exc
    if not isinstance(lock, Mapping):
        raise EvaluationDataError("selection lock root must be an object")
    validate_test_authorization(lock)
    gold_path = _repo_relative_file(root, lock["gold_path"], context="locked TEST gold")
    if _sha256_bytes(gold_path.read_bytes()) != lock["gold_sha256"]:
        raise EvaluationDataError("locked TEST gold digest changed")
    for finalist in lock["finalists"]:
        for key in ("model_weights", "code", "preprocessing", "evaluator", "schema"):
            values = finalist.get(key)
            if values is None and key == "schema" and finalist.get("schema_sha256") is not None:
                schema_path = finalist.get("schema_path")
                values = {schema_path: finalist["schema_sha256"]} if schema_path else {}
            _verify_artifact_map(root, values, context=f"finalist {finalist['run_id']} {key}")
    return {"manifest": dict(lock), "path": lock_path, "relative_path": relative,
            "sha256": _sha256_bytes(raw), "repository_root": root}


def _finalist_by_id(lock: Mapping[str, Any], run_id: str) -> Mapping[str, Any]:
    found = [item for item in lock["finalists"] if item["run_id"] == run_id]
    if len(found) != 1:
        raise EvaluationDataError(f"run_id {run_id!r} is not a unique finalist in the selection lock")
    return found[0]


def reserve_test_run(selection_lock_path: str | Path, run_id: str) -> Path:
    """Exclusively reserve a finalist before one-time TEST inference.

    The marker lives below the ignored private experiment directory and is
    created with exclusive file creation, so concurrent or later reservations
    for the same finalist fail.
    """
    lock_info = validate_committed_test_lock(selection_lock_path)
    finalist = _finalist_by_id(lock_info["manifest"], run_id)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise EvaluationDataError("run_id contains characters unsafe for a private marker filename")
    output_relative = finalist.get("expected_output_path", finalist.get("expected_private_output_path"))
    output_path = (lock_info["repository_root"] / output_relative).resolve()
    try:
        output_path.relative_to(lock_info["repository_root"].resolve())
    except ValueError as exc:
        raise EvaluationDataError("expected private TEST output must stay inside the repository") from exc
    if output_path.exists():
        raise EvaluationDataError(f"expected TEST output already exists for {run_id!r}")
    private_dir = lock_info["repository_root"] / "ai" / "data" / "experiments" / "mailex_extraction_v1" / "private_test"
    private_dir.mkdir(parents=True, exist_ok=True)
    marker = private_dir / f"{run_id}.reservation.json"
    payload = {"run_id": run_id, "status": "reserved_before_inference",
               "selection_lock_sha256": lock_info["sha256"],
               "expected_output_path": output_path.relative_to(lock_info["repository_root"]).as_posix()}
    try:
        with marker.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise EvaluationDataError(f"TEST inference is already reserved or completed for {run_id!r}") from exc
    return marker


def score_rows(gold_rows: Iterable[Mapping[str, Any]],
               prediction_rows: Iterable[Mapping[str, Any]], *,
               split: str = "dev",
               test_authorization: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Score predictions against native MailEx rows for ``train`` or ``dev``.

    TEST requires the frozen selection manifest through ``test_authorization``.
    The CLI verifies the committed manifest and its digests before reading
    TEST files. Offset overlap uses
    character IoU >= 0.50; exact means identical ordered-independent segment
    boundaries. All matching is one-to-one and scoped to one message/event.
    """
    if split not in {"train", "dev", "test"}:
        raise EvaluationDataError("split must be train, dev, or test")
    if split == "test":
        if test_authorization is None:
            raise EvaluationDataError("TEST scoring requires a valid locked selection manifest")
        validate_test_authorization(test_authorization)
    elif test_authorization is not None:
        raise EvaluationDataError("test_authorization is only valid when split='test'")
    source_counts: Counter[str] = Counter()
    gold_by_id = _validate_rows(gold_rows, gold=True, source_counts=source_counts)
    pred_by_id = _validate_rows(prediction_rows, gold=False, source_counts=source_counts)
    for message_id in set(gold_by_id) & set(pred_by_id):
        gold_message = gold_by_id[message_id]
        pred_message = pred_by_id[message_id]
        if gold_message.split == split or pred_message.split == split:
            if gold_message.split != pred_message.split:
                raise EvaluationDataError(
                    f"prediction split disagrees with gold for message {message_id!r}"
                )
            if gold_message.text != pred_message.text:
                raise EvaluationDataError(
                    f"prediction text differs from gold for message {message_id!r}; "
                    "source offsets must be checked against the original message"
                )
    gold_by_id = {mid: row for mid, row in gold_by_id.items() if row.split == split}
    pred_by_id = {mid: row for mid, row in pred_by_id.items() if row.split == split}
    if not gold_by_id:
        raise EvaluationDataError(f"no gold messages found for split {split!r}")

    all_ids = sorted(set(gold_by_id) | set(pred_by_id))
    gold_events = pred_events = paired_events = 0
    type_gold: Counter[str] = Counter()
    type_pred: Counter[str] = Counter()
    type_tp: Counter[str] = Counter()
    type_confusion: Counter[tuple[str, str]] = Counter()
    event_errors: Counter[str] = Counter()
    event_record_gold = event_record_pred = event_record_exact_tp = 0
    event_record_trigger_exact_tp = 0
    partial_p_credit = partial_r_credit = 0.0
    partial_trigger_p_credit = partial_trigger_r_credit = 0.0

    trigger_gold = trigger_pred = trigger_exact_tp = trigger_partial_tp = 0
    trigger_iou_credit = 0.0
    trigger_type_enabled: set[str] = set()
    trigger_type_gold: Counter[str] = Counter()
    trigger_type_pred: Counter[str] = Counter()
    trigger_type_tp: Counter[str] = Counter()
    trigger_type_confusion: Counter[tuple[str, str]] = Counter()
    trigger_errors: Counter[str] = Counter()

    arg_gold = arg_pred = arg_exact_tp = arg_partial_tp = 0
    arg_span_exact_tp = arg_span_overlap_tp = 0
    arg_span_matches = role_correct = qualifier_correct = 0
    role_qualifier_exact_tp = 0
    arg_errors: Counter[str] = Counter()
    role_gold: Counter[str] = Counter()
    role_pred: Counter[str] = Counter()
    role_exact_tp: Counter[str] = Counter()
    role_partial_tp: Counter[str] = Counter()
    role_qualifier_gold = role_qualifier_pred = 0
    qualifier_gold: Counter[str] = Counter()
    qualifier_pred: Counter[str] = Counter()
    qualifier_tp: Counter[str] = Counter()
    qualifier_exact_tp: Counter[str] = Counter()
    arg_type_role_gold: Counter[str] = Counter()
    arg_type_role_pred: Counter[str] = Counter()
    arg_type_role_tp: Counter[str] = Counter()

    messages_with_pred_events = messages_without_pred_events = messages_without_gold_events = 0
    evaluated_message_count = len(all_ids)
    gold_message_count = len(gold_by_id)
    prediction_message_count = len(pred_by_id)

    for message in gold_by_id.values():
        for event in message.events:
            if event.trigger.segments:
                trigger_type_enabled.add(event.event_type)

    for message_id in all_ids:
        gold_message = gold_by_id.get(message_id)
        pred_message = pred_by_id.get(message_id)
        gold_events_for_message = gold_message.events if gold_message else ()
        pred_events_for_message = pred_message.events if pred_message else ()
        gold_events += len(gold_events_for_message)
        pred_events += len(pred_events_for_message)
        event_record_gold += len(gold_events_for_message)
        event_record_pred += len(pred_events_for_message)
        if pred_events_for_message:
            messages_with_pred_events += 1
        else:
            messages_without_pred_events += 1
        if not gold_events_for_message:
            messages_without_gold_events += 1

        for event in gold_events_for_message:
            type_gold[event.event_type] += 1
            arg_gold += len(event.arguments)
            if event.trigger.segments:
                trigger_gold += 1
                trigger_type_gold[event.event_type] += 1
            for argument in event.arguments:
                role_gold[argument.role] += 1
                qualifier_gold[argument.qualifier or "<none>"] += 1
                role_qualifier_gold += 1
                arg_type_role_gold[f"{event.event_type}::{argument.role}"] += 1
        for event in pred_events_for_message:
            type_pred[event.event_type] += 1
            arg_pred += len(event.arguments)
            for argument in event.arguments:
                role_pred[argument.role] += 1
                qualifier_pred[argument.qualifier or "<none>"] += 1
                role_qualifier_pred += 1
                arg_type_role_pred[f"{event.event_type}::{argument.role}"] += 1

        # Primary record alignment is type-exact and uses only attached
        # argument spans (or deterministic alignment for triggerless direct
        # records with no source geometry).
        primary_pairs = _assign_primary_records(gold_events_for_message, pred_events_for_message)
        primary_gold = {i for i, _ in primary_pairs}
        primary_pred = {j for _, j in primary_pairs}
        residual_gold_indices = [i for i in range(len(gold_events_for_message)) if i not in primary_gold]
        residual_pred_indices = [j for j in range(len(pred_events_for_message)) if j not in primary_pred]
        residual_gold = [gold_events_for_message[i] for i in residual_gold_indices]
        residual_pred = [pred_events_for_message[j] for j in residual_pred_indices]
        diagnostic_local = _assign_diagnostic_events(residual_gold, residual_pred)
        diagnostic_pairs = [(residual_gold_indices[i], residual_pred_indices[j])
                            for i, j in diagnostic_local]
        classification_pairs = primary_pairs + diagnostic_pairs
        paired_events += len(classification_pairs)
        used_g = {i for i, _ in classification_pairs}
        used_p = {j for _, j in classification_pairs}
        event_errors["missed_event"] += len(gold_events_for_message) - len(used_g)
        event_errors["spurious_event"] += len(pred_events_for_message) - len(used_p)

        # Type identification uses the residual diagnostic alignment to expose
        # wrong-type records without allowing them to displace primary records.
        for gi, pi in classification_pairs:
            gold_event = gold_events_for_message[gi]
            pred_event = pred_events_for_message[pi]
            if gold_event.event_type == pred_event.event_type:
                type_tp[gold_event.event_type] += 1
            else:
                type_confusion[(gold_event.event_type, pred_event.event_type)] += 1
                event_errors["wrong_event_type"] += 1
                if (gi, pi) in diagnostic_pairs:
                    # Error categories can inspect the residual relation
                    # without granting it primary argument-record credit.
                    for ai, bi, _ in _label_aware_span_matches(
                            gold_event.arguments, pred_event.arguments,
                            label="role", threshold=IOU_THRESHOLD):
                        ga, pa = gold_event.arguments[ai], pred_event.arguments[bi]
                        if ga.role != pa.role:
                            arg_errors["wrong_role"] += 1
                    for ai, bi, _ in _label_aware_span_matches(
                            gold_event.arguments, pred_event.arguments,
                            label="qualifier", threshold=IOU_THRESHOLD):
                        ga, pa = gold_event.arguments[ai], pred_event.arguments[bi]
                        if ga.qualifier != pa.qualifier:
                            arg_errors["wrong_qualifier"] += 1

        # Trigger scoring has its own one-to-one assignment. Wrong predicted
        # event types remain detectable when their trigger overlaps a gold one.
        gold_trigger_indices = [i for i, e in enumerate(gold_events_for_message) if e.trigger.segments]
        paired_gold_for_pred = {pi: gi for gi, pi in classification_pairs}
        pred_trigger_indices = []
        for j, pred_event in enumerate(pred_events_for_message):
            if not pred_event.trigger.segments:
                continue
            overlaps_gold_trigger = any(
                span_iou(gold_events_for_message[i].trigger, pred_event.trigger) > 0
                for i in gold_trigger_indices
            )
            matched_gold_index = paired_gold_for_pred.get(j)
            if matched_gold_index is not None:
                trigger_evaluable = bool(gold_events_for_message[matched_gold_index].trigger.segments)
            else:
                trigger_evaluable = pred_event.event_type in trigger_type_enabled or overlaps_gold_trigger
            if trigger_evaluable:
                pred_trigger_indices.append(j)
                trigger_type_pred[pred_event.event_type] += 1
        trigger_pred += len(pred_trigger_indices)
        trigger_weights = []
        trigger_raw_weights = []
        for gi in gold_trigger_indices:
            raw_row = [span_iou(gold_events_for_message[gi].trigger,
                                pred_events_for_message[pj].trigger)
                       for pj in pred_trigger_indices]
            trigger_raw_weights.append(raw_row)
            trigger_weights.append([value if value >= IOU_THRESHOLD else 0.0 for value in raw_row])
        trigger_local_pairs = _hungarian_max(trigger_weights)
        trigger_pairs = []
        for local_g, local_p in trigger_local_pairs:
            iou = trigger_raw_weights[local_g][local_p]
            trigger_pairs.append((gold_trigger_indices[local_g], pred_trigger_indices[local_p], iou))
            trigger_partial_tp += 1
            trigger_iou_credit += iou
            ge = gold_events_for_message[gold_trigger_indices[local_g]]
            pe = pred_events_for_message[pred_trigger_indices[local_p]]
            if _span_exact(ge.trigger, pe.trigger):
                trigger_exact_tp += 1
            if ge.event_type == pe.event_type:
                trigger_type_tp[ge.event_type] += 1
            else:
                trigger_type_confusion[(ge.event_type, pe.event_type)] += 1
        trigger_errors["missed_trigger"] += len(gold_trigger_indices) - len(trigger_pairs)
        trigger_errors["spurious_trigger"] += len(pred_trigger_indices) - len(trigger_pairs)

        # Primary relation and argument metrics are strictly scoped to one
        # same-type event and its own arguments.
        for gi, pi in primary_pairs:
            gold_event = gold_events_for_message[gi]
            pred_event = pred_events_for_message[pi]
            event_exact = _event_exact(gold_event, pred_event)
            if event_exact:
                event_record_exact_tp += 1
            if event_exact and (not gold_event.trigger.segments or _span_exact(gold_event.trigger, pred_event.trigger)):
                event_record_trigger_exact_tp += 1
            p_credit, r_credit = _partial_event_credit(gold_event, pred_event)
            partial_p_credit += p_credit
            partial_r_credit += r_credit
            if gold_event.trigger.segments:
                trigger_iou = span_iou(gold_event.trigger, pred_event.trigger)
                partial_trigger_p_credit += (p_credit + trigger_iou) / 2
                partial_trigger_r_credit += (r_credit + trigger_iou) / 2
            else:
                partial_trigger_p_credit += p_credit
                partial_trigger_r_credit += r_credit

            exact_matches = _exact_argument_matches(gold_event.arguments, pred_event.arguments)
            arg_exact_tp += len(exact_matches)
            role_qualifier_exact_tp += len(exact_matches)
            arg_span_exact_tp += len(_exact_span_matches(gold_event.arguments, pred_event.arguments))
            exact_span_pairs = _label_aware_span_matches(
                gold_event.arguments, pred_event.arguments, label="role", threshold=1.0, exact=True)
            for ai, bi, _ in exact_span_pairs:
                ga, pa = gold_event.arguments[ai], pred_event.arguments[bi]
                if ga.role == pa.role:
                    role_exact_tp[ga.role] += 1
            for ai, bi, _ in _label_aware_span_matches(
                    gold_event.arguments, pred_event.arguments, label="qualifier", threshold=1.0, exact=True):
                ga, pa = gold_event.arguments[ai], pred_event.arguments[bi]
                if ga.qualifier == pa.qualifier:
                    qualifier_exact_tp[ga.qualifier or "<none>"] += 1

            partial_matches = _partial_argument_matches(gold_event.arguments, pred_event.arguments)
            arg_partial_tp += len(partial_matches)
            span_matches = _span_only_matches(gold_event.arguments, pred_event.arguments)
            arg_span_overlap_tp += len(span_matches)
            arg_span_matches += len(span_matches)
            matched_gold_args = {ai for ai, _, _ in span_matches}
            matched_pred_args = {bi for _, bi, _ in span_matches}
            role_span_matches = _label_aware_span_matches(
                gold_event.arguments, pred_event.arguments, label="role", threshold=IOU_THRESHOLD)
            qualifier_span_matches = _label_aware_span_matches(
                gold_event.arguments, pred_event.arguments, label="qualifier", threshold=IOU_THRESHOLD)
            for ai, bi, _ in role_span_matches:
                ga, pa = gold_event.arguments[ai], pred_event.arguments[bi]
                if ga.role == pa.role:
                    role_correct += 1
                    role_partial_tp[ga.role] += 1
                    arg_type_role_tp[f"{gold_event.event_type}::{ga.role}"] += 1
                else:
                    arg_errors["wrong_role"] += 1
            for ai, bi, _ in qualifier_span_matches:
                ga, pa = gold_event.arguments[ai], pred_event.arguments[bi]
                if ga.qualifier == pa.qualifier:
                    qualifier_correct += 1
                    qualifier_tp[ga.qualifier or "<none>"] += 1
                else:
                    arg_errors["wrong_qualifier"] += 1
            arg_errors["unmatched_gold_arguments_in_primary_pairs"] += len(gold_event.arguments) - len(matched_gold_args)
            arg_errors["unmatched_predicted_arguments_in_primary_pairs"] += len(pred_event.arguments) - len(matched_pred_args)

    event_partial = {
        "precision": partial_p_credit / event_record_pred if event_record_pred else None,
        "recall": partial_r_credit / event_record_gold if event_record_gold else None,
        "gold_events": event_record_gold,
        "predicted_events": event_record_pred,
        "threshold": IOU_THRESHOLD,
        "definition": "event type must be exact; attached argument role+qualifier matches use character IoU >= 0.50; trigger is excluded",
    }
    p, r = event_partial["precision"], event_partial["recall"]
    event_partial["f1"] = (2 * p * r / (p + r) if p is not None and r is not None and p + r else
                            0.0 if p == 0 or r == 0 else None)

    event_partial_with_trigger = {
        "precision": partial_trigger_p_credit / event_record_pred if event_record_pred else None,
        "recall": partial_trigger_r_credit / event_record_gold if event_record_gold else None,
        "gold_events": event_record_gold,
        "predicted_events": event_record_pred,
        "threshold": IOU_THRESHOLD,
        "definition": "primary partial event-record score plus trigger IoU averaged for events with an annotated gold trigger; triggerless direct records omit trigger",
    }
    p, r = event_partial_with_trigger["precision"], event_partial_with_trigger["recall"]
    event_partial_with_trigger["f1"] = (2 * p * r / (p + r) if p is not None and r is not None and p + r else
                                         0.0 if p == 0 or r == 0 else None)

    exact_event_metric = _prf(event_record_exact_tp, event_record_pred, event_record_gold)
    exact_event_metric["definition"] = "exact event type and exact multiset of attached (role, qualifier, segment-boundary set) arguments; trigger excluded"
    exact_event_trigger_metric = _prf(event_record_trigger_exact_tp, event_record_pred, event_record_gold)
    exact_event_trigger_metric["definition"] = "primary exact event record and exact trigger when gold has a trigger; triggerless direct records omit trigger"
    exact_arg_metric = _prf(arg_exact_tp, arg_pred, arg_gold)
    exact_arg_metric["definition"] = "exact attached (role, qualifier, segment-boundary set) argument record"
    partial_arg_metric = _prf(arg_partial_tp, arg_pred, arg_gold)
    partial_arg_metric["definition"] = "one-to-one attached argument record match with exact role and qualifier and character IoU >= 0.50; unspanned records match only when both spans are empty"
    span_exact_metric = _prf(arg_span_exact_tp, arg_pred, arg_gold)
    span_exact_metric["definition"] = "one-to-one exact source extent match independent of role and qualifier"
    span_overlap_metric = _prf(arg_span_overlap_tp, arg_pred, arg_gold)
    span_overlap_metric["definition"] = "one-to-one character IoU >= 0.50 match independent of role and qualifier"

    trigger_exact_metric = _prf(trigger_exact_tp, trigger_pred, trigger_gold)
    trigger_partial_metric = _prf(trigger_partial_tp, trigger_pred, trigger_gold)
    if not trigger_gold:
        trigger_exact_metric = {"status": "not_applicable", "reason": "no annotated trigger spans in the selected gold split", "precision": None, "recall": None, "f1": None}
        trigger_partial_metric = dict(trigger_exact_metric)
        trigger_type_metric: dict[str, Any] = {"status": "not_applicable", "reason": "no annotated trigger spans in the selected gold split"}
    else:
        trigger_partial_metric["iou_credit_sum"] = trigger_iou_credit
        trigger_partial_metric["threshold"] = IOU_THRESHOLD
        trigger_type_metric = _per_label_report(trigger_type_gold, trigger_type_pred, trigger_type_tp)
        trigger_type_metric["confusion_pairs"] = [
            {"gold": gold_type, "predicted": pred_type, "count": count}
            for (gold_type, pred_type), count in sorted(trigger_type_confusion.items())
        ]

    event_type_metric = _per_label_report(type_gold, type_pred, type_tp)
    event_type_metric["confusion_pairs"] = [
        {"gold": gold_type, "predicted": pred_type, "count": count}
        for (gold_type, pred_type), count in sorted(type_confusion.items())
    ]
    role_report = _per_label_report(role_gold, role_pred, role_partial_tp)
    role_exact_report = _per_label_report(role_gold, role_pred, role_exact_tp)
    qualifier_report = _per_label_report(qualifier_gold, qualifier_pred, qualifier_tp)
    qualifier_exact_report = _per_label_report(qualifier_gold, qualifier_pred, qualifier_exact_tp)
    type_role_report = _per_label_report(arg_type_role_gold, arg_type_role_pred, arg_type_role_tp)
    messages_with_pred_events = sum(
        bool(pred_by_id.get(message_id) and pred_by_id[message_id].events)
        for message_id in gold_by_id
    )
    messages_without_pred_events = gold_message_count - messages_with_pred_events
    messages_without_gold_events = sum(not message.events for message in gold_by_id.values())
    prediction_only_message_count = len(set(pred_by_id) - set(gold_by_id))
    alignment_rate = paired_events / max(gold_events, pred_events, 1)
    return {
        "schema_version": 1,
        "split": split,
        "matching": {
            "primary_record_assignment": "maximum-weight one-to-one assignment restricted to exact event type and role-agnostic attached argument overlap; when neither side has argument geometry, same-type records are paired in stable order",
            "diagnostic_event_assignment": "after primary pairs are fixed, residual events are aligned by trigger IoU and role-agnostic argument IoU to report type confusion, misses, and spurious events",
            "trigger_assignment": "independent maximum-weight one-to-one trigger-span assignment at character IoU >= 0.50",
            "span_overlap": "character interval IoU after merging overlapping segments within each discontinuous span",
            "partial_threshold": IOU_THRESHOLD,
            "offset_convention": "half-open Python character offsets into message text",
            "text_recovery": "none; supplied text is checked against text[start:end] and never relocated",
        },
        "messages": {
            "gold": gold_message_count,
            "prediction_rows": prediction_message_count,
            "evaluated_union": evaluated_message_count,
            "prediction_only_rows": prediction_only_message_count,
            "with_predictions": messages_with_pred_events,
            "without_predictions": messages_without_pred_events,
            "without_gold_events": messages_without_gold_events,
            "empty_prediction_rate": messages_without_pred_events / evaluated_message_count if evaluated_message_count else None,
        },
        "events": {
            "gold": gold_events,
            "predicted": pred_events,
            "aligned": paired_events,
            "unaligned_gold": event_errors["missed_event"],
            "unaligned_prediction": event_errors["spurious_event"],
            "type_identification": event_type_metric,
            "record_exact": exact_event_metric,
            "record_partial": {**event_partial, "alignment_rate": alignment_rate},
            "record_exact_with_trigger": exact_event_trigger_metric,
            "record_partial_with_trigger": event_partial_with_trigger,
            "error_categories": dict(sorted(event_errors.items())),
        },
        "triggers": {
            "gold_triggered_events": trigger_gold,
            "gold_triggerless_events": gold_events - trigger_gold,
            "predicted_trigger_candidates": trigger_pred,
            "exact": trigger_exact_metric,
            "partial": trigger_partial_metric,
            "event_type_identification": trigger_type_metric,
            "error_categories": dict(sorted(trigger_errors.items())),
            "not_applicable_event_types": sorted({e.event_type for m in gold_by_id.values() for e in m.events
                                                    if not e.trigger.segments and e.event_type not in trigger_type_enabled}),
        },
        "argument_records": {
            "gold": arg_gold,
            "predicted": arg_pred,
            "exact": exact_arg_metric,
            "partial": partial_arg_metric,
            "span_exact": span_exact_metric,
            "span_overlap": span_overlap_metric,
            "span_group_matches_iou_threshold": arg_span_matches,
            "role_accuracy_on_span_matches": role_correct / arg_span_matches if arg_span_matches else None,
            "qualifier_accuracy_on_span_matches": qualifier_correct / arg_span_matches if arg_span_matches else None,
            "role_exact": role_exact_report,
            "role_partial": role_report,
            "role_qualifier_exact": _prf(role_qualifier_exact_tp, role_qualifier_pred, role_qualifier_gold),
            "qualifier": qualifier_exact_report,
            "qualifier_partial": qualifier_report,
            "event_type_and_role_partial": type_role_report,
            "error_categories": dict(sorted(arg_errors.items())),
        },
        "source_validation": {
            **dict(sorted(source_counts.items())),
            "non_source_prediction_segments": source_counts["non_source_segments"] + source_counts["invalid_offset_segments"],
            "gold_policy": "malformed offsets or source-text disagreement raise EvaluationDataError; event/argument flags are counted and retained as diagnostics, never silently repaired or excluded",
            "prediction_policy": "invalid offsets and text/offset disagreement are counted; invalid segments cannot earn span overlap credit",
        },
    }

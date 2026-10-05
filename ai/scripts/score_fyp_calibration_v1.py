"""Score a private FYP V1 three-reviewer blind agreement export.

The input is a ``fyp-calibration-export-v1`` app export with ``annotation_tier``
UNSET and ``gold_count`` zero. ``sources`` rows contain ``source_id``,
``allocation`` and direct V1 source fields. ``reviewers`` may be user IDs or
objects with ``user_id`` and display metadata. ``reviews`` are revision
snapshots with ``source_id``, ``user_id``, ``revision``, ``status`` and an
``annotation_json`` string for submitted rows; the highest revision is active.
Site provenance aliases (``source_ref``, ``timestamp`` and ``ai_assist``) are
normalized only for V1 validation. Source rows may also include
``context_annotations``; review rows may carry reviewer-specific context
annotations as well.

Only the common ``blind_agreement`` allocation is scored. Metrics are withheld
until every common source has a submitted annotation from all three reviewers.
Submitted annotations must be valid, source-grounded, BLIND_HUMAN and UNSET.
This command emits aggregate counts only; it never writes source text, answers,
source IDs or reviewer IDs. Scope uses Fleiss' kappa and unanimity. Multi-label
agreement reports pairwise exact label-set agreement, binary micro agreement/F1,
and per-label positive/negative agreement with support. Span and event metrics
use pairwise exact-set precision, recall and F1. Event-role tuples include event
kind/state and anchor coordinates, then role, span type/field/bounds and certainty;
local event/span IDs are omitted. Decision Gate A is provisional and does not
promote annotations to GOLD automatically.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai"))

from src.fyp_structured_v1 import LABELS, derive_labels, validate_annotation  # noqa: E402

REVIEW_STATUSES = {"submitted", "draft", "in_progress", "waiting", "withdrawn"}
ALLOCATIONS = {"blind_agreement", "calibration_training", "labeler_human_holdout"}


class ExportError(ValueError):
    """Safe-to-display export error; messages must not contain private values."""


@dataclass(frozen=True)
class Review:
    source_id: str
    user_id: str
    status: str
    annotation: Mapping[str, Any] | None
    active_ms: int | None
    context_annotations: Any = None


def _fail(message: str) -> None:
    raise ExportError(message)


def _parse_annotation(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            _fail("a submitted annotation is not valid JSON")
    if not isinstance(value, Mapping):
        _fail("a submitted annotation must be a JSON object")
    return value


def _reviewer_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail("export reviewers must be a list of three authenticated users")
    ids: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            user_id = entry
        elif isinstance(entry, Mapping):
            user_id = entry.get("user_id")
            # Site exports contain the authenticated user ID plus display-only
            # slot metadata; authentication is established by the export source.
            # Preserve compatibility with explicit auth flags when supplied.
            if "authenticated" in entry and entry.get("authenticated") is not True:
                _fail("all exported reviewers must be authenticated")
        else:
            _fail("export reviewers must contain user IDs")
        if not isinstance(user_id, str) or not user_id.strip():
            _fail("export reviewers must contain non-empty user IDs")
        ids.append(user_id)
    if len(ids) != 3 or len(set(ids)) != 3:
        _fail("agreement scoring requires exactly three distinct authenticated reviewers")
    return tuple(ids)


def _source_record(row: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = row.get("source")
    source = nested if isinstance(nested, Mapping) else row
    subject = source.get("subject")
    body = source.get("current_message")
    ranges = source.get("authored_ranges")
    if not isinstance(subject, str) or not isinstance(body, str) or not isinstance(ranges, list):
        _fail("each source requires subject, current_message and authored_ranges")
    result = {"subject": subject, "current_message": body, "authored_ranges": ranges}
    context = row.get("context_annotations", source.get("context_annotations"))
    if context is not None:
        result["_context_annotations"] = context
    return result


def _safe_status(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("every review requires a status")
    normalized = value.strip().lower()
    return normalized if normalized in REVIEW_STATUSES else "other"


def _parse_export(payload: Any) -> tuple[tuple[str, ...], dict[str, Mapping[str, Any]], dict[str, str], list[Review]]:
    if not isinstance(payload, Mapping):
        _fail("export must be a JSON object")
    if payload.get("schema_version") != "fyp-calibration-export-v1":
        _fail("export schema_version must be fyp-calibration-export-v1")
    gold_count = payload.get("gold_count")
    if (payload.get("annotation_tier") != "UNSET" or not isinstance(gold_count, int)
            or isinstance(gold_count, bool) or gold_count != 0):
        _fail("calibration export must remain UNSET with zero GOLD annotations")
    reviewers = _reviewer_ids(payload.get("reviewers"))
    source_rows = payload.get("sources")
    review_rows = payload.get("reviews")
    if not isinstance(source_rows, list) or not source_rows:
        _fail("export must contain source allocation rows")
    if not isinstance(review_rows, list):
        _fail("export must contain a reviews list")

    source_map: dict[str, Mapping[str, Any]] = {}
    allocation_by_source: dict[str, str] = {}
    for row in source_rows:
        if not isinstance(row, Mapping):
            _fail("source allocation rows must be objects")
        source_id = row.get("source_id")
        allocation = row.get("allocation")
        if not isinstance(source_id, str) or not source_id.strip():
            _fail("every source allocation requires a source ID")
        if source_id in source_map:
            _fail("source allocation IDs must be unique")
        if allocation not in ALLOCATIONS:
            _fail("source allocation must be blind_agreement, calibration_training or labeler_human_holdout")
        source_map[source_id] = _source_record(row)
        allocation_by_source[source_id] = str(allocation)
    if not any(allocation == "blind_agreement" for allocation in allocation_by_source.values()):
        _fail("export has no common blind agreement sources")

    review_rows_by_slot: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in review_rows:
        if not isinstance(row, Mapping):
            _fail("review rows must be objects")
        source_id = row.get("source_id")
        user_id = row.get("user_id")
        if not isinstance(source_id, str) or source_id not in source_map:
            _fail("review source is absent from the source allocation")
        if not isinstance(user_id, str) or user_id not in reviewers:
            _fail("reviewer identity is absent from the authenticated reviewer set")
        slot = (source_id, user_id)
        revision = row.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            _fail("each review requires a positive integer revision")
        review_rows_by_slot.setdefault(slot, []).append(row)

    parsed_reviews: list[Review] = []
    for slot, candidates in review_rows_by_slot.items():
        revisions = [row["revision"] for row in candidates]
        if len(revisions) != len(set(revisions)):
            _fail("export contains duplicate reviewer/source revisions")
        # Review rows are revision snapshots. Only the newest snapshot is the
        # active submission; stale submitted snapshots must never fill a newer
        # draft or pending slot.
        row = max(candidates, key=lambda candidate: candidate["revision"])
        source_id, user_id = slot
        status = _safe_status(row.get("status"))
        annotation: Mapping[str, Any] | None = None
        if status == "submitted":
            if "annotation_json" not in row:
                _fail("submitted reviews require annotation_json")
            annotation = _parse_annotation(row["annotation_json"])
        active_ms = row.get("active_ms")
        if active_ms is not None and (
            not isinstance(active_ms, int) or isinstance(active_ms, bool) or active_ms < 0
        ):
            _fail("active_ms must be a non-negative integer or null")
        parsed_reviews.append(Review(
            source_id=source_id,
            user_id=user_id,
            status=status,
            annotation=annotation,
            active_ms=active_ms,
            context_annotations=row.get("context_annotations"),
        ))
    return reviewers, source_map, allocation_by_source, parsed_reviews


def _require_blind_unset(review: Review) -> None:
    annotation = review.annotation
    assert annotation is not None
    provenance = annotation.get("provenance")
    if not isinstance(provenance, Mapping):
        _fail("submitted annotation provenance is missing")
    if provenance.get("annotation_tier") != "UNSET":
        _fail("submitted common annotations must remain UNSET; SILVER, SYNTHETIC and GOLD are excluded")
    if provenance.get("annotation_mode") != "BLIND_HUMAN":
        _fail("submitted common annotations must use BLIND_HUMAN provenance")
    if provenance.get("annotator_id") != review.user_id:
        _fail("submitted annotation identity does not match its authenticated reviewer")
    if provenance.get("blind_prelabels_shown") is not False:
        _fail("submitted blind annotations must record blind_prelabels_shown=false")
    source_reference = _provenance_value(provenance, "source_reference", "source_ref")
    ai_assistance = _provenance_value(provenance, "ai_assistance", "ai_assist")
    timestamp = _provenance_value(provenance, "annotated_at", "timestamp")
    if ai_assistance is not None or provenance.get("human_review") is not None:
        _fail("blind submissions cannot contain AI assistance or adjudication provenance")
    if provenance.get("data_origin") not in {"REAL_EMAIL", "PUBLIC_CORPUS"}:
        _fail("synthetic and unknown-origin sources cannot enter blind agreement scoring")
    if (review.source_id != annotation.get("current_source_id")
            or source_reference != review.source_id):
        _fail("submitted annotation source does not match its assigned source")
    if not isinstance(timestamp, str) or not timestamp.strip():
        _fail("submitted blind annotations require an ISO timestamp")


def _provenance_value(provenance: Mapping[str, Any], canonical: str, alias: str) -> Any:
    """Read a canonical V1 field, allowing a Site alias only if unambiguous."""
    if canonical in provenance and alias in provenance and provenance[canonical] != provenance[alias]:
        _fail("submitted annotation provenance fields conflict")
    return provenance[canonical] if canonical in provenance else provenance.get(alias)


def _v1_validation_annotation(annotation: Mapping[str, Any]) -> Mapping[str, Any]:
    """Translate the Site provenance names to the canonical V1 validator shape."""
    normalized = dict(annotation)
    raw_provenance = annotation.get("provenance")
    if not isinstance(raw_provenance, Mapping):
        return annotation
    provenance = dict(raw_provenance)
    aliases = (
        ("source_ref", "source_reference"),
        ("timestamp", "annotated_at"),
        ("ai_assist", "ai_assistance"),
    )
    for site_name, schema_name in aliases:
        if site_name in provenance:
            site_value = provenance.pop(site_name)
            if schema_name in provenance and provenance[schema_name] != site_value:
                _fail("submitted annotation provenance fields conflict")
            provenance[schema_name] = site_value
    # Site records represent ordinary sources, so the V1 schema's explicit
    # synthetic marker is null when it is absent from the export shape.
    provenance.setdefault("synthetic_case_id", None)
    normalized["provenance"] = provenance
    return normalized


def _context_for(
    review: Review,
    reviews_by_user: Mapping[str, Sequence[Review]],
    source_map: Mapping[str, Mapping[str, Any]],
) -> Any:
    contexts: list[Any] = []
    current_source = source_map.get(review.source_id, {})
    for value in (review.context_annotations, current_source.get("_context_annotations")):
        if isinstance(value, Mapping):
            if isinstance(value.get("current_source_id"), str) and isinstance(value.get("events"), list):
                contexts.append(value)
            else:
                contexts.extend(value.values())
        elif isinstance(value, (list, tuple)):
            contexts.extend(value)
    for other in reviews_by_user.get(review.user_id, ()):
        if other.source_id != review.source_id and other.annotation is not None:
            contexts.append(other.annotation)
    return contexts


def _validate_common_submissions(
    common_reviews: Sequence[Review],
    reviewers: Sequence[str],
    source_map: Mapping[str, Mapping[str, Any]],
) -> None:
    submitted = [review for review in common_reviews if review.status == "submitted"]
    by_user: dict[str, list[Review]] = {user: [] for user in reviewers}
    for review in submitted:
        by_user[review.user_id].append(review)
        _require_blind_unset(review)
    for review in submitted:
        result = validate_annotation(
            _v1_validation_annotation(review.annotation),
            source_map,
            _context_for(review, by_user, source_map),
            evaluation=False,
        )
        if not result.valid:
            # V1 validator messages can contain private source IDs and span data.
            _fail("a submitted annotation failed V1 structural or exact-source validation")


def _f1(tp: int, fp: int, fn: int) -> float | None:
    denominator = 2 * tp + fp + fn
    return None if denominator == 0 else _rounded(2 * tp / denominator)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _pairwise_set_counts(items: Mapping[str, Sequence[set[Any]]]) -> tuple[int, int, int, int]:
    tp = fp = fn = exact = 0
    for annotations in items.values():
        if len(annotations) != 3:
            raise ValueError("internal metric input requires three annotations per source")
        for left, right in combinations(annotations, 2):
            tp += len(left & right)
            fp += len(right - left)
            fn += len(left - right)
            exact += left == right
    return tp, fp, fn, exact


def _fleiss_scope(annotations_by_source: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    categories = ("PROJECT", "NON_PROJECT", "UNCERTAIN")
    item_agreement: list[float] = []
    total = Counter()
    for annotations in annotations_by_source.values():
        if len(annotations) != 3:
            raise ValueError("internal metric input requires three annotations per source")
        ratings = [annotation["scope"]["value"] for annotation in annotations]
        counts = Counter(ratings)
        total.update(counts)
        item_agreement.append(sum(counts[label] * (counts[label] - 1) for label in categories) / 6)
    item_count = len(item_agreement)
    if not item_count:
        return {
            "items": 0, "reviewers_per_item": 3, "unanimous_items": 0,
            "unanimity_rate": None, "observed_agreement": None,
            "expected_agreement": None, "fleiss_kappa": None,
        }
    observed = sum(item_agreement) / item_count
    ratings_total = item_count * 3
    proportions = [total[label] / ratings_total for label in categories]
    expected = sum(probability * probability for probability in proportions)
    kappa = None if math.isclose(expected, 1.0) else (observed - expected) / (1 - expected)
    unanimous = sum(score == 1.0 for score in item_agreement)
    return {
        "items": item_count,
        "reviewers_per_item": 3,
        "unanimous_items": unanimous,
        "unanimity_rate": _rounded(unanimous / item_count),
        "observed_agreement": _rounded(observed),
        "expected_agreement": _rounded(expected),
        "fleiss_kappa": _rounded(kappa),
    }


def _multi_label_agreement(
    labels_by_source: Mapping[str, Sequence[set[str]]],
) -> dict[str, Any]:
    tp = fp = fn = tn = exact = pair_count = 0
    per_label: dict[str, dict[str, int]] = {
        label: {"both_positive": 0, "left_only": 0, "right_only": 0, "both_negative": 0}
        for label in LABELS
    }
    for label_sets in labels_by_source.values():
        if len(label_sets) != 3:
            raise ValueError("internal metric input requires three annotations per source")
        for left, right in combinations(label_sets, 2):
            pair_count += 1
            exact += left == right
            for label in LABELS:
                lvalue, rvalue = label in left, label in right
                cell = per_label[label]
                if lvalue and rvalue:
                    cell["both_positive"] += 1
                    tp += 1
                elif lvalue:
                    cell["left_only"] += 1
                    fn += 1
                elif rvalue:
                    cell["right_only"] += 1
                    fp += 1
                else:
                    cell["both_negative"] += 1
                    tn += 1
    label_metrics: dict[str, Any] = {}
    for label, counts in per_label.items():
        disagreements = counts["left_only"] + counts["right_only"]
        positive_denominator = 2 * counts["both_positive"] + disagreements
        negative_denominator = 2 * counts["both_negative"] + disagreements
        label_metrics[label] = {
            **counts,
            "positive_union_support": counts["both_positive"] + disagreements,
            "positive_ratings": 2 * counts["both_positive"] + counts["left_only"] + counts["right_only"],
            "pairwise_positive_agreement": _rounded(
                2 * counts["both_positive"] / positive_denominator if positive_denominator else None
            ),
            "pairwise_negative_agreement": _rounded(
                2 * counts["both_negative"] / negative_denominator if negative_denominator else None
            ),
        }
    return {
        "source_reviewer_pairs": pair_count,
        "exact_label_set_agreements": exact,
        "exact_label_set_agreement_rate": _rounded(exact / pair_count if pair_count else None),
        "micro_binary_label_agreement": _rounded((tp + tn) / (pair_count * len(LABELS)) if pair_count else None),
        "micro_binary_label_f1": _f1(tp, fp, fn),
        "per_label": label_metrics,
    }


def _span_key(span: Mapping[str, Any]) -> tuple[Any, ...]:
    return (span["field"], span["type"], span["start"], span["end"])


def _event_role_tuples(annotation: Mapping[str, Any]) -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    spans = {span["id"]: span for span in annotation["spans"]}
    events = {event["id"]: event for event in annotation["events"]}
    anchors: dict[str, list[tuple[Any, ...]]] = {event_id: [] for event_id in events}
    links_by_event: dict[str, list[Mapping[str, Any]]] = {event_id: [] for event_id in events}
    for link in annotation["event_span_links"]:
        event_id = link["event_id"]
        span = spans[link["span_id"]]
        if link["role"] == "EVENT_ANCHOR":
            anchors[event_id].append(_span_key(span))
        links_by_event[event_id].append(link)
    event_keys: set[tuple[Any, ...]] = set()
    role_tuples: set[tuple[Any, ...]] = set()
    for event_id, event in events.items():
        # Event IDs are deliberately omitted; source coordinates disambiguate
        # repeated events without relying on local annotator-generated IDs.
        anchor_key = tuple(sorted(anchors[event_id]))
        event_key = (event["kind"], event["state"], event["certainty"], anchor_key)
        event_keys.add(event_key)
        for link in links_by_event[event_id]:
            span = spans[link["span_id"]]
            role_tuples.add((
                event_key,
                link["role"],
                span["type"],
                span["field"],
                span["start"],
                span["end"],
                span.get("actor_kind"),
                link["certainty"],
            ))
    return event_keys, role_tuples


def _set_metric_bundle(sets_by_source: Mapping[str, Sequence[set[Any]]]) -> dict[str, Any]:
    tp, fp, fn, exact = _pairwise_set_counts(sets_by_source)
    pair_count = sum(3 for _ in sets_by_source)
    return {
        "source_reviewer_pairs": pair_count,
        "matched_items": tp,
        "left_only_items": fn,
        "right_only_items": fp,
        "item_instances_left": tp + fn,
        "item_instances_right": tp + fp,
        "pairwise_exact_set_agreements": exact,
        "pairwise_exact_set_agreement_rate": _rounded(exact / pair_count if pair_count else None),
        "precision": _rounded(tp / (tp + fp) if tp + fp else None),
        "recall": _rounded(tp / (tp + fn) if tp + fn else None),
        "f1": _f1(tp, fp, fn),
    }


def compute_agreement_metrics(
    annotations_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    active_ms: Sequence[int | None] = (),
) -> dict[str, Any]:
    """Compute metrics from complete three-annotation-per-source groups.

    This pure scorer is used after source/provenance validation by the CLI. Its
    inputs may also be synthetic in unit tests; it does not certify provenance.
    """
    if not annotations_by_source:
        raise ValueError("at least one complete source group is required")
    if any(len(items) != 3 for items in annotations_by_source.values()):
        raise ValueError("agreement metrics require exactly three annotations per source")
    labels_by_source: dict[str, list[set[str]]] = {}
    spans_by_source: dict[str, list[set[Any]]] = {}
    events_by_source: dict[str, list[set[Any]]] = {}
    role_tuples_by_source: dict[str, list[set[Any]]] = {}
    all_annotations: list[Mapping[str, Any]] = []
    for source_id, annotations in annotations_by_source.items():
        labels_by_source[source_id] = [set(derive_labels(annotation)) for annotation in annotations]
        spans_by_source[source_id] = [
            {_span_key(span) for span in annotation["spans"]}
            for annotation in annotations
        ]
        canonical = [_event_role_tuples(annotation) for annotation in annotations]
        events_by_source[source_id] = [entry[0] for entry in canonical]
        role_tuples_by_source[source_id] = [entry[1] for entry in canonical]
        all_annotations.extend(annotations)
    elapsed = [value for value in active_ms if isinstance(value, int) and not isinstance(value, bool) and value >= 0]
    review_count = sum(annotation.get("needs_review") is True for annotation in all_annotations)
    empty_label_count = sum(not labels for values in labels_by_source.values() for labels in values)
    annotation_count = len(all_annotations)
    return {
        "scope": _fleiss_scope(annotations_by_source),
        "derived_multi_label": _multi_label_agreement(labels_by_source),
        "span_type_and_exact_boundary_pairwise": _set_metric_bundle(spans_by_source),
        "event_instances_pairwise": _set_metric_bundle(events_by_source),
        "event_role_linked_tuples_pairwise": _set_metric_bundle(role_tuples_by_source),
        "review_and_abstention": {
            "annotation_count": annotation_count,
            "needs_review_count": review_count,
            "needs_review_rate": _rounded(review_count / annotation_count),
            "mapper_abstention_count": review_count,
            "mapper_abstention_rate": _rounded(review_count / annotation_count),
            "empty_derived_label_count": empty_label_count,
            "empty_derived_label_rate": _rounded(empty_label_count / annotation_count),
        },
        "active_time": {
            "timed_reviews": len(elapsed),
            "median_active_minutes": _rounded(statistics.median(elapsed) / 60_000) if elapsed else None,
        },
    }


def _incomplete_report(
    allocation_by_source: Mapping[str, str],
    reviewers: Sequence[str],
    common_reviews: Sequence[Review],
) -> dict[str, Any]:
    status_by_slot = {(review.source_id, review.user_id): review.status for review in common_reviews}
    pending: Counter[str] = Counter()
    for source_id, allocation in allocation_by_source.items():
        if allocation != "blind_agreement":
            continue
        for user_id in reviewers:
            pending[status_by_slot.get((source_id, user_id), "missing")] += 1
    statuses = Counter(pending)
    submitted = statuses.get("submitted", 0)
    return {
        "status": "waiting",
        "decision_gate": "A_PROVISIONAL",
        "metrics_scope": "blind_agreement_only",
        "reviewers_required": 3,
        "gold_annotations_scored": 0,
        "source_counts": {
            "blind_agreement": sum(value == "blind_agreement" for value in allocation_by_source.values()),
            "calibration_training_excluded": sum(value == "calibration_training" for value in allocation_by_source.values()),
            "labeler_human_holdout_sealed_excluded": sum(value == "labeler_human_holdout" for value in allocation_by_source.values()),
        },
        "common_blind_progress": {
            "expected_reviewer_source_reviews": sum(value == "blind_agreement" for value in allocation_by_source.values()) * 3,
            "submitted_reviews": submitted,
            "status_counts": dict(sorted(statuses.items(), key=lambda item: item[0])),
        },
        "metrics": None,
        "gold_promotion": "not_automatic",
    }


def score_export(payload: Any) -> dict[str, Any]:
    reviewers, source_map, allocation_by_source, reviews = _parse_export(payload)
    common_ids = {source_id for source_id, allocation in allocation_by_source.items() if allocation == "blind_agreement"}
    common_reviews = [review for review in reviews if review.source_id in common_ids]
    _validate_common_submissions(common_reviews, reviewers, source_map)

    status_by_slot = {(review.source_id, review.user_id): review.status for review in common_reviews}
    complete = all(status_by_slot.get((source_id, user_id)) == "submitted"
                   for source_id in common_ids for user_id in reviewers)
    if not complete:
        return _incomplete_report(allocation_by_source, reviewers, common_reviews)

    review_by_slot = {(review.source_id, review.user_id): review for review in common_reviews}
    annotations_by_source = {
        source_id: [review_by_slot[(source_id, user_id)].annotation for user_id in reviewers]
        for source_id in sorted(common_ids)
    }
    # All annotation values are present because the common allocation is complete.
    complete_annotations = {
        source_id: [annotation for annotation in annotations if annotation is not None]
        for source_id, annotations in annotations_by_source.items()
    }
    if any(len(annotations) != 3 for annotations in complete_annotations.values()):
        _fail("common blind allocation is incomplete")
    elapsed = [review_by_slot[(source_id, user_id)].active_ms
               for source_id in common_ids for user_id in reviewers]
    return {
        "status": "complete_provisional",
        "decision_gate": "A_PROVISIONAL",
        "metrics_scope": "blind_agreement_only",
        "reviewers_required": 3,
        "gold_annotations_scored": 0,
        "source_counts": {
            "blind_agreement_scored": len(common_ids),
            "calibration_training_excluded": sum(value == "calibration_training" for value in allocation_by_source.values()),
            "labeler_human_holdout_sealed_excluded": sum(value == "labeler_human_holdout" for value in allocation_by_source.values()),
        },
        "common_blind_progress": {
            "expected_reviewer_source_reviews": len(common_ids) * 3,
            "submitted_reviews": len(common_ids) * 3,
            "status_counts": {"submitted": len(common_ids) * 3},
        },
        "metrics": compute_agreement_metrics(complete_annotations, elapsed),
        "gold_promotion": "not_automatic",
        "decision_note": "Gate A is provisional; review and adjudication are required before any GOLD decision.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="private app export JSON")
    parser.add_argument("--output", type=Path, help="aggregate-only JSON report; defaults to stdout")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        report = score_export(payload)
    except (OSError, json.JSONDecodeError):
        print("Could not read or parse the private calibration export.", file=sys.stderr)
        return 2
    except ExportError as error:
        print(str(error), file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

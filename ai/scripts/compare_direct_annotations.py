"""Compare two fyp-direct-label-v1 annotations without treating either as gold.

Accepts one JSONL or JSON/app-export file for each annotator. App exports are
read in memory and filtered to the requested reviewer before annotation JSON is
decoded. Holdout assignments are always excluded. The report contains aggregate
metrics only; no source text, annotator identity, or per-email answers are saved.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "fyp-direct-label-v1"
REPORT_VERSION = "fyp-direct-agreement-report-v1"
PROJECT_LABELS = (
    "MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT",
    "ACTION_REQUEST", "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE",
)
LABELS = (*PROJECT_LABELS, "NON_PROJECT")
SCOPES = ("PROJECT", "NON_PROJECT", "UNCERTAIN")
HOLDOUT_ALLOCATIONS = {"labeler_human_holdout", "holdout", "test"}


@dataclass
class LoadedAnnotations:
    records: list[dict[str, Any]]
    reviewer_ids: set[str]
    heldout_rows_excluded: int = 0


def _fail(message: str) -> ValueError:
    return ValueError(message)


def _as_json_value(value: Any, description: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise _fail(f"{description} contains invalid JSON: {exc.msg}") from exc
    return value


def _as_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{description} must be a JSON object")
    return value


def _source_id(record: dict[str, Any], fallback: dict[str, Any] | None = None) -> str | None:
    source = record.get("source")
    if isinstance(source, dict):
        for key in ("current_source_id", "source_id", "email_id", "id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("current_source_id", "source_id", "email_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    if fallback:
        for key in ("current_source_id", "source_id", "email_id", "id"):
            value = fallback.get(key)
            if isinstance(value, str) and value:
                return value
    value = record.get("record_id")
    if isinstance(value, str) and value:
        return value
    return None


def _source_hash(record: dict[str, Any], fallback: dict[str, Any] | None = None) -> str | None:
    source = record.get("source")
    candidates: list[Any] = []
    if isinstance(source, dict):
        candidates.extend(source.get(key) for key in ("source_sha256", "sha256", "source_hash"))
    candidates.extend(record.get(key) for key in ("source_sha256", "source_hash"))
    if fallback:
        candidates.extend(fallback.get(key) for key in ("source_sha256", "sha256", "source_hash"))
    hashes = {str(value).lower() for value in candidates if isinstance(value, str) and value}
    if len(hashes) > 1:
        raise _fail("annotation and immutable source manifest contain different source hashes")
    return next(iter(hashes), None)


def _source_texts(record: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    source = record.get("source")
    if isinstance(source, dict):
        for key in ("subject", "current_message", "body", "thread_context"):
            if isinstance(source.get(key), str):
                values[key] = source[key]
    for key in ("subject", "current_message", "body", "thread_context"):
        if isinstance(record.get(key), str):
            values.setdefault(key, record[key])
    if fallback:
        for key in ("subject", "current_message", "body", "thread_context"):
            if isinstance(fallback.get(key), str):
                values.setdefault(key, fallback[key])
    return values


def _reviewer_from_provenance(record: dict[str, Any]) -> str | None:
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return None
    for key in ("annotator_id", "annotator", "reviewer_id", "user_id"):
        value = provenance.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalise_direct_record(
    raw: Any,
    *,
    source_manifest: dict[str, Any] | None = None,
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    outer = _as_mapping(raw, "annotation record")
    if "scope" not in outer and "labels" not in outer and "annotation" in outer:
        annotation = _as_json_value(outer["annotation"], "annotation")
        record = dict(_as_mapping(annotation, "annotation"))
    else:
        record = dict(outer)

    if record.get("schema_version") != SCHEMA_VERSION:
        raise _fail(
            f"record schema_version must be {SCHEMA_VERSION!r}; got {record.get('schema_version')!r}"
        )

    embedded_source = record.get("source")
    if embedded_source is not None and not isinstance(embedded_source, dict):
        raise _fail("source must be an object when present")
    source = dict(embedded_source or {})
    fallback = source_manifest or {}
    record_source_id = _source_id(record, fallback)
    manifest_source_id = _source_id({}, fallback)
    current_source_id = record.get("current_source_id")
    record_id = record.get("record_id")
    if not isinstance(current_source_id, str) or not current_source_id:
        raise _fail("every direct annotation must identify current_source_id")
    if not isinstance(record_id, str) or not record_id:
        raise _fail("every direct annotation must identify record_id")
    if record_id != current_source_id:
        raise _fail("record_id and current_source_id must identify the same source")
    record_source_id = current_source_id
    if manifest_source_id is not None and record_source_id != manifest_source_id:
        raise _fail("annotation current_source_id/record_id does not match its app-export source row")
    for identity in (record.get("source_id"), record.get("email_id"),
                     source.get("source_id"), source.get("email_id")):
        if isinstance(identity, str) and identity and identity != record_source_id:
            raise _fail("annotation source identity fields do not agree")
    source["source_id"] = record_source_id

    record_hash = _source_hash(record)
    manifest_hash = _source_hash({}, fallback)
    if record_hash and manifest_hash and record_hash != manifest_hash:
        raise _fail(f"annotation source hash differs from immutable source row for {record_source_id}")
    resolved_hash = record_hash or manifest_hash
    if resolved_hash:
        source["source_sha256"] = resolved_hash
    for key, value in _source_texts(record, fallback).items():
        if key not in source:
            source[key] = value
        elif source[key] != value:
            raise _fail(f"annotation source text differs from app export for {record_source_id} ({key})")
    record["source"] = source

    scope = record.get("scope")
    if not isinstance(scope, dict) or scope.get("value") not in SCOPES:
        raise _fail(f"scope.value must be one of {', '.join(SCOPES)} for {record_source_id}")
    labels = record.get("labels")
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise _fail(f"labels must be an array of label strings for {record_source_id}")
    if len(labels) != len(set(labels)):
        raise _fail(f"duplicate labels in annotation for {record_source_id}")
    invalid_labels = sorted(set(labels) - set(LABELS))
    if invalid_labels:
        raise _fail(f"unknown FYP labels for {record_source_id}: {', '.join(invalid_labels)}")
    if scope["value"] == "NON_PROJECT" and set(labels) != {"NON_PROJECT"}:
        raise _fail(f"NON_PROJECT scope must have only the NON_PROJECT label for {record_source_id}")
    if scope["value"] == "PROJECT" and "NON_PROJECT" in labels:
        raise _fail(f"PROJECT scope cannot include NON_PROJECT for {record_source_id}")
    if scope["value"] == "UNCERTAIN" and labels:
        raise _fail(f"UNCERTAIN scope cannot produce selected labels for {record_source_id}")

    if not isinstance(record.get("needs_review"), bool):
        raise _fail(f"needs_review must be a boolean for {record_source_id}")
    review_reasons = record.get("review_reasons")
    if (not isinstance(review_reasons, list)
            or any(not isinstance(reason, str) or not reason.strip() for reason in review_reasons)):
        raise _fail(f"review_reasons must be an array of nonempty strings for {record_source_id}")
    if scope["value"] == "UNCERTAIN" and not record["needs_review"]:
        raise _fail(f"UNCERTAIN scope must be marked needs_review for {record_source_id}")

    spans = record.get("spans")
    if not isinstance(spans, list):
        raise _fail(f"spans must be an array for {record_source_id}")
    span_ids: set[str] = set()
    exact_span_signatures: set[tuple[Any, ...]] = set()
    span_coordinates: set[tuple[Any, ...]] = set()
    source_texts = _source_texts(record)
    for span in spans:
        if not isinstance(span, dict):
            raise _fail(f"each span must be an object for {record_source_id}")
        required = ("id", "field", "start", "end", "text", "type")
        if any(key not in span for key in required):
            raise _fail(f"span is missing one of {', '.join(required)} for {record_source_id}")
        if not isinstance(span["id"], str) or not span["id"] or span["id"] in span_ids:
            raise _fail(f"span IDs must be unique nonempty strings for {record_source_id}")
        if span["field"] not in {"subject", "current_message"}:
            raise _fail(f"span field must be subject or current_message for {record_source_id}")
        if span["type"] not in {
            "EVIDENCE", "MEETING_DATE", "MEETING_TIME", "DEADLINE_DATE", "DEADLINE_TIME",
            "ACTION_ITEM", "RESPONSIBLE_PARTY", "DEPARTMENT", "REQUESTED_DOCUMENT",
            "PARTICIPANT", "AGENDA", "PROJECT", "INPUT", "APPROVAL_TARGET",
        }:
            raise _fail(f"unknown span type for {record_source_id}: {span['type']!r}")
        if (not isinstance(span["start"], int) or isinstance(span["start"], bool)
                or not isinstance(span["end"], int) or isinstance(span["end"], bool)
                or span["start"] < 0 or span["end"] <= span["start"]):
            raise _fail(f"span offsets must be a nonempty half-open range for {record_source_id}")
        if not isinstance(span["text"], str) or not span["text"]:
            raise _fail(f"span text must be a nonempty string for {record_source_id}")
        signature = (span["field"], span["type"], span["start"], span["end"], span["text"])
        if signature in exact_span_signatures:
            raise _fail(f"duplicate identical span in annotation for {record_source_id}")
        coordinate = (span["field"], span["type"], span["start"], span["end"])
        if coordinate in span_coordinates:
            raise _fail(f"duplicate span coordinates in annotation for {record_source_id}")
        if span["field"] in source_texts:
            actual = source_texts[span["field"]][span["start"]:span["end"]]
            if actual != span["text"]:
                raise _fail(f"span text/offset does not match source field for {record_source_id}")
        authored_ranges = fallback.get("authored_ranges", source.get("authored_ranges"))
        if span["field"] == "current_message" and authored_ranges is not None:
            body = source_texts.get("current_message")
            if body is None or not isinstance(authored_ranges, list):
                raise _fail(f"authored_ranges are invalid or current message is missing for {record_source_id}")
            covered = False
            for bounds in authored_ranges:
                if not isinstance(bounds, dict) or set(bounds) != {"start", "end"}:
                    raise _fail(f"authored_ranges contain an invalid range for {record_source_id}")
                left, right = bounds["start"], bounds["end"]
                if (not isinstance(left, int) or isinstance(left, bool)
                        or not isinstance(right, int) or isinstance(right, bool)
                        or left < 0 or right < left or right > len(body)):
                    raise _fail(f"authored_ranges contain invalid offsets for {record_source_id}")
                covered = covered or left <= span["start"] and span["end"] <= right
            if not covered:
                raise _fail(f"span is outside the authored current-message ranges for {record_source_id}")
        span_ids.add(span["id"])
        exact_span_signatures.add(signature)
        span_coordinates.add(coordinate)

    scope_evidence_ids = scope.get("evidence_span_ids")
    if (not isinstance(scope_evidence_ids, list) or not scope_evidence_ids
            or any(not isinstance(value, str) or value not in span_ids for value in scope_evidence_ids)
            or len(scope_evidence_ids) != len(set(scope_evidence_ids))):
        raise _fail(f"scope.evidence_span_ids must reference one or more unique spans for {record_source_id}")

    supports = record.get("label_support")
    if not isinstance(supports, list):
        raise _fail(f"label_support must be an array for {record_source_id}")
    support_labels = []
    for support in supports:
        if not isinstance(support, dict) or support.get("label") not in PROJECT_LABELS:
            raise _fail(f"each label_support entry needs a known label for {record_source_id}")
        if support["label"] not in labels:
            raise _fail(f"label_support references an unselected label for {record_source_id}")
        support_labels.append(support["label"])
        for field in ("evidence_span_ids", "field_span_ids"):
            ids = support.get(field)
            if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
                raise _fail(f"label_support.{field} must be an array of span IDs for {record_source_id}")
            if len(ids) != len(set(ids)) or any(value not in span_ids for value in ids):
                raise _fail(f"label_support.{field} has duplicate or unknown span IDs for {record_source_id}")
            if field == "evidence_span_ids" and not ids:
                raise _fail(f"label_support needs evidence spans for {record_source_id}")
        if not isinstance(support.get("applies_to"), str):
            raise _fail(f"label_support.applies_to must be a string for {record_source_id}")
        if support.get("follow_up_target") not in {
            None, "TASK", "DOCUMENT_REQUEST", "APPROVAL", "DEPARTMENT_INPUT", "MEETING_ACTION", "UNCLEAR",
        }:
            raise _fail(f"invalid label_support.follow_up_target for {record_source_id}")
        if not isinstance(support.get("review_reason"), str):
            raise _fail(f"label_support.review_reason must be a string for {record_source_id}")
    if len(support_labels) != len(set(support_labels)):
        raise _fail(f"duplicate label_support rows for {record_source_id}")
    if set(support_labels) != (set(labels) & set(PROJECT_LABELS)):
        raise _fail(f"selected project labels and label_support rows differ for {record_source_id}")
    if record["needs_review"] and not (
        review_reasons or any(support.get("review_reason", "").strip() for support in supports)
    ):
        raise _fail(f"needs_review requires at least one review reason for {record_source_id}")
    record["__source_id"] = record_source_id
    record["__source_hash"] = resolved_hash
    record["__source_texts"] = source_texts
    record["__reviewer_id"] = reviewer_id or _reviewer_from_provenance(record)
    record["__allocation"] = fallback.get("allocation", record.get("allocation"))
    return record


def _holdout(allocation: Any) -> bool:
    return isinstance(allocation, str) and allocation.casefold() in HOLDOUT_ALLOCATIONS


def _records_from_app_export(
    payload: dict[str, Any], reviewer_id: str | None,
) -> LoadedAnnotations:
    if payload.get("schema_version") not in {"fyp-calibration-export-v1", "fyp-calibration-export-v2"}:
        raise _fail("app export schema_version must be fyp-calibration-export-v1 or fyp-calibration-export-v2")
    raw_sources = payload.get("sources")
    raw_reviews = payload.get("reviews")
    if not isinstance(raw_sources, list) or not isinstance(raw_reviews, list):
        raise _fail("app export must contain sources and reviews arrays")
    sources: dict[str, dict[str, Any]] = {}
    for source in raw_sources:
        source = _as_mapping(source, "app-export source")
        sid = _source_id({}, source)
        if not sid:
            raise _fail("every app-export source row must identify source_id")
        if sid in sources:
            raise _fail(f"duplicate source_id in app export: {sid}")
        sources[sid] = source

    submitted = []
    reviewer_ids = set()
    heldout = 0
    for review in raw_reviews:
        review = _as_mapping(review, "app-export review")
        status = review.get("status")
        if status != "submitted":
            continue
        user_id = review.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise _fail("each submitted app-export review must identify user_id")
        if reviewer_id and user_id != reviewer_id:
            continue
        sid = review.get("source_id")
        if not isinstance(sid, str) or sid not in sources:
            raise _fail("submitted app-export review refers to a missing source row")
        if _holdout(sources[sid].get("allocation")):
            heldout += 1
            continue
        reviewer_ids.add(user_id)
        submitted.append((review, sources[sid], user_id))

    if reviewer_id and reviewer_id not in {str(r.get("user_id")) for r in raw_reviews if isinstance(r, dict)}:
        raise _fail(f"requested reviewer id not present in app export: {reviewer_id}")
    if not reviewer_id and len(reviewer_ids) > 1:
        raise _fail("app export contains multiple submitted reviewers; select one with --reviewer-a-id/--reviewer-b-id")

    records = []
    for review, source, user_id in submitted:
        annotation = _as_json_value(review.get("annotation_json"), "app-export annotation_json")
        annotation = _as_mapping(annotation, "app-export annotation_json")
        if annotation.get("schema_version") != SCHEMA_VERSION:
            raise _fail(
                f"submitted app annotation schema_version must be {SCHEMA_VERSION!r}; "
                f"got {annotation.get('schema_version')!r}"
            )
        records.append(_normalise_direct_record(annotation, source_manifest=source, reviewer_id=user_id))
    return LoadedAnnotations(records, reviewer_ids, heldout)


def _jsonl_rows(text: str, path: Path) -> list[Any]:
    rows: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise _fail(f"invalid JSON on line {line_number} of {path}: {exc.msg}") from exc
    if not rows:
        raise _fail(f"no annotation records found in {path}")
    return rows


def load_annotations(path: Path, reviewer_id: str | None = None) -> LoadedAnnotations:
    """Load JSONL, a flat JSON collection, or a literal annotation-app export."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise _fail(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        rows = _jsonl_rows(text, path)
        if reviewer_id:
            raise _fail("reviewer ID selectors apply only to a JSON app export")
        raw_records = rows
    else:
        if isinstance(payload, dict) and isinstance(payload.get("reviews"), list):
            loaded = _records_from_app_export(payload, reviewer_id)
            _ensure_unique_sources(loaded.records, path)
            _ensure_single_reviewer(loaded.reviewer_ids, path)
            return loaded
        if reviewer_id:
            raise _fail("reviewer ID selectors apply only to a JSON app export")
        if isinstance(payload, list):
            raw_records = payload
        elif isinstance(payload, dict) and "scope" in payload:
            raw_records = [payload]
        elif isinstance(payload, dict):
            raw_records = None
            envelope_version = payload.get("schema_version")
            if envelope_version is not None and envelope_version != SCHEMA_VERSION:
                raise _fail(f"JSON annotation envelope schema_version must be {SCHEMA_VERSION!r}")
            for key in ("records", "annotations", "submissions", "items"):
                if isinstance(payload.get(key), list):
                    raw_records = payload[key]
                    break
            if raw_records is None:
                raise _fail(f"JSON document in {path} is not an annotation or supported export envelope")
        else:
            raise _fail(f"JSON document in {path} must be an object or array")

    records = []
    heldout = 0
    for raw in raw_records:
        outer = _as_mapping(raw, "annotation record")
        allocation = outer.get("allocation")
        if not _holdout(allocation) and isinstance(outer.get("source"), dict):
            allocation = outer["source"].get("allocation", allocation)
        if _holdout(allocation):
            heldout += 1
            continue
        records.append(_normalise_direct_record(outer))
    _ensure_unique_sources(records, path)
    reviewer_ids = {row["__reviewer_id"] for row in records if row.get("__reviewer_id")}
    _ensure_single_reviewer(reviewer_ids, path)
    return LoadedAnnotations(records, reviewer_ids, heldout)


def _ensure_unique_sources(records: list[dict[str, Any]], path: Path) -> None:
    ids = [row["__source_id"] for row in records]
    duplicate_ids = sorted(sid for sid, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        raise _fail(f"duplicate source IDs in {path}: {', '.join(duplicate_ids[:5])}")
    annotation_ids = [row.get("annotation_id") for row in records if row.get("annotation_id") is not None]
    duplicates = sorted(str(sid) for sid, count in Counter(annotation_ids).items() if count > 1)
    if duplicates:
        raise _fail(f"duplicate annotation IDs in {path}: {', '.join(duplicates[:5])}")


def _ensure_single_reviewer(reviewer_ids: set[str], path: Path) -> None:
    if len(reviewer_ids) > 1:
        raise _fail(f"{path} contains records from multiple annotators; provide one file per annotator")


def _prf(tp: int, fp: int, fn: int) -> dict[str, int | float | None]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    denominator = 2 * tp + fp + fn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * tp / denominator if denominator else None,
    }


def _effective_review(record: dict[str, Any]) -> bool:
    if record["needs_review"] or record.get("review_reasons"):
        return True
    return any(
        isinstance(item.get("review_reason"), str) and item["review_reason"].strip()
        for item in record.get("label_support", []) if isinstance(item, dict)
    )


def _eligible_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, int]]:
    eligible = []
    uncertain = review = 0
    for a, b in pairs:
        if a["scope"]["value"] == "UNCERTAIN" or b["scope"]["value"] == "UNCERTAIN":
            uncertain += 1
        elif _effective_review(a) or _effective_review(b):
            review += 1
        else:
            eligible.append((a, b))
    return eligible, {
        "eligible_pairs": len(eligible),
        "excluded_uncertain_scope_pairs": uncertain,
        "excluded_needs_review_pairs": review,
    }


def _set_agreement(a_values: set[Any], b_values: set[Any]) -> bool:
    return a_values == b_values


def _scope_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    confusion: dict[str, dict[str, int]] = {scope: {other: 0 for other in SCOPES} for scope in SCOPES}
    counts_a = Counter()
    counts_b = Counter()
    agrees = 0
    for a, b in pairs:
        sa, sb = a["scope"]["value"], b["scope"]["value"]
        counts_a[sa] += 1
        counts_b[sb] += 1
        confusion[sa][sb] += 1
        agrees += sa == sb
    n = len(pairs)
    return {
        "paired_records": n,
        "agreements": agrees,
        "disagreements": n - agrees,
        "agreement_rate": agrees / n if n else None,
        "counts": {"A": {s: counts_a[s] for s in SCOPES}, "B": {s: counts_b[s] for s in SCOPES}},
        "confusion_A_rows_B_columns": confusion,
    }


def _label_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    by_label: dict[str, Any] = {}
    total_tp = total_fp = total_fn = 0
    macro_scores: list[float] = []
    set_agrees = 0
    for a, b in pairs:
        set_agrees += set(a["labels"]) == set(b["labels"])
    for label in LABELS:
        both_positive = both_negative = a_only = b_only = support_a = support_b = 0
        for a, b in pairs:
            has_a, has_b = label in a["labels"], label in b["labels"]
            support_a += has_a
            support_b += has_b
            if has_a and has_b:
                both_positive += 1
            elif has_a:
                a_only += 1
            elif has_b:
                b_only += 1
            else:
                both_negative += 1
        prf = _prf(both_positive, a_only, b_only)
        total_tp += both_positive
        total_fp += a_only
        total_fn += b_only
        if support_a or support_b:
            macro_scores.append(float(prf["f1"]))
        by_label[label] = {
            "eligible_records": len(pairs),
            "support": {"A": support_a, "B": support_b},
            "both_positive": both_positive,
            "both_negative": both_negative,
            "agreements": both_positive + both_negative,
            "disagreements": a_only + b_only,
            "a_only": a_only,
            "b_only": b_only,
            "agreement_rate": (both_positive + both_negative) / len(pairs) if pairs else None,
            "f1": prf,
        }
    micro = _prf(total_tp, total_fp, total_fn)
    exact_count = len(pairs)
    return {
        "eligible_records": exact_count,
        "exact_multilabel_set": {
            "eligible_records": exact_count,
            "agreements": set_agrees,
            "disagreements": exact_count - set_agrees,
            "agreement_rate": set_agrees / exact_count if exact_count else None,
        },
        "micro_f1": micro,
        "macro_f1": sum(macro_scores) / len(macro_scores) if macro_scores else None,
        "macro_f1_label_count": len(macro_scores),
        "per_label": by_label,
        "disagreements_by_label": {
            label: {"a_only": by_label[label]["a_only"], "b_only": by_label[label]["b_only"],
                    "total": by_label[label]["disagreements"]}
            for label in LABELS
        },
    }


def _span_signature(span: dict[str, Any]) -> tuple[Any, ...]:
    return (span["field"], span["type"], span["start"], span["end"], span["text"])


def _span_iou(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    start = max(a["start"], b["start"])
    end = min(a["end"], b["end"])
    if start >= end:
        return None
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return (end - start) / union


def _maximum_overlap_pairs(
    left: list[dict[str, Any]], right: list[dict[str, Any]],
) -> list[tuple[int, int, float]]:
    """Return a maximum-cardinality, one-to-one matching for one field/type."""
    graph: list[list[tuple[int, float]]] = []
    for a in left:
        edges = []
        for j, b in enumerate(right):
            score = _span_iou(a, b)
            if score is not None:
                edges.append((j, score))
        graph.append(sorted(edges, key=lambda edge: (-edge[1], edge[0])))
    owners: dict[int, tuple[int, float]] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j, score in graph[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or augment(owners[j][0], seen):
                owners[j] = (i, score)
                return True
        return False

    # Process the most constrained spans first; augmenting paths still maximize
    # cardinality, while this order makes tied solutions deterministic.
    for i in sorted(range(len(left)), key=lambda index: (len(graph[index]), left[index]["start"], left[index]["end"], index)):
        augment(i, set())
    return [(i, j, score) for j, (i, score) in sorted(owners.items())]


def _span_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    exact_tp = exact_fp = exact_fn = overlap_tp = overlap_fp = overlap_fn = 0
    overlap_ious: list[float] = []
    by_type: dict[str, dict[str, int | list[float]]] = defaultdict(
        lambda: {"exact_tp": 0, "exact_fp": 0, "exact_fn": 0,
                 "overlap_tp": 0, "overlap_fp": 0, "overlap_fn": 0, "ious": []}
    )
    total_a = total_b = 0
    for a, b in pairs:
        spans_a, spans_b = a["spans"], b["spans"]
        total_a += len(spans_a)
        total_b += len(spans_b)
        types = {span["type"] for span in spans_a + spans_b}
        exact_matched_all = 0
        overlap_matched_all = 0
        for span_type in types:
            rows_a = [span for span in spans_a if span["type"] == span_type]
            rows_b = [span for span in spans_b if span["type"] == span_type]
            exact_a = Counter(_span_signature(span) for span in rows_a)
            exact_b = Counter(_span_signature(span) for span in rows_b)
            exact_matched = sum((exact_a & exact_b).values())
            exact_matched_all += exact_matched
            by_type[span_type]["exact_tp"] += exact_matched
            by_type[span_type]["exact_fp"] += len(rows_a) - exact_matched
            by_type[span_type]["exact_fn"] += len(rows_b) - exact_matched

            groups_a: dict[str, list[dict[str, Any]]] = defaultdict(list)
            groups_b: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for span in rows_a:
                groups_a[span["field"]].append(span)
            for span in rows_b:
                groups_b[span["field"]].append(span)
            for field in set(groups_a) | set(groups_b):
                left, right = groups_a[field], groups_b[field]
                matches = _maximum_overlap_pairs(left, right)
                overlap_matched_all += len(matches)
                ious = [score for _, _, score in matches]
                overlap_ious.extend(ious)
                by_type[span_type]["overlap_tp"] += len(matches)
                by_type[span_type]["overlap_fp"] += len(left) - len(matches)
                by_type[span_type]["overlap_fn"] += len(right) - len(matches)
                by_type[span_type]["ious"].extend(ious)
        exact_tp += exact_matched_all
        exact_fp += len(spans_a) - exact_matched_all
        exact_fn += len(spans_b) - exact_matched_all
        overlap_tp += overlap_matched_all
        overlap_fp += len(spans_a) - overlap_matched_all
        overlap_fn += len(spans_b) - overlap_matched_all

    per_type: dict[str, Any] = {}
    for span_type, counts in sorted(by_type.items()):
        ious = counts["ious"]
        per_type[span_type] = {
            "exact": _prf(int(counts["exact_tp"]), int(counts["exact_fp"]), int(counts["exact_fn"])),
            "overlap": {
                **_prf(int(counts["overlap_tp"]), int(counts["overlap_fp"]), int(counts["overlap_fn"])),
                "mean_iou": sum(ious) / len(ious) if ious else None,
            },
        }
    return {
        "eligible_records": len(pairs),
        "span_counts": {"A": total_a, "B": total_b},
        "exact_micro": _prf(exact_tp, exact_fp, exact_fn),
        "overlap_micro": {
            **_prf(overlap_tp, overlap_fp, overlap_fn),
            "mean_iou": sum(overlap_ious) / len(overlap_ious) if overlap_ious else None,
            "matching": "maximum-cardinality one-to-one by source field and span type; positive character overlap",
        },
        "by_type": per_type,
    }


def _support_links(record: dict[str, Any]) -> set[tuple[str, str, str]]:
    links = set()
    for support in record["label_support"]:
        label = support["label"]
        for relation_name in ("applies_to", "follow_up_target"):
            value = support.get(relation_name)
            if value is not None and value != "" and value != [] and value != {}:
                links.add((label, relation_name, _canonical(value)))
    return links


def _explicit_relations(record: dict[str, Any]) -> set[str]:
    relations = record.get("relations")
    if relations is None:
        return set()
    if not isinstance(relations, list):
        raise _fail(f"relations must be an array for {record['__source_id']}")
    return {_canonical(relation) for relation in relations}


def _relation_metrics(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    values,
    *,
    available: bool = True,
) -> dict[str, Any]:
    tp = fp = fn = exact = count_a = count_b = 0
    for a, b in pairs:
        left, right = values(a), values(b)
        count_a += len(left)
        count_b += len(right)
        tp += len(left & right)
        fp += len(left - right)
        fn += len(right - left)
        exact += left == right
    return {
        "available": available,
        "eligible_records": len(pairs),
        "items": {"A": count_a if available else None, "B": count_b if available else None},
        "exact_set_agreement": exact / len(pairs) if pairs and available else None,
        "exact_set_agreements": exact if available else None,
        "micro_f1": _prf(tp, fp, fn) if available else None,
        "comparison": "scored separately from labels and spans",
    }


def _check_pair_sources(
    pairs_by_id_a: dict[str, dict[str, Any]], pairs_by_id_b: dict[str, dict[str, Any]],
) -> int:
    ids_a, ids_b = set(pairs_by_id_a), set(pairs_by_id_b)
    if ids_a != ids_b:
        missing_a = sorted(ids_b - ids_a)[:5]
        missing_b = sorted(ids_a - ids_b)[:5]
        raise _fail(f"source ID sets differ; missing from A={missing_a}, missing from B={missing_b}")
    checked_hashes = 0
    for source_id in sorted(ids_a):
        a, b = pairs_by_id_a[source_id], pairs_by_id_b[source_id]
        hash_a, hash_b = a.get("__source_hash"), b.get("__source_hash")
        if bool(hash_a) != bool(hash_b):
            raise _fail(f"source hash is present for only one annotator on {source_id}")
        if hash_a and hash_a != hash_b:
            raise _fail(f"source hashes differ for {source_id}")
        if hash_a:
            checked_hashes += 1
        text_a, text_b = a.get("__source_texts", {}), b.get("__source_texts", {})
        for field in set(text_a) & set(text_b):
            if text_a[field] != text_b[field]:
                raise _fail(f"source field {field} differs for {source_id}")
    return checked_hashes


def compare_direct_records(
    reviewer_a_records: Iterable[dict[str, Any]],
    reviewer_b_records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Compute pairwise agreement on direct labels, with review rows separated."""
    a_rows, b_rows = list(reviewer_a_records), list(reviewer_b_records)
    if not a_rows or not b_rows:
        raise _fail("both inputs must contain at least one submitted direct annotation")
    a_by_id: dict[str, dict[str, Any]] = {}
    b_by_id: dict[str, dict[str, Any]] = {}
    for dest, rows, side in ((a_by_id, a_rows, "A"), (b_by_id, b_rows, "B")):
        for raw in rows:
            record = raw if "__source_id" in raw else _normalise_direct_record(raw)
            source_id = record["__source_id"]
            if source_id in dest:
                raise _fail(f"duplicate source_id for reviewer {side}: {source_id}")
            dest[source_id] = record
    checked_hashes = _check_pair_sources(a_by_id, b_by_id)
    reviewer_ids_a = {row["__reviewer_id"] for row in a_by_id.values() if row.get("__reviewer_id")}
    reviewer_ids_b = {row["__reviewer_id"] for row in b_by_id.values() if row.get("__reviewer_id")}
    shared_reviewers = reviewer_ids_a & reviewer_ids_b
    if shared_reviewers:
        raise _fail("annotator identities overlap between reviewer A and reviewer B")

    pairs = [(a_by_id[sid], b_by_id[sid]) for sid in sorted(a_by_id)]
    eligible, exclusion_counts = _eligible_pairs(pairs)
    has_support_links = any(_support_links(record) for pair in eligible for record in pair)
    supports = _relation_metrics(eligible, _support_links, available=has_support_links)
    has_explicit_relations = any("relations" in row for pair in pairs for row in pair)
    explicit_relations = _relation_metrics(
        eligible, _explicit_relations, available=has_explicit_relations,
    )
    needs_review_a = sum(_effective_review(a) for a, _ in pairs)
    needs_review_b = sum(_effective_review(b) for _, b in pairs)
    review_both = sum(_effective_review(a) and _effective_review(b) for a, b in pairs)
    uncertain_a = sum(a["scope"]["value"] == "UNCERTAIN" for a, _ in pairs)
    uncertain_b = sum(b["scope"]["value"] == "UNCERTAIN" for _, b in pairs)

    return {
        "report_version": REPORT_VERSION,
        "annotation_schema_version": SCHEMA_VERSION,
        "interpretation": "descriptive pairwise annotator agreement only; neither annotator is gold",
        "metric_definitions": {
            "scope": "agreement on every aligned pair, including UNCERTAIN choices",
            "labels_spans_relations": "eligible only when both scope choices are definite and neither record needs review",
            "label_micro_f1": "pooled positive-label counts across all nine FYP labels",
            "label_macro_f1": "mean positive-class F1 over labels selected by either annotator at least once",
            "exact_span": "same source field, type, half-open start/end offsets, and text",
            "overlap_span": "positive character overlap with maximum-cardinality one-to-one matching per source field and span type",
        },
        "paired_records": len(pairs),
        "source_alignment": {"id_sets_match": True, "source_hashes_checked": checked_hashes},
        "review_status": {
            **exclusion_counts,
            "A_needs_review_records": needs_review_a,
            "B_needs_review_records": needs_review_b,
            "both_need_review_records": review_both,
            "A_uncertain_scope_records": uncertain_a,
            "B_uncertain_scope_records": uncertain_b,
            "unresolved_records_are_excluded_from_label_span_and_relation_metrics": True,
        },
        "scope": _scope_metrics(pairs),
        "labels": _label_metrics(eligible),
        "spans": _span_metrics(eligible),
        "relations": {
            "label_support_links": supports,
            "explicit_relations": explicit_relations,
        },
        "gold_annotations_scored": 0,
        "gold_promotion": "not_automatic; requires independent human adjudication and provenance review",
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-a", type=Path, required=True,
                        help="direct-label JSONL or app-export JSON for annotator A")
    parser.add_argument("--reviewer-b", type=Path, required=True,
                        help="direct-label JSONL or app-export JSON for annotator B")
    parser.add_argument("--reviewer-a-id", help="select one reviewer from an app export")
    parser.add_argument("--reviewer-b-id", help="select one reviewer from an app export")
    parser.add_argument("--report", type=Path, required=True, help="aggregate metrics JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if bool(args.reviewer_a_id) != bool(args.reviewer_b_id):
        parser.error("--reviewer-a-id and --reviewer-b-id must be supplied together")
    try:
        a = load_annotations(args.reviewer_a, args.reviewer_a_id)
        b = load_annotations(args.reviewer_b, args.reviewer_b_id)
        report = compare_direct_records(a.records, b.records)
        report["input_handling"] = {
            "A_heldout_rows_excluded": a.heldout_rows_excluded,
            "B_heldout_rows_excluded": b.heldout_rows_excluded,
            "reviewer_A_id_known": len(a.reviewer_ids) == 1,
            "reviewer_B_id_known": len(b.reviewer_ids) == 1,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "paired_records": report["paired_records"],
        "eligible_label_records": report["labels"]["eligible_records"],
        "scope_agreement": report["scope"]["agreement_rate"],
        "exact_label_set_agreement": report["labels"]["exact_multilabel_set"]["agreement_rate"],
        "report": str(args.report),
        "agreement_is_not_gold": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

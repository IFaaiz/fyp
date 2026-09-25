"""Validation of canonical records and split isolation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .schemas import ANNOTATION_STATUSES, LABELS, REQUIRED, SOURCES, SPAN_LABELS


def validate_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED - record.keys()
    if missing:
        return [f"missing fields: {', '.join(sorted(missing))}"]
    for field in ("email_id", "thread_id"):
        if not isinstance(record[field], str) or not record[field].strip():
            errors.append(f"{field} must be a nonempty string")
    if not isinstance(record["source_dataset"], str) or record["source_dataset"] not in SOURCES:
        errors.append("invalid source_dataset")
    if not isinstance(record["turn_index"], int) or record["turn_index"] < 0:
        errors.append("turn_index must be a nonnegative integer")
    for field in ("subject", "raw_body", "current_message", "clean_body", "thread_context", "sender"):
        if not isinstance(record[field], str):
            errors.append(f"{field} must be a string")
    if record["sent_at"] is not None and not isinstance(record["sent_at"], str):
        errors.append("sent_at must be a string or null")
    for field in ("recipients", "cc", "attachment_names"):
        if not isinstance(record[field], list) or any(not isinstance(x, str) for x in record[field]):
            errors.append(f"{field} must be a list of strings")
    labels = record["labels"]
    if not isinstance(labels, list) or any(not isinstance(x, str) or x not in LABELS for x in labels):
        errors.append("labels must be a list of known classification labels")
    elif len(labels) != len(set(labels)):
        errors.append("duplicate labels")
    elif "NON_PROJECT" in labels and len(labels) > 1:
        errors.append("NON_PROJECT cannot co-occur with project labels")
    annotation = record["annotation"]
    if not isinstance(annotation, dict) or not isinstance(annotation.get("status"), str) or annotation.get("status") not in ANNOTATION_STATUSES:
        errors.append("annotation.status is invalid")
    else:
        status = annotation["status"]
        source = annotation.get("annotation_source")
        annotator = annotation.get("annotator")
        if source not in {None, "dataset", "human", "ai", "synthetic"}:
            errors.append("annotation.annotation_source is invalid")
        if status == "ai_prelabelled" and source != "ai":
            errors.append("ai_prelabelled requires ai annotation_source")
        if status in {"human_reviewed", "gold"}:
            if source != "human":
                errors.append(f"{status} requires human annotation_source")
            if not isinstance(annotator, str) or not annotator.strip():
                errors.append(f"{status} requires annotator")
        if status == "gold" and record["source_dataset"] == "synthetic":
            errors.append("synthetic record cannot be gold")
        if status == "unlabelled":
            if labels:
                errors.append("unlabelled record cannot carry classification labels")
            if record["spans"] and source != "dataset":
                errors.append("unlabelled spans require dataset annotation_source")
    spans = record["spans"]
    if not isinstance(spans, list):
        errors.append("spans must be a list")
    else:
        seen_spans: set[tuple[str, int, int, str]] = set()
        for index, span in enumerate(spans):
            if not isinstance(span, dict):
                errors.append(f"span {index} must be an object")
                continue
            field = span.get("field", "current_message")
            if field not in {"current_message", "subject"}:
                errors.append(f"span {index}: invalid field")
                continue
            start, end, value = span.get("start"), span.get("end"), span.get("text")
            if isinstance(start, int) and isinstance(end, int) and isinstance(span.get("label"), str):
                key = (field, start, end, span["label"])
                if key in seen_spans:
                    errors.append(f"span {index}: duplicate canonical span")
                seen_spans.add(key)
            if span.get("label") not in SPAN_LABELS:
                errors.append(f"span {index}: invalid label")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                errors.append(f"span {index}: invalid offsets")
            elif not isinstance(record[field], str) or record[field][start:end] != value:
                errors.append(f"span {index}: text/offset mismatch in {field}")
    return errors


def validate_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    seen: set[str] = set()
    by_source: Counter[str] = Counter()
    count = 0
    for count, record in enumerate(records, 1):
        email_id = record.get("email_id")
        if email_id in seen:
            errors.append(f"record {count}: duplicate email_id {email_id}")
        seen.add(email_id)
        by_source[str(record.get("source_dataset"))] += 1
        errors.extend(f"record {count}: {error}" for error in validate_record(record))
    return {"records": count, "by_source": dict(by_source), "errors": errors}


def validate_split_isolation(splits: dict[str, list[dict[str, Any]]]) -> list[str]:
    errors = []
    owners: dict[str, str] = {}
    for split_name, records in splits.items():
        for record in records:
            if record.get("annotation", {}).get("status") == "gold" and split_name != "test":
                errors.append(f"gold record {record.get('email_id')} occurs in {split_name}")
            if record.get("source_dataset") == "synthetic" and split_name == "test":
                errors.append(f"synthetic record {record.get('email_id')} occurs in test")
            thread = record["thread_id"]
            key = f"{record['source_dataset']}:{thread}"
            previous = owners.setdefault(key, split_name)
            if previous != split_name:
                errors.append(f"thread {key} occurs in {previous} and {split_name}")
    return sorted(set(errors))

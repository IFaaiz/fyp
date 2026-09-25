"""Apply explicit human adjudication decisions to canonical records."""
from __future__ import annotations
from collections.abc import Iterable
from typing import Any
from ..datasets.validation import validate_record
from .label_studio import assert_no_gold_threads


def apply_adjudication_decisions(
    base_records: Iterable[dict[str, Any]], decisions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only explicitly finalized, human-reviewed decisions; never mark gold."""
    base_rows = list(base_records)
    decision_rows = list(decisions)
    by_id = {row.get("email_id"): row for row in base_rows}
    if None in by_id or len(by_id) != len(base_rows):
        raise ValueError("base records must have unique nonempty email_id values")
    if any(not isinstance(key, str) or not key for key in by_id):
        raise ValueError("base records must have unique nonempty email_id values")
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for decision in decision_rows:
        email_id = decision.get("email_id")
        if not isinstance(email_id, str) or not email_id:
            raise ValueError("every adjudication decision needs email_id")
        if email_id in seen:
            raise ValueError(f"duplicate adjudication decision for {email_id}")
        seen.add(email_id)
        if email_id not in by_id:
            raise ValueError(f"adjudication decision references unknown email_id {email_id}")
        if decision.get("final") is not True:
            raise ValueError(f"adjudication decision for {email_id} must set final=true")
        adjudicator = decision.get("adjudicator")
        if not isinstance(adjudicator, str) or not adjudicator.strip():
            raise ValueError(f"adjudication decision for {email_id} needs a human adjudicator")
        labels = decision.get("labels")
        spans = decision.get("spans")
        if not isinstance(labels, list) or not labels:
            raise ValueError(f"final adjudication for {email_id} must choose at least one classification label")
        if not isinstance(spans, list):
            raise ValueError(f"final adjudication for {email_id} needs a spans list")
        record = dict(by_id[email_id])
        if record.get("annotation", {}).get("status") == "gold":
            raise ValueError(f"cannot change existing gold record {email_id}")
        canonical_spans = []
        for span in spans:
            if not isinstance(span, dict):
                raise ValueError(f"adjudication span for {email_id} must be an object")
            value = dict(span)
            value.setdefault("field", "current_message")
            canonical_spans.append(value)
        record["labels"] = labels
        record["spans"] = canonical_spans
        note = decision.get("resolution_note")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"resolution_note for {email_id} must be a string")
        record["annotation"] = {
            "status": "human_reviewed", "annotator": adjudicator,
            "annotation_source": "human", "confidence": None,
            "adjudication_note": note,
        }
        errors = validate_record(record)
        if errors:
            raise ValueError(f"adjudicated record {email_id} is invalid: {'; '.join(errors)}")
        selected.append(record)
    assert_no_gold_threads(selected, base_rows)
    return selected

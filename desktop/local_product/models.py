"""Typed records shared by local import adapters, storage, and UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
from typing import Any, Iterable


LABELS = (
    "MEETING",
    "DEADLINE",
    "REPORT_REQUEST",
    "DEPARTMENTAL_INPUT",
    "ACTION_REQUEST",
    "FOLLOW_UP",
    "APPROVAL",
    "GENERAL_UPDATE",
)
NON_PROJECT_LABEL = "NON_PROJECT"
ALL_LABELS = frozenset((*LABELS, NON_PROJECT_LABEL))
SCOPE_VALUES = frozenset({"PROJECT", "NON_PROJECT", "UNCERTAIN"})
SPAN_TYPES = frozenset(
    {
        "MEETING_DATE",
        "MEETING_TIME",
        "DEADLINE_DATE",
        "DEADLINE_TIME",
        "PARTICIPANT",
        "RESPONSIBLE_PARTY",
        "DEPARTMENT",
        "AGENDA",
        "ACTION_ITEM",
        "REQUESTED_DOCUMENT",
        "PROJECT",
        "EVIDENCE",  # Auxiliary evidence only; it is not an extraction target.
    }
)


def _string(value: Any, field_name: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if required and not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a string or list of strings")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only strings")
        if item and item not in values:
            values.append(item)
    return tuple(values)


def _json_value(value: Any, field_name: str) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON-compatible values") from exc
    return value


def normalize_message_id(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("<") and stripped.endswith(">"):
        stripped = stripped[1:-1].strip()
    return stripped or None


def parse_message_ids(values: Any) -> tuple[str, ...]:
    """Normalize a References header/list while keeping its observed order."""
    raw_values = _string_tuple(values, "references")
    result: list[str] = []
    for value in raw_values:
        parts = value.split()
        if len(parts) == 1:
            parts = [value]
        for part in parts:
            normalized = normalize_message_id(part)
            if normalized and normalized not in result:
                result.append(normalized)
    return tuple(result)


def effective_thread_id(
    thread_id: str | None,
    source_id: str,
    message_id: str | None,
    in_reply_to: str | None,
    references: Iterable[str],
) -> str:
    if thread_id and thread_id.strip():
        return thread_id.strip()
    references = tuple(references)
    if references:
        return f"message-thread:{references[0]}"
    if in_reply_to:
        return f"message-thread:{normalize_message_id(in_reply_to) or in_reply_to}"
    # A standalone parent message becomes the stable root that replies using
    # only In-Reply-To can resolve to, even when it has no References header.
    if message_id:
        return f"message-thread:{normalize_message_id(message_id) or message_id}"
    return f"message:{source_id}"


def _normalize_labels(labels: Any) -> tuple[str, ...]:
    values = _string_tuple(labels, "labels")
    unknown = sorted(set(values) - ALL_LABELS)
    if unknown:
        raise ValueError(f"labels contain unsupported FYP values: {', '.join(unknown)}")
    if NON_PROJECT_LABEL in values and len(values) > 1:
        raise ValueError("NON_PROJECT is exclusive and cannot be combined with project labels")
    return tuple(label for label in (*LABELS, NON_PROJECT_LABEL) if label in values)


def _normalize_spans(spans: Any) -> tuple[dict[str, Any], ...]:
    if spans is None:
        return ()
    if not isinstance(spans, (list, tuple)):
        raise ValueError("spans must be a list")
    result: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError("each span must be an object")
        span_type = span.get("type", span.get("label"))
        if span_type not in SPAN_TYPES:
            raise ValueError("span type is not in the approved extraction schema")
        text = span.get("text")
        if not isinstance(text, str):
            raise ValueError("span text must be a string")
        field_name = span.get("field", "current_message")
        if field_name not in {"current_message", "subject"}:
            raise ValueError("span field must be current_message or subject")
        start, end = span.get("start"), span.get("end")
        if (start is None) != (end is None):
            raise ValueError("span start and end must either both be set or both be omitted")
        if start is not None and (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end < start
        ):
            raise ValueError("span offsets must be non-negative integers with end >= start")
        result.append(dict(span))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class EmailRecord:
    """One normalized message. Attachments are represented by names only."""

    source_id: str
    source_name: str
    project_or_list: str = ""
    message_id: str | None = None
    in_reply_to: str | None = None
    references: tuple[str, ...] = ()
    thread_id: str = ""
    subject: str = ""
    sender: str = ""
    recipients: tuple[str, ...] = ()
    timestamp: str | None = None
    body_raw: str = ""
    current_message: str = ""
    quoted_history: str = ""
    attachment_names: tuple[str, ...] = ()
    provenance: Any = field(default_factory=dict)
    license_or_terms_note: str = ""
    scope: str | None = None
    labels: tuple[str, ...] = ()
    spans: tuple[dict[str, Any], ...] = ()
    annotation_method: str = "UNANNOTATED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _string(self.source_id, "source_id", required=True))
        object.__setattr__(self, "source_name", _string(self.source_name, "source_name", required=True))
        for name in (
            "project_or_list",
            "thread_id",
            "subject",
            "sender",
            "body_raw",
            "current_message",
            "quoted_history",
            "license_or_terms_note",
        ):
            object.__setattr__(self, name, _string(getattr(self, name), name))
        object.__setattr__(self, "annotation_method", _string(self.annotation_method, "annotation_method", required=True))
        for name in ("message_id", "in_reply_to", "timestamp"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _string(value, name))
        object.__setattr__(self, "message_id", normalize_message_id(self.message_id))
        object.__setattr__(self, "in_reply_to", normalize_message_id(self.in_reply_to))
        object.__setattr__(self, "references", parse_message_ids(self.references))
        object.__setattr__(self, "recipients", _string_tuple(self.recipients, "recipients"))
        object.__setattr__(self, "attachment_names", _string_tuple(self.attachment_names, "attachment_names"))
        object.__setattr__(self, "labels", _normalize_labels(self.labels))
        object.__setattr__(self, "spans", _normalize_spans(self.spans))
        _json_value(self.provenance, "provenance")
        for span in self.spans:
            span_text = span["text"]
            if not span_text:
                raise ValueError("span text must not be blank")
            source_text = self.subject if span.get("field", "current_message") == "subject" else self.current_message
            if span.get("start") is not None:
                if span["end"] > len(source_text) or source_text[span["start"] : span["end"]] != span_text:
                    raise ValueError("span offsets and text must exactly match the selected source field")
            elif span_text not in source_text:
                raise ValueError("span text must occur exactly in the selected source field")
        if self.scope is not None and self.scope not in SCOPE_VALUES:
            raise ValueError("scope must be PROJECT, NON_PROJECT, UNCERTAIN, or null")
        if self.scope == "NON_PROJECT" and any(label != NON_PROJECT_LABEL for label in self.labels):
            raise ValueError("NON_PROJECT scope cannot carry project labels")
        if self.scope == "PROJECT" and NON_PROJECT_LABEL in self.labels:
            raise ValueError("PROJECT scope cannot carry NON_PROJECT")
        if self.scope == "UNCERTAIN" and self.labels:
            raise ValueError("UNCERTAIN scope cannot carry final project labels")

    @property
    def canonical_thread_id(self) -> str:
        return effective_thread_id(
            self.thread_id, self.source_id, self.message_id, self.in_reply_to, self.references
        )

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body_raw.encode("utf-8", errors="replace")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "project_or_list": self.project_or_list,
            "message_id": self.message_id,
            "in_reply_to": self.in_reply_to,
            "references": list(self.references),
            "thread_id": self.canonical_thread_id,
            "subject": self.subject,
            "sender": self.sender,
            "recipients": list(self.recipients),
            "timestamp": self.timestamp,
            "body_raw": self.body_raw,
            "current_message": self.current_message,
            "quoted_history": self.quoted_history,
            "attachment_names": list(self.attachment_names),
            "provenance": self.provenance,
            "license_or_terms_note": self.license_or_terms_note,
            "scope": self.scope,
            "labels": list(self.labels),
            "spans": [dict(span) for span in self.spans],
            "annotation_method": self.annotation_method,
        }

    @classmethod
    def from_mapping(cls, row: dict[str, Any], *, source_name: str | None = None) -> "EmailRecord":
        """Read the agreed normalized JSONL shape and narrow legacy aliases."""
        if not isinstance(row, dict):
            raise ValueError("each JSONL row must be an object")
        labels = row.get("labels", [])
        scope = row.get("scope")
        if isinstance(labels, str):
            labels = [labels]
        if isinstance(labels, list):
            scope_labels = [label for label in labels if isinstance(label, str) and label in SCOPE_VALUES]
            if scope is None and scope_labels:
                if len(set(scope_labels)) > 1:
                    raise ValueError("labels contain conflicting scope values")
                scope = scope_labels[0]
                labels = [label for label in labels if label not in SCOPE_VALUES]
        body_raw = row.get("body_raw", row.get("raw_body", row.get("body", "")))
        if not isinstance(body_raw, str):
            raise ValueError("body_raw must be a string")
        current = row.get("current_message")
        quoted = row.get("quoted_history", "")
        if current is None:
            from .preprocessing import split_authored_text

            current, derived_quote = split_authored_text(body_raw)
            if not quoted:
                quoted = derived_quote
        if not isinstance(current, str):
            raise ValueError("current_message must be a string")
        if isinstance(quoted, list):
            if not all(isinstance(part, str) for part in quoted):
                raise ValueError("quoted_history list must contain strings")
            quoted = "\n\n".join(quoted)
        raw_in_reply_to = row.get("in_reply_to")
        in_reply_to_ids = parse_message_ids(raw_in_reply_to)
        provenance_value = _json_value(row.get("provenance", {}), "provenance")
        provenance: dict[str, Any]
        if isinstance(provenance_value, dict):
            provenance = dict(provenance_value)
        else:
            provenance = {"source_provenance": provenance_value}
        if isinstance(raw_in_reply_to, list):
            # Keep the complete source list even though the canonical column
            # uses its first observed parent ID.
            provenance["in_reply_to_observed"] = raw_in_reply_to
        known_fields = {
            "source_id", "email_id", "source_name", "source_dataset",
            "project_or_list", "project", "message_id", "in_reply_to",
            "references", "thread_id", "subject", "sender", "recipients",
            "timestamp", "sent_at", "body_raw", "raw_body", "body",
            "current_message", "quoted_history", "attachment_names",
            "provenance", "license_or_terms_note", "scope", "labels",
            "spans", "annotation_method",
        }
        source_metadata = {key: value for key, value in row.items() if key not in known_fields}
        if source_name and row.get("source_name") and row["source_name"] != source_name:
            source_metadata["source_name"] = row["source_name"]
        if source_metadata:
            existing_metadata = provenance.get("source_metadata", {})
            if isinstance(existing_metadata, dict):
                provenance["source_metadata"] = {**existing_metadata, **source_metadata}
            else:
                provenance["source_metadata"] = {
                    "source_metadata": existing_metadata,
                    **source_metadata,
                }
        record = cls(
            source_id=_string(row.get("source_id", row.get("email_id")), "source_id", required=True),
            source_name=source_name or _string(row.get("source_name", row.get("source_dataset", "jsonl")), "source_name", required=True),
            project_or_list=_string(row.get("project_or_list", row.get("project", "")), "project_or_list"),
            message_id=normalize_message_id(row.get("message_id")),
            in_reply_to=in_reply_to_ids[0] if in_reply_to_ids else None,
            references=parse_message_ids(row.get("references", [])),
            thread_id=_string(row.get("thread_id"), "thread_id"),
            subject=_string(row.get("subject"), "subject"),
            sender=_string(row.get("sender"), "sender"),
            recipients=_string_tuple(row.get("recipients", []), "recipients"),
            timestamp=_timestamp(row.get("timestamp", row.get("sent_at"))),
            body_raw=body_raw,
            current_message=current,
            quoted_history=_string(quoted, "quoted_history"),
            attachment_names=_string_tuple(row.get("attachment_names", []), "attachment_names"),
            provenance=provenance,
            license_or_terms_note=_string(row.get("license_or_terms_note", ""), "license_or_terms_note"),
            scope=scope,
            labels=labels,
            spans=_normalize_spans(row.get("spans", [])),
            annotation_method=_string(row.get("annotation_method", "UNANNOTATED"), "annotation_method"),
        )
        if (record.scope is not None or record.labels or record.spans) and record.annotation_method == "UNANNOTATED":
            raise ValueError("records with labels, scope, or spans must name their annotation_method")
        return record


def _timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string or date-time")
    return value

"""Canonical JSONL record contract shared by all email sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

LABELS = frozenset({
    "MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT", "ACTION_REQUEST",
    "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE", "NON_PROJECT",
})
SPAN_LABELS = frozenset({
    "MEETING_DATE", "MEETING_TIME", "DEADLINE_DATE", "DEADLINE_TIME", "PARTICIPANT",
    "RESPONSIBLE_PARTY", "DEPARTMENT", "AGENDA", "ACTION_ITEM",
    "REQUESTED_DOCUMENT", "PROJECT",
})
ANNOTATION_STATUSES = frozenset({
    "unlabelled", "ai_prelabelled", "human_reviewed", "gold",
})
SOURCES = frozenset({"mailex", "enron", "manual", "synthetic"})
REQUIRED = frozenset({
    "email_id", "source_dataset", "thread_id", "turn_index", "subject",
    "raw_body", "current_message", "clean_body", "thread_context", "sender",
    "recipients", "cc", "sent_at", "attachment_names", "labels", "spans",
    "annotation",
})


def empty_record(
    *, email_id: str, source_dataset: str, thread_id: str,
    raw_body: str, subject: str = "", turn_index: int = 0,
) -> dict[str, Any]:
    """Make an unlabelled record; callers fill metadata and derived text."""
    return {
        "email_id": email_id, "source_dataset": source_dataset,
        "thread_id": thread_id, "turn_index": turn_index, "subject": subject,
        "raw_body": raw_body, "current_message": raw_body,
        "clean_body": raw_body, "thread_context": "", "sender": "",
        "recipients": [], "cc": [], "sent_at": None, "attachment_names": [],
        "labels": [], "spans": [],
        "annotation": {
            "status": "unlabelled", "annotator": None,
            "annotation_source": None, "confidence": None,
        },
    }


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record must be an object")
            yield value


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count

"""Sparse exact-text extraction suggestions, never approved archive fields.

This deliberately limited baseline does not infer owners, projects, participants,
agenda items or missing dates. Each returned offset is in current_message.
Relative dates remain raw strings: no calendar resolution or time zone guessing.
"""
from __future__ import annotations

import re
from .models import EmailRecord

TARGETS = (
    "MEETING_DATE", "MEETING_TIME", "DEADLINE_DATE", "DEADLINE_TIME",
    "PARTICIPANT", "RESPONSIBLE_PARTY", "DEPARTMENT", "AGENDA",
    "ACTION_ITEM", "REQUESTED_DOCUMENT", "PROJECT",
)
_DATE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|today|tomorrow|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))\b", re.I)
_TIME = re.compile(r"\b(?:\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?|(?:[01]?\d|2[0-3]):[0-5]\d|noon|midnight)\b", re.I)
_MEETING = re.compile(r"\b(?:meeting|teleconference|telecon|conference call)\b", re.I)
_DUE = re.compile(r"\b(?:deadline|due|overdue|(?:submit|send|complete|finish|review)[^.!?\n]{0,100}\bby)\b", re.I)
_DOC_REQUEST = re.compile(r"\b(?:please|could you|can you|would you|kindly)\s+(?:send|share|provide|submit|forward)\b(?P<object>[^.!?\n]{0,120})", re.I)
_DOCUMENT = re.compile(r"\b(?:(?:revised|updated|draft|status|monthly|weekly|final)\s+){0,2}(?:report|document|proposal|minutes|plan|draft)\b", re.I)
_ACTION = re.compile(r"\b(?:please|could you|can you|would you|kindly)\s+(?P<item>(?:review|update|prepare|complete|confirm|check|revise|organize|organise|call|contact|finish|test|fix)\b[^.!?\n]{0,160})", re.I)


def extract_rule_suggestions(record: EmailRecord) -> dict:
    text = record.current_message
    spans = []

    def add(kind, start, end, rule):
        while end > start and text[end - 1].isspace():
            end -= 1
        value = {"type": kind, "field": "current_message", "start": start,
                 "end": end, "text": text[start:end], "rule_id": rule,
                 "status": "REVIEW"}
        if end > start and not any(s["type"] == kind and s["start"] == start and s["end"] == end for s in spans):
            spans.append(value)

    for sentence in re.finditer(r"[^.!?\n]+(?:[.!?]|$)", text):
        value = sentence.group()
        kinds = []
        if _MEETING.search(value):
            kinds.append("MEETING")
        if _DUE.search(value):
            kinds.append("DEADLINE")
        # A sentence with both may contain multiple dates for different events.
        # Abstain rather than attach every date/time to both roles.
        if len(kinds) != 1:
            continue
        for pattern, suffix in ((_DATE, "DATE"), (_TIME, "TIME")):
            for match in pattern.finditer(value):
                add(kinds[0] + "_" + suffix, sentence.start() + match.start(),
                    sentence.start() + match.end(), "explicit_" + kinds[0].lower() + "_context")
    for request in _DOC_REQUEST.finditer(text):
        for document in _DOCUMENT.finditer(request.group("object")):
            add("REQUESTED_DOCUMENT", request.start("object") + document.start(),
                request.start("object") + document.end(), "explicit_document_request")
    for action in _ACTION.finditer(text):
        add("ACTION_ITEM", action.start("item"), action.end("item"), "explicit_action_request")
    return {"method": "RULE_EXTRACTION_V1", "status": "REVIEW" if spans else "ABSTAIN",
            "spans": spans, "targets": {kind: [s for s in spans if s["type"] == kind] for kind in TARGETS},
            "human_gold": False, "review_required": True, "normalized_dates": {},
            "limitations": "Sparse exact-text cues only; unpopulated targets are unknown. No date resolution, inferred owners, or link/state reasoning."}

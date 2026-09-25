"""Locate exact text spans; reject missing or ambiguous matches."""

from __future__ import annotations


def locate_span(source: str, text: str, *, label: str, field: str = "current_message") -> dict:
    if not text:
        raise ValueError("span text must not be empty")
    starts = []
    cursor = 0
    while (index := source.find(text, cursor)) != -1:
        starts.append(index)
        cursor = index + 1
    if len(starts) != 1:
        raise ValueError(f"expected one exact match for {text!r}; found {len(starts)}")
    start = starts[0]
    return {"label": label, "text": text, "start": start, "end": start + len(text), "field": field}

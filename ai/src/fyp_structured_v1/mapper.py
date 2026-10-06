"""Deterministic derived FYP labels for Structured Schema V1."""

from __future__ import annotations

from typing import Any, Mapping

LABELS = (
    "MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT",
    "ACTION_REQUEST", "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE", "NON_PROJECT",
)
DERIVATION_VERSION = "fyp-derived-labels-1.1"
LEGACY_DERIVATION_VERSION = "fyp-derived-labels-1.0"


def _supported(value: Mapping[str, Any]) -> bool:
    return value.get("certainty") == "SUPPORTED"


def derive_labels(annotation: Any) -> list[str]:
    """Derive the nine legacy labels from V1 facts.

    Call validate_annotation first for complete source, role and reference checks.
    This mapper itself only fails closed for malformed top-level data, uncertain
    records, or any annotation marked for review. A supported NON_PROJECT decision
    returns only that label.
    """
    if not isinstance(annotation, dict) or annotation.get("schema_version") != "fyp-structured-v1":
        return []
    if annotation.get("needs_review") is not False or annotation.get("review_reasons") not in ([], ()):
        return []
    derivation_version = annotation.get("derived_label_version", LEGACY_DERIVATION_VERSION)
    if derivation_version not in {LEGACY_DERIVATION_VERSION, DERIVATION_VERSION}:
        return []
    scope = annotation.get("scope")
    if not isinstance(scope, dict):
        return []
    if scope.get("value") == "NON_PROJECT":
        if annotation.get("events") or annotation.get("event_span_links") or annotation.get("event_relations"):
            return []
        return ["NON_PROJECT"]
    if scope.get("value") != "PROJECT":
        return []
    events = annotation.get("events")
    links = annotation.get("event_span_links")
    relations = annotation.get("event_relations")
    spans = annotation.get("spans")
    if not all(isinstance(value, list) for value in (events, links, relations, spans)):
        return []
    if any(not isinstance(item, dict) or not _supported(item) for item in events + links + relations):
        return []
    by_id = {span.get("id"): span for span in spans if isinstance(span, dict)}
    event_by_id = {event.get("id"): event for event in events if isinstance(event, dict)}
    links_by_event: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        if link.get("event_id") not in event_by_id or link.get("span_id") not in by_id:
            return []
        links_by_event.setdefault(link["event_id"], []).append(link)
    emitted: set[str] = set()
    for event in events:
        kind = event.get("kind")
        state = event.get("state")
        event_links = links_by_event.get(event.get("id"), [])
        roles = {link.get("role") for link in event_links}
        if kind == "MEETING":
            emitted.add("MEETING")
        if kind in {"ACTION", "DOCUMENT"} and roles.intersection({"DUE_DATE", "DUE_TIME"}):
            emitted.add("DEADLINE")
        if kind == "DOCUMENT" and state == "requested" and event.get("document_class") == "PROJECT_DELIVERABLE":
            emitted.add("REPORT_REQUEST")
        if derivation_version == DERIVATION_VERSION and kind == "DOCUMENT" and state in {"submitted", "delivered", "missing", "reviewed"}:
            emitted.add("GENERAL_UPDATE")
        if kind == "ACTION":
            if event.get("action_class") == "OPERATIONAL" and state in {"requested", "assigned"}:
                emitted.add("ACTION_REQUEST")
            if derivation_version == DERIVATION_VERSION and state in {"completed", "cancelled"}:
                emitted.add("GENERAL_UPDATE")
            if event.get("action_class") == "DEPARTMENTAL_CONTRIBUTION":
                if any(
                    link.get("role") == "CONTRIBUTOR"
                    and by_id[link["span_id"]].get("type") == "ACTOR"
                    and by_id[link["span_id"]].get("actor_kind") == "DEPARTMENT"
                    for link in event_links
                ):
                    emitted.add("DEPARTMENTAL_INPUT")
        if kind == "APPROVAL":
            emitted.add("APPROVAL")
        if kind == "STATUS":
            emitted.add("GENERAL_UPDATE")
    for relation in relations:
        if relation.get("kind") == "FOLLOW_UP_OF" and relation.get("source_event_id") in event_by_id:
            if relation.get("target") is not None:
                emitted.add("FOLLOW_UP")
    return [label for label in LABELS if label in emitted]

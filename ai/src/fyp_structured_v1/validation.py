"""Validation for the FYP Structured Schema V1.

The contract is stored in ai/config/fyp_structured_v1_schema.json. Validation
uses jsonschema when installed and a dependency-free evaluator for the schema
subset used by that file otherwise. Source, context, role, provenance and
cross-record invariants are checked here because JSON Schema cannot express them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "fyp_structured_v1_schema.json"
SCHEMA: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VERSION = "fyp-structured-v1"

try:  # Optional acceleration; the fallback keeps offline use dependency-free.
    import jsonschema  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised in lean/offline installs
    jsonschema = None


@dataclass(frozen=True)
class ValidationResult:
    """Hard contract errors and non-fatal review warnings for one annotation."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    needs_review: bool

    @property
    def valid(self) -> bool:
        return not self.errors


def _pointer(root: Mapping[str, Any], ref: str) -> Any:
    value: Any = root
    for part in ref.removeprefix("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[part]
    return value


def _fallback_schema_errors(value: Any, rule: Mapping[str, Any], path: str = "$") -> list[str]:
    """Evaluate the JSON Schema keywords used by this contract without packages."""
    errors: list[str] = []
    if "$ref" in rule:
        try:
            # Draft 2020-12 applies sibling keywords alongside $ref. Keep
            # validating this rule after the referenced schema so constraints
            # such as minItems on evidence arrays are not silently skipped.
            errors.extend(_fallback_schema_errors(value, _pointer(SCHEMA, str(rule["$ref"])), path))
        except (KeyError, TypeError):
            return [f"{path}: unresolved schema reference {rule.get('$ref')!r}"]
    expected = rule.get("type")
    type_ok = True
    if expected == "object":
        type_ok = isinstance(value, dict)
    elif expected == "array":
        type_ok = isinstance(value, list)
    elif expected == "string":
        type_ok = isinstance(value, str)
    elif expected == "integer":
        type_ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "boolean":
        type_ok = isinstance(value, bool)
    elif expected == "null":
        type_ok = value is None
    if not type_ok:
        return [f"{path}: expected {expected}"]
    if "const" in rule and value != rule["const"]:
        errors.append(f"{path}: expected constant {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{path}: expected one of {rule['enum']!r}")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if rule.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError:
                errors.append(f"{path}: expected ISO date-time with timezone")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < rule.get("minimum", float("-inf")):
            errors.append(f"{path}: below minimum")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            errors.append(f"{path}: fewer items than minItems")
        if len(value) > rule.get("maxItems", float("inf")):
            errors.append(f"{path}: more items than maxItems")
        if rule.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}: items must be unique")
        item_rule = rule.get("items")
        if isinstance(item_rule, Mapping):
            for index, item in enumerate(value):
                errors.extend(_fallback_schema_errors(item, item_rule, f"{path}[{index}]"))
    if isinstance(value, dict):
        for key in rule.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        properties = rule.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_fallback_schema_errors(item, properties[key], f"{path}.{key}"))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key {key!r}")
    for branch in rule.get("allOf", []):
        errors.extend(_fallback_schema_errors(value, branch, path))
    for keyword in ("anyOf", "oneOf"):
        branches = rule.get(keyword)
        if branches:
            branch_errors = [_fallback_schema_errors(value, branch, path) for branch in branches]
            successes = sum(not branch_error for branch_error in branch_errors)
            if keyword == "anyOf" and successes == 0:
                errors.append(f"{path}: does not match any allowed schema")
            if keyword == "oneOf" and successes != 1:
                errors.append(f"{path}: must match exactly one schema")
    if "if" in rule:
        condition_matches = not _fallback_schema_errors(value, rule["if"], path)
        branch = rule.get("then") if condition_matches else rule.get("else")
        if isinstance(branch, Mapping):
            errors.extend(_fallback_schema_errors(value, branch, path))
    if "not" in rule and not _fallback_schema_errors(value, rule["not"], path):
        errors.append(f"{path}: matches a forbidden schema")
    return errors


def _schema_errors(annotation: Any) -> list[str]:
    if jsonschema is not None:
        validator = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
        errors = sorted(validator.iter_errors(annotation), key=lambda item: list(map(str, item.absolute_path)))
        return [
            "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
            + f": {error.message}"
            for error in errors
        ]
    return _fallback_schema_errors(annotation, SCHEMA)


def _context_event_index(context_annotations: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index actual earlier annotation records by (source_id, event_id).

    Accepted shapes are a mapping from source IDs to annotation records, or a
    sequence of records that each carry current_source_id.
    """
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    if context_annotations is None:
        return result
    if isinstance(context_annotations, Mapping):
        records = context_annotations.items()
    elif isinstance(context_annotations, (list, tuple)):
        records = ((None, item) for item in context_annotations)
    else:
        return result
    for source_key, record in records:
        if not isinstance(record, Mapping):
            continue
        source_id = record.get("current_source_id", source_key)
        if not isinstance(source_id, str) or not source_id:
            continue
        events = record.get("events", [])
        if isinstance(events, Mapping):
            events = list(events.values())
        if not isinstance(events, (list, tuple)):
            continue
        for event in events:
            if isinstance(event, Mapping) and isinstance(event.get("id"), str):
                result[(source_id, event["id"])] = event
    return result


def _valid_range(span_start: int, span_end: int, ranges: Any, body_length: int) -> bool:
    if not isinstance(ranges, list):
        return False
    valid_ranges = True
    covered = False
    for bounds in ranges:
        if not isinstance(bounds, Mapping) or set(bounds) != {"start", "end"}:
            valid_ranges = False
            continue
        start, end = bounds.get("start"), bounds.get("end")
        if (not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 0 or end < start or end > body_length):
            valid_ranges = False
            continue
        if start <= span_start and span_end <= end:
            covered = True
    return valid_ranges and covered


def _provenance_errors(provenance: Mapping[str, Any], *, evaluation: bool) -> list[str]:
    errors: list[str] = []
    origin = provenance.get("data_origin")
    tier = provenance.get("annotation_tier")
    mode = provenance.get("annotation_mode")
    ai = provenance.get("ai_assistance")
    review = provenance.get("human_review")
    annotator = provenance.get("annotator_id")
    annotated_at = provenance.get("annotated_at")
    blind = provenance.get("blind_prelabels_shown")

    if origin == "SYNTHETIC":
        if tier != "SYNTHETIC":
            errors.append("provenance: synthetic source must use annotation_tier SYNTHETIC")
        if not provenance.get("synthetic_case_id"):
            errors.append("provenance: synthetic source requires synthetic_case_id")
    elif provenance.get("synthetic_case_id") is not None:
        errors.append("provenance.synthetic_case_id: must be null for non-synthetic sources")
    if origin in {"REAL_EMAIL", "PUBLIC_CORPUS"}:
        if not isinstance(provenance.get("source_reference"), str) or not provenance["source_reference"].strip():
            errors.append("provenance.source_reference: real/public sources require a provenance reference")
    if tier == "GOLD":
        if origin not in {"REAL_EMAIL", "PUBLIC_CORPUS"}:
            errors.append("provenance: GOLD requires a real-email or public-corpus source")
        if mode not in {"BLIND_HUMAN", "AI_ASSISTED_HUMAN"}:
            errors.append("provenance: GOLD requires BLIND_HUMAN or AI_ASSISTED_HUMAN mode")
        if not isinstance(annotator, str) or not annotator.strip():
            errors.append("provenance: GOLD requires annotator_id")
        if not isinstance(annotated_at, str) or not annotated_at:
            errors.append("provenance: GOLD requires annotated_at")
        if not isinstance(review, Mapping):
            errors.append("provenance: GOLD requires explicit human_review")
        else:
            if not review.get("reviewer_id") or not review.get("reviewed_at"):
                errors.append("provenance.human_review: reviewer identity and reviewed_at are required for GOLD")
            if review.get("decision") == "rejected":
                errors.append("provenance.human_review: rejected annotation cannot be GOLD")
    if mode == "BLIND_HUMAN":
        if not isinstance(annotator, str) or not annotator.strip() or not annotated_at:
            errors.append("provenance: blind annotation requires annotator_id and annotated_at")
        if blind is not False:
            errors.append("provenance.blind_prelabels_shown: BLIND_HUMAN requires false")
        if ai is not None:
            errors.append("provenance.ai_assistance: blind annotation cannot contain AI assistance")
    elif mode == "AI_ASSISTED_HUMAN":
        if not isinstance(annotator, str) or not annotator.strip() or not annotated_at:
            errors.append("provenance: AI-assisted human annotation requires annotator_id and annotated_at")
        if blind is not True:
            errors.append("provenance.blind_prelabels_shown: AI_ASSISTED_HUMAN requires true")
        if not isinstance(ai, Mapping):
            errors.append("provenance.ai_assistance: AI-assisted annotation requires AI provenance")
        elif ai.get("human_disposition") not in {"accepted", "modified", "rejected"}:
            errors.append("provenance.ai_assistance.human_disposition: accepted/modified/rejected is required")
    elif mode == "AI_ONLY":
        if tier not in {"SILVER", "SYNTHETIC"}:
            errors.append("provenance: AI_ONLY annotation must be SILVER or SYNTHETIC")
        if not isinstance(ai, Mapping):
            errors.append("provenance.ai_assistance: AI_ONLY annotation requires model/run provenance")
        if review is not None:
            errors.append("provenance.human_review: AI_ONLY cannot claim human review")
        if annotator is not None or annotated_at is not None or blind is not None:
            errors.append("provenance: AI_ONLY cannot claim a human annotator or blind presentation")
    elif mode == "RULE_BASED":
        if tier != "SILVER":
            errors.append("provenance: RULE_BASED annotations must be SILVER")
        if ai is not None:
            errors.append("provenance.ai_assistance: RULE_BASED must not claim model assistance")
    elif mode == "UNANNOTATED":
        if tier != "UNSET" or annotator is not None or annotated_at is not None:
            errors.append("provenance: UNANNOTATED requires UNSET tier and null annotator/time")
        if review is not None or ai is not None or blind is not None:
            errors.append("provenance: UNANNOTATED cannot claim review, AI assistance or blind work")
    elif mode == "SYNTHETIC_GENERATION":
        if origin != "SYNTHETIC" or tier != "SYNTHETIC":
            errors.append("provenance: SYNTHETIC_GENERATION requires synthetic origin and tier")
    if evaluation:
        if tier != "GOLD":
            errors.append("evaluation: only human-reviewed GOLD annotations are allowed")
        if origin not in {"REAL_EMAIL", "PUBLIC_CORPUS"}:
            errors.append("evaluation: source must be real email or public corpus; synthetic/unknown is disallowed")
        if mode != "BLIND_HUMAN" or blind is not False:
            errors.append("evaluation: annotations must be blind with no AI prelabels")
        if not isinstance(review, Mapping):
            errors.append("evaluation: human review/adjudication provenance is required")
    return errors


def validate_annotation(
    annotation: Any,
    sources: Mapping[str, Mapping[str, Any]],
    context_annotations: Mapping[str, Any] | list[Any] | None = None,
    evaluation: bool = False,
) -> ValidationResult:
    """Validate one V1 record against exact sources and optional prior annotations.

    sources maps authentic source IDs to subject, current_message and explicit
    authored_ranges. Current-message spans always require authored_ranges; this API
    never assumes a body is quote-free. context_annotations maps prior source IDs
    to actual annotation records containing their events. Context IDs resolve
    against that map and the supplied sources; context text is never copied into
    this annotation's spans.

    Structural/reference violations are hard errors. Valid uncertainty is returned
    as warnings and needs_review=True. Callers should save the structured result
    and expose the review warning rather than converting it into a hard rejection.
    """
    if not isinstance(sources, Mapping):
        return ValidationResult(("sources: expected mapping from source ID to source record",), (), True)
    shape_errors = _schema_errors(annotation)
    if shape_errors:
        return ValidationResult(tuple(shape_errors), (), True)
    assert isinstance(annotation, dict)
    errors: list[str] = []
    warnings: list[str] = []
    current_source_id = annotation["current_source_id"]
    if current_source_id not in sources:
        errors.append(f"current_source_id {current_source_id!r} is absent from sources")
    current_source = sources.get(current_source_id)
    if not isinstance(current_source, Mapping):
        errors.append(f"sources[{current_source_id!r}]: expected current source record")

    spans = {item["id"]: item for item in annotation["spans"]}
    events = {item["id"]: item for item in annotation["events"]}
    relations = annotation["event_relations"]
    all_ids: dict[str, str] = {}
    for collection, items in (("spans", annotation["spans"]), ("events", annotation["events"]),
                              ("event_relations", relations)):
        for item in items:
            item_id = item["id"]
            if item_id in all_ids:
                errors.append(f"{collection}: duplicate ID {item_id!r} also used by {all_ids[item_id]}")
            else:
                all_ids[item_id] = collection

    span_coordinates: dict[tuple[Any, ...], str] = {}
    for index, span in enumerate(annotation["spans"]):
        coordinate = (span["source_id"], span["field"], span["type"], span["start"], span["end"])
        previous_span_id = span_coordinates.get(coordinate)
        if previous_span_id is not None:
            errors.append(
                f"spans[{index}]: duplicates span coordinates from {previous_span_id!r}; "
                "reuse one span ID and link it to each event"
            )
        else:
            span_coordinates[coordinate] = span["id"]

    # Exact source slices and mandatory authored ranges.
    for index, span in enumerate(annotation["spans"]):
        path = f"spans[{index}]"
        if span["source_id"] != current_source_id:
            errors.append(f"{path}.source_id: spans must refer to current_source_id")
            continue
        source = sources.get(span["source_id"])
        if not isinstance(source, Mapping):
            continue
        source_text = source.get(span["field"])
        if not isinstance(source_text, str):
            errors.append(f"sources[{span['source_id']!r}].{span['field']}: expected source string")
            continue
        start, end = span["start"], span["end"]
        if end > len(source_text) or source_text[start:end] != span["text"]:
            errors.append(f"{path}: text must equal exact source slice [{start}:{end}]")
        if span["field"] == "current_message":
            body = source.get("current_message")
            ranges = source.get("authored_ranges")
            if not isinstance(body, str) or not isinstance(ranges, list):
                errors.append(f"sources[{span['source_id']!r}].authored_ranges: required for current-message evidence")
            elif not _valid_range(start, end, ranges, len(body)):
                errors.append(f"{path}: current-message span is outside valid authored_ranges")

    scope = annotation["scope"]
    for span_id in scope["evidence_span_ids"]:
        if span_id not in spans:
            errors.append(f"scope.evidence_span_ids: unknown span_id {span_id!r}")
        elif spans[span_id]["source_id"] != current_source_id:
            errors.append(f"scope.evidence_span_ids: span {span_id!r} must refer to current_source_id")

    role_types = SCHEMA["x-semantics"]["role_types"]
    role_actor_kind = SCHEMA["x-semantics"].get("role_actor_kind", {})
    role_event_kinds = SCHEMA["x-semantics"]["role_event_kinds"]
    required_roles = SCHEMA["x-semantics"]["required_event_roles"]
    links_by_event: dict[str, list[Mapping[str, Any]]] = {event_id: [] for event_id in events}
    link_keys: set[tuple[str, str, str]] = set()
    for index, link in enumerate(annotation["event_span_links"]):
        path = f"event_span_links[{index}]"
        event_id, span_id, role = link["event_id"], link["span_id"], link["role"]
        event = events.get(event_id)
        span = spans.get(span_id)
        if event is None:
            errors.append(f"{path}.event_id: unknown event ID {event_id!r}")
            continue
        if span is None:
            errors.append(f"{path}.span_id: unknown span ID {span_id!r}")
            continue
        key = (event_id, span_id, role)
        if key in link_keys:
            errors.append(f"{path}: duplicate event-span-role link {key!r}")
        link_keys.add(key)
        links_by_event[event_id].append(link)
        if span["type"] not in role_types[role]:
            errors.append(f"{path}: role {role} is incompatible with span type {span['type']}")
        if event["kind"] not in role_event_kinds[role]:
            errors.append(f"{path}: role {role} is incompatible with event kind {event['kind']}")
        allowed_actor_kinds = role_actor_kind.get(role)
        if allowed_actor_kinds and span.get("actor_kind") not in allowed_actor_kinds:
            errors.append(f"{path}: role {role} requires actor_kind in {allowed_actor_kinds!r}")
        if role == "EVENT_ANCHOR":
            if (span["type"] != "EVENT_TRIGGER" or span["field"] != "current_message"
                    or span["source_id"] != current_source_id):
                errors.append(f"{path}: EVENT_ANCHOR must link a current-message EVENT_TRIGGER")
            if span["field"] == "current_message":
                source = sources.get(span["source_id"], {})
                if isinstance(source, Mapping) and isinstance(source.get("authored_ranges"), list):
                    if not _valid_range(span["start"], span["end"], source["authored_ranges"], len(source.get("current_message", ""))):
                        errors.append(f"{path}: EVENT_ANCHOR must be inside an authored range")
    for event_id, event in events.items():
        have = {link["role"] for link in links_by_event[event_id]}
        missing = set(required_roles[event["kind"]]) - have
        if missing:
            errors.append(f"events[{event_id!r}]: missing required event-span roles {sorted(missing)!r}")

    context_index = _context_event_index(context_annotations)
    seen_relations: set[tuple[Any, ...]] = set()
    for index, relation in enumerate(relations):
        path = f"event_relations[{index}]"
        source_event = events.get(relation["source_event_id"])
        if source_event is None:
            errors.append(f"{path}.source_event_id: unknown current event")
            continue
        evidence = [spans.get(item_id) for item_id in relation["evidence_span_ids"]]
        if any(span is None for span in evidence):
            errors.append(f"{path}.evidence_span_ids: unknown span ID")
        elif any(span["source_id"] != current_source_id or span["field"] != "current_message" for span in evidence):
            errors.append(f"{path}.evidence_span_ids: relation evidence must be current-message spans")
        anchor_ids = {
            link["span_id"] for link in links_by_event.get(source_event["id"], [])
            if link["role"] == "EVENT_ANCHOR"
        }
        if not anchor_ids.intersection(relation["evidence_span_ids"]):
            errors.append(f"{path}: relation evidence must include its current event anchor")
        target = relation["target"]
        if relation["kind"] == "SUPERSEDES" and target is None:
            errors.append(f"{path}.target: SUPERSEDES requires an actual prior event reference")
        if target is None:
            if relation["kind"] != "FOLLOW_UP_OF":
                errors.append(f"{path}.target: only FOLLOW_UP_OF may have a null target")
            else:
                if not annotation["needs_review"]:
                    errors.append(f"{path}: unresolved FOLLOW_UP_OF requires needs_review=true")
                warnings.append(f"{path}: explicit follow-up has no resolved prior event")
        else:
            target_source, target_event_id = target["source_id"], target["event_id"]
            key = (relation["source_event_id"], relation["kind"], target_source, target_event_id)
            if key in seen_relations:
                errors.append(f"{path}: duplicate event relation {key!r}")
            seen_relations.add(key)
            if target_source == current_source_id:
                errors.append(f"{path}.target.source_id: context target must be an earlier source")
            if target_source not in sources:
                errors.append(f"{path}.target.source_id: source is absent from supplied sources")
            prior_event = context_index.get((target_source, target_event_id))
            if prior_event is None:
                errors.append(f"{path}.target: prior event does not resolve in context_annotations")
            elif relation["kind"] == "SUPERSEDES" and prior_event.get("kind") != source_event.get("kind"):
                errors.append(f"{path}.target: SUPERSEDES must target a prior event of the same kind")

    reasons: list[str] = []
    if scope["value"] == "UNCERTAIN":
        reasons.append("scope_uncertain")
    for event in annotation["events"]:
        if event["certainty"] == "UNCERTAIN":
            reasons.append(f"event_uncertain:{event['id']}")
        if event.get("action_class") in SCHEMA["x-semantics"]["review_classes"]["action_class"]:
            reasons.append(f"action_class_review:{event['id']}")
        if event.get("document_class") in SCHEMA["x-semantics"]["review_classes"]["document_class"]:
            reasons.append(f"document_class_review:{event['id']}")
    for index, link in enumerate(annotation["event_span_links"]):
        if link["certainty"] == "UNCERTAIN":
            reasons.append(f"event_span_link_uncertain:{index}")
    for index, relation in enumerate(relations):
        if relation["certainty"] == "UNCERTAIN":
            reasons.append(f"event_relation_uncertain:{index}")
    if reasons and not annotation["needs_review"]:
        errors.append("needs_review: true is required for uncertain scope/events/links/relations and OTHER/UNCERTAIN classes")
    if annotation["needs_review"]:
        warnings.extend(["needs_review: " + reason for reason in annotation["review_reasons"]])
        if not annotation["review_reasons"]:
            errors.append("review_reasons: needs_review=true requires at least one reason")
    if annotation["review_reasons"] and not annotation["needs_review"]:
        errors.append("review_reasons: non-empty reasons require needs_review=true")

    if scope["value"] == "NON_PROJECT":
        if annotation["events"] or annotation["event_span_links"] or relations:
            errors.append("NON_PROJECT is exclusive and cannot contain events, event-span links, or event relations")
    errors.extend(_provenance_errors(annotation["provenance"], evaluation=evaluation))
    needs_review = bool(annotation["needs_review"] or reasons or warnings)
    return ValidationResult(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)), needs_review)

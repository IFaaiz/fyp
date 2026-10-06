"""Source-grounded validation for directly assigned FYP labels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "fyp_direct_label_v1_schema.json"
SCHEMA: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VERSION = "fyp-direct-label-v1"
LABELS = tuple(SCHEMA["x-semantics"]["labels"])
PROJECT_LABELS = tuple(SCHEMA["x-semantics"]["project_labels"])
SPAN_TYPES = tuple(SCHEMA["x-semantics"]["span_types"])
_REQUIRED_FIELDS = SCHEMA["x-semantics"]["required_fields"]
_ALLOWED_FIELD_TYPES = SCHEMA["x-semantics"]["allowed_field_types"]
_FOLLOW_UP_TARGETS = set(SCHEMA["x-semantics"]["follow_up_targets"])

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional in lean/offline installations
    jsonschema = None


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    needs_review: bool

    @property
    def valid(self) -> bool:
        return not self.errors


def _schema_errors(annotation: Any) -> list[str]:
    if jsonschema is not None:
        validator = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
        errors = sorted(validator.iter_errors(annotation), key=lambda error: list(map(str, error.absolute_path)))
        return [
            "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
            + f": {error.message}"
            for error in errors
        ]
    return _fallback_schema_errors(annotation, SCHEMA)


def _fallback_schema_errors(value: Any, rule: Mapping[str, Any], path: str = "$") -> list[str]:
    """Small dependency-free evaluator for the schema keywords used here."""
    errors: list[str] = []
    if rule is True:
        return []
    if rule is False:
        return [f"{path}: forbidden"]
    if "$ref" in rule:
        target: Any = SCHEMA
        try:
            for part in str(rule["$ref"]).removeprefix("#/").split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            return [f"{path}: unresolved $ref"]
        errors.extend(_fallback_schema_errors(value, target, path))
    expected = rule.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        matches = any(
            (kind == "object" and isinstance(value, dict))
            or (kind == "array" and isinstance(value, list))
            or (kind == "string" and isinstance(value, str))
            or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (kind == "boolean" and isinstance(value, bool))
            or (kind == "null" and value is None)
            for kind in choices
        )
        if not matches:
            return errors + [f"{path}: expected {expected}"]
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
                errors.append(f"{path}: invalid date-time")
    if isinstance(value, int) and not isinstance(value, bool) and value < rule.get("minimum", value):
        errors.append(f"{path}: below minimum")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            errors.append(f"{path}: fewer items than minItems")
        if rule.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            errors.append(f"{path}: duplicate items")
        if "items" in rule:
            errors.extend(item_error for index, item in enumerate(value)
                          for item_error in _fallback_schema_errors(item, rule["items"], f"{path}[{index}]"))
    if isinstance(value, dict):
        for key in rule.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, item in value.items():
            if key in rule.get("properties", {}):
                errors.extend(_fallback_schema_errors(item, rule["properties"][key], f"{path}.{key}"))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: additional property")
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in rule:
            continue
        results = [_fallback_schema_errors(value, child, path) for child in rule[keyword]]
        successes = sum(not result for result in results)
        if keyword == "allOf":
            errors.extend(error for result in results for error in result)
        elif keyword == "anyOf" and successes == 0:
            errors.append(f"{path}: does not match any allowed schema")
        elif keyword == "oneOf" and successes != 1:
            errors.append(f"{path}: must match exactly one allowed schema")
    if "not" in rule and not _fallback_schema_errors(value, rule["not"], path):
        errors.append(f"{path}: matches a forbidden schema")
    if "if" in rule:
        branch = rule.get("then") if not _fallback_schema_errors(value, rule["if"], path) else rule.get("else")
        if isinstance(branch, Mapping):
            errors.extend(_fallback_schema_errors(value, branch, path))
    return errors


def _range_covers(start: int, end: int, source: Mapping[str, Any], body_length: int) -> bool:
    ranges = source.get("authored_ranges")
    if not isinstance(ranges, list):
        return False
    covered = False
    for bounds in ranges:
        if not isinstance(bounds, Mapping) or set(bounds) != {"start", "end"}:
            return False
        left, right = bounds.get("start"), bounds.get("end")
        if (not isinstance(left, int) or isinstance(left, bool) or not isinstance(right, int)
                or isinstance(right, bool) or left < 0 or right < left or right > body_length):
            return False
        if left <= start and end <= right:
            covered = True
    return covered


def _provenance_errors(provenance: Mapping[str, Any], source: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    origin = source.get("data_origin") or "UNKNOWN"
    tier, mode = provenance.get("annotation_tier"), provenance.get("annotation_mode")
    ai, review = provenance.get("ai_assistance"), provenance.get("human_review")
    annotator, at, blind = provenance.get("annotator_id"), provenance.get("annotated_at"), provenance.get("blind_prelabels_shown")
    expected_reference = source.get("source_id") if origin in {"REAL_EMAIL", "PUBLIC_CORPUS"} else None
    expected_synthetic_id = (source.get("synthetic_case_id") or source.get("source_id")) if origin == "SYNTHETIC" else None
    if provenance.get("data_origin") != origin:
        errors.append("provenance.data_origin: must match source")
    if provenance.get("source_reference") != expected_reference:
        errors.append("provenance.source_reference: must be server-stamped from the source")
    if provenance.get("synthetic_case_id") != expected_synthetic_id:
        errors.append("provenance.synthetic_case_id: must match source provenance")
    if origin == "SYNTHETIC":
        if tier != "SYNTHETIC":
            errors.append("provenance: synthetic examples must keep SYNTHETIC provenance")
        if not provenance.get("synthetic_case_id"):
            errors.append("provenance: synthetic examples require a case ID")
    if tier == "GOLD":
        if origin not in {"REAL_EMAIL", "PUBLIC_CORPUS"}:
            errors.append("provenance: GOLD requires a real or public source")
        if mode not in {"BLIND_HUMAN", "AI_ASSISTED_HUMAN"}:
            errors.append("provenance: GOLD requires human annotation")
        if not isinstance(annotator, str) or not annotator.strip() or not at:
            errors.append("provenance: GOLD requires annotator identity and time")
        if not isinstance(review, Mapping):
            errors.append("provenance: GOLD requires separate human review")
        else:
            if not review.get("reviewer_id") or not review.get("reviewed_at"):
                errors.append("provenance.human_review: reviewer identity and time are required")
            elif review.get("reviewer_id") == annotator:
                errors.append("provenance.human_review: GOLD review must be completed by a different person")
            if review.get("decision") == "rejected":
                errors.append("provenance.human_review: rejected annotation cannot be GOLD")
        if mode == "AI_ONLY" or origin == "SYNTHETIC":
            errors.append("provenance: AI-only or synthetic annotations cannot be GOLD")
    if mode == "BLIND_HUMAN":
        if not isinstance(annotator, str) or not annotator.strip() or not at:
            errors.append("provenance: blind human annotation requires identity and time")
        if blind is not False:
            errors.append("provenance.blind_prelabels_shown: BLIND_HUMAN requires false")
        if ai is not None:
            errors.append("provenance.ai_assistance: blind human annotation cannot include AI assistance")
    elif mode == "AI_ASSISTED_HUMAN":
        if not isinstance(annotator, str) or not annotator.strip() or not at:
            errors.append("provenance: AI-assisted human annotation requires identity and time")
        if blind is not True:
            errors.append("provenance.blind_prelabels_shown: AI_ASSISTED_HUMAN requires true")
        if not isinstance(ai, Mapping) or ai.get("human_disposition") not in {"accepted", "modified", "rejected"}:
            errors.append("provenance.ai_assistance: AI-assisted annotation needs model/run details and disposition")
    elif mode == "AI_ONLY":
        if tier not in {"SILVER", "SYNTHETIC"}:
            errors.append("provenance: AI_ONLY must stay SILVER or SYNTHETIC")
        if not isinstance(ai, Mapping):
            errors.append("provenance.ai_assistance: AI_ONLY needs model/run details")
        if review is not None or annotator is not None or at is not None or blind is not None:
            errors.append("provenance: AI_ONLY cannot claim human review or presentation")
    elif mode == "RULE_BASED":
        if tier != "SILVER":
            errors.append("provenance: RULE_BASED must stay SILVER")
        if ai is not None:
            errors.append("provenance.ai_assistance: RULE_BASED cannot claim model assistance")
    elif mode == "UNANNOTATED":
        if tier != "UNSET" or annotator is not None or at is not None:
            errors.append("provenance: UNANNOTATED must stay UNSET and have no human identity or time")
        if review is not None or ai is not None or blind is not None:
            errors.append("provenance: UNANNOTATED cannot claim review, AI assistance or blind work")
    elif mode == "SYNTHETIC_GENERATION" and (origin != "SYNTHETIC" or tier != "SYNTHETIC"):
        errors.append("provenance: SYNTHETIC_GENERATION requires synthetic origin and tier")
    return errors


def validate_annotation(annotation: Any, source: Mapping[str, Any], *, evaluation: bool = False) -> ValidationResult:
    """Validate a direct-label annotation against its exact current source."""
    if not isinstance(source, Mapping):
        return ValidationResult(("source: expected a source record mapping",), (), True)
    shape_errors = _schema_errors(annotation)
    if shape_errors:
        return ValidationResult(tuple(shape_errors[:30]), (), True)
    assert isinstance(annotation, dict)
    errors: list[str] = []
    warnings: list[str] = []
    source_id = source.get("source_id")
    if annotation["current_source_id"] != source_id or annotation["record_id"] != source_id:
        errors.append("record_id/current_source_id: must match the current source")

    spans = {item["id"]: item for item in annotation["spans"]}
    used_ids: set[str] = set()
    coordinates: dict[tuple[Any, ...], str] = {}
    for index, span in enumerate(annotation["spans"]):
        path = f"spans[{index}]"
        if span["id"] in used_ids:
            errors.append(f"{path}.id: duplicate span ID {span['id']!r}")
        used_ids.add(span["id"])
        coordinate = (span["field"], span["type"], span["start"], span["end"])
        if coordinate in coordinates:
            errors.append(f"{path}: duplicate span coordinates; reuse the existing span")
        coordinates[coordinate] = span["id"]
        text = source.get(span["field"])
        if not isinstance(text, str):
            errors.append(f"{path}.field: source field is unavailable")
            continue
        if span["end"] <= span["start"] or span["end"] > len(text) or text[span["start"]:span["end"]] != span["text"]:
            errors.append(f"{path}: text/offsets must exactly match the source using Unicode code points")
        if span["field"] == "current_message" and not _range_covers(span["start"], span["end"], source, len(text)):
            errors.append(f"{path}: current-message span must lie within authored_ranges")

    def references(ids: list[str], allowed_types: set[str] | None, path: str) -> set[str]:
        referenced: set[str] = set()
        for item_id in ids:
            span = spans.get(item_id)
            if span is None:
                errors.append(f"{path}: unknown span ID {item_id!r}")
                continue
            referenced.add(item_id)
            if allowed_types is not None and span["type"] not in allowed_types:
                errors.append(f"{path}: span type {span['type']} is incompatible")
        return referenced

    used_spans = references(annotation["scope"]["evidence_span_ids"], {"EVIDENCE"}, "scope.evidence_span_ids")
    scope = annotation["scope"]
    labels = annotation["labels"]
    support_rows = annotation["label_support"]
    if scope["value"] == "UNCERTAIN":
        if not scope["reason"].strip():
            errors.append("scope.reason: uncertain scope requires a reason")
        if not annotation["needs_review"] or not annotation["review_reasons"]:
            errors.append("scope: UNCERTAIN requires needs_review and a review reason")
        if labels or support_rows:
            errors.append("scope: UNCERTAIN cannot have labels or label support")
        if any(span["type"] != "EVIDENCE" for span in annotation["spans"]):
            errors.append("scope: UNCERTAIN may contain only scope EVIDENCE spans")
        if set(spans) != used_spans:
            errors.append("scope: UNCERTAIN spans must all be referenced by scope evidence")
    elif scope["value"] == "NON_PROJECT":
        if labels != ["NON_PROJECT"]:
            errors.append("labels: NON_PROJECT scope must have only the NON_PROJECT label")
        if support_rows:
            errors.append("label_support: NON_PROJECT cannot have project label support")
        if any(span["type"] != "EVIDENCE" for span in annotation["spans"]):
            errors.append("spans: NON_PROJECT may contain only scope EVIDENCE spans")
        if set(spans) != used_spans:
            errors.append("spans: NON_PROJECT evidence must be referenced by scope")
    elif "NON_PROJECT" in labels:
        errors.append("labels: NON_PROJECT is exclusive and requires NON_PROJECT scope")

    support_by_label: dict[str, Mapping[str, Any]] = {}
    support_review = False
    for index, support in enumerate(support_rows):
        path = f"label_support[{index}]"
        label = support["label"]
        if label in support_by_label:
            errors.append(f"{path}.label: duplicate support row for {label}")
        support_by_label[label] = support
        allowed = set(_ALLOWED_FIELD_TYPES[label])
        evidence_ids = references(support["evidence_span_ids"], {"EVIDENCE"}, f"{path}.evidence_span_ids")
        field_ids = references(support["field_span_ids"], allowed, f"{path}.field_span_ids")
        used_spans |= evidence_ids | field_ids
        if not any(spans[item_id]["field"] == "current_message" for item_id in evidence_ids if item_id in spans):
            errors.append(f"{path}.evidence_span_ids: requires a current_message EVIDENCE trigger")
        if label == "FOLLOW_UP":
            target = support["follow_up_target"]
            if target not in _FOLLOW_UP_TARGETS:
                errors.append(f"{path}.follow_up_target: FOLLOW_UP requires a valid target")
            if target == "UNCLEAR" and not support["review_reason"].strip():
                errors.append(f"{path}.review_reason: UNCLEAR target requires a review reason")
        elif support["follow_up_target"] is not None:
            errors.append(f"{path}.follow_up_target: only FOLLOW_UP may set a target")
        actual_types = {spans[item_id]["type"] for item_id in field_ids if item_id in spans}
        missing = []
        for requirement in _REQUIRED_FIELDS[label]:
            if isinstance(requirement, list):
                if not actual_types.intersection(requirement):
                    missing.append(" or ".join(requirement))
            elif requirement == "applies_to":
                if not support["applies_to"].strip():
                    missing.append(requirement)
            elif requirement == "follow_up_target":
                if support["follow_up_target"] not in _FOLLOW_UP_TARGETS:
                    missing.append(requirement)
            elif requirement not in actual_types:
                missing.append(requirement)
        row_reason = support["review_reason"].strip()
        if missing and not row_reason:
            errors.append(f"{path}: missing required fields {missing!r}; explain any waiver in review_reason")
        if (missing and row_reason) or row_reason:
            support_review = True
            if not annotation["needs_review"] or not annotation["review_reasons"]:
                errors.append(f"{path}: field waiver/review reason requires needs_review and a global review reason")

    for label in labels:
        if label == "NON_PROJECT":
            continue
        if label not in support_by_label:
            errors.append(f"label_support: selected label {label} needs one support row")
    for label in support_by_label:
        if label not in labels:
            errors.append(f"label_support: {label} is not a selected label")
    if scope["value"] == "PROJECT" and not labels and (not annotation["needs_review"] or not annotation["review_reasons"]):
        errors.append("labels: a PROJECT record with no selected labels requires review and a reason")
    for span_id in spans:
        if span_id not in used_spans:
            errors.append(f"spans: orphan span {span_id!r}")

    if annotation["needs_review"] and not annotation["review_reasons"]:
        errors.append("review_reasons: needs_review=true requires at least one reason")
    if not annotation["needs_review"] and annotation["review_reasons"]:
        errors.append("review_reasons: non-empty reasons require needs_review=true")
    errors.extend(_provenance_errors(annotation["provenance"], source))
    if evaluation:
        provenance = annotation["provenance"]
        if provenance["annotation_tier"] != "GOLD":
            errors.append("evaluation: only human-reviewed GOLD records are allowed")
        if provenance["data_origin"] not in {"REAL_EMAIL", "PUBLIC_CORPUS"}:
            errors.append("evaluation: source must be real email or public corpus")
        if provenance["annotation_mode"] != "BLIND_HUMAN" or provenance["blind_prelabels_shown"] is not False:
            errors.append("evaluation: annotations must be blind with no AI prelabels")
        if not isinstance(provenance["human_review"], Mapping):
            errors.append("evaluation: separate human review/adjudication is required")
    if annotation["provenance"]["annotation_tier"] == "GOLD" and (annotation["needs_review"] or scope["value"] == "UNCERTAIN"):
        errors.append("provenance: unresolved or needs-review annotations cannot be GOLD")
    if support_review:
        warnings.append("One or more label rows need review.")
    return ValidationResult(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)), bool(annotation["needs_review"] or warnings))

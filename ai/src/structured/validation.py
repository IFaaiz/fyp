"""Strict structural and source-evidence validation for schema v2-alpha."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "2-alpha"

ENUMS: dict[str, set[str]] = {
    "scope": {"PROJECT", "NON_PROJECT", "UNCERTAIN"},
    "confidence": {"supported", "uncertain"},
    "evidence_field": {"subject", "current_message"},
    "actor_kind": {"PERSON", "GROUP", "DEPARTMENT", "ROLE", "UNKNOWN"},
    "action_state": {"requested", "assigned", "committed", "completed", "cancelled"},
    "action_category": {"OPERATIONAL", "DOCUMENT_TRANSFER", "DEPARTMENTAL_CONTRIBUTION", "APPROVAL_TRANSACTION", "OTHER", "UNCERTAIN"},
    "document_state": {"requested", "expected", "submitted", "delivered", "missing", "reviewed", "unknown"},
    "document_type": {"PROJECT_DELIVERABLE", "OTHER", "UNCERTAIN"},
    "target_formality": {"PROJECT_DELIVERABLE", "OTHER", "UNCERTAIN", "NOT_APPLICABLE"},
    "department_role": {"contributor", "owner", "recipient", "mention_only"},
    "temporal_kind": {"DATE", "TIME"},
    "meeting_state": {"proposed", "scheduled", "rescheduled", "cancelled", "completed"},
    "approval_state": {"requested", "granted", "rejected", "withheld", "conditional"},
    "approval_formality": {"FORMAL", "INFORMAL", "UNCERTAIN"},
    "approval_target_type": {"ACTION", "DOCUMENT", "PROJECT", "IMPLICIT"},
    "status_kind": {"progress", "completed", "blocker", "decision", "work_state_change", "other"},
    "thread_change_kind": {
        "current_chase", "escalation", "future_follow_up_instruction",
        "deadline_changed", "owner_changed", "document_missing",
        "document_delivered", "meeting_rescheduled", "meeting_cancelled", "other",
    },
    "prior_expectation": {"explicit_current", "context", "unknown", "not_applicable"},
    "speech_act": {
        "REQUEST", "INFORM", "COMMIT", "APPROVE", "REJECT", "DELIVER",
        "PROPOSE", "REMIND", "SCHEDULE", "CANCEL", "RESCHEDULE",
    },
    "target_type": {
        "ACTION", "DOCUMENT", "DEPARTMENT", "MEETING", "DEADLINE",
        "APPROVAL", "STATUS_UPDATE", "THREAD_CHANGE", "IMPLICIT", "NONE",
    },
    "thread_target_type": {"ACTION", "DOCUMENT", "DEPARTMENT", "MEETING", "APPROVAL", "IMPLICIT"},
    "deadline_target_type": {"ACTION", "DOCUMENT"},
}


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _obj(value: Any, path: str, required: set[str], optional: set[str], errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return False
    missing = required - value.keys()
    extra = value.keys() - required - optional
    for key in sorted(missing, key=str):
        errors.append(f"{path}: missing required key {key!r}")
    for key in sorted(extra, key=str):
        errors.append(f"{path}: unknown key {key!r}")
    return not missing and not extra


def _string(value: Any, path: str, errors: list[str], *, allow_empty: bool = False) -> bool:
    good = isinstance(value, str) and (allow_empty or bool(value.strip()))
    if not good:
        errors.append(f"{path}: expected {'string' if allow_empty else 'non-empty string'}")
    return good


def _enum(value: Any, enum_name: str, path: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or value not in ENUMS[enum_name]:
        errors.append(f"{path}: expected one of {sorted(ENUMS[enum_name])!r}")
        return False
    return True


def _list(value: Any, path: str, errors: list[str], *, nonempty: bool = False) -> bool:
    if not isinstance(value, list):
        errors.append(f"{path}: expected array")
        return False
    if nonempty and not value:
        errors.append(f"{path}: must not be empty")
        return False
    return True


def _id_refs(value: Any, path: str, known_ids: set[str], errors: list[str], *, nonempty: bool = False) -> list[str]:
    if not _list(value, path, errors, nonempty=nonempty):
        return []
    refs: list[str] = []
    for i, ref in enumerate(value):
        p = f"{path}[{i}]"
        if _string(ref, p, errors):
            refs.append(ref)
            if ref not in known_ids:
                errors.append(f"{p}: unknown reference {ref!r}")
    if len(refs) != len(set(refs)):
        errors.append(f"{path}: duplicate references are not allowed")
    return refs


def _unique_items(items: Any, name: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        errors.append(f"{name}: expected array")
        return result
    for i, item in enumerate(items):
        path = f"{name}[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: expected object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            errors.append(f"{path}.id: expected non-empty string")
            continue
        if item_id in result:
            errors.append(f"{path}.id: duplicate id {item_id!r}")
        else:
            result[item_id] = item
    return result


def _validate_evidence(annotation: dict[str, Any], current_source_id: str,
                       sources: Mapping[str, Mapping[str, Any]], errors: list[str]) -> dict[str, dict[str, Any]]:
    evidence = _unique_items(annotation.get("evidence"), "evidence", errors)
    for i, item in enumerate(evidence.values()):
        path = f"evidence[{i}]"
        if not _obj(item, path, {"id", "source_id", "field", "start", "end", "text"}, set(), errors):
            continue
        source_id, field = item.get("source_id"), item.get("field")
        if not _string(source_id, f"{path}.source_id", errors):
            continue
        if not _enum(field, "evidence_field", f"{path}.field", errors):
            continue
        start, end = item.get("start"), item.get("end")
        if not _is_int(start) or not _is_int(end):
            errors.append(f"{path}: start/end must be integer Python Unicode code-point offsets")
            continue
        if start < 0 or end <= start:
            errors.append(f"{path}: expected 0 <= start < end")
            continue
        if source_id not in sources:
            errors.append(f"{path}: source_id {source_id!r} is absent from sources")
            continue
        source = sources[source_id]
        if not isinstance(source, Mapping):
            errors.append(f"sources[{source_id!r}]: expected object")
            continue
        text_field = "subject" if field == "subject" else "current_message"
        content = source.get(text_field)
        if not isinstance(content, str):
            errors.append(f"sources[{source_id!r}].{text_field}: expected source string")
            continue
        if end > len(content):
            errors.append(f"{path}: end offset exceeds {text_field} length {len(content)}")
            continue
        actual = content[start:end]
        if item.get("text") != actual:
            errors.append(f"{path}: text does not equal sources[{source_id!r}].{text_field}[{start}:{end}]")
        if source_id == current_source_id and field == "current_message":
            authored_ranges = source.get("authored_ranges")
            if authored_ranges is not None:
                if not isinstance(authored_ranges, list):
                    errors.append(f"sources[{source_id!r}].authored_ranges: expected array of ranges")
                else:
                    covered = False
                    for j, bounds in enumerate(authored_ranges):
                        if not isinstance(bounds, Mapping):
                            errors.append(f"sources[{source_id!r}].authored_ranges[{j}]: expected object")
                            continue
                        if set(bounds) != {"start", "end"}:
                            errors.append(f"sources[{source_id!r}].authored_ranges[{j}]: expected only start/end")
                        a, b = bounds.get("start"), bounds.get("end")
                        if not _is_int(a) or not _is_int(b) or a < 0 or b < a or b > len(content):
                            errors.append(f"sources[{source_id!r}].authored_ranges[{j}]: invalid Python code-point range")
                            continue
                        if a <= start and end <= b:
                            covered = True
                    if not covered:
                        errors.append(f"{path}: current evidence is outside authored_ranges (for example, quoted text)")
            # If authored_ranges is absent, the caller contract is that the supplied
            # current_message contains only current-authored text; no quote heuristic is applied.
    return evidence


def validate_annotation(annotation: Any, *, current_source_id: str,
                        sources: Mapping[str, Mapping[str, Any]]) -> ValidationResult:
    """Validate shape, IDs, exact evidence slices, and cross-field relations.

    ``sources`` maps each authentic source message ID to its exact ``subject`` and
    ``current_message`` strings. If a source's current_message includes quoted
    material, pass ``authored_ranges`` (exclusive-end Python code-point ranges).
    Without authored_ranges, the caller asserts that current_message is already
    authored-only; this function never guesses quote boundaries.
    """
    errors: list[str] = []
    if not isinstance(sources, Mapping):
        return ValidationResult(("sources: expected mapping of source IDs to source text",))
    if not _string(current_source_id, "current_source_id", errors):
        current_source_id = ""
    if current_source_id not in sources:
        errors.append(f"current_source_id {current_source_id!r} is absent from sources")
    top_required = {
        "schema_version", "email_id", "current_source_id", "project_scope", "evidence",
        "actors", "actions", "documents", "departments", "temporal_entities", "meetings",
        "deadlines", "approvals", "status_updates", "thread_changes", "acts",
        "needs_review", "uncertainty_reasons",
    }
    if not _obj(annotation, "annotation", top_required, set(), errors):
        return ValidationResult(tuple(errors))
    if annotation.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: expected {SCHEMA_VERSION!r}")
    _string(annotation.get("email_id"), "email_id", errors)
    if annotation.get("current_source_id") != current_source_id:
        errors.append("current_source_id: must match the explicit current_source_id argument")
    if not isinstance(annotation.get("needs_review"), bool):
        errors.append("needs_review: expected boolean")
    reasons = annotation.get("uncertainty_reasons")
    if _list(reasons, "uncertainty_reasons", errors):
        for i, reason in enumerate(reasons):
            _string(reason, f"uncertainty_reasons[{i}]", errors)

    scope = annotation.get("project_scope")
    if _obj(scope, "project_scope", {"value", "confidence", "evidence_ids"}, set(), errors):
        _enum(scope.get("value"), "scope", "project_scope.value", errors)
        _enum(scope.get("confidence"), "confidence", "project_scope.confidence", errors)

    evidence = _validate_evidence(annotation, current_source_id, sources, errors)
    evidence_ids = set(evidence)

    collection_specs = {
        "actors": ({"id", "kind", "named", "name_evidence_ids", "evidence_ids", "confidence"}, {"kind": "actor_kind"}),
        "actions": ({"id", "state", "category", "evidence_ids", "actor_id", "confidence"}, {"state": "action_state", "category": "action_category"}),
        "documents": ({"id", "state", "document_type", "named", "name_evidence_ids", "evidence_ids", "confidence"}, {"state": "document_state", "document_type": "document_type"}),
        "departments": ({"id", "role", "named", "name_evidence_ids", "evidence_ids", "confidence"}, {"role": "department_role"}),
        "temporal_entities": ({"id", "kind", "evidence_ids", "confidence"}, {"kind": "temporal_kind"}),
        "meetings": ({"id", "state", "evidence_ids", "date_ids", "time_ids", "participant_actor_ids", "confidence"}, {"state": "meeting_state"}),
        "deadlines": ({"id", "target_type", "target_id", "due_date_ids", "due_time_ids", "due_relation_evidence_ids", "confidence"}, {"target_type": "deadline_target_type"}),
        "approvals": ({"id", "state", "formality", "target_type", "target_id", "evidence_ids", "confidence"}, {"state": "approval_state", "formality": "approval_formality", "target_type": "approval_target_type"}),
        "status_updates": ({"id", "kind", "evidence_ids", "confidence"}, {"kind": "status_kind"}),
        "thread_changes": ({"id", "kind", "target_type", "target_id", "prior_expectation", "context_evidence_ids", "evidence_ids", "confidence"}, {"kind": "thread_change_kind", "target_type": "thread_target_type", "prior_expectation": "prior_expectation"}),
        "acts": ({"id", "speech_act", "target_type", "target_id", "target_formality", "evidence_ids", "confidence"}, {"speech_act": "speech_act", "target_type": "target_type", "target_formality": "target_formality"}),
    }
    items: dict[str, dict[str, dict[str, Any]]] = {}
    for collection, (required, _) in collection_specs.items():
        indexed = _unique_items(annotation.get(collection), collection, errors)
        items[collection] = indexed
        for i, item in enumerate(indexed.values()):
            path = f"{collection}[{i}]"
            if not _obj(item, path, required, set(), errors):
                continue
            for key, enum_name in collection_specs[collection][1].items():
                _enum(item.get(key), enum_name, f"{path}.{key}", errors)
            if "confidence" in item:
                _enum(item.get("confidence"), "confidence", f"{path}.confidence", errors)
            if collection in {"actors", "documents", "departments"}:
                if not isinstance(item.get("named"), bool):
                    errors.append(f"{path}.named: expected boolean")
                name_refs = _id_refs(item.get("name_evidence_ids"), f"{path}.name_evidence_ids", evidence_ids, errors,
                                     nonempty=item.get("named") is True)
                if item.get("named") is False and name_refs:
                    errors.append(f"{path}: unnamed entity must have no name_evidence_ids")
                if collection == "actors":
                    actor_refs = _id_refs(item.get("evidence_ids"), f"{path}.evidence_ids", evidence_ids, errors, nonempty=True)
                    if not set(name_refs).issubset(actor_refs):
                        errors.append(f"{path}: name_evidence_ids must also appear in evidence_ids")
            evidence_key = "evidence_ids"
            if collection == "deadlines":
                evidence_key = "due_relation_evidence_ids"
            _id_refs(item.get(evidence_key), f"{path}.{evidence_key}", evidence_ids, errors, nonempty=True)
            if collection == "actions":
                actor_id = item.get("actor_id")
                if actor_id is not None and (not isinstance(actor_id, str) or actor_id not in items["actors"]):
                    errors.append(f"{path}.actor_id: unknown actor {actor_id!r}")
            if collection == "meetings":
                date_ids = _id_refs(item.get("date_ids"), f"{path}.date_ids", set(items["temporal_entities"]), errors)
                time_ids = _id_refs(item.get("time_ids"), f"{path}.time_ids", set(items["temporal_entities"]), errors)
                actor_ids = _id_refs(item.get("participant_actor_ids"), f"{path}.participant_actor_ids", set(items["actors"]), errors)
                for temporal_id in date_ids:
                    if items["temporal_entities"].get(temporal_id, {}).get("kind") != "DATE":
                        errors.append(f"{path}.date_ids: {temporal_id!r} is not a DATE temporal entity")
                for temporal_id in time_ids:
                    if items["temporal_entities"].get(temporal_id, {}).get("kind") != "TIME":
                        errors.append(f"{path}.time_ids: {temporal_id!r} is not a TIME temporal entity")
                for temporal_id in (*date_ids, *time_ids):
                    temporal = items["temporal_entities"].get(temporal_id, {})
                    if not _has_current_message_evidence(temporal.get("evidence_ids", []), evidence, current_source_id):
                        errors.append(f"{path}: linked meeting dates/times must be stated in the current message")
                _ = actor_ids
            if collection == "deadlines":
                target_type, target_id = item.get("target_type"), item.get("target_id")
                target_collection = "actions" if target_type == "ACTION" else "documents" if target_type == "DOCUMENT" else ""
                if not isinstance(target_id, str) or target_id not in items.get(target_collection, {}):
                    errors.append(f"{path}.target_id: must reference an existing action or document (meeting dates are not deadlines)")
                date_ids = _id_refs(item.get("due_date_ids"), f"{path}.due_date_ids", set(items["temporal_entities"]), errors)
                time_ids = _id_refs(item.get("due_time_ids"), f"{path}.due_time_ids", set(items["temporal_entities"]), errors)
                if not date_ids and not time_ids:
                    errors.append(f"{path}: deadline requires an explicit due date or due time")
                for temporal_id in date_ids:
                    if items["temporal_entities"].get(temporal_id, {}).get("kind") != "DATE":
                        errors.append(f"{path}.due_date_ids: {temporal_id!r} is not a DATE temporal entity")
                for temporal_id in time_ids:
                    if items["temporal_entities"].get(temporal_id, {}).get("kind") != "TIME":
                        errors.append(f"{path}.due_time_ids: {temporal_id!r} is not a TIME temporal entity")
                for temporal_id in (*date_ids, *time_ids):
                    temporal = items["temporal_entities"].get(temporal_id, {})
                    if not _has_current_message_evidence(temporal.get("evidence_ids", []), evidence, current_source_id):
                        errors.append(f"{path}: linked due dates/times must be stated in the current message")
            if collection == "approvals":
                target_type, target_id = item.get("target_type"), item.get("target_id")
                expected_collection = {"ACTION": "actions", "DOCUMENT": "documents"}.get(target_type) if isinstance(target_type, str) else None
                if expected_collection and (not isinstance(target_id, str) or target_id not in items[expected_collection]):
                    errors.append(f"{path}.target_id: unknown {target_type.lower()} target {target_id!r}")
                if target_type == "IMPLICIT" and target_id is not None:
                    errors.append(f"{path}: IMPLICIT target must have null target_id")
                if isinstance(target_type, str) and target_type in {"PROJECT", "ACTION", "DOCUMENT"} and target_id is None and target_type != "PROJECT":
                    errors.append(f"{path}: named target type requires target_id; use IMPLICIT when unnamed")
            if collection == "thread_changes":
                context_ids = _id_refs(item.get("context_evidence_ids"), f"{path}.context_evidence_ids", evidence_ids, errors)
                prior = item.get("prior_expectation")
                if prior == "context":
                    if not context_ids:
                        errors.append(f"{path}: context-dependent expectation requires context_evidence_ids")
                    for ref in context_ids:
                        if evidence.get(ref, {}).get("source_id") == current_source_id:
                            errors.append(f"{path}: context_evidence_ids must identify an earlier source message")
                elif context_ids:
                    errors.append(f"{path}: context_evidence_ids require prior_expectation='context'")
                if isinstance(item.get("kind"), str) and item.get("kind") in {"current_chase", "escalation"} and prior == "not_applicable":
                    errors.append(f"{path}: a current chase/escalation cannot use prior_expectation='not_applicable'")
                target_type, target_id = item.get("target_type"), item.get("target_id")
                target_map = {"ACTION": "actions", "DOCUMENT": "documents", "DEPARTMENT": "departments", "MEETING": "meetings", "APPROVAL": "approvals"}
                if isinstance(target_type, str) and target_type in target_map and (not isinstance(target_id, str) or target_id not in items[target_map[target_type]]):
                    errors.append(f"{path}.target_id: unknown {target_type.lower()} target {target_id!r}")
                if target_type == "IMPLICIT" and target_id is not None:
                    errors.append(f"{path}: IMPLICIT target must have null target_id")
            if collection == "acts":
                target_type, target_id = item.get("target_type"), item.get("target_id")
                target_map = {
                    "ACTION": "actions", "DOCUMENT": "documents", "DEPARTMENT": "departments",
                    "MEETING": "meetings", "DEADLINE": "deadlines", "APPROVAL": "approvals",
                    "STATUS_UPDATE": "status_updates", "THREAD_CHANGE": "thread_changes",
                }
                if isinstance(target_type, str) and target_type in target_map and (not isinstance(target_id, str) or target_id not in items[target_map[target_type]]):
                    errors.append(f"{path}.target_id: unknown {target_type.lower()} target {target_id!r}")
                if isinstance(target_type, str) and target_type in {"IMPLICIT", "NONE"} and target_id is not None:
                    errors.append(f"{path}: {target_type} target must have null target_id")
                _validate_act_target(item, items, path, errors)

    # Every current speech act (and every current primitive) must be backed by
    # current-source current_message evidence; context can only support identity or
    # a prior expectation.
    if scope and isinstance(scope, dict):
        scope_refs = _id_refs(scope.get("evidence_ids"), "project_scope.evidence_ids", evidence_ids, errors, nonempty=True)
        for ref in scope_refs:
            ev = evidence.get(ref, {})
            if ev.get("source_id") != current_source_id:
                errors.append(f"project_scope.evidence_ids: {ref!r} must cite the current source")
    current_evidence_ids = {
        ev_id for ev_id, ev in evidence.items()
        if ev.get("source_id") == current_source_id and ev.get("field") == "current_message"
    }
    for collection, indexed in items.items():
        for item_id, item in indexed.items():
            refs = item.get("evidence_ids", [])
            if collection == "deadlines":
                refs = item.get("due_relation_evidence_ids", [])
            if collection == "thread_changes":
                refs = item.get("evidence_ids", [])
            if collection == "acts":
                refs = item.get("evidence_ids", [])
            if not isinstance(refs, list):
                continue
            if collection in {"acts", "actions", "documents", "departments", "meetings", "deadlines", "approvals", "status_updates", "thread_changes"}:
                if not current_evidence_ids.intersection(refs):
                    errors.append(f"{collection}[{item_id!r}]: requires current-source current_message evidence")
    primitive_id_owner: dict[str, str] = {}
    for collection, indexed in items.items():
        for item_id in indexed:
            if item_id in primitive_id_owner:
                errors.append(f"primitive id {item_id!r} is duplicated across {primitive_id_owner[item_id]} and {collection}")
            else:
                primitive_id_owner[item_id] = collection
    if scope and isinstance(scope, dict) and scope.get("value") == "NON_PROJECT":
        if any(items.get(name) for name in ("actions", "documents", "departments", "meetings", "deadlines", "approvals", "status_updates", "thread_changes", "acts")):
            errors.append("NON_PROJECT scope cannot carry project-management primitives or acts")
    return ValidationResult(tuple(errors))


def _has_current_message_evidence(refs: Any, evidence: dict[str, dict[str, Any]], current_source_id: str) -> bool:
    if not isinstance(refs, list):
        return False
    return any(
        isinstance(ref, str)
        and evidence.get(ref, {}).get("source_id") == current_source_id
        and evidence.get(ref, {}).get("field") == "current_message"
        for ref in refs
    )


def _validate_act_target(act: dict[str, Any], items: dict[str, dict[str, dict[str, Any]]],
                         path: str, errors: list[str]) -> None:
    speech, kind = act.get("speech_act"), act.get("target_type")
    target = act.get("target_id")
    if kind == "ACTION" and isinstance(target, str) and target in items["actions"]:
        action = items["actions"][target]
        if speech == "REQUEST" and action.get("category") == "OPERATIONAL" and (not isinstance(action.get("state"), str) or action.get("state") not in {"requested", "assigned"}):
            errors.append(f"{path}: operational REQUEST must target an action in requested/assigned state")
        if speech == "COMMIT" and action.get("state") != "committed":
            errors.append(f"{path}: COMMIT speech_act requires action state committed")
        if speech == "CANCEL" and action.get("state") != "cancelled":
            errors.append(f"{path}: CANCEL speech_act requires action state cancelled")
    if kind == "APPROVAL" and isinstance(target, str) and target in items["approvals"]:
        approval = items["approvals"][target]
        state_for_act = {"REQUEST": "requested", "APPROVE": "granted", "REJECT": "rejected"}.get(speech) if isinstance(speech, str) else None
        if state_for_act and approval.get("state") != state_for_act:
            errors.append(f"{path}: speech_act {speech} contradicts approval state {approval.get('state')!r}")
    if kind == "THREAD_CHANGE" and isinstance(target, str) and target in items["thread_changes"]:
        if not isinstance(speech, str) or speech not in {"REQUEST", "REMIND"}:
            errors.append(f"{path}: a current chase act requires REQUEST or REMIND")
        change = items["thread_changes"][target]
        if not isinstance(change.get("kind"), str) or change.get("kind") not in {"current_chase", "escalation"}:
            errors.append(f"{path}: current chase act must target current_chase or escalation")
        if change.get("prior_expectation") == "not_applicable":
            errors.append(f"{path}: follow-up cannot have prior_expectation='not_applicable'")
        target_type, target_id = change.get("target_type"), change.get("target_id")
        if target_type == "DOCUMENT" and isinstance(target_id, str) and target_id in items["documents"]:
            if items["documents"][target_id].get("state") == "delivered":
                errors.append(f"{path}: current chase cannot target a document already marked delivered")
    if kind == "DEADLINE" and isinstance(target, str) and target in items["deadlines"]:
        deadline = items["deadlines"][target]
        if not (deadline.get("due_date_ids") or deadline.get("due_time_ids")):
            errors.append(f"{path}: deadline relation act requires an explicit due date/time")
        if not isinstance(speech, str) or speech not in {"REQUEST", "INFORM", "COMMIT", "REMIND"}:
            errors.append(f"{path}: deadline relation has incompatible speech_act {speech!r}")
    if kind == "DOCUMENT":
        if act.get("target_formality") != "NOT_APPLICABLE":
            errors.append(f"{path}: explicit document target takes formality from document_type")
        if isinstance(target, str) and target in items["documents"]:
            doc = items["documents"][target]
            if speech == "REQUEST" and doc.get("state") != "requested" and not (doc.get("state") == "unknown" and act.get("confidence") == "uncertain"):
                errors.append(f"{path}: document REQUEST contradicts document state {doc.get('state')!r}")
            if speech == "DELIVER" and doc.get("state") != "delivered":
                errors.append(f"{path}: DELIVER speech_act requires document state delivered")
    elif kind == "IMPLICIT":
        if speech == "REQUEST":
            if not isinstance(act.get("target_formality"), str) or act.get("target_formality") not in {"PROJECT_DELIVERABLE", "OTHER", "UNCERTAIN"}:
                errors.append(f"{path}: implicit REQUEST target must explicitly state its target formality")
        elif act.get("target_formality") != "NOT_APPLICABLE":
            errors.append(f"{path}: target_formality only applies to an implicit request")
    elif act.get("target_formality") != "NOT_APPLICABLE":
        errors.append(f"{path}: target_formality is only used for an implicit request")
    if kind == "MEETING" and isinstance(target, str) and target in items["meetings"]:
        state_for_act = {"PROPOSE": "proposed", "SCHEDULE": "scheduled", "RESCHEDULE": "rescheduled", "CANCEL": "cancelled"}.get(speech) if isinstance(speech, str) else None
        if state_for_act and items["meetings"][target].get("state") != state_for_act:
            errors.append(f"{path}: speech_act {speech} contradicts meeting state {items['meetings'][target].get('state')!r}")

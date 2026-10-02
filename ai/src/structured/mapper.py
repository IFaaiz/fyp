"""Derive the existing FYP labels deterministically from validated primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .validation import validate_annotation


LABELS = (
    "MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT",
    "ACTION_REQUEST", "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE", "NON_PROJECT",
)


@dataclass(frozen=True)
class MappingExplanation:
    label: str | None
    rule_id: str
    decision: str
    evidence_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class MappingResult:
    labels: tuple[str, ...]
    needs_review: bool
    explanations: tuple[MappingExplanation, ...]
    review_reasons: tuple[str, ...]
    validation_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["labels"] = list(self.labels)
        result["explanations"] = [
            {**asdict(item), "evidence_ids": list(item.evidence_ids)} for item in self.explanations
        ]
        result["review_reasons"] = list(self.review_reasons)
        result["validation_errors"] = list(self.validation_errors)
        return result


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)}


def map_labels(annotation: Any, *, current_source_id: str,
               sources: Mapping[str, Mapping[str, Any]]) -> MappingResult:
    """Validate and map one annotation; no text extraction or label prediction occurs.

    Candidate labels come from source-grounded speech acts and typed target state.
    The mapper does not consume a separate label-like function prediction.
    Invalid input fails closed; uncertain scope blocks all output, and uncertain
    high-risk relations are suppressed while independent supported labels survive.
    """
    validation = validate_annotation(annotation, current_source_id=current_source_id, sources=sources)
    if not validation.valid:
        return MappingResult((), True, (), ("structured_annotation_invalid",), validation.errors)

    scope = annotation["project_scope"]
    review_reasons = list(annotation["uncertainty_reasons"])
    if annotation["needs_review"] and not review_reasons:
        review_reasons.append("annotation_marked_for_review")
    for name in ("actors", "actions", "documents", "departments", "temporal_entities", "meetings", "deadlines",
                 "approvals", "status_updates", "thread_changes", "acts"):
        if any(item.get("confidence") == "uncertain" for item in annotation[name]):
            review_reasons.append(f"uncertain_{name}")
    if scope["value"] == "UNCERTAIN" or scope["confidence"] == "uncertain":
        return MappingResult((), True,
            (MappingExplanation(None, "SCOPE-001", "suppressed", tuple(scope["evidence_ids"]),
                                "Uncertain scope produces no project or NON_PROJECT labels."),),
            ("project_scope_uncertain",))
    if scope["value"] == "NON_PROJECT":
        return MappingResult(("NON_PROJECT",), bool(review_reasons),
            (MappingExplanation("NON_PROJECT", "SCOPE-002", "emitted", tuple(scope["evidence_ids"]),
                                "Explicitly supported out-of-scope decision; the label is exclusive."),),
            tuple(dict.fromkeys(review_reasons)))

    names = ("actions", "documents", "departments", "temporal_entities", "meetings", "deadlines",
             "approvals", "status_updates", "thread_changes")
    entities = {name: _by_id(annotation[name]) for name in names}
    acts = _by_id(annotation["acts"])
    emitted: dict[str, list[str]] = {}
    explanations: list[MappingExplanation] = []

    def emit(label: str, act: dict[str, Any], rule: str, detail: str) -> None:
        emitted.setdefault(label, []).extend(act["evidence_ids"])
        explanations.append(MappingExplanation(label, rule, "emitted", tuple(act["evidence_ids"]), detail))

    def suppress(label: str, act: dict[str, Any], rule: str, reason: str, detail: str) -> None:
        if reason not in review_reasons:
            review_reasons.append(reason)
        explanations.append(MappingExplanation(label, rule, "suppressed", tuple(act["evidence_ids"]), detail))

    for act in acts.values():
        speech = act["speech_act"]
        target_type, target_id = act["target_type"], act["target_id"]
        target = None
        if target_type == "ACTION":
            target = entities["actions"].get(target_id)
        elif target_type == "DOCUMENT":
            target = entities["documents"].get(target_id)
        elif target_type == "DEPARTMENT":
            target = entities["departments"].get(target_id)
        elif target_type == "MEETING":
            target = entities["meetings"].get(target_id)
        elif target_type == "DEADLINE":
            target = entities["deadlines"].get(target_id)
        elif target_type == "APPROVAL":
            target = entities["approvals"].get(target_id)
        elif target_type == "STATUS_UPDATE":
            target = entities["status_updates"].get(target_id)
        elif target_type == "THREAD_CHANGE":
            target = entities["thread_changes"].get(target_id)

        base_supported = act["confidence"] == "supported" and (target is None or target.get("confidence", "supported") == "supported")

        if target_type == "ACTION" and speech == "REQUEST" and target:
            if target["category"] == "UNCERTAIN":
                suppress("ACTION_REQUEST", act, "ACT-ACTION-REQUEST", "action_category_uncertain",
                         "The action category is uncertain; it is not accepted as operational work.")
            elif target["category"] == "OPERATIONAL" and target["state"] in {"requested", "assigned"}:
                if base_supported:
                    emit("ACTION_REQUEST", act, "ACT-ACTION-REQUEST", "REQUEST targets a supported new operational action in requested/assigned state.")
                else:
                    suppress("ACTION_REQUEST", act, "ACT-ACTION-REQUEST", "operational_action_uncertain", "The operational request or target is uncertain.")

        if target_type == "DOCUMENT" and speech == "REQUEST" and target:
            if target["document_type"] == "UNCERTAIN":
                suppress("REPORT_REQUEST", act, "ACT-DOCUMENT-REQUEST", "document_formality_uncertain",
                         "The requested document's project-deliverable status is uncertain.")
            elif target["document_type"] == "PROJECT_DELIVERABLE" and target["state"] == "requested":
                if base_supported:
                    emit("REPORT_REQUEST", act, "ACT-DOCUMENT-REQUEST", "REQUEST targets a supported formal project deliverable in requested state.")
                else:
                    suppress("REPORT_REQUEST", act, "ACT-DOCUMENT-REQUEST", "document_request_uncertain", "The document request or target is uncertain.")
        elif target_type == "IMPLICIT" and speech == "REQUEST":
            if act["target_formality"] == "UNCERTAIN":
                suppress("REPORT_REQUEST", act, "ACT-DOCUMENT-REQUEST-IMPLICIT", "implicit_document_formality_uncertain",
                         "The unnamed target's formal deliverable status is uncertain.")
            elif act["target_formality"] == "PROJECT_DELIVERABLE":
                if base_supported:
                    emit("REPORT_REQUEST", act, "ACT-DOCUMENT-REQUEST-IMPLICIT", "REQUEST has exact evidence for an implicit formal project deliverable.")
                else:
                    suppress("REPORT_REQUEST", act, "ACT-DOCUMENT-REQUEST-IMPLICIT", "implicit_document_request_uncertain", "The implicit document request is uncertain.")

        if target_type == "DEPARTMENT" and speech in {"REQUEST", "INFORM", "REMIND"} and target:
            if target["role"] == "contributor":
                if base_supported:
                    emit("DEPARTMENTAL_INPUT", act, "ACT-DEPARTMENT-CONTRIBUTION", "Speech act targets a supported department contribution/response.")
                else:
                    suppress("DEPARTMENTAL_INPUT", act, "ACT-DEPARTMENT-CONTRIBUTION", "department_input_uncertain", "Departmental contribution is uncertain.")

        if target_type == "APPROVAL" and speech in {"REQUEST", "APPROVE", "REJECT", "INFORM"} and target:
            if target["formality"] == "UNCERTAIN":
                suppress("APPROVAL", act, "ACT-FORMAL-APPROVAL", "approval_formality_uncertain", "Formal approval status is uncertain.")
            elif target["formality"] == "FORMAL":
                if base_supported:
                    emit("APPROVAL", act, "ACT-FORMAL-APPROVAL", "Speech act and supported formal-approval state agree.")
                else:
                    suppress("APPROVAL", act, "ACT-FORMAL-APPROVAL", "approval_relation_uncertain", "The formal approval request/decision is uncertain.")

        if target_type == "THREAD_CHANGE" and speech in {"REQUEST", "REMIND"} and target:
            if target["kind"] in {"current_chase", "escalation"}:
                prior = target["prior_expectation"]
                if prior == "unknown":
                    suppress("FOLLOW_UP", act, "ACT-CURRENT-FOLLOW-UP", "follow_up_prior_expectation_unknown",
                             "The current chase does not establish or authenticate an earlier expectation.")
                elif not base_supported:
                    suppress("FOLLOW_UP", act, "ACT-CURRENT-FOLLOW-UP", "follow_up_relation_uncertain",
                             "The current chase or its typed target is uncertain.")
                else:
                    chase_target_type, chase_target_id = target["target_type"], target["target_id"]
                    typed_target = None
                    mapping = {"ACTION": "actions", "DOCUMENT": "documents", "DEPARTMENT": "departments", "MEETING": "meetings", "APPROVAL": "approvals"}
                    if chase_target_type in mapping and chase_target_id is not None:
                        typed_target = entities[mapping[chase_target_type]].get(chase_target_id)
                    if typed_target is not None and typed_target.get("confidence", "supported") == "uncertain":
                        suppress("FOLLOW_UP", act, "ACT-CURRENT-FOLLOW-UP", "follow_up_target_uncertain", "The prior expectation target is uncertain.")
                    else:
                        emit("FOLLOW_UP", act, "ACT-CURRENT-FOLLOW-UP", "Current REMIND/REQUEST chases a supported explicit or context-evidenced prior expectation.")
                        if chase_target_type == "DOCUMENT" and typed_target:
                            if typed_target["document_type"] == "PROJECT_DELIVERABLE" and typed_target["state"] != "delivered":
                                emit("REPORT_REQUEST", act, "ACT-FOLLOW-UP-DOCUMENT", "The current chase targets a formal project deliverable.")
                            elif typed_target["document_type"] == "UNCERTAIN":
                                if "document_formality_uncertain" not in review_reasons:
                                    review_reasons.append("document_formality_uncertain")
                        elif chase_target_type == "DEPARTMENT" and typed_target and typed_target["role"] == "contributor":
                            emit("DEPARTMENTAL_INPUT", act, "ACT-FOLLOW-UP-DEPARTMENT", "The current chase targets a department contribution.")

        if target_type == "MEETING" and speech in {"PROPOSE", "SCHEDULE", "CANCEL", "RESCHEDULE", "INFORM"} and target:
            state_for_act = {"PROPOSE": "proposed", "SCHEDULE": "scheduled", "CANCEL": "cancelled", "RESCHEDULE": "rescheduled"}.get(speech)
            compatible = state_for_act is None or target["state"] == state_for_act
            if compatible:
                if base_supported:
                    emit("MEETING", act, "ACT-MEETING-EVENT", "Speech act is grounded in a supported specific meeting event and compatible state.")
                else:
                    suppress("MEETING", act, "ACT-MEETING-EVENT", "meeting_event_uncertain", "The meeting event is uncertain.")

        if target_type == "STATUS_UPDATE" and speech in {"INFORM", "COMMIT", "DELIVER", "APPROVE", "REJECT"} and target:
            if target["kind"] == "other":
                suppress("GENERAL_UPDATE", act, "ACT-PROJECT-STATUS", "status_kind_other_uncertain",
                         "The status kind is too generic to establish a substantive project update.")
            elif base_supported:
                emit("GENERAL_UPDATE", act, "ACT-PROJECT-STATUS", "A substantive project status/update primitive is explicitly evidenced.")
            else:
                suppress("GENERAL_UPDATE", act, "ACT-PROJECT-STATUS", "status_update_uncertain", "The project status update is uncertain.")

    # A due relation is its own primitive. A request may target the action or
    # document; it need not be duplicated as a speech act targeting DEADLINE.
    for deadline in entities["deadlines"].values():
        target_collection = "actions" if deadline["target_type"] == "ACTION" else "documents"
        due_target = entities[target_collection][deadline["target_id"]]
        temporal_ids = deadline["due_date_ids"] + deadline["due_time_ids"]
        temporal = entities["temporal_entities"]
        relation_supported = (
            deadline["confidence"] == "supported" and due_target["confidence"] == "supported"
            and all(temporal[temporal_id]["confidence"] == "supported" for temporal_id in temporal_ids)
        )
        relation_evidence = {"evidence_ids": deadline["due_relation_evidence_ids"]}
        if relation_supported:
            emit("DEADLINE", relation_evidence, "DUE-RELATION",
                 "Supported current due relation connects a date/time to an action or deliverable.")
        else:
            suppress("DEADLINE", relation_evidence, "DUE-RELATION", "deadline_target_or_time_uncertain",
                     "The due relation, temporal value, or target is uncertain.")

    labels = tuple(sorted(emitted, key=LABELS.index))
    if not labels:
        if "no_mappable_project_act" not in review_reasons:
            review_reasons.append("no_mappable_project_act")
        explanations.append(MappingExplanation(None, "MAP-EMPTY-001", "review", tuple(),
                                                "Project scope has no supported current act mapping to an existing label."))
    return MappingResult(labels, bool(review_reasons), tuple(explanations), tuple(dict.fromkeys(review_reasons)))

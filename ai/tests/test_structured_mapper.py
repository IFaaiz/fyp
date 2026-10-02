"""Contract tests only; these synthetic strings are not annotation/training data."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from src.structured import LABELS, map_labels, validate_annotation


class Builder:
    def __init__(self, current: str, *, subject: str = "Project work", source_id: str = "source-current"):
        self.source_id = source_id
        self.sources = {source_id: {"subject": subject, "current_message": current}}
        self.annotation = {
            "schema_version": "2-alpha", "email_id": "local-email-1", "current_source_id": source_id,
            "project_scope": {"value": "PROJECT", "confidence": "supported", "evidence_ids": []},
            "evidence": [], "actors": [], "actions": [], "documents": [], "departments": [],
            "temporal_entities": [], "meetings": [], "deadlines": [], "approvals": [],
            "status_updates": [], "thread_changes": [], "acts": [],
            "needs_review": False, "uncertainty_reasons": [],
        }
        scope_ev = self.ev(current, field="current_message") if current else self.ev(subject, field="subject")
        self.annotation["project_scope"]["evidence_ids"] = [scope_ev]

    def ev(self, text: str, *, source_id: str | None = None, field: str = "current_message", start: int | None = None) -> str:
        sid = source_id or self.source_id
        value = self.sources[sid][field]
        if start is None:
            start = value.index(text)
        assert value[start:start + len(text)] == text
        eid = f"ev{len(self.annotation['evidence']) + 1}"
        self.annotation["evidence"].append({
            "id": eid, "source_id": sid, "field": field, "start": start,
            "end": start + len(text), "text": text,
        })
        return eid

    def action(self, text: str, *, item_id: str = "action-1", state: str = "requested",
               category: str = "OPERATIONAL", confidence: str = "supported") -> str:
        refs = [self.ev(text)]
        self.annotation["actions"].append({
            "id": item_id, "state": state, "category": category,
            "evidence_ids": refs, "actor_id": None, "confidence": confidence,
        })
        return item_id

    def document(self, text: str, *, item_id: str = "document-1", state: str = "requested",
                 document_type: str = "PROJECT_DELIVERABLE", confidence: str = "supported", named: bool = True) -> str:
        ref = self.ev(text)
        self.annotation["documents"].append({
            "id": item_id, "state": state, "document_type": document_type, "named": named,
            "name_evidence_ids": [ref] if named else [], "evidence_ids": [ref], "confidence": confidence,
        })
        return item_id

    def act(self, speech_act: str, text: str, *, target_type: str = "NONE",
            target_id: str | None = None, target_formality: str = "NOT_APPLICABLE",
            confidence: str = "supported", start: int | None = None) -> str:
        ref = self.ev(text, start=start)
        act_id = f"act-{len(self.annotation['acts']) + 1}"
        self.annotation["acts"].append({
            "id": act_id, "speech_act": speech_act,
            "target_type": target_type, "target_id": target_id,
            "target_formality": target_formality, "evidence_ids": [ref], "confidence": confidence,
        })
        return act_id

    def map(self):
        return map_labels(self.annotation, current_source_id=self.source_id, sources=self.sources)


def add_deadline(b: Builder, *, target_type: str = "ACTION", target_id: str = "action-1",
                 due_text: str = "Friday", relation_text: str = "by Friday", confidence: str = "supported") -> str:
    due_ev = b.ev(due_text)
    relation_ev = b.ev(relation_text)
    temporal_id = f"date-{len(b.annotation['temporal_entities']) + 1}"
    b.annotation["temporal_entities"].append({
        "id": temporal_id, "kind": "DATE", "evidence_ids": [due_ev], "confidence": confidence,
    })
    deadline_id = f"deadline-{len(b.annotation['deadlines']) + 1}"
    b.annotation["deadlines"].append({
        "id": deadline_id, "target_type": target_type, "target_id": target_id,
        "due_date_ids": [temporal_id], "due_time_ids": [],
        "due_relation_evidence_ids": [relation_ev], "confidence": confidence,
    })
    b.act("REQUEST", relation_text, target_type="DEADLINE", target_id=deadline_id)
    return deadline_id


class StructuredMapperTests(unittest.TestCase):
    def test_public_taxonomy_order_and_schema_version_are_separate(self):
        self.assertEqual(LABELS, (
            "MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT", "ACTION_REQUEST",
            "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE", "NON_PROJECT",
        ))
        schema_path = Path(__file__).parents[1] / "config" / "structured_primitive_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "urn:fyp:structured-primitive-schema:2-alpha")
        self.assertIn("current_source_id", schema["required"])

    def test_action_only_maps_to_action_request_not_update(self):
        b = Builder("Ali, please contact the vendor and confirm installation.")
        aid = b.action("contact the vendor and confirm installation")
        b.act("REQUEST", "please contact the vendor and confirm installation",
              target_type="ACTION", target_id=aid)
        result = b.map()
        self.assertEqual(result.labels, ("ACTION_REQUEST",))
        self.assertFalse(result.needs_review)

    def test_action_categories_keep_document_and_department_transactions_out_of_action_request(self):
        for category in ("DOCUMENT_TRANSFER", "DEPARTMENTAL_CONTRIBUTION", "APPROVAL_TRANSACTION", "OTHER"):
            with self.subTest(category=category):
                b = Builder("Please send the revised report.")
                action = b.action("send the revised report", category=category)
                b.act("REQUEST", "send the revised report", target_type="ACTION", target_id=action)
                self.assertNotIn("ACTION_REQUEST", b.map().labels)

    def test_unnamed_but_evidenced_formal_deliverable_request_maps_report_request(self):
        b = Builder("Please prepare the project report.")
        b.act("REQUEST", "prepare the project report", target_type="IMPLICIT", target_formality="PROJECT_DELIVERABLE")
        self.assertEqual(b.map().labels, ("REPORT_REQUEST",))

    def test_uncertain_implicit_deliverable_is_suppressed(self):
        b = Builder("Please prepare the project report.")
        b.act("REQUEST", "prepare the project report", target_type="IMPLICIT", target_formality="UNCERTAIN")
        result = b.map()
        self.assertNotIn("REPORT_REQUEST", result.labels)
        self.assertTrue(result.needs_review)

    def test_other_document_request_is_not_a_formal_report_request(self):
        b = Builder("Please send me a copy of the email.")
        doc = b.document("copy of the email", document_type="OTHER")
        b.act("REQUEST", "send me a copy of the email", target_type="DOCUMENT", target_id=doc)
        self.assertNotIn("REPORT_REQUEST", b.map().labels)

    def test_document_request_plus_deadline_without_duplicating_action_request(self):
        b = Builder("Please submit the revised report by Friday.")
        doc = b.document("revised report")
        action = b.action("submit the revised report")
        b.act("REQUEST", "submit the revised report", target_type="DOCUMENT", target_id=doc)
        add_deadline(b, target_id=action, relation_text="by Friday")
        self.assertEqual(b.map().labels, ("DEADLINE", "REPORT_REQUEST"))

    def test_independent_operational_and_document_requests_coexist(self):
        b = Builder("Contact the vendor and send the revised report by Friday.")
        action = b.action("Contact the vendor")
        doc_action = b.action("send the revised report", item_id="action-doc")
        doc = b.document("revised report")
        b.act("REQUEST", "Contact the vendor", target_type="ACTION", target_id=action)
        b.act("REQUEST", "send the revised report", target_type="DOCUMENT", target_id=doc)
        add_deadline(b, target_id=doc_action, relation_text="by Friday")
        self.assertEqual(b.map().labels, ("DEADLINE", "REPORT_REQUEST", "ACTION_REQUEST"))

    def test_expected_report_and_due_date_do_not_create_report_request(self):
        b = Builder("The final report is due Friday.")
        doc = b.document("final report", state="expected")
        action = b.action("final report", item_id="action-final", state="committed")
        add_deadline(b, target_id=action, relation_text="due Friday")
        result = b.map()
        self.assertEqual(result.labels, ("DEADLINE",))
        self.assertNotIn("REPORT_REQUEST", result.labels)
        self.assertFalse(result.needs_review)

    def test_completed_status_and_deadline_cooccur_but_not_request(self):
        text = "The testing phase is complete and the final report is due Friday."
        b = Builder(text)
        status_ev = b.ev("The testing phase is complete")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "completed", "evidence_ids": [status_ev], "confidence": "supported"})
        b.act("INFORM", "The testing phase is complete", target_type="STATUS_UPDATE", target_id="status-1")
        b.document("final report", state="expected")
        action = b.action("final report", item_id="action-final", state="committed")
        add_deadline(b, target_id=action, relation_text="due Friday")
        self.assertEqual(b.map().labels, ("DEADLINE", "GENERAL_UPDATE"))

    def test_completed_status_plus_explicit_report_submission_request(self):
        text = "The testing phase is complete. Please submit the final report by Friday."
        b = Builder(text)
        status_ev = b.ev("The testing phase is complete")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "completed", "evidence_ids": [status_ev], "confidence": "supported"})
        b.act("INFORM", "The testing phase is complete", target_type="STATUS_UPDATE", target_id="status-1")
        doc = b.document("final report")
        action = b.action("submit the final report", item_id="action-submit")
        b.act("REQUEST", "submit the final report", target_type="DOCUMENT", target_id=doc)
        add_deadline(b, target_id=action, relation_text="by Friday")
        self.assertEqual(b.map().labels, ("DEADLINE", "REPORT_REQUEST", "GENERAL_UPDATE"))

    def test_meeting_schedule_date_is_not_deadline(self):
        text = "The design review is moved to Friday at 3 PM."
        b = Builder(text)
        meeting_ev = b.ev("The design review is moved")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "rescheduled", "evidence_ids": [meeting_ev],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.act("RESCHEDULE", "The design review is moved", target_type="MEETING", target_id="meeting-1")
        self.assertEqual(b.map().labels, ("MEETING",))

    def test_deadline_time_and_date_are_distinct_temporal_entities(self):
        b = Builder("Please send the revised report by Friday at 3 PM.")
        action = b.action("send the revised report")
        date_ev, time_ev, relation_ev = b.ev("Friday"), b.ev("3 PM"), b.ev("by Friday at 3 PM")
        b.annotation["temporal_entities"].extend([
            {"id": "date-1", "kind": "DATE", "evidence_ids": [date_ev], "confidence": "supported"},
            {"id": "time-1", "kind": "TIME", "evidence_ids": [time_ev], "confidence": "supported"},
        ])
        b.annotation["deadlines"].append({
            "id": "deadline-1", "target_type": "ACTION", "target_id": action,
            "due_date_ids": ["date-1"], "due_time_ids": ["time-1"],
            "due_relation_evidence_ids": [relation_ev], "confidence": "supported",
        })
        b.act("REQUEST", "by Friday at 3 PM", target_type="DEADLINE", target_id="deadline-1")
        result = b.map()
        self.assertIn("DEADLINE", result.labels)
        self.assertFalse(result.validation_errors)

    def test_departmental_input_and_due_date_are_not_action_request(self):
        b = Builder("Finance Department, please provide the revised budget figures by COB Friday.")
        dept_ev = b.ev("Finance Department")
        b.annotation["departments"].append({
            "id": "department-1", "role": "contributor", "named": True,
            "name_evidence_ids": [dept_ev], "evidence_ids": [dept_ev], "confidence": "supported",
        })
        action = b.action("provide the revised budget figures")
        b.act("REQUEST", "provide the revised budget figures", target_type="DEPARTMENT", target_id="department-1")
        date_ev, time_ev, relation_ev = b.ev("Friday"), b.ev("COB"), b.ev("by COB Friday")
        b.annotation["temporal_entities"].extend([
            {"id": "date-1", "kind": "DATE", "evidence_ids": [date_ev], "confidence": "supported"},
            {"id": "time-1", "kind": "TIME", "evidence_ids": [time_ev], "confidence": "supported"},
        ])
        b.annotation["deadlines"].append({
            "id": "deadline-1", "target_type": "ACTION", "target_id": action,
            "due_date_ids": ["date-1"], "due_time_ids": ["time-1"],
            "due_relation_evidence_ids": [relation_ev], "confidence": "supported",
        })
        b.act("REQUEST", "by COB Friday", target_type="DEADLINE", target_id="deadline-1")
        self.assertEqual(b.map().labels, ("DEADLINE", "DEPARTMENTAL_INPUT"))

    def test_current_context_supported_department_chase_maps_followup_and_input(self):
        current = "Following up on the budget request: has Finance sent the Q3 cost figures?"
        b = Builder(current)
        b.sources["source-prior"] = {"subject": "Budget figures", "current_message": "Could Finance provide the Q3 cost figures?"}
        dept_ev = b.ev("Finance")
        b.annotation["departments"].append({
            "id": "department-1", "role": "contributor", "named": True,
            "name_evidence_ids": [dept_ev], "evidence_ids": [dept_ev], "confidence": "supported",
        })
        prior_ev = b.ev("Could Finance provide the Q3 cost figures?", source_id="source-prior")
        current_ev = b.ev("Following up on the budget request")
        b.annotation["thread_changes"].append({
            "id": "thread-1", "kind": "current_chase", "target_type": "DEPARTMENT", "target_id": "department-1",
            "prior_expectation": "context", "context_evidence_ids": [prior_ev], "evidence_ids": [current_ev], "confidence": "supported",
        })
        b.act("REMIND", "Following up on the budget request", target_type="THREAD_CHANGE", target_id="thread-1")
        self.assertEqual(b.map().labels, ("DEPARTMENTAL_INPUT", "FOLLOW_UP"))

    def test_current_explicit_chase_can_establish_prior_expectation_without_history(self):
        b = Builder("Following up on the report due yesterday—when can we expect it?")
        doc = b.document("report", state="missing")
        chase_ev = b.ev("Following up on the report due yesterday")
        b.annotation["thread_changes"].append({
            "id": "thread-1", "kind": "current_chase", "target_type": "DOCUMENT", "target_id": doc,
            "prior_expectation": "explicit_current", "context_evidence_ids": [], "evidence_ids": [chase_ev], "confidence": "supported",
        })
        b.act("REMIND", "Following up on the report due yesterday", target_type="THREAD_CHANGE", target_id="thread-1")
        result = b.map()
        self.assertEqual(result.labels, ("REPORT_REQUEST", "FOLLOW_UP"))

    def test_future_instruction_to_follow_up_is_new_action_not_current_chase(self):
        b = Builder("Follow up with the vendor after the meeting.")
        action = b.action("Follow up with the vendor after the meeting")
        b.act("REQUEST", "Follow up with the vendor after the meeting",
              target_type="ACTION", target_id=action)
        self.assertEqual(b.map().labels, ("ACTION_REQUEST",))

    def test_unknown_chase_is_suppressed_but_independent_update_survives(self):
        b = Builder("Could you send those today? Testing is complete.")
        chase = b.ev("Could you send those today?")
        status_ev = b.ev("Testing is complete")
        b.annotation["thread_changes"].append({
            "id": "thread-1", "kind": "current_chase", "target_type": "IMPLICIT", "target_id": None,
            "prior_expectation": "unknown", "context_evidence_ids": [], "evidence_ids": [chase], "confidence": "uncertain",
        })
        b.annotation["status_updates"].append({"id": "status-1", "kind": "completed", "evidence_ids": [status_ev], "confidence": "supported"})
        b.act("REQUEST", "Could you send those today?", target_type="THREAD_CHANGE", target_id="thread-1", confidence="uncertain")
        b.act("INFORM", "Testing is complete", target_type="STATUS_UPDATE", target_id="status-1")
        result = b.map()
        self.assertEqual(result.labels, ("GENERAL_UPDATE",))
        self.assertTrue(result.needs_review)
        self.assertIn("follow_up_prior_expectation_unknown", result.review_reasons)

    def test_department_mention_alone_does_not_map(self):
        b = Builder("Finance Department changed its office hours.")
        ref = b.ev("Finance Department")
        b.annotation["departments"].append({
            "id": "department-1", "role": "mention_only", "named": True,
            "name_evidence_ids": [ref], "evidence_ids": [ref], "confidence": "supported",
        })
        b.act("INFORM", "Finance Department", target_type="DEPARTMENT", target_id="department-1")
        self.assertNotIn("DEPARTMENTAL_INPUT", b.map().labels)

    def test_department_recipient_or_copy_is_not_a_contribution(self):
        for text, phrase, speech in (
            ("I sent Finance a copy.", "Finance", "INFORM"),
            ("Please copy Finance.", "Finance", "REQUEST"),
        ):
            with self.subTest(text=text):
                b = Builder(text)
                ref = b.ev(phrase)
                b.annotation["departments"].append({
                    "id": "department-1", "role": "recipient", "named": True,
                    "name_evidence_ids": [ref], "evidence_ids": [ref], "confidence": "supported",
                })
                b.act(speech, phrase, target_type="DEPARTMENT", target_id="department-1")
                self.assertNotIn("DEPARTMENTAL_INPUT", b.map().labels)

    def test_formal_approval_maps_but_informal_review_or_agreement_does_not(self):
        b = Builder("Please approve the revised project plan.")
        ev = b.ev("approve the revised project plan")
        b.annotation["approvals"].append({
            "id": "approval-1", "state": "requested", "formality": "FORMAL", "target_type": "IMPLICIT",
            "target_id": None, "evidence_ids": [ev], "confidence": "supported",
        })
        b.act("REQUEST", "approve the revised project plan", target_type="APPROVAL", target_id="approval-1")
        self.assertEqual(b.map().labels, ("APPROVAL",))

        informal = Builder("Please review the plan and send comments.")
        action = informal.action("review the plan and send comments")
        informal.act("REQUEST", "review the plan and send comments", target_type="ACTION", target_id=action)
        self.assertNotIn("APPROVAL", informal.map().labels)

        agree = Builder("Agreed.")
        self.assertEqual(agree.map().labels, ())
        self.assertTrue(agree.map().needs_review)

    def test_uncertain_approval_formality_is_suppressed_and_reviewed(self):
        b = Builder("The steering group has approved the revised schedule.")
        ev = b.ev("approved the revised schedule")
        b.annotation["approvals"].append({
            "id": "approval-1", "state": "granted", "formality": "UNCERTAIN", "target_type": "IMPLICIT",
            "target_id": None, "evidence_ids": [ev], "confidence": "supported",
        })
        b.act("INFORM", "approved the revised schedule", target_type="APPROVAL", target_id="approval-1")
        result = b.map()
        self.assertNotIn("APPROVAL", result.labels)
        self.assertTrue(result.needs_review)
        self.assertIn("approval_formality_uncertain", result.review_reasons)

    def test_bare_reschedule_is_meeting_not_general_update(self):
        b = Builder("The design review is moved to Friday.")
        ev = b.ev("The design review is moved to Friday")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "rescheduled", "evidence_ids": [ev],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.act("RESCHEDULE", "The design review is moved to Friday", target_type="MEETING", target_id="meeting-1")
        self.assertEqual(b.map().labels, ("MEETING",))

    def test_meeting_plus_deadline_plus_approval_and_meeting_metadata(self):
        text = "The design review is moved to Friday at 3 PM. Send the revised report by Thursday for approval."
        b = Builder(text)
        meeting_ev = b.ev("The design review is moved")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "rescheduled", "evidence_ids": [meeting_ev],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.act("RESCHEDULE", "The design review is moved", target_type="MEETING", target_id="meeting-1")
        doc = b.document("revised report")
        b.act("REQUEST", "Send the revised report", target_type="DOCUMENT", target_id=doc)
        action = b.action("Send the revised report", item_id="action-send")
        add_deadline(b, target_id=action, relation_text="by Thursday")
        approval_ev = b.ev("for approval")
        b.annotation["approvals"].append({
            "id": "approval-1", "state": "requested", "formality": "FORMAL", "target_type": "DOCUMENT",
            "target_id": doc, "evidence_ids": [approval_ev], "confidence": "supported",
        })
        b.act("REQUEST", "for approval", target_type="APPROVAL", target_id="approval-1")
        self.assertEqual(b.map().labels, ("MEETING", "DEADLINE", "REPORT_REQUEST", "APPROVAL"))

    def test_non_project_is_exclusive(self):
        b = Builder("Would you like to have lunch tomorrow?")
        b.annotation["project_scope"].update(value="NON_PROJECT")
        result = b.map()
        self.assertEqual(result.labels, ("NON_PROJECT",))
        self.assertFalse(result.needs_review)

    def test_non_project_label_survives_uncertain_ner_with_review_flag(self):
        b = Builder("Would Ali like lunch tomorrow?")
        b.annotation["project_scope"].update(value="NON_PROJECT")
        actor_ref = b.ev("Ali")
        temporal_ref = b.ev("tomorrow")
        b.annotation["actors"].append({
            "id": "actor-1", "kind": "PERSON", "named": True, "name_evidence_ids": [actor_ref],
            "evidence_ids": [actor_ref], "confidence": "uncertain",
        })
        b.annotation["temporal_entities"].append({
            "id": "date-1", "kind": "DATE", "evidence_ids": [temporal_ref], "confidence": "uncertain",
        })
        result = b.map()
        self.assertEqual(result.labels, ("NON_PROJECT",))
        self.assertTrue(result.needs_review)
        self.assertIn("uncertain_actors", result.review_reasons)
        self.assertIn("uncertain_temporal_entities", result.review_reasons)

    def test_project_scope_uncertainty_suppresses_every_label(self):
        b = Builder("Please test the new release by Friday.")
        action = b.action("test the new release")
        b.act("REQUEST", "test the new release", target_type="ACTION", target_id=action)
        add_deadline(b, target_id=action, relation_text="by Friday")
        b.annotation["project_scope"].update(value="UNCERTAIN")
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(result.needs_review)

    def test_subject_scope_evidence_is_allowed_but_actions_still_need_current_message(self):
        b = Builder("Testing is complete.", subject="Project Orion", source_id="src")
        b.annotation["project_scope"]["evidence_ids"] = [b.ev("Project Orion", field="subject")]
        status_ref = b.ev("Testing is complete")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "completed", "evidence_ids": [status_ref], "confidence": "supported"})
        b.act("INFORM", "Testing is complete", target_type="STATUS_UPDATE", target_id="status-1")
        self.assertEqual(b.map().labels, ("GENERAL_UPDATE",))

    def test_missing_scope_evidence_fails_closed(self):
        b = Builder("Testing is complete.")
        b.annotation["project_scope"]["evidence_ids"] = []
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(result.validation_errors)

    def test_every_current_act_requires_current_source_message_evidence(self):
        b = Builder("Thanks.")
        b.sources["old-source"] = {"subject": "Report", "current_message": "Please submit the report by Friday."}
        old = b.ev("Please submit the report", source_id="old-source")
        b.annotation["acts"].append({
            "id": "act-1", "speech_act": "REQUEST", "target_type": "IMPLICIT",
            "target_id": None, "target_formality": "PROJECT_DELIVERABLE", "evidence_ids": [old], "confidence": "supported",
        })
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(any("requires current-source current_message evidence" in e for e in result.validation_errors))

    def test_quoted_current_message_span_is_rejected_when_authored_ranges_are_supplied(self):
        current = "Could you send that today?\n\nEarlier: Please submit the report."
        b = Builder(current)
        authored_end = len("Could you send that today?")
        b.sources[b.source_id]["authored_ranges"] = [{"start": 0, "end": authored_end}]
        b.annotation["project_scope"]["evidence_ids"] = [b.ev("Could you send that today?")]
        quote = b.ev("Please submit the report")
        b.annotation["acts"].append({
            "id": "act-1", "speech_act": "REQUEST", "target_type": "IMPLICIT",
            "target_id": None, "target_formality": "PROJECT_DELIVERABLE", "evidence_ids": [quote], "confidence": "supported",
        })
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(any("outside authored_ranges" in e for e in result.validation_errors))

    def test_contextual_followup_requires_real_prior_source_and_current_chase(self):
        b = Builder("Could you send those figures today?")
        b.sources["old-source"] = {"subject": "Figures", "current_message": "Please send the Q3 cost figures."}
        prior = b.ev("Please send the Q3 cost figures", source_id="old-source")
        current = b.ev("Could you send those figures today?")
        b.annotation["thread_changes"].append({
            "id": "thread-1", "kind": "current_chase", "target_type": "IMPLICIT", "target_id": None,
            "prior_expectation": "context", "context_evidence_ids": [prior], "evidence_ids": [current], "confidence": "supported",
        })
        b.act("REQUEST", "Could you send those figures today?", target_type="THREAD_CHANGE", target_id="thread-1")
        self.assertIn("FOLLOW_UP", b.map().labels)

    def test_context_id_must_not_be_fabricated_or_current_only(self):
        b = Builder("Could you send those figures today?")
        current = b.ev("Could you send those figures today?")
        b.annotation["thread_changes"].append({
            "id": "thread-1", "kind": "current_chase", "target_type": "IMPLICIT", "target_id": None,
            "prior_expectation": "context", "context_evidence_ids": [current], "evidence_ids": [current], "confidence": "supported",
        })
        b.act("REQUEST", "Could you send those figures today?", target_type="THREAD_CHANGE", target_id="thread-1")
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(any("earlier source message" in e for e in result.validation_errors))

    def test_deadline_cannot_target_meeting_or_testing_window(self):
        b = Builder("The review meeting is Friday.")
        m_ev, date_ev, relation_ev = b.ev("review meeting"), b.ev("Friday"), b.ev("meeting is Friday")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "scheduled", "evidence_ids": [m_ev],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.annotation["temporal_entities"].append({"id": "date-1", "kind": "DATE", "evidence_ids": [date_ev], "confidence": "supported"})
        b.annotation["deadlines"].append({
            "id": "deadline-1", "target_type": "MEETING", "target_id": "meeting-1", "due_date_ids": ["date-1"],
            "due_time_ids": [], "due_relation_evidence_ids": [relation_ev], "confidence": "supported",
        })
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(any("expected one of" in e or "action or document" in e for e in result.validation_errors))

    def test_uncertain_deadline_target_or_temporal_expression_is_suppressed(self):
        b = Builder("Please test the new release by Friday.")
        action = b.action("test the new release", confidence="uncertain")
        add_deadline(b, target_id=action)
        result = b.map()
        self.assertNotIn("DEADLINE", result.labels)
        self.assertTrue(result.needs_review)

    def test_deadline_mapper_checks_target_and_temporal_confidence(self):
        b = Builder("Please test the new release by Friday.")
        action = b.action("test the new release")
        due_ev, relation_ev = b.ev("Friday"), b.ev("by Friday")
        b.annotation["temporal_entities"].append({"id": "date-1", "kind": "DATE", "evidence_ids": [due_ev], "confidence": "uncertain"})
        b.annotation["deadlines"].append({
            "id": "deadline-1", "target_type": "ACTION", "target_id": action,
            "due_date_ids": ["date-1"], "due_time_ids": [], "due_relation_evidence_ids": [relation_ev], "confidence": "supported",
        })
        b.act("REQUEST", "by Friday", target_type="DEADLINE", target_id="deadline-1")
        result = b.map()
        self.assertNotIn("DEADLINE", result.labels)
        self.assertIn("deadline_target_or_time_uncertain", result.review_reasons)

    def test_forged_span_is_rejected(self):
        b = Builder("Test 🧪 the release by Friday.")
        action = b.action("Test 🧪 the release")
        add_deadline(b, target_id=action)
        b.annotation["evidence"][0]["text"] = "forged"
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(any("text does not equal" in e for e in result.validation_errors))

    def test_non_bmp_unicode_offsets_use_python_code_points(self):
        text = "Test 🧪 the release by Friday."
        b = Builder(text)
        action = b.action("Test 🧪 the release")
        deadline = add_deadline(b, target_id=action)
        result = b.map()
        self.assertIn("DEADLINE", result.labels)
        Friday = next(ev for ev in b.annotation["evidence"] if ev["text"] == "Friday")
        self.assertEqual(text[Friday["start"]:Friday["end"]], "Friday")
        self.assertEqual(Friday["start"], text.index("Friday"))
        utf16_start = len(text[:Friday["start"]].encode("utf-16-le")) // 2
        self.assertNotEqual(Friday["start"], utf16_start)
        self.assertTrue(deadline)

    def test_missing_refs_unknown_keys_and_globally_duplicate_primitive_ids_fail_closed(self):
        b = Builder("Please test the new release by Friday.")
        action = b.action("test the new release")
        add_deadline(b, target_id=action, relation_text="by Friday")
        bad_ref = copy.deepcopy(b.annotation)
        bad_ref["acts"][0]["target_id"] = "does-not-exist"
        self.assertTrue(map_labels(bad_ref, current_source_id=b.source_id, sources=b.sources).validation_errors)
        extra = copy.deepcopy(b.annotation)
        extra["unexpected"] = True
        self.assertTrue(map_labels(extra, current_source_id=b.source_id, sources=b.sources).validation_errors)
        duplicate = copy.deepcopy(b.annotation)
        duplicate["deadlines"][0]["id"] = duplicate["actions"][0]["id"]
        errors = map_labels(duplicate, current_source_id=b.source_id, sources=b.sources).validation_errors
        self.assertTrue(any("duplicated across" in e for e in errors))

    def test_malformed_scalars_never_raise_type_errors(self):
        b = Builder("Please test the new release by Friday.")
        action = b.action("test the new release")
        add_deadline(b, target_id=action)
        mutations = []
        ev_bad = copy.deepcopy(b.annotation)
        ev_bad["evidence"][0]["source_id"] = []
        mutations.append(ev_bad)
        target_bad = copy.deepcopy(b.annotation)
        target_bad["acts"][0]["target_id"] = ["deadline-1"]
        mutations.append(target_bad)
        target_type_bad = copy.deepcopy(b.annotation)
        target_type_bad["acts"][0]["target_type"] = ["DEADLINE"]
        mutations.append(target_type_bad)
        for annotation in mutations:
            with self.subTest(annotation=annotation):
                result = map_labels(annotation, current_source_id=b.source_id, sources=b.sources)
                self.assertEqual(result.labels, ())
                self.assertTrue(result.validation_errors)

    def test_subject_and_current_message_evidence_are_exactly_typed(self):
        b = Builder("Testing is complete.", subject="Project Orion")
        sub = b.ev("Project Orion", field="subject")
        b.annotation["project_scope"]["evidence_ids"] = [sub]
        status = b.ev("Testing is complete")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "completed", "evidence_ids": [status], "confidence": "supported"})
        b.act("INFORM", "Testing is complete", target_type="STATUS_UPDATE", target_id="status-1")
        self.assertTrue(validate_annotation(b.annotation, current_source_id=b.source_id, sources=b.sources).valid)

    def test_unknown_enums_and_non_applicable_chase_are_rejected(self):
        b = Builder("Could you send those figures today?")
        current = b.ev("Could you send those figures today?")
        b.annotation["thread_changes"].append({
            "id": "thread-1", "kind": "current_chase", "target_type": "IMPLICIT", "target_id": None,
            "prior_expectation": "not_applicable", "context_evidence_ids": [], "evidence_ids": [current], "confidence": "supported",
        })
        b.act("REQUEST", "Could you send those figures today?", target_type="THREAD_CHANGE", target_id="thread-1")
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(any("not_applicable" in e for e in result.validation_errors))

    def test_speech_act_cannot_override_incompatible_meeting_or_document_state(self):
        b = Builder("The meeting is scheduled. The final report was delivered.")
        ev = b.ev("The meeting is scheduled")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "completed", "evidence_ids": [ev],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.act("SCHEDULE", "The meeting is scheduled", target_type="MEETING", target_id="meeting-1")
        doc = b.document("final report", state="delivered")
        b.act("REQUEST", "final report", target_type="DOCUMENT", target_id=doc)
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(result.validation_errors)

    def test_inform_commit_propose_cancel_and_delivery_states_remain_representable(self):
        b = Builder("I will prepare the plan. The review is cancelled. The report was delivered.")
        commit = b.action("prepare the plan", item_id="action-commit", state="committed")
        b.act("COMMIT", "prepare the plan", target_type="ACTION", target_id=commit)
        meeting_ev = b.ev("review is cancelled")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "cancelled", "evidence_ids": [meeting_ev],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.act("CANCEL", "review is cancelled", target_type="MEETING", target_id="meeting-1")
        report = b.document("report", item_id="document-1", state="delivered")
        b.act("DELIVER", "report was delivered", target_type="DOCUMENT", target_id=report)
        result = b.map()
        self.assertIn("MEETING", result.labels)
        self.assertNotIn("ACTION_REQUEST", result.labels)
        self.assertNotIn("REPORT_REQUEST", result.labels)
        self.assertEqual(b.annotation["actions"][0]["state"], "committed")
        self.assertEqual(b.annotation["documents"][0]["state"], "delivered")

    def test_guideline_completed_action_is_status_not_new_request(self):
        b = Builder("Testing of Phase 2 was completed yesterday.")
        ref = b.ev("Testing of Phase 2 was completed yesterday")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "completed", "evidence_ids": [ref], "confidence": "supported"})
        b.act("INFORM", "Testing of Phase 2 was completed yesterday", target_type="STATUS_UPDATE", target_id="status-1")
        self.assertEqual(b.map().labels, ("GENERAL_UPDATE",))

    def test_guideline_request_meeting_proposal_and_wrong_meeting_deadline(self):
        b = Builder("Can we meet next week to review the launch plan?")
        ref = b.ev("meet next week to review the launch plan")
        b.annotation["meetings"].append({
            "id": "meeting-1", "state": "proposed", "evidence_ids": [ref],
            "date_ids": [], "time_ids": [], "participant_actor_ids": [], "confidence": "supported",
        })
        b.act("PROPOSE", "meet next week to review the launch plan", target_type="MEETING", target_id="meeting-1")
        self.assertEqual(b.map().labels, ("MEETING",))

    def test_guideline_report_due_is_deadline_but_document_state_does_not_request(self):
        b = Builder("The final report is due Friday.")
        b.document("final report", state="expected")
        action = b.action("final report", state="committed")
        add_deadline(b, target_id=action, relation_text="due Friday")
        result = b.map()
        self.assertIn("DEADLINE", result.labels)
        self.assertNotIn("REPORT_REQUEST", result.labels)

    def test_guideline_delivery_status_does_not_request_document(self):
        b = Builder("The final report was sent yesterday.")
        doc = b.document("final report", state="delivered")
        b.act("DELIVER", "final report was sent yesterday", target_type="DOCUMENT", target_id=doc)
        self.assertNotIn("REPORT_REQUEST", b.map().labels)

    def test_explicit_departmental_input_and_approval_labels_are_independent(self):
        b = Builder("Finance will send the estimates by Thursday; please approve the plan.")
        dept_ev = b.ev("Finance")
        b.annotation["departments"].append({
            "id": "department-1", "role": "contributor", "named": True,
            "name_evidence_ids": [dept_ev], "evidence_ids": [dept_ev], "confidence": "supported",
        })
        b.act("INFORM", "Finance will send the estimates", target_type="DEPARTMENT", target_id="department-1")
        action = b.action("send the estimates")
        add_deadline(b, target_id=action, due_text="Thursday", relation_text="by Thursday")
        approval_ev = b.ev("approve the plan")
        b.annotation["approvals"].append({
            "id": "approval-1", "state": "requested", "formality": "FORMAL", "target_type": "IMPLICIT",
            "target_id": None, "evidence_ids": [approval_ev], "confidence": "supported",
        })
        b.act("REQUEST", "approve the plan", target_type="APPROVAL", target_id="approval-1")
        self.assertEqual(b.map().labels, ("DEADLINE", "DEPARTMENTAL_INPUT", "APPROVAL"))

    def test_attachment_or_report_mention_does_not_make_report_request(self):
        b = Builder("Attached is the weekly status report.")
        doc = b.document("weekly status report", state="delivered")
        status_ev = b.ev("weekly status report")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "progress", "evidence_ids": [status_ev], "confidence": "supported"})
        b.act("INFORM", "weekly status report", target_type="STATUS_UPDATE", target_id="status-1")
        b.act("DELIVER", "Attached is the weekly status report", target_type="DOCUMENT", target_id=doc)
        result = b.map()
        self.assertIn("GENERAL_UPDATE", result.labels)
        self.assertNotIn("REPORT_REQUEST", result.labels)

    def test_generic_other_status_is_not_accepted_as_general_update(self):
        b = Builder("The project matter has changed.")
        status = b.ev("The project matter has changed")
        b.annotation["status_updates"].append({"id": "status-1", "kind": "other", "evidence_ids": [status], "confidence": "supported"})
        b.act("INFORM", "The project matter has changed", target_type="STATUS_UPDATE", target_id="status-1")
        result = b.map()
        self.assertNotIn("GENERAL_UPDATE", result.labels)
        self.assertTrue(result.needs_review)
        self.assertIn("status_kind_other_uncertain", result.review_reasons)

    def test_no_regex_extraction_from_text(self):
        b = Builder("Please test the new release by Friday.")
        result = b.map()
        self.assertEqual(result.labels, ())
        self.assertTrue(result.needs_review)


if __name__ == "__main__":
    unittest.main()

"""FYP Direct Label Schema V1.1 validator tests with synthetic-only fixtures."""
from __future__ import annotations

import copy
import unittest

from src.fyp_direct_label_v1_1 import (
    EVALUATION_SPAN_TYPES,
    EXTRACTION_SPAN_TYPES,
    SCHEMA,
    SCHEMA_VERSION,
    SPAN_TYPES,
    SUPPORT_SPAN_TYPES,
    validate_annotation,
)


def build_record(label: str, message: str, trigger: str, fields=(), *, target=None, authored_ranges=None):
    source = {
        "source_id": "synthetic-test-email",
        "subject": "Orion project delivery",
        "current_message": message,
        "authored_ranges": authored_ranges if authored_ranges is not None else [{"start": 0, "end": len(message)}],
        "data_origin": "PUBLIC_CORPUS",
    }

    def span(span_id, field, text, span_type):
        value = source[field]
        start = value.index(text)
        return {"id": span_id, "field": field, "start": start, "end": start + len(text), "text": text, "type": span_type}

    spans = [span("scope", "subject", "Orion", "EVIDENCE"), span("trigger", "current_message", trigger, "EVIDENCE")]
    field_ids = []
    for index, (text, span_type) in enumerate(fields):
        span_id = f"field-{index}"
        spans.append(span(span_id, "current_message", text, span_type))
        field_ids.append(span_id)
    annotation = {
        "schema_version": SCHEMA_VERSION,
        "record_id": source["source_id"],
        "current_source_id": source["source_id"],
        "scope": {"value": "PROJECT", "reason": "", "evidence_span_ids": ["scope"]},
        "labels": [label],
        "spans": spans,
        "label_support": [{
            "label": label,
            "evidence_span_ids": ["trigger"],
            "field_span_ids": field_ids,
            "applies_to": "",
            "follow_up_target": target,
            "review_reason": "",
        }],
        "needs_review": False,
        "review_reasons": [],
        "provenance": {
            "data_origin": "PUBLIC_CORPUS", "source_reference": source["source_id"], "synthetic_case_id": None,
            "annotation_tier": "UNSET", "annotation_mode": "UNANNOTATED", "annotator_id": None, "annotated_at": None,
            "blind_prelabels_shown": None, "human_review": None, "ai_assistance": None,
        },
    }
    return source, annotation


def build_scope(scope, labels, message="Routine office logistics."):
    source = {
        "source_id": "scope-test-email", "subject": "Orion project", "current_message": message,
        "authored_ranges": [{"start": 0, "end": len(message)}], "data_origin": "PUBLIC_CORPUS",
    }
    span = {"id": "scope", "field": "subject", "start": 0, "end": 5, "text": "Orion", "type": "EVIDENCE"}
    annotation = {
        "schema_version": SCHEMA_VERSION, "record_id": source["source_id"], "current_source_id": source["source_id"],
        "scope": {"value": scope, "reason": "The message mixes project and routine coordination." if scope == "UNCERTAIN" else "", "evidence_span_ids": ["scope"]},
        "labels": labels, "spans": [span], "label_support": [], "needs_review": scope == "UNCERTAIN",
        "review_reasons": ["Scope needs adjudication."] if scope == "UNCERTAIN" else [],
        "provenance": {
            "data_origin": "PUBLIC_CORPUS", "source_reference": source["source_id"], "synthetic_case_id": None,
            "annotation_tier": "UNSET", "annotation_mode": "UNANNOTATED", "annotator_id": None, "annotated_at": None,
            "blind_prelabels_shown": None, "human_review": None, "ai_assistance": None,
        },
    }
    return source, annotation


class DirectLabelV1_1Tests(unittest.TestCase):
    def test_schema_version_and_eleven_extraction_targets(self):
        self.assertEqual(SCHEMA["properties"]["schema_version"]["const"], SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, "fyp-direct-label-v1.1")
        self.assertEqual(len(EXTRACTION_SPAN_TYPES), 11)
        self.assertEqual(EXTRACTION_SPAN_TYPES, tuple(SCHEMA["x-semantics"]["extraction_span_types"]))
        self.assertEqual(EVALUATION_SPAN_TYPES, EXTRACTION_SPAN_TYPES)
        self.assertEqual(SUPPORT_SPAN_TYPES, ("EVIDENCE",))
        self.assertEqual(len(SPAN_TYPES), 12)
        self.assertNotIn("EVIDENCE", EVALUATION_SPAN_TYPES)
        self.assertTrue(all("EVIDENCE" not in types for types in SCHEMA["x-semantics"]["allowed_field_types"].values()))

    def test_deadline_with_explicit_date_and_implicit_overdue_without_date(self):
        explicit_source, explicit = build_record("DEADLINE", "Please submit the form by Friday.", "by Friday", [("Friday", "DEADLINE_DATE")])
        implicit_source, implicit = build_record("DEADLINE", "The submission is overdue.", "overdue")
        self.assertTrue(validate_annotation(explicit, explicit_source).valid)
        self.assertTrue(validate_annotation(implicit, implicit_source).valid)
        self.assertFalse(implicit["needs_review"])
        self.assertEqual(implicit["label_support"][0]["applies_to"], "")

    def test_meeting_date_does_not_become_deadline(self):
        source, row = build_record("MEETING", "Let's meet on Friday.", "meet on Friday", [("Friday", "MEETING_DATE")])
        self.assertTrue(validate_annotation(row, source).valid)
        self.assertEqual(row["labels"], ["MEETING"])
        self.assertNotIn("DEADLINE", row["labels"])

    def test_report_request_needs_no_forced_document_and_delivery_is_update(self):
        request_source, request = build_record("REPORT_REQUEST", "Please send the revised report.", "send the revised report", [("revised report", "REQUESTED_DOCUMENT")])
        no_doc_source, no_doc = build_record("REPORT_REQUEST", "Please send the file.", "send the file")
        delivered_source, delivered = build_record("GENERAL_UPDATE", "Attached is the report we completed.", "report we completed", [("report", "REQUESTED_DOCUMENT")])
        self.assertTrue(validate_annotation(request, request_source).valid)
        self.assertTrue(validate_annotation(no_doc, no_doc_source).valid)
        self.assertTrue(validate_annotation(delivered, delivered_source).valid)
        self.assertEqual(delivered["labels"], ["GENERAL_UPDATE"])

    def test_department_input_and_department_mention_are_separate_direct_labels(self):
        input_source, department_input = build_record("DEPARTMENTAL_INPUT", "Finance should send the figures.", "Finance should send the figures", [("Finance", "DEPARTMENT"), ("send the figures", "ACTION_ITEM")])
        mention_source, mention = build_record("GENERAL_UPDATE", "Testing is complete. Finance is copied.", "Testing is complete", [("Finance", "DEPARTMENT")])
        self.assertTrue(validate_annotation(department_input, input_source).valid)
        self.assertTrue(validate_annotation(mention, mention_source).valid)
        self.assertEqual(mention["labels"], ["GENERAL_UPDATE"])

    def test_approval_request_does_not_require_target_and_review_is_not_approval(self):
        approval_source, approval = build_record("APPROVAL", "Please approve the revised plan.", "approve the revised plan")
        approved_source, approved = build_record("APPROVAL", "Approved.", "Approved.")
        review_source, review = build_record("ACTION_REQUEST", "Please review the project report.", "review the project report", [("review the project report", "ACTION_ITEM")])
        self.assertTrue(validate_annotation(approval, approval_source).valid)
        self.assertTrue(validate_annotation(approved, approved_source).valid)
        self.assertTrue(validate_annotation(review, review_source).valid)
        self.assertEqual(approval["labels"], ["APPROVAL"])
        self.assertEqual(approved["label_support"][0]["field_span_ids"], [])
        self.assertEqual(review["labels"], ["ACTION_REQUEST"])

    def test_follow_up_requires_current_evidence_but_target_can_be_unstated(self):
        source, row = build_record("FOLLOW_UP", "Reminder: I am still waiting on Finance.", "Reminder: I am still waiting on Finance", target=None)
        self.assertTrue(validate_annotation(row, source).valid)
        self.assertIsNone(row["label_support"][0]["follow_up_target"])

        unclear_source, unclear = build_record("FOLLOW_UP", "Reminder: I am still waiting.", "Reminder: I am still waiting", target="UNCLEAR")
        unclear["label_support"][0]["review_reason"] = "The prior thread does not identify what is pending."
        unclear["needs_review"] = True
        unclear["review_reasons"] = ["Follow-up target needs adjudication."]
        self.assertTrue(validate_annotation(unclear, unclear_source).valid)
        unclear["needs_review"] = False
        unclear["review_reasons"] = []
        self.assertFalse(validate_annotation(unclear, unclear_source).valid)

    def test_action_request_stays_distinct_from_other_acts(self):
        source, row = build_record("ACTION_REQUEST", "Please test the deployment.", "test the deployment", [("test the deployment", "ACTION_ITEM")])
        self.assertTrue(validate_annotation(row, source).valid)
        self.assertEqual(row["labels"], ["ACTION_REQUEST"])

    def test_non_project_exclusivity_and_uncertain_abstention(self):
        source, row = build_scope("NON_PROJECT", ["NON_PROJECT"])
        self.assertTrue(validate_annotation(row, source).valid)
        row["labels"] = ["NON_PROJECT", "MEETING"]
        self.assertFalse(validate_annotation(row, source).valid)

        source, row = build_scope("UNCERTAIN", [])
        self.assertTrue(validate_annotation(row, source).valid)
        row["labels"] = ["GENERAL_UPDATE"]
        self.assertFalse(validate_annotation(row, source).valid)

    def test_quoted_history_cannot_supply_current_message_label_evidence(self):
        message = 'On Tuesday, Alex wrote: "Please send the report."\nI will review it.'
        authored_start = message.index("I will review it.")
        source, row = build_record(
            "REPORT_REQUEST", message, "Please send the report.",
            authored_ranges=[{"start": authored_start, "end": len(message)}],
        )
        result = validate_annotation(row, source)
        self.assertFalse(result.valid)
        self.assertTrue(any("authored_ranges" in error for error in result.errors))

    def test_every_approved_extraction_type_is_accepted(self):
        message = "Meet Monday at 3 PM. Deadline Friday at 5 PM. Send the draft to Alex in Finance with the budget report. Attendees Alex. Agenda budget review for Orion."
        fields = [
            ("Monday", "MEETING_DATE"), ("3 PM", "MEETING_TIME"),
            ("Friday", "DEADLINE_DATE"), ("5 PM", "DEADLINE_TIME"),
            ("Send the draft", "ACTION_ITEM"), ("Alex", "RESPONSIBLE_PARTY"),
            ("Finance", "DEPARTMENT"), ("budget report", "REQUESTED_DOCUMENT"),
            ("Alex", "PARTICIPANT"), ("budget review", "AGENDA"), ("Orion", "PROJECT"),
        ]
        source, row = build_record("GENERAL_UPDATE", message, "Meet Monday", fields)
        result = validate_annotation(row, source)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual({span["type"] for span in row["spans"] if span["type"] != "EVIDENCE"}, set(EXTRACTION_SPAN_TYPES))

    def test_removed_input_and_approval_target_types_are_rejected(self):
        source, row = build_record("GENERAL_UPDATE", "Finance approved the plan.", "approved the plan")
        for index, span_type in enumerate(("INPUT", "APPROVAL_TARGET")):
            invalid = copy.deepcopy(row)
            text = "Finance" if span_type == "INPUT" else "the plan"
            start = source["current_message"].index(text)
            span_id = f"removed-{index}"
            invalid["spans"].append({
                "id": span_id, "field": "current_message", "start": start,
                "end": start + len(text), "text": text, "type": span_type,
            })
            invalid["label_support"][0]["field_span_ids"].append(span_id)
            self.assertFalse(validate_annotation(invalid, source).valid)

    def test_each_direct_project_label_still_requires_current_message_evidence(self):
        source, row = build_record("DEADLINE", "The submission is overdue.", "overdue")
        row["label_support"][0]["evidence_span_ids"] = ["scope"]
        result = validate_annotation(row, source)
        self.assertFalse(result.valid)
        self.assertTrue(any("current_message EVIDENCE trigger" in error for error in result.errors))

    def test_offsets_and_provenance_guards_remain_enforced(self):
        source, row = build_record("APPROVAL", "Please approve the plan.", "approve the plan")
        invalid = copy.deepcopy(row)
        invalid["spans"][1]["text"] = "approve the plans"
        self.assertFalse(validate_annotation(invalid, source).valid)

        gold = copy.deepcopy(row)
        gold["provenance"].update({
            "annotation_tier": "GOLD", "annotation_mode": "BLIND_HUMAN", "annotator_id": "reviewer-a",
            "annotated_at": "2026-10-06T00:00:00Z", "blind_prelabels_shown": False,
            "human_review": {"reviewer_id": "reviewer-b", "reviewed_at": "2026-10-06T01:00:00Z", "decision": "accepted"},
        })
        self.assertTrue(validate_annotation(gold, source).valid)
        gold["provenance"]["human_review"]["reviewer_id"] = "reviewer-a"
        result = validate_annotation(gold, source)
        self.assertFalse(result.valid)
        self.assertTrue(any("different person" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()

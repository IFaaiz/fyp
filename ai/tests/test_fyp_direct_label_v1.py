"""Direct FYP label contract tests; all email strings below are synthetic."""
from __future__ import annotations

import copy
import unittest

from src.fyp_direct_label_v1 import LABELS, SCHEMA, SCHEMA_VERSION, validate_annotation


def build_record():
    body = "Please send the revised report by Friday."
    source = {
        "source_id": "synthetic-test-email",
        "subject": "Project report due Friday",
        "current_message": body,
        "authored_ranges": [{"start": 0, "end": len(body)}],
        "data_origin": "PUBLIC_CORPUS",
    }

    def span(span_id, field, text, span_type):
        content = source[field]
        start = content.index(text)
        return {"id": span_id, "field": field, "start": start, "end": start + len(text), "text": text, "type": span_type}

    annotation = {
        "schema_version": SCHEMA_VERSION,
        "record_id": source["source_id"],
        "current_source_id": source["source_id"],
        "scope": {"value": "PROJECT", "reason": "", "evidence_span_ids": ["scope"]},
        "labels": ["REPORT_REQUEST", "DEADLINE"],
        "spans": [
            span("scope", "subject", "Project", "EVIDENCE"),
            span("trigger", "current_message", "Please send", "EVIDENCE"),
            span("document", "current_message", "revised report", "REQUESTED_DOCUMENT"),
            span("due", "current_message", "Friday", "DEADLINE_DATE"),
        ],
        "label_support": [
            {"label": "REPORT_REQUEST", "evidence_span_ids": ["trigger"], "field_span_ids": ["document"], "applies_to": "", "follow_up_target": None, "review_reason": ""},
            {"label": "DEADLINE", "evidence_span_ids": ["trigger"], "field_span_ids": ["due"], "applies_to": "revised report", "follow_up_target": None, "review_reason": ""},
        ],
        "needs_review": False,
        "review_reasons": [],
        "provenance": {
            "data_origin": "PUBLIC_CORPUS", "source_reference": source["source_id"], "synthetic_case_id": None,
            "annotation_tier": "UNSET", "annotation_mode": "UNANNOTATED", "annotator_id": None, "annotated_at": None,
            "blind_prelabels_shown": None, "human_review": None, "ai_assistance": None,
        },
    }
    return source, annotation


class DirectLabelV1Tests(unittest.TestCase):
    def setUp(self):
        self.source, self.annotation = build_record()

    def validate(self, annotation=None, source=None):
        return validate_annotation(annotation or self.annotation, source or self.source)

    def test_schema_and_direct_multi_label_record(self):
        self.assertEqual(SCHEMA["properties"]["schema_version"]["const"], SCHEMA_VERSION)
        self.assertEqual(LABELS, ("MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT", "ACTION_REQUEST", "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE", "NON_PROJECT"))
        self.assertTrue(self.validate().valid, self.validate().errors)

    def test_each_selected_label_needs_current_message_trigger(self):
        row = copy.deepcopy(self.annotation)
        row["label_support"][0]["evidence_span_ids"] = ["scope"]
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("current_message EVIDENCE trigger" in error for error in result.errors))

    def test_deadline_needs_date_or_time_and_applies_to(self):
        row = copy.deepcopy(self.annotation)
        row["label_support"][1]["field_span_ids"] = []
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("DEADLINE_DATE or DEADLINE_TIME" in error for error in result.errors))
        row["label_support"][1]["review_reason"] = "The date is absent from the source."
        row["spans"] = [span for span in row["spans"] if span["id"] != "due"]
        row["needs_review"] = True
        row["review_reasons"] = ["Deadline evidence needs adjudication."]
        self.assertTrue(self.validate(row).valid, self.validate(row).errors)

    def test_non_project_is_exclusive_and_uncertain_scope_is_review_only(self):
        row = copy.deepcopy(self.annotation)
        row["scope"] = {"value": "NON_PROJECT", "reason": "Routine office logistics.", "evidence_span_ids": ["scope"]}
        row["labels"] = ["NON_PROJECT"]
        row["spans"] = [row["spans"][0]]
        row["label_support"] = []
        self.assertTrue(self.validate(row).valid, self.validate(row).errors)
        row["scope"]["evidence_span_ids"] = []
        row["spans"] = []
        self.assertTrue(self.validate(row).valid, self.validate(row).errors)
        row["scope"]["value"] = "PROJECT"
        row["labels"] = ["NON_PROJECT", "MEETING"]
        self.assertFalse(self.validate(row).valid)

        uncertain = copy.deepcopy(self.annotation)
        uncertain["scope"] = {"value": "UNCERTAIN", "reason": "Project context is unclear.", "evidence_span_ids": ["scope"]}
        uncertain["labels"] = []
        uncertain["spans"] = [uncertain["spans"][0]]
        uncertain["label_support"] = []
        uncertain["needs_review"] = True
        uncertain["review_reasons"] = ["Scope needs adjudication."]
        self.assertTrue(self.validate(uncertain).valid, self.validate(uncertain).errors)
        uncertain["scope"]["evidence_span_ids"] = []
        uncertain["spans"] = []
        self.assertTrue(self.validate(uncertain).valid, self.validate(uncertain).errors)
        uncertain["labels"] = ["GENERAL_UPDATE"]
        self.assertFalse(self.validate(uncertain).valid)

    def test_unicode_offsets_authored_ranges_and_orphan_references(self):
        source = copy.deepcopy(self.source)
        source["current_message"] = "📧 " + source["current_message"]
        source["authored_ranges"] = [{"start": 0, "end": len(source["current_message"])}]
        row = copy.deepcopy(self.annotation)
        for span in row["spans"]:
            if span["field"] == "current_message":
                span["start"] += 2
                span["end"] += 2
        self.assertTrue(self.validate(row, source).valid, self.validate(row, source).errors)
        source["authored_ranges"] = [{"start": 0, "end": 2}]
        self.assertFalse(self.validate(row, source).valid)
        orphaned = copy.deepcopy(self.annotation)
        orphaned["spans"].append({"id": "orphan", "field": "subject", "start": 0, "end": 1, "text": "P", "type": "EVIDENCE"})
        self.assertFalse(self.validate(orphaned).valid)

    def test_follow_up_unclear_requires_review_and_valid_target(self):
        row = copy.deepcopy(self.annotation)
        row["labels"] = ["FOLLOW_UP"]
        row["label_support"] = [{"label": "FOLLOW_UP", "evidence_span_ids": ["trigger"], "field_span_ids": [], "applies_to": "", "follow_up_target": "UNCLEAR", "review_reason": "Prior expectation is unavailable."}]
        row["spans"] = [span for span in row["spans"] if span["id"] in {"scope", "trigger"}]
        row["needs_review"] = True
        row["review_reasons"] = ["Prior context needs adjudication."]
        self.assertTrue(self.validate(row).valid, self.validate(row).errors)
        row["needs_review"] = False
        row["review_reasons"] = []
        self.assertFalse(self.validate(row).valid)

    def test_ai_or_synthetic_and_unresolved_records_cannot_be_gold(self):
        row = copy.deepcopy(self.annotation)
        row["provenance"].update({
            "annotation_tier": "GOLD", "annotation_mode": "BLIND_HUMAN", "annotator_id": "a",
            "annotated_at": "2026-10-06T00:00:00Z", "blind_prelabels_shown": False,
            "human_review": {"reviewer_id": "b", "reviewed_at": "2026-10-06T01:00:00Z", "decision": "accepted"},
        })
        self.assertTrue(self.validate(row).valid, self.validate(row).errors)
        row["needs_review"] = True
        row["review_reasons"] = ["Field ambiguity remains."]
        self.assertFalse(self.validate(row).valid)
        row["needs_review"] = False
        row["review_reasons"] = []
        row["provenance"]["annotation_mode"] = "AI_ONLY"
        row["provenance"].update({"annotator_id": None, "annotated_at": None, "blind_prelabels_shown": None, "human_review": None})
        row["provenance"]["ai_assistance"] = {
            "provider": "test-provider", "model": "test-model", "checkpoint": None,
            "protocol_version": "v1", "run_id": "run-1", "timestamp": "2026-10-06T00:00:00Z",
            "human_disposition": "accepted",
        }
        self.assertFalse(self.validate(row).valid)

        synthetic_source = copy.deepcopy(self.source)
        synthetic_source.update(data_origin="SYNTHETIC", synthetic_case_id="case-1")
        synthetic = copy.deepcopy(self.annotation)
        synthetic["provenance"].update({
            "data_origin": "SYNTHETIC", "source_reference": None, "synthetic_case_id": "case-1",
            "annotation_tier": "GOLD", "annotation_mode": "BLIND_HUMAN", "annotator_id": "a",
            "annotated_at": "2026-10-06T00:00:00Z", "blind_prelabels_shown": False,
            "human_review": {"reviewer_id": "b", "reviewed_at": "2026-10-06T01:00:00Z", "decision": "accepted"},
        })
        self.assertFalse(self.validate(synthetic, synthetic_source).valid)

    def test_gold_requires_separate_reviewer(self):
        row = copy.deepcopy(self.annotation)
        row["provenance"].update({
            "annotation_tier": "GOLD", "annotation_mode": "BLIND_HUMAN", "annotator_id": "same-person",
            "annotated_at": "2026-10-06T00:00:00Z", "blind_prelabels_shown": False,
            "human_review": {"reviewer_id": "same-person", "reviewed_at": "2026-10-06T01:00:00Z", "decision": "accepted"},
        })
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("different person" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()

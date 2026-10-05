"""Contract tests for the isolated V1 schema, validator and mapper.

All message strings in this file and its JSONL fixtures are synthetic; no corpus
text or protected evaluation records are used.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.fyp_structured_v1 import LABELS, derive_labels, validate_annotation
from src.fyp_structured_v1 import validation as validation_module


ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "annotation" / "fyp_structured_v1_synthetic_examples.jsonl"
SCHEMA_PATH = ROOT / "config" / "fyp_structured_v1_schema.json"


def load_fixtures():
    return [json.loads(line) for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def fixture_inputs(row):
    sources = {
        row["source"]["source_id"]: row["source"],
        **{item["source_id"]: item for item in row.get("context_sources", [])},
    }
    context = {
        item["source_id"]: {
            "current_source_id": item["source_id"],
            "events": item.get("events", []),
        }
        for item in row.get("context_sources", [])
    }
    return sources, context


class StructuredV1ContractTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = {row["fixture_id"]: row for row in load_fixtures()}

    def validate(self, row, *, context_override=None, evaluation=False):
        sources, context = fixture_inputs(row)
        if context_override is not None:
            context = context_override
        return validate_annotation(row["annotation"], sources, context, evaluation=evaluation)

    def test_schema_and_all_synthetic_fixtures_are_machine_readable(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "fyp-structured-v1")
        self.assertEqual(
            LABELS,
            ("MEETING", "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT",
             "ACTION_REQUEST", "FOLLOW_UP", "APPROVAL", "GENERAL_UPDATE", "NON_PROJECT"),
        )
        for row in self.fixtures.values():
            with self.subTest(fixture=row["fixture_id"]):
                result = self.validate(row)
                self.assertTrue(result.valid, result.errors)
                self.assertEqual(derive_labels(row["annotation"]), row["expected_derived_labels"])

    def test_stdlib_fallback_applies_ref_sibling_min_items_constraints(self):
        scope_row = copy.deepcopy(self.fixtures["routine_corporate_operations"])
        scope_row["annotation"]["scope"]["evidence_span_ids"] = []
        sources, context = fixture_inputs(scope_row)
        with patch.object(validation_module, "jsonschema", None):
            scope_result = validate_annotation(scope_row["annotation"], sources, context)
        self.assertFalse(scope_result.valid)
        self.assertTrue(any("scope.evidence_span_ids" in error and "fewer items" in error for error in scope_result.errors))

        relation_row = copy.deepcopy(self.fixtures["follow_up_with_quoted_history"])
        relation_row["annotation"]["event_relations"][0]["evidence_span_ids"] = []
        sources, context = fixture_inputs(relation_row)
        with patch.object(validation_module, "jsonschema", None):
            relation_result = validate_annotation(relation_row["annotation"], sources, context)
        self.assertFalse(relation_result.valid)
        self.assertTrue(any("evidence_span_ids" in error and "fewer items" in error for error in relation_result.errors))

    def test_unicode_offsets_are_python_code_points(self):
        row = copy.deepcopy(self.fixtures["document_request_with_deadline"])
        body = row["source"]["current_message"].replace("Please send", "📧 Please send")
        row["source"]["current_message"] = body
        row["source"]["authored_ranges"] = [{"start": 0, "end": len(body)}]
        for span in row["annotation"]["spans"]:
            content = row["source"][span["field"]]
            span["start"] = content.index(span["text"])
            span["end"] = span["start"] + len(span["text"])
        trigger = next(span for span in row["annotation"]["spans"] if span["id"] == "trigger")
        self.assertEqual(trigger["start"], body.index("Please send"))
        self.assertEqual(self.validate(row).errors, ())

    def test_subject_span_cannot_anchor_an_event(self):
        row = copy.deepcopy(self.fixtures["document_request_with_deadline"])
        trigger = next(span for span in row["annotation"]["spans"] if span["id"] == "trigger")
        trigger["field"] = "subject"
        trigger["text"] = row["source"]["subject"]
        trigger["start"] = 0
        trigger["end"] = len(trigger["text"])
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("EVENT_ANCHOR" in error for error in result.errors))

    def test_quoted_history_is_excluded_by_authored_ranges_and_context_ids_resolve(self):
        row = copy.deepcopy(self.fixtures["follow_up_with_quoted_history"])
        self.assertTrue(self.validate(row).valid)
        current = row["source"]["current_message"]
        quoted_start = current.index("Tuesday")
        date_span = next(span for span in row["annotation"]["spans"] if span["id"] == "date")
        date_span["text"] = "Tuesday"
        date_span["start"] = quoted_start
        date_span["end"] = quoted_start + len("Tuesday")
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("authored_ranges" in error for error in result.errors))

    def test_duplicate_ids_links_and_unresolved_refs_are_hard_errors(self):
        row = copy.deepcopy(self.fixtures["document_request_with_deadline"])
        row["annotation"]["spans"][1]["id"] = row["annotation"]["spans"][0]["id"]
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("duplicate ID" in error for error in result.errors))

        row = copy.deepcopy(self.fixtures["document_request_with_deadline"])
        row["annotation"]["event_span_links"].append(copy.deepcopy(row["annotation"]["event_span_links"][0]))
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("duplicate event-span-role" in error for error in result.errors))

        row = copy.deepcopy(self.fixtures["document_request_with_deadline"])
        duplicate = copy.deepcopy(row["annotation"]["spans"][0])
        duplicate["id"] = "duplicate-coordinate"
        row["annotation"]["spans"].append(duplicate)
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("duplicates span coordinates" in error for error in result.errors))

        row = copy.deepcopy(self.fixtures["follow_up_with_quoted_history"])
        result = self.validate(row, context_override={})
        self.assertFalse(result.valid)
        self.assertTrue(any("does not resolve" in error for error in result.errors))

    def test_role_span_and_event_kind_mismatches_are_rejected(self):
        row = copy.deepcopy(self.fixtures["meeting_date_not_deadline"])
        meeting_link = next(link for link in row["annotation"]["event_span_links"] if link["role"] == "MEETING_NAME")
        meeting_link["role"] = "ACTION"
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("incompatible" in error for error in result.errors))

    def test_non_project_is_exclusive_and_supported_non_project_needs_no_review(self):
        row = self.fixtures["routine_corporate_operations"]
        result = self.validate(row)
        self.assertTrue(result.valid, result.errors)
        self.assertFalse(result.needs_review)
        self.assertEqual(derive_labels(row["annotation"]), ["NON_PROJECT"])

        row = copy.deepcopy(row)
        row["annotation"]["events"].append({
            "id": "action-1", "kind": "ACTION", "state": "requested",
            "certainty": "SUPPORTED", "action_class": "OPERATIONAL",
        })
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("events" in error or "NON_PROJECT" in error for error in result.errors))

    def test_gold_requires_real_human_review_provenance_and_never_allows_synthetic_gold(self):
        row = copy.deepcopy(self.fixtures["document_request_with_deadline"])
        provenance = row["annotation"]["provenance"]
        provenance.update({
            "annotation_tier": "GOLD",
            "annotation_mode": "AI_ONLY",
            "annotator_id": None,
            "annotated_at": None,
            "blind_prelabels_shown": None,
            "human_review": None,
        })
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("GOLD" in error or "synthetic" in error.lower() for error in result.errors))

    def test_synthetic_cannot_enter_evaluation(self):
        row = self.fixtures["document_request_with_deadline"]
        result = self.validate(row, evaluation=True)
        self.assertFalse(result.valid)
        self.assertTrue(any("evaluation" in error for error in result.errors))

    def test_valid_uncertainty_is_a_review_warning_and_mapper_abstains(self):
        row = self.fixtures["follow_up_unresolved_prior"]
        result = self.validate(row)
        self.assertTrue(result.valid, result.errors)
        self.assertTrue(result.needs_review)
        self.assertTrue(result.warnings)
        self.assertEqual(derive_labels(row["annotation"]), [])

    def test_shared_arguments_link_to_each_event_without_span_duplication(self):
        row = self.fixtures["two_events_shared_owner_and_deadline"]
        annotation = row["annotation"]
        owner_links = [link for link in annotation["event_span_links"] if link["span_id"] == "owner"]
        date_links = [link for link in annotation["event_span_links"] if link["span_id"] == "date"]
        self.assertEqual(len(owner_links), 2)
        self.assertEqual(len(date_links), 2)
        self.assertTrue(self.validate(row).valid)
        self.assertEqual(derive_labels(annotation), ["DEADLINE", "REPORT_REQUEST", "ACTION_REQUEST"])

    def test_report_delivery_and_ordinary_date_do_not_become_request_or_deadline(self):
        delivery = self.fixtures["document_delivery_not_request"]
        self.assertEqual(self.validate(delivery).errors, ())
        self.assertEqual(derive_labels(delivery["annotation"]), ["GENERAL_UPDATE"])

        completed = self.fixtures["completed_action_is_status"]
        self.assertEqual(self.validate(completed).errors, ())
        self.assertEqual(derive_labels(completed["annotation"]), ["GENERAL_UPDATE"])

    def test_follow_up_and_supersession_use_real_prior_event_references(self):
        follow = self.fixtures["follow_up_with_quoted_history"]
        self.assertTrue(self.validate(follow).valid)
        self.assertEqual(derive_labels(follow["annotation"]), ["DEADLINE", "REPORT_REQUEST", "FOLLOW_UP"])

        moved = self.fixtures["meeting_rescheduled_supersedes"]
        self.assertTrue(self.validate(moved).valid)
        self.assertEqual(derive_labels(moved["annotation"]), ["MEETING"])

    def test_scope_evidence_must_reference_a_current_source_span(self):
        row = copy.deepcopy(self.fixtures["follow_up_with_quoted_history"])
        context_source = row["context_sources"][0]
        context_text = context_source["current_message"]
        prior_span = {
            "id": "prior-span",
            "source_id": context_source["source_id"],
            "field": "current_message",
            "type": "DOCUMENT",
            "text": "Orion report",
            "start": context_text.index("Orion report"),
            "end": context_text.index("Orion report") + len("Orion report"),
        }
        row["annotation"]["spans"].append(prior_span)
        row["annotation"]["scope"]["evidence_span_ids"] = ["prior-span"]
        result = self.validate(row)
        self.assertFalse(result.valid)
        self.assertTrue(any("must refer to current_source_id" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()

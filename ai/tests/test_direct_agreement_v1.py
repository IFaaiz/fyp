from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from scripts.compare_direct_annotations_v1 import (  # noqa: E402
    _maximum_overlap_pairs,
    compare_direct_records,
    load_annotations,
)


def _record(
    source_id: str,
    annotator: str,
    *,
    message: str = "Please send revised report by Friday.",
    scope: str = "PROJECT",
    labels: list[str] | None = None,
    spans: list[dict] | None = None,
    needs_review: bool = False,
) -> dict:
    labels = list(labels or [])
    spans = [{
        "id": "scope-evidence", "field": "current_message", "start": 0, "end": 6,
        "text": message[:6], "type": "EVIDENCE",
    }, *(copy.deepcopy(spans or []))]
    support = [
        {
            "label": label,
            "evidence_span_ids": ["scope-evidence"],
            "field_span_ids": [s["id"] for s in spans if s["id"] != "scope-evidence"],
            "applies_to": "",
            "follow_up_target": None,
            "review_reason": "",
        }
        for label in labels
    ]
    return {
        "schema_version": "fyp-direct-label-v1",
        "record_id": source_id,
        "current_source_id": source_id,
        "scope": {"value": scope, "reason": "Specific project deliverable.",
                  "evidence_span_ids": ["scope-evidence"]},
        "labels": labels,
        "spans": spans,
        "label_support": support,
        "needs_review": needs_review,
        "review_reasons": ["Scope needs adjudication."] if needs_review else [],
        "provenance": {
            "data_origin": "PUBLIC_CORPUS",
            "source_reference": source_id,
            "synthetic_case_id": None,
            "annotation_tier": "UNSET",
            "annotation_mode": "BLIND_HUMAN",
            "annotator_id": annotator,
            "annotated_at": "2026-10-06T12:00:00Z",
            "blind_prelabels_shown": False,
            "human_review": None,
            "ai_assistance": None,
        },
    }


class DirectAgreementTests(unittest.TestCase):
    def test_metrics_separate_unresolved_scope_and_match_spans_one_to_one(self):
        message = "Please send revised report by Friday."
        start_report = message.index("revised report")
        start_report_b = message.index("report")
        start_friday = message.index("Friday")
        a1 = _record("case-1", "human-a", message=message,
                     labels=["REPORT_REQUEST", "DEADLINE"], spans=[
                         {"id": "a-doc", "field": "current_message", "start": start_report,
                          "end": start_report + len("revised report"), "text": "revised report",
                          "type": "REQUESTED_DOCUMENT"},
                         {"id": "a-date", "field": "current_message", "start": start_friday,
                          "end": start_friday + len("Friday"), "text": "Friday", "type": "DEADLINE_DATE"},
                     ])
        b1 = _record("case-1", "human-b", message=message,
                     labels=["DEADLINE", "REPORT_REQUEST"], spans=[
                         {"id": "b-doc", "field": "current_message", "start": start_report_b,
                          "end": start_report_b + len("report"), "text": "report",
                          "type": "REQUESTED_DOCUMENT"},
                         {"id": "b-date", "field": "current_message", "start": start_friday,
                          "end": start_friday + len("Friday"), "text": "Friday", "type": "DEADLINE_DATE"},
                     ])
        a2 = _record("case-2", "human-a", labels=["ACTION_REQUEST"])
        b2 = _record("case-2", "human-b", labels=[])
        a3 = _record("case-3", "human-a", labels=[])
        b3 = _record("case-3", "human-b", scope="UNCERTAIN", labels=[], needs_review=True)

        report = compare_direct_records([a1, a2, a3], [b1, b2, b3])

        self.assertEqual(report["scope"]["agreements"], 2)
        self.assertEqual(report["scope"]["paired_records"], 3)
        self.assertEqual(report["review_status"]["eligible_pairs"], 2)
        self.assertEqual(report["review_status"]["excluded_uncertain_scope_pairs"], 1)
        self.assertEqual(report["labels"]["exact_multilabel_set"]["agreements"], 1)
        self.assertEqual(report["labels"]["exact_multilabel_set"]["eligible_records"], 2)
        self.assertEqual(report["labels"]["per_label"]["ACTION_REQUEST"]["a_only"], 1)
        self.assertEqual(report["labels"]["micro_f1"]["f1"], 0.8)
        self.assertEqual(report["spans"]["exact_micro"]["f1"], 0.75)
        self.assertEqual(report["spans"]["overlap_micro"]["f1"], 1.0)
        self.assertEqual(report["spans"]["overlap_micro"]["tp"], 4)
        self.assertEqual(report["gold_annotations_scored"], 0)

    def test_review_flag_and_support_review_reason_are_excluded(self):
        a = _record("case-1", "human-a", labels=["FOLLOW_UP"], needs_review=True)
        b = _record("case-1", "human-b", labels=["FOLLOW_UP"])
        report = compare_direct_records([a], [b])
        self.assertEqual(report["review_status"]["eligible_pairs"], 0)
        self.assertEqual(report["review_status"]["excluded_needs_review_pairs"], 1)
        self.assertEqual(report["labels"]["per_label"]["FOLLOW_UP"]["eligible_records"], 0)

    def test_label_support_relations_are_scored_separately(self):
        a = _record("case-1", "human-a", labels=["FOLLOW_UP"])
        b = _record("case-1", "human-b", labels=["FOLLOW_UP"])
        a["label_support"][0]["applies_to"] = "the report"
        b["label_support"][0]["applies_to"] = "the report"
        a["label_support"][0]["follow_up_target"] = "DOCUMENT_REQUEST"
        b["label_support"][0]["follow_up_target"] = "TASK"

        report = compare_direct_records([a], [b])

        self.assertEqual(report["labels"]["micro_f1"]["f1"], 1.0)
        self.assertEqual(report["relations"]["label_support_links"]["micro_f1"]["f1"], 0.5)
        self.assertEqual(report["relations"]["label_support_links"]["items"], {"A": 2, "B": 2})

    def test_source_hash_mismatch_is_rejected(self):
        a = _record("case-1", "human-a")
        b = _record("case-1", "human-b")
        a["source"] = {"source_id": "case-1", "source_sha256": "a" * 64}
        b["source"] = {"source_id": "case-1", "source_sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "source hashes differ"):
            compare_direct_records([a], [b])

    def test_raw_direct_jsonl_uses_current_source_id_and_record_id(self):
        record = _record("case-1", "human-a")
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "reviewer-a.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            loaded = load_annotations(path)
        self.assertEqual(loaded.records[0]["__source_id"], "case-1")

    def test_current_source_and_record_ids_must_match(self):
        a = _record("case-1", "human-a")
        a["record_id"] = "different-record"
        with self.assertRaisesRegex(ValueError, "record_id and current_source_id"):
            compare_direct_records([a], [_record("case-1", "human-b")])

    def test_source_id_sets_must_match(self):
        a = _record("case-a", "human-a")
        b = _record("case-b", "human-b")
        with self.assertRaisesRegex(ValueError, "source ID sets differ"):
            compare_direct_records([a], [b])

    def test_duplicate_source_id_is_rejected(self):
        a = _record("case-1", "human-a")
        b = _record("case-1", "human-a")
        with self.assertRaisesRegex(ValueError, "duplicate source_id"):
            compare_direct_records([a, b], [a])

    def test_schema_mismatch_is_rejected(self):
        record = _record("case-1", "human-a")
        record["schema_version"] = "fyp-structured-v1"
        with self.assertRaisesRegex(ValueError, "schema_version"):
            compare_direct_records([record], [_record("case-1", "human-b")])

    def test_maximum_overlap_matching_does_not_reuse_a_span(self):
        left = [
            {"field": "current_message", "type": "ACTION_ITEM", "start": 0, "end": 10},
            {"field": "current_message", "type": "ACTION_ITEM", "start": 0, "end": 4},
        ]
        right = [
            {"field": "current_message", "type": "ACTION_ITEM", "start": 1, "end": 3},
            {"field": "current_message", "type": "ACTION_ITEM", "start": 5, "end": 8},
        ]
        pairs = _maximum_overlap_pairs(left, right)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len({i for i, _, _ in pairs}), 2)
        self.assertEqual(len({j for _, j, _ in pairs}), 2)

    def test_literal_app_export_selects_reviewer_and_skips_holdout_before_decode(self):
        direct = _record("case-train", "reviewer-a", labels=[])
        source_text = "Please send revised report by Friday."
        payload = {
            "schema_version": "fyp-calibration-export-v2",
            "sources": [
                {"source_id": "case-train", "source_sha256": "a" * 64,
                 "subject": "Orion project", "current_message": source_text,
                 "authored_ranges": [{"start": 0, "end": len(source_text)}],
                 "allocation": "calibration_training"},
                {"source_id": "case-holdout", "source_sha256": "b" * 64,
                 "subject": "private", "current_message": "private", "allocation": "labeler_human_holdout"},
            ],
            "reviews": [
                {"source_id": "case-train", "user_id": "reviewer-a", "status": "submitted",
                 "annotation_json": json.dumps(direct)},
                {"source_id": "case-holdout", "user_id": "reviewer-a", "status": "submitted",
                 "annotation_json": "this must not be decoded"},
                {"source_id": "case-train", "user_id": "reviewer-b", "status": "submitted",
                 "annotation_json": json.dumps(_record("case-train", "reviewer-b", labels=[]))},
            ],
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "app-export.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_annotations(path, "reviewer-a")
        self.assertEqual(len(loaded.records), 1)
        self.assertEqual(loaded.records[0]["__source_id"], "case-train")
        self.assertEqual(loaded.heldout_rows_excluded, 1)
        self.assertEqual(loaded.reviewer_ids, {"reviewer-a"})

    def test_app_source_manifest_must_match_annotation_identity(self):
        direct = _record("other-case", "reviewer-a", labels=[])
        payload = {
            "schema_version": "fyp-calibration-export-v2",
            "sources": [{"source_id": "case-train", "source_sha256": "a" * 64,
                         "subject": "Orion project", "current_message": "Please send revised report by Friday.",
                         "allocation": "blind_agreement"}],
            "reviews": [{"source_id": "case-train", "user_id": "reviewer-a", "status": "submitted",
                         "annotation_json": json.dumps(direct)}],
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "app-export.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match its app-export source row"):
                load_annotations(path, "reviewer-a")

    def test_non_project_is_exclusive_and_uncertain_must_abstain(self):
        invalid = _record("case-1", "human-a", scope="NON_PROJECT", labels=["ACTION_REQUEST"])
        with self.assertRaisesRegex(ValueError, "NON_PROJECT scope"):
            compare_direct_records([invalid], [_record("case-1", "human-b")])


if __name__ == "__main__":
    unittest.main()

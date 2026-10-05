"""Synthetic-only tests for the source-private V1 agreement scorer."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts.score_fyp_calibration_v1 import ExportError, compute_agreement_metrics, score_export


ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "annotation" / "fyp_structured_v1_synthetic_examples.jsonl"


def fixtures():
    return {
        row["fixture_id"]: row
        for row in (
            json.loads(line)
            for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


USERS = ["synthetic-reviewer-a", "synthetic-reviewer-b", "synthetic-reviewer-c"]
TEST_TIMESTAMP = "2026-10-01T12:00:00Z"


def site_annotation(fixture, user_id, source_id=None):
    """Adapt hand-authored synthetic test data to the Site export contract.

    PUBLIC_CORPUS is a placeholder used only to exercise provenance validation
    on this synthetic fixture. It is not an external corpus or accuracy claim.
    """
    annotation = copy.deepcopy(fixture["annotation"])
    source_id = source_id or fixture["source"]["source_id"]
    annotation["current_source_id"] = source_id
    for span in annotation["spans"]:
        span["source_id"] = source_id
    annotation["provenance"] = {
        "data_origin": "PUBLIC_CORPUS",
        "source_reference": source_id,
        "synthetic_case_id": None,
        "annotation_tier": "UNSET",
        "annotation_mode": "BLIND_HUMAN",
        "annotator_id": user_id,
        "annotated_at": TEST_TIMESTAMP,
        "blind_prelabels_shown": False,
        "human_review": None,
        "ai_assistance": None,
    }
    return annotation


def site_export(fixture, include_excluded=False):
    """Build an export-shaped fixture using local synthetic text only."""
    base_source = fixture["source"]
    source_ids = [(base_source["source_id"], "blind_agreement")]
    if include_excluded:
        source_ids.extend([
            ("SYN-training-source", "calibration_training"),
            ("SYN-holdout-source", "labeler_human_holdout"),
        ])
    sources = []
    for index, (source_id, allocation) in enumerate(source_ids):
        sources.append({
            **base_source,
            "source_id": source_id,
            "allocation": allocation,
            "common_blind": 1 if allocation == "blind_agreement" else 0,
            "owner_slot": index,
        })

    reviews = []
    for source_id, allocation in source_ids:
        for index, user_id in enumerate(USERS):
            annotation = site_annotation(fixture, user_id, source_id)
            reviews.append({
                "source_id": source_id,
                "user_id": user_id,
                "annotation_json": json.dumps(annotation, ensure_ascii=False),
                "status": "submitted",
                "revision": 1,
                "active_ms": (index + 1) * 60_000,
                "created_at": TEST_TIMESTAMP,
            })
    return {
        "schema_version": "fyp-calibration-export-v1",
        "annotation_tier": "UNSET",
        "gold_count": 0,
        "sources": sources,
        "reviewers": [
            {"user_id": user_id, "display_name": f"Synthetic Reviewer {index + 1}", "slot": index}
            for index, user_id in enumerate(USERS)
        ],
        "reviews": reviews,
    }


class CalibrationAgreementTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = fixtures()

    def test_scope_fleiss_kappa_and_unanimity_for_three_synthetic_ratings(self):
        annotation = self.fixtures["meeting_date_not_deadline"]["annotation"]
        result = compute_agreement_metrics({"synthetic-only": [annotation, copy.deepcopy(annotation), copy.deepcopy(annotation)]})
        scope = result["scope"]
        self.assertEqual(scope["reviewers_per_item"], 3)
        self.assertEqual(scope["unanimous_items"], 1)
        self.assertEqual(scope["unanimity_rate"], 1.0)
        # With only one scope category present, chance agreement is 1 and kappa is undefined.
        self.assertIsNone(scope["fleiss_kappa"])

    def test_multi_label_pairwise_agreement_reports_support_and_disagreement(self):
        annotation = self.fixtures["meeting_date_not_deadline"]["annotation"]
        abstaining = copy.deepcopy(annotation)
        abstaining["needs_review"] = True
        abstaining["review_reasons"] = ["synthetic test uncertainty"]
        result = compute_agreement_metrics({"synthetic-only": [annotation, copy.deepcopy(annotation), abstaining]})
        labels = result["derived_multi_label"]
        self.assertEqual(labels["source_reviewer_pairs"], 3)
        self.assertEqual(labels["exact_label_set_agreements"], 1)
        meeting = labels["per_label"]["MEETING"]
        self.assertEqual(meeting["both_positive"], 1)
        self.assertEqual(meeting["positive_union_support"], 3)
        self.assertEqual(meeting["pairwise_positive_agreement"], 0.5)

    def test_span_boundary_and_event_role_tuples_are_scored_exactly(self):
        annotation = self.fixtures["meeting_date_not_deadline"]["annotation"]
        shifted = copy.deepcopy(annotation)
        non_anchor = next(span for span in shifted["spans"] if span["type"] == "DATE")
        non_anchor["start"] += 1
        non_anchor["end"] += 1
        result = compute_agreement_metrics({"synthetic-only": [annotation, copy.deepcopy(annotation), shifted]})
        self.assertLess(result["span_type_and_exact_boundary_pairwise"]["f1"], 1.0)
        self.assertLess(result["event_role_linked_tuples_pairwise"]["f1"], 1.0)

    def test_event_role_canonicalization_ignores_annotator_local_ids(self):
        annotation = self.fixtures["meeting_date_not_deadline"]["annotation"]
        renamed = copy.deepcopy(annotation)
        span_ids = {span["id"]: f"other-{span['id']}" for span in renamed["spans"]}
        event_ids = {event["id"]: f"other-{event['id']}" for event in renamed["events"]}
        for span in renamed["spans"]:
            span["id"] = span_ids[span["id"]]
        for event in renamed["events"]:
            event["id"] = event_ids[event["id"]]
        for link in renamed["event_span_links"]:
            link["span_id"] = span_ids[link["span_id"]]
            link["event_id"] = event_ids[link["event_id"]]
        for span_id in renamed["scope"]["evidence_span_ids"]:
            renamed["scope"]["evidence_span_ids"][renamed["scope"]["evidence_span_ids"].index(span_id)] = span_ids[span_id]
        result = compute_agreement_metrics({"synthetic-only": [annotation, annotation, renamed]})
        self.assertEqual(result["event_instances_pairwise"]["f1"], 1.0)
        self.assertEqual(result["event_role_linked_tuples_pairwise"]["f1"], 1.0)

    def test_median_active_minutes_uses_only_nonnegative_integer_times(self):
        annotation = self.fixtures["routine_corporate_operations"]["annotation"]
        result = compute_agreement_metrics({"synthetic-only": [annotation, annotation, annotation]}, [60_000, 120_000, 600_000])
        self.assertEqual(result["active_time"]["median_active_minutes"], 2.0)
        self.assertEqual(result["active_time"]["timed_reviews"], 3)

    def test_incomplete_export_returns_waiting_counts_without_metrics_or_private_values(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        source = fixture["source"]
        payload = site_export(fixture, include_excluded=True)
        payload["reviews"] = [
            {"source_id": source["source_id"], "user_id": USERS[0], "status": "draft", "revision": 1},
            {"source_id": source["source_id"], "user_id": USERS[1], "status": "in_progress", "revision": 1},
        ]
        report = score_export(payload)
        serialized = json.dumps(report, sort_keys=True)
        self.assertEqual(report["status"], "waiting")
        self.assertEqual(report["metrics_scope"], "blind_agreement_only")
        self.assertEqual(report["gold_annotations_scored"], 0)
        self.assertIsNone(report["metrics"])
        self.assertEqual(report["source_counts"]["labeler_human_holdout_sealed_excluded"], 1)
        self.assertEqual(report["common_blind_progress"]["status_counts"]["missing"], 1)
        for private_value in (
            source["source_id"], source["current_message"], USERS[0],
            "SYN-training-source", "SYN-holdout-source", "Synthetic Reviewer 1",
        ):
            self.assertNotIn(private_value, serialized)

    def test_complete_report_is_aggregate_only_and_stays_provisional(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        source = fixture["source"]
        payload = site_export(fixture, include_excluded=True)
        report = score_export(payload)
        serialized = json.dumps(report, sort_keys=True)
        self.assertEqual(report["status"], "complete_provisional")
        self.assertEqual(report["metrics_scope"], "blind_agreement_only")
        self.assertEqual(report["gold_annotations_scored"], 0)
        self.assertEqual(report["gold_promotion"], "not_automatic")
        self.assertEqual(report["source_counts"]["labeler_human_holdout_sealed_excluded"], 1)
        self.assertEqual(report["source_counts"]["calibration_training_excluded"], 1)
        self.assertEqual(report["metrics"]["scope"]["items"], 1)
        self.assertEqual(report["metrics"]["review_and_abstention"]["annotation_count"], 3)
        self.assertEqual(report["metrics"]["scope"]["unanimity_rate"], 1.0)
        for private_value in (
            source["source_id"], source["current_message"], *USERS,
            "SYN-training-source", "SYN-holdout-source", "Synthetic Reviewer 1",
        ):
            self.assertNotIn(private_value, serialized)

    def test_literal_site_export_shape_scores_unmocked(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        source = fixture["source"]
        users = [
            {"user_id": "synthetic-reviewer-a", "display_name": "Synthetic Reviewer 1", "slot": 0},
            {"user_id": "synthetic-reviewer-b", "display_name": "Synthetic Reviewer 2", "slot": 1},
            {"user_id": "synthetic-reviewer-c", "display_name": "Synthetic Reviewer 3", "slot": 2},
        ]
        reviews = []
        for reviewer in users:
            annotation = copy.deepcopy(fixture["annotation"])
            annotation["provenance"] = {
                "data_origin": "PUBLIC_CORPUS",  # Synthetic fixture placeholder; no external data or accuracy claim.
                "source_reference": source["source_id"],
                "synthetic_case_id": None,
                "annotation_tier": "UNSET",
                "annotation_mode": "BLIND_HUMAN",
                "annotator_id": reviewer["user_id"],
                "annotated_at": TEST_TIMESTAMP,
                "blind_prelabels_shown": False,
                "human_review": None,
                "ai_assistance": None,
            }
            reviews.append({
                "source_id": source["source_id"],
                "user_id": reviewer["user_id"],
                "annotation_json": json.dumps(annotation, ensure_ascii=False),
                "status": "submitted",
                "revision": 1,
                "active_ms": 60_000,
                "created_at": TEST_TIMESTAMP,
            })
        payload = {
            "schema_version": "fyp-calibration-export-v1",
            "annotation_tier": "UNSET",
            "gold_count": 0,
            "sources": [{
                "source_id": source["source_id"],
                "subject": source["subject"],
                "current_message": source["current_message"],
                "authored_ranges": source["authored_ranges"],
                "allocation": "blind_agreement",
                "common_blind": 1,
                "owner_slot": 0,
            }],
            "reviewers": users,
            "reviews": reviews,
        }
        report = score_export(payload)
        self.assertEqual(report["status"], "complete_provisional")
        self.assertEqual(report["gold_annotations_scored"], 0)
        self.assertEqual(report["metrics"]["scope"]["items"], 1)

    def test_site_provenance_aliases_work_only_when_unambiguous(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        payload = site_export(fixture)
        for row in payload["reviews"]:
            annotation = json.loads(row["annotation_json"])
            provenance = annotation["provenance"]
            provenance["source_ref"] = provenance.pop("source_reference")
            provenance["timestamp"] = provenance.pop("annotated_at")
            provenance["ai_assist"] = provenance.pop("ai_assistance")
            row["annotation_json"] = json.dumps(annotation)
        self.assertEqual(score_export(payload)["status"], "complete_provisional")

        conflict = copy.deepcopy(payload)
        annotation = json.loads(conflict["reviews"][0]["annotation_json"])
        annotation["provenance"]["source_reference"] = "another-source"
        conflict["reviews"][0]["annotation_json"] = json.dumps(annotation)
        with self.assertRaisesRegex(ExportError, "provenance fields conflict"):
            score_export(conflict)

    def test_scorer_rejects_non_unset_or_synthetic_submitted_provenance(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        def assert_first_annotation_rejected(annotation, message):
            payload = site_export(fixture)
            payload["reviews"][0]["annotation_json"] = json.dumps(annotation)
            with self.assertRaisesRegex(ExportError, message):
                score_export(payload)

        synthetic_annotation = site_annotation(fixture, USERS[0])
        synthetic_annotation["provenance"]["annotation_tier"] = "SYNTHETIC"
        assert_first_annotation_rejected(synthetic_annotation, "must remain UNSET")

        for tier in ("SILVER", "GOLD"):
            wrong_tier = site_annotation(fixture, USERS[0])
            wrong_tier["provenance"]["annotation_tier"] = tier
            assert_first_annotation_rejected(wrong_tier, "must remain UNSET")

        fake_unset_synthetic = site_annotation(fixture, USERS[0])
        fake_unset_synthetic["provenance"]["data_origin"] = "SYNTHETIC"
        assert_first_annotation_rejected(fake_unset_synthetic, "synthetic and unknown-origin")

    def test_unmocked_validation_rejects_wrong_identity_and_bad_source_spans(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        wrong_identity_payload = site_export(fixture)
        wrong_identity = json.loads(wrong_identity_payload["reviews"][0]["annotation_json"])
        wrong_identity["provenance"]["annotator_id"] = USERS[1]
        wrong_identity_payload["reviews"][0]["annotation_json"] = json.dumps(wrong_identity)
        with self.assertRaisesRegex(ExportError, "identity does not match"):
            score_export(wrong_identity_payload)

        invalid_span_payload = site_export(fixture)
        invalid_span = json.loads(invalid_span_payload["reviews"][0]["annotation_json"])
        invalid_span["spans"][0]["end"] += 1
        invalid_span_payload["reviews"][0]["annotation_json"] = json.dumps(invalid_span)
        with self.assertRaisesRegex(ExportError, "failed V1 structural or exact-source validation"):
            score_export(invalid_span_payload)

    def test_unmocked_validation_accepts_python_unicode_codepoint_offsets(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        payload = site_export(fixture)
        source = payload["sources"][0]
        prefix = "🧪 "
        source["current_message"] = prefix + source["current_message"]
        source["authored_ranges"] = [{"start": 0, "end": len(source["current_message"])}]
        for row in payload["reviews"]:
            annotation = json.loads(row["annotation_json"])
            for span in annotation["spans"]:
                if span["field"] == "current_message":
                    span["start"] += len(prefix)
                    span["end"] += len(prefix)
            row["annotation_json"] = json.dumps(annotation, ensure_ascii=False)
        report = score_export(payload)
        self.assertEqual(report["status"], "complete_provisional")

        wrong_utf16_payload = copy.deepcopy(payload)
        for row in wrong_utf16_payload["reviews"]:
            annotation = json.loads(row["annotation_json"])
            for span in annotation["spans"]:
                if span["field"] == "current_message":
                    span["start"] += 1
                    span["end"] += 1
            row["annotation_json"] = json.dumps(annotation, ensure_ascii=False)
        with self.assertRaisesRegex(ExportError, "failed V1 structural or exact-source validation"):
            score_export(wrong_utf16_payload)

    def test_unmocked_validation_rejects_invalid_references_wrong_roles_and_unmarked_uncertainty(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        mutations = (
            (lambda annotation: annotation["event_span_links"][0].update({"span_id": "missing-span"})),
            (lambda annotation: annotation["event_span_links"][0].update({"role": "MEETING_NAME"})),
            (lambda annotation: annotation["events"][0].update({"certainty": "UNCERTAIN"})),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                payload = site_export(fixture)
                annotation = json.loads(payload["reviews"][0]["annotation_json"])
                mutate(annotation)
                payload["reviews"][0]["annotation_json"] = json.dumps(annotation)
                with self.assertRaisesRegex(ExportError, "failed V1 structural or exact-source validation"):
                    score_export(payload)

    def test_latest_revision_supersedes_stale_submission(self):
        fixture = self.fixtures["meeting_date_not_deadline"]
        payload = site_export(fixture)
        stale = copy.deepcopy(payload["reviews"][0])
        stale["revision"] = 2
        stale["status"] = "draft"
        stale.pop("annotation_json")
        payload["reviews"].append(stale)
        report = score_export(payload)
        self.assertEqual(report["status"], "waiting")
        self.assertEqual(report["common_blind_progress"]["submitted_reviews"], 2)
        self.assertEqual(report["common_blind_progress"]["status_counts"], {"draft": 1, "submitted": 2})

        duplicate_revision = copy.deepcopy(payload)
        duplicate_revision["reviews"][-1]["revision"] = 1
        with self.assertRaisesRegex(ExportError, "duplicate reviewer/source revisions"):
            score_export(duplicate_revision)

    def test_authenticated_reviewer_contract_requires_three_distinct_users(self):
        payload = site_export(self.fixtures["meeting_date_not_deadline"])
        payload["reviewers"] = payload["reviewers"][:2]
        with self.assertRaisesRegex(ExportError, "exactly three distinct authenticated reviewers"):
            score_export(payload)
        payload = site_export(self.fixtures["meeting_date_not_deadline"])
        payload["reviewers"][1]["user_id"] = payload["reviewers"][0]["user_id"]
        with self.assertRaisesRegex(ExportError, "three distinct authenticated reviewers"):
            score_export(payload)


if __name__ == "__main__":
    unittest.main()

"""Provenance and abstention checks for the classification-only silver batch."""

import unittest

from scripts.build_ai_silver_classification import build
from src.datasets.schemas import empty_record


def source(email_id):
    row = empty_record(
        email_id=email_id, source_dataset="enron", thread_id=email_id,
        raw_body="Project review Friday.", subject="Review",
    )
    row["current_message"] = "Project review Friday."
    return row


def decision(email_id, labels, needs_review=False):
    return {
        "email_id": email_id,
        "reviewer": "primary_agent_direct_ai_audit",
        "status": "ai_audit_suggestion" if labels else "ai_audit_abstention",
        "suggested_labels": labels,
        "needs_review": needs_review,
        "reason": "Scope requires another look." if needs_review else "Current project work.",
    }


class SilverClassificationTests(unittest.TestCase):
    def test_build_keeps_uncertain_rows_unlabelled_and_drops_spans(self):
        seed = [source("one"), source("two")]
        audit = [decision("one", ["MEETING"]), decision("two", ["MEETING"], True)]
        result = build(seed, audit)
        self.assertEqual(result[0]["labels"], ["MEETING"])
        self.assertEqual(result[0]["annotation"]["status"], "ai_prelabelled")
        self.assertEqual(result[0]["annotation"]["span_review_status"], "not_adjudicated")
        self.assertEqual(result[1]["labels"], [])
        self.assertEqual(result[1]["annotation"]["status"], "unlabelled")
        self.assertTrue(result[1]["annotation"]["needs_review"])
        self.assertEqual([r["spans"] for r in result], [[], []])
        self.assertEqual([r["raw_body"] for r in result], [r["raw_body"] for r in seed])

    def test_rejects_misaligned_audit(self):
        with self.assertRaisesRegex(ValueError, "identical order"):
            build([source("one"), source("two")],
                  [decision("two", ["MEETING"]), decision("one", ["MEETING"])])

    def test_rejects_bad_provenance_and_non_project_mix(self):
        bad = decision("one", ["MEETING"])
        bad["reviewer"] = "human"
        with self.assertRaisesRegex(ValueError, "provenance"):
            build([source("one")], [bad])
        with self.assertRaisesRegex(ValueError, "NON_PROJECT must be exclusive"):
            build([source("one")], [decision("one", ["NON_PROJECT", "MEETING"])])


if __name__ == "__main__":
    unittest.main()

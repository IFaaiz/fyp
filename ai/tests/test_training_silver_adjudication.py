"""Guard the conservative three-pass AI-silver classification gate."""

from __future__ import annotations

import unittest
import hashlib

from scripts.adjudicate_training_silver_1400 import (
    adjudicate, expected_audit_ids, validate_seed_against_manifest,
)


class TrainingSilverAdjudicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed = [
            {"source_dataset": "enron", "email_id": "a", "thread_id": "old-a"},
            {"source_dataset": "enron", "email_id": "b", "thread_id": "thread-b"},
            {"source_dataset": "enron", "email_id": "c", "thread_id": "thread-c"},
        ]
        self.left = [
            {"email_id": "a", "labels": ["MEETING"], "needs_review": False},
            {"email_id": "b", "labels": ["NON_PROJECT"], "needs_review": False},
            {"email_id": "c", "labels": ["GENERAL_UPDATE"], "needs_review": False},
        ]
        self.right = [
            {"email_id": "a", "labels": ["MEETING"], "needs_review": False},
            {"email_id": "b", "labels": ["NON_PROJECT"], "needs_review": False},
            {"email_id": "c", "labels": ["ACTION_REQUEST"], "needs_review": False},
        ]

    def audit(self, *, veto_a: bool = False) -> list[dict]:
        labels = {"a": ["NON_PROJECT"] if veto_a else ["MEETING"],
                  "b": ["NON_PROJECT"], "c": ["GENERAL_UPDATE"]}
        return [
            {"email_id": email_id, "labels": labels[email_id], "needs_review": False}
            for email_id in sorted(expected_audit_ids(self.seed, self.left, self.right))
        ]

    def adjudicate(self, audit: list[dict]) -> list[dict]:
        return adjudicate(self.seed, self.left, self.right, audit,
                          exclusions=set(), aliases={"a": "canonical-a"},
                          supervisor_vetoes=set())

    def test_disagreement_is_not_promoted_by_tiebreaker(self) -> None:
        result = self.adjudicate(self.audit())
        self.assertEqual(result[2]["status"], "excluded_uncertain")
        self.assertEqual(result[2]["labels"], [])
        self.assertEqual(result[0]["thread_id"], "canonical-a")

    def test_third_audit_vetoes_an_exact_agreement(self) -> None:
        result = self.adjudicate(self.audit(veto_a=True))
        self.assertEqual(result[0]["status"], "excluded_uncertain")
        self.assertEqual(result[0]["acceptance_rule"], "third_audit_veto")

    def test_missing_required_audit_is_rejected(self) -> None:
        audit = self.audit()
        audit = [row for row in audit if row["email_id"] != "c"]
        with self.assertRaisesRegex(ValueError, "third audit missing"):
            self.adjudicate(audit)

    def test_seed_hash_must_match_frozen_selection(self) -> None:
        source = [{"email_id": "a", "thread_id": "thread-a", "current_message": "Project report"}]
        selected = [{"order": 7, "email_id": "a", "thread_id": "thread-a",
                     "current_sha256": hashlib.sha256(b"Project report").hexdigest()}]
        validate_seed_against_manifest(source, selected, 7)
        source[0]["current_message"] = "Different text"
        with self.assertRaisesRegex(ValueError, "selection manifest mismatch"):
            validate_seed_against_manifest(source, selected, 7)

    def test_sparse_calendar_export_can_be_excluded_from_noisy_tranche(self) -> None:
        self.seed[0]["current_message"] = "CALENDAR ENTRY: generic appointment"
        self.seed[1]["current_message"] = "A clear non-project message"
        self.seed[2]["current_message"] = "A disputed project message"
        result = adjudicate(self.seed, self.left, self.right, self.audit(),
                            exclusions=set(), aliases={}, supervisor_vetoes=set(),
                            exclude_calendar_task_exports=True)
        self.assertEqual(result[0]["acceptance_rule"], "sparse_calendar_task_export")
        self.assertEqual(result[0]["status"], "excluded_uncertain")


if __name__ == "__main__":
    unittest.main()

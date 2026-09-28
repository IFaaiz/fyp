import unittest
import json
import tempfile
from pathlib import Path

from scripts.audit_cross_source_leakage import run_audit
from src.datasets.leakage import (
    fingerprint_content,
    is_near_duplicate,
    normalize_body,
    normalize_subject,
    normalize_tokens,
)


class LeakageFingerprintTests(unittest.TestCase):
    def test_body_normalization_collapses_case_and_whitespace(self):
        self.assertEqual(
            normalize_body("  Project\tPLAN\r\nREADY "),
            "project plan ready",
        )

    def test_strong_tokens_ignore_punctuation_but_exact_body_does_not(self):
        left = fingerprint_content(
            "Project Plan",
            "The revised project schedule is ready for review. Please send any detailed feedback by Friday.",
        )
        right = fingerprint_content(
            "Re: Project Plan",
            "The revised project schedule is ready for review please send any detailed feedback by Friday",
        )
        self.assertIsNotNone(left.body_exact)
        self.assertNotEqual(left.body_exact, right.body_exact)
        self.assertEqual(left.body_tokens, right.body_tokens)
        self.assertEqual(left.subject_body, right.subject_body)

    def test_compact_tokens_join_contractions_across_token_boundaries(self):
        left = fingerprint_content(
            "Project review",
            "The project team didn't approve the revised schedule after reviewing every item in the detailed implementation plan.",
        )
        right = fingerprint_content(
            "Project review",
            "The project team did n't approve the revised schedule after reviewing every item in the detailed implementation plan.",
        )
        self.assertNotEqual(left.body_exact, right.body_exact)
        self.assertNotEqual(left.body_tokens, right.body_tokens)
        self.assertEqual(left.body_compact, right.body_compact)
        self.assertEqual(left.subject_body, right.subject_body)

    def test_short_generic_text_never_gets_a_link_key(self):
        for text in ("Thanks", "Yes", "Confirmed"):
            with self.subTest(text=text):
                result = fingerprint_content("Project status", text)
                self.assertFalse(result.eligible)
                self.assertIsNone(result.body_exact)
                self.assertIsNone(result.body_tokens)
                self.assertIsNone(result.subject_body)
                self.assertIsNotNone(result.short_body_exact)

    def test_subject_normalization_strips_reply_prefixes(self):
        self.assertEqual(
            normalize_subject("Fwd: Re: Project update"),
            "project update",
        )

    def test_near_match_requires_same_subject_and_high_overlap(self):
        shared = " ".join(
            f"Section {number} verifies the revised integration test plan for service boundary {number}, "
            f"records result {number}, and sends the detailed release summary to project reviewers before Friday."
            for number in range(1, 13)
        )
        near = shared.replace("revised integration test plan", "updated integration test plan", 1)
        accepted, score = is_near_duplicate(
            "Re: Integration test plan",
            shared,
            "Integration test plan",
            near,
        )
        self.assertTrue(accepted)
        self.assertGreaterEqual(score, 0.92)

    def test_near_match_rejects_short_generic_body_and_different_subject(self):
        accepted_short, _ = is_near_duplicate(
            "Project update",
            "Thanks",
            "Project update",
            "Thanks!",
        )
        self.assertFalse(accepted_short)

        body = (
            "The revised integration test plan covers the release candidate, "
            "checks each service boundary, records every result, and sends a summary "
            "to the project team before the review meeting."
        )
        accepted_subject, _ = is_near_duplicate(
            "Integration test plan",
            body,
            "Quarterly finance review",
            body + " ",
        )
        self.assertFalse(accepted_subject)


class LeakageAuditIntegrationTests(unittest.TestCase):
    def test_audit_unions_cross_source_content_and_threads_but_excludes_short_generic(self):
        shared = " ".join(
            f"Section {number} confirms the detailed implementation plan and the team didn't approve "
            f"work item {number}; it records review decision {number} and sends the completed schedule to the project owner."
            for number in range(1, 13)
        )
        compact_variant = shared.replace("didn't", "did n't")
        near_variant = shared.replace("completed schedule", "revised schedule", 1)
        records = [
            {"source_dataset": "enron", "email_id": "e1", "thread_id": "te1", "subject": "Plan", "current_message": shared, "raw_body": shared},
            {"source_dataset": "enron", "email_id": "e2", "thread_id": "te2", "subject": "Re: Plan", "current_message": near_variant, "raw_body": near_variant},
            {"source_dataset": "enron", "email_id": "e3", "thread_id": "shared-thread", "subject": "Personal", "current_message": "Thanks", "raw_body": "Thanks"},
            {"source_dataset": "mailex", "email_id": "m1", "thread_id": "tm1", "subject": "Fwd: Plan", "current_message": compact_variant, "raw_body": compact_variant},
            {"source_dataset": "mailex", "email_id": "m2", "thread_id": "tm1", "subject": "Re: Plan", "current_message": "See attached", "raw_body": "See attached"},
            {"source_dataset": "mailex", "email_id": "m3", "thread_id": "shared-thread", "subject": "Personal", "current_message": "Thanks", "raw_body": "Thanks"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            enron = root / "enron.jsonl"
            mailex = root / "mailex.jsonl"
            candidates = root / "candidates.jsonl"
            sidecar = root / "leakage_groups.jsonl"
            report = root / "report.md"
            for path, selected in ((enron, records[:3]), (mailex, records[3:])):
                path.write_text("".join(json.dumps(row) + "\n" for row in selected), encoding="utf-8")
            candidates.write_text(json.dumps({"email_id": "e1"}) + "\n", encoding="utf-8")
            result = run_audit(enron, mailex, candidates, sidecar, report, root)
            rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
            by_id = {row["email_id"]: row for row in rows}

        self.assertEqual(result["records"], 6)
        self.assertEqual(len(rows), 6)
        self.assertEqual(by_id["e1"]["leakage_group_id"], by_id["e2"]["leakage_group_id"])
        self.assertEqual(by_id["e1"]["leakage_group_id"], by_id["m1"]["leakage_group_id"])
        self.assertEqual(by_id["m1"]["leakage_group_id"], by_id["m2"]["leakage_group_id"])
        self.assertNotEqual(by_id["e3"]["leakage_group_id"], by_id["m3"]["leakage_group_id"])
        self.assertEqual(result["short_ambiguous_groups_excluded"], 1)
        self.assertEqual(result["candidate_stats"]["candidate_records_in_cross_source_groups"], 1)


if __name__ == "__main__":
    unittest.main()

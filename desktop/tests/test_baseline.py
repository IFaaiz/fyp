from __future__ import annotations

import unittest

from desktop.local_product.classification import rule_baseline
from desktop.local_product.models import EmailRecord


def _record(body: str, *, subject: str = "") -> EmailRecord:
    return EmailRecord(
        source_id="fixture-1",
        source_name="synthetic",
        subject=subject,
        body_raw=body,
        current_message=body,
        annotation_method="UNANNOTATED",
    )


class RuleBaselineTests(unittest.TestCase):
    def test_document_request_by_date_is_review_only_and_does_not_double_add_action(self):
        suggestion = rule_baseline(_record("Please send the revised report by Friday."))
        self.assertEqual(suggestion.status, "REVIEW")
        self.assertEqual(set(suggestion.labels), {"REPORT_REQUEST", "DEADLINE"})
        self.assertNotIn("ACTION_REQUEST", suggestion.labels)
        self.assertFalse(suggestion.human_gold)
        self.assertTrue(suggestion.review_required)

    def test_attached_report_is_not_a_request(self):
        suggestion = rule_baseline(_record("The report is attached."))
        self.assertEqual(suggestion.status, "ABSTAIN")
        self.assertEqual(suggestion.labels, ())

    def test_reviewing_a_document_is_action_not_report_request_or_approval(self):
        suggestion = rule_baseline(_record("Please review the draft report."))
        self.assertIn("ACTION_REQUEST", suggestion.labels)
        self.assertNotIn("REPORT_REQUEST", suggestion.labels)
        self.assertNotIn("APPROVAL", suggestion.labels)
        self.assertEqual(suggestion.status, "REVIEW")

    def test_meeting_date_by_itself_is_not_a_deadline(self):
        suggestion = rule_baseline(_record("The meeting is on Friday."))
        self.assertIn("MEETING", suggestion.labels)
        self.assertNotIn("DEADLINE", suggestion.labels)

    def test_quoted_history_never_adds_a_cue(self):
        record = EmailRecord(
            source_id="fixture-2",
            source_name="synthetic",
            subject="Re: status",
            body_raw="Thanks.\n\nPlease approve the project report by Friday.",
            current_message="Thanks.",
            quoted_history="Please approve the project report by Friday.",
            annotation_method="UNANNOTATED",
        )
        suggestion = rule_baseline(record)
        self.assertEqual(suggestion.status, "ABSTAIN")
        self.assertEqual(suggestion.labels, ())
        self.assertEqual(suggestion.evidence, ())

    def test_inherited_reply_subject_cannot_trigger_a_cue_without_authored_action(self):
        record = _record(
            "Thanks, I will check the notes.",
            subject="Re: Please send the report by Friday",
        )
        suggestion = rule_baseline(record)
        self.assertEqual(suggestion.status, "ABSTAIN")
        self.assertEqual(suggestion.labels, ())
        self.assertEqual(suggestion.evidence, ())

    def test_separate_document_request_and_action_keep_both_suggestions(self):
        suggestion = rule_baseline(
            _record("Please send the report and please update the tracking schedule.")
        )
        self.assertEqual(suggestion.status, "REVIEW")
        self.assertIn("REPORT_REQUEST", suggestion.labels)
        self.assertIn("ACTION_REQUEST", suggestion.labels)
        self.assertEqual(
            [item.text for item in suggestion.evidence if item.label == "ACTION_REQUEST"],
            ["please update"],
        )

    def test_no_owner_date_or_span_is_invented(self):
        suggestion = rule_baseline(_record("Please complete the plan by Friday."))
        self.assertTrue(suggestion.evidence)
        self.assertTrue(all(cue.label in {"ACTION_REQUEST", "DEADLINE"} for cue in suggestion.evidence))
        self.assertFalse(hasattr(suggestion, "spans"))


if __name__ == "__main__":
    unittest.main()

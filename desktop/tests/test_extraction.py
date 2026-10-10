"""Synthetic behavior checks for provisional extraction, without corpus text."""
from dataclasses import replace
import unittest

from desktop.local_product.models import EmailRecord
from desktop.local_product.extraction import TARGETS, extract_rule_suggestions


class ExtractionTests(unittest.TestCase):
    def record(self, text):
        return EmailRecord(source_id="synthetic", source_name="synthetic", current_message=text)

    def test_meeting_date_is_not_deadline(self):
        record = self.record("The project meeting is Friday at 3 PM.")
        result = extract_rule_suggestions(record)
        self.assertEqual([s["type"] for s in result["spans"]], ["MEETING_DATE", "MEETING_TIME"])
        self.assertFalse(result["targets"]["DEADLINE_DATE"])
        self.assertEqual(len(result["targets"]), 11)

    def test_request_and_exact_offsets_without_invented_fields(self):
        record = self.record("Please send the revised report by Friday. Please update the plan.")
        result = extract_rule_suggestions(record)
        for span in result["spans"]:
            self.assertEqual(span["text"], record.current_message[span["start"]:span["end"]])
        self.assertEqual(result["targets"]["REQUESTED_DOCUMENT"][0]["text"], "revised report")
        self.assertEqual(result["targets"]["DEADLINE_DATE"][0]["text"], "Friday")
        self.assertEqual(result["targets"]["ACTION_ITEM"][0]["text"], "update the plan")
        self.assertEqual(result["normalized_dates"], {})
        self.assertFalse(result["targets"]["RESPONSIBLE_PARTY"])
        self.assertEqual(record.spans, ())
        self.assertFalse(result["human_gold"])

    def test_delivery_review_and_missing_details(self):
        result = extract_rule_suggestions(self.record("The report is attached. Please review it."))
        self.assertFalse(result["targets"]["REQUESTED_DOCUMENT"])
        self.assertTrue(result["targets"]["ACTION_ITEM"])
        self.assertFalse(result["targets"]["DEADLINE_DATE"])
        self.assertNotIn("INPUT", TARGETS)
        self.assertNotIn("APPROVAL_TARGET", TARGETS)

    def test_history_subject_and_ambiguous_roles_abstain(self):
        record = replace(self.record("Thanks."), subject="Please send the report by Friday", quoted_history="Meeting tomorrow at noon.")
        self.assertEqual(extract_rule_suggestions(record)["status"], "ABSTAIN")
        ambiguous = self.record("Review is due Friday before the meeting Monday.")
        self.assertFalse(extract_rule_suggestions(ambiguous)["spans"])


if __name__ == "__main__":
    unittest.main()

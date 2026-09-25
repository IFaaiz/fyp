import unittest

from src.datasets.schemas import empty_record
from src.datasets.validation import validate_record


class AnnotationValidationTests(unittest.TestCase):
    def setUp(self):
        self.record = empty_record(
            email_id="e", source_dataset="enron", thread_id="t",
            raw_body="Submit by Friday at 5 PM.",
        )

    def test_ai_prelabelled_requires_ai_source(self):
        self.record["annotation"]["status"] = "ai_prelabelled"
        self.assertIn("ai_prelabelled requires ai annotation_source", validate_record(self.record))
        self.record["annotation"]["annotation_source"] = "ai"
        self.assertEqual(validate_record(self.record), [])

    def test_human_reviewed_requires_human_and_annotator(self):
        self.record["annotation"]["status"] = "human_reviewed"
        errors = validate_record(self.record)
        self.assertIn("human_reviewed requires human annotation_source", errors)
        self.assertIn("human_reviewed requires annotator", errors)
        self.record["annotation"].update(annotation_source="human", annotator="A")
        self.assertEqual(validate_record(self.record), [])

    def test_gold_requires_human_and_real_source(self):
        self.record["annotation"].update(status="gold", annotation_source="human", annotator="A")
        self.assertEqual(validate_record(self.record), [])
        self.record["source_dataset"] = "synthetic"
        self.assertIn("synthetic record cannot be gold", validate_record(self.record))

    def test_unlabelled_dataset_spans_are_provisional(self):
        span = {"label": "DEADLINE_DATE", "text": "Friday", "start": 10, "end": 16}
        self.record["spans"] = [span]
        self.assertIn("unlabelled spans require dataset annotation_source", validate_record(self.record))
        self.record["annotation"]["annotation_source"] = "dataset"
        self.assertEqual(validate_record(self.record), [])
        self.record["labels"] = ["DEADLINE"]
        self.assertIn("unlabelled record cannot carry classification labels", validate_record(self.record))

    def test_duplicate_canonical_span_is_rejected(self):
        span = {"label": "DEADLINE_TIME", "text": "5 PM", "start": 20, "end": 24}
        self.record["annotation"].update(status="human_reviewed", annotation_source="human", annotator="A")
        self.record["spans"] = [span, dict(span)]
        self.assertTrue(any("duplicate canonical span" in error for error in validate_record(self.record)))


if __name__ == "__main__":
    unittest.main()

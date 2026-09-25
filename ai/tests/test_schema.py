import unittest

from src.annotation.prelabel import apply_prelabel
from src.datasets.schemas import empty_record
from src.datasets.validation import validate_record


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.record = empty_record(
            email_id="e1", source_dataset="enron", thread_id="t1",
            raw_body="Please submit the report by Friday.",
        )

    def test_empty_is_unlabelled_not_negative(self):
        self.assertEqual(validate_record(self.record), [])
        self.assertEqual(self.record["labels"], [])

    def test_multiple_labels_and_exact_span(self):
        prediction = {
            "labels": ["DEADLINE", "REPORT_REQUEST"],
            "spans": [{"label": "DEADLINE_DATE", "text": "Friday"}],
            "confidence": {"DEADLINE": 0.9},
        }
        labelled = apply_prelabel(self.record, prediction)
        self.assertEqual(labelled["annotation"]["status"], "ai_prelabelled")
        self.assertEqual(validate_record(labelled), [])
        self.assertEqual(labelled["current_message"][labelled["spans"][0]["start"]:labelled["spans"][0]["end"]], "Friday")

    def test_ambiguous_span_is_rejected(self):
        self.record["current_message"] = "Friday or Friday"
        with self.assertRaises(ValueError):
            apply_prelabel(self.record, {"labels": ["DEADLINE"], "spans": [{"label": "DEADLINE_DATE", "text": "Friday"}]})

    def test_ai_prelabel_cannot_overwrite_reviewed_or_gold(self):
        for status in ("human_reviewed", "gold"):
            with self.subTest(status=status):
                self.record["annotation"] = {"status": status, "annotator": "A", "annotation_source": "human"}
                with self.assertRaisesRegex(ValueError, "cannot overwrite"):
                    apply_prelabel(self.record, {"labels": ["DEADLINE"], "spans": []})

    def test_synthetic_cannot_be_gold(self):
        self.record["source_dataset"] = "synthetic"
        self.record["annotation"] = {"status": "gold", "annotator": "A", "annotation_source": "human"}
        self.assertIn("synthetic record cannot be gold", validate_record(self.record))


if __name__ == "__main__":
    unittest.main()

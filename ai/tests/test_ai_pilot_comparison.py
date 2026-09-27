import copy
import unittest

from scripts.compare_ai_pilot import compare_ai_pilot_records
from src.datasets.schemas import empty_record


def make_seed():
    rows = []
    for index in range(50):
        rows.append(empty_record(
            email_id=f"pilot-{index:02d}", source_dataset="enron",
            thread_id=f"thread-{index:02d}", raw_body="Send report by Friday.",
            subject=f"Pilot {index}",
        ))
    return rows


def make_ai_rows(seed, *, unresolved=()):
    rows = copy.deepcopy(seed)
    for index, row in enumerate(rows):
        row["annotation"] = {
            "status": "unlabelled" if index in unresolved else "ai_prelabelled",
            "annotator": "test-model",
            "annotation_source": "ai",
            "confidence": None,
        }
        if index not in unresolved:
            row["labels"] = ["NON_PROJECT"]
    return rows


class AiPilotComparisonTests(unittest.TestCase):
    def setUp(self):
        self.seed = make_seed()
        self.a = make_ai_rows(self.seed)
        self.b = make_ai_rows(self.seed)

    def test_reports_raw_clean_flagged_and_unresolved_agreement(self):
        self.a[0]["labels"] = ["MEETING"]
        self.a[1]["spans"] = [{
            "label": "DEADLINE_DATE", "field": "current_message", "start": 15,
            "end": 21, "text": "Friday",
        }]
        self.b[1]["spans"] = [{
            "label": "DEADLINE_DATE", "field": "current_message", "start": 0,
            "end": 3, "text": "Sen",
        }]
        self.a[2]["annotation"]["status"] = "unlabelled"
        self.a[2]["labels"] = []
        self.a[0]["annotation"]["needs_review"] = True
        self.b[1]["annotation"]["needs_review"] = True

        report = compare_ai_pilot_records(self.seed, self.a, self.b)

        self.assertEqual(report["paired_records"], 50)
        self.assertEqual(report["both_ai_prelabelled_records"], 49)
        self.assertEqual(report["clean_subset_records"], 47)
        self.assertEqual(report["unresolved_records"], 1)
        self.assertEqual(report["unresolved_email_ids"], ["pilot-02"])

        raw = report["raw_pairwise_agreement"]
        self.assertEqual(raw["records"], 50)
        raw_meeting = raw["classification"]["per_label"]["MEETING"]
        self.assertEqual(raw_meeting["a_only"], 1)
        self.assertEqual(raw_meeting["agreement_records"], 49)
        self.assertAlmostEqual(raw_meeting["agreement_rate"], 49 / 50)
        self.assertEqual(raw["spans"]["record_exact_span_set_match_records"], 49)

        clean = report["clean_subset_agreement"]
        self.assertEqual(clean["records"], 47)
        clean_meeting = clean["classification"]["per_label"]["MEETING"]
        self.assertEqual(clean_meeting["agreement_records"], 47)
        self.assertEqual(clean_meeting["agreement_rate"], 1.0)
        self.assertEqual(clean["spans"]["record_exact_span_set_match_records"], 47)

        flags = report["needs_review_flags"]
        self.assertEqual(flags["flagged_records"], 2)
        self.assertEqual(flags["flagged_email_ids"], ["pilot-00", "pilot-01"])
        self.assertEqual(flags["by_reviewer"]["A"], {
            "count": 1, "email_ids": ["pilot-00"],
        })
        self.assertEqual(flags["by_reviewer"]["B"], {
            "count": 1, "email_ids": ["pilot-01"],
        })

        self.assertEqual(report["disagreement_count"], 3)
        flagged = next(row for row in report["disagreements"] if row["email_id"] == "pilot-00")
        self.assertTrue(flagged["needs_review"])
        self.assertEqual(flagged["needs_review_by"], ["A"])
        unresolved = next(row for row in report["disagreements"] if row["email_id"] == "pilot-02")
        self.assertTrue(unresolved["unresolved"])
        self.assertEqual(unresolved["unresolved_by"], ["A"])
        self.assertFalse(report["gold_labels_used"])
        self.assertFalse(report["accuracy_reported"])
    def test_requires_fixed_count_exact_id_order_and_source_fields(self):
        with self.assertRaisesRegex(ValueError, "exactly 50"):
            compare_ai_pilot_records(self.seed[:-1], self.a[:-1], self.b[:-1])

        reordered = copy.deepcopy(self.b)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaisesRegex(ValueError, "order differs"):
            compare_ai_pilot_records(self.seed, self.a, reordered)

        changed_source = copy.deepcopy(self.b)
        changed_source[0]["subject"] = "Edited subject"
        with self.assertRaisesRegex(ValueError, "changed source field 'subject'"):
            compare_ai_pilot_records(self.seed, self.a, changed_source)

    def test_requires_ai_provenance_known_labels_and_valid_spans(self):
        bad_provenance = copy.deepcopy(self.a)
        bad_provenance[0]["annotation"]["annotation_source"] = "human"
        with self.assertRaisesRegex(ValueError, "requires ai annotation_source"):
            compare_ai_pilot_records(self.seed, bad_provenance, self.b)

        empty_resolved = copy.deepcopy(self.a)
        empty_resolved[0]["labels"] = []
        with self.assertRaisesRegex(ValueError, "empty labels while marked ai_prelabelled"):
            compare_ai_pilot_records(self.seed, empty_resolved, self.b)

        bad_review_flag = copy.deepcopy(self.a)
        bad_review_flag[0]["annotation"]["needs_review"] = "true"
        with self.assertRaisesRegex(ValueError, "needs_review must be boolean"):
            compare_ai_pilot_records(self.seed, bad_review_flag, self.b)

        bad_label = copy.deepcopy(self.a)
        bad_label[0]["labels"] = ["UNKNOWN"]
        with self.assertRaisesRegex(ValueError, "known classification labels"):
            compare_ai_pilot_records(self.seed, bad_label, self.b)

        bad_span = copy.deepcopy(self.a)
        bad_span[0]["spans"] = [{
            "label": "ACTION_ITEM", "field": "current_message", "start": 0,
            "end": 4, "text": "Wrong",
        }]
        with self.assertRaisesRegex(ValueError, "text/offset mismatch"):
            compare_ai_pilot_records(self.seed, bad_span, self.b)


if __name__ == "__main__":
    unittest.main()

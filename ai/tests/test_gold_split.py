import unittest

from src.datasets.schemas import empty_record
from src.datasets.splitting import split_by_thread
from src.datasets.threading import apply_secondary_thread_suggestions, suggest_secondary_thread_links
from src.datasets.validation import validate_split_isolation


def record(email_id, thread_id, *, source="enron", status="human_reviewed"):
    item = empty_record(email_id=email_id, source_dataset=source, thread_id=thread_id, raw_body="body")
    item["annotation"] = {
        "status": status,
        "annotation_source": "human",
        "annotator": "reviewer",
        "confidence": None,
    }
    return item


class GoldSplitTests(unittest.TestCase):
    def test_single_message_gold_thread(self):
        splits = split_by_thread([record("g", "gold", status="gold"), record("n", "other")])
        self.assertEqual([item["email_id"] for item in splits["test"] if item["thread_id"] == "gold"], ["g"])

    def test_entire_mixed_thread_reserved(self):
        records = [
            record("a", "shared", status="human_reviewed"),
            record("b", "shared", status="gold"),
            record("c", "shared", status="human_reviewed"),
        ] + [record(f"n{i}", f"other{i}") for i in range(20)]
        for seed in range(20):
            splits = split_by_thread(records, seed=seed)
            self.assertEqual(validate_split_isolation(splits), [])
            self.assertEqual({item["email_id"] for item in splits["test"] if item["thread_id"] == "shared"}, {"a", "b", "c"})
            self.assertFalse(any(item["thread_id"] == "shared" for name in ("train", "validation") for item in splits[name]))

    def test_derived_heuristic_thread_keeps_gold_pair_in_one_split(self):
        raw = [
            {
                "email_id": "a", "thread_id": "canonical-a",
                "subject": "Quarterly project review schedule",
                "sent_at": "2024-01-01T10:00:00Z",
                "sender": "alice@example.test", "recipients": ["bob@example.test"], "cc": [],
                "current_message": "Please review the project schedule.",
            },
            {
                "email_id": "b", "thread_id": "canonical-b",
                "subject": "Re: Quarterly project review schedule",
                "sent_at": "2024-01-02T10:00:00Z",
                "sender": "bob@example.test", "recipients": ["alice@example.test"], "cc": [],
                "current_message": "I will send the revised schedule Friday.",
            },
        ]
        derived = apply_secondary_thread_suggestions(raw, suggest_secondary_thread_links(raw))
        records = [
            record(item["email_id"], item["thread_id"],
                   status="gold" if item["email_id"] == "a" else "human_reviewed")
            for item in derived
        ]
        splits = split_by_thread(records, seed=11)
        self.assertEqual(validate_split_isolation(splits), [])
        derived_id = derived[0]["thread_id"]
        self.assertEqual(
            {item["email_id"] for item in splits["test"] if item["thread_id"] == derived_id},
            {"a", "b"},
        )
        self.assertFalse(any(
            item["thread_id"] == derived_id
            for name in ("train", "validation") for item in splits[name]
        ))

    def test_synthetic_gold_forbidden(self):
        with self.assertRaises(ValueError):
            split_by_thread([record("s", "synthetic", source="synthetic", status="gold")])


    def test_split_validator_rejects_manual_gold_leak(self):
        gold = record("g", "gold", status="gold")
        synthetic = record("s", "synthetic", source="synthetic")
        errors = validate_split_isolation({"train": [gold], "validation": [], "test": [synthetic]})
        self.assertTrue(any("gold record" in error for error in errors))
        self.assertTrue(any("synthetic record" in error for error in errors))
if __name__ == "__main__":
    unittest.main()

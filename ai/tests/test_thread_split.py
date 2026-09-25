import unittest

from src.datasets.schemas import empty_record
from src.datasets.splitting import split_by_thread
from src.datasets.validation import validate_split_isolation


class SplitTests(unittest.TestCase):
    def test_thread_never_crosses_splits(self):
        records = [
            empty_record(email_id=f"e{index}", source_dataset="enron", thread_id=f"t{index // 3}", raw_body="body")
            for index in range(60)
        ]
        splits = split_by_thread(records, seed=7)
        self.assertEqual(validate_split_isolation(splits), [])
        self.assertEqual(sum(map(len, splits.values())), 60)
        self.assertEqual(splits, split_by_thread(records, seed=7))

    def test_synthetic_is_train_only(self):
        records = [empty_record(email_id="s1", source_dataset="synthetic", thread_id="s", raw_body="body")]
        splits = split_by_thread(records)
        self.assertEqual(len(splits["train"]), 1)
        self.assertFalse(splits["test"])


if __name__ == "__main__":
    unittest.main()

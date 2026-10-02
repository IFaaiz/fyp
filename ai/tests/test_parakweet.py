"""Synthetic fixture tests for deterministic Parakweet row parsing."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai.src.datasets.parakweet import parse_parakweet, write_jsonl


class ParakweetParserTests(unittest.TestCase):
    def test_preserves_sentence_label_split_and_incomplete_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Ask0729-fixed.txt").write_bytes("Yes\t  naïve request.  \nNo\tContext only.".encode("utf-8"))
            (root / "testSet-qualifiedBatch-fixed.txt").write_bytes(b"No\tSeparate test sentence.\n")
            records = parse_parakweet(data_root=root, verify_pinned_files=False)
            output = root / "records.jsonl"
            write_jsonl(output, records)
            decoded = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([row["source_split"] for row in records], ["train", "train", "test"])
        self.assertEqual(records[0]["source_label"], "Yes")
        self.assertTrue(records[0]["intent_present"])
        self.assertEqual(records[0]["text"], "  naïve request.  ")
        self.assertEqual(decoded[0]["text"], records[0]["text"])
        self.assertEqual(records[0]["source_id_kind"], "dataset_file_line")
        self.assertIsNone(records[0]["source_message_id"])
        self.assertIsNone(records[0]["rfc_message_id"])
        self.assertIsNone(records[0]["source_thread_id"])
        self.assertTrue(records[0]["fragment"])
        self.assertFalse(records[0]["overlap_identity_complete"])
        self.assertEqual(records[1]["source_label"], "No")
        self.assertFalse(records[1]["intent_present"])
        self.assertEqual(records[1]["normalized_auxiliary_act"], None)
        self.assertEqual(records[1]["fyp_labels"], [])

    def test_rejects_unknown_labels_and_extra_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train = root / "Ask0729-fixed.txt"
            test = root / "testSet-qualifiedBatch-fixed.txt"
            train.write_text("Maybe\tunknown label\n", encoding="utf-8")
            test.write_text("No\tvalid test row\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown source label"):
                parse_parakweet(data_root=root, verify_pinned_files=False)

            train.write_text("Yes\tpart one\tpart two\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one label/sentence tab delimiter"):
                parse_parakweet(data_root=root, verify_pinned_files=False)

    def test_rejects_invalid_utf8_and_expected_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train = root / "Ask0729-fixed.txt"
            test = root / "testSet-qualifiedBatch-fixed.txt"
            train.write_bytes(b"Yes\t\xff\n")
            test.write_text("No\tvalid test row\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match its pinned SHA-256"):
                parse_parakweet(data_root=root, verify_pinned_files=True)
            with self.assertRaisesRegex(ValueError, "invalid source encoding"):
                parse_parakweet(data_root=root, verify_pinned_files=False)


if __name__ == "__main__":
    unittest.main()

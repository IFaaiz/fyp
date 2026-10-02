"""Synthetic tests for the CEREC adapter; no corpus text is stored here."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from ai.src.datasets.cerec import (
    ARCHIVE_SHA256,
    CONLL_FILES,
    _parse_begin_header,
    prepare_cerec,
    safe_extract_cerec_archive,
)


def _row(*columns: str) -> str:
    if len(columns) != 7:
        raise ValueError("synthetic CoNLL row must contain seven columns")
    return "\t\t".join(columns)


class CerecAdapterTests(unittest.TestCase):
    def test_parses_standard_and_author_bare_headers(self) -> None:
        self.assertEqual(
            _parse_begin_header("#begin document (synthetic-thread); part 2"),
            ("synthetic-thread", "2"),
        )
        self.assertEqual(
            _parse_begin_header("#begin document synthetic-thread."),
            ("synthetic-thread.", None),
        )
        self.assertIsNone(_parse_begin_header("#begin document"))
        self.assertIsNone(_parse_begin_header("#begin document two words"))

    def test_prepare_preserves_source_rows_and_token_cluster_positions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conll_root = root / "conll"
            conll_root.mkdir()
            main = [
                "#begin document synthetic-thread.",
                _row("Ada", "m1", "s1", "speaker-a", "(PERSON", "(mention-1", "(7"),
                _row("Lovelace", "m1", "s1", "speaker-a", "PERSON)", "mention-1)", "7)"),
                "",
                "#end document",
                "",
            ]
            for filename in CONLL_FILES:
                path = conll_root / filename
                path.write_text(
                    "\n".join(main) if filename == "cerec.conll" else "",
                    encoding="utf-8",
                    newline="",
                )

            review_path = root / "review.jsonl"
            stats_path = root / "statistics.json"
            stats = prepare_cerec(
                conll_root=conll_root,
                review_output_path=review_path,
                stats_path=stats_path,
                source_archive_sha256=ARCHIVE_SHA256,
                review_limit=1,
            )

            self.assertEqual(stats["observed_per_file"]["cerec.conll"]["document_count"], 1)
            self.assertEqual(stats["observed_per_file"]["cerec.conll"]["token_row_count"], 2)
            self.assertEqual(
                stats["observed_per_file"]["cerec.conll"]["distinct_coreference_cluster_count"],
                1,
            )
            record = json.loads(review_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["source_thread_id"], "synthetic-thread.")
            self.assertIsNone(record["source_message_id"])
            self.assertIsNone(record["source_document_part"])
            self.assertEqual(record["text"], "Ada Lovelace")
            self.assertEqual(
                record["coreference_clusters"],
                [{
                    "source_cluster_id": "7",
                    "annotation_column": "coreference_annotation",
                    "annotated_token_rows": [0, 1],
                }],
            )
            self.assertEqual(record["fyp_labels"], [])
            self.assertFalse(record["training_permitted"])
            self.assertEqual(json.loads(stats_path.read_text(encoding="utf-8"))["review_record_count"], 1)

    def test_safe_extraction_accepts_unspecified_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "fixture.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("cerec/fixture.conll", "synthetic\n")
            extracted = safe_extract_cerec_archive(archive_path, root / "extracted")
            self.assertEqual(
                (extracted / "cerec" / "fixture.conll").read_text(encoding="utf-8"),
                "synthetic\n",
            )

    def test_safe_extraction_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "synthetic")
            with self.assertRaises(ValueError):
                safe_extract_cerec_archive(archive_path, root / "extracted")

    def test_safe_extraction_rejects_windows_special_paths(self) -> None:
        unsafe_members = (
            "release/message.txt:hidden",
            "release/NUL.txt",
            "release/folder./file.txt",
        )
        for index, member in enumerate(unsafe_members):
            with self.subTest(member_index=index):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    archive_path = root / "unsafe.zip"
                    with zipfile.ZipFile(archive_path, "w") as archive:
                        archive.writestr(member, "synthetic")
                    with self.assertRaises(ValueError):
                        safe_extract_cerec_archive(archive_path, root / "extracted")


if __name__ == "__main__":
    unittest.main()

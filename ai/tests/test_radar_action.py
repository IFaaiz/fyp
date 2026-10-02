"""Synthetic fixture tests for RADAR Action-Item source parsing."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from ai.src.datasets.radar_action import parse_radar_action, safe_extract_archive, write_jsonl


def _write_fixture(root: Path, *, bad_action_offset: bool = False) -> str:
    message_root = root / "handStripped"
    (message_root / "messages").mkdir(parents=True)
    (message_root / "judgments").mkdir()
    (message_root / "annotations").mkdir()
    text = "From:   \r\nSubject:  agenda update  \r\n\r\nPlease send the draft.\r\n"
    message_bytes = text.encode("utf-8")
    (message_root / "messages" / "msg-0.txt").write_bytes(message_bytes)
    start = text.index("send the draft")
    if bad_action_offset:
        start = len(text) + 3
    (message_root / "judgments" / "judgments.txt").write_text(
        f"msg-0.txt\tY\t{start}\t{len('send the draft')}\n", encoding="utf-8"
    )
    (message_root / "annotations" / "MsgAnnotationFilenamePairs.txt").write_text(
        "msg-0.txt\tannotation-0.txt\n", encoding="utf-8"
    )
    sentence_start = text.index("Please send the draft.")
    (message_root / "annotations" / "annotation-0.txt").write_text(
        f"{sentence_start}\t{len('Please send the draft.')}\tsentence\n",
        encoding="utf-8",
    )
    return str(message_root)


class RadarActionParserTests(unittest.TestCase):
    def test_parse_preserves_full_file_text_and_character_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            message_root = _write_fixture(Path(temporary))
            record = parse_radar_action(
                message_root=message_root,
                expected_archive_sha256="fixture-sha",
                source_archive_sha256="fixture-sha",
            )[0]
            output_path = Path(temporary) / "records.jsonl"
            write_jsonl(output_path, [record])
            round_trip = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertTrue(record["text"].endswith("draft.\r\n"))
        self.assertEqual(record["subject"], "agenda update")
        self.assertEqual(record["body"], "Please send the draft.\r\n")
        self.assertEqual(record["source_message_id_kind"], "dataset_filename")
        self.assertIsNone(record["rfc_message_id"])
        self.assertIsNone(record["source_thread_id"])
        self.assertTrue(record["action_item_present"])
        action_span = record["action_item_spans"][0]
        self.assertEqual(record["text"][action_span["start"]:action_span["end"]], "send the draft")
        self.assertEqual(round_trip["text"], record["text"])
        self.assertEqual(action_span["offset_basis"], "text")
        self.assertEqual(record["annotations"][0]["source_type"], "sentence")
        self.assertIsNone(record["fyp_label_mapping"])

    def test_out_of_range_action_span_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            message_root = _write_fixture(Path(temporary), bad_action_offset=True)
            with self.assertRaisesRegex(ValueError, "outside source text"):
                parse_radar_action(
                    message_root=message_root,
                    expected_archive_sha256="fixture-sha",
                    source_archive_sha256="fixture-sha",
                )

    def test_safe_extract_rejects_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            archive = tmp_path / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                payload = b"escape"
                member = tarfile.TarInfo("../outside.txt")
                member.size = len(payload)
                stream.addfile(member, io.BytesIO(payload))

            with self.assertRaisesRegex(ValueError, "unsafe archive member path"):
                safe_extract_archive(archive, tmp_path / "extracted")

            self.assertFalse((tmp_path / "outside.txt").exists())

    def test_safe_extract_rejects_windows_stream_and_device_paths(self) -> None:
        for name in ('release/message.txt:hidden','release/NUL.txt','release/folder./file.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); archive=root/'unsafe.tar.gz'
                with tarfile.open(archive,'w:gz') as stream:
                    member=tarfile.TarInfo(name);member.size=7
                    stream.addfile(member,io.BytesIO(b'blocked'))
                with self.assertRaises(ValueError):
                    safe_extract_archive(archive,root/'extracted')

    def test_late_unsafe_member_leaves_no_partial_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);archive=root/'unsafe.tar.gz'
            with tarfile.open(archive,'w:gz') as stream:
                for name in ('safe/file.txt','../escape.txt'):
                    member=tarfile.TarInfo(name);member.size=7
                    stream.addfile(member,io.BytesIO(b'blocked'))
            with self.assertRaises(ValueError):safe_extract_archive(archive,root/'extracted')
            self.assertFalse((root/'extracted').exists())


if __name__ == "__main__":
    unittest.main()

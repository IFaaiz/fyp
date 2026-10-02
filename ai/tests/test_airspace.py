import tempfile
import unittest
import zipfile
from pathlib import Path

from src.datasets.airspace import (
    parse_archive,
    parse_eml,
    safe_extract_archive,
    summarize_records,
)


def _eml(message_id: int, *, label: str | None = None, noise: str | None = None,
         reply_to: str | None = None, subject: str = "Plan", body: str = "Body text.") -> bytes:
    headers = [
        "From: sender@example.test",
        "To: receiver@example.test",
        f"Subject: {subject}",
        f"Message-ID: <sender.injector.{message_id}@CURUNIR>",
        f"X-RADAR-Messageid: {message_id}",
    ]
    if label is not None:
        headers.extend(f"X-RADAR-Label: {value}" for value in label.split("|"))
    if noise is not None:
        headers.append(f"X-RADAR-Noise: {noise}")
    if reply_to is not None:
        headers.append(f"X-RADAR-Replyto: {reply_to}")
    headers.extend(["Content-Type: text/plain; charset=utf-8", "", body])
    return "\r\n".join(headers).encode("utf-8")


class AirspaceParserTests(unittest.TestCase):
    def test_parser_preserves_taxonomy_noise_reply_and_offsets(self):
        record = parse_eml(
            _eml(101, label="INFO-REQ|MISC-ACTION", noise="false", reply_to="0",
                 subject="Conference plan", body="Please answer."),
            archive_member="Airspace_wargaming_1.0/msg000101.eml",
            archive_sha256="abc123",
            acquired_at="2026-10-02T14:08:44+00:00",
        )
        self.assertEqual(record["source_labels"], ["INFO-REQ", "MISC-ACTION"])
        self.assertNotIn("labels", record)
        self.assertFalse(record["noise"])
        self.assertEqual(record["reply_to_status"], "no_parent")
        self.assertIsNone(record["reply_to_message_id"])
        offsets = record["source_text_offsets"]
        text = record["source_text"]
        self.assertEqual(text[offsets["subject"]["start"]:offsets["subject"]["end"]], "Conference plan")
        self.assertEqual(text[offsets["body"]["start"]:offsets["body"]["end"]], "Please answer.")
        self.assertEqual(record["source_provenance"]["archive_sha256"], "abc123")

    def test_missing_reply_field_stays_unknown(self):
        record = parse_eml(
            _eml(7), archive_member="m7.eml", archive_sha256="hash"
        )
        self.assertIsNone(record["reply_to_message_id"])
        self.assertEqual(record["reply_to_status"], "unknown")
        self.assertIsNone(record["thread_id"])

    def test_archive_parser_derives_only_observed_reply_components(self):
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "messages.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("release/msg000101.eml", _eml(101, label="BRIEFING", reply_to="0"))
                archive.writestr("release/msg000102.eml", _eml(102, label="INFO-REQ", reply_to="101"))
                archive.writestr("release/msg000103.eml", _eml(103, label="WEB-VIO"))
            first = parse_archive(archive_path)
            second = parse_archive(archive_path)
            self.assertEqual(first, second)
            by_id = {row["source_message_id"]: row for row in first}
            self.assertEqual(by_id["102"]["reply_to_status"], "linked")
            self.assertEqual(by_id["102"]["thread_id"], "airspace-reply-component:101")
            self.assertEqual(by_id["101"]["thread_id"], by_id["102"]["thread_id"])
            self.assertIsNone(by_id["103"]["thread_id"])
            stats = summarize_records(first)
            self.assertEqual(stats["message_count"], 3)
            self.assertEqual(stats["label_counts"], {"BRIEFING": 1, "INFO-REQ": 1, "WEB-VIO": 1})
            self.assertFalse(stats["fyp_labels_emitted"])

    def test_safe_extraction_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "messages.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("release/msg000001.eml", _eml(1))
            target = root / "extracted"
            safe_extract_archive(archive_path, target)
            safe_extract_archive(archive_path, target)
            self.assertEqual((target / "release" / "msg000001.eml").read_bytes(), _eml(1))

    def test_safe_extraction_rejects_path_traversal_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "malicious.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "no")
            with self.assertRaises(ValueError):
                safe_extract_archive(archive_path, root / "extracted")
            self.assertFalse((root / "escape.txt").exists())

    def test_safe_extraction_rejects_windows_stream_and_device_paths(self):
        for name in ('release/message.txt:hidden','release/NUL.txt','release/folder./file.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); archive_path=root/'unsafe.zip'
                with zipfile.ZipFile(archive_path,'w') as archive:
                    archive.writestr(name,'blocked')
                with self.assertRaises(ValueError):
                    safe_extract_archive(archive_path,root/'extracted')
                self.assertFalse((root/'extracted').exists())


if __name__ == "__main__":
    unittest.main()

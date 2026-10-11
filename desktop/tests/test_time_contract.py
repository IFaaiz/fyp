"""Synthetic timestamp, evidence, and conversation-index contracts."""
import base64
import unittest
from desktop.local_product.models import EmailRecord
from desktop.local_product.temporal import timestamp_info


class TimeContractTests(unittest.TestCase):
    def test_utc_instants_offsets_midnight_and_dst_fold(self):
        self.assertLess(timestamp_info("2026-10-11T10:00:00+05:00")["utc"],
                        timestamp_info("2026-10-11T06:00:00Z")["utc"])
        self.assertEqual(timestamp_info("2026-10-11T00:30:00+05:00")["utc"],
                         "2026-10-10T19:30:00.000000Z")
        self.assertLess(timestamp_info("2026-11-01T01:30:00-04:00")["utc"],
                        timestamp_info("2026-11-01T01:30:00-05:00")["utc"])

    def test_unknown_dates_and_zones_are_never_imputed(self):
        for value, kind in [(None, "missing"), ("2026-10-11", "date_only"),
                            ("2026-10-11T06:00:00", "naive"),
                            ("2026-02-30", "malformed"), ("next Friday", "malformed")]:
            info = timestamp_info(value)
            self.assertEqual(info["original"], value)
            self.assertEqual(info["kind"], kind)
            self.assertIsNone(info["utc"])
        self.assertEqual(timestamp_info("Sun, 11 Oct 2026 10:00:00 +0500")["kind"], "aware")

    def test_valid_thread_index_reply_uses_root_invalid_alias_preserved(self):
        root = bytes([1]) + bytes(range(21))
        indexes = [base64.b64encode(root + suffix).decode() for suffix in (b"", b"12345", b"1234567890")]
        records = [EmailRecord(source_id=str(i), source_name="synthetic", thread_id=index) for i, index in enumerate(indexes)]
        self.assertEqual(len({r.canonical_thread_id for r in records}), 1)
        self.assertEqual(EmailRecord(source_id="bad", source_name="synthetic", thread_id="bad index").canonical_thread_id, "bad index")

    def test_raw_segmentation_is_persistable_and_fingerprint_changes(self):
        row = {"source_id": "a", "source_name": "synthetic", "body_raw": "> Friday?\r\nPlease use Monday.\r\n"}
        record = EmailRecord.from_mapping(row)
        self.assertEqual(record.current_message, "Please use Monday.")
        self.assertTrue(record.provenance["segmentation"]["current_projection_matches"])
        changed = EmailRecord.from_mapping({**row, "body_raw": "Please use Tuesday."})
        self.assertNotEqual(record.input_fingerprint, changed.input_fingerprint)
        self.assertEqual(EmailRecord.from_mapping(record.to_dict()).input_fingerprint, record.input_fingerprint)

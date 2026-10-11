"""Primary-review regressions for candidate boundaries and canonical collisions."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from desktop.local_product.items import ItemLedger
from desktop.local_product.models import EmailRecord
from desktop.local_product.store import EmailStore


class WorkflowReviewTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".local" / "test-tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.store = EmailStore(Path(self.temp.name) / "review.sqlite3")

    def record(self, body):
        return EmailRecord(source_id="synthetic", source_name="synthetic",
            subject="Synthetic", sender="a@example.test", recipients=["b@example.test"],
            message_id="synthetic@example.test", timestamp="2026-10-11T10:00:00Z",
            timestamp_kind="sent", body_raw=body, current_message=body)

    def test_trailing_spaces_and_address_periods_do_not_create_extra_candidates(self):
        text = "Please email sam@example.test. Please review the report.   \r\n"
        self.store.import_records([self.record(text)])
        ledger = ItemLedger(self.store)
        first = ledger.suggest("synthetic")
        self.assertEqual(len(first), 2)
        self.assertEqual([c["evidence"]["text"] for c in first],
            ["Please email sam@example.test.", "Please review the report."])
        self.assertEqual([c["candidate_id"] for c in ledger.suggest("synthetic")],
            [c["candidate_id"] for c in first])

    def test_canonical_rows_remain_reviewable_when_adapter_alias_is_ambiguous(self):
        original = self.record("Please review the report.")
        unrelated = replace(original, source_name="other", sender="different@example.test",
            body_raw="Please schedule a meeting.", current_message="Please schedule a meeting.")
        self.store.import_records([original, unrelated])
        self.assertIsNone(self.store.get_email("synthetic"))
        rows = self.store.list_emails()
        self.assertEqual(len(rows), 2)
        ledger = ItemLedger(self.store)
        for row in rows:
            candidates = ledger.suggest(row["source_id"])
            self.assertTrue(candidates)
            item = ledger.decide(candidates[0]["candidate_id"], "APPROVE", 1)
            self.assertEqual(item["source_id"], row["source_id"])
        self.assertEqual(len(ledger.list_items()), 2)

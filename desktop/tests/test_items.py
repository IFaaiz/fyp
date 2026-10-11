from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest

from desktop.local_product.items import ConflictError, ItemLedger
from desktop.local_product.models import EmailRecord
from desktop.local_product.store import EmailStore
from desktop.tests.support import temporary_directory


def _record(source_id: str, body: str, *, subject: str = "Project update") -> EmailRecord:
    return EmailRecord(
        source_id=source_id,
        source_name="synthetic",
        project_or_list="project-demo",
        thread_id="thread-demo",
        subject=subject,
        sender="sender@example.test",
        recipients=("team@example.test",),
        timestamp="2026-10-11T09:30:00+00:00",
        timestamp_kind="sent",
        body_raw=body,
        current_message=body,
        provenance={"adapter": "synthetic"},
    )


def _evidence(text: str, needle: str | None = None) -> dict:
    selected = needle or text
    start = text.index(selected)
    return {"field": "current_message", "start": start, "end": start + len(selected), "text": selected}


class ItemLedgerTests(unittest.TestCase):
    def _fixture(self, body: str = "Please send the revised report by Friday."):
        temp = temporary_directory()
        self.addCleanup(temp.__exit__, None, None, None)
        path = Path(temp.__enter__()) / "archive.sqlite3"
        store = EmailStore(path)
        store.import_records([_record("source-1", body)])
        ledger = ItemLedger(store)
        return store, ledger, path, body

    def test_suggest_persists_source_bound_candidates_without_guessing_owner_or_due(self):
        store, ledger, path, body = self._fixture(
            "Please send the revised report by Friday.\nLet's schedule a meeting on Tuesday."
        )
        suggestions = ledger.suggest("source-1")
        self.assertEqual(len(suggestions), 2)
        report, meeting = suggestions
        self.assertEqual(report["proposed_fields"]["kind"], "DOCUMENT_REQUEST")
        self.assertEqual(report["proposed_fields"]["due"], "")
        self.assertEqual(report["proposed_fields"]["due_text"], "by Friday")
        self.assertEqual(report["proposed_fields"]["owner"], "")
        self.assertIn("OWNER_UNASSIGNED", report["review_flags"])
        self.assertIn("DUE_NOT_NORMALIZED", report["review_flags"])
        self.assertNotIn("SEGMENTATION_UNCERTAIN", report["review_flags"])
        self.assertEqual(meeting["proposed_fields"]["kind"], "MEETING")
        for candidate in suggestions:
            evidence = candidate["evidence"]
            source = store.get_email(candidate["source_id"])
            self.assertEqual(source["current_message"][evidence["start"] : evidence["end"]], evidence["text"])
            self.assertEqual(candidate["input_fingerprint"], source["input_fingerprint"])
        self.assertEqual(len(ledger.list_candidates()), 2)
        with closing(sqlite3.connect(path)) as connection:
            archive_version = connection.execute("PRAGMA user_version").fetchone()[0]
            product_version = connection.execute(
                "SELECT meta_value FROM product_meta WHERE meta_key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(archive_version, 3)
        self.assertEqual(product_version, "1")
        reopened = ItemLedger(EmailStore(path))
        self.assertEqual(len(reopened.list_candidates()), 2)
        self.assertEqual(body, store.get_email("source-1")["current_message"])

    def test_evidence_is_exact_and_candidate_proposals_are_idempotent(self):
        _store, ledger, _path, body = self._fixture()
        fields = {"kind": "DOCUMENT_REQUEST", "title": "Send revised report"}
        evidence = _evidence(body)
        first = ledger.propose("source-1", fields, evidence)
        replay = ledger.propose("source-1", fields, evidence)
        self.assertEqual(first["candidate_id"], replay["candidate_id"])
        self.assertEqual(len(ledger.list_candidates()), 1)
        wrong = dict(evidence, text="different")
        with self.assertRaises(ValueError):
            ledger.propose("source-1", fields, wrong)
        self.assertEqual(len(ledger.list_items()), 0)

    def test_manual_proposals_inherit_source_projection_uncertainty(self):
        temp = temporary_directory()
        self.addCleanup(temp.__exit__, None, None, None)
        path = Path(temp.__enter__()) / "archive.sqlite3"
        store = EmailStore(path)
        source = EmailRecord(
            source_id="projection-source",
            source_name="synthetic",
            subject="Project update",
            sender="sender@example.test",
            timestamp="2026-10-11T09:30:00+00:00",
            timestamp_kind="sent",
            body_raw="Original forwarded text",
            current_message="Please send the revised report.",
            provenance={"adapter": "synthetic"},
        )
        store.import_records([source])
        ledger = ItemLedger(store)
        candidate = ledger.propose(
            "projection-source",
            {"title": "Send revised report", "kind": "DOCUMENT_REQUEST"},
            _evidence(source.current_message),
        )
        self.assertIn("PROJECTION_MISMATCH", candidate["review_flags"])

    def test_approve_replay_creates_one_item_and_undo_appends_cancellation(self):
        _store, ledger, _path, body = self._fixture()
        candidate = ledger.propose(
            "source-1",
            {"kind": "DOCUMENT_REQUEST", "title": "Send revised report", "due_text": "by Friday"},
            _evidence(body),
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: ledger.decide(candidate["candidate_id"], "APPROVE", 1, note="Reviewed"),
                    range(2),
                )
            )
        self.assertEqual(results[0]["item_id"], results[1]["item_id"])
        self.assertEqual(results[0]["status"], results[0]["fields"]["status"])
        self.assertEqual(len(ledger.list_items()), 1)
        with self.assertRaises(ConflictError):
            ledger.decide(candidate["candidate_id"], "APPROVE", 1, note="Different replay")
        with self.assertRaises(ConflictError):
            ledger.decide(candidate["candidate_id"], "REJECT", 1)
        undone = ledger.undo(results[0]["item_id"], 1, "Withdrawn after review")
        self.assertEqual(undone["status"], "CANCELLED")
        loaded = ledger.get_item(undone["item_id"])
        self.assertEqual([event["action"] for event in loaded["history"]], ["APPROVE", "UNDO"])
        self.assertEqual(loaded["history"][1]["note"], "Withdrawn after review")
        self.assertTrue(loaded["history"][1]["diff"])

    def test_corrections_record_diff_and_target_updates_require_explicit_id_and_version(self):
        _store, ledger, _path, body = self._fixture()
        create = ledger.propose(
            "source-1", {"title": "Deliver report", "kind": "TASK"}, _evidence(body)
        )
        with self.assertRaises(ValueError):
            ledger.decide(create["candidate_id"], "APPROVE", create["version"], fields={"title": "Other fact"})
        item = ledger.decide(
            create["candidate_id"],
            "CORRECT",
            create["version"],
            fields={"kind": "DOCUMENT_REQUEST", "status": "IN_PROGRESS"},
            note="Corrected the kind and status",
        )
        self.assertEqual(item["fields"]["kind"], "DOCUMENT_REQUEST")
        self.assertEqual(item["status"], "IN_PROGRESS")
        self.assertEqual(ledger.get_item(item["item_id"])["history"][0]["action"], "CORRECT")

        updated = ledger.propose(
            "source-1",
            {"owner": "analyst@example.test", "status": "DELIVERED", "due_text": "rescheduled to Monday"},
            _evidence(body, "revised report"),
            target_item_id=item["item_id"],
        )
        stale_target = ledger.propose(
            "source-1",
            {"owner": "reviewer@example.test"},
            _evidence(body, "revised report"),
            target_item_id=item["item_id"],
        )
        saved = ledger.decide(updated["candidate_id"], "APPROVE", updated["version"])
        self.assertEqual(saved["item_id"], item["item_id"])
        self.assertEqual(saved["status"], "DELIVERED")
        self.assertEqual(saved["fields"]["owner"], "analyst@example.test")
        self.assertEqual(saved["fields"]["due_text"], "rescheduled to Monday")
        with self.assertRaises(ConflictError):
            ledger.decide(stale_target["candidate_id"], "APPROVE", stale_target["version"])
        self.assertEqual(len(ledger.list_items()), 1)

    def test_history_from_each_update_source_contributes_to_conflict_state(self):
        store, ledger, _path, body = self._fixture()
        created = ledger.propose("source-1", {"title": "Share report"}, _evidence(body))
        item = ledger.decide(created["candidate_id"], "APPROVE", created["version"])
        second_body = "Please review the revised plan."
        store.import_records([_record("source-2", second_body)])
        update = ledger.propose(
            "source-2",
            {"owner": "reviewer@example.test"},
            _evidence(second_body),
            target_item_id=item["item_id"],
        )
        ledger.decide(update["candidate_id"], "APPROVE", update["version"])
        store.import_records([_record("source-1", "Changed source evidence.")])
        changed = ledger.get_item(item["item_id"])
        self.assertTrue(changed["source_conflict"])
        snapshot = ledger.export_snapshot()
        self.assertTrue(snapshot[0]["source_conflict"])
        self.assertEqual(changed["history"][1]["source_id"], "source-2")

    def test_source_revision_conflict_marks_candidate_stale_and_creates_no_fact(self):
        store, ledger, _path, body = self._fixture()
        candidate = ledger.propose("source-1", {"title": "Send report"}, _evidence(body))
        store.import_records([_record("source-1", "Please send the corrected report by Monday.")])
        with self.assertRaises(ConflictError):
            ledger.decide(candidate["candidate_id"], "APPROVE", candidate["version"])
        with self.assertRaises(ConflictError):
            ledger.decide(candidate["candidate_id"], "APPROVE", candidate["version"])
        saved_candidate = next(row for row in ledger.list_candidates() if row["candidate_id"] == candidate["candidate_id"])
        self.assertEqual(saved_candidate["status"], "STALE")
        self.assertTrue(saved_candidate["source_conflict"])
        self.assertEqual(ledger.list_items(), [])

    def test_reject_creates_no_item_and_decision_replay_returns_candidate(self):
        _store, ledger, _path, body = self._fixture()
        candidate = ledger.propose("source-1", {"title": "Possible task"}, _evidence(body))
        rejected = ledger.decide(candidate["candidate_id"], "REJECT", 1, note="Not a commitment")
        replay = ledger.decide(candidate["candidate_id"], "REJECT", 1, note="Not a commitment")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["candidate_id"], replay["candidate_id"])
        self.assertEqual(ledger.list_items(), [])

    def test_export_snapshot_contains_history_and_source_conflict_in_one_shape(self):
        _store, ledger, _path, body = self._fixture()
        candidate = ledger.propose("source-1", {"title": "Send report"}, _evidence(body))
        item = ledger.decide(candidate["candidate_id"], "APPROVE", 1)
        snapshot = ledger.export_snapshot()
        self.assertEqual(snapshot[0]["item_id"], item["item_id"])
        self.assertEqual(len(snapshot[0]["history"]), 1)
        self.assertFalse(snapshot[0]["source_conflict"])
        self.assertEqual(snapshot[0]["history"][0]["evidence"]["text"], body)

    def test_observation_aliases_are_not_accepted_as_canonical_item_sources(self):
        store, ledger, _path, body = self._fixture()
        canonical = EmailRecord(
            source_id="canonical-2",
            source_name="synthetic",
            message_id="message-alias@example.test",
            subject="Aliased source",
            sender="sender@example.test",
            recipients=("team@example.test",),
            timestamp="2026-10-11T09:30:00+00:00",
            timestamp_kind="sent",
            body_raw="Please send the file.",
            current_message="Please send the file.",
            provenance={"adapter": "synthetic"},
        )
        observation = EmailRecord(
            source_id="adapter-alias",
            source_name="other-adapter",
            message_id="message-alias@example.test",
            subject="Aliased source",
            sender="sender@example.test",
            recipients=("team@example.test",),
            timestamp="2026-10-11T09:30:00+00:00",
            timestamp_kind="sent",
            body_raw="Please send the file.",
            current_message="Please send the file.",
            provenance={"adapter": "eml"},
        )
        store.import_records([canonical, observation])
        alias = store.get_email("adapter-alias")
        self.assertEqual(alias["source_id"], "canonical-2")
        with self.assertRaises(ConflictError):
            ledger.propose(
                "adapter-alias",
                {"title": "Send file"},
                _evidence("Please send the file."),
            )


if __name__ == "__main__":
    unittest.main()

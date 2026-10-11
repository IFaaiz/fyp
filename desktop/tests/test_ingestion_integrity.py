"""Synthetic regression coverage for canonical identity and source observations."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unittest

from desktop.local_product.models import EmailRecord
from desktop.local_product.store import AnnotationConflictError, EmailStore
from desktop.tests.support import temporary_directory


class _Classifier:
    def predict(self, record: EmailRecord) -> dict[str, object]:
        return {
            "status": "REVIEW",
            "method": "synthetic-classifier",
            "model_id": "fixture-model",
            "run_id": "fixture-run",
            "schema_version": "fixture-labels-v1",
            "settings_hash": "fixture-settings-v1",
            "labels": ["APPROVAL"],
            "scores": {"APPROVAL": 0.91},
        }


def _record(
    source_id: str,
    *,
    source_name: str = "jsonl",
    body: str = "Please review the report.",
    subject: str = "Project update",
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: tuple[str, ...] = (),
    thread_id: str = "",
    timestamp: str | None = "2026-10-11T12:00:00+00:00",
    sent_at: str | None = "2026-10-11T12:00:00+00:00",
    received_at: str | None = None,
    timestamp_kind: str = "sent",
    source_access_scope: str = "LOCAL_ONLY",
    provenance: dict[str, object] | None = None,
    annotation_method: str = "UNANNOTATED",
    scope: str | None = None,
    labels: tuple[str, ...] = (),
) -> EmailRecord:
    source_provenance = {
        "adapter": source_name,
        "source_access_scope": source_access_scope,
    }
    if provenance:
        source_provenance.update(provenance)
    return EmailRecord(
        source_id=source_id,
        source_name=source_name,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        thread_id=thread_id,
        subject=subject,
        sender="Project Lead <lead@example.test>",
        recipients=("Team <team@example.test>",),
        timestamp=timestamp,
        sent_at=sent_at,
        received_at=received_at,
        timestamp_kind=timestamp_kind,
        body_raw=body,
        current_message=body,
        provenance=source_provenance,
        annotation_method=annotation_method,
        scope=scope,
        labels=labels,
    )


class IngestionIntegrityTests(unittest.TestCase):
    def test_cross_adapter_duplicate_keeps_observation_scopes_separate_and_aliases_resolve(self):
        first = _record(
            "source-a", source_name="eml", body="Same body.\n", message_id="shared@example.test",
            source_access_scope="LOCAL_FILE_READ",
        )
        second = _record(
            "source-b", source_name="outlook", body="Same body.\r\n", message_id="shared@example.test",
            source_access_scope="MAILBOX_READ",
        )
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([first, second])
            canonical = store.get_email("source-a")
            alias = store.get_email("source-b")
            total = store.count()

        self.assertEqual(total, 1)
        self.assertEqual(alias["source_id"], canonical["source_id"])
        self.assertEqual(
            {observation["source_access_scope"] for observation in canonical["source_observations"]},
            {"LOCAL_FILE_READ", "MAILBOX_READ"},
        )
        self.assertEqual(canonical["provenance"]["source_access_scope"], "LOCAL_FILE_READ")
        self.assertEqual(canonical["source_observations"][1]["metadata"]["record"]["body_raw"], "Same body.\r\n")

    def test_reused_message_id_with_different_body_or_sent_instant_stays_distinct(self):
        records = [
            _record("reused-a", message_id="reused@example.test", body="First body."),
            _record("reused-b", source_name="eml", message_id="reused@example.test", body="Second body."),
            _record(
                "reused-c", source_name="outlook", message_id="reused@example.test", body="First body.",
                sent_at="2026-10-11T13:00:00+00:00", timestamp="2026-10-11T13:00:00+00:00",
            ),
        ]
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records(records)
            total = store.count()

        self.assertEqual(total, 3)

    def test_missing_id_dedup_requires_a_known_sent_instant_and_envelope(self):
        sent_a = _record("missing-a", message_id=None)
        sent_b = _record("missing-b", source_name="eml", message_id=None)
        unknown_a = _record("unknown-a", source_name="dataset-a", sent_at=None, timestamp_kind="unspecified")
        unknown_b = _record("unknown-b", source_name="dataset-b", sent_at=None, timestamp_kind="unspecified")
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([sent_a, sent_b, unknown_a, unknown_b])
            total = store.count()
            missing_alias = store.get_email("missing-b")
            unknown_alias = store.get_email("unknown-b")

        self.assertEqual(total, 3)
        self.assertEqual(missing_alias["source_id"], "missing-a")
        self.assertIsNotNone(unknown_alias)

    def test_utc_ordering_uses_instants_and_keeps_ambiguous_times_after_known(self):
        rows = [
            _record("earlier", timestamp="2026-10-11T07:00:00+03:00", sent_at="2026-10-11T07:00:00+03:00"),
            _record("later", timestamp="2026-10-11T06:30:00Z", sent_at="2026-10-11T06:30:00Z"),
            _record("naive", timestamp="2026-10-11T12:00:00", sent_at=None, timestamp_kind="unspecified"),
        ]
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records(rows)
            ordered = [row["source_id"] for row in store.list_emails()]
            saved_naive = store.get_email("naive")

        self.assertEqual(ordered, ["later", "earlier", "naive"])
        self.assertIsNone(saved_naive["timestamp_utc"])
        self.assertEqual(saved_naive["timestamp_info"]["kind"], "naive")

    def test_late_parent_rebuilds_transitive_conversation_without_source_thread_hints(self):
        child = _record("child", message_id="child@example.test", in_reply_to="root@example.test")
        grandchild = _record(
            "grandchild", message_id="grandchild@example.test", in_reply_to="child@example.test",
            timestamp="2026-10-11T13:00:00+00:00",
        )
        root = _record(
            "root", message_id="root@example.test", timestamp="2026-10-11T11:00:00+00:00"
        )
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([grandchild, child])
            before = store.list_threads()
            store.import_records([root])
            saved = [store.get_email(source_id) for source_id in ("root", "child", "grandchild")]
            final_thread = store.list_threads()[0]

        self.assertEqual(len(before), 1)
        self.assertEqual({row["thread_id"] for row in saved}, {"message-thread:root@example.test"})
        self.assertEqual(final_thread["message_count"], 3)

    def test_changed_input_clears_classifier_and_persists_both_revisions(self):
        original = _record("revised", body="We approve the initial report.")
        changed = _record("revised", body="The report needs another review.")
        with temporary_directory() as temp:
            path = Path(temp) / "archive.sqlite3"
            store = EmailStore(path)
            store.import_records([original], classifier=_Classifier())
            store.import_records([changed])
            saved = store.get_email("revised")
            with closing(sqlite3.connect(path)) as connection:
                revisions = connection.execute(
                    "SELECT source_revision, payload_json FROM message_revisions WHERE source_id='revised' ORDER BY source_revision"
                ).fetchall()

        self.assertEqual(saved["source_revision"], 2)
        self.assertIsNone(saved["classifier_status"])
        self.assertEqual(saved["classifier_labels"], [])
        self.assertEqual([row[0] for row in revisions], [1, 2])
        self.assertIn("We approve the initial report.", revisions[0][1])
        self.assertIn("The report needs another review.", revisions[1][1])
        self.assertEqual(saved["rule_derivation"]["input_fingerprint"], changed.input_fingerprint)
        self.assertEqual(saved["extraction_derivation"]["input_fingerprint"], changed.input_fingerprint)

    def test_reviewed_source_revision_conflict_rolls_back_the_whole_batch(self):
        reviewed = _record(
            "reviewed", body="Original reviewed text.", annotation_method="HUMAN_REVIEWED",
            scope="PROJECT", labels=("APPROVAL",),
        )
        changed = _record("reviewed", body="Changed source text.")
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([reviewed])
            with self.assertRaises(AnnotationConflictError):
                store.import_records([_record("would-be-inserted"), changed])
            count = store.count()
            saved = store.get_email("reviewed")

        self.assertEqual(count, 1)
        self.assertEqual(saved["current_message"], "Original reviewed text.")
        self.assertEqual(saved["labels"], ["APPROVAL"])
        self.assertEqual(saved["annotation_method"], "HUMAN_REVIEWED")

    def test_v2_migration_preserves_reviews_and_marks_unbound_legacy_predictions_stale(self):
        reviewed = _record(
            "legacy", body="Keep my reviewed notes.", annotation_method="HUMAN_REVIEWED",
            scope="PROJECT", labels=("APPROVAL",),
        )
        with temporary_directory() as temp:
            path = Path(temp) / "archive.sqlite3"
            store = EmailStore(path)
            store.import_records([reviewed], classifier=_Classifier())
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("DELETE FROM source_aliases")
                connection.execute("DELETE FROM source_observations")
                connection.execute("DELETE FROM message_revisions")
                connection.execute(
                    "UPDATE emails SET classifier_derivation_json='{}' WHERE source_id='legacy'"
                )
                connection.execute("PRAGMA user_version=2")

            migrated = EmailStore(path)
            saved = migrated.get_email("legacy")
            with closing(sqlite3.connect(path)) as connection:
                snapshot = connection.execute(
                    "SELECT payload_json FROM message_revisions WHERE source_id='legacy' AND source_revision=1"
                ).fetchone()[0]

        self.assertEqual(saved["labels"], ["APPROVAL"])
        self.assertEqual(saved["annotation_method"], "HUMAN_REVIEWED")
        self.assertEqual(saved["classifier_status"], "STALE")
        self.assertEqual(saved["classifier_labels"], [])
        self.assertEqual(saved["classifier_scores"], {})
        self.assertIn('"classifier_labels_json":"[\\"APPROVAL\\"]"', snapshot)


if __name__ == "__main__":
    unittest.main()

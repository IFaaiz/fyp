"""Independent synthetic integration checks for ingestion integrity claims."""
from __future__ import annotations

import base64
from contextlib import closing
from email.message import EmailMessage
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest

from desktop.local_product.adapters import EmlAdapter, MsgAdapter, OutlookAdapter
from desktop.local_product.models import EmailRecord
from desktop.local_product.store import EmailStore
from desktop.local_product.temporal import timestamp_info
from desktop.tests.support import temporary_directory


class _Classifier:
    def predict(self, record: EmailRecord) -> dict[str, object]:
        return {
            "status": "REVIEW",
            "method": "synthetic",
            "model_id": "fixture-model",
            "run_id": "fixture-run",
            "schema_version": "fixture-schema",
            "settings_hash": "fixture-settings",
            "labels": ["APPROVAL"],
            "scores": {"APPROVAL": 0.9},
        }


def _record(
    source_id: str,
    *,
    source_name: str = "synthetic",
    adapter: str = "jsonl",
    body: str = "Please review the project report.",
    subject: str = "Project update",
    sender: str = "sender@example.test",
    recipients: tuple[str, ...] = ("team@example.test",),
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: tuple[str, ...] = (),
    thread_id: str = "",
    timestamp: str | None = "2026-10-11T06:00:00Z",
    source_access_scope: str = "scope-a",
    thread_index: str | None = None,
) -> EmailRecord:
    provenance = {"adapter": adapter, "source_access_scope": source_access_scope}
    if thread_index is not None:
        provenance["thread_index"] = thread_index
    return EmailRecord(
        source_id=source_id,
        source_name=source_name,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        thread_id=thread_id,
        subject=subject,
        sender=sender,
        recipients=recipients,
        timestamp=timestamp,
        sent_at=timestamp,
        timestamp_kind="sent" if timestamp else "unspecified",
        body_raw=body,
        current_message=body,
        provenance=provenance,
    )


class IntegrityReviewTests(unittest.TestCase):
    def test_root_only_thread_index_groups_parent_and_replies_without_references(self):
        root = bytes([1]) + bytes(range(21))
        values = [base64.b64encode(root + suffix).decode("ascii") for suffix in (b"", b"12345")]
        parent = _record(
            "index-parent", thread_id=values[0], thread_index=values[0], message_id="root@example.test"
        )
        reply = _record(
            "index-reply", thread_id=values[1], thread_index=values[1], message_id="reply@example.test"
        )

        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([reply, parent])
            saved_parent = store.get_email("index-parent")
            saved_reply = store.get_email("index-reply")
            thread_count = store.list_threads()[0]["message_count"]

        self.assertEqual(saved_parent["thread_id"], saved_reply["thread_id"])
        self.assertEqual(thread_count, 2)
        self.assertEqual(saved_parent["source_observations"][0]["provenance"]["thread_index"], values[0])
        self.assertEqual(saved_reply["source_observations"][0]["provenance"]["thread_index"], values[1])

    def test_late_cross_adapter_duplicate_alias_can_resolve_a_child(self):
        original = _record("json-root", source_name="jsonl", message_id="root@example.test")
        duplicate = _record(
            "eml-root", source_name="eml", adapter="eml", message_id="root@example.test",
            source_access_scope="scope-b",
        )
        child = _record(
            "child",
            message_id="child@example.test",
            in_reply_to="root@example.test",
            timestamp="2026-10-11T07:00:00Z",
        )

        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([original])
            store.import_records([duplicate, child])
            resolved = store.get_email("eml-root")
            parent = store.get_email("json-root")
            saved_child = store.get_email("child")
            total = store.count()

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["source_id"], parent["source_id"])
        self.assertEqual(saved_child["thread_id"], parent["thread_id"])
        self.assertEqual(total, 2)
        self.assertEqual(len(parent["source_observations"]), 2)
        self.assertEqual(
            {item["source_access_scope"] for item in parent["source_observations"]},
            {"scope-a", "scope-b"},
        )
        self.assertEqual(parent["provenance"]["source_access_scope"], "scope-a")

    def test_reused_message_ids_with_different_envelopes_stay_separate(self):
        left = _record(
            "reuse-left", source_name="jsonl", message_id="reused@example.test", sender="left@example.test"
        )
        right = _record(
            "reuse-right", source_name="eml", adapter="eml", message_id="reused@example.test",
            sender="right@example.test",
        )
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([left, right])
            total = store.count()
            left_saved = store.get_email("reuse-left")
            right_saved = store.get_email("reuse-right")

        self.assertEqual(total, 2)
        self.assertNotEqual(left_saved["source_id"], right_saved["source_id"])

    def test_missing_message_ids_alias_only_with_a_complete_sent_envelope(self):
        first = _record("missing-json", source_name="jsonl", message_id=None)
        second = _record("missing-eml", source_name="eml", adapter="eml", message_id=None)
        weak_first = _record(
            "weak-one", source_name="jsonl", message_id=None, timestamp=None,
            subject="", sender="", recipients=(), body="Same text without enough envelope evidence.",
        )
        weak_second = _record(
            "weak-two", source_name="eml", adapter="eml", message_id=None, timestamp=None,
            subject="", sender="", recipients=(), body="Same text without enough envelope evidence.",
        )
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([first, second, weak_first, weak_second])
            total = store.count()
            alias = store.get_email("missing-eml")
            weak_count = sum(item["source_id"].startswith("weak-") for item in store.list_emails())

        self.assertEqual(total, 3)
        self.assertEqual(alias["source_id"], "missing-json")
        self.assertEqual(len(alias["source_observations"]), 2)
        self.assertEqual(weak_count, 2)

    def test_common_explicit_thread_hint_is_preserved_after_graph_rebuild(self):
        parent = _record("hint-parent", thread_id="thread-1", message_id="hint-root@example.test")
        child = _record(
            "hint-child",
            thread_id="thread-1",
            message_id="hint-reply@example.test",
            in_reply_to="hint-root@example.test",
        )
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records([parent, child])
            saved = store.get_email("hint-child")
        self.assertEqual(saved["thread_id"], "thread-1")

    def test_same_eml_basename_in_distinct_directories_is_two_observations(self):
        eml = (
            b"From: sender@example.test\r\n"
            b"To: team@example.test\r\n"
            b"Date: Sun, 11 Oct 2026 06:00:00 +0000\r\n"
            b"Message-ID: <same@example.test>\r\n"
            b"Subject: Synthetic report\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Please review the project report.\r\n"
        )
        with temporary_directory() as temp:
            root = Path(temp)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            left_file, right_file = left / "same.eml", right / "same.eml"
            left_file.write_bytes(eml)
            right_file.write_bytes(eml)
            left_record = next(EmlAdapter(left_file, source_name="archive").iter_records())
            right_record = next(EmlAdapter(right_file, source_name="archive").iter_records())
            store = EmailStore(root / "archive.sqlite3")
            store.import_records([left_record, right_record])
            saved = store.get_email(left_record.source_id)
            total = store.count()

        self.assertEqual(len(saved["source_observations"]), 2)
        self.assertEqual(total, 1)

    def test_ambiguous_reused_source_alias_does_not_select_one_canonical_message(self):
        common = (
            b"From: sender@example.test\r\n"
            b"To: team@example.test\r\n"
            b"Date: Sun, 11 Oct 2026 06:00:00 +0000\r\n"
            b"Message-ID: <same-envelope@example.test>\r\n"
            b"Subject: Synthetic report\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        )
        with temporary_directory() as temp:
            root = Path(temp)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            left_file, right_file = left / "same.eml", right / "same.eml"
            left_file.write_bytes(common + b"First source body.\r\n")
            right_file.write_bytes(common + b"Different source body.\r\n")
            first = next(EmlAdapter(left_file, source_name="archive").iter_records())
            second = next(EmlAdapter(right_file, source_name="archive").iter_records())
            store = EmailStore(root / "archive.sqlite3")
            store.import_records([first, second])
            unresolved = store.get_email(first.source_id)
            count = store.count()

        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(count, 2)
        self.assertIsNone(unresolved)

    def test_normal_reimport_records_each_source_revision_and_initialize_is_idempotent(self):
        with temporary_directory() as temp:
            path = Path(temp) / "archive.sqlite3"
            store = EmailStore(path)
            first = _record("revisioned", body="Please review the first report.")
            changed = _record("revisioned", body="Please review the corrected report.")
            store.import_records([first])
            store.import_records([changed])
            with closing(sqlite3.connect(path)) as connection:
                before = connection.execute(
                    "SELECT COUNT(*), MAX(source_revision) FROM source_observations"
                ).fetchone()
                revisions_before = connection.execute(
                    "SELECT COUNT(*) FROM message_revisions WHERE source_id='revisioned'"
                ).fetchone()[0]
                snapshots_before = connection.execute(
                    "SELECT source_revision, payload_json FROM message_revisions "
                    "WHERE source_id='revisioned' ORDER BY source_revision"
                ).fetchall()
            store.initialize()
            store.initialize()
            with closing(sqlite3.connect(path)) as connection:
                after = connection.execute(
                    "SELECT COUNT(*), MAX(source_revision) FROM source_observations"
                ).fetchone()
                revisions_after = connection.execute(
                    "SELECT COUNT(*) FROM message_revisions WHERE source_id='revisioned'"
                ).fetchone()[0]

        self.assertEqual(tuple(before), (1, 2))
        self.assertEqual(tuple(after), tuple(before))
        self.assertEqual(revisions_before, 2)
        self.assertEqual(revisions_after, revisions_before)
        self.assertEqual(
            [json.loads(row[1])["body_raw"] for row in snapshots_before],
            ["Please review the first report.", "Please review the corrected report."],
        )

    def test_alternate_observation_change_advances_canonical_revision_monotonically(self):
        with temporary_directory() as temp:
            path = Path(temp) / "archive.sqlite3"
            store = EmailStore(path)
            versions = [
                _record("primary", source_name="jsonl", message_id="shared@example.test", body="Version one."),
                _record("primary", source_name="jsonl", message_id="shared@example.test", body="Version two."),
                _record("primary", source_name="jsonl", message_id="shared@example.test", body="Version three."),
                _record("alternate", source_name="eml", adapter="eml", message_id="shared@example.test", body="Version three."),
                _record("alternate", source_name="eml", adapter="eml", message_id="shared@example.test", body="Version four."),
            ]
            revisions: list[int] = []
            for item in versions:
                store.import_records([item])
                with closing(sqlite3.connect(path)) as connection:
                    revisions.append(
                        connection.execute(
                            "SELECT source_revision FROM emails WHERE source_id='primary'"
                        ).fetchone()[0]
                    )
            with closing(sqlite3.connect(path)) as connection:
                snapshots = connection.execute(
                    "SELECT source_revision FROM message_revisions WHERE source_id='primary' ORDER BY source_revision"
                ).fetchall()

        self.assertEqual(revisions, [1, 2, 3, 3, 4])
        self.assertEqual([row[0] for row in snapshots], [1, 2, 3, 4])

    def test_changed_source_without_rescoring_does_not_retain_old_classifier_labels(self):
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            original = _record("prediction", body="We approve the project report.")
            changed = _record("prediction", body="The project report still needs review.")
            store.import_records([original], classifier=_Classifier())
            store.import_records([changed])
            saved = store.get_email("prediction")

        self.assertEqual(saved["classifier_labels"], [])
        self.assertNotEqual(saved["classifier_derivation"].get("input_fingerprint"), original.input_fingerprint)

    def test_msg_and_outlook_keep_adapter_body_raw_whitespace_and_line_endings(self):
        raw_body = " \r\n  Original authored line.\r\n\r\n "

        class FakeMsg:
            body = raw_body
            subject = "Synthetic"
            sender = "sender@example.test"
            to = ""
            cc = ""
            messageId = "<raw-msg@example.test>"
            header = EmailMessage()

            @staticmethod
            def listDir(*_args):
                return []

            @staticmethod
            def getStringStream(_path):
                return None

        with temporary_directory() as temp:
            record = next(
                MsgAdapter(
                    Path(temp) / "synthetic.msg",
                    open_msg=lambda *_args, **_kwargs: FakeMsg(),
                ).iter_records()
            )
        outlook_record = OutlookAdapter()._record_from_item(SimpleNamespace(Class=43, Body=raw_body))

        self.assertEqual(record.body_raw, raw_body)
        self.assertEqual(outlook_record.body_raw, raw_body)

    def test_v2_migration_backfills_timestamp_hint_and_initial_source_snapshot(self):
        with temporary_directory() as temp:
            path = Path(temp) / "archive.sqlite3"
            store = EmailStore(path)
            store.import_records([_record("legacy", thread_id="thread-1", message_id=None)])
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT * FROM emails WHERE source_id='legacy'").fetchone()
                fields = {
                    "subject": row["subject"],
                    "current_message": row["current_message"],
                    "body_raw": row["body_raw"],
                    "attachment_names": json.loads(row["attachment_names_json"]),
                    "timestamp_info": timestamp_info(row["timestamp"]),
                    "version": "legacy-store-fallback-v1",
                }
                input_fingerprint = hashlib.sha256(
                    json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                identity_fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            "subject": row["subject"].strip().casefold(),
                            "sender": [row["sender"].casefold()],
                            "recipients": ["team@example.test"],
                            "body_raw": row["body_raw"],
                            "attachment_names": (),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                connection.execute("DELETE FROM source_observations")
                connection.execute("DELETE FROM source_aliases")
                connection.execute("DELETE FROM message_revisions")
                connection.execute(
                    """UPDATE emails SET input_fingerprint=?, identity_fingerprint=?, timestamp_utc=NULL,
                       timestamp_info_json='{}', source_thread_hint='' WHERE source_id='legacy'""",
                    (input_fingerprint, identity_fingerprint),
                )
                connection.execute("PRAGMA user_version=2")

            migrated = EmailStore(path)
            saved = migrated.get_email("legacy")
            with closing(sqlite3.connect(path)) as connection:
                snapshots = connection.execute(
                    "SELECT COUNT(*) FROM message_revisions WHERE source_id='legacy'"
                ).fetchone()[0]
                observations = connection.execute(
                    "SELECT COUNT(*) FROM source_observations WHERE canonical_source_id='legacy'"
                ).fetchone()[0]

        self.assertEqual(saved["timestamp_utc"], "2026-10-11T06:00:00.000000Z")
        self.assertEqual(saved["timestamp_info"]["kind"], "aware")
        self.assertEqual(saved["source_thread_hint"], "thread-1")
        self.assertEqual(snapshots, 1)
        self.assertEqual(observations, 1)

    def test_sort_uses_known_utc_instants_and_leaves_ambiguous_times_unordered_after_them(self):
        rows = [
            _record("offset-five", timestamp="2026-10-11T10:00:00+05:00"),
            _record("utc-six", timestamp="2026-10-11T06:00:00Z"),
            _record("naive", timestamp="2026-10-11T08:00:00"),
            _record("date-only", timestamp="2026-10-11"),
            _record("malformed", timestamp="next Friday"),
        ]
        with temporary_directory() as temp:
            store = EmailStore(Path(temp) / "archive.sqlite3")
            store.import_records(rows)
            saved = store.list_emails()

        known_ids = [row["source_id"] for row in saved if row["timestamp_utc"]]
        unknown_ids = {row["source_id"] for row in saved if not row["timestamp_utc"]}
        self.assertEqual(known_ids, ["utc-six", "offset-five"])
        self.assertEqual(unknown_ids, {"naive", "date-only", "malformed"})
        self.assertEqual(
            {row["source_id"]: row["timestamp_info"]["kind"] for row in saved if row["source_id"] in unknown_ids},
            {"naive": "naive", "date-only": "date_only", "malformed": "malformed"},
        )


if __name__ == "__main__":
    unittest.main()

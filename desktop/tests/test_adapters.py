from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
from pathlib import Path
import unittest

from desktop.local_product.adapters import EmlAdapter, ImportFormatError, MsgAdapter, OutlookAdapter, iter_jsonl_records
from desktop.local_product.models import EmailRecord
from desktop.tests.support import temporary_directory


def _eml_bytes(subject: str, body: str, *, message_id: str, headers: dict[str, str] | None = None) -> bytes:
    message = EmailMessage()
    message["From"] = "A. Sender <a.sender@example.test>"
    message["To"] = "B. Recipient <b@example.test>"
    message["Cc"] = "C. Copy <c@example.test>"
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message["Date"] = "Fri, 09 Oct 2026 09:30:00 +0000"
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(body)
    message.add_attachment(b"not read by the adapter", maintype="application", subtype="pdf", filename="agenda.pdf")
    return message.as_bytes()


class _FakeAttachment:
    name = "confidential-draft.docx"
    FileName = "confidential-draft.docx"

    @property
    def data(self):
        raise AssertionError("attachment payload must not be accessed")


class _FakeMsg:
    def __init__(self):
        self.body = "Please review the plan.\n\n-----Original Message-----\nFrom: old@example.test\nPlease approve."
        self.subject = "Review plan"
        self.sender = "a.sender@example.test"
        self.to = "b@example.test"
        self.cc = "c@example.test"
        self.date = datetime(2026, 10, 9, 9, 30, tzinfo=timezone.utc)
        self.messageId = "<msg-2@example.test>"
        self.inReplyTo = "<msg-1@example.test>"
        self.header = EmailMessage()
        self.header["References"] = "<root@example.test> <msg-1@example.test>"
        self.attachment_reads = 0

    @property
    def attachments(self):
        self.attachment_reads += 1
        raise AssertionError("attachment objects/payloads must not be constructed")

    def listDir(self, streams, storages, include_prefix):
        assert (streams, storages, include_prefix) == (False, True, False)
        return [["__attach_version1.0_#00000000"], ["__recip_version1.0_#00000000"]]

    def getStringStream(self, path):
        assert path[1] in ("__substg1.0_3707", "__substg1.0_3704")
        return "confidential-draft.docx\0" if path[1] == "__substg1.0_3707" else None


class _FakeRecipient:
    def __init__(self, address: str):
        self.Address = address


class _FakeCollection:
    def __init__(self, values):
        self.values = list(values)
        self.Count = len(self.values)

    def Item(self, index: int):
        return self.values[index - 1]


class _FakeParent:
    StoreID = "store-private-id"


class _FakePropertyAccessor:
    values = {
        "http://schemas.microsoft.com/mapi/proptag/0x1035001F": "<tagged-outlook@example.test>",
        "http://schemas.microsoft.com/mapi/proptag/0x1042001F": "<tagged-parent@example.test>",
        "http://schemas.microsoft.com/mapi/proptag/0x1039001F": "<tagged-root@example.test> <tagged-parent@example.test>",
    }

    def GetProperty(self, schema_name: str):
        return self.values[schema_name]


class _FakeMail:
    Class = 43
    MessageClass = "IPM.Note"
    EntryID = "entry-private-id"
    Parent = _FakeParent()
    PropertyAccessor = _FakePropertyAccessor()
    InternetMessageID = "<outlook-1@example.test>"
    ConversationID = "conversation-private-id"
    ReceivedTime = datetime(2026, 10, 9, 9, 30, tzinfo=timezone.utc)
    Subject = "Please send the report by Friday"
    SenderEmailAddress = "sender@example.test"
    Body = "Please send the report by Friday.\n\n> Older quoted request: please approve this."
    Recipients = _FakeCollection([_FakeRecipient("to@example.test"), _FakeRecipient("cc@example.test")])
    To = "to@example.test"
    CC = "cc@example.test"
    Attachments = _FakeCollection([_FakeAttachment()])


class _FakeItems(_FakeCollection):
    def Sort(self, property_name: str, descending: bool):
        assert property_name == "[ReceivedTime]"
        self.sort_call = (property_name, descending)
        self.values.sort(
            key=lambda item: getattr(item, "ReceivedTime", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=descending,
        )


class _FakeFolder:
    def __init__(self, items):
        self.Items = _FakeItems(items)


class _FakeNamespace:
    def __init__(self, items):
        self.folder = _FakeFolder(items)

    def GetDefaultFolder(self, folder_id: int):
        assert folder_id == 6
        return self.folder


class _FakeOutlook:
    def __init__(self, items):
        self.namespace = _FakeNamespace(items)

    def GetNamespace(self, name: str):
        assert name == "MAPI"
        return self.namespace


class AdapterTests(unittest.TestCase):
    def test_eml_preserves_headers_thread_and_filename_only(self):
        content = _eml_bytes(
            "Please send the report by Friday",
            "Please send the revised report by Friday.\n\nFrom: old@example.test\nSent: Thursday\nTo: team@example.test\nSubject: Old request\nPlease approve the old report.",
            message_id="<reply@example.test>",
            headers={"In-Reply-To": "<parent@example.test>", "References": "<root@example.test> <parent@example.test>", "List-Id": "project-list.example.test"},
        )
        record = EmlAdapter.parse_bytes(content, path_name="message.eml", source_name="fixture")
        self.assertEqual(record.source_name, "fixture")
        self.assertEqual(record.message_id, "reply@example.test")
        self.assertEqual(record.in_reply_to, "parent@example.test")
        self.assertEqual(record.references, ("root@example.test", "parent@example.test"))
        self.assertEqual(record.canonical_thread_id, "message-thread:root@example.test")
        self.assertEqual(record.recipients, ("B. Recipient <b@example.test>", "C. Copy <c@example.test>"))
        self.assertEqual(record.attachment_names, ("agenda.pdf",))
        self.assertIn("Please send the revised report by Friday.", record.current_message)
        self.assertIn("Please approve the old report.", record.quoted_history)
        self.assertNotIn("Please approve the old report.", record.current_message)
        self.assertEqual(record.labels, ())
        self.assertEqual(record.annotation_method, "UNANNOTATED")
        self.assertEqual(record.provenance["file_name"], "message.eml")

    def test_eml_can_be_imported_from_a_path(self):
        with temporary_directory() as temp:
            path = Path(temp) / "item.eml"
            path.write_bytes(_eml_bytes("Update", "The report is attached.", message_id="<item@example.test>"))
            record = next(EmlAdapter(path).iter_records())
            self.assertEqual(record.subject, "Update")
            self.assertEqual(record.current_message, "The report is attached.")

    def test_html_only_message_excludes_hidden_text_and_quoted_block(self):
        message = EmailMessage()
        message["Subject"] = "Project"
        message.set_content('<html><head><style>Please approve.</style></head><body><p>Please review <b>the plan</b>.</p><script>Please approve by Friday.</script><blockquote>Please send the old report.</blockquote></body></html>', subtype="html")
        record = EmlAdapter.parse_bytes(message.as_bytes())
        self.assertEqual(record.current_message, "Please review the plan.")
        self.assertNotIn("approve", record.body_raw)
        self.assertIn("old report", record.quoted_history)

    def test_msg_uses_public_metadata_only_and_does_not_read_attachment_data(self):
        with temporary_directory() as temp:
            path = Path(temp) / "message.msg"
            path.write_bytes(b"synthetic fixture bytes")
            opened = []

            fake = _FakeMsg()

            def open_msg(filename, **kwargs):
                self.assertEqual(kwargs, {"delayAttachments": True})
                opened.append(filename)
                return fake

            record = next(MsgAdapter(path, open_msg=open_msg).iter_records())
            self.assertEqual(opened, [str(path)])
            self.assertEqual(record.subject, "Review plan")
            self.assertEqual(record.in_reply_to, "msg-1@example.test")
            self.assertEqual(record.references, ("root@example.test", "msg-1@example.test"))
            self.assertEqual(record.attachment_names, ("confidential-draft.docx",))
            self.assertEqual(fake.attachment_reads, 0)
            self.assertNotIn("Please approve.", record.current_message)
            self.assertIn("Please approve.", record.quoted_history)

    def test_jsonl_contract_preserves_metadata_and_accepts_scope_alias(self):
        row = {
            "source_id": "public:message-1",
            "source_name": "w3c",
            "project_or_list": "working-group",
            "message_id": "<m1@example.test>",
            "in_reply_to": None,
            "references": [],
            "thread_id": "thread-1",
            "subject": "Update",
            "sender": "sender@example.test",
            "recipients": ["team@example.test"],
            "timestamp": "2026-10-09T09:30:00Z",
            "body_raw": "The report is attached.",
            "current_message": "The report is attached.",
            "quoted_history": "",
            "attachment_names": ["agenda.pdf"],
            "provenance": {"archive": "public"},
            "license_or_terms_note": "Internal retention permitted.",
            "metadata_quality": "public_source_candidate",
            "leakage_group": "thread-group-3",
            "split": "TRAIN",
            "source_url": "https://example.test/archive/message-1",
            "checksum": "abc123",
            "labels": ["PROJECT", "GENERAL_UPDATE"],
            "annotation_method": "HUMAN_REVIEWED",
        }
        with temporary_directory() as temp:
            path = Path(temp) / "corpus.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            record = next(iter_jsonl_records(path))
        self.assertEqual(record.source_id, "public:message-1")
        self.assertEqual(record.scope, "PROJECT")
        self.assertEqual(record.labels, ("GENERAL_UPDATE",))
        self.assertEqual(record.project_or_list, "working-group")
        self.assertEqual(record.license_or_terms_note, "Internal retention permitted.")
        self.assertEqual(record.attachment_names, ("agenda.pdf",))
        self.assertEqual(
            record.provenance["source_metadata"],
            {
                "metadata_quality": "public_source_candidate",
                "leakage_group": "thread-group-3",
                "split": "TRAIN",
                "source_url": "https://example.test/archive/message-1",
                "checksum": "abc123",
            },
        )

    def test_jsonl_preserves_all_parent_ids_when_in_reply_to_is_a_list(self):
        row = {
            "source_id": "public:reply",
            "source_name": "w3c",
            "message_id": "reply@example.test",
            "in_reply_to": ["<parent@example.test>", "<older-parent@example.test>"],
            "references": [],
            "body_raw": "Thanks.",
            "current_message": "Thanks.",
            "labels": [],
            "annotation_method": "UNANNOTATED",
        }
        record = EmailRecord.from_mapping(row)
        self.assertEqual(record.in_reply_to, "parent@example.test")
        self.assertEqual(
            record.provenance["in_reply_to_observed"],
            ["<parent@example.test>", "<older-parent@example.test>"],
        )

    def test_jsonl_rejects_invalid_row_without_echoing_message_text(self):
        with temporary_directory() as temp:
            path = Path(temp) / "bad.jsonl"
            path.write_text('{"source_id":"x","source_name":"test","body_raw":"private fixture","labels":["MADE_UP"]}\n', encoding="utf-8")
            with self.assertRaises(ImportFormatError) as raised:
                list(iter_jsonl_records(path))
        self.assertNotIn("private fixture", str(raised.exception))
        self.assertIn("line 1", str(raised.exception))

    def test_outlook_adapter_uses_fake_com_and_skips_non_mail_objects(self):
        non_mail = type("Other", (), {"Class": 2, "Subject": "Task", "Body": "No email"})()
        outlook = _FakeOutlook([non_mail, _FakeMail()])
        adapter = OutlookAdapter(application_factory=lambda: outlook)
        record = next(adapter.iter_records())
        self.assertEqual(record.source_name, "outlook")
        self.assertEqual(record.subject, "Please send the report by Friday")
        self.assertEqual(record.message_id, "tagged-outlook@example.test")
        self.assertEqual(record.in_reply_to, "tagged-parent@example.test")
        self.assertEqual(record.references, ("tagged-root@example.test", "tagged-parent@example.test"))
        self.assertEqual(record.attachment_names, ("confidential-draft.docx",))
        self.assertTrue(record.thread_id.startswith("outlook-conversation:"))
        self.assertNotIn("Older quoted request", record.current_message)
        self.assertEqual(record.annotation_method, "UNANNOTATED")
        self.assertEqual(outlook.namespace.folder.Items.sort_call, ("[ReceivedTime]", True))

    def test_outlook_import_is_newest_first_and_bounded(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        items = []
        for index in range(205):
            mail = _FakeMail()
            mail.EntryID = f"entry-{index}"
            mail.ReceivedTime = base.replace(day=1) + timedelta(days=index)
            items.append(mail)
        outlook = _FakeOutlook(items)
        records = list(OutlookAdapter(application_factory=lambda: outlook).iter_records())
        self.assertEqual(len(records), 200)
        self.assertEqual(records[0].timestamp, (base + timedelta(days=204)).isoformat())
        self.assertEqual(records[-1].timestamp, (base + timedelta(days=5)).isoformat())

    def test_outlook_limit_rejects_unbounded_or_invalid_values(self):
        for limit in (0, -1, 5001, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                OutlookAdapter(limit=limit)


if __name__ == "__main__":
    unittest.main()

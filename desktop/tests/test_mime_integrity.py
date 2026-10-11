from __future__ import annotations

from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
import unittest

from desktop.local_product.adapters import EmlAdapter, MsgAdapter, OutlookAdapter


def _nested_email(subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = "nested@example.test"
    message["Subject"] = subject
    message.set_content(body)
    return message


class _SyntheticOutlookMessage:
    Class = 43
    MessageClass = "IPM.Note"
    Subject = "Outlook timestamp fixture"
    Body = "Synthetic body."
    SenderEmailAddress = "sender@example.test"
    EntryID = "synthetic-entry"
    ConversationID = "synthetic-conversation"
    SentOn = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    ReceivedTime = None


class _SyntheticMsg:
    def __init__(self, *, body: str, subject: str = "MSG status", sender: str = "sender@example.test"):
        self.body = body
        self.subject = subject
        self.sender = sender
        self.to = "team@example.test"
        self.cc = ""
        self.date = datetime(2026, 10, 9, 9, 30, tzinfo=timezone.utc)
        self.messageId = "<reused-msg@example.test>"
        self.inReplyTo = ""
        self.header = EmailMessage()
        self.header["Date"] = "Fri, 09 Oct 2026 09:30:00 +0000"

    def listDir(self, streams, storages, include_prefix):
        return []

    def getStringStream(self, path):
        return None


class MimeIntegrityTests(unittest.TestCase):
    def test_attached_emails_are_excluded_and_unnamed_ones_are_recorded(self):
        outer = EmailMessage()
        outer["Subject"] = "Outer message"
        outer.set_content("Keep this outer body.")
        outer.add_attachment(_nested_email("Named attachment", "SECRET NAMED EMAIL BODY."), filename="forwarded.eml")
        outer.add_attachment(_nested_email("Unnamed attachment", "SECRET UNNAMED EMAIL BODY."))

        record = EmlAdapter.parse_bytes(outer.as_bytes())

        self.assertEqual(record.body_raw.strip(), "Keep this outer body.")
        self.assertEqual(record.current_message, "Keep this outer body.")
        self.assertNotIn("SECRET", record.body_raw)
        self.assertEqual(record.attachment_names, ("forwarded.eml", "attached-message.eml"))

    def test_multipart_attachment_is_a_boundary_and_keeps_its_filename(self):
        outer = EmailMessage()
        outer["Subject"] = "Outer message"
        outer.make_mixed()
        body = EmailMessage()
        body.set_content("Outer text only.")
        outer.attach(body)

        bundle = EmailMessage()
        bundle.make_mixed()
        bundle.add_header("Content-Disposition", "attachment", filename="nested-bundle.mime")
        child = EmailMessage()
        child.set_content("SECRET MULTIPART ATTACHMENT BODY.")
        bundle.attach(child)
        outer.attach(bundle)

        parsed = BytesParser(policy=policy.default).parsebytes(outer.as_bytes())
        record = EmlAdapter.parse_bytes(parsed.as_bytes())

        self.assertEqual(record.body_raw.strip(), "Outer text only.")
        self.assertNotIn("SECRET", record.body_raw)
        self.assertEqual(record.attachment_names, ("nested-bundle.mime",))

    def test_attached_plaintext_cannot_suppress_outer_html_body(self):
        outer = EmailMessage()
        outer["Subject"] = "HTML outer message"
        outer.set_content("<html><body><p>Outer HTML survives.</p></body></html>", subtype="html")
        outer.add_attachment(_nested_email("Attached plaintext", "SECRET NESTED PLAIN BODY."))

        record = EmlAdapter.parse_bytes(outer.as_bytes())

        self.assertEqual(record.current_message, "Outer HTML survives.")
        self.assertNotIn("SECRET", record.body_raw)
        self.assertEqual(record.attachment_names, ("attached-message.eml",))

    def test_unnamed_non_message_attachment_gets_a_fallback_name(self):
        outer = EmailMessage()
        outer["Subject"] = "Outer message"
        outer.make_mixed()
        body = EmailMessage()
        body.set_content("Outer body.")
        outer.attach(body)
        unnamed = EmailMessage()
        unnamed.set_content("SECRET ATTACHMENT BODY.")
        unnamed["Content-Disposition"] = "attachment"
        outer.attach(unnamed)

        record = EmlAdapter.parse_bytes(outer.as_bytes())

        self.assertEqual(record.body_raw.strip(), "Outer body.")
        self.assertNotIn("SECRET", record.body_raw)
        self.assertEqual(record.attachment_names, ("unnamed-attachment",))

    def test_reused_message_id_uses_the_envelope_but_ignores_body_changes(self):
        first = EmailMessage()
        first["From"] = "one@example.test"
        first["To"] = "team@example.test"
        first["Subject"] = "Status update"
        first["Message-ID"] = "<reused@example.test>"
        first["Date"] = "Fri, 09 Oct 2026 09:30:00 +0000"
        first["Thread-Index"] = "AQIDBAUGBwg="
        first.set_content("Original body.")

        changed_body = EmailMessage()
        for name, value in first.items():
            changed_body[name] = value
        changed_body.set_content("Corrected body.")

        different_envelope = EmailMessage()
        different_envelope["From"] = "two@example.test"
        different_envelope["To"] = "team@example.test"
        different_envelope["Subject"] = "Another message"
        different_envelope["Message-ID"] = "<reused@example.test>"
        different_envelope["Date"] = "Fri, 09 Oct 2026 10:30:00 +0000"
        different_envelope.set_content("Original body.")

        first_record = EmlAdapter.parse_bytes(first.as_bytes())
        corrected_record = EmlAdapter.parse_bytes(changed_body.as_bytes())
        other_record = EmlAdapter.parse_bytes(different_envelope.as_bytes())

        self.assertEqual(first_record.source_id, corrected_record.source_id)
        self.assertNotEqual(first_record.source_id, other_record.source_id)
        self.assertEqual(first_record.sent_at, "Fri, 09 Oct 2026 09:30:00 +0000")
        self.assertEqual(first_record.timestamp, "2026-10-09T09:30:00+00:00")
        self.assertEqual(first_record.timestamp_kind, "sent")
        self.assertEqual(first_record.provenance["thread_index"], "AQIDBAUGBwg=")

    def test_outlook_keeps_sent_and_received_times_separate(self):
        adapter = OutlookAdapter()
        item = _SyntheticOutlookMessage()

        sent_only = adapter._record_from_item(item)

        self.assertIsNotNone(sent_only)
        self.assertEqual(sent_only.sent_at, "2026-10-09T08:00:00+00:00")
        self.assertIsNone(sent_only.received_at)
        self.assertEqual(sent_only.timestamp, sent_only.sent_at)
        self.assertEqual(sent_only.timestamp_kind, "sent")

        item.ReceivedTime = datetime(2026, 10, 9, 8, 5, tzinfo=timezone.utc)
        sent_and_received = adapter._record_from_item(item)

        self.assertIsNotNone(sent_and_received)
        self.assertEqual(sent_and_received.sent_at, "2026-10-09T08:00:00+00:00")
        self.assertEqual(sent_and_received.received_at, "2026-10-09T08:05:00+00:00")
        self.assertEqual(sent_and_received.timestamp, sent_and_received.received_at)
        self.assertEqual(sent_and_received.timestamp_kind, "received")

    def test_msg_reused_message_id_uses_envelope_and_ignores_body_changes(self):
        def parse(body: str, subject: str = "MSG status"):
            fake = _SyntheticMsg(body=body, subject=subject)
            opener = lambda *_args, **_kwargs: fake
            return next(MsgAdapter(Path("synthetic.msg"), open_msg=opener).iter_records())

        original = parse("Original body.")
        changed_body = parse("Corrected body.")
        different_envelope = parse("Original body.", subject="Another MSG")

        self.assertEqual(original.source_id, changed_body.source_id)
        self.assertNotEqual(original.source_id, different_envelope.source_id)


if __name__ == "__main__":
    unittest.main()

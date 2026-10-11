"""Generated EML/JSONL files and mocked MSG/COM through the same canonical store."""
from dataclasses import replace
from datetime import datetime, timezone
from email.message import EmailMessage
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from desktop.local_product.adapters import EmlAdapter, MsgAdapter, OutlookAdapter, iter_jsonl_records
from desktop.local_product.store import EmailStore
from desktop.tests.support import temporary_directory
from desktop.tests.test_adapters import _FakeCollection, _FakeOutlook


class AdapterPipelineTests(unittest.TestCase):
    def test_four_actual_adapter_paths_alias_without_scope_union_or_replay_duplicates(self):
        body = "Please send the design report by Friday."
        message = EmailMessage()
        for key, value in {"Subject": "Design report", "From": "Lead <lead@example.test>",
                           "To": "Team <team@example.test>", "Date": "Sun, 11 Oct 2026 15:00:00 +0500",
                           "Message-ID": "<four-adapters@example.test>"}.items():
            message[key] = value
        message.set_content(body)
        msg = SimpleNamespace(body=body + "\r\n", header=message, messageId="<four-adapters@example.test>",
            subject="Design report", sender="lead@example.test", to="team@example.test", cc="",
            date=datetime(2026, 10, 11, 10, tzinfo=timezone.utc),
            listDir=lambda *_: [], getStringStream=lambda _: None, close=lambda: None)
        mail = SimpleNamespace(Class=43, MessageClass="IPM.Note", EntryID="synthetic-entry",
            InternetMessageID="<four-adapters@example.test>", Subject="Design report", Body=body + "\r\n",
            SenderEmailAddress="lead@example.test", To="team@example.test", CC="",
            SentOn=datetime(2026, 10, 11, 10, tzinfo=timezone.utc),
            ReceivedTime=datetime(2026, 10, 11, 10, 2, tzinfo=timezone.utc),
            Recipients=_FakeCollection([SimpleNamespace(Address="team@example.test")]),
            Attachments=_FakeCollection([]))
        with temporary_directory() as scratch:
            root = Path(scratch)
            eml_path = root / "synthetic.eml"
            eml_path.write_bytes(message.as_bytes())
            eml = next(EmlAdapter(eml_path).iter_records())
            standalone_msg = next(MsgAdapter(root / "synthetic.msg", open_msg=lambda *_args, **_kwargs: msg).iter_records())
            outlook = next(OutlookAdapter(application_factory=lambda: _FakeOutlook([mail]), limit=1).iter_records())
            jsonl_path = root / "synthetic.jsonl"
            jsonl_path.write_text(json.dumps({**eml.to_dict(), "source_id": "synthetic-jsonl",
                "source_name": "jsonl", "body_raw": body, "timestamp": "2026-10-11T10:00:00Z",
                "sent_at": "2026-10-11T10:00:00Z"}) + "\n", encoding="utf-8")
            normalized = next(iter_jsonl_records(jsonl_path))
            records = [replace(record, provenance={**record.provenance, "source_access_scope": f"scope-{index}"})
                       for index, record in enumerate([eml, standalone_msg, outlook, normalized])]
            store = EmailStore(root / "canonical.sqlite3")
            store.import_records(records)
            store.import_records(records)
            self.assertEqual(store.count(), 1)
            canonical = store.list_emails()[0]
            self.assertEqual(len(canonical["source_observations"]), 4)
            self.assertEqual({o["source_access_scope"] for o in canonical["source_observations"]},
                             {f"scope-{index}" for index in range(4)})
            self.assertEqual(canonical["provenance"]["source_access_scope"], "scope-0")
            self.assertEqual(canonical["source_revision"], 1)
            for record in records:
                self.assertEqual(store.get_email(record.source_id)["source_id"], canonical["source_id"])

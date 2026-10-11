"""Reproduce the six pre-fix ingestion defects against the frozen baseline.

This diagnostic loads source modules returned by ``git show <revision>:...`` into
a fresh package namespace. By default it uses the original audit baseline and
can be overridden with ``--revision``. It uses synthetic messages and shared
in-memory SQLite, then prints aggregate booleans without fixture text.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from email.message import EmailMessage
import json
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

_BASELINE_REVISION = "3df6c0edaeaa4a06c368f8ee08581e889a0c6ec0"


def _old_module(name: str, package: str, revision: str) -> types.ModuleType:
    path = f"desktop/local_product/{name}.py"
    source = subprocess.check_output(
        ["git", "show", f"{revision}:{path}"], text=True, encoding="utf-8"
    )
    full_name = f"{package}.{name}"
    module = types.ModuleType(full_name)
    module.__file__ = f"git-show:{path}"
    module.__package__ = package
    sys.modules[full_name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    setattr(sys.modules[package], name, module)
    return module


def _load_legacy(revision: str) -> types.ModuleType:
    package_name = "ingestion_v2_head"
    package = types.ModuleType(package_name)
    package.__path__ = []
    sys.modules[package_name] = package
    for name in ("preprocessing", "models", "classification", "extraction", "adapters", "store"):
        _old_module(name, package_name, revision)
    return sys.modules[package_name]


class _Collection:
    Count = 0


class _Parent:
    StoreID = "synthetic-store"


class _PropertyAccessor:
    def GetProperty(self, schema_name: str):
        if schema_name == "http://schemas.microsoft.com/mapi/proptag/0x1035001F":
            return "<same@example.test>"
        raise KeyError(schema_name)


class _OutlookItem:
    Class = 43
    MessageClass = "IPM.Note"
    EntryID = "synthetic-entry"
    Parent = _Parent()
    PropertyAccessor = _PropertyAccessor()
    InternetMessageID = "<same@example.test>"
    ConversationID = "synthetic-conversation"
    ReceivedTime = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)
    SentOn = ReceivedTime
    Subject = "Synthetic status"
    SenderEmailAddress = "sender@example.test"
    Body = "Synthetic duplicate body."
    Recipients = _Collection()
    Attachments = _Collection()
    To = "team@example.test"
    CC = ""


class _Msg:
    def __init__(self, body: str = "Synthetic duplicate body."):
        self.body = body
        self.subject = "Synthetic status"
        self.sender = "sender@example.test"
        self.to = "team@example.test"
        self.cc = ""
        self.date = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)
        self.messageId = "<same@example.test>"
        self.inReplyTo = ""
        self.header = EmailMessage()
        self.header["Date"] = "Sun, 11 Oct 2026 06:00:00 +0000"

    def listDir(self, streams, storages, include_prefix):
        return []

    def getStringStream(self, path):
        return None


class _Classifier:
    def predict(self, record):
        return {
            "method": "SYNTHETIC_DIAGNOSTIC",
            "status": "PREDICTED",
            "run_id": "synthetic-run",
            "labels": ["APPROVAL"],
            "scores": {"APPROVAL": 0.99},
        }


def _memory_store(store_module, name: str):
    """Run the legacy store against shared in-memory SQLite, without files."""

    class MemoryStore(store_module.EmailStore):
        def __init__(self):
            self.path = Path(f"synthetic-{name}.sqlite3")
            self._uri = f"file:ingestion-v2-{name}?mode=memory&cache=shared"
            self._keeper = sqlite3.connect(self._uri, uri=True)
            self.initialize()

        def _connect(self):
            connection = sqlite3.connect(self._uri, timeout=15, uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 15000")
            return connection

    return MemoryStore()


def _record(models, source_id: str, *, body: str, timestamp: str | None = None, **values):
    current, quoted = sys.modules["ingestion_v2_head.preprocessing"].split_authored_text(body)
    return models.EmailRecord(
        source_id=source_id,
        source_name="synthetic",
        timestamp=timestamp,
        body_raw=body,
        current_message=current,
        quoted_history=quoted,
        **values,
    )


def reproduce(revision: str = _BASELINE_REVISION) -> dict[str, bool]:
    legacy = _load_legacy(revision)
    adapters = sys.modules["ingestion_v2_head.adapters"]
    models = legacy.models
    flags: dict[str, bool] = {}

    outer = EmailMessage()
    outer["From"] = "outer@example.test"
    outer["Subject"] = "Synthetic outer"
    outer["Message-ID"] = "<same@example.test>"
    outer.set_content("For reference only.")
    nested = EmailMessage()
    nested["Subject"] = "Synthetic attachment"
    nested.set_content("Synthetic approval request.")
    outer.add_attachment(nested, filename="attached-message.eml")
    parsed = adapters.EmlAdapter.parse_bytes(outer.as_bytes())
    flags["attached_email_contamination"] = (
        "Synthetic approval request." in parsed.current_message
        and "attached-message.eml" not in parsed.attachment_names
    )

    records = [parsed]
    records.extend(adapters.MsgAdapter(Path("synthetic.msg"), open_msg=lambda *_args, **_kwargs: _Msg()).iter_records())
    records.append(adapters.OutlookAdapter()._record_from_item(_OutlookItem()))
    jsonl_record = models.EmailRecord.from_mapping(
        {
            "source_id": "jsonl:synthetic-observation",
            "source_name": "jsonl",
            "message_id": "<same@example.test>",
            "body_raw": "Synthetic duplicate body.",
            "current_message": "Synthetic duplicate body.",
        }
    )
    records.append(jsonl_record)
    duplicate_store = _memory_store(legacy.store, "duplicates")
    duplicate_store.import_records(records)
    flags["cross_format_duplicate_observations"] = duplicate_store.count() == 4

    time_store = _memory_store(legacy.store, "times")
    earlier = _record(
        models, "synthetic-early", body="Synthetic early instant.",
        timestamp="2026-10-11T10:00:00+05:00",
    )
    later = _record(
        models, "synthetic-late", body="Synthetic later instant.",
        timestamp="2026-10-11T06:00:00Z",
    )
    time_store.import_records([earlier, later])
    flags["timezone_lexical_sort"] = time_store.list_emails()[0]["source_id"] == "synthetic-early"

    prediction_store = _memory_store(legacy.store, "predictions")
    original = _record(models, "stable-source", body="Synthetic approval request.")
    changed = _record(models, "stable-source", body="Synthetic acknowledgement.")
    prediction_store.import_records([original], classifier=_Classifier())
    prediction_store.import_records([changed])
    flags["stale_classifier_prediction"] = prediction_store.get_email("stable-source")["classifier_labels"] == ["APPROVAL"]

    root_bytes = bytes([1]) + bytes(range(21))
    parent_index = base64.b64encode(root_bytes).decode("ascii")
    child_index = base64.b64encode(root_bytes + b"12345").decode("ascii")
    parent = _record(models, "synthetic-parent", body="Synthetic parent.", thread_id=parent_index)
    child = _record(models, "synthetic-child", body="Synthetic child.", thread_id=child_index)
    chain_root = _record(models, "chain-root", body="Synthetic root.", message_id="root@example.test")
    chain_middle = _record(
        models, "chain-middle", body="Synthetic middle.", message_id="middle@example.test",
        in_reply_to="root@example.test",
    )
    chain_leaf = _record(
        models, "chain-leaf", body="Synthetic leaf.", message_id="leaf@example.test",
        in_reply_to="middle@example.test",
    )
    flags["thread_alias_and_chain_split"] = (
        parent.canonical_thread_id != child.canonical_thread_id
        and len({chain_root.canonical_thread_id, chain_middle.canonical_thread_id, chain_leaf.canonical_thread_id}) > 1
    )

    current, _ = legacy.preprocessing.split_authored_text(
        "> Can we submit on Friday?\nNo, the deadline is Monday."
    )
    flags["inline_reply_loss"] = "deadline is Monday" not in current
    return flags


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=_BASELINE_REVISION, help="source revision to load (default: original audit baseline)")
    print(json.dumps(reproduce(parser.parse_args().revision), sort_keys=True))

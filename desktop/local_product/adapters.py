"""Read-only adapters for RFC822, Outlook MSG, classic Outlook, and JSONL."""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Protocol

from .models import EmailRecord, normalize_message_id, parse_message_ids
from .preprocessing import split_authored_text


class EmailAdapter(Protocol):
    def iter_records(self) -> Iterator[EmailRecord]: ...


class ImportFormatError(ValueError):
    """Input could not be converted to the local record contract."""


class _PlainHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if not self.hidden:
            if tag in {"br", "p", "div", "pre"}:
                self.parts.append("\n")
            elif tag == "blockquote":
                self.parts.append("\n> ")

    def handle_endtag(self, tag) -> None:
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div", "pre", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _message_headers(message: Message, name: str) -> list[str]:
    return [str(value) for value in message.get_all(name, []) if str(value).strip()]


def _body_from_mime(message: Message) -> tuple[str, tuple[str, ...]]:
    plain: list[str] = []
    html: list[str] = []
    names: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename:
            filename = str(filename).strip()
            if filename and filename not in names:
                names.append(filename)
        # Do not decode or read attachment payloads. Only message-body parts
        # without an attachment filename/disposition are considered here.
        if disposition == "attachment" or filename:
            continue
        if part.get_content_type() == "text/plain":
            try:
                value = part.get_content()
            except (LookupError, UnicodeDecodeError, KeyError):
                value = ""
            if isinstance(value, str) and value:
                plain.append(value)
        elif part.get_content_type() == "text/html":
            try:
                value = part.get_content()
            except (LookupError, UnicodeDecodeError, KeyError):
                value = ""
            if isinstance(value, str) and value:
                parser = _PlainHTML()
                parser.feed(value)
                parser.close()
                html.append("".join(parser.parts))
    parts = plain or html
    return "\n".join(parts), tuple(names)


def _addresses(values: list[str]) -> tuple[str, ...]:
    found: list[str] = []
    for display_name, address in getaddresses(values):
        value = f"{display_name} <{address}>" if display_name and address else address or display_name
        value = value.strip()
        if value and value not in found:
            found.append(value)
    return tuple(found)


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return value.strip() or None


def _stable_source_id(prefix: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:32]
    return f"{prefix}:{digest}"


class EmlAdapter:
    """Parse one RFC822 .eml file, preserving headers and attachment names."""

    def __init__(self, path: str | Path, *, source_name: str = "eml") -> None:
        self.path = Path(path)
        self.source_name = source_name

    def iter_records(self) -> Iterator[EmailRecord]:
        yield self.parse_bytes(self.path.read_bytes(), path_name=self.path.name, source_name=self.source_name)

    @staticmethod
    def parse_bytes(content: bytes, *, path_name: str = "message.eml", source_name: str = "eml") -> EmailRecord:
        try:
            message = BytesParser(policy=policy.default).parsebytes(content)
        except Exception as exc:
            raise ImportFormatError("Could not parse the RFC822 message.") from exc
        body, attachment_names = _body_from_mime(message)
        current, quoted = split_authored_text(body)
        message_id = normalize_message_id(str(message.get("Message-ID") or ""))
        in_reply_to = normalize_message_id(" ".join(_message_headers(message, "In-Reply-To")))
        references = parse_message_ids(_message_headers(message, "References"))
        thread_id = _header_first(message, ("Thread-Index", "X-Thread-ID"))
        if not thread_id:
            thread_id = f"message-thread:{references[0]}" if references else (
                f"message-thread:{in_reply_to}" if in_reply_to else ""
            )
        provenance = {
            "adapter": "eml",
            "file_name": path_name,
            "list_id": _header_first(message, ("List-Id",)),
        }
        source_identity = f"message-id:{message_id}" if message_id else "content:" + hashlib.sha256(content).hexdigest()
        return EmailRecord(
            source_id=_stable_source_id("eml", source_identity),
            source_name=source_name,
            project_or_list=_header_first(message, ("X-Project", "List-Id")) or "",
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
            thread_id=thread_id,
            subject=str(message.get("Subject") or ""),
            sender=str(message.get("From") or ""),
            recipients=_addresses(_message_headers(message, "To") + _message_headers(message, "Cc")),
            timestamp=_parse_date(str(message.get("Date") or "")),
            body_raw=body,
            current_message=current,
            quoted_history=quoted,
            attachment_names=attachment_names,
            provenance=provenance,
            license_or_terms_note=_header_first(message, ("X-License-Note",)) or "",
            labels=(),
            annotation_method="UNANNOTATED",
        )


def _header_first(message: Message, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = message.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return default if value is None else value


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else (str(value).strip() if value is not None else "")


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    return _as_text(value) or None


def _header_obj(msg: Any) -> Message | None:
    header = _safe_attr(msg, "header")
    return header if hasattr(header, "get_all") else None


class MsgAdapter:
    """Parse a standalone .msg with extract-msg; only attachment names are read."""

    def __init__(
        self,
        path: str | Path,
        *,
        source_name: str = "msg",
        open_msg: Callable[..., Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.source_name = source_name
        self._open_msg = open_msg

    def iter_records(self) -> Iterator[EmailRecord]:
        opener = self._open_msg
        if opener is None:
            try:
                import extract_msg
            except ImportError as exc:
                raise RuntimeError(
                    "Reading .msg files needs extract-msg; install desktop/requirements-msg.txt."
                ) from exc
            opener = extract_msg.openMsg
        # extract-msg otherwise constructs attachments during open, which can
        # load payloads. Delay them and read only filename property streams.
        msg = opener(str(self.path), delayAttachments=True)
        try:
            body = _as_text(_safe_attr(msg, "body", ""))
            header = _header_obj(msg)
            header_values = lambda key: [str(value) for value in header.get_all(key, [])] if header else []
            message_id = normalize_message_id(_as_text(_safe_attr(msg, "messageId")))
            if not message_id:
                message_id = normalize_message_id(" ".join(header_values("Message-ID")))
            in_reply_to = normalize_message_id(_as_text(_safe_attr(msg, "inReplyTo")))
            if not in_reply_to:
                in_reply_to = normalize_message_id(" ".join(header_values("In-Reply-To")))
            references = parse_message_ids(header_values("References"))
            names: list[str] = []
            list_dirs = getattr(msg, "listDir", None)
            get_string = getattr(msg, "getStringStream", None)
            if not callable(list_dirs) or not callable(get_string):
                raise ImportFormatError("MSG parser lacks the required filename-only metadata API.")
            dirs = {entry[0] for entry in list_dirs(False, True, False)
                    if entry and entry[0].startswith("__attach")}
            for directory in sorted(dirs):
                name = ""
                for prop in ("__substg1.0_3707", "__substg1.0_3704"):
                    value = get_string([directory, prop])
                    if value:
                        name = _as_text(value).strip("\0").strip()
                        break
                if name and name not in names:
                    names.append(name)
            current, quoted = split_authored_text(body)
            thread_id = f"message-thread:{references[0]}" if references else (
                f"message-thread:{in_reply_to}" if in_reply_to else ""
            )
            # Do not hash the whole MSG container: it may include attachment
            # payloads. Fall back to the local file path when no message ID exists.
            identity = (
                f"message-id:{message_id}"
                if message_id
                else f"file:{self.path.resolve().as_posix()}"
            )
            recipients = _addresses([_as_text(_safe_attr(msg, "to")), _as_text(_safe_attr(msg, "cc"))])
            timestamp = _date_text(_safe_attr(msg, "date"))
            yield EmailRecord(
                source_id=_stable_source_id("msg", identity),
                source_name=self.source_name,
                project_or_list="",
                message_id=message_id,
                in_reply_to=in_reply_to,
                references=references,
                thread_id=thread_id,
                subject=_as_text(_safe_attr(msg, "subject")),
                sender=_as_text(_safe_attr(msg, "sender")),
                recipients=recipients,
                timestamp=timestamp,
                body_raw=body,
                current_message=current,
                quoted_history=quoted,
                attachment_names=tuple(names),
                provenance={"adapter": "extract-msg", "file_name": self.path.name},
                labels=(),
                annotation_method="UNANNOTATED",
            )
        finally:
            close = _safe_attr(msg, "close")
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def _com_text(item: Any, *names: str) -> str:
    for name in names:
        value = _safe_attr(item, name)
        text = _as_text(value)
        if text:
            return text
    return ""


_OUTLOOK_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
_OUTLOOK_IN_REPLY_TO_ID = "http://schemas.microsoft.com/mapi/proptag/0x1042001F"
_OUTLOOK_INTERNET_REFERENCES = "http://schemas.microsoft.com/mapi/proptag/0x1039001F"


def _outlook_property_text(item: Any, schema_name: str, *fallback_names: str) -> str:
    """Read an unexposed MAPI string property, then try object-model aliases."""
    try:
        accessor = _safe_attr(item, "PropertyAccessor")
        getter = _safe_attr(accessor, "GetProperty")
        if callable(getter):
            value = getter(schema_name)
            text = _as_text(value)
            if text:
                return text
    except Exception:
        # Some messages do not carry the property or Outlook may deny access.
        pass
    return _com_text(item, *fallback_names)


class OutlookAdapter:
    """Read the classic Outlook Inbox through COM. Never changes mailbox items."""

    def __init__(
        self,
        *,
        application_factory: Callable[[], Any] | None = None,
        source_name: str = "outlook",
        limit: int = 200,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError("Outlook import limit must be an integer from 1 to 5000.")
        self.application_factory = application_factory
        self.source_name = source_name
        self.limit = limit

    def iter_records(self) -> Iterator[EmailRecord]:
        factory = self.application_factory
        if factory is None:
            try:
                from win32com.client import Dispatch
            except ImportError as exc:
                raise RuntimeError("Classic Outlook import needs pywin32 on Windows.") from exc
            factory = lambda: Dispatch("Outlook.Application")
        outlook = factory()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)  # Outlook olFolderInbox
        items = inbox.Items
        sorter = _safe_attr(items, "Sort")
        if not callable(sorter):
            raise RuntimeError("Could not sort Outlook Inbox by newest received time.")
        sorter("[ReceivedTime]", True)
        count = min(int(items.Count), self.limit)
        for index in range(1, count + 1):
            item = items.Item(index)
            record = self._record_from_item(item)
            if record is not None:
                yield record

    def _record_from_item(self, item: Any) -> EmailRecord | None:
        class_id = _safe_attr(item, "Class")
        message_class = _com_text(item, "MessageClass")
        is_note = class_id in (None, 43) or message_class.startswith(("IPM.Note", "IPM.Schedule.Meeting"))
        if not is_note:
            return None
        subject = _com_text(item, "Subject")
        body = _com_text(item, "Body")
        sender = _com_text(item, "SenderEmailAddress", "SenderName")
        entry_id = _com_text(item, "EntryID")
        parent = _safe_attr(item, "Parent")
        store_id = _com_text(parent, "StoreID")
        internet_id = normalize_message_id(
            _outlook_property_text(item, _OUTLOOK_INTERNET_MESSAGE_ID, "InternetMessageID")
        )
        conversation_id = _com_text(item, "ConversationID")
        recipients: list[str] = []
        collection = _safe_attr(item, "Recipients")
        if collection is not None:
            try:
                for recipient_index in range(1, int(collection.Count) + 1):
                    recipient = collection.Item(recipient_index)
                    value = _com_text(recipient, "Address", "Name")
                    if value and value not in recipients:
                        recipients.append(value)
            except Exception:
                recipients = []
        if not recipients:
            raw_recipients = _com_text(item, "To", "CC")
            recipients = [part.strip() for part in raw_recipients.split(";") if part.strip()]
        attachment_names: list[str] = []
        attachments = _safe_attr(item, "Attachments")
        if attachments is not None:
            try:
                for attachment_index in range(1, int(attachments.Count) + 1):
                    name = _com_text(attachments.Item(attachment_index), "FileName")
                    if name and name not in attachment_names:
                        attachment_names.append(name)
            except Exception:
                attachment_names = []
        in_reply_to = normalize_message_id(
            _outlook_property_text(item, _OUTLOOK_IN_REPLY_TO_ID, "InReplyTo")
        )
        references = parse_message_ids(
            _outlook_property_text(item, _OUTLOOK_INTERNET_REFERENCES, "InternetReferences")
        )
        current, quoted = split_authored_text(body)
        identity = f"{store_id}\0{entry_id}" if entry_id else "\0".join((internet_id or "", sender, subject, body))
        source_id = _stable_source_id("outlook", identity)
        thread_id = f"outlook-conversation:{hashlib.sha256(conversation_id.encode()).hexdigest()[:24]}" if conversation_id else ""
        received = _safe_attr(item, "ReceivedTime") or _safe_attr(item, "SentOn")
        return EmailRecord(
            source_id=source_id,
            source_name=self.source_name,
            message_id=internet_id,
            in_reply_to=in_reply_to,
            references=references,
            thread_id=thread_id,
            subject=subject,
            sender=sender,
            recipients=tuple(recipients),
            timestamp=_date_text(received),
            body_raw=body,
            current_message=current,
            quoted_history=quoted,
            attachment_names=tuple(attachment_names),
            provenance={"adapter": "outlook_com", "folder": "Inbox"},
            labels=(),
            annotation_method="UNANNOTATED",
        )


def iter_jsonl_records(path: str | Path, *, source_name: str | None = None) -> Iterator[EmailRecord]:
    """Stream normalized JSONL without logging or echoing row content."""
    source_path = Path(path)
    try:
        stream = source_path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise ImportFormatError("Could not open the JSONL source.") from exc
    with stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("row is not an object")
                yield EmailRecord.from_mapping(value, source_name=source_name)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise ImportFormatError(f"Invalid normalized JSONL at line {line_number}: {exc}") from None


def iter_path_records(
    paths: list[str | Path], *, source_name: str | None = None
) -> Iterator[EmailRecord]:
    """Dispatch explicit files or directories by extension in stable order."""
    for raw_path in paths:
        path = Path(raw_path)
        candidates = (
            sorted(
                (item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".eml", ".msg", ".jsonl"}),
                key=lambda item: item.as_posix().casefold(),
            )
            if path.is_dir()
            else [path]
        )
        for candidate in candidates:
            suffix = candidate.suffix.lower()
            if suffix == ".eml":
                yield from EmlAdapter(candidate, source_name=source_name or "eml").iter_records()
            elif suffix == ".msg":
                yield from MsgAdapter(candidate, source_name=source_name or "msg").iter_records()
            elif suffix == ".jsonl":
                yield from iter_jsonl_records(candidate, source_name=source_name)
            else:
                raise ImportFormatError(f"Unsupported source extension: {candidate.suffix or '(none)'}")

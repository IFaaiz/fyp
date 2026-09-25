"""Ingest the CMU CALO Enron maildir into the canonical email JSONL schema."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator

from .cleaning import clean_email_body
from .schemas import empty_record
from .threading import append_thread_context, assign_thread_metadata, normalize_message_id


_MESSAGE_ID_PATTERN = re.compile(r"<([^<>]+)>")


@dataclass(frozen=True)
class ParsedEnronMessage:
    email_id: str
    source_path: str
    message_id: str
    references: tuple[str, ...]
    in_reply_to: tuple[str, ...]
    subject: str
    sender: str
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    sent_at: str | None
    attachment_names: tuple[str, ...]
    raw_body: str
    body_digest: str
    parser_defect_count: int

    def index_row(self) -> dict[str, Any]:
        """Return compact metadata needed for global thread reconstruction."""
        return {
            "email_id": self.email_id,
            "source_path": self.source_path,
            "message_id": self.message_id,
            "references": self.references,
            "in_reply_to": self.in_reply_to,
            "subject": self.subject,
            "sender": self.sender,
            "sent_at": self.sent_at,
            "body_digest": self.body_digest,
        }


@dataclass(frozen=True)
class EnronIndexEntry:
    email_id: str
    source_path: str
    message_id: str
    references: tuple[str, ...]
    in_reply_to: tuple[str, ...]
    subject: str
    sender: str
    sent_at: str | None
    body_digest: str
    parser_defect_count: int
    has_nonempty_body: bool
    has_recipients: bool
    has_cc: bool

    def thread_row(self) -> dict[str, Any]:
        return {
            "email_id": self.email_id,
            "source_path": self.source_path,
            "message_id": self.message_id,
            "references": self.references,
            "in_reply_to": self.in_reply_to,
            "sent_at": self.sent_at,
        }


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "tr", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _decode_part(part: Message) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError, KeyError, AttributeError):
        payload = part.get_payload(decode=True)
        if payload is None:
            raw_payload = part.get_payload()
            return raw_payload if isinstance(raw_payload, str) else ""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    if isinstance(content, bytes):
        return content.decode(part.get_content_charset() or "utf-8", errors="replace")
    return content if isinstance(content, str) else str(content)


def _body_and_attachments(message: Message) -> tuple[str, tuple[str, ...]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachment_names: list[str] = []
    for part in message.walk():
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename:
            cleaned_name = str(filename).strip()
            if cleaned_name and cleaned_name not in attachment_names:
                attachment_names.append(cleaned_name)
        if part.is_multipart() or disposition == "attachment" or filename:
            continue
        if part.get_content_type() == "text/plain":
            plain_parts.append(_decode_part(part))
        elif part.get_content_type() == "text/html":
            html = _decode_part(part)
            extractor = _HTMLTextExtractor()
            extractor.feed(html)
            extractor.close()
            html_parts.append("".join(extractor.parts))
    body_parts = plain_parts if plain_parts else html_parts
    return "\n".join(part for part in body_parts if part), tuple(attachment_names)


def _address_values(header_values: Iterable[str]) -> tuple[str, ...]:
    parsed = getaddresses(list(header_values))
    result: list[str] = []
    for name, address in parsed:
        value = (address or name).strip()
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _header_values(message: Message, name: str) -> list[str]:
    return [str(value) for value in message.get_all(name, [])]


def _custom_address_values(header_values: Iterable[str]) -> tuple[str, ...]:
    values = [value.strip() for value in header_values if value.strip()]
    if any("@" in value or "<" in value or ">" in value for value in values):
        return _address_values(values)
    return tuple(dict.fromkeys(values))


def _extract_message_ids(values: Iterable[str]) -> tuple[str, ...]:
    identifiers: list[str] = []
    for value in values:
        matches = _MESSAGE_ID_PATTERN.findall(value)
        candidates = matches if matches else [value.strip()]
        for candidate in candidates:
            normalized = normalize_message_id(candidate)
            if normalized and normalized not in identifiers:
                identifiers.append(normalized)
    return tuple(identifiers)


def _sent_at(message: Message) -> str | None:
    value = message.get("Date")
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.isoformat()


def parse_enron_bytes(raw_bytes: bytes, *, source_path: str = "<memory>") -> ParsedEnronMessage:
    """Parse one RFC 822 message while retaining its decoded body verbatim."""
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    raw_body, attachments = _body_and_attachments(message)
    parser_defect_count = sum(len(part.defects) for part in message.walk())
    body_digest = hashlib.sha256(raw_body.encode("utf-8", errors="replace")).hexdigest()

    raw_message_id = str(message.get("Message-ID", ""))
    message_id = normalize_message_id(raw_message_id)
    subject = str(message.get("Subject", ""))
    from_values = _address_values(_header_values(message, "From"))
    if not from_values:
        from_values = _custom_address_values(_header_values(message, "X-From"))
    sender = from_values[0] if from_values else ""
    recipients = _address_values(_header_values(message, "To"))
    if not recipients:
        recipients = _custom_address_values(_header_values(message, "X-To"))
    cc = _address_values(_header_values(message, "Cc"))
    if not cc:
        cc = _custom_address_values(_header_values(message, "X-cc"))
    references = _extract_message_ids(_header_values(message, "References"))
    in_reply_to = _extract_message_ids(_header_values(message, "In-Reply-To"))
    sent_at = _sent_at(message)

    if message_id:
        dedupe_material = f"message-id\0{message_id}\0{body_digest}"
    else:
        recipient_key = ",".join(recipients).casefold()
        cc_key = ",".join(cc).casefold()
        fallback = "\0".join((sender.casefold(), recipient_key, cc_key, subject.casefold(), sent_at or "", body_digest))
        dedupe_material = f"fallback\0{fallback}"
    email_id = "enron-" + hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()[:24]
    return ParsedEnronMessage(
        email_id=email_id,
        source_path=source_path,
        message_id=message_id,
        references=references,
        in_reply_to=in_reply_to,
        subject=subject,
        sender=sender,
        recipients=recipients,
        cc=cc,
        sent_at=sent_at,
        attachment_names=attachments,
        raw_body=raw_body,
        body_digest=body_digest,
        parser_defect_count=parser_defect_count,
    )


def parse_enron_file(path: str | Path, *, root: str | Path | None = None) -> ParsedEnronMessage:
    """Read and parse a single maildir message file."""
    source = Path(path)
    try:
        relative = source.relative_to(Path(root)) if root is not None else source.name
    except ValueError:
        relative = source
    try:
        raw_bytes = source.read_bytes()
    except OSError as exc:
        raise OSError(f"could not read Enron message {source}: {exc}") from exc
    return parse_enron_bytes(raw_bytes, source_path=relative.as_posix())


def iter_enron_paths(root: str | Path, *, max_messages: int | None = None) -> Iterator[Path]:
    """Yield maildir files in deterministic order."""
    maildir = Path(root)
    if not maildir.is_dir():
        raise FileNotFoundError(f"Enron maildir does not exist or is not a directory: {maildir}")
    if max_messages is not None and max_messages < 0:
        raise ValueError("max_messages must be nonnegative")
    if max_messages == 0:
        return
    yielded = 0
    for directory, subdirectories, filenames in os.walk(maildir):
        subdirectories.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        for filename in filenames:
            yield Path(directory) / filename
            yielded += 1
            if max_messages is not None and yielded >= max_messages:
                return


def _dedupe_key(message: ParsedEnronMessage) -> tuple[str, str]:
    if message.message_id:
        return ("message-id", message.message_id + "\0" + message.body_digest)
    return ("email-id", message.email_id)


def scan_enron_index(
    root: str | Path, *, max_messages: int | None = None,
) -> tuple[list[EnronIndexEntry], dict[str, Any]]:
    """Parse compact headers and deduplicate repeated source mailbox copies."""
    maildir = Path(root)
    entries: list[EnronIndexEntry] = []
    seen: set[tuple[str, str]] = set()
    input_count = 0
    duplicate_count = 0
    source_file_bytes = 0
    parser_defects = 0
    body_characters = 0
    nonempty_bodies = 0
    messages_with_message_id = 0
    messages_with_subject = 0
    messages_with_sender = 0
    messages_with_sent_at = 0
    messages_with_references = 0
    messages_with_in_reply_to = 0
    messages_with_attachment_names = 0
    messages_with_recipients = 0
    messages_with_cc = 0
    for path in iter_enron_paths(maildir, max_messages=max_messages):
        input_count += 1
        source_file_bytes += path.stat().st_size
        message = parse_enron_file(path, root=maildir)
        parser_defects += message.parser_defect_count
        body_characters += len(message.raw_body)
        nonempty_bodies += bool(message.raw_body.strip())
        messages_with_message_id += bool(message.message_id)
        messages_with_subject += bool(message.subject.strip())
        messages_with_sender += bool(message.sender)
        messages_with_sent_at += message.sent_at is not None
        messages_with_references += bool(message.references)
        messages_with_in_reply_to += bool(message.in_reply_to)
        messages_with_attachment_names += bool(message.attachment_names)
        messages_with_recipients += bool(message.recipients)
        messages_with_cc += bool(message.cc)
        key = _dedupe_key(message)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        entries.append(EnronIndexEntry(
            email_id=message.email_id,
            source_path=message.source_path,
            message_id=message.message_id,
            references=message.references,
            in_reply_to=message.in_reply_to,
            subject=message.subject,
            sender=message.sender,
            sent_at=message.sent_at,
            body_digest=message.body_digest,
            parser_defect_count=message.parser_defect_count,
            has_nonempty_body=bool(message.raw_body.strip()),
            has_recipients=bool(message.recipients),
            has_cc=bool(message.cc),
        ))
    return entries, {
        "source_files": input_count,
        "source_file_bytes": source_file_bytes,
        "duplicate_messages_removed": duplicate_count,
        "parser_defects": parser_defects,
        "source_body_characters": body_characters,
        "source_messages_with_nonempty_body": nonempty_bodies,
        "source_empty_body_messages": input_count - nonempty_bodies,
        "source_messages_with_message_id": messages_with_message_id,
        "source_messages_with_subject": messages_with_subject,
        "source_messages_with_sender": messages_with_sender,
        "source_messages_with_sent_at": messages_with_sent_at,
        "source_messages_with_references": messages_with_references,
        "source_messages_with_in_reply_to": messages_with_in_reply_to,
        "source_messages_with_attachment_names": messages_with_attachment_names,
        "source_messages_with_recipients": messages_with_recipients,
        "source_messages_with_cc": messages_with_cc,
    }


def _record_from_message(
    message: ParsedEnronMessage,
    *,
    thread_id: str,
    turn_index: int,
    thread_context: str,
) -> dict[str, Any]:
    clean_body, current_message = clean_email_body(message.raw_body)
    record = empty_record(
        email_id=message.email_id,
        source_dataset="enron",
        thread_id=thread_id,
        turn_index=turn_index,
        subject=message.subject,
        raw_body=message.raw_body,
    )
    record.update({
        "current_message": current_message,
        "clean_body": clean_body,
        "thread_context": thread_context,
        "sender": message.sender,
        "recipients": list(message.recipients),
        "cc": list(message.cc),
        "sent_at": message.sent_at,
        "attachment_names": list(message.attachment_names),
        "labels": [],
        "spans": [],
        "annotation": {
            "status": "unlabelled",
            "annotator": None,
            "annotation_source": None,
            "confidence": None,
        },
    })
    return record


def prepare_enron_jsonl(
    maildir: str | Path,
    output: str | Path,
    *,
    max_messages: int | None = None,
    context_limit_chars: int = 6000,
) -> dict[str, int]:
    """Write canonical, unlabelled Enron records from a local maildir.

    The source archive is read only. The first pass keeps compact metadata for
    cross-file threading; the second pass reads bodies in thread/time order and
    writes one JSONL record at a time.
    """
    maildir = Path(maildir)
    entries, stats = scan_enron_index(maildir, max_messages=max_messages)
    thread_map = assign_thread_metadata(entry.thread_row() for entry in entries)
    known_message_ids = {entry.message_id for entry in entries if entry.message_id}
    reference_tokens = sum(len(entry.references) for entry in entries)
    in_reply_to_tokens = sum(len(entry.in_reply_to) for entry in entries)
    unique_messages_with_resolved_reference = sum(
        any(reference in known_message_ids and reference != entry.message_id for reference in entry.references)
        for entry in entries
    )
    unique_messages_with_resolved_in_reply_to = sum(
        any(reference in known_message_ids and reference != entry.message_id for reference in entry.in_reply_to)
        for entry in entries
    )
    ordered_entries = sorted(
        entries,
        key=lambda entry: (
            thread_map[entry.email_id][0],
            thread_map[entry.email_id][1],
            entry.source_path.casefold(),
        ),
    )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    current_thread = ""
    context = ""
    threads: set[str] = set()
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for entry in ordered_entries:
            thread_id, turn_index = thread_map[entry.email_id]
            if thread_id != current_thread:
                current_thread = thread_id
                context = ""
            message = parse_enron_file(maildir / Path(entry.source_path), root=maildir)
            if message.email_id != entry.email_id:
                raise ValueError(f"source changed during preparation: {entry.source_path}")
            record = _record_from_message(
                message,
                thread_id=thread_id,
                turn_index=turn_index,
                thread_context=context,
            )
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            threads.add(thread_id)
            context = append_thread_context(
                context,
                sender=record["sender"],
                sent_at=record["sent_at"],
                subject=record["subject"],
                current_message=record["current_message"],
                max_chars=context_limit_chars,
            )
    thread_sizes = Counter(thread_map[entry.email_id][0] for entry in entries)
    thread_size_buckets = {
        "1": sum(size == 1 for size in thread_sizes.values()),
        "2": sum(size == 2 for size in thread_sizes.values()),
        "3-5": sum(3 <= size <= 5 for size in thread_sizes.values()),
        "6-10": sum(6 <= size <= 10 for size in thread_sizes.values()),
        "11-50": sum(11 <= size <= 50 for size in thread_sizes.values()),
        ">50": sum(size > 50 for size in thread_sizes.values()),
    }
    messages_with_explicit_links = sum(
        bool(entry.references or entry.in_reply_to) for entry in entries
    )
    messages_with_resolvable_links = sum(
        any(
            reference in known_message_ids and reference != entry.message_id
            for reference in (*entry.references, *entry.in_reply_to)
        )
        for entry in entries
    )
    messages_with_external_only_links = sum(
        bool(entry.references or entry.in_reply_to)
        and not any(
            reference in known_message_ids and reference != entry.message_id
            for reference in (*entry.references, *entry.in_reply_to)
        )
        for entry in entries
    )
    stats.update({
        "messages_written": len(ordered_entries),
        "threads": len(threads),
        "single_message_threads": sum(size == 1 for size in thread_sizes.values()),
        "multi_message_threads": sum(size > 1 for size in thread_sizes.values()),
        "messages_in_multi_message_threads": sum(size for size in thread_sizes.values() if size > 1),
        "messages_in_multi_message_threads_with_explicit_links": sum(
            bool(entry.references or entry.in_reply_to)
            for entry in entries
            if thread_sizes[thread_map[entry.email_id][0]] > 1
        ),
        "messages_in_multi_message_threads_without_explicit_links": sum(
            not (entry.references or entry.in_reply_to)
            for entry in entries
            if thread_sizes[thread_map[entry.email_id][0]] > 1
        ),
        "largest_thread_size": max(thread_sizes.values(), default=0),
        "thread_size_buckets": thread_size_buckets,
        "messages_with_explicit_links": messages_with_explicit_links,
        "messages_with_resolvable_links": messages_with_resolvable_links,
        "messages_with_external_only_links": messages_with_external_only_links,
        "reference_tokens": reference_tokens,
        "reference_tokens_resolvable_in_corpus": sum(
            reference in known_message_ids and reference != entry.message_id
            for entry in entries
            for reference in entry.references
        ),
        "in_reply_to_tokens": in_reply_to_tokens,
        "in_reply_to_tokens_resolvable_in_corpus": sum(
            reference in known_message_ids and reference != entry.message_id
            for entry in entries
            for reference in entry.in_reply_to
        ),
        "unique_messages_with_resolved_reference": unique_messages_with_resolved_reference,
        "unique_messages_with_resolved_in_reply_to": unique_messages_with_resolved_in_reply_to,
        "unique_messages_with_references": sum(bool(entry.references) for entry in entries),
        "unique_messages_with_in_reply_to": sum(bool(entry.in_reply_to) for entry in entries),
        "unique_messages_with_message_id": sum(bool(entry.message_id) for entry in entries),
        "unique_messages_with_subject": sum(bool(entry.subject.strip()) for entry in entries),
        "unique_messages_with_sender": sum(bool(entry.sender) for entry in entries),
        "unique_messages_with_sent_at": sum(entry.sent_at is not None for entry in entries),
        "unique_parser_defects": sum(entry.parser_defect_count for entry in entries),
        "unique_empty_body_messages": sum(not entry.has_nonempty_body for entry in entries),
        "unique_messages_with_recipients": sum(entry.has_recipients for entry in entries),
        "unique_messages_with_cc": sum(entry.has_cc for entry in entries),
    })
    return stats

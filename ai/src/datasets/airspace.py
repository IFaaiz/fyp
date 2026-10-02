"""Deterministic parser for the official CMU Airspace wargaming release.

This adapter preserves the source taxonomy and does not emit FYP labels. The
corpus is highly fabricated and is suitable only as auxiliary supervision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections import Counter, defaultdict, deque
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


DATASET = "airspace"
SOURCE_FAMILY = "AIRSPACE"
VERSION = "1.0"
OFFICIAL_PAGE = "https://www.cs.cmu.edu/~airspace/"
ARCHIVE_URL = "https://www.cs.cmu.edu/~airspace/corpus/Airspace_wargaming_1.0.zip"
SYNTAX_URL = "https://www.cs.cmu.edu/~airspace/corpus/README_EmailSyntax_1.0.pdf"
METHODOLOGY_URL = "https://reports-archive.adm.cs.cmu.edu/anon/2006/abstracts/06-125.html"

EXPECTED_LABELS = frozenset({
    "BRIEFING", "CHANGE-ROOM", "CHANGE-SESSION", "CHANGE-SPEAKER",
    "INFO-REQ", "MISC-ACTION", "WEB-VIO", "WEB-WBE",
})


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    """Validate a ZIP path before any filesystem operation."""
    if not name or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    if any(":" in part or part.endswith((".", " ")) for part in path.parts):
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{i}" for prefix in ("com", "lpt") for i in range(1,10)}
    if any(part.split(".")[0].casefold() in reserved for part in path.parts):
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    return path


def safe_extract_archive(
    archive_path: str | Path,
    destination: str | Path,
    *,
    max_members: int = 5000,
    max_member_bytes: int = 16 * 1024 * 1024,
    max_total_bytes: int = 128 * 1024 * 1024,
) -> Path:
    """Extract into a new directory after validating every member.

    Existing extraction directories are accepted only when every file matches
    the corresponding archive member. No existing path is overwritten.
    """
    archive_path = Path(archive_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target_root = destination.resolve()

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError(f"archive has too many members: {len(members)}")
        total_size = 0
        checked: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for info in members:
            member_path = _safe_member_path(info.filename.rstrip("/")) if info.filename.rstrip("/") else None
            if member_path is None:
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"symbolic link ZIP member is not allowed: {info.filename!r}")
            if info.file_size > max_member_bytes:
                raise ValueError(f"ZIP member exceeds size limit: {info.filename!r}")
            total_size += info.file_size
            if total_size > max_total_bytes:
                raise ValueError("archive expands beyond configured size limit")
            candidate = (target_root / Path(*member_path.parts)).resolve()
            if candidate != target_root and target_root not in candidate.parents:
                raise ValueError(f"ZIP member escapes extraction directory: {info.filename!r}")
            checked.append((info, member_path))

        if destination.exists():
            for info, member_path in checked:
                target = destination.joinpath(*member_path.parts)
                if info.is_dir():
                    if not target.is_dir():
                        raise FileExistsError(f"existing extraction differs from archive: {target}")
                    continue
                if not target.is_file() or target.stat().st_size != info.file_size:
                    raise FileExistsError(f"existing extraction differs from archive: {target}")
                with archive.open(info) as source, target.open("rb") as extracted:
                    if source.read() != extracted.read():
                        raise FileExistsError(f"existing extraction differs from archive: {target}")
            return destination

        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            for info, member_path in checked:
                target = staging.joinpath(*member_path.parts)
                target_resolved = target.resolve()
                if target_resolved != staging.resolve() and staging.resolve() not in target_resolved.parents:
                    raise ValueError(f"ZIP member escapes staging directory: {info.filename!r}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return destination


def _header_values(message: Message, header: str) -> list[str]:
    return [str(value).strip() for value in message.get_all(header, [])]


def _single_header(message: Message, header: str) -> str | None:
    values = _header_values(message, header)
    nonempty = [value for value in values if value]
    if not nonempty:
        return None
    if len(nonempty) > 1 and len(set(nonempty)) > 1:
        # Keep the first value deterministic and preserve all values elsewhere.
        return nonempty[0]
    return nonempty[0]


def _decode_body(message: Message) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() != "text/plain":
                continue
            content = part.get_content()
            if isinstance(content, bytes):
                charset = part.get_content_charset() or "utf-8"
                content = content.decode(charset, errors="replace")
            if isinstance(content, str):
                parts.append(content)
    else:
        content = message.get_content()
        if isinstance(content, bytes):
            charset = message.get_content_charset() or "utf-8"
            content = content.decode(charset, errors="replace")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _bool_header(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _message_id(message: Message, member: str) -> tuple[str, str | None]:
    source_id = _single_header(message, "X-RADAR-Messageid")
    message_id = str(message.get("Message-Id") or "").strip() or None
    if source_id is None and message_id:
        match = re.search(r"\.injector\.(\d+)(?:@|>)", message_id, flags=re.IGNORECASE)
        if match:
            source_id = match.group(1)
    if source_id is None:
        source_id = Path(member).stem
    return source_id, message_id


def parse_eml(
    content: bytes,
    *,
    archive_member: str,
    archive_sha256: str,
    acquired_at: str | None = None,
) -> dict[str, Any]:
    """Parse one source message without mapping source categories to FYP labels."""
    message = BytesParser(policy=policy.default).parsebytes(content)
    subject = str(message.get("Subject") or "")
    body = _decode_body(message)
    source_message_id, rfc_message_id = _message_id(message, archive_member)

    raw_labels = _header_values(message, "X-RADAR-Label")
    source_labels = [label for label in raw_labels if label]
    noise_header = _single_header(message, "X-RADAR-Noise")
    reply_header = _single_header(message, "X-RADAR-Replyto")
    source_thread_header = _single_header(message, "X-RADAR-Thread")
    if reply_header is None:
        reply_to_message_id = None
        reply_status = "unknown"
    elif reply_header == "0":
        reply_to_message_id = None
        reply_status = "no_parent"
    else:
        reply_to_message_id = reply_header
        reply_status = "unresolved"

    source_text_prefix = f"Subject: {subject}\n\n" if subject else ""
    source_text = source_text_prefix + body
    subject_offset = (
        {"start": len("Subject: "), "end": len("Subject: ") + len(subject)}
        if subject else None
    )
    body_offset = {"start": len(source_text_prefix), "end": len(source_text)}
    labels_state = "present" if source_labels else "no_label"

    return {
        "dataset": DATASET,
        "source_dataset": DATASET,
        "source_family": SOURCE_FAMILY,
        "source_id": f"airspace:{source_message_id}",
        "email_id": f"airspace:{source_message_id}",
        "source_message_id": source_message_id,
        "rfc_message_id": rfc_message_id,
        "source_thread_id": source_thread_header,
        "thread_id": None,
        "thread_id_source": (
            "unknown" if source_thread_header is None
            else "source_thread_field_unverified_as_reply_thread"
        ),
        "reply_to_message_id": reply_to_message_id,
        "reply_to_message_id_raw": reply_header,
        "reply_to_status": reply_status,
        "subject": subject,
        "body": body,
        "raw_body": body,
        "current_message": body,
        "source_text": source_text,
        "source_text_offsets": {
            "coordinate_system": "unicode_character_offsets_in_source_text",
            "subject": subject_offset,
            "body": body_offset,
        },
        "source_labels": source_labels,
        "original_labels": source_labels,
        "source_label_status": labels_state,
        "noise": _bool_header(noise_header),
        "noise_raw": noise_header,
        "source_annotations": {
            "labels": source_labels,
            "label_status": labels_state,
            "noise": _bool_header(noise_header),
            "noise_raw": noise_header,
        },
        "sender": str(message.get("From") or ""),
        "recipients": [str(message.get("To") or "")] if message.get("To") else [],
        "cc": [str(message.get("Cc") or "")] if message.get("Cc") else [],
        "sent_at_raw": str(message.get("X-RADAR-Time") or message.get("Date") or "") or None,
        "source_provenance": {
            "official_page": OFFICIAL_PAGE,
            "archive_url": ARCHIVE_URL,
            "archive_sha256": archive_sha256,
            "archive_member": archive_member,
            "version": VERSION,
            "acquired_at_utc": acquired_at,
            "terms_url": OFFICIAL_PAGE,
            "redistribution_permitted": False,
        },
    }


def assign_reply_threads(records: list[dict[str, Any]]) -> None:
    """Resolve Replyto links; never treat X-RADAR-Thread grouping as a reply."""
    id_map: dict[str, dict[str, Any]] = {}
    for row in records:
        key = row["source_message_id"]
        if key in id_map:
            raise ValueError(f"duplicate Airspace source message ID: {key}")
        id_map[key] = row

    graph: dict[str, set[str]] = defaultdict(set)
    for row in records:
        target_id = row.get("reply_to_message_id")
        if target_id is None:
            continue
        target = id_map.get(str(target_id))
        row["reply_to_status"] = "linked" if target else "dangling"
        row["source_annotations"]["reply_to_status"] = row["reply_to_status"]
        if target:
            child_id = row["source_message_id"]
            graph[child_id].add(str(target_id))
            graph[str(target_id)].add(child_id)

    visited: set[str] = set()
    for start in sorted(graph):
        if start in visited:
            continue
        component: list[str] = []
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(graph[current]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        thread_id = f"airspace-reply-component:{min(component, key=_numeric_id_key)}"
        for source_id in component:
            row = id_map[source_id]
            if row.get("source_thread_id"):
                row["thread_id"] = f"airspace-source-thread:{row['source_thread_id']}"
                row["thread_id_source"] = "X-RADAR-Thread"
            else:
                row["thread_id"] = thread_id
                row["thread_id_source"] = "derived_from_replyto_component"

def _numeric_id_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except ValueError:
        return 2**63 - 1, value


def parse_archive(
    archive_path: str | Path,
    *,
    extract_to: str | Path | None = None,
    acquired_at: str | None = None,
) -> list[dict[str, Any]]:
    """Read every .eml from the archive, validating all member paths first."""
    archive_path = Path(archive_path)
    archive_hash = sha256_file(archive_path)
    if extract_to is not None:
        extracted = safe_extract_archive(archive_path, extract_to)
        message_paths = sorted(extracted.rglob("*.eml"), key=lambda path: path.as_posix())
        records = [
            parse_eml(
                path.read_bytes(),
                archive_member=path.relative_to(extracted).as_posix(),
                archive_sha256=archive_hash,
                acquired_at=acquired_at,
            )
            for path in message_paths
        ]
    else:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            for info in infos:
                if info.filename.rstrip("/"):
                    _safe_member_path(info.filename.rstrip("/"))
            message_infos = sorted(
                (info for info in infos if info.filename.lower().endswith(".eml")),
                key=lambda info: info.filename,
            )
            records = [
                parse_eml(
                    archive.read(info),
                    archive_member=info.filename,
                    archive_sha256=archive_hash,
                    acquired_at=acquired_at,
                )
                for info in message_infos
            ]
    assign_reply_threads(records)
    return records


def summarize_records(records: Iterable[dict[str, Any]], *, expected_archive_sha256: str | None = None) -> dict[str, Any]:
    rows = list(records)
    label_counts: Counter[str] = Counter()
    noise_counts: Counter[str] = Counter()
    reply_counts: Counter[str] = Counter()
    label_multiplicity: Counter[str] = Counter()
    source_thread_values: Counter[str] = Counter()
    reply_component_sizes: Counter[str] = Counter()
    for row in rows:
        labels = row.get("source_labels") or []
        label_counts.update(labels)
        label_multiplicity[str(len(labels))] += 1
        noise_counts["true" if row.get("noise") is True else "false" if row.get("noise") is False else "unknown"] += 1
        reply_counts[str(row.get("reply_to_status") or "unknown")] += 1
        if row.get("source_thread_id") is not None:
            source_thread_values[str(row["source_thread_id"])] += 1
        if row.get("thread_id"):
            if row.get("thread_id_source") == "derived_from_replyto_component":
                reply_component_sizes[str(row["thread_id"])] += 1
    unknown_labels = sorted(set(label_counts) - EXPECTED_LABELS)
    return {
        "dataset": DATASET,
        "source_family": SOURCE_FAMILY,
        "version": VERSION,
        "source_url": OFFICIAL_PAGE,
        "archive_url": ARCHIVE_URL,
        "archive_sha256": expected_archive_sha256 or (rows[0]["source_provenance"]["archive_sha256"] if rows else None),
        "message_count": len(rows),
        "unique_source_message_ids": len({row["source_message_id"] for row in rows}),
        "label_counts": dict(sorted(label_counts.items())),
        "messages_with_labels": sum(bool(row.get("source_labels")) for row in rows),
        "messages_without_labels": sum(not row.get("source_labels") for row in rows),
        "messages_with_multiple_labels": sum(len(row.get("source_labels") or []) > 1 for row in rows),
        "label_multiplicity_counts": dict(sorted(label_multiplicity.items(), key=lambda item: int(item[0]))),
        "unknown_source_labels": unknown_labels,
        "noise_counts": dict(sorted(noise_counts.items())),
        "reply_status_counts": dict(sorted(reply_counts.items())),
        "explicit_no_parent_count": sum(row.get("reply_to_message_id_raw") == "0" for row in rows),
        "reply_edge_count": sum(row.get("reply_to_status") == "linked" for row in rows),
        "source_thread_field_messages": sum(bool(row.get("source_thread_id")) for row in rows),
        "reply_threaded_messages": sum(row.get("thread_id_source") == "derived_from_replyto_component" for row in rows),
        "derived_reply_component_count": len(reply_component_sizes),
        "reply_thread_size_histogram": dict(sorted(Counter(map(str, reply_component_sizes.values())).items(), key=lambda item: int(item[0]))),
        "source_thread_group_count": len(source_thread_values),
        "source_thread_zero_group_messages": source_thread_values.get("0", 0),
        "source_thread_nonzero_group_messages": sum(count for value, count in source_thread_values.items() if value != "0"),
        "source_thread_group_size_histogram": dict(sorted(Counter(map(str, source_thread_values.values())).items(), key=lambda item: int(item[0]))),
        "subject_missing": sum(not row.get("subject") for row in rows),
        "body_missing": sum(not row.get("body") for row in rows),
        "evidence_offsets_available": sum(bool(row.get("source_text_offsets")) for row in rows),
        "source_labels_preserved_without_fyp_mapping": True,
        "fyp_labels_emitted": False,
        "redistribution_permitted": False,
        "fabricated_content_share_stated_by_cmu": ">90%",
    }


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count

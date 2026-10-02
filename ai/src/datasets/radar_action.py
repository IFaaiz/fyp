"""Acquire and parse the CMU RADAR Action-Item email corpus.

The published offsets are character offsets into each complete message file.
This module therefore reads each file as bytes, decodes UTF-8 without newline
translation, and retains the original full-file text as ``text``. Parsed
subject/body fields are convenience fields and never change span coordinates.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Any, Iterable
from urllib.request import Request, urlopen


DEFAULT_AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ROOT = DEFAULT_AI_ROOT / "data" / "raw" / "radar_action"
DEFAULT_ARCHIVE = DEFAULT_RAW_ROOT / "action-item-dataset.tgz"
DEFAULT_DOC = DEFAULT_RAW_ROOT / "action-item-dataset.html"
DEFAULT_EXTRACTED_ROOT = DEFAULT_RAW_ROOT / "extracted"
DEFAULT_MESSAGE_ROOT = DEFAULT_EXTRACTED_ROOT / "distribute" / "handStripped"
DEFAULT_OUTPUT = DEFAULT_AI_ROOT / "data" / "processed" / "radar_action.jsonl"
DEFAULT_REVIEW_OUTPUT = DEFAULT_AI_ROOT / "data" / "processed" / "radar_action_review_50.jsonl"
DEFAULT_STATS = DEFAULT_AI_ROOT / "reports" / "radar_action_statistics.json"
DEFAULT_ACQUISITION_MANIFEST = DEFAULT_RAW_ROOT / "acquisition.json"

OFFICIAL_PAGE_URL = "https://www.cs.cmu.edu/~pbennett/action-item-dataset.html"
OFFICIAL_ARCHIVE_URL = "http://www.cs.cmu.edu/~pbennett/action-item-dataset.tgz"
ARCHIVE_SHA256 = "1cee24880166b982ea25feaae0a0b23a04b7edf4de7b6c8ca098c390c5667e43"

_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*)$")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> str:
    """Download one official file atomically and return its final URL."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = Request(url, headers={"User-Agent": "FYP-RADAR-Acquisition/1.0"})
    try:
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            final_url = response.geturl()
        temporary.replace(destination)
        return final_url
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe archive member path: {name!r}")
    if "\\" in name or "\x00" in name or any(":" in part or part.endswith((".", " ")) for part in path.parts):
        raise ValueError(f"unsafe archive member path: {name!r}")
    reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{i}" for prefix in ("com", "lpt") for i in range(1,10)}
    if any(part.split(".")[0].casefold() in reserved for part in path.parts):
        raise ValueError(f"unsafe archive member path: {name!r}")
    return path


def safe_extract_archive(archive_path: str | Path, destination: str | Path) -> int:
    """Extract regular files/directories only, refusing path escapes and links.

    Existing files are accepted only when their bytes match the archive. This
    makes repeated extraction idempotent while preventing silent replacement.
    """
    archive_path = Path(archive_path)
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members=archive.getmembers()
        if len(members)>5000 or sum(m.size for m in members)>128*1024*1024:
            raise ValueError('archive exceeds bounded extraction limits')
        checked=[];kinds={}
        for member in members:
            relative = _safe_member_path(member.name)
            target = (destination / Path(*relative.parts)).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"archive member escapes extraction root: {member.name!r}")
            if not member.isfile() and not member.isdir():
                raise ValueError(f"unsupported archive member type: {member.name!r}")
            if member.size>16*1024*1024:
                raise ValueError('archive member exceeds bounded extraction limits')
            key=relative.as_posix().casefold()
            if key in kinds:
                raise ValueError(f"duplicate archive file path: {member.name!r}")
            kinds[key]='file' if member.isfile() else 'directory'
            checked.append((member,relative))
        for _,relative in checked:
            if any(kinds.get(p.as_posix().casefold())=='file' for p in relative.parents):
                raise ValueError('archive file/directory path conflict')
        extracted_files=sum(m.isfile() for m,_ in checked)
        if destination.exists():
            for member,relative in checked:
                target=destination.joinpath(*relative.parts)
                if member.isdir():
                    if not target.is_dir():raise FileExistsError(f'existing extraction differs: {target}')
                else:
                    source=archive.extractfile(member)
                    if not target.is_file() or target.read_bytes()!=source.read():
                        raise FileExistsError(f'existing extracted file differs: {target}')
            return extracted_files
        staging=Path(tempfile.mkdtemp(prefix=f'.{destination.name}-',dir=destination.parent))
        try:
            for member,relative in checked:
                target=staging.joinpath(*relative.parts)
                if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
                target.parent.mkdir(parents=True,exist_ok=True)
                source=archive.extractfile(member)
                if source is None:raise ValueError(f'could not read archive member: {member.name!r}')
                with target.open('xb') as output:shutil.copyfileobj(source,output)
            os.replace(staging,destination)
        except Exception:
            shutil.rmtree(staging,ignore_errors=True)
            raise
    return extracted_files


def acquire_radar_action(
    *,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    archive_path: str | Path | None = None,
    doc_path: str | Path | None = None,
    extracted_root: str | Path | None = None,
) -> dict[str, Any]:
    """Acquire/pin the official release and safely extract it locally."""
    raw_root = Path(raw_root)
    archive_path = Path(archive_path) if archive_path else raw_root / DEFAULT_ARCHIVE.name
    doc_path = Path(doc_path) if doc_path else raw_root / DEFAULT_DOC.name
    extracted_root = Path(extracted_root) if extracted_root else raw_root / "extracted"
    manifest_path = raw_root / "acquisition.json"
    raw_root.mkdir(parents=True, exist_ok=True)

    prior: dict[str, Any] = {}
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))

    resolved_archive_url = prior.get("resolved_archive_url", OFFICIAL_ARCHIVE_URL)
    archive_downloaded = False
    if not archive_path.exists():
        resolved_archive_url = _download(OFFICIAL_ARCHIVE_URL, archive_path)
        archive_downloaded = True
    archive_hash = sha256_file(archive_path)
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError(
            f"archive SHA-256 mismatch: expected pinned {ARCHIVE_SHA256}, got {archive_hash}; "
            "preserve the file and review the upstream release before updating the pin"
        )

    resolved_doc_url = prior.get("resolved_doc_url", OFFICIAL_PAGE_URL)
    doc_downloaded = False
    if not doc_path.exists():
        resolved_doc_url = _download(OFFICIAL_PAGE_URL, doc_path)
        doc_downloaded = True
    doc_hash = sha256_file(doc_path)

    extracted_file_count = safe_extract_archive(archive_path, extracted_root)
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {
        "dataset": "RADAR_ACTION",
        "source_page_url": OFFICIAL_PAGE_URL,
        "archive_url": OFFICIAL_ARCHIVE_URL,
        "resolved_archive_url": resolved_archive_url,
        "documentation_file": doc_path.name,
        "resolved_doc_url": resolved_doc_url,
        "archive_file": archive_path.name,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": archive_hash,
        "documentation_sha256": doc_hash,
        "retrieved_at_utc": prior.get("retrieved_at_utc", now_utc),
        "retrieval_date_utc": prior.get("retrieval_date_utc", now_utc[:10]),
        "archive_downloaded_by_this_run": archive_downloaded,
        "documentation_downloaded_by_this_run": doc_downloaded,
        "extracted_root": str(extracted_root),
        "extracted_file_count": extracted_file_count,
        "version_note": "CMU page provides no numbered version or publication checksum; pinned by local SHA-256.",
        "usage_note": "Official page says distribution was exempt from further IRB review for research purposes; no explicit open license or general redistribution permission was found.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _decode_source_file(path: Path) -> str:
    """Decode without universal-newline conversion so offsets remain stable."""
    return path.read_bytes().decode("utf-8", errors="strict")


def _portable_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(DEFAULT_AI_ROOT.parent.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _subject_and_body(text: str) -> tuple[str, str]:
    separator = re.search(r"\r\n\r\n|\n\n|\r\r", text)
    if separator is None:
        header_text, body = text, ""
    else:
        header_text = text[:separator.start()]
        body = text[separator.end():]
    subject = ""
    for raw_line in header_text.splitlines():
        line = raw_line.rstrip("\r\n")
        match = _HEADER_RE.match(line)
        if match and match.group(1).casefold() == "subject":
            subject = match.group(2).strip()
    return subject, body


def _span(text: str, start: int, length: int, *, kind: str, source_type: str | None = None) -> dict[str, Any]:
    if start < 0 or length < 0 or start + length > len(text):
        raise ValueError(f"span outside source text: start={start}, length={length}, text_chars={len(text)}")
    end = start + length
    return {
        "kind": kind,
        "source_type": source_type,
        "start": start,
        "length": length,
        "end": end,
        "text": text[start:end],
        "offset_basis": "text",
    }


def _read_judgments(path: Path) -> dict[str, tuple[str, list[tuple[int, int]]]]:
    judgments: dict[str, tuple[str, list[tuple[int, int]]]] = {}
    for line_number, raw_line in enumerate(_decode_source_file(path).splitlines(), 1):
        if not raw_line.strip():
            continue
        fields = raw_line.split()
        if len(fields) < 2:
            raise ValueError(f"{path}:{line_number}: expected filename and Y/N label")
        filename, label = fields[:2]
        if Path(filename).name != filename:
            raise ValueError(f"{path}:{line_number}: unsafe message filename {filename!r}")
        if label not in {"Y", "N"}:
            raise ValueError(f"{path}:{line_number}: unexpected presence label {label!r}")
        coordinates = fields[2:]
        if label == "N" and coordinates:
            raise ValueError(f"{path}:{line_number}: negative judgment unexpectedly has offsets")
        if label == "Y" and (not coordinates or len(coordinates) % 2):
            raise ValueError(f"{path}:{line_number}: positive judgment has malformed span pairs")
        pairs = [(int(coordinates[index]), int(coordinates[index + 1])) for index in range(0, len(coordinates), 2)]
        if filename in judgments:
            raise ValueError(f"{path}:{line_number}: duplicate judgment for {filename}")
        judgments[filename] = (label, pairs)
    return judgments


def _read_annotation_map(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line_number, raw_line in enumerate(_decode_source_file(path).splitlines(), 1):
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        if len(fields) != 2:
            raise ValueError(f"{path}:{line_number}: expected message and annotation filenames")
        message_name, annotation_name = fields
        if Path(message_name).name != message_name or Path(annotation_name).name != annotation_name:
            raise ValueError(f"{path}:{line_number}: unsafe source filename")
        if message_name in mapping:
            raise ValueError(f"{path}:{line_number}: duplicate mapping for {message_name}")
        mapping[message_name] = annotation_name
    return mapping


def _read_additional_annotations(path: Path, text: str) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(_decode_source_file(path).splitlines(), 1):
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        if len(fields) < 3:
            raise ValueError(f"{path}:{line_number}: malformed annotation record")
        try:
            start, length = int(fields[0]), int(fields[1])
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: non-integer annotation offset") from exc
        source_type = fields[-1]
        annotation = _span(text, start, length, kind="source_annotation", source_type=source_type)
        annotation["source_fields"] = fields[2:]
        annotations.append(annotation)
    return annotations


def parse_radar_action(
    *,
    message_root: str | Path = DEFAULT_MESSAGE_ROOT,
    expected_archive_sha256: str = ARCHIVE_SHA256,
    source_archive_sha256: str = ARCHIVE_SHA256,
) -> list[dict[str, Any]]:
    """Parse the official release into auxiliary records without FYP remapping."""
    root = Path(message_root)
    messages_dir = root / "messages"
    judgments_path = root / "judgments" / "judgments.txt"
    annotation_dir = root / "annotations"
    pair_path = annotation_dir / "MsgAnnotationFilenamePairs.txt"
    for required in (messages_dir, judgments_path, annotation_dir, pair_path):
        if not required.exists():
            raise FileNotFoundError(required)

    if source_archive_sha256 != expected_archive_sha256:
        raise ValueError("source archive hash does not match the pinned RADAR release")
    judgments = _read_judgments(judgments_path)
    annotation_map = _read_annotation_map(pair_path)
    records: list[dict[str, Any]] = []
    for message_path in sorted(messages_dir.glob("msg-*.txt"), key=lambda path: int(path.stem.removeprefix("msg-"))):
        filename = message_path.name
        if filename not in judgments or filename not in annotation_map:
            raise ValueError(f"missing judgment or annotation mapping for {filename}")
        text = _decode_source_file(message_path)
        label, raw_spans = judgments[filename]
        action_spans = [
            _span(text, start, length, kind="action_item")
            for start, length in raw_spans
        ]
        if (label == "Y") != bool(action_spans):
            raise ValueError(f"presence label and span count disagree for {filename}")
        annotation_name = annotation_map[filename]
        annotation_path = annotation_dir / annotation_name
        if not annotation_path.is_file():
            raise FileNotFoundError(annotation_path)
        extra_annotations = _read_additional_annotations(annotation_path, text)
        subject, body = _subject_and_body(text)
        records.append({
            "dataset": "RADAR_ACTION",
            "family": "RADAR_ACTION",
            "source_id": f"RADAR_ACTION:{filename}",
            "source_archive_sha256": source_archive_sha256,
            "source_message_id": filename,
            "source_message_id_kind": "dataset_filename",
            "rfc_message_id": None,
            "source_thread_id": None,
            "subject": subject,
            "body": body,
            "text": text,
            "text_encoding": "UTF-8",
            "newline_policy": "source bytes decoded without newline conversion",
            "offset_index_base": 0,
            "offset_unit": "Unicode code points",
            "offset_basis": "text (complete original message file, including headers and subject)",
            "action_item_present": label == "Y",
            "action_item_source_label": label,
            "action_item_spans": action_spans,
            "annotations": extra_annotations,
            "fyp_label_mapping": None,
            "threading_available": False,
        })
    if len(records) != len(judgments) or len(records) != len(annotation_map):
        raise ValueError(
            "message, judgment, and annotation-map counts differ: "
            f"{len(records)}, {len(judgments)}, {len(annotation_map)}"
        )
    return records


def summarize_radar_action(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    presence_counts = Counter("present" if record["action_item_present"] else "absent" for record in records)
    spans_per_message = Counter(len(record["action_item_spans"]) for record in records)
    annotation_types = Counter(
        annotation["source_type"]
        for record in records
        for annotation in record["annotations"]
    )
    annotation_records = sum(len(record["annotations"]) for record in records)
    return {
        "dataset": "RADAR_ACTION",
        "family": "RADAR_ACTION",
        "source_archive_sha256": records[0]["source_archive_sha256"] if records else None,
        "message_count": len(records),
        "judgment_presence_counts": dict(sorted(presence_counts.items())),
        "action_item_span_count": sum(len(record["action_item_spans"]) for record in records),
        "messages_by_action_item_span_count": {str(k): v for k, v in sorted(spans_per_message.items())},
        "additional_annotation_record_count": annotation_records,
        "additional_annotation_type_counts": dict(sorted(annotation_types.items())),
        "thread_id_available": False,
        "fyp_label_mapping_applied": False,
        "offset_basis": "complete original source message file",
        "offset_unit": "Unicode code points, zero-based, end-exclusive",
    }


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_radar_action_outputs(
    *,
    message_root: str | Path = DEFAULT_MESSAGE_ROOT,
    output_path: str | Path = DEFAULT_OUTPUT,
    review_output_path: str | Path = DEFAULT_REVIEW_OUTPUT,
    stats_path: str | Path = DEFAULT_STATS,
    source_archive_sha256: str = ARCHIVE_SHA256,
) -> dict[str, Any]:
    records = parse_radar_action(message_root=message_root, source_archive_sha256=source_archive_sha256)
    write_jsonl(output_path, records)

    positives = [record for record in records if record["action_item_present"]]
    negatives = [record for record in records if not record["action_item_present"]]
    review_records: list[dict[str, Any]] = []
    for index in range(25):
        if index < len(positives):
            review_records.append(positives[index])
        if index < len(negatives):
            review_records.append(negatives[index])
    if len(review_records) < 50:
        remaining = [record for record in records if record not in review_records]
        review_records.extend(remaining[:50 - len(review_records)])
    write_jsonl(review_output_path, review_records)

    stats = summarize_radar_action(records)
    stats.update({
        "source_message_file_count": len(list((Path(message_root) / "messages").glob("msg-*.txt"))),
        "judgment_row_count": len(_read_judgments(Path(message_root) / "judgments" / "judgments.txt")),
        "annotation_mapping_row_count": len(_read_annotation_map(Path(message_root) / "annotations" / "MsgAnnotationFilenamePairs.txt")),
        "source_annotation_file_count": len(list((Path(message_root) / "annotations").glob("annotation-*.txt"))),
        "validated_action_item_span_count": sum(len(record["action_item_spans"]) for record in records),
        "validated_additional_annotation_count": sum(len(record["annotations"]) for record in records),
        "processed_jsonl": _portable_path(output_path),
        "review_jsonl": _portable_path(review_output_path),
        "review_record_count": len(review_records),
    })
    target = Path(stats_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


__all__ = [
    "ARCHIVE_SHA256",
    "DEFAULT_ARCHIVE",
    "DEFAULT_EXTRACTED_ROOT",
    "DEFAULT_MESSAGE_ROOT",
    "DEFAULT_OUTPUT",
    "DEFAULT_RAW_ROOT",
    "DEFAULT_REVIEW_OUTPUT",
    "DEFAULT_STATS",
    "OFFICIAL_ARCHIVE_URL",
    "OFFICIAL_PAGE_URL",
    "acquire_radar_action",
    "parse_radar_action",
    "safe_extract_archive",
    "sha256_file",
    "summarize_radar_action",
    "write_radar_action_outputs",
]

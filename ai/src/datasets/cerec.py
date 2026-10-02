"""Acquisition and bounded inspection parser for the author CEREC release.

The Enron-derived message text has unresolved source-license scope. This
adapter only prepares aggregate counts and a local 50-thread review sample;
it does not authorize training or label mapping. Raw column values remain
available in the review sample so an authorized audit can inspect the actual
annotation encoding without the parser inventing a reply graph.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Iterator
from urllib.request import Request, urlopen
import zipfile


DATASET = "cerec"
SOURCE_FAMILY = "ENRON"
REPOSITORY_URL = "https://github.com/paragdakle/emailcoref"
COMMIT = "d86bdcdf963b4181aa7d6a3e3ca761c971ab27d9"
BASE_URL = f"https://raw.githubusercontent.com/paragdakle/emailcoref/{COMMIT}"
DEFAULT_AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ROOT = DEFAULT_AI_ROOT / "data" / "raw" / "cerec"
DEFAULT_DATA_ROOT = DEFAULT_RAW_ROOT / COMMIT
DEFAULT_EXTRACTED_ROOT = DEFAULT_DATA_ROOT / "extracted"
DEFAULT_CONLL_ROOT = DEFAULT_EXTRACTED_ROOT / "cerec"
DEFAULT_REVIEW_OUTPUT = DEFAULT_AI_ROOT / "data" / "processed" / "cerec_review_50.jsonl"
DEFAULT_STATS = DEFAULT_AI_ROOT / "reports" / "cerec_statistics.json"
DEFAULT_MANIFEST = DEFAULT_DATA_ROOT / "acquisition.json"
ARCHIVE_GIT_BLOB_SHA = "4b86f155028285e93b50396a8bc5a4975875ed41"
ARCHIVE_SHA256 = "6719223815d6a2301c01a596892d76c0cf33a03fff0ac53f7b43de4b93bc830b"

FILES = {
    "archive": {
        "name": "cerec.zip",
        "path": "data/COLING/cerec.zip",
        "sha256": ARCHIVE_SHA256,
        "bytes": 16994267,
    },
    "readme": {
        "name": "README.md",
        "path": "README.md",
        "sha256": "647ebba111a2646b9ab480d373caf1ef1505eb72d891190abc69a765f4d6d910",
        "bytes": 5447,
    },
    "license": {
        "name": "LICENSE",
        "path": "LICENSE",
        "sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        "bytes": 11357,
    },
}

CONLL_FILES = {
    "cerec.conll": "full_corpus",
    "cerec.validation.14.conll": "validation_set_14",
    "cerec.validation.20.conll": "validation_set_20",
    "mention.corrected.94.conll": "mention_corrected_94",
    "seed.conll": "seed_corpus",
}
COLUMN_NAMES = (
    "token",
    "message_id_feature",
    "section_id_feature",
    "speaker_feature",
    "entity_type_annotation",
    "mention_annotation",
    "coreference_annotation",
)
BEGIN_RE = re.compile(r"^#begin document \((.*?)\); part\s+(\d+)\s*$")
NUMBER_RE = re.compile(r"\d+")
ENTITY_CODES = {
    "PERSON": "PERSON", "PER": "PERSON", "P": "PERSON",
    "ORGANIZATION": "ORGANIZATION", "ORG": "ORGANIZATION", "O": "ORGANIZATION",
    "LOCATION": "LOCATION", "LOC": "LOCATION", "L": "LOCATION",
    "DIGITAL": "DIGITAL", "DIG": "DIGITAL", "D": "DIGITAL",
}
ENTITY_CODE_RE = re.compile(
    r"(?<![A-Z])(ORGANIZATION|PERSON|LOCATION|DIGITAL|ORG|PER|LOC|DIG|O|P|L|D)(?![A-Z])",
    re.IGNORECASE,
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = Request(url, headers={"User-Agent": "FYP-CEREC-Acquisition/1.0"})
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            resolved_url = response.geturl()
        temporary.replace(destination)
        return resolved_url
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _safe_zip_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe CEREC ZIP member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe CEREC ZIP member path: {name!r}")
    if any(":" in part or part.endswith((".", " ")) for part in path.parts):
        raise ValueError(f"unsafe CEREC ZIP member path: {name!r}")
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{index}"
        for prefix in ("com", "lpt")
        for index in range(1, 10)
    }
    if any(part.split(".")[0].casefold() in reserved for part in path.parts):
        raise ValueError(f"unsafe CEREC ZIP member path: {name!r}")
    return path


def safe_extract_cerec_archive(
    archive_path: str | Path,
    destination: str | Path,
    *,
    max_members: int = 100,
    max_member_bytes: int = 160 * 1024 * 1024,
    max_total_bytes: int = 200 * 1024 * 1024,
) -> Path:
    """Safely extract the small author ZIP and validate existing extraction."""
    archive_path = Path(archive_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target_root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError(f"CEREC archive has too many members: {len(members)}")
        checked: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        total_size = 0
        seen: set[PurePosixPath] = set()
        for info in members:
            relative = _safe_zip_path(info.filename.rstrip("/")) if info.filename.rstrip("/") else None
            if relative is None:
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"CEREC ZIP symbolic link is not allowed: {info.filename!r}")
            # ZIP producers often omit the POSIX file-type bits entirely. In
            # that case the member is an ordinary file unless it is explicitly
            # marked as a symlink or another special type.
            file_type = stat.S_IFMT(mode)
            if not info.is_dir() and file_type not in {0, stat.S_IFREG}:
                raise ValueError(f"unsupported CEREC ZIP member type: {info.filename!r}")
            if relative in seen:
                raise ValueError(f"duplicate CEREC ZIP path: {info.filename!r}")
            seen.add(relative)
            if info.file_size > max_member_bytes:
                raise ValueError(f"CEREC ZIP member exceeds size limit: {info.filename!r}")
            total_size += info.file_size
            if total_size > max_total_bytes:
                raise ValueError("CEREC ZIP expands beyond configured size limit")
            target = (target_root / Path(*relative.parts)).resolve()
            if target != target_root and target_root not in target.parents:
                raise ValueError(f"CEREC ZIP member escapes extraction directory: {info.filename!r}")
            checked.append((info, relative))

        if destination.exists():
            for info, relative in checked:
                target = destination.joinpath(*relative.parts)
                if info.is_dir():
                    if not target.is_dir():
                        raise FileExistsError(f"existing CEREC extraction differs: {target}")
                    continue
                if not target.is_file() or target.stat().st_size != info.file_size:
                    raise FileExistsError(f"existing CEREC extraction differs: {target}")
                with archive.open(info) as source, target.open("rb") as extracted:
                    for source_chunk in iter(lambda: source.read(1024 * 1024), b""):
                        if source_chunk != extracted.read(len(source_chunk)):
                            raise FileExistsError(f"existing CEREC extraction differs: {target}")
            return destination

        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info, relative in checked:
                    target = staging.joinpath(*relative.parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return destination


def acquire_cerec(*, raw_root: str | Path = DEFAULT_RAW_ROOT) -> dict[str, Any]:
    """Acquire pinned author files and safely extract the CEREC archive."""
    raw_root = Path(raw_root)
    data_root = raw_root / COMMIT
    data_root.mkdir(parents=True, exist_ok=True)
    manifest_path = data_root / "acquisition.json"
    previous: dict[str, Any] = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("commit") != COMMIT:
            raise ValueError("existing CEREC manifest names a different author commit")

    resolved_urls: dict[str, str] = dict(previous.get("resolved_urls", {}))
    files: dict[str, dict[str, Any]] = {}
    for key, metadata in FILES.items():
        target = data_root / metadata["name"]
        if not target.exists():
            resolved_urls[key] = _download(f"{BASE_URL}/{metadata['path']}", target)
        digest = sha256_file(target)
        if digest != metadata["sha256"] or target.stat().st_size != metadata["bytes"]:
            raise ValueError(f"pinned CEREC file validation failed: {metadata['name']}")
        resolved_urls.setdefault(key, f"{BASE_URL}/{metadata['path']}")
        files[key] = {
            "filename": metadata["name"],
            "url": f"{BASE_URL}/{metadata['path']}",
            "resolved_url": resolved_urls[key],
            "bytes": metadata["bytes"],
            "sha256": digest,
        }

    extracted_root = data_root / "extracted"
    safe_extract_cerec_archive(data_root / FILES["archive"]["name"], extracted_root)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {
        "dataset": DATASET,
        "repository_url": REPOSITORY_URL,
        "commit": COMMIT,
        "archive_git_blob_sha": ARCHIVE_GIT_BLOB_SHA,
        "downloaded_at_utc": previous.get("downloaded_at_utc", timestamp),
        "download_date_utc": previous.get("download_date_utc", timestamp[:10]),
        "repository_license": "Apache-2.0 declared by repository metadata and pinned LICENSE",
        "paper_license_statement": "The COLING paper states CC BY 4.0; its scope for embedded Enron email text is not explicit.",
        "message_text_rights": "UNRESOLVED; local inspection only; training and redistribution prohibited pending orchestrator authorization.",
        "files": files,
        "extracted_root": str(extracted_root),
        "zip_crc_checked_during_extraction": True,
        "training_permitted": False,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _strip_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _parse_begin_header(line: str) -> tuple[str, str | None] | None:
    """Accept the standard CoNLL header and the author's bare CEREC header."""
    standard = BEGIN_RE.match(line)
    if standard:
        doc_id, part_number = standard.groups()
        if doc_id:
            return doc_id, part_number
        return None
    prefix = "#begin document "
    if not line.startswith(prefix):
        return None
    # CEREC's bundled files use a one-token document name with no explicit
    # `part` clause. Keep the complete token exactly as stored in the header.
    doc_id = line[len(prefix):].strip()
    if not doc_id or any(char.isspace() for char in doc_id):
        return None
    return doc_id, None


def _feature_values(values: set[str]) -> set[str]:
    return {value for value in values if value not in {"", "-", "_"}}


def _entity_types(value: str) -> list[str]:
    types: list[str] = []
    for match in ENTITY_CODE_RE.findall(value.upper()):
        mapped = ENTITY_CODES.get(match.upper())
        if mapped and mapped not in types:
            types.append(mapped)
    return types


def _document_record(
    *,
    doc_id: str,
    part_number: str | None,
    source_file: str,
    source_role: str,
    sentences: list[list[list[str]]],
    message_ids: set[str],
    section_ids: set[str],
    speakers: set[str],
    entity_types: Counter[str],
    coreference_ids: set[str],
    mention_ids: set[str],
    coreference_occurrences: dict[str, list[int]],
    entity_annotation_rows: int,
    mention_annotation_rows: int,
    coreference_annotation_rows: int,
    antecedent_marker_count: int,
    malformed_coreference_code_count: int,
    token_count: int,
    source_archive_sha256: str,
) -> dict[str, Any]:
    token_rows = [row for sentence in sentences for row in sentence]
    text = "\n".join(" ".join(row[0] for row in sentence) for sentence in sentences)
    clusters = [
        {
            "source_cluster_id": cluster_id,
            "annotation_column": "coreference_annotation",
            "annotated_token_rows": positions,
        }
        for cluster_id, positions in sorted(coreference_occurrences.items(), key=lambda item: int(item[0]))
    ]
    return {
        "dataset": DATASET,
        "source_dataset": DATASET,
        "source_family": SOURCE_FAMILY,
        "overlap_family": SOURCE_FAMILY,
        "source_id": f"cerec:{COMMIT}:{source_file}:{doc_id}"
        + (f":part{part_number}" if part_number is not None else ""),
        "source_id_kind": "author_conll_document_id_and_optional_part",
        "source_thread_id": doc_id,
        "source_thread_id_kind": "cerec_document_id",
        "source_document_part": int(part_number) if part_number is not None else None,
        "source_message_id": None,
        "rfc_message_id": None,
        "source_split": source_role,
        "source_file": source_file,
        "source_archive_sha256": source_archive_sha256,
        "unit": "thread",
        "text": text,
        "text_provenance": "space-joined source CoNLL token sequence with blank-line sentence boundaries; not original mail bytes",
        "source_column_names": list(COLUMN_NAMES),
        "sentences": [
            {"token_rows": [dict(zip(COLUMN_NAMES, row)) for row in sentence]}
            for sentence in sentences
        ],
        "token_count": token_count,
        "message_id_feature_count": len(_feature_values(message_ids)),
        "section_id_feature_count": len(_feature_values(section_ids)),
        "speaker_feature_count": len(_feature_values(speakers)),
        "entity_type_counts": dict(sorted(entity_types.items())),
        "entity_annotation_row_count": entity_annotation_rows,
        "mention_annotation_row_count": mention_annotation_rows,
        "coreference_annotation_row_count": coreference_annotation_rows,
        "mention_annotation_id_count": len(mention_ids),
        "coreference_cluster_count": len(coreference_ids),
        "coreference_clusters": clusters,
        "antecedent_marker_count": antecedent_marker_count,
        "malformed_coreference_code_count": malformed_coreference_code_count,
        "fragment": False,
        "overlap_identity_complete": False,
        "fyp_labels": [],
        "training_permitted": False,
        "reply_graph_available": False,
    }


def _parse_file(
    path: str | Path,
    *,
    source_file: str,
    source_role: str,
    source_archive_sha256: str,
    review_remaining: int,
) -> tuple[dict[str, Any], set[str], list[dict[str, Any]]]:
    path = Path(path)
    file_stats: Counter[str] = Counter()
    entity_counts: Counter[str] = Counter()
    coreference_ids_all: set[tuple[str, str]] = set()
    mention_ids_all: set[tuple[str, str]] = set()
    documents: set[str] = set()
    duplicate_document_blocks = 0
    review_records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def new_document(doc_id: str, part_number: str | None) -> dict[str, Any]:
        return {
            "doc_id": doc_id,
            "part_number": part_number,
            "sentences": [],
            "current_sentence": [],
            "message_ids": set(),
            "section_ids": set(),
            "speakers": set(),
            "entity_types": Counter(),
            "coreference_ids": set(),
            "mention_ids": set(),
            "coreference_occurrences": defaultdict(list),
            "entity_annotation_rows": 0,
            "mention_annotation_rows": 0,
            "coreference_annotation_rows": 0,
            "antecedent_marker_count": 0,
            "malformed_coreference_code_count": 0,
            "token_count": 0,
        }

    def finish_document(doc: dict[str, Any]) -> None:
        if doc["current_sentence"]:
            doc["sentences"].append(doc["current_sentence"])
            doc["current_sentence"] = []

    with path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = _strip_line_ending(raw_line)
            if line.startswith("#begin document"):
                if current is not None:
                    raise ValueError(f"{path}:{line_number}: nested document start")
                parsed_header = _parse_begin_header(line)
                if parsed_header is None:
                    raise ValueError(f"{path}:{line_number}: malformed document header")
                doc_id, part_number = parsed_header
                current = new_document(doc_id, part_number)
                if doc_id in documents:
                    duplicate_document_blocks += 1
                documents.add(doc_id)
                file_stats["document_block_count"] += 1
                continue
            if line.startswith("#end document"):
                if current is None:
                    raise ValueError(f"{path}:{line_number}: document end without a start")
                finish_document(current)
                for chain_id in current["coreference_ids"]:
                    coreference_ids_all.add((current["doc_id"], chain_id))
                for mention_id in current["mention_ids"]:
                    mention_ids_all.add((current["doc_id"], mention_id))
                for key in (
                    "token_count", "entity_annotation_rows", "mention_annotation_rows",
                    "coreference_annotation_rows", "antecedent_marker_count",
                    "malformed_coreference_code_count",
                ):
                    file_stats[key] += current[key]
                file_stats["message_id_feature_count"] += len(_feature_values(current["message_ids"]))
                file_stats["section_id_feature_count"] += len(_feature_values(current["section_ids"]))
                file_stats["speaker_feature_count"] += len(_feature_values(current["speakers"]))
                file_stats["distinct_coreference_cluster_count"] += len(current["coreference_ids"])
                file_stats["distinct_mention_annotation_id_count"] += len(current["mention_ids"])
                file_stats["threads_with_coreference_annotations"] += bool(current["coreference_annotation_rows"])
                for entity_type, count in current["entity_types"].items():
                    entity_counts[entity_type] += count
                if review_remaining > 0 and current["coreference_annotation_rows"]:
                    review_records.append(_document_record(
                        doc_id=current["doc_id"],
                        part_number=current["part_number"],
                        source_file=source_file,
                        source_role=source_role,
                        sentences=current["sentences"],
                        message_ids=current["message_ids"],
                        section_ids=current["section_ids"],
                        speakers=current["speakers"],
                        entity_types=current["entity_types"],
                        coreference_ids=current["coreference_ids"],
                        mention_ids=current["mention_ids"],
                        coreference_occurrences=current["coreference_occurrences"],
                        entity_annotation_rows=current["entity_annotation_rows"],
                        mention_annotation_rows=current["mention_annotation_rows"],
                        coreference_annotation_rows=current["coreference_annotation_rows"],
                        antecedent_marker_count=current["antecedent_marker_count"],
                        malformed_coreference_code_count=current["malformed_coreference_code_count"],
                        token_count=current["token_count"],
                        source_archive_sha256=source_archive_sha256,
                    ))
                    review_remaining -= 1
                current = None
                continue
            if current is None:
                if not line.strip() or line.startswith("#"):
                    continue
                raise ValueError(f"{path}:{line_number}: token row outside a document block")
            if not line:
                if current["current_sentence"]:
                    current["sentences"].append(current["current_sentence"])
                    current["current_sentence"] = []
                continue
            if line.startswith("#"):
                file_stats["comment_line_count"] += 1
                continue
            columns = line.split("\t\t")
            if len(columns) != len(COLUMN_NAMES):
                raise ValueError(
                    f"{path}:{line_number}: expected {len(COLUMN_NAMES)} double-tab columns, got {len(columns)}"
                )
            file_stats[f"column_width_{len(columns)}_row_count"] += 1
            current["token_count"] += 1
            current["current_sentence"].append(columns)
            for key, column_index in (("message_ids", 1), ("section_ids", 2), ("speakers", 3)):
                if columns[column_index] not in {"", "-", "_"}:
                    current[key].add(columns[column_index])
            entity_cell, mention_cell, coref_cell = columns[4:7]
            if entity_cell not in {"", "-", "_"}:
                current["entity_annotation_rows"] += 1
                for entity_type in _entity_types(entity_cell):
                    current["entity_types"][entity_type] += 1
            if mention_cell not in {"", "-", "_"}:
                current["mention_annotation_rows"] += 1
                ids = NUMBER_RE.findall(mention_cell)
                current["mention_ids"].update(ids)
            if coref_cell not in {"", "-", "_"}:
                current["coreference_annotation_rows"] += 1
                ids = NUMBER_RE.findall(coref_cell)
                if not ids:
                    current["malformed_coreference_code_count"] += 1
                for chain_id in ids:
                    current["coreference_ids"].add(chain_id)
                    current["coreference_occurrences"][chain_id].append(current["token_count"] - 1)
                current["antecedent_marker_count"] += coref_cell.count("*")
    if current is not None:
        raise ValueError(f"{path}: unterminated CEREC document block")

    return (
        {
            "source_file": source_file,
            "source_file_role": source_role,
            "document_count": file_stats["document_block_count"],
            "unique_thread_id_count": len(documents),
            "duplicate_document_block_count": duplicate_document_blocks,
            "token_row_count": file_stats["token_count"],
            "message_id_feature_count_sum": file_stats["message_id_feature_count"],
            "section_id_feature_count_sum": file_stats["section_id_feature_count"],
            "speaker_feature_count_sum": file_stats["speaker_feature_count"],
            "entity_annotation_row_count": file_stats["entity_annotation_rows"],
            "entity_type_annotation_token_counts": dict(sorted(entity_counts.items())),
            "mention_annotation_row_count": file_stats["mention_annotation_rows"],
            "distinct_mention_annotation_id_count": file_stats["distinct_mention_annotation_id_count"],
            "coreference_annotation_row_count": file_stats["coreference_annotation_rows"],
            "distinct_coreference_cluster_count": file_stats["distinct_coreference_cluster_count"],
            "threads_with_coreference_annotations": file_stats["threads_with_coreference_annotations"],
            "antecedent_marker_count": file_stats["antecedent_marker_count"],
            "malformed_coreference_code_count": file_stats["malformed_coreference_code_count"],
            "observed_token_column_widths": {"7": file_stats["column_width_7_row_count"]},
        },
        documents,
        review_records,
    )


def _portable_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(DEFAULT_AI_ROOT.parent.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def write_jsonl(path: str | Path, records: list[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


def prepare_cerec(
    *,
    conll_root: str | Path = DEFAULT_CONLL_ROOT,
    review_output_path: str | Path = DEFAULT_REVIEW_OUTPUT,
    stats_path: str | Path = DEFAULT_STATS,
    source_archive_sha256: str = ARCHIVE_SHA256,
    review_limit: int = 50,
) -> dict[str, Any]:
    """Count each author file and write only a local sample for rights review."""
    if source_archive_sha256 != ARCHIVE_SHA256:
        raise ValueError("CEREC archive hash does not match the pinned author release")
    if review_limit < 1:
        raise ValueError("review_limit must be positive")
    conll_root = Path(conll_root)
    per_file: dict[str, Any] = {}
    ids_by_file: dict[str, set[str]] = {}
    review_records: list[dict[str, Any]] = []
    for filename, role in CONLL_FILES.items():
        file_path = conll_root / filename
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        stats, document_ids, samples = _parse_file(
            file_path,
            source_file=filename,
            source_role=role,
            source_archive_sha256=source_archive_sha256,
            review_remaining=review_limit - len(review_records) if filename == "cerec.conll" else 0,
        )
        per_file[filename] = stats
        ids_by_file[filename] = document_ids
        if filename == "cerec.conll":
            review_records.extend(samples)
    if len(review_records) != review_limit:
        raise ValueError(f"only {len(review_records)} coreference-annotated threads available for review")

    overlaps = {}
    full_ids = ids_by_file.get("cerec.conll", set())
    for filename, ids in ids_by_file.items():
        if filename != "cerec.conll":
            overlaps[filename] = {
                "thread_ids_also_in_full_corpus_count": len(ids & full_ids),
                "thread_ids_not_in_full_corpus_count": len(ids - full_ids),
            }
    all_ids = set().union(*ids_by_file.values()) if ids_by_file else set()
    stats = {
        "dataset": DATASET,
        "source_family": SOURCE_FAMILY,
        "repository_url": REPOSITORY_URL,
        "pinned_commit": COMMIT,
        "archive_git_blob_sha": ARCHIVE_GIT_BLOB_SHA,
        "source_archive_sha256": source_archive_sha256,
        "source_archive_bytes": FILES["archive"]["bytes"],
        "source_file_roles": dict(CONLL_FILES),
        "source_stated_counts": {
            "threads": 6001,
            "messages": 36448,
            "coreference_chains_repository_and_2020_paper": 38996,
            "coreference_chains_updated_author_paper": 60383,
        },
        "observed_per_file": per_file,
        "unique_thread_ids_union_across_files": len(all_ids),
        "file_overlap_counts_against_main_corpus": overlaps,
        "observed_source_column_count": 7,
        "readme_column_count_note": "README calls the CoNLL files eight-column once but enumerates seven columns; every token row in all five pinned files has exactly seven double-tab-separated columns.",
        "thread_ids_preserved": True,
        "reply_graph_inferred": False,
        "message_text_rights": "UNRESOLVED; locally acquired for inspection only; training and redistribution are not authorized.",
        "training_permitted": False,
        "fyp_labels_generated": False,
        "review_record_count": len(review_records),
        "review_sample_source_file": "cerec.conll",
        "review_output": _portable_path(review_output_path),
        "review_sample_has_coreference_annotations": all(row["coreference_annotation_row_count"] > 0 for row in review_records),
    }
    write_jsonl(review_output_path, review_records)
    stats_path = Path(stats_path)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


__all__ = [
    "ARCHIVE_GIT_BLOB_SHA",
    "ARCHIVE_SHA256",
    "COMMIT",
    "CONLL_FILES",
    "DATASET",
    "DEFAULT_CONLL_ROOT",
    "DEFAULT_RAW_ROOT",
    "DEFAULT_REVIEW_OUTPUT",
    "DEFAULT_STATS",
    "FILES",
    "SOURCE_FAMILY",
    "acquire_cerec",
    "prepare_cerec",
    "safe_extract_cerec_archive",
    "sha256_file",
    "write_jsonl",
]

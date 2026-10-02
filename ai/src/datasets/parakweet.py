"""Deterministic adapter for the author-released Parakweet email-intent rows.

The source files are one sentence fragment per line with a binary ``Yes`` or
``No`` label. They contain no reliable email or thread identifier. Records are
therefore marked as fragments from the ENRON overlap family with incomplete
identity, and the binary source intent label is never mapped to FYP labels.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen


DATASET = "parakweet"
SOURCE_FAMILY = "ENRON"
REPOSITORY_URL = "https://github.com/ParakweetLabs/EmailIntentDataSet"
COMMIT = "055f62857b3214c1682a0b18a2c5fc2c9f0c00e6"
BASE_URL = f"https://raw.githubusercontent.com/ParakweetLabs/EmailIntentDataSet/{COMMIT}"
DEFAULT_AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ROOT = DEFAULT_AI_ROOT / "data" / "raw" / "parakweet"
DEFAULT_DATA_ROOT = DEFAULT_RAW_ROOT / COMMIT
DEFAULT_OUTPUT = DEFAULT_AI_ROOT / "data" / "processed" / "parakweet.jsonl"
DEFAULT_REVIEW_OUTPUT = DEFAULT_AI_ROOT / "data" / "processed" / "parakweet_review_50.jsonl"
DEFAULT_STATS = DEFAULT_AI_ROOT / "reports" / "parakweet_statistics.json"
DEFAULT_MANIFEST = DEFAULT_DATA_ROOT / "acquisition.json"

FILES = {
    "train": {
        "name": "Ask0729-fixed.txt",
        "path": "src/resources/Ask0729-fixed.txt",
        "sha256": "1dafc1b367cf2fb1e8b4a944b67e14578bcb1085f2f02ea150be45c373fbe8cd",
        "bytes": 347997,
    },
    "test": {
        "name": "testSet-qualifiedBatch-fixed.txt",
        "path": "src/resources/testSet-qualifiedBatch-fixed.txt",
        "sha256": "1b5ebc45a80c1e7fdeed656b7db7cec8e50eb18f562daa20070f1e3187e01e4a",
        "bytes": 95679,
    },
    "readme": {
        "name": "README.md",
        "path": "README.md",
        "sha256": "3c245e8439670e0f52c4997927144b35ee962d9487c09c7ba08fe621be838c05",
        "bytes": 387,
    },
    "license": {
        "name": "LICENSE",
        "path": "LICENSE",
        "sha256": "1945e82c7c7425a814c790a1ea16964083da7042ffdfa8232cd04e575dd6ff88",
        "bytes": 11351,
    },
}

AUTHOR_WIKI_COUNTS = {
    "train": {"records": 4213, "yes": 1631, "no": 2582},
    "test": {"records": 991, "yes": 277, "no": 714},
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = Request(url, headers={"User-Agent": "FYP-Parakweet-Acquisition/1.0"})
    try:
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            resolved_url = response.geturl()
        temporary.replace(destination)
        return resolved_url
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def acquire_parakweet(*, raw_root: str | Path = DEFAULT_RAW_ROOT) -> dict[str, Any]:
    """Acquire only the author data files plus the commit's README and license."""
    raw_root = Path(raw_root)
    data_root = raw_root / COMMIT
    data_root.mkdir(parents=True, exist_ok=True)
    manifest_path = data_root / "acquisition.json"
    previous: dict[str, Any] = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("commit") != COMMIT:
            raise ValueError("existing Parakweet manifest names a different author commit")

    resolved_urls: dict[str, str] = dict(previous.get("resolved_urls", {}))
    acquired: dict[str, dict[str, Any]] = {}
    for key, metadata in FILES.items():
        target = data_root / metadata["name"]
        if not target.exists():
            resolved_urls[key] = _download(f"{BASE_URL}/{metadata['path']}", target)
        actual_hash = sha256_file(target)
        if actual_hash != metadata["sha256"]:
            raise ValueError(
                f"{metadata['name']} SHA-256 mismatch: expected pinned {metadata['sha256']}, got {actual_hash}"
            )
        if target.stat().st_size != metadata["bytes"]:
            raise ValueError(f"{metadata['name']} byte length differs from the pinned file")
        resolved_urls.setdefault(key, f"{BASE_URL}/{metadata['path']}")
        acquired[key] = {
            "filename": metadata["name"],
            "url": f"{BASE_URL}/{metadata['path']}",
            "resolved_url": resolved_urls[key],
            "bytes": metadata["bytes"],
            "sha256": actual_hash,
        }

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {
        "dataset": DATASET,
        "repository_url": REPOSITORY_URL,
        "commit": COMMIT,
        "downloaded_at_utc": previous.get("downloaded_at_utc", timestamp),
        "download_date_utc": previous.get("download_date_utc", timestamp[:10]),
        "repository_license": "Apache-2.0 declared by the pinned README, LICENSE, and GitHub metadata",
        "data_files": acquired,
        "underlying_source": "Enron email sentence fragments; local/private source-text handling applies",
        "source_identity": "No reliable original email or thread identifiers are included in these sentence rows.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _line_records(path: str | Path, *, split: str, expected_sha256: str | None) -> list[dict[str, Any]]:
    path = Path(path)
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ValueError(f"{path.name} does not match its pinned SHA-256")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path.name} contains an unexpected UTF-8 BOM")

    rows: list[dict[str, Any]] = []
    for line_number, physical_line in enumerate(raw.splitlines(keepends=True), 1):
        if physical_line.endswith(b"\r\n"):
            row_bytes, line_ending = physical_line[:-2], "CRLF"
        elif physical_line.endswith(b"\n"):
            row_bytes, line_ending = physical_line[:-1], "LF"
        elif physical_line.endswith(b"\r"):
            row_bytes, line_ending = physical_line[:-1], "CR"
        else:
            row_bytes, line_ending = physical_line, "none"
        if not row_bytes:
            raise ValueError(f"{path.name}:{line_number}: blank rows are not permitted")
        if row_bytes.count(b"\t") != 1:
            raise ValueError(f"{path.name}:{line_number}: expected one label/sentence tab delimiter")
        label_bytes, sentence_bytes = row_bytes.split(b"\t", 1)
        try:
            label = label_bytes.decode("ascii", errors="strict")
            sentence = sentence_bytes.decode("utf-8", errors="strict")
            source_row_text = row_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{path.name}:{line_number}: invalid source encoding") from exc
        if label not in {"Yes", "No"}:
            raise ValueError(f"{path.name}:{line_number}: unknown source label {label!r}")
        rows.append({
            "dataset": DATASET,
            "source_dataset": DATASET,
            "source_family": SOURCE_FAMILY,
            "overlap_family": SOURCE_FAMILY,
            "source_id": f"parakweet:{COMMIT}:{split}:{line_number:06d}",
            "source_id_kind": "dataset_file_line",
            "source_message_id": None,
            "source_message_id_kind": "not_provided",
            "rfc_message_id": None,
            "source_thread_id": None,
            "source_file": path.name,
            "source_file_sha256": actual_sha256,
            "source_split": split,
            "source_row_number": line_number,
            "unit": "sentence",
            "text": sentence,
            "source_row_text": source_row_text,
            "source_label": label,
            "intent_present": label == "Yes",
            "normalized_auxiliary_act": None,
            "fyp_labels": [],
            "fragment": True,
            "overlap_identity_complete": False,
            "text_encoding": "UTF-8 (validated strictly)",
            "source_line_ending": line_ending,
        })
    return rows


def parse_parakweet(
    *,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    verify_pinned_files: bool = True,
) -> list[dict[str, Any]]:
    """Parse train/test rows while preserving source splits and binary labels."""
    data_root = Path(data_root)
    records: list[dict[str, Any]] = []
    for split in ("train", "test"):
        metadata = FILES[split]
        records.extend(_line_records(
            data_root / metadata["name"],
            split=split,
            expected_sha256=metadata["sha256"] if verify_pinned_files else None,
        ))
    return records


def _portable_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(DEFAULT_AI_ROOT.parent.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _split_counts(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_split: dict[str, Counter[str]] = defaultdict(Counter)
    texts_by_split: dict[str, list[str]] = defaultdict(list)
    for row in records:
        label_key = row["source_label"].casefold()
        by_split[row["source_split"]][label_key] += 1
        texts_by_split[row["source_split"]].append(row["text"])
    results: dict[str, Any] = {}
    for split in ("train", "test"):
        labels = by_split[split]
        results[split] = {
            "record_count": sum(labels.values()),
            "source_label_counts": {"Yes": labels["yes"], "No": labels["no"]},
            "unique_sentence_count": len(set(texts_by_split[split])),
            "duplicate_sentence_record_count": len(texts_by_split[split]) - len(set(texts_by_split[split])),
        }
    train_texts = set(texts_by_split["train"])
    test_texts = set(texts_by_split["test"])
    results["train_test_exact_sentence_overlap_unique_count"] = len(train_texts & test_texts)
    return results


def summarize_parakweet(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    split_counts = _split_counts(records)
    overall = Counter(row["source_label"] for row in records)
    ending_counts = Counter(row["source_line_ending"] for row in records)
    return {
        "dataset": DATASET,
        "source_family": SOURCE_FAMILY,
        "repository_url": REPOSITORY_URL,
        "pinned_commit": COMMIT,
        "source_file_sha256": {split: FILES[split]["sha256"] for split in ("train", "test")},
        "parsed_record_count": len(records),
        "source_label_counts": {"Yes": overall["Yes"], "No": overall["No"]},
        "split_counts": split_counts,
        "line_ending_counts": dict(sorted(ending_counts.items())),
        "fragment_count": sum(bool(row["fragment"]) for row in records),
        "identity_complete_count": sum(bool(row["overlap_identity_complete"]) for row in records),
        "source_message_id_available": False,
        "source_thread_id_available": False,
        "source_scope": "one sentence-level row per released line; no full email/thread reconstruction",
        "author_wiki_cited_counts": AUTHOR_WIKI_COUNTS,
        "mapping_policy": "Preserve Yes/No; no fine-grained act or FYP label inferred.",
    }


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def _select_review_records(records: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("review limit must be positive")
    targets = {
        ("train", "Yes"): limit // 4 + (limit % 4 > 0),
        ("train", "No"): limit // 4,
        ("test", "Yes"): limit // 4,
        ("test", "No"): limit // 4 + (limit % 4 > 1),
    }
    # For the standard 50-row review, this yields 13/12 positive and 12/13
    # negative records across train/test, for 25 records per label.
    selected: list[dict[str, Any]] = []
    for (split, label), target_count in targets.items():
        candidates = [row for row in records if row["source_split"] == split and row["source_label"] == label]
        selected.extend(candidates[:target_count])
    return sorted(selected, key=lambda row: (row["source_split"], row["source_row_number"]))


def prepare_parakweet(
    *,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    output_path: str | Path = DEFAULT_OUTPUT,
    review_output_path: str | Path = DEFAULT_REVIEW_OUTPUT,
    stats_path: str | Path = DEFAULT_STATS,
) -> dict[str, Any]:
    records = parse_parakweet(data_root=data_root)
    write_jsonl(output_path, records)
    review = _select_review_records(records)
    if len(review) != 50:
        raise ValueError(f"could only create {len(review)} review records; expected 50")
    write_jsonl(review_output_path, review)

    stats = summarize_parakweet(records)
    stats.update({
        "review_record_count": len(review),
        "review_source_label_counts": dict(sorted(Counter(row["source_label"] for row in review).items())),
        "review_split_counts": dict(sorted(Counter(row["source_split"] for row in review).items())),
        "processed_jsonl": _portable_path(output_path),
        "review_jsonl": _portable_path(review_output_path),
    })
    target = Path(stats_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


__all__ = [
    "COMMIT",
    "DATASET",
    "DEFAULT_DATA_ROOT",
    "DEFAULT_OUTPUT",
    "DEFAULT_REVIEW_OUTPUT",
    "DEFAULT_STATS",
    "FILES",
    "SOURCE_FAMILY",
    "acquire_parakweet",
    "parse_parakweet",
    "prepare_parakweet",
    "sha256_file",
    "summarize_parakweet",
    "write_jsonl",
]

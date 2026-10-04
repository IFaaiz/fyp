"""Build paired, FYP-safe MailEx body-only and subject-plus-body views.

Only safe TRAIN and DEV JSONL inputs are opened. A raw subject is used only
when the existing raw-thread helper verifies every turn in that thread.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT / "src"))

from datasets.mailex import _safe_raw_headers  # noqa: E402


DEFAULT_ROWS_DIR = AI_ROOT / "data" / "experiments" / "mailex_extraction_v1"
DEFAULT_RAW_THREADS = AI_ROOT / "data" / "raw" / "mailex" / "extracted" / "data" / "raw_threads"
DEFAULT_OUTPUT_DIR = AI_ROOT / "data" / "experiments" / "mailex_subject_ablation_v1"
DEFAULT_REPORT = AI_ROOT / "reports" / "mailex_subject_ablation.md"
SPLITS = ("train", "dev")
NONSPACE_RE = re.compile(r"\S+")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path.name}:{line_number}: expected a row object")
                rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return _sha256(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _offset_pair(offset: Any) -> tuple[int, int]:
    if isinstance(offset, dict):
        return int(offset["start"]), int(offset["end"])
    return int(offset[0]), int(offset[1])


def _parsed_segments(row: dict[str, Any]):
    for event in row.get("events", []):
        trigger = event.get("trigger")
        if isinstance(trigger, dict):
            for segment in trigger.get("segments", []):
                yield segment
        for argument in event.get("arguments", []):
            for segment in argument.get("segments", []):
                yield segment
    for marker in row.get("outside_markers", []):
        trigger = marker.get("trigger")
        if isinstance(trigger, dict):
            for segment in trigger.get("segments", []):
                yield segment


def _validate_row(row: dict[str, Any]) -> tuple[int, int]:
    text = row["text"]
    tokens = row["tokens"]
    offsets = row["token_offsets"]
    if len(tokens) != len(offsets):
        raise ValueError(f"token/offset length mismatch in row {row.get('message_id', '<unknown>')}")
    for token, offset in zip(tokens, offsets):
        start, end = _offset_pair(offset)
        if start < 0 or end < start or end > len(text) or text[start:end] != token:
            raise ValueError(f"token substring mismatch in row {row.get('message_id', '<unknown>')}")
    segment_count = 0
    for segment in _parsed_segments(row):
        start, end = int(segment["start"]), int(segment["end"])
        if start < 0 or end < start or end > len(text):
            raise ValueError(f"span offset out of bounds in row {row.get('message_id', '<unknown>')}")
        if text[start:end] != segment.get("text", ""):
            raise ValueError(f"span substring mismatch in row {row.get('message_id', '<unknown>')}")
        segment_count += 1
    return len(tokens), segment_count


def _prefix_tokens(prefix: str) -> tuple[list[str], list[dict[str, int]]]:
    tokens = []
    offsets = []
    for match in NONSPACE_RE.finditer(prefix):
        tokens.append(match.group(0))
        offsets.append({"start": match.start(), "end": match.end()})
    return tokens, offsets


def _shift_segment(segment: dict[str, Any], char_shift: int, token_shift: int) -> None:
    segment["start"] = int(segment["start"]) + char_shift
    segment["end"] = int(segment["end"]) + char_shift
    if "token_start" in segment:
        segment["token_start"] = int(segment["token_start"]) + token_shift
    if "token_end" in segment:
        segment["token_end"] = int(segment["token_end"]) + token_shift
    if isinstance(segment.get("token_indices"), list):
        segment["token_indices"] = [int(index) + token_shift for index in segment["token_indices"]]


def _shift_argument_token_indices(row: dict[str, Any], token_shift: int) -> int:
    checks = 0
    for event in row.get("events", []):
        for argument in event.get("arguments", []):
            if isinstance(argument.get("token_indices"), list):
                argument["token_indices"] = [int(index) + token_shift for index in argument["token_indices"]]
                checks += len(argument["token_indices"])
    return checks


def _subject_view(source: dict[str, Any], subject: str) -> tuple[dict[str, Any], int, int, int, int, int]:
    view = copy.deepcopy(source)
    prefix = f"Subject: {subject.strip()}\n\n" if subject.strip() else ""
    prefix_tokens, prefix_offsets = _prefix_tokens(prefix)
    char_shift, token_shift = len(prefix), len(prefix_tokens)
    old_text = source["text"]
    old_offsets = [_offset_pair(offset) for offset in source["token_offsets"]]
    old_segments = list(_parsed_segments(source))

    view["text"] = prefix + old_text
    view["tokens"] = prefix_tokens + list(source["tokens"])
    view["token_offsets"] = prefix_offsets + [
        {"start": start + char_shift, "end": end + char_shift}
        for start, end in old_offsets
    ]
    for segment in _parsed_segments(view):
        _shift_segment(segment, char_shift, token_shift)
    argument_token_index_checks = _shift_argument_token_indices(view, token_shift)
    view["subject_ablation"] = {
        "header_alignment": "verified",
        "subject_present": bool(subject.strip()),
        "prefix_char_length": char_shift,
        "prefix_token_count": token_shift,
    }

    token_count, segment_count = _validate_row(view)
    if view["text"][char_shift:] != old_text:
        raise ValueError("subject prefix changed body text")
    # Verify both coordinate systems were translated by precisely the prefix.
    for before, after in zip(old_offsets, view["token_offsets"][token_shift:]):
        if after != {"start": before[0] + char_shift, "end": before[1] + char_shift}:
            raise ValueError("body token offset did not shift exactly")
    new_segments = list(_parsed_segments(view))
    if len(old_segments) != len(new_segments):
        raise ValueError("parsed span count changed while adding the subject")
    token_index_checks = 0
    for before, after in zip(old_segments, new_segments):
        if (after["start"] != int(before["start"]) + char_shift
                or after["end"] != int(before["end"]) + char_shift
                or after.get("text") != before.get("text")):
            raise ValueError("event span character offsets did not shift exactly")
        for field in ("token_start", "token_end"):
            if field in before:
                if int(after[field]) != int(before[field]) + token_shift:
                    raise ValueError("event span token bounds did not shift exactly")
                token_index_checks += 1
        if isinstance(before.get("token_indices"), list):
            expected = [int(index) + token_shift for index in before["token_indices"]]
            if after.get("token_indices") != expected:
                raise ValueError("event span token indices did not shift exactly")
            token_index_checks += len(expected)
    for before_event, after_event in zip(source.get("events", []), view.get("events", [])):
        for before_argument, after_argument in zip(before_event.get("arguments", []), after_event.get("arguments", [])):
            if isinstance(before_argument.get("token_indices"), list):
                expected = [int(index) + token_shift for index in before_argument["token_indices"]]
                if after_argument.get("token_indices") != expected:
                    raise ValueError("argument token indices did not shift exactly")
    char_shift_checks = len(old_offsets) + len(old_segments)
    return view, token_count, segment_count, token_shift, char_shift_checks, token_index_checks + argument_token_index_checks


def _format_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# MailEx subject-plus-body ablation artifacts",
        "",
        "This report records a source-free preparation audit for separate FYP-safe TRAIN and DEV views. The script did not open TEST rows or TEST raw threads. It reads each safe thread's raw-thread header only after the existing `_safe_raw_headers` helper verifies turn count and normalized body alignment.",
        "",
        "## Paired view policy",
        "",
        "Only threads with verified header alignment are included, so body-only and subject-plus-body files contain the same messages. An empty or absent subject remains an aligned row with no added prefix. The body text and native event/argument associations are preserved. Nonempty subject text is prepended as unlabeled tokens; body token and event span character/token offsets are shifted by the exact prefix lengths and validated against exact substrings.",
        "",
        "The paired artifacts are an experimental view over the FYP-safe rows. They do not alter official MailEx splits or the original safe-view files. No message text, subject text, row IDs, or thread IDs are included here.",
        "",
        "## Counts and hashes",
        "",
        "| Split | Input safe messages | Input safe threads | Aligned threads | Paired messages | Nonempty subjects | Empty subjects | Alignment failures | Body file SHA-256 | Subject+body file SHA-256 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for split in SPLITS:
        item = manifest["splits"][split]
        lines.append(
            f"| {split} | {item['input_messages']} | {item['input_threads']} | {item['aligned_threads']} | "
            f"{item['paired_messages']} | {item['messages_with_nonempty_subject']} | {item['messages_with_empty_subject']} | "
            f"{item['alignment_failed_threads']} | `{item['body_paired_sha256']}` | `{item['subject_body_sha256']}` |"
        )
    lines.extend([
        "",
        "## Validation",
        "",
        "| Split | Token offsets checked | Parsed span segments checked | Exact character shifts checked | Exact token-index shifts checked | Validation errors |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for split in SPLITS:
        item = manifest["splits"][split]
        lines.append(
            f"| {split} | {item['validated_token_offsets']} | {item['validated_span_segments']} | "
            f"{item['exact_character_shift_checks']} | {item['exact_token_index_shift_checks']} | {item['validation_errors']} |"
        )
    lines.extend([
        "",
        "The manifest stores input and output file hashes and the aggregate alignment-reason counts. Hashes identify the exact private artifacts used; they do not reveal their contents.",
        "",
        "## Reproduction",
        "",
        "Run from `ai/` with the project virtual environment:",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe scripts\\prepare_mailex_subject_ablation.py",
        "```",
        "",
        "",
    ])
    return "\n".join(lines)


def prepare_subject_ablation(
    rows_dir: Path = DEFAULT_ROWS_DIR,
    raw_threads_dir: Path = DEFAULT_RAW_THREADS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    """Create source-aligned paired subject/body views for safe TRAIN and DEV."""
    manifest: dict[str, Any] = {
        "schema": "mailex_subject_ablation_v1",
        "source_variant": "mailex_native_fyp_safe_v1",
        "splits_read": list(SPLITS),
        "test_accessed": False,
        "subject_prefix_template": "Subject: {subject}\\n\\n; omitted for empty/absent subject",
        "alignment": "datasets.mailex._safe_raw_headers; whole thread included only if turns are complete and body alignment verifies",
        "splits": {},
        "privacy": "No message text, header text, thread IDs, or message IDs in this manifest or report.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        input_path = rows_dir / f"{split}_fyp_safe.jsonl"
        source_rows = _read_jsonl(input_path)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            if row.get("split") != split:
                raise ValueError(f"unexpected split label in {input_path.name}")
            groups[str(row["thread_id"])].append(row)

        body_rows: list[dict[str, Any]] = []
        subject_rows: list[dict[str, Any]] = []
        alignment_reasons: Counter[str] = Counter()
        aligned_threads = 0
        aligned_messages_nonempty_subject = 0
        aligned_messages_empty_subject = 0
        validation_counts = Counter()
        validation_errors = 0

        for thread_id, thread_rows in groups.items():
            ordered = sorted(thread_rows, key=lambda row: int(row["source_turn"]))
            turns = [int(row["source_turn"]) for row in ordered]
            complete_turns = turns == list(range(len(ordered)))
            if complete_turns:
                try:
                    headers_by_turn, alignment = _safe_raw_headers(
                        thread_id,
                        [list(row["tokens"]) for row in ordered],
                        raw_threads_dir,
                    )
                except OSError:
                    headers_by_turn = [{} for _ in ordered]
                    alignment = {"aligned": False, "reason": "raw thread file read error"}
            else:
                headers_by_turn = [{} for _ in ordered]
                alignment = {"aligned": False, "reason": "source turns are not a complete zero-based sequence"}

            if not alignment.get("aligned"):
                alignment_reasons[str(alignment.get("reason", "unknown alignment failure"))] += 1
                continue

            aligned_threads += 1
            for row, headers in zip(ordered, headers_by_turn):
                body_tokens, body_segments = _validate_row(row)
                validation_counts["validated_token_offsets"] += body_tokens
                validation_counts["validated_span_segments"] += body_segments
                subject = str(headers.get("subject", ""))
                if subject.strip():
                    aligned_messages_nonempty_subject += 1
                else:
                    aligned_messages_empty_subject += 1
                body_rows.append(copy.deepcopy(row))
                view, token_count, segment_count, token_shift, char_checks, token_checks = _subject_view(row, subject)
                subject_rows.append(view)
                validation_counts["validated_token_offsets"] += token_count
                validation_counts["validated_span_segments"] += segment_count
                validation_counts["exact_character_shift_checks"] += char_checks
                validation_counts["exact_token_index_shift_checks"] += token_checks

        body_name = f"{split}_body_paired.jsonl"
        subject_name = f"{split}_subject_body.jsonl"
        body_hash = _write_jsonl(output_dir / body_name, body_rows)
        subject_hash = _write_jsonl(output_dir / subject_name, subject_rows)
        manifest["splits"][split] = {
            "input_file": input_path.name,
            "input_sha256": _sha256(input_path),
            "input_messages": len(source_rows),
            "input_threads": len(groups),
            "aligned_threads": aligned_threads,
            "paired_messages": len(subject_rows),
            "alignment_failed_threads": sum(alignment_reasons.values()),
            "alignment_failure_reasons": dict(sorted(alignment_reasons.items())),
            "messages_with_nonempty_subject": aligned_messages_nonempty_subject,
            "messages_with_empty_subject": aligned_messages_empty_subject,
            "body_file": body_name,
            "body_paired_sha256": body_hash,
            "subject_body_file": subject_name,
            "subject_body_sha256": subject_hash,
            **dict(validation_counts),
            "validation_errors": validation_errors,
        }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_format_report(manifest), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows-dir", type=Path, default=DEFAULT_ROWS_DIR)
    parser.add_argument("--raw-threads-dir", type=Path, default=DEFAULT_RAW_THREADS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = prepare_subject_ablation(args.rows_dir, args.raw_threads_dir, args.output_dir, args.report)
    print(json.dumps({
        "test_accessed": result["test_accessed"],
        "splits": {
            split: {
                "paired_messages": data["paired_messages"],
                "aligned_threads": data["aligned_threads"],
                "messages_with_nonempty_subject": data["messages_with_nonempty_subject"],
                "body_paired_sha256": data["body_paired_sha256"],
                "subject_body_sha256": data["subject_body_sha256"],
                "validation_errors": data["validation_errors"],
            }
            for split, data in result["splits"].items()
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

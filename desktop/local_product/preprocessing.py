"""Conservative authored-text isolation for display and rule candidates.

The versioned segmentation API reports ranges against the original Python
string. Its offsets are end-exclusive string indexes, not UTF-8 byte offsets.
"""
from __future__ import annotations

import re
from typing import Literal


_DASHED_HISTORY = re.compile(r"^-{2,}\s*(?:original message|forwarded message|forwarded by)\b", re.I)
_ON_WROTE = re.compile(r"^on\s+.{4,}\s+wrote:\s*$", re.I)
_SIGNATURE = re.compile(r"^--\s*$")
_HEADER_FIELD = re.compile(r"^(?:from|sent|date|to|cc|subject):\s*\S", re.I)
_LINE_BREAK = re.compile(r"\r\n|\r|\n")

_RangeKind = Literal["authored", "quoted", "uncertain", "signature"]
_KINDS: tuple[_RangeKind, ...] = ("authored", "quoted", "uncertain", "signature")


def normalize_body_text(text: str) -> str:
    """Normalize transport whitespace while leaving the stored raw body intact."""
    return (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )


def _raw_lines(raw_body: str) -> list[tuple[int, int, str]]:
    """Return (start, end, normalized line) tuples without losing raw offsets."""
    lines: list[tuple[int, int, str]] = []
    start = 0
    for match in _LINE_BREAK.finditer(raw_body):
        end = match.end()
        lines.append((start, end, normalize_body_text(raw_body[start:end])))
        start = end
    if start < len(raw_body):
        lines.append((start, len(raw_body), normalize_body_text(raw_body[start:])))
    return lines


def _header_block_starts(lines: list[str], index: int) -> bool:
    if not re.match(r"^from:\s*\S", lines[index].strip(), re.I):
        return False
    fields: set[str] = set()
    for candidate in lines[index : min(len(lines), index + 10)]:
        match = _HEADER_FIELD.match(candidate.strip())
        if match:
            fields.add(match.group(0).split(":", 1)[0].lower())
    return "from" in fields and bool(fields.intersection({"sent", "date"})) and bool(
        fields.intersection({"to", "cc", "subject"})
    )


def _classify_lines(raw_body: str) -> list[tuple[int, int, str, _RangeKind]]:
    lines = _raw_lines(raw_body)
    normalized_lines = [line.strip("\r\n") for _, _, line in lines]
    classified: list[tuple[int, int, str, _RangeKind]] = []
    explicit_history_started = False
    on_wrote_started = False
    on_wrote_quote_seen = False
    signature_started = False

    for index, (start, end, normalized_line) in enumerate(lines):
        stripped = normalized_line.strip()
        is_explicit_history_header = bool(
            _DASHED_HISTORY.match(stripped)
            or _header_block_starts(normalized_lines, index)
        )
        is_on_wrote_header = bool(_ON_WROTE.match(stripped))
        is_marked_quote = stripped.startswith(">")

        if signature_started:
            kind: _RangeKind = "signature"
        elif index > 0 and _SIGNATURE.match(stripped):
            signature_started = True
            kind = "signature"
        elif is_explicit_history_header:
            explicit_history_started = True
            kind = "quoted"
        elif is_on_wrote_header:
            on_wrote_started = True
            on_wrote_quote_seen = False
            kind = "quoted"
        elif explicit_history_started:
            # Headers identify an earlier message, but its unmarked body is not
            # reliable evidence that the current sender authored the text.
            kind = "quoted" if is_marked_quote else "uncertain"
        elif on_wrote_started:
            if is_marked_quote:
                on_wrote_quote_seen = True
                kind = "quoted"
            elif on_wrote_quote_seen:
                # A marked quote block after an attribution header gives us a
                # safe anchor for unmarked inline replies that follow it.
                kind = "authored"
            else:
                # An attribution header without a marked quote block leaves
                # plain text ambiguous, so keep it out of authored evidence.
                kind = "uncertain"
        elif is_marked_quote:
            # A marked quote line can appear between inline replies. It does
            # not make subsequent unmarked instructions historical.
            kind = "quoted"
        else:
            kind = "authored"

        classified.append((start, end, normalized_line, kind))

    return classified


def _merge_ranges(
    classified: list[tuple[int, int, str, _RangeKind]], kind: _RangeKind
) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    for start, end, _, line_kind in classified:
        if line_kind != kind or start == end:
            continue
        if ranges and ranges[-1]["end"] == start:
            ranges[-1]["end"] = end
        else:
            ranges.append({"start": start, "end": end})
    return ranges


def segment_authored_text_v1(raw_body: str) -> dict[str, object]:
    """Segment a raw message body into JSON-safe, end-exclusive raw ranges.

    Offsets are Python string indexes into ``raw_body`` (not byte offsets).
    Each line ending belongs to that line's category. The ranges across all
    four categories partition the complete body. Unmarked text after an
    explicit history header is marked uncertain so it cannot silently become
    current-sender evidence; an isolated ``>`` line does not start history.
    """
    classified = _classify_lines(raw_body)
    result: dict[str, object] = {
        "version": "authored-segmentation-v1",
        "offset_unit": "python_string_index",
        "raw_length": len(raw_body),
        "uncertain": any(kind == "uncertain" for _, _, _, kind in classified),
    }
    for kind in _KINDS:
        result[f"{kind}_ranges"] = _merge_ranges(classified, kind)
    return result


def split_authored_text(raw_body: str) -> tuple[str, str]:
    """Return normalized current text and the quoted/signature tail separately.

    This legacy tuple API now preserves unmarked inline replies after ``>``
    quote lines. Text following an explicit history header is conservatively
    excluded from current text and retained in the second tuple item.
    """
    classified = _classify_lines(raw_body)
    authored = "".join(
        raw_body[start:end] for start, end, _, kind in classified if kind == "authored"
    )
    quoted = "".join(
        raw_body[start:end] for start, end, _, kind in classified if kind != "authored"
    )
    return normalize_body_text(authored).strip(), normalize_body_text(quoted).strip()

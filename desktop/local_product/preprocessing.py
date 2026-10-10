"""Conservative authored-text isolation for display and rule candidates."""
from __future__ import annotations

import re


_DASHED_HISTORY = re.compile(r"^-{2,}\s*(?:original message|forwarded message|forwarded by)\b", re.I)
_ON_WROTE = re.compile(r"^on\s+.{4,}\s+wrote:\s*$", re.I)
_SIGNATURE = re.compile(r"^--\s*$")
_HEADER_FIELD = re.compile(r"^(?:from|sent|date|to|cc|subject):\s*\S", re.I)


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


def split_authored_text(raw_body: str) -> tuple[str, str]:
    """Return normalized current text and the quoted/signature tail separately.

    These boundaries are deliberately conservative. Unmarked quoted prose is
    ambiguous, so it remains in ``current_message`` for later human review.
    """
    normalized = normalize_body_text(raw_body)
    lines = normalized.split("\n")
    cutoff = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith(">")
            or _DASHED_HISTORY.match(stripped)
            or _ON_WROTE.match(stripped)
            or (index > 0 and _SIGNATURE.match(stripped))
            or _header_block_starts(lines, index)
        ):
            cutoff = index
            break
    authored = "\n".join(lines[:cutoff]).strip()
    quoted = "\n".join(lines[cutoff:]).strip() if cutoff < len(lines) else ""
    return authored, quoted

"""Conservative email-body normalization that leaves source text untouched."""

from __future__ import annotations

import re


_QUOTE_START = re.compile(
    r"^(?:"
    r"-{2,}\s*(?:original message|forwarded message|forwarded by)\b.*"
    r"|on .{4,}\s+wrote:\s*"
    r"|from:\s+\S.*"
    r")$",
    re.IGNORECASE,
)
_SIGNATURE_START = re.compile(r"^--\s*$")


def normalize_line_endings(text: str) -> str:
    """Normalize transport whitespace without removing message content."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return text


def clean_email_body(raw_body: str) -> tuple[str, str]:
    """Return (normalized full body, conservative current-message text).

    The full decoded body is retained in ``clean_body``. Only the derived
    ``current_message`` stops at well-known quote/signature boundaries; the
    caller must preserve ``raw_body`` separately.
    """
    clean_body = normalize_line_endings(raw_body)
    lines = clean_body.split("\n")
    cutoff = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if index > 0 and (
            stripped.startswith(">")
            or _QUOTE_START.match(stripped)
            or _SIGNATURE_START.match(stripped)
        ):
            cutoff = index
            break
    current_message = "\n".join(lines[:cutoff]).strip()
    return clean_body, current_message

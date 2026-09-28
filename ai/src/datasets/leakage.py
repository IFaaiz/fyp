"""Conservative fingerprints and duplicate checks for cross-source leakage."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from typing import Sequence


BODY_MIN_CHARS = 80
BODY_MIN_TOKENS = 12
NEAR_MIN_CHARS = 120
NEAR_MIN_TOKENS = 20
NEAR_MIN_LENGTH_RATIO = 0.90
NEAR_MIN_SHINGLE_JACCARD = 0.92
NEAR_SHINGLE_SIZE = 5
NEAR_MAX_TOKENS = 4000
MAX_NEAR_SUBJECT_GROUP = 40

_WORD_RE = re.compile(r"(?u)[^\W_]+")
_REPLY_PREFIX_RE = re.compile(r"^(?:(?:re|fw|fwd|aw|sv)\s*:\s*)+", re.IGNORECASE)


def normalize_body(text: str | None) -> str:
    """Normalize Unicode, case, and whitespace while preserving punctuation."""
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(normalized.split())


def normalize_tokens(text: str | None) -> tuple[str, ...]:
    """Return ordered alphanumeric tokens, ignoring punctuation and spacing."""
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return tuple(_WORD_RE.findall(normalized))


def normalize_subject(text: str | None) -> str:
    """Normalize a subject and remove only leading reply/forward prefixes."""
    normalized = unicodedata.normalize("NFKC", text or "").casefold().strip()
    previous = None
    while normalized != previous:
        previous = normalized
        normalized = _REPLY_PREFIX_RE.sub("", normalized).strip()
    return " ".join(_WORD_RE.findall(normalized))


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class ContentFingerprints:
    body_exact: str | None
    body_tokens: str | None
    body_compact: str | None
    subject_body: str | None
    short_body_exact: str | None
    short_body_tokens: str | None
    normalized_subject: str
    normalized_body: str
    token_text: str
    body_char_count: int
    token_count: int
    eligible: bool


def fingerprint_content(subject: str | None, body: str | None) -> ContentFingerprints:
    """Build privacy-safe hashes; short/generic bodies never become link keys."""
    normalized_body = normalize_body(body)
    tokens = normalize_tokens(body)
    token_text = " ".join(tokens)
    compact_token_text = "".join(tokens)
    normalized_subject = normalize_subject(subject)
    eligible = (
        len(normalized_body) >= BODY_MIN_CHARS
        and len(tokens) >= BODY_MIN_TOKENS
    )

    body_exact = _digest(normalized_body) if eligible else None
    body_tokens = _digest(token_text) if eligible else None
    body_compact = _digest(compact_token_text) if eligible else None
    subject_body = (
        _digest(normalized_subject + "\0" + compact_token_text)
        if eligible and normalized_subject
        else None
    )
    short_body_exact = (
        _digest(normalized_body) if normalized_body and not eligible else None
    )
    short_body_tokens = (
        _digest(token_text) if tokens and not eligible else None
    )

    return ContentFingerprints(
        body_exact=body_exact,
        body_tokens=body_tokens,
        body_compact=body_compact,
        subject_body=subject_body,
        short_body_exact=short_body_exact,
        short_body_tokens=short_body_tokens,
        normalized_subject=normalized_subject,
        normalized_body=normalized_body,
        token_text=token_text,
        body_char_count=len(normalized_body),
        token_count=len(tokens),
        eligible=eligible,
    )


def shingle_jaccard(
    left: Sequence[str],
    right: Sequence[str],
    *,
    shingle_size: int = NEAR_SHINGLE_SIZE,
) -> float:
    """Measure ordered token-shingle overlap for conservative near matching."""
    if shingle_size < 1:
        raise ValueError("shingle_size must be positive")
    if len(left) < shingle_size or len(right) < shingle_size:
        return 0.0
    left_shingles = {
        tuple(left[index:index + shingle_size])
        for index in range(len(left) - shingle_size + 1)
    }
    right_shingles = {
        tuple(right[index:index + shingle_size])
        for index in range(len(right) - shingle_size + 1)
    }
    union = left_shingles | right_shingles
    if not union:
        return 0.0
    return len(left_shingles & right_shingles) / len(union)


def is_near_duplicate(
    subject_left: str | None,
    body_left: str | None,
    subject_right: str | None,
    body_right: str | None,
) -> tuple[bool, float]:
    """Return a same-subject, high-overlap body match and its shingle score.

    This intentionally detects only small edits with stable subject and body
    length. It is not a semantic similarity test.
    """
    left = fingerprint_content(subject_left, body_left)
    right = fingerprint_content(subject_right, body_right)
    if (
        not left.eligible
        or not right.eligible
        or left.body_char_count < NEAR_MIN_CHARS
        or right.body_char_count < NEAR_MIN_CHARS
        or left.token_count < NEAR_MIN_TOKENS
        or right.token_count < NEAR_MIN_TOKENS
        or left.token_count > NEAR_MAX_TOKENS
        or right.token_count > NEAR_MAX_TOKENS
        or not left.normalized_subject
        or left.normalized_subject != right.normalized_subject
        or left.body_tokens == right.body_tokens
    ):
        return False, 0.0

    length_ratio = min(left.token_count, right.token_count) / max(
        left.token_count, right.token_count
    )
    if length_ratio < NEAR_MIN_LENGTH_RATIO:
        return False, 0.0

    score = shingle_jaccard(
        normalize_tokens(body_left),
        normalize_tokens(body_right),
    )
    return score >= NEAR_MIN_SHINGLE_JACCARD, score


__all__ = [
    "BODY_MIN_CHARS",
    "BODY_MIN_TOKENS",
    "MAX_NEAR_SUBJECT_GROUP",
    "NEAR_MAX_TOKENS",
    "ContentFingerprints",
    "fingerprint_content",
    "is_near_duplicate",
    "normalize_body",
    "normalize_subject",
    "normalize_tokens",
    "shingle_jaccard",
]

"""Conservative RFC 822 thread linking and bounded context construction."""

from __future__ import annotations

import hashlib
import math
from bisect import bisect_left
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def normalize_message_id(value: str | None) -> str:
    """Normalize a Message-ID value for linking across folded headers."""
    if not value:
        return ""
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    return value.strip().casefold()


def _sort_timestamp(value: str | None) -> float:
    if not value:
        return math.inf
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return math.inf


def assign_thread_metadata(
    messages: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, int]]:
    """Map email IDs to (thread ID, turn index).

    Only explicit RFC 822 ``In-Reply-To`` and ``References`` links are used.
    Messages with no resolvable links remain singleton threads; matching by
    subject alone would join unrelated conversations that reuse common titles.
    References to messages absent from a selected subset are retained as
    temporary anchors, so two replies to the same missing parent can still be
    linked.
    """
    rows = list(messages)
    count = len(rows)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    message_ids: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        message_id = normalize_message_id(row.get("message_id"))
        if message_id:
            message_ids.setdefault(message_id, []).append(index)
    for duplicate_indices in message_ids.values():
        for duplicate_index in duplicate_indices[1:]:
            union(duplicate_indices[0], duplicate_index)

    external_reference_owner: dict[str, int] = {}
    for index, row in enumerate(rows):
        references = list(row.get("references", ()))
        in_reply_to = list(row.get("in_reply_to", ()))
        for reference in (*references, *in_reply_to):
            normalized = normalize_message_id(str(reference))
            if not normalized:
                continue
            linked_indices = message_ids.get(normalized)
            if linked_indices:
                for linked_index in linked_indices:
                    union(index, linked_index)
            elif normalized in external_reference_owner:
                union(index, external_reference_owner[normalized])
            else:
                external_reference_owner[normalized] = index

    groups: dict[int, list[int]] = {}
    for index in range(count):
        groups.setdefault(find(index), []).append(index)

    result: dict[str, tuple[str, int]] = {}
    for indices in groups.values():
        ordered = sorted(
            indices,
            key=lambda index: (
                _sort_timestamp(rows[index].get("sent_at")),
                str(rows[index].get("source_path", "")).casefold(),
                str(rows[index].get("email_id", "")),
            ),
        )
        member_ids = sorted(str(rows[index]["email_id"]) for index in indices)
        thread_digest = hashlib.sha256("\n".join(member_ids).encode("utf-8")).hexdigest()[:20]
        thread_id = f"enron-thread-{thread_digest}"
        for turn_index, index in enumerate(ordered):
            result[str(rows[index]["email_id"])] = (thread_id, turn_index)
    return result


def append_thread_context(
    previous_context: str,
    *,
    sender: str,
    sent_at: str | None,
    subject: str,
    current_message: str,
    max_chars: int = 6000,
) -> str:
    """Append one message to the context for later turns, retaining a tail."""
    if max_chars <= 0:
        return ""
    details = [f"From: {sender}" if sender else "From: (unknown sender)"]
    if sent_at:
        details.append(f"Date: {sent_at}")
    if subject:
        details.append(f"Subject: {subject}")
    if current_message:
        details.append(current_message)
    snippet = "\n".join(details)
    combined = f"{previous_context}\n\n{snippet}" if previous_context else snippet
    return combined[-max_chars:]



_SUBJECT_REPLY_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd)\s*:\s*)+", re.I)
_EMAIL_ADDRESS = re.compile(r"[a-z0-9.!#$%&'*+/=?^_{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.I)


def _heuristic_subject(value: Any) -> str:
    value = str(value or "").strip()
    value = _SUBJECT_REPLY_PREFIX.sub("", value)
    return " ".join(value.split()).casefold()


def _heuristic_addresses(values: Any) -> set[str]:
    if isinstance(values, str):
        values = [values]
    result: set[str] = set()
    for value in values or ():
        result.update(address.casefold() for address in _EMAIL_ADDRESS.findall(str(value)))
    return result


def _heuristic_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError, OverflowError):
        return None


def suggest_secondary_thread_links(
    messages: Iterable[Mapping[str, Any]],
    *,
    max_gap_days: int = 7,
    max_subject_bucket_size: int = 100,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Suggest conservative subject/participant links without changing canonical IDs.

    A pair needs the same normalized subject (at least three words and 16
    characters), a later Re: message within max_gap_days, different senders,
    reciprocal sender/recipient-or-cc matches, and singleton canonical thread
    IDs. Any message with multiple possible partner edges is excluded. Buckets
    larger than max_subject_bucket_size are skipped to avoid common-subject
    joins and unbounded work. Rule confidence is uncalibrated and is not
    recovered RFC 822 threading.
    """
    if max_gap_days < 0:
        raise ValueError("max_gap_days must be nonnegative")
    if max_subject_bucket_size < 2:
        raise ValueError("max_subject_bucket_size must be at least 2")

    rows = list(messages)
    canonical_sizes: dict[str, int] = defaultdict(int)
    for row in rows:
        thread_id = str(row.get("thread_id", "") or "")
        if thread_id:
            canonical_sizes[thread_id] += 1

    buckets: dict[str, list[int]] = defaultdict(list)
    senders: dict[int, str] = {}
    participants: dict[int, set[str]] = {}
    sent_at: dict[int, datetime] = {}
    for index, row in enumerate(rows):
        thread_id = str(row.get("thread_id", "") or "")
        subject = _heuristic_subject(row.get("subject"))
        if (
            not thread_id
            or canonical_sizes[thread_id] != 1
            or len(subject) < 16
            or len(subject.split()) < 3
        ):
            continue
        sender_addresses = _heuristic_addresses([row.get("sender")])
        timestamp = _heuristic_timestamp(row.get("sent_at"))
        if len(sender_addresses) != 1 or not timestamp:
            continue
        senders[index] = next(iter(sender_addresses))
        participants[index] = _heuristic_addresses(
            list(row.get("recipients") or ()) + list(row.get("cc") or ())
        )
        sent_at[index] = timestamp
        buckets[subject].append(index)

    edges: list[tuple[int, int]] = []
    oversized_buckets = 0
    oversized_records = 0
    max_gap = max_gap_days * 86400
    for indices in buckets.values():
        if len(indices) > max_subject_bucket_size:
            oversized_buckets += 1
            oversized_records += len(indices)
            continue

        # Index each earlier sender and the participant addresses they sent to.
        # A later sender can only pair with an earlier record addressed to them.
        earlier_by_sender_pair: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
        for earlier_index in indices:
            earlier_sender = senders[earlier_index]
            for recipient in participants[earlier_index]:
                earlier_by_sender_pair[(earlier_sender, recipient)].append(
                    (sent_at[earlier_index].timestamp(), earlier_index)
                )
        sorted_entries = {}
        for key, entries in earlier_by_sender_pair.items():
            entries.sort()
            sorted_entries[key] = (entries, [item[0] for item in entries])

        for later_index in indices:
            later = rows[later_index]
            if not re.match(r"^\s*re\s*:", str(later.get("subject", "")), re.I):
                continue
            later_sender = senders[later_index]
            later_time = sent_at[later_index]
            later_participants = participants[later_index]
            for earlier_sender in later_participants:
                if earlier_sender == later_sender:
                    continue
                indexed = sorted_entries.get((earlier_sender, later_sender))
                if not indexed:
                    continue
                entries, timestamps = indexed
                earliest = bisect_left(timestamps, later_time.timestamp() - max_gap)
                latest = bisect_left(timestamps, later_time.timestamp())
                for _, earlier_index in entries[earliest:latest]:
                    if earlier_index != later_index:
                        edges.append((earlier_index, later_index))

    degree: dict[int, int] = defaultdict(int)
    for left, right in edges:
        degree[left] += 1
        degree[right] += 1
    suggestions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for left, right in edges:
        if degree[left] != 1 or degree[right] != 1:
            continue
        left_id = str(rows[left].get("email_id", ""))
        right_id = str(rows[right].get("email_id", ""))
        if not left_id or not right_id:
            continue
        pair = tuple(sorted((left_id, right_id)))
        if pair in seen:
            continue
        seen.add(pair)
        digest = hashlib.sha256("\n".join(pair).encode("utf-8")).hexdigest()[:20]
        suggestions.append({
            "secondary_thread_id": f"enron-heuristic-thread-{digest}",
            "email_ids": list(pair),
            "source_thread_ids": sorted({
                str(rows[left].get("thread_id", "")),
                str(rows[right].get("thread_id", "")),
            }),
            "thread_link_method": "heuristic_subject_reciprocal_participants_time",
            "confidence": "high_rule_match_uncalibrated",
            "confidence_basis": (
                "same normalized subject, later Re: within time window, reciprocal "
                "sender/recipient-or-cc match, unique one-to-one edge, canonical singletons"
            ),
            "max_gap_days": max_gap_days,
        })
    suggestions.sort(key=lambda item: item["email_ids"])
    if diagnostics is not None:
        eligible_rows = sum(len(indices) for indices in buckets.values())
        diagnostics.update({
            "eligible_singleton_rows": eligible_rows,
            "normalized_subject_buckets": len(buckets),
            "considered_subject_buckets": len(buckets) - oversized_buckets,
            "oversized_subject_buckets_skipped": oversized_buckets,
            "oversized_subject_records_skipped": oversized_records,
            "reciprocal_candidate_edges": len(edges),
            "one_to_one_suggested_pairs": len(suggestions),
            "one_to_one_suggested_records": 2 * len(suggestions),
            "one_to_one_coverage_of_eligible_rows": (
                (2 * len(suggestions) / eligible_rows) if eligible_rows else 0.0
            ),
            "max_subject_bucket_size": max_subject_bucket_size,
            "max_gap_days": max_gap_days,
        })
    return suggestions

def apply_secondary_thread_suggestions(
    messages: Iterable[Mapping[str, Any]],
    suggestions: Iterable[Mapping[str, Any]],
    *,
    max_context_chars: int = 6000,
) -> list[dict[str, Any]]:
    """Return derived copies grouped by suggestions, preserving source thread IDs."""
    rows = [dict(row) for row in messages]
    by_id = {str(row.get("email_id", "")): row for row in rows}
    links_by_id: dict[str, Mapping[str, Any]] = {}
    for suggestion in suggestions:
        ids = list(suggestion.get("email_ids") or ())
        if len(ids) != 2:
            continue
        for email_id in ids:
            links_by_id[str(email_id)] = suggestion

    result = []
    for row in rows:
        email_id = str(row.get("email_id", ""))
        suggestion = links_by_id.get(email_id)
        if not suggestion:
            result.append(row)
            continue
        pair_ids = list(suggestion.get("email_ids") or ())
        partner_id = next((str(item) for item in pair_ids if str(item) != email_id), "")
        partner = by_id.get(partner_id)
        row["source_thread_id"] = str(row.get("thread_id", "") or "")
        row["thread_id"] = str(suggestion["secondary_thread_id"])
        row["thread_link_method"] = "heuristic"
        row["thread_link_confidence"] = "high_unverified"
        row["thread_link_confidence_basis"] = str(suggestion.get("confidence_basis", ""))
        row["thread_link_partner_email_id"] = partner_id
        if partner:
            own_at = _heuristic_timestamp(row.get("sent_at"))
            partner_at = _heuristic_timestamp(partner.get("sent_at"))
            if own_at and partner_at and partner_at < own_at:
                row["thread_context"] = append_thread_context(
                    str(row.get("thread_context") or ""),
                    sender=str(partner.get("sender") or ""),
                    sent_at=partner.get("sent_at"),
                    subject=str(partner.get("subject") or ""),
                    current_message=str(partner.get("current_message") or ""),
                    max_chars=max_context_chars,
                )
                row["turn_index"] = 1
            else:
                row["turn_index"] = 0
        result.append(row)
    return result

"""Deterministic, thread-aware candidate sampling; matches are not labels."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .schemas import read_jsonl
from .threading import apply_secondary_thread_suggestions, suggest_secondary_thread_links

REPO_ROOT = Path(__file__).resolve().parents[3]

_PATTERNS = tuple((n, re.compile(p, re.I)) for n, p in (
    ("meeting", r"\b(?:meetings?|mtgs?\.?)\b"), ("schedule", r"\bschedul(?:e|ed|ing|es)\b"),
    ("reschedule", r"\breschedul(?:e|ed|ing|es)\b"), ("agenda", r"\bagenda\b"),
    ("minutes", r"\bminutes?\b|\bmom\b"), ("deadline", r"\bdeadlines?\b"),
    ("due", r"\bdue\s+(?:date|by|on|before|today|tomorrow|immediately|asap|monday|tuesday|wednesday|thursday|friday|saturday|sunday|(?:\d{1,2})(?:st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|no later than|in\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:hours?|days?|weeks?))\b|\bis\s+due\s+(?:on|by|at|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|(?:\d{1,2})(?:st|nd|rd|th)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"), ("submit", r"\bsubmit(?:s|ted|ting)?\b"),
    ("report", r"\breports?\b"), ("presentation", r"\bpresentations?\b"),
    ("approval", r"\bapprov(?:e|es|ed|al|ing)\b"),
    ("review", r"\breviews?\b|\breviewing\b|\breviewed\b"),
    ("follow_up", r"\bfollow[ -]?up\b"), ("reminder", r"\breminders?\b|\bremind\b"),
    ("input", r"\binputs?\b"), ("action_item", r"\baction items?\b"),
    ("action", r"\bactions?\b"), ("task", r"\btasks?(?!\s+force)\b|\bto[- ]do\b"),
    ("assigned", r"\bassign(?:s|ed|ment|ments|ing)?\b"), ("pending", r"\bpending\b"),
    ("update", r"\bupdates?\b|\bupdated\b"),
    ("attached", r"\battachments?\b|\battached\b"),
    ("send", r"\bsend(?:s|ing|t)?\b"), ("provide", r"\bprovid(?:e|es|ed|ing)\b"),
    ("complete", r"\bcomplet(?:e|es|ed|ing|ion)\b"),
))
ORDER = {name: i for i, (name, _) in enumerate(_PATTERNS)}
CATEGORY_ORDER = (
    "meeting", "deadline", "report_doc", "department_input", "follow_up",
    "approval", "update", "action_task",
)
CATEGORY_LABELS = {
    "meeting": "Meeting", "deadline": "Deadline", "report_doc": "Report / document",
    "department_input": "Department / input", "follow_up": "Follow-up",
    "approval": "Approval", "update": "Update", "action_task": "Action / task",
    "random": "Random",
}
_CUE_CATEGORY = {
    "meeting": "meeting", "schedule": "meeting", "reschedule": "meeting",
    "agenda": "meeting", "minutes": "meeting",
    "deadline": "deadline", "due": "deadline",
    "report": "report_doc", "submit": "report_doc", "presentation": "report_doc",
    "attached": "report_doc", "provide": "report_doc",
    "input": "department_input",
    "follow_up": "follow_up", "reminder": "follow_up", "send": "follow_up",
    "approval": "approval", "review": "approval",
    "update": "update",
    "action_item": "action_task", "action": "action_task", "task": "action_task",
    "assigned": "action_task", "pending": "action_task", "complete": "action_task",
}
_CATEGORY_ORDER = {name: i for i, name in enumerate((*CATEGORY_ORDER, "random"))}


def _categories(cues: Iterable[str]) -> tuple[str, ...]:
    found = {_CUE_CATEGORY[cue] for cue in cues if cue in _CUE_CATEGORY}
    return tuple(category for category in CATEGORY_ORDER if category in found)


_QUOTE_BOUNDARIES = tuple(re.compile(p, re.I) for p in (
    r"^\s*-{2,}\s*(?:original message|forwarded message|forwarded by)\b",
    r"^\s*begin forwarded message\s*:?\s*$",
    r"^\s*on .{4,}\s+wrote\s*:\s*$",
    r"^\s*from:\s+\S",
    r"^\s*>+",
    r"^\s*_{6,}\s*$",
))

_WEAK_CUES = frozenset({"report", "update", "attached", "send", "provide", "complete", "input"})
_EMPTY_BODY_SUBJECT_CUES = frozenset({
    "meeting", "schedule", "reschedule", "agenda", "deadline", "due", "submit",
    "follow_up", "reminder", "action_item", "action", "task", "assigned", "pending",
})
_ACTION_CONTEXT = re.compile(
    r"\b(?:can|could|would|will)\s+you\b|"
    r"\bi\s+need(?:s|ed)?\s+you\s+to\b|"
    r"\b(?:need(?:s|ed)?|must|should)\s+(?:you\s+)?(?:to\s+)?|"
    r"\b(?:assigned\s+to|responsible\s+for|action\s+required)\b|"
    r"\bby\s+(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}(?:st|nd|rd|th)?)\b|"
    r"\bplease\s+(?!(?:do\s+not|don't|note\b|be\s+advised|feel\s+free|"
    r"don't\s+hesitate|do\s+not\s+hesitate|read\b|click\b|visit\b|unsubscribe\b))\w+\b",
    re.I,
)
_SUBJECT_TASK_CONTEXT = re.compile(
    r"\b(?:action\s+required|approval\s+(?:required|needed|requested)|"
    r"request\s+for\s+approval|review\s+(?:required|requested)|"
    r"task\s+assigned|assigned\s+to|due\s+date|deadline)\b", re.I,
)
_AUTOMATED_OR_BULK = re.compile(
    r"\b(?:newsletter|(?:daily|weekly|monthly)\s+(?:briefing|news|update|report|digest)|"
    r"news\s+(?:update|for)|what's\s+new|press\s+release|stock\s+quote|earnings\s+report|"
    r"automated\s+message|do\s+not\s+(?:reply|respond)|unsubscribe|mailing\s+list|"
    r"discussion\s+list|remove\s+me\s+from\s+(?:your\s+)?(?:email\s+)?list|"
    r"you\s+are\s+receiving\s+this\s+(?:email|message)|special\s+offer|click\s+here)\b",
    re.I,
)
_AUTOMATED_SENDER = re.compile(
    r"(?:^|[._+\-])(?:no.?reply|noreply|mailbot|listserv|mailer|announc(?:e|ement|ements)?|"
    r"news(?:letter)?|digest|owner)(?:[._+\-]|@)", re.I,
)



@dataclass(frozen=True)
class Info:
    email_id: str
    thread_id: str
    turn: int
    sender: str
    direct: tuple[str, ...]
    context: tuple[str, ...]
    rank: int

    @property
    def cues(self) -> tuple[str, ...]:
        return tuple(n for n, _ in _PATTERNS if n in self.direct or n in self.context)

    @property
    def categories(self) -> tuple[str, ...]:
        return _categories(self.cues)

    @property
    def direct_categories(self) -> tuple[str, ...]:
        return _categories(self.direct)

    @property
    def context_categories(self) -> tuple[str, ...]:
        return _categories(self.context)

    @property
    def context_only(self) -> bool:
        return not self.direct and bool(self.context)


@dataclass
class Index:
    input_count: int
    candidates: list[Info]
    by_id: dict[str, Info]
    thread_sizes: Counter[str]
    candidate_threads: set[str]
    negatives: list[Info]
    direct_counts: Counter[str]
    context_counts: Counter[str]
    direct_category_counts: Counter[str]
    context_category_counts: Counter[str]
    senders: Counter[str]
    cue_recall_risk: dict[str, Any]


def _secondary_link_metadata(
    source: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """Find conservative links and retain enriched full rows only for suggested pairs."""
    keys = ("email_id", "thread_id", "subject", "sent_at", "sender", "recipients", "cc")
    link_rows = [
        {key: row.get(key) for key in keys}
        for row in read_jsonl(source)
    ]
    diagnostics: dict[str, Any] = {}
    suggestions = suggest_secondary_thread_links(link_rows, diagnostics=diagnostics)
    linked_ids = {email_id for item in suggestions for email_id in item["email_ids"]}
    if not linked_ids:
        return suggestions, {}, diagnostics
    pair_records = [
        row for row in read_jsonl(source)
        if str(row.get("email_id", "")) in linked_ids
    ]
    derived = apply_secondary_thread_suggestions(pair_records, suggestions)
    return suggestions, {str(row["email_id"]): row for row in derived}, diagnostics


def _derived_row(row: dict[str, Any], derived_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return derived_rows.get(str(row.get("email_id", "")), row)


def _linking_stats(
    suggestions: list[dict[str, Any]],
    enabled: bool,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "enabled": enabled,
        "suggested_pairs": len(suggestions) if enabled else 0,
        "suggested_records": 2 * len(suggestions) if enabled else 0,
        "method": "heuristic_subject_reciprocal_participants_time" if enabled else None,
        "confidence": "high_unverified" if enabled else None,
        "confidence_calibrated": False,
        "source_canonical_records_changed": False,
    }
    if enabled:
        result.update(diagnostics or {})
    return result


def _rank(seed: int, value: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}\0{value}".encode()).digest()[:8], "big")


def _before_quoted_content(text: str) -> str:
    """Keep only the authored prefix before a quoted or forwarded block."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    for index, line in enumerate(lines):
        if any(pattern.search(line) for pattern in _QUOTE_BOUNDARIES):
            return "\n".join(lines[:index]).strip()
    return normalized.strip()


def _cues(text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _PATTERNS if pattern.search(text))


def _useful_cues(subject: str, body: str, sender: str = "") -> tuple[str, ...]:
    """Apply conservative precision guards without treating cues as labels."""
    cues = set(_cues(subject)) | set(_cues(body))
    if not cues:
        return ()

    action_context = bool(_ACTION_CONTEXT.search(body)) or bool(_ACTION_CONTEXT.search(subject))
    subject_task_context = bool(_SUBJECT_TASK_CONTEXT.search(subject))
    if not body and not action_context and not subject_task_context:
        cues.intersection_update(_EMPTY_BODY_SUBJECT_CUES)

    # Broad terms alone catch ordinary reports, updates, and courtesy text.
    strong = cues - _WEAK_CUES
    if not strong and not action_context and not subject_task_context:
        cues.difference_update(_WEAK_CUES)

    # Ignore clear digests, mailing-list notices, and no-reply alerts unless
    # they contain an actual request or assignment for the recipient.
    is_bulk = bool(_AUTOMATED_OR_BULK.search(subject + "\n" + body))
    is_automated_sender = bool(_AUTOMATED_SENDER.search(sender))
    if (is_bulk or is_automated_sender) and not action_context and not subject_task_context:
        cues.clear()
    return tuple(name for name, _ in _PATTERNS if name in cues)


def _info(row: dict[str, Any], seed: int, fallback: str = "") -> Info:
    subject = str(row.get("subject", "") or "")
    body = _before_quoted_content(str(row.get("current_message", "") or ""))
    direct = _useful_cues(subject, body, str(row.get("sender", "") or ""))
    context_text = str(row.get("thread_context", "") or "")
    # Canonical thread context is built from already-cleaned prior messages and
    # begins with a synthetic From/Date/Subject header for each message.
    context = _cues(context_text)
    email_id = str(row.get("email_id") or fallback)
    thread_id = str(row.get("thread_id") or f"singleton:{email_id}")
    try:
        turn = int(row.get("turn_index", 0))
    except (TypeError, ValueError):
        turn = 0
    return Info(email_id, thread_id, turn, str(row.get("sender", "") or ""),
                direct, context, _rank(seed, email_id))


def candidate_reasons(record: dict[str, Any]) -> list[str]:
    """Return heuristic cue names; they are sampling signals, never labels."""
    return list(_info(record, 0).cues)


def is_keyword_candidate(record: dict[str, Any]) -> bool:
    return bool(candidate_reasons(record))


def _index(rows: Iterable[dict[str, Any]], seed: int, random_capacity: int) -> Index:
    candidates, by_id = [], {}
    sizes, candidate_threads = Counter(), set()
    direct_counts, context_counts = Counter(), Counter()
    direct_category_counts, context_category_counts, senders = Counter(), Counter(), Counter()
    heap: list[tuple[int, str, Info]] = []
    total = 0
    risk = {
        "nonempty_current_message_empty_authored_prefix": 0,
        "raw_keyword_hit_records": 0,
        "post_trim_guarded_candidate_records": 0,
        "records_losing_any_cue_at_quote_trim": 0,
        "cue_instances_lost_at_quote_trim": Counter(),
        "records_losing_any_cue_at_precision_guard": 0,
        "cue_instances_suppressed_by_precision_guard": Counter(),
    }
    for line_no, row in enumerate(rows, 1):
        total += 1
        subject = str(row.get("subject", "") or "")
        raw_body = str(row.get("current_message", "") or "")
        authored_body = _before_quoted_content(raw_body)
        if raw_body.strip() and not authored_body:
            risk["nonempty_current_message_empty_authored_prefix"] += 1
        raw_cues = set(_cues(subject + "\n" + raw_body))
        trimmed_cues = set(_cues(subject + "\n" + authored_body))
        info = _info(row, seed, f"row-{line_no}")
        if raw_cues:
            risk["raw_keyword_hit_records"] += 1
        if info.direct:
            risk["post_trim_guarded_candidate_records"] += 1
        quote_lost = raw_cues - trimmed_cues
        guard_lost = trimmed_cues - set(info.direct)
        if quote_lost:
            risk["records_losing_any_cue_at_quote_trim"] += 1
            risk["cue_instances_lost_at_quote_trim"].update(quote_lost)
        if guard_lost:
            risk["records_losing_any_cue_at_precision_guard"] += 1
            risk["cue_instances_suppressed_by_precision_guard"].update(guard_lost)
        sizes[info.thread_id] += 1
        senders[info.sender or "(unknown)"] += 1
        if info.direct or info.context:
            candidates.append(info)
            by_id[info.email_id] = info
            candidate_threads.add(info.thread_id)
            direct_counts.update(info.direct)
            context_counts.update(info.context)
            direct_category_counts.update(info.direct_categories)
            context_category_counts.update(info.context_categories)
        elif random_capacity:
            item = (-info.rank, info.email_id, info)
            if len(heap) < random_capacity:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    negatives = sorted((x[2] for x in heap), key=lambda x: (x.rank, x.email_id))
    risk_summary = {
        **{key: value for key, value in risk.items() if not isinstance(value, Counter)},
        "cue_instances_lost_at_quote_trim": dict(risk["cue_instances_lost_at_quote_trim"]),
        "cue_instances_suppressed_by_precision_guard": dict(
            risk["cue_instances_suppressed_by_precision_guard"]
        ),
        "interpretation": (
            "Quoted/forwarded cue losses are intentional and can omit tasks stated only "
            "in quoted text; precision guards can suppress implicit or subject-only tasks; "
            "these are not known false negatives."
        ),
    }
    return Index(total, candidates, by_id, sizes, candidate_threads, negatives,
                 direct_counts, context_counts, direct_category_counts,
                 context_category_counts, senders, risk_summary)


def _primary(info: Info, counts: Counter[str]) -> str:
    return min(info.direct or info.context, key=lambda c: (counts[c], ORDER[c]))


def _primary_category(info: Info, counts: Counter[str]) -> str:
    categories = info.direct_categories or info.context_categories
    return min(categories, key=lambda c: (counts[c], _CATEGORY_ORDER[c]))


def _pick(
    groups: dict[str, list[Info]], count: int,
    prior_counts: Counter[str] | None = None,
) -> list[Info]:
    groups = {c: sorted(rows, key=lambda x: (x.rank, x.email_id))
              for c, rows in groups.items() if rows}
    limit = min(max(count, 0), sum(len(x) for x in groups.values()))
    prior_counts = prior_counts or Counter()
    heap: list[tuple[int, int, str, int]] = []
    for category, rows in groups.items():
        heapq.heappush(heap, (prior_counts[category], _CATEGORY_ORDER[category], category, 0))
    result = []
    while heap and len(result) < limit:
        _, order, category, offset = heapq.heappop(heap)
        rows = groups[category]
        result.append(rows[offset])
        offset += 1
        if offset < len(rows):
            heapq.heappush(heap, (prior_counts[category] + offset, order, category, offset))
    return result


def _groups(rows: Iterable[Info], counts: Counter[str], context_only: bool) -> dict[str, list[Info]]:
    groups: dict[str, list[Info]] = defaultdict(list)
    for info in rows:
        if info.context_only == context_only and (info.direct or info.context):
            groups[_primary_category(info, counts)].append(info)
    return dict(groups)


def _take_candidates(index: Index, excluded: set[str], count: int) -> list[Info]:
    rows = [x for x in index.candidates if x.email_id not in excluded]
    direct = [x for x in rows if x.direct]
    contextual = [x for x in rows if x.context_only]
    context_n = min(len(contextual), round(count * .2))
    direct_n = min(len(direct), count - context_n)
    context_n = min(len(contextual), count - direct_n)
    direct_n = min(len(direct), count - context_n)
    prior_counts = Counter()
    for email_id in excluded:
        info = index.by_id.get(email_id)
        if info:
            counts = index.direct_category_counts if info.direct else index.context_category_counts
            prior_counts[_primary_category(info, counts)] += 1
    picked = _pick(_groups(direct, index.direct_category_counts, False), direct_n, prior_counts)
    for info in picked:
        prior_counts[_primary_category(info, index.direct_category_counts)] += 1
    contextual_picked = _pick(
        _groups(contextual, index.context_category_counts, True), context_n, prior_counts
    )
    picked += contextual_picked
    for info in contextual_picked:
        prior_counts[_primary_category(info, index.context_category_counts)] += 1
    if len(picked) < count:
        omitted = excluded | {x.email_id for x in picked}
        rest = [x for x in rows if x.email_id not in omitted]
        extra_context = [x for x in rest if x.context_only]
        more_context = _pick(
            _groups(extra_context, index.context_category_counts, True),
            count - len(picked), prior_counts,
        )
        picked += more_context
        for info in more_context:
            prior_counts[_primary_category(info, index.context_category_counts)] += 1
        omitted |= {x.email_id for x in picked}
        rest = [x for x in rest if x.email_id not in omitted]
        picked += _pick(
            _groups(rest, index.direct_category_counts, False),
            count - len(picked), prior_counts,
        )
    return picked


def _fit_seed(index: Index, target: int, random_count: int) -> tuple[dict[str, str], int, int]:
    negative_goal = min(target, random_count)
    reserve = min(max(0, target - negative_goal), target // 8)
    picked = _take_candidates(index, set(), max(0, target - negative_goal - reserve))
    return ({x.email_id: "direct_match" if x.direct else "thread_context_match"
             for x in picked}, negative_goal, reserve)


def _expand_fit(
    index: Index, selected: dict[str, str], members: dict[str, list[Info]],
    target: int, negative_goal: int, reserve: int,
) -> tuple[dict[str, str], dict[str, Info]]:
    seed_ids = set(selected)
    seed_threads = {index.by_id[e].thread_id for e in seed_ids if e in index.by_id}
    thread_options = []
    for tid in seed_threads:
        rows = members.get(tid, [])
        turns = [x.turn for x in rows if x.email_id in seed_ids]
        if not turns:
            continue
        neighbors = [x for x in rows if x.email_id not in seed_ids]
        if not neighbors:
            continue
        direct_n = sum(bool(x.direct) for x in neighbors)
        min_rank = min(x.rank for x in neighbors)
        thread_options.append((len(neighbors), -direct_n, min_rank, tid, neighbors, turns))
    thread_options.sort()
    cap = max(0, target - negative_goal)
    room = min(reserve, max(0, cap - len(selected)))
    added = 0
    for missing, _, _, _, neighbors, turns in thread_options:
        if added >= room or len(selected) >= cap:
            break
        if missing <= room - added and missing <= cap - len(selected):
            for x in neighbors:
                selected[x.email_id] = "thread_expansion"
            added += missing
            continue
        # If a full thread cannot fit, use the remaining slots for its nearest
        # neighbors and preserve the partial-thread status in the sidecar.
        ordered = sorted(
            neighbors,
            key=lambda x: (
                0 if x.direct else 1 if x.context else 2,
                min(abs(x.turn - turn) for turn in turns),
                x.rank,
            ),
        )
        available = min(room - added, cap - len(selected))
        for x in ordered[:available]:
            selected[x.email_id] = "thread_expansion"
        added += min(available, len(ordered))
    extra = max(0, cap - len(selected))
    for x in _take_candidates(index, set(selected), extra):
        selected[x.email_id] = "direct_match" if x.direct else "thread_context_match"
    added_negatives = 0
    for x in index.negatives:
        if added_negatives >= negative_goal or len(selected) >= target:
            break
        if x.email_id not in selected:
            selected[x.email_id] = "random_nonmatching"
            added_negatives += 1
    info = dict(index.by_id)
    info.update({x.email_id: x for rows in members.values() for x in rows})
    info.update({x.email_id: x for x in index.negatives})
    return selected, {eid: info[eid] for eid in selected if eid in info}


def _whole_plan(index: Index, target: int, random_count: int, seed: int) -> dict[str, str]:
    by_thread: dict[str, list[Info]] = defaultdict(list)
    for x in index.candidates:
        by_thread[x.thread_id].append(x)
    strata: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for tid, rows in by_thread.items():
        direct = tuple(dict.fromkeys(c for x in rows for c in x.direct_categories))
        context = tuple(dict.fromkeys(c for x in rows for c in x.context_categories))
        categories = direct or context
        counts = index.direct_category_counts if direct else index.context_category_counts
        category = min(categories, key=lambda c: (counts[c], _CATEGORY_ORDER[c]))
        strata[category].append((_rank(seed, tid), tid))
    units = {c: [tid for _, tid in sorted(v)] for c, v in strata.items()}
    heap: list[tuple[float, int, str, int]] = []
    for cue, tids in units.items():
        heapq.heappush(heap, (0.0, _CATEGORY_ORDER[cue], cue, 0))
    candidate_target = max(0, target - min(target, random_count))
    picked, count = [], 0
    while heap and count < candidate_target:
        _, order, cue, offset = heapq.heappop(heap)
        tid = units[cue][offset]
        picked.append(tid)
        count += index.thread_sizes[tid]
        offset += 1
        if offset < len(units[cue]):
            heapq.heappush(heap, (offset, order, cue, offset))
    chosen_threads = set(picked)
    # Fill remaining capacity with deterministic no-cue whole threads.
    no_cue = [t for t in index.thread_sizes if t not in index.candidate_threads]
    no_cue.sort(key=lambda t: (_rank(seed, t), t))
    random_messages = 0
    for tid in no_cue:
        if count >= target or random_messages >= random_count:
            break
        chosen_threads.add(tid)
        size = index.thread_sizes[tid]
        count += size
        random_messages += size
    plan = {x.email_id: ("direct_match" if x.direct else "thread_context_match")
            for x in index.candidates if x.thread_id in chosen_threads}
    for tid in chosen_threads:
        plan[f"__thread__:{tid}"] = (
            "whole_candidate_thread" if tid in index.candidate_threads
            else "random_nonmatching_thread"
        )
    return plan


def _finish_whole(plan: dict[str, str], members: dict[str, list[Info]]) -> tuple[dict[str, str], dict[str, Info]]:
    units = {k.removeprefix("__thread__:"): v for k, v in plan.items()
             if k.startswith("__thread__:")}
    selected, infos = {}, {}
    for tid, rows in members.items():
        unit_reason = units.get(tid)
        if not unit_reason:
            continue
        for x in rows:
            if x.direct or x.context:
                reason = "direct_match" if x.direct else "thread_context_match"
            elif unit_reason == "random_nonmatching_thread":
                reason = "random_nonmatching"
            else:
                reason = "thread_expansion"
            selected[x.email_id] = reason
            infos[x.email_id] = x
    return selected, infos


def _distribution(values: Iterable[int]) -> dict[str, Any]:
    vals = sorted(values)
    if not vals:
        return {"min": 0, "median": 0, "p90": 0, "max": 0, "histogram": {}}
    hist = Counter(min(n, 20) for n in vals)
    def pct(p: float) -> int:
        return vals[max(0, math.ceil(len(vals) * p) - 1)]
    return {"min": vals[0], "median": pct(.5), "p90": pct(.9), "max": vals[-1],
            "histogram": {(f"{n}+" if n == 20 else str(n)): v for n, v in sorted(hist.items())}}


def _stats(index: Index, selected: dict[str, str], infos: dict[str, Info],
           target: int, random_count: int, seed: int, mode: str) -> dict[str, Any]:
    direct_sel, context_sel, senders, threads = Counter(), Counter(), Counter(), Counter()
    unique_available, unique_selected = Counter(), Counter()
    category_available, category_selected = Counter(), Counter()
    category_primary_available, category_primary_selected = Counter(), Counter()
    for x in index.candidates:
        unique_available.update(x.cues)
        category_available.update(x.categories)
        category_primary_available[_primary_category(
            x, index.direct_category_counts if x.direct else index.context_category_counts
        )] += 1
    for x in infos.values():
        direct_sel.update(x.direct)
        context_sel.update(x.context)
        unique_selected.update(x.cues)
        category_selected.update(x.categories)
        if x.direct or x.context:
            category_primary_selected[_primary_category(
                x, index.direct_category_counts if x.direct else index.context_category_counts
            )] += 1
        senders[x.sender or "(unknown)"] += 1
        threads[x.thread_id] += 1
    full = sum(threads[t] == index.thread_sizes[t] for t in threads)
    partial = len(threads) - full
    cues = {name: {
        "direct_available": index.direct_counts[name],
        "context_available": index.context_counts[name],
        "unique_available": unique_available[name],
        "direct_selected": direct_sel[name],
        "context_selected": context_sel[name],
        "unique_selected": unique_selected[name],
        "selected_total": unique_selected[name],
    } for name, _ in _PATTERNS}
    direct_available = sum(bool(x.direct) for x in index.candidates)
    context_available = sum(x.context_only for x in index.candidates)
    direct_selected = sum(bool(x.direct) for x in infos.values())
    context_only_selected = sum(x.context_only for x in infos.values())
    random_selected = sum(v == "random_nonmatching" for v in selected.values())
    expansion_selected = sum(v == "thread_expansion" for v in selected.values())
    category_counts = {
        category: {
            "available": (index.input_count - len(index.candidates)) if category == "random" else category_available[category],
            "selected": random_selected if category == "random" else category_selected[category],
            "primary_selected": random_selected if category == "random" else category_primary_selected[category],
        }
        for category in (*CATEGORY_ORDER, "random")
    }
    return {
        "input_records": index.input_count,
        "input_threads": len(index.thread_sizes),
        "keyword_candidates": len(index.candidates),
        "direct_candidates_available": direct_available,
        "context_only_candidates_available": context_available,
        "nonkeyword_available": index.input_count - len(index.candidates),
        "records_selected": len(infos),
        "selected_direct_matches": direct_selected,
        "selected_context_only_matches": context_only_selected,
        "selected_random_nonmatching": random_selected,
        "random_sample_selected": random_selected,
        "selected_thread_expansion": expansion_selected,
        "multi_cue_records": {
            "available": sum(len(x.cues) > 1 for x in index.candidates),
            "selected": sum(len(x.cues) > 1 for x in infos.values()),
        },
        "cue_counts": cues,
        "cue_recall_risk": index.cue_recall_risk,
        "sampling_category_counts": category_counts,
        "threads_selected": len(threads),
        "full_threads_selected": full,
        "partial_threads_selected": partial,
        "partial_thread_proportion": partial / len(threads) if threads else 0.0,
        "full_thread_proportion": full / len(threads) if threads else 0.0,
        "selected_record_proportion": len(infos) / index.input_count if index.input_count else 0.0,
        "input_thread_sizes": _distribution(index.thread_sizes.values()),
        "selected_thread_sizes": _distribution(threads.values()),
        "senders_input_top_50": dict(index.senders.most_common(50)),
        "senders_selected_top_50": dict(senders.most_common(50)),
        "target_count": target,
        "target_exceeded": max(0, len(infos) - target),
        "thread_mode": mode,
        "thread_cap_semantics": (
            "hard record cap; partial canonical thread-ID groups are marked in metadata"
            if mode == "fit" else
            "whole canonical thread-ID groups; target can be exceeded by complete selected groups"
        ),
        "thread_completeness_note": (
            "Complete means all input records sharing the canonical thread_id were selected; "
            "missing reply headers can leave related messages as singleton IDs."
        ),
        "random_sample_target": min(target, random_count),
        "seed": seed,
        "sampling_categories": [*CATEGORY_ORDER, "random"],
        "heuristics_are_labels": False,
        "labels_changed": False,
    }


def _metadata(x: Info, reason: str, selected_n: int, total_n: int,
              primary_cue: str, primary_category: str) -> dict[str, Any]:
    return {
        "email_id": x.email_id, "thread_id": x.thread_id,
        "cue_reasons": list(x.cues), "direct_cue_reasons": list(x.direct),
        "thread_context_cue_reasons": list(x.context),
        "sampling_stratum": reason, "selection_reason": reason,
        "primary_sampling_cue": primary_cue,
        "primary_sampling_category": primary_category,
        "thread_selected_count": selected_n, "thread_total_count": total_n,
        "thread_complete": selected_n == total_n,
    }


def _validate(random_count: int, target: int, mode: str) -> None:
    if random_count < 0 or target < 0:
        raise ValueError("sample and target counts must be nonnegative")
    if random_count > target:
        raise ValueError("random_sample_count cannot exceed target_count")
    if mode not in {"fit", "whole"}:
        raise ValueError("thread_mode must be 'fit' or 'whole'")


def select_candidate_records(records: Iterable[dict[str, Any]], *,
    random_sample_count: int = 2000, seed: int = 2026, target_count: int = 8000,
    thread_mode: str = "fit", use_secondary_thread_links: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select deterministic records; fit has a hard cap, whole allows thread overage."""
    _validate(random_sample_count, target_count, thread_mode)
    rows = list(records)
    diagnostics: dict[str, Any] = {}
    suggestions = (
        suggest_secondary_thread_links(rows, diagnostics=diagnostics)
        if use_secondary_thread_links else []
    )
    if suggestions:
        rows = apply_secondary_thread_suggestions(rows, suggestions)
    index = _index(rows, seed, max(target_count, random_sample_count))
    members: dict[str, list[Info]] = defaultdict(list)
    row_by_id = {}
    for line_no, row in enumerate(rows, 1):
        x = _info(row, seed, f"row-{line_no}")
        members[x.thread_id].append(x)
        row_by_id[x.email_id] = row
    if thread_mode == "whole":
        plan = _whole_plan(index, target_count, random_sample_count, seed)
        selected, infos = _finish_whole(plan, members)
    else:
        plan, neg, reserve = _fit_seed(index, target_count, random_sample_count)
        selected, infos = _expand_fit(index, plan, members, target_count, neg, reserve)
    result = [row_by_id[eid] for eid in selected if eid in row_by_id]
    stats = _stats(index, selected, infos, target_count, random_sample_count, seed, thread_mode)
    stats["secondary_thread_linking"] = _linking_stats(
        suggestions, use_secondary_thread_links, diagnostics
    )
    if use_secondary_thread_links:
        stats["thread_cap_semantics"] = (
            "hard record cap; partial derived thread-ID groups are marked in metadata"
            if thread_mode == "fit" else
            "whole derived thread-ID groups; target can be exceeded by complete selected groups"
        )
        stats["thread_completeness_note"] = (
            "Complete is relative to derived thread IDs, which may include unverified "
            "heuristic pairs. Original canonical IDs are preserved in source_thread_id."
        )
    return result, stats


def write_candidate_pool(input_jsonl: str | Path, output_jsonl: str | Path, *,
    random_sample_count: int = 2000, seed: int = 2026, target_count: int = 8000,
    thread_mode: str = "fit", metadata_jsonl: str | Path | None = None,
    use_secondary_thread_links: bool = False,
) -> dict[str, Any]:
    """Write canonical records unchanged and add cue/provenance metadata separately."""
    _validate(random_sample_count, target_count, thread_mode)
    source, output = Path(input_jsonl), Path(output_jsonl)
    metadata = Path(metadata_jsonl) if metadata_jsonl else output.with_name(output.stem + ".metadata.jsonl")
    if source.resolve() in {output.resolve(), metadata.resolve()}:
        raise ValueError("input and output/metadata paths must be different")
    if use_secondary_thread_links:
        suggestions, derived_rows, diagnostics = _secondary_link_metadata(source)
    else:
        suggestions, derived_rows, diagnostics = [], {}, {}
    index = _index(
        (_derived_row(row, derived_rows) for row in read_jsonl(source)),
        seed, max(target_count, random_sample_count),
    )
    if thread_mode == "whole":
        plan = _whole_plan(index, target_count, random_sample_count, seed)
        tids = {k.removeprefix("__thread__:") for k in plan if k.startswith("__thread__:")}
    else:
        plan, neg, reserve = _fit_seed(index, target_count, random_sample_count)
        tids = {index.by_id[e].thread_id for e in plan if e in index.by_id}
    members: dict[str, list[Info]] = defaultdict(list)
    with source.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            x = _info(_derived_row(row, derived_rows), seed, f"row-{line_no}")
            if x.thread_id in tids:
                members[x.thread_id].append(x)
    if thread_mode == "whole":
        selected, infos = _finish_whole(plan, members)
    else:
        selected, infos = _expand_fit(index, plan, members, target_count, neg, reserve)
    thread_counts = Counter(x.thread_id for x in infos.values())
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as out:
        for row in read_jsonl(source):
            eid = str(row.get("email_id", ""))
            if eid in selected:
                out.write(json.dumps(_derived_row(row, derived_rows), ensure_ascii=False) + "\n")
    with metadata.open("w", encoding="utf-8", newline="\n") as side:
        for eid in sorted(selected, key=lambda e: (infos[e].thread_id, infos[e].turn, e)):
            x = infos[eid]
            counts = index.direct_counts if x.direct else index.context_counts
            cue = _primary(x, counts) if x.direct or x.context else "random_nonmatching"
            item = _metadata(
                x, selected[eid], thread_counts[x.thread_id],
                index.thread_sizes[x.thread_id], cue,
                _primary_category(x, index.direct_category_counts if x.direct else index.context_category_counts)
                if x.direct or x.context else "random",
            )
            if eid in derived_rows:
                for key in (
                    "source_thread_id", "thread_link_method",
                    "thread_link_confidence", "thread_link_partner_email_id",
                ):
                    item[key] = derived_rows[eid].get(key)
            side.write(json.dumps(item, ensure_ascii=False) + "\n")
    stats = _stats(index, selected, infos, target_count, random_sample_count, seed, thread_mode)
    stats["secondary_thread_linking"] = _linking_stats(
        suggestions, use_secondary_thread_links, diagnostics
    )
    if use_secondary_thread_links:
        stats["thread_cap_semantics"] = (
            "hard record cap; partial derived thread-ID groups are marked in metadata"
            if thread_mode == "fit" else
            "whole derived thread-ID groups; target can be exceeded by complete selected groups"
        )
        stats["thread_completeness_note"] = (
            "Complete is relative to derived thread IDs, which may include unverified "
            "heuristic pairs. Original canonical IDs are preserved in source_thread_id."
        )
    try:
        stats["metadata_jsonl"] = metadata.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        stats["metadata_jsonl"] = str(metadata)
    output.with_suffix(".stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats

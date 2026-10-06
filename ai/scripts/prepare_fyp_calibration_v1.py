"""Curate a new, unlabelled FYP email calibration source set from safe TRAIN.

This script only selects sources. Retrieval cues are private provenance, never
labels or prompts to reviewers. Email text is exported only beneath ignored
``ai/data/experiments``. The source boundary and global leakage index are
checked before candidate message text is inspected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai"))

from src.datasets.cleaning import normalize_line_endings  # noqa: E402
from src.models.silver_classifier import extract_authored_prefix  # noqa: E402
from src.structured_annotation.workflow import (  # noqa: E402
    _load_boundary,
    _normalize_record,
    _verify_candidate_index_fingerprint,
    _verify_train_isolation,
    sha256_file,
)


DEFAULT_SOURCE = ROOT / "ai/data/experiments/structured_v2_candidates_20261002_v2/isolated_v2/train_screen_candidates.jsonl"
DEFAULT_BOUNDARY = ROOT / "ai/data/experiments/structured_v2_candidates_20261002_v2/isolated_v2/boundary_manifest.json"
DEFAULT_INDEX = ROOT / "ai/data/processed/structured_v2_expanded_leakage_index_v2.json"
DEFAULT_OUTPUT = ROOT / "ai/data/experiments/fyp_calibration_v1_20261005"
REPORT = ROOT / "ai/reports/fyp_calibration_v1_retrieval_proposal.md"
SEED = "fyp-calibration-v1-20261005"


EXPLICIT_SCOPE = {
    "project": re.compile(r"\bprojects?\b", re.I),
    "proposal": re.compile(r"\bproposals?\b", re.I),
    "milestone": re.compile(r"\bmilestones?\b", re.I),
    "implementation": re.compile(r"\bimplement(?:ation|ed|ing|s)?\b", re.I),
    "deliverable": re.compile(r"\bdeliverables?\b", re.I),
    "test_plan": re.compile(r"\btest\s*plans?\b", re.I),
    "requirements": re.compile(r"\brequirements?\b", re.I),
    "rollout": re.compile(r"\b(?:rollout|deployment|workstream|pilot)\b", re.I),
    "work_group": re.compile(r"\b(?:working|study)\s+groups?|task\s+forces?\b", re.I),
    "business_plan": re.compile(r"\bbusiness\s+plans?\b", re.I),
    "migration": re.compile(r"\bmigrat(?:e|ed|es|ing|ion|ions)\b", re.I),
    "construction": re.compile(r"\bconstruction\b", re.I),
}
CONTEXT_SCOPE = re.compile(
    r"\b(?:project|team|workstream|initiative|program|programme|system|"
    r"process|plan|development|design|implementation|requirements|rollout|"
    r"deployment|product|proposal|budget|scope|phase|facility|task|contract|"
    r"working\s+group|study\s+group|task\s+force|migration|construction|"
    r"integration|business\s+plan)\b",
    re.I,
)
FUNCTION_CUES = {
    "meeting": re.compile(r"\b(?:meetings?|conference\s+call|agenda|reschedul\w*|schedule\w*)\b", re.I),
    "deadline": re.compile(
        r"\b(?:deadlines?|due\s+(?:by|date|on|before)|by\s+(?:today|tomorrow|"
        r"monday|tuesday|wednesday|thursday|friday|\d{1,2}|end\s+of|close\s+of\s+business)|"
        r"no\s+later\s+than)\b", re.I,
    ),
    "document": re.compile(
        r"\b(?:reports?|presentations?|minutes|proposals?|plans?|drafts?|"
        r"documents?|analysis|memos?|deliverables?)\b", re.I,
    ),
    "department_input": re.compile(
        r"\b(?:departments?|engineering|finance|legal|operations|input|"
        r"comments\s+from|cross[- ]functional)\b", re.I,
    ),
    "approval_review": re.compile(r"\b(?:approv\w*|authoriz\w*|sign[- ]off|review\w*)\b", re.I),
    "follow_up": re.compile(
        r"\b(?:follow[- ]?up|remind(?:er)?|still\s+waiting|checking\s+back|"
        r"as\s+discussed|per\s+our|as\s+requested)\b", re.I,
    ),
    "action_assignment": re.compile(
        r"\b(?:please\s+(?:(?:plan\s+to|help\s+me\s+)?)(?:send|submit|provide|"
        r"prepare|draft|review|approve|confirm|coordinate|develop|revise|implement|"
        r"build|test|gather|identify|compile|circulate|schedule|attend|respond|"
        r"complete|finish|share|return|update|forward|discuss|create|present|rsvp|"
        r"let\s+me\s+know|keep\s+me\s+informed)\b|"
        r"(?:can|could|would)(?:\s+you)?\s+(?:please\s+)?(?:help(?:\s+me)?|send|submit|provide|"
        r"prepare|draft|review|approve|confirm|coordinate|develop|revise|implement|"
        r"build|test|gather|identify|compile|schedule|attend|respond|update|discuss)\b|"
        r"need\s+you\s+to\s+(?:send|submit|provide|prepare|draft|review|approve|"
        r"confirm|coordinate|develop|revise|implement|build|test|gather|identify|"
        r"compile|schedule|attend|respond|update|discuss)\b|"
        r"(?:asked|requested)\s+(?:me|us|you|the\s+team)?\s*to\s+(?:send|submit|"
        r"provide|prepare|draft|review|approve|confirm|coordinate|develop|revise|"
        r"implement|build|test|gather|identify|compile|schedule|attend|respond|update|discuss)\b|"
        r"(?:we|i|the\s+team)\s+(?:are|am|is)\s+(?:gathering|developing|drafting|"
        r"preparing|building|implementing|testing|reviewing|coordinating|compiling)\b|"
        r"(?:assigned|responsible)\s+to\s+(?:prepare|draft|review|approve|confirm|"
        r"coordinate|develop|implement|build|test|gather|identify|compile|submit)\b)",
        re.I,
    ),
    "status_update": re.compile(
        r"\b(?:status|progress|completed|finished|on\s+track|delayed|blocked|"
        r"currently\s+working|moving\s+forward|update)\b", re.I,
    ),
}
BULK_OR_NEWS = re.compile(
    r"\b(?:newsletter|newswire|press release|daily headlines|daily news|"
    r"daily market|morning market call|enron mentions|state newswire|"
    r"industry news|news service|news roundup|e\.bulletin|free web version|"
    r"energy central daily|powermarketers|enerfax|today's headlines|"
    r"market notice|unsubscribe|enron in action|daily california update|"
    r"competitive analysis report|document preservation|terrorism attacks|"
    r"employee performance reviews|performance reviews needed|daily california|"
    r"daily (?:update|briefing|bulletin)|news (?:update|briefing|bulletin)|"
    r"commission (?:order|docket|notice)|ferc (?:order|docket|notice)|"
    r"federal energy regulatory commission|order approving settlement|"
    r"employee (?:notice|announcement|review)|performance review)",
    re.I,
)
REGULATORY_NEWS = re.compile(
    r"\b(?:ferc|federal energy regulatory commission|commission|cpuc|"
    r"public utilities commission|nyiso|nymex)\b",
    re.I,
)
REGULATORY_SUBJECT = re.compile(
    r"\b(?:order|docket|settlement|notice|case\s*(?:no\.?|number)|"
    r"decision|filing|tariff|rulemaking)\b",
    re.I,
)
SUBJECT_HARD_EXCLUSIONS = re.compile(
    r"\b(?:important announcement regarding document preservation|"
    r"document preservation|enron in action|daily california update|"
    r"competitive analysis report|terrorism attacks|employee performance reviews|"
    r"performance reviews needed|daily (?:news|headlines|update|briefing)|"
    r"outage report|scheduled system availability|enron hr data|update yourself|"
    r"caiso notification|operating procedure|rescind .*offer|job offer|"
    r"(?:org|organization|organizational) announcement|dinner meeting|"
    r"order approving settlement|arto/miso order|"
    r"(?:ferc|miso|iso|commission|puc).*(?:order|docket|settlement|notice)|"
    r"(?:order|docket|settlement|notice).*(?:ferc|miso|iso|commission|puc)|"
    r"ferc.*(?:order|docket|settlement|notice)|(?:order|docket|settlement|notice).*ferc|"
    r"commission.*(?:order|docket|settlement|notice)|"
    r"(?:order|docket|settlement|notice).*commission|"
    r"(?:employee|staff) (?:performance )?review|review.*(?:employee|staff))\b",
    re.I,
)
BODY_HARD_EXCLUSIONS = re.compile(
    r"\b(?:this message is being sent to all employees|"
    r"all employees are required to|employee performance review|"
    r"please complete your annual review|document preservation notice|"
    r"legal hold notice|attached is the daily news|today's california update|"
    r"this article was sent to you by someone who found it on|copyright\s+\d{4}\s+the associated press|"
    r"daily gpi|associated press|sfgate\.com|the following new or revised iso operating procedures|"
    r"operating procedure posted|not yet updated your information|hris helpdesk|"
    r"offer of employment|rescind.{0,30}offer|non-essential hire|"
    r"employment recruiter|attached is our cash forecast|"
    r"weekend systems availability|scheduled system outages|"
    r"organization announcement that will be sent out)\b",
    re.I,
)
CALENDAR_EXPORT = re.compile(
    r"(?:\bappointment has been (?:modified|cancelled|updated)\b|"
    r"\bthis meeting request was sent by\b|\bBEGIN:VCALENDAR\b|"
    r"\bMETHOD:(?:REQUEST|CANCEL)\b)", re.I,
)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            low, high = sorted((a, b))
            self.parent[high] = low


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def write_jsonl_new(path: Path, rows: list[dict[str, Any]]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return sha256_file(path)


def normalized_template(text: str) -> str:
    value = text.casefold()
    value = re.sub(r"https?://\S+|www\.\S+", " <url> ", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", " <email> ", value)
    value = re.sub(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\.?\s+\d{1,2}(?:,\s*\d{4})?\b",
        " <date> ", value,
    )
    value = re.sub(r"\b\d{1,4}(?:[./:-]\d{1,4})*\b", " <num> ", value)
    value = re.sub(r"[^a-z0-9<>]+", " ", value)
    return " ".join(value.split())


def authored_offsets(full_text: str) -> tuple[str, list[dict[str, int]], str]:
    """Return normalized full text and a conservative authored-prefix range."""
    normalized = normalize_line_endings(full_text)
    authored = extract_authored_prefix(normalized)
    if not authored:
        return normalized, [], normalized
    start = len(normalized) - len(normalized.lstrip())
    if normalized[start:start + len(authored)] != authored:
        raise ValueError("authored-prefix extractor did not return a source prefix")
    end = start + len(authored)
    quoted = normalized[end:]
    return normalized, [{"start": start, "end": end}], quoted


def source_cues(subject: str, authored: str) -> dict[str, Any]:
    combined = subject + "\n" + authored
    anchors = [name for name, pattern in EXPLICIT_SCOPE.items() if pattern.search(combined)]
    cues = [name for name, pattern in FUNCTION_CUES.items() if pattern.search(combined)]
    explicit_request = bool(FUNCTION_CUES["action_assignment"].search(authored))
    is_bulk = bool(BULK_OR_NEWS.search(subject + "\n" + authored))
    is_bulk = is_bulk or bool(SUBJECT_HARD_EXCLUSIONS.search(subject))
    is_bulk = is_bulk or bool(BODY_HARD_EXCLUSIONS.search(authored))
    if REGULATORY_NEWS.search(subject) and REGULATORY_SUBJECT.search(subject):
        is_bulk = True
    if not is_bulk:
        # Retain the established high precision guard for promotional/news mail.
        from src.datasets.candidate_filter import _AUTOMATED_OR_BULK
        is_bulk = bool(_AUTOMATED_OR_BULK.search(subject + "\n" + authored))
    calendar_export = bool(CALENDAR_EXPORT.search(subject + "\n" + authored))
    return {
        "anchors": anchors,
        "function_cues": cues,
        "explicit_request_or_assignment": explicit_request,
        "bulk_or_news_excluded": is_bulk,
        "calendar_export_excluded": calendar_export,
        "scope_context": bool(CONTEXT_SCOPE.search(combined)),
    }


def tier_for(cues: dict[str, Any], authored: str) -> str | None:
    cue_count = len(cues["function_cues"])
    if cues["bulk_or_news_excluded"] or cues["calendar_export_excluded"]:
        return None
    if len(authored.strip()) < 80 or len(authored) > 8000:
        return None
    if cues["explicit_request_or_assignment"] and cues["anchors"] and cue_count >= 2:
        return "project_context"
    if (cues["explicit_request_or_assignment"] and cue_count >= 4
            and any(name in cues["function_cues"] for name in ("meeting", "deadline", "document"))
            and cues["scope_context"]):
        return "project_adjacent"
    if cues["explicit_request_or_assignment"] and cue_count >= 4:
        return "scope_boundary"
    return None


def rank_candidate(row: dict[str, Any], cues: dict[str, Any]) -> int:
    anchor_count = len(cues["anchors"])
    cue_count = len(cues["function_cues"])
    score = 4 * anchor_count + 2 * cue_count
    if cues["explicit_request_or_assignment"]:
        score += 3
    if "project" in cues["anchors"]:
        score += 2
    if "proposal" in cues["anchors"] or "requirements" in cues["anchors"]:
        score += 1
    subject = str(row.get("subject") or "")
    if any(pattern.search(subject) for pattern in EXPLICIT_SCOPE.values()):
        score += 2
    return score


def assign_components(rows: list[dict[str, Any]], index_records: dict[str, Any]) -> dict[str, str]:
    """Join leakage, verified-thread, and normalized whole-template groups."""
    uf = UnionFind()
    template_owners: dict[str, str] = {}
    for row in rows:
        source_id = str(row["source_id"])
        qualified = f"enron:{source_id}"
        uf.find(qualified)
        record = index_records[qualified]
        uf.union(qualified, "leakage:" + str(record["leakage_group_id"]))
        if row.get("source_thread_verified") is True and row.get("source_thread_id"):
            uf.union(qualified, "verified-thread:" + str(row["source_thread_id"]))
        full = normalize_line_endings(str(row.get("current_message") or ""))
        authored = extract_authored_prefix(full)
        template = normalized_template(authored)
        if len(template) >= 500 and len(template.split()) >= 60:
            template_key = digest_text(template)
            if template_key in template_owners:
                uf.union(qualified, template_owners[template_key])
            else:
                template_owners[template_key] = qualified
    members: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        qualified = "enron:" + str(row["source_id"])
        members[uf.find(qualified)].append(qualified)
    component_ids: dict[str, str] = {}
    for group in members.values():
        component = "fypcal-v1-" + digest_text("\n".join(sorted(group)))[:20]
        for qualified in group:
            component_ids[qualified] = component
    return component_ids


def deterministic_key(component_id: str, tier: str) -> str:
    return digest_text(f"{SEED}\0{tier}\0{component_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    data_root = (ROOT / "ai/data").resolve()
    if data_root not in output.parents:
        raise ValueError("Email source exports must remain under ignored ai/data")

    index_payload, boundary, index_sha, boundary_sha = _load_boundary(
        index_path=args.index, assignments_path=args.boundary, dataset_id="enron", root=ROOT,
    )
    _verify_train_isolation(index_payload, boundary)
    source_sha = sha256_file(args.source)
    if source_sha != boundary.get("train_screen_candidates_sha256"):
        raise ValueError("source is not the frozen isolated_v2 TRAIN screen")
    rows = [
        json.loads(line)
        for line in args.source.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]

    # Validate canonical identity and source partition before reading any body.
    seen_ids: set[str] = set()
    for row in rows:
        source_id = row.get("source_id")
        qualified = f"enron:{source_id}"
        if (row.get("source_dataset") != "enron" or not isinstance(source_id, str)
                or row.get("email_id") != source_id):
            raise ValueError("candidate canonical source metadata mismatch")
        if source_id in seen_ids:
            raise ValueError("duplicate canonical source ID in TRAIN screen")
        seen_ids.add(source_id)
        if boundary["partitions"].get(qualified) != "TRAIN_SCREEN":
            raise ValueError("candidate is not assigned to TRAIN_SCREEN")
        if qualified in set(boundary.get("protected_global_ids", [])):
            raise ValueError("candidate also appears in protected source IDs")
        if qualified not in index_payload["records"]:
            raise ValueError("candidate is missing from the frozen leakage index")

    # The source ID and partition checks are complete. Verify each source text
    # against its index fingerprints, then create retrieval-only cues.
    for row in rows:
        qualified = "enron:" + str(row["source_id"])
        normalized = _normalize_record(row)
        _verify_candidate_index_fingerprint(
            normalized_record=normalized,
            index_record=index_payload["records"][qualified],
        )

    component_ids = assign_components(rows, index_payload["records"])
    grouped_candidates: dict[str, dict[str, Any]] = {}
    all_candidates: list[dict[str, Any]] = []
    for row in rows:
        full, authored_ranges, quoted_tail = authored_offsets(str(row.get("current_message") or ""))
        if not authored_ranges:
            continue
        authored = full[authored_ranges[0]["start"]:authored_ranges[0]["end"]]
        subject = str(row.get("subject") or "")
        cues = source_cues(subject, authored)
        tier = tier_for(cues, authored)
        if tier is None:
            continue
        qualified = "enron:" + str(row["source_id"])
        candidate = {
            "row": row,
            "full_text": full,
            "authored_ranges": authored_ranges,
            "quoted_tail": quoted_tail,
            "authored_length": len(authored),
            "cues": cues,
            "tier": tier,
            "score": rank_candidate(row, cues),
            "component_id": component_ids[qualified],
        }
        all_candidates.append(candidate)
        previous = grouped_candidates.get(candidate["component_id"])
        if previous is None or (candidate["score"], candidate["row"]["source_id"]) > (
                previous["score"], previous["row"]["source_id"]):
            grouped_candidates[candidate["component_id"]] = candidate

    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in grouped_candidates.values():
        by_tier[candidate["tier"]].append(candidate)
    for tier, candidates in by_tier.items():
        candidates.sort(key=lambda item: (-item["score"], deterministic_key(item["component_id"], tier)))

    targets = {"project_context": 108, "project_adjacent": 51, "scope_boundary": 28}
    selected: list[dict[str, Any]] = []
    selected_components: set[str] = set()
    selected_per_tier: Counter[str] = Counter()
    for tier in ("project_context", "project_adjacent", "scope_boundary"):
        for candidate in by_tier.get(tier, []):
            if selected_per_tier[tier] >= targets[tier]:
                break
            if candidate["component_id"] in selected_components:
                continue
            selected.append(candidate)
            selected_components.add(candidate["component_id"])
            selected_per_tier[tier] += 1

    # If conservative grouping leaves a stratum short, fill from the next
    # strongest unused groups. This remains source retrieval, never labeling.
    target_total = sum(targets.values())
    if len(selected) < target_total:
        fallback = sorted(
            (candidate for tier in ("project_context", "project_adjacent", "scope_boundary")
             for candidate in by_tier.get(tier, [])
             if candidate["component_id"] not in selected_components),
            key=lambda item: (-item["score"], deterministic_key(item["component_id"], item["tier"])),
        )
        for candidate in fallback:
            if len(selected) >= target_total:
                break
            # Scope-boundary items are useful hard negatives, but never let
            # them exceed the documented 15% cap of the final source set.
            if candidate["tier"] == "scope_boundary" and selected_per_tier[candidate["tier"]] >= int(target_total * 0.15):
                continue
            selected.append(candidate)
            selected_components.add(candidate["component_id"])
            selected_per_tier[candidate["tier"]] += 1
    if len(selected) != target_total:
        raise ValueError(
            f"only {len(selected)} eligible independent groups after quality guards; "
            "adjust target totals honestly rather than admitting weak sources; "
            f"available_by_tier={dict((key, len(value)) for key, value in by_tier.items())}; "
            f"selected_by_tier={dict(selected_per_tier)}"
        )

    # Keep a useful shared agreement set and sealed human holdout as pool size
    # varies; the remainder is personal calibration training.
    if len(selected) < 3:
        raise ValueError("At least three sources are needed for the proposed allocations")
    common_count = min(70, max(10, round(len(selected) * .5)), len(selected) - 2)
    holdout_count = min(60, max(1, round(len(selected) * .24)), len(selected) - common_count - 1)
    allocation_counts = {
        "blind_agreement": common_count,
        "calibration_training": len(selected) - common_count - holdout_count,
        "labeler_human_holdout": holdout_count,
    }
    tiers = ("project_context", "project_adjacent", "scope_boundary")
    allocations = tuple(allocation_counts)
    tier_sizes = Counter(candidate["tier"] for candidate in selected)
    allocation_matrix: dict[str, dict[str, int]] = {tier: {} for tier in tiers}
    row_remaining: dict[str, int] = {}
    column_remaining = dict(allocation_counts)
    fractional: dict[tuple[str, str], float] = {}
    for tier in tiers:
        row_remaining[tier] = tier_sizes[tier]
        for allocation in allocations:
            ideal = tier_sizes[tier] * allocation_counts[allocation] / len(selected)
            base = int(ideal)
            allocation_matrix[tier][allocation] = base
            row_remaining[tier] -= base
            column_remaining[allocation] -= base
            fractional[(tier, allocation)] = ideal - base
    extras_given: set[tuple[str, str]] = set()
    while sum(row_remaining.values()):
        options = [
            (fractional[(tier, allocation)], tier, allocation)
            for tier in tiers for allocation in allocations
            if row_remaining[tier] > 0 and column_remaining[allocation] > 0
            and (tier, allocation) not in extras_given
        ]
        if not options:
            raise ValueError("cannot apportion source strata to exact allocation totals")
        _, tier, allocation = max(options, key=lambda item: (item[0], item[1], item[2]))
        allocation_matrix[tier][allocation] += 1
        row_remaining[tier] -= 1
        column_remaining[allocation] -= 1
        extras_given.add((tier, allocation))
    if any(column_remaining.values()):
        raise ValueError(f"allocation apportionment totals differ: {column_remaining}")
    for tier in tiers:
        candidates = [candidate for candidate in selected if candidate["tier"] == tier]
        candidates.sort(key=lambda item: deterministic_key(item["component_id"], "allocation-" + tier))
        cursor = 0
        for allocation in allocations:
            count = allocation_matrix[tier][allocation]
            for candidate in candidates[cursor:cursor + count]:
                candidate["allocation"] = allocation
            cursor += count
        if cursor != len(candidates):
            raise ValueError(f"allocation did not consume all {tier} sources")

    allocation_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in selected:
        if "allocation" not in candidate:
            raise ValueError("selected source lacks an allocation")
        allocation_rows[candidate["allocation"]].append(candidate)
    if {key: len(allocation_rows[key]) for key in allocation_counts} != allocation_counts:
        actual = {key: len(allocation_rows[key]) for key in allocation_counts}
        selected_tiers = dict(Counter(candidate["tier"] for candidate in selected))
        available_tiers = {key: len(value) for key, value in by_tier.items()}
        raise ValueError(
            "group-aware allocation did not produce the frozen split: "
            f"actual={actual}, selected_tiers={selected_tiers}, available_tiers={available_tiers}"
        )

    ordered: list[dict[str, Any]] = []
    for allocation in ("blind_agreement", "calibration_training", "labeler_human_holdout"):
        subset = allocation_rows[allocation]
        subset.sort(key=lambda item: deterministic_key(item["component_id"], "position-" + allocation))
        for candidate in subset:
            ordered.append(candidate)
    # Stable global positions; do not expose strata order or retrieval score.
    for position, candidate in enumerate(ordered):
        candidate["position"] = position

    site_import: list[dict[str, Any]] = []
    calibration_sources: list[dict[str, Any]] = []
    private_metadata: list[dict[str, Any]] = []
    train_common_import: list[dict[str, Any]] = []
    holdout_import: list[dict[str, Any]] = []
    group_allocations: dict[str, str] = {}
    for candidate in ordered:
        row = candidate["row"]
        source_id = str(row["source_id"])
        allocation = candidate["allocation"]
        common_blind = allocation == "blind_agreement"
        owner_slot = None if common_blind else (
            sum(1 for prior in allocation_rows[allocation]
                if prior["position"] < candidate["position"]) % 3
        )
        body = candidate["full_text"]
        source_sha256 = digest_text(str(row.get("subject") or "") + "\n" + body)
        site_row: dict[str, Any] = {
            "source_id": source_id,
            "subject": str(row.get("subject") or ""),
            "current_message": body,
            "authored_ranges": candidate["authored_ranges"],
            "source_sha256": source_sha256,
            "allocation": allocation,
            "position": candidate["position"],
            "common_blind": common_blind,
            "owner_slot": owner_slot,
        }
        if row.get("source_thread_verified") is True and row.get("source_thread_id"):
            thread_context = row.get("thread_context")
            if thread_context:
                site_row["thread_context"] = thread_context
                site_row["context_sources"] = [str(row["source_thread_id"])]
        site_import.append(site_row)
        if allocation in {"blind_agreement", "calibration_training"}:
            train_common_import.append(site_row)
        else:
            holdout_import.append(site_row)
        group_allocations[candidate["component_id"]] = allocation

        calibration_sources.append({
            "source_id": source_id,
            "canonical_email_id": str(row["email_id"]),
            "subject": str(row.get("subject") or ""),
            "current_message": body,
            "authored_ranges": candidate["authored_ranges"],
            "quoted_history_reference_only": candidate["quoted_tail"],
            "origin": "public_corpus:Enron Email Dataset",
            "source_hash": source_sha256,
            "source_text_sha256": digest_text(body),
            "component_id": candidate["component_id"],
            "thread_id": row.get("thread_id"),
            "thread_id_verified": bool(row.get("source_thread_verified")),
            "allocation": allocation,
            "sampling_provenance": "fyp_calibration_v1_enron_train_screen_group_retrieval",
        })
        private_metadata.append({
            "source_id": source_id,
            "position": candidate["position"],
            "component_id": candidate["component_id"],
            "allocation": allocation,
            "private_retrieval_stratum": candidate["tier"],
            "private_retrieval_hints": {
                "scope_terms": candidate["cues"]["anchors"],
                "function_cues": candidate["cues"]["function_cues"],
                "explicit_request_or_assignment": candidate["cues"]["explicit_request_or_assignment"],
                "score": candidate["score"],
            },
            "source_sha256": source_sha256,
        })

    # Deterministic personal assignment order within private splits.
    for allocation in ("calibration_training", "labeler_human_holdout"):
        subset = sorted(
            (item for item in site_import if item["allocation"] == allocation),
            key=lambda item: item["position"],
        )
        for local_position, item in enumerate(subset):
            item["owner_slot"] = local_position % 3

    # Site import sidecars share object references above, so copy updated owner
    # slots back into the audit and holdout views before writing.
    owner_by_id = {item["source_id"]: item["owner_slot"] for item in site_import}
    for rows_view in (train_common_import, holdout_import):
        for item in rows_view:
            item["owner_slot"] = owner_by_id[item["source_id"]]

    expected_files = (
        "site_import.jsonl", "site_import_train_common.jsonl", "site_import_holdout.jsonl",
        "calibration_sources.jsonl", "selection_metadata_private.jsonl",
        "curation_manifest.json", "holdout_manifest.json",
    )
    output.mkdir(parents=True, exist_ok=True)
    for name in expected_files:
        if (output / name).exists():
            raise FileExistsError(f"refusing to overwrite frozen artifact: {output / name}")
    if REPORT.exists():
        raise FileExistsError(f"refusing to overwrite report: {REPORT}")

    site_sha = write_jsonl_new(output / "site_import.jsonl", site_import)
    train_common_sha = write_jsonl_new(output / "site_import_train_common.jsonl", train_common_import)
    holdout_sha = write_jsonl_new(output / "site_import_holdout.jsonl", holdout_import)
    sources_sha = write_jsonl_new(output / "calibration_sources.jsonl", calibration_sources)
    private_sha = write_jsonl_new(output / "selection_metadata_private.jsonl", private_metadata)
    allocation_hashes = {
        name: digest_text("\n".join(
            f"{row['source_id']}\t{row['source_sha256']}" for row in site_import
            if row["allocation"] == name
        ))
        for name in allocation_counts
    }
    holdout_manifest = {
        "status": "sealed_human_holdout_sources_unlabelled",
        "source_count": len(holdout_import),
        "source_ids_and_hashes_sha256": allocation_hashes["labeler_human_holdout"],
        "site_import_holdout_sha256": holdout_sha,
        "selection_frozen_before_labeler_prototype": True,
        "labels_present": False,
        "ai_prelabels_present": False,
        "group_component_count": len({item["component_id"] for item in private_metadata
                                       if item["allocation"] == "labeler_human_holdout"}),
    }
    (output / "holdout_manifest.json").write_text(
        json.dumps(holdout_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    template_counts = Counter()
    for row in rows:
        full = normalize_line_endings(str(row.get("current_message") or ""))
        authored = extract_authored_prefix(full)
        template = normalized_template(authored)
        if len(template) >= 500 and len(template.split()) >= 60:
            template_counts[digest_text(template)] += 1
    selected_thread_verified = sum(
        bool(candidate["row"].get("source_thread_verified")) for candidate in ordered
    )
    curation_manifest = {
        "status": "frozen_unlabelled_fyp_calibration_sources",
        "run_id": "fyp_calibration_v1_20261005",
        "created_from": {
            "source_path": args.source.resolve().relative_to(ROOT).as_posix(),
            "source_sha256": source_sha,
            "boundary_path": args.boundary.resolve().relative_to(ROOT).as_posix(),
            "boundary_sha256": boundary_sha,
            "index_path": args.index.resolve().relative_to(ROOT).as_posix(),
            "index_sha256": index_sha,
        },
        "boundary_status": boundary.get("status"),
        "train_screen_rows_verified_before_text_review": len(rows),
        "source_dataset_counts": {"enron": len(site_import)},
        "selected_source_count": len(site_import),
        "selected_component_count": len({row["component_id"] for row in calibration_sources}),
        "selected_verified_source_thread_count": selected_thread_verified,
        "selected_unverified_thread_metadata_count": len(site_import) - selected_thread_verified,
        "allocation_counts": {key: len(allocation_rows[key]) for key in allocation_counts},
        "selection_strata_counts_private_retrieval_only": dict(selected_per_tier),
        "site_import_sha256": site_sha,
        "site_import_train_common_sha256": train_common_sha,
        "site_import_holdout_sha256": holdout_sha,
        "calibration_sources_sha256": sources_sha,
        "selection_metadata_private_sha256": private_sha,
        "groups_split_across_allocations": 0,
        "template_normalization": "authored-prefix exact hash after replacing email, URL, date and numeric values; min 500 chars/60 tokens",
        "leakage_grouping": "frozen global leakage_group_id plus verified source threads plus normalized template groups; one source representative per resulting component",
        "thread_policy": "Enron source_thread_verified was false for all selected records; thread_id is retained as unverified metadata and is not used to claim thread coverage",
        "source_policy": "Enron fallback from frozen TRAIN_SCREEN only; no MailEx archive or protected EVAL message text was read",
        "labels_present": False,
        "ai_prelabels_present": False,
        "synthetic_rows_in_real_email_count": 0,
        "annotation_support": "unknown until humans label; retrieval stratum counts are not class support",
        "quote_boundary_policy": "Existing extract_authored_prefix heuristic; authored_ranges identify its conservative prefix; remaining inline history is reference-only; heuristic is not exhaustive",
        "reviewer_payload_policy": "site_import.jsonl includes source text and assignment metadata only; retrieval hints are stored separately and must not be sent to reviewers",
        "limitation": "Public Enron email is old corporate mail and selected by retrieval cues; it cannot establish project-domain prevalence or target-domain performance",
    }
    (output / "curation_manifest.json").write_text(
        json.dumps(curation_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    report = f"""# FYP calibration V1 retrieval proposal

Prepared {len(site_import)} unlabelled source candidates from {len(rows):,} isolated TRAIN_SCREEN records. Proposed allocations: {common_count} common blind, {len(selected) - common_count - holdout_count} personal calibration TRAIN, {holdout_count} sealed human holdout. This is an unapproved retrieval proposal: manual relevance and evidence-range review is required before import.

Normalized body/subject bytes are preserved. Authored-prefix extraction is heuristic and may retain signatures or unmarked quotes. Retrieval cues and sidecars must not be displayed to blind reviewers. Whole leakage/thread/template components are allocated together; global source fingerprints and protected-boundary metadata are checked.

Enron is a historical public-corpus fallback. Retrieval counts do not establish project prevalence, human class support, GOLD data, or target-domain accuracy. No labels or AI prelabels are included. Private import/curator files and manifests remain excluded from Git. Preserve this proposal and write manual corrections to a fresh iteration.
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(report)
    print(json.dumps({
        "status": curation_manifest["status"],
        "selected": len(site_import),
        "allocation_counts": curation_manifest["allocation_counts"],
        "retrieval_strata_counts": curation_manifest["selection_strata_counts_private_retrieval_only"],
        "verified_source_threads": selected_thread_verified,
        "site_import_sha256": site_sha,
        "holdout_sha256": holdout_sha,
        "report": REPORT.relative_to(ROOT).as_posix(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()

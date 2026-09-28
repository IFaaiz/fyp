"""Build text-free silver decisions from independently reviewed tranches.

The conservative gate accepts only exact, unflagged blind agreement. A third
audit must confirm every such rare-label or multi-label row and a fixed 20%
sample of other agreements. It also inspects every disagreement and flag, but
those rows remain excluded from high-confidence training even if tie-broken.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


AI_DIR = Path(__file__).resolve().parents[1]
BATCH = AI_DIR / "data/annotated/ai/training_silver_1400"
SEED = BATCH / "annotation_seed_1400.jsonl"
ALIASES = AI_DIR / "annotation/training_silver_1400_thread_aliases.json"
EXCLUSIONS = AI_DIR / "annotation/training_leakage_exclusions.json"
RARE_THRESHOLD = 10
SAMPLE_FRACTION = 0.2


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def expected_audit_ids(seed: list[dict], left: list[dict], right: list[dict]) -> set[str]:
    if not (len(seed) == len(left) == len(right)):
        raise ValueError("source and reviewer row counts differ")
    agreement_counts: Counter[str] = Counter()
    for source, a, b in zip(seed, left, right):
        if a["email_id"] != source["email_id"] or b["email_id"] != source["email_id"]:
            raise ValueError("reviewer IDs/order differ from seed")
        if set(a["labels"]) == set(b["labels"]) and not a["needs_review"] and not b["needs_review"]:
            agreement_counts.update(a["labels"])
    rare = {label for label, count in agreement_counts.items() if count <= RARE_THRESHOLD}
    mandatory: set[str] = set()
    ordinary = []
    for source, a, b in zip(seed, left, right):
        email_id = source["email_id"]
        labels = set(a["labels"])
        if labels != set(b["labels"]) or a["needs_review"] or b["needs_review"]:
            mandatory.add(email_id)
        elif len(labels) > 1 or labels & rare:
            mandatory.add(email_id)
        else:
            ordinary.append(email_id)
    sample_size = (len(ordinary) + 4) // 5
    ordinary.sort(key=lambda email_id: (hashlib.sha256(email_id.encode("utf-8")).hexdigest(), email_id))
    return mandatory | set(ordinary[:sample_size])


def adjudicate(seed: list[dict], left: list[dict], right: list[dict], audit: list[dict],
               *, exclusions: set[str], aliases: dict[str, str], supervisor_vetoes: set[str]) -> list[dict]:
    required = expected_audit_ids(seed, left, right)
    audited = {}
    source_ids = {row["email_id"] for row in seed}
    for row in audit:
        if set(row) != {"email_id", "labels", "needs_review"}:
            raise ValueError("audit row must have exactly email_id, labels, needs_review")
        email_id = row["email_id"]
        if email_id not in source_ids or email_id in audited:
            raise ValueError(f"unknown or duplicate audited email_id: {email_id}")
        if not isinstance(row["labels"], list) or not isinstance(row["needs_review"], bool):
            raise ValueError(f"invalid audit decision: {email_id}")
        audited[email_id] = row
    missing = required - set(audited)
    if missing:
        raise ValueError(f"third audit missing {len(missing)} required records; e.g. {sorted(missing)[:3]}")

    decisions = []
    for source, a, b in zip(seed, left, right):
        email_id = source["email_id"]
        labels = set(a["labels"])
        exact_unflagged = labels == set(b["labels"]) and not a["needs_review"] and not b["needs_review"] and bool(labels)
        third = audited.get(email_id)
        third_confirms = third is None or (set(third["labels"]) == labels and not third["needs_review"])
        allowed = exact_unflagged and third_confirms and email_id not in exclusions and email_id not in supervisor_vetoes
        if allowed:
            reason = "exact_unflagged_blind_agreement_third_audit_gate"
        elif email_id in exclusions:
            reason = "curated_leakage_exclusion"
        elif email_id in supervisor_vetoes:
            reason = "supervisor_scope_veto"
        elif not exact_unflagged:
            reason = "disagreement_flag_or_abstention"
        else:
            reason = "third_audit_veto"
        decisions.append({
            "source_dataset": source["source_dataset"],
            "email_id": email_id,
            "thread_id": aliases.get(email_id, source["thread_id"]),
            "labels": a["labels"] if allowed else [],
            "status": "ai_silver" if allowed else "excluded_uncertain",
            "training_provenance": "ai_silver" if allowed else None,
            "acceptance_rule": reason,
        })
    return decisions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, default=SEED, help="frozen source JSONL under ignored data")
    parser.add_argument("--start", type=int, default=1, help="one-based seed row")
    parser.add_argument("--end", type=int, default=300, help="inclusive seed row")
    parser.add_argument("--reviewer-a", type=Path, default=BATCH / "reviewer_a_first300.jsonl")
    parser.add_argument("--reviewer-b", type=Path, default=BATCH / "reviewer_b_decisions_300.jsonl")
    parser.add_argument("--third-audit", type=Path, default=BATCH / "third_audit_first300.jsonl")
    parser.add_argument("--supervisor-vetoes", type=Path, default=AI_DIR / "annotation/training_silver_supervisor_vetoes.json")
    parser.add_argument("--output", type=Path, default=AI_DIR / "annotation/training_silver_first300_decisions.jsonl")
    args = parser.parse_args()
    seed = read_jsonl(args.seed)[args.start - 1:args.end]
    a = read_jsonl(args.reviewer_a)
    b = read_jsonl(args.reviewer_b)
    audit = read_jsonl(args.third_audit)
    exclusions = set(json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["training_exclusions"])
    alias_rows = json.loads(ALIASES.read_text(encoding="utf-8"))["aliases"]
    aliases = {row["email_id"]: row["canonical_thread_id"] for row in alias_rows}
    vetoes = set(json.loads(args.supervisor_vetoes.read_text(encoding="utf-8"))["email_ids"])
    decisions = adjudicate(seed, a, b, audit, exclusions=exclusions, aliases=aliases, supervisor_vetoes=vetoes)
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in decisions)
    if args.output.exists() and args.output.read_text(encoding="utf-8") != content:
        raise ValueError("existing decision manifest differs; inspect before overwriting")
    args.output.write_text(content, encoding="utf-8", newline="\n")
    print(f"{args.output}: {sum(row['status'] == 'ai_silver' for row in decisions)} accepted / {len(decisions)} reviewed")


if __name__ == "__main__":
    main()

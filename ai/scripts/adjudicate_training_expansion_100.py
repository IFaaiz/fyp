"""Reproduce the supervisor-audited classification decisions for expansion 100.

Only exact unflagged agreements enter silver. Every disagreement or abstention
was inspected by the supervisor and remains excluded; agreement alone is not
treated as gold. The fixed spot-audit sample is recorded in the report.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data/annotated/ai/training_expansion_100"
OUTPUT = ROOT / "annotation/training_expansion_100_silver_decisions.jsonl"
SUPERVISOR_EXCLUSIONS = {
    # Parallel-system access could be part of a project rollout; current text
    # does not establish scope well enough for a confident NON_PROJECT label.
    "enron-7981fe543fd7d1647c087c5d": "possible project scope",
    # Staffing an EnronOnline customer onboarding effort could be ongoing
    # operations or managed rollout work; exclude instead of guessing.
    "enron-b8bb47f003abbacfef057c42": "possible project scope",
}


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def adjudicate() -> list[dict]:
    seed = read(BATCH / "annotation_seed_100.jsonl")
    left = read(BATCH / "reviewer_a_decisions.jsonl")
    right = read(BATCH / "reviewer_b_decisions.jsonl")
    if not (len(seed) == len(left) == len(right) == 100):
        raise ValueError("expected 100 aligned source and reviewer rows")
    decisions = []
    for index, (source, a, b) in enumerate(zip(seed, left, right), 1):
        email_id = source["email_id"]
        if a["email_id"] != email_id or b["email_id"] != email_id:
            raise ValueError(f"reviewer order mismatch at {index}")
        agree = set(a["labels"]) == set(b["labels"])
        flagged = bool(a["needs_review"] or b["needs_review"])
        accepted = agree and not flagged and bool(a["labels"]) and email_id not in SUPERVISOR_EXCLUSIONS
        # The supervisor inspected all 32 nonaccepted rows, the sole accepted
        # project-positive row, and a deterministic sample plus targeted risky
        # NON_PROJECT agreements. None were promoted against the strict gate.
        decisions.append({
            "source_dataset": source["source_dataset"],
            "email_id": email_id,
            "thread_id": source["thread_id"],
            "labels": a["labels"] if accepted else [],
            "status": "ai_silver" if accepted else "excluded_uncertain",
            "training_provenance": "ai_silver" if accepted else None,
            "acceptance_rule": (
                "exact_unflagged_blind_agreement_supervisor_spot_audit" if accepted
                else "supervisor_scope_exclusion" if email_id in SUPERVISOR_EXCLUSIONS
                else "disagreement_or_review_flag"
            ),
        })
    return decisions


if __name__ == "__main__":
    rows = adjudicate()
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") != content:
        raise ValueError("existing decision manifest differs; inspect before overwriting")
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"{OUTPUT}: {sum(row['status'] == 'ai_silver' for row in rows)} accepted")

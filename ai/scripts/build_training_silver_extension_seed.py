"""Select a disjoint, leakage-aware Enron extension for blind AI review.

Regexes are screening cues only. They never produce labels. Raw source text is
written solely to the ignored seed; the committed manifest is ID/hash only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.models.silver_classifier import extract_authored_prefix

FULL = AI_DIR / "data/interim/enron_full.jsonl"
GROUPS = AI_DIR / "data/interim/leakage_groups.jsonl"
PREVIOUS = AI_DIR / "annotation/training_silver_1400_manifest.json"
OUTPUT = AI_DIR / "data/annotated/ai/training_silver_extension_1200/annotation_seed_1200.jsonl"
MANIFEST = AI_DIR / "annotation/training_silver_extension_1200_manifest.json"
SELECTION_SEED = "fyp-silver-extension-20260928-v1"

QUOTAS = {
    "document_request_cue": 185,
    "department_input_cue": 145,
    "approval_cue": 120,
    "followup_cue": 120,
    "deadline_cue": 120,
    "meeting_cue": 120,
    "other_project_cue": 340,
    "pm_cue_no_project_marker": 50,
}
RARE_PROJECT_QUOTAS = {
    "document_request_cue": 120,
    "department_input_cue": 100,
    "approval_cue": 90,
    "followup_cue": 90,
    "deadline_cue": 90,
    "meeting_cue": 90,
    "other_project_cue": 20,
    "pm_cue_no_project_marker": 0,
}
PROJECT = re.compile(r"\b(project|implementation|migration|pilot|rollout|workstream|phase\s+[ivx0-9]+|remediation|development|launch|construction)\b", re.I)
DOC = re.compile(r"\b(report|presentation|project plan|meeting minutes|proposal|budget|forecast|deliverable|documentation|document)\b", re.I)
REQUEST = re.compile(r"\b(please|could you|would you|need|request|send|submit|prepare|provide|share|deliver|forward|complete)\b", re.I)
DEPARTMENT = re.compile(r"\b(finance|marketing|legal|engineering|operations|risk|technology|IT|HR|human resources|compliance|accounting)\b", re.I)
INPUT = re.compile(r"\b(input|feedback|estimate|figures|data|comments|review|contribution|testing|approval|decision)\b", re.I)
APPROVAL = re.compile(r"\b(approve|approved|approval|authorize|authorization|sign.?off|consent)\b", re.I)
FOLLOWUP = re.compile(r"\b(follow.?up|remind|reminder|outstanding|still waiting|status of|update on|checking in)\b", re.I)
DEADLINE = re.compile(r"\b(deadline|due|by (?:monday|tuesday|wednesday|thursday|friday|tomorrow|[0-9]{1,2}/[0-9]{1,2})|no later than|end of day|COB)\b", re.I)
MEETING = re.compile(r"\b(meeting|conference call|status call|design review|planning session|workshop)\b", re.I)
PM_CUE = re.compile(r"\b(meeting|deadline|due|approve|approval|report|action|review|plan|status update|follow.?up)\b", re.I)


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def stable_rank(email_id: str, selection_seed: str = SELECTION_SEED) -> str:
    return hashlib.sha256((selection_seed + ":" + email_id).encode("utf-8")).hexdigest()


def screening_stratum(row: dict) -> str | None:
    body = extract_authored_prefix(row["current_message"])
    if not 100 <= len(body) <= 3500:
        return None
    if body.startswith(("CALENDAR ENTRY", "TASK ASSIGNMENT")):
        return None
    if "Forwarded by" in body[:150] or "Click Here To Download" in body[:400]:
        return None
    # Current authored content is the label target. A project word deep in a
    # forwarded thread or corporate signature is weak evidence for screening.
    text = row["subject"] + "\n" + body[:450]
    scoped = bool(PROJECT.search(text))
    if not scoped:
        return "pm_cue_no_project_marker" if PM_CUE.search(text) else None
    if DOC.search(text) and REQUEST.search(body):
        return "document_request_cue"
    if DEPARTMENT.search(text) and INPUT.search(body):
        return "department_input_cue"
    if APPROVAL.search(body):
        return "approval_cue"
    if FOLLOWUP.search(body):
        return "followup_cue"
    if DEADLINE.search(body):
        return "deadline_cue"
    if MEETING.search(body):
        return "meeting_cue"
    return "other_project_cue" if PM_CUE.search(text) else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("balanced", "rare_project"), default="balanced")
    parser.add_argument("--additional-prior-manifest", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--selection-name", default="training_silver_extension_1200_v1")
    parser.add_argument("--selection-seed", default=SELECTION_SEED)
    args = parser.parse_args()
    quotas = QUOTAS if args.profile == "balanced" else RARE_PROJECT_QUOTAS
    prior_ids = set()
    for path in (PREVIOUS, *args.additional_prior_manifest):
        prior_manifest = json.loads(path.read_text(encoding="utf-8"))
        prior_ids.update(row["email_id"] for row in prior_manifest["records"])
    for path in (AI_DIR / "annotation/training_expansion_100_ids.json",
                 AI_DIR / "annotation/project_pilot_50_v2_ids.json",
                 AI_DIR / "annotation/project_pilot_50_ids.json",
                 AI_DIR / "data/annotated/human/label_studio_seed/manifest.json"):
        prior_ids.update(json.loads(path.read_text(encoding="utf-8"))["selected_email_ids"])
    group_by_id = {}
    for row in read_jsonl(GROUPS):
        if row["source_dataset"] == "enron":
            group_by_id[row["email_id"]] = row["leakage_group_id"]
    if not prior_ids <= set(group_by_id):
        raise ValueError("prior IDs missing from full-corpus leakage sidecar")
    banned_groups = {group_by_id[email_id] for email_id in prior_ids}

    # Keep a deterministic rank shortlist per stratum, with room for duplicate
    # and leakage-group exclusions. Classification is never inferred here.
    shortlists: dict[str, list[tuple[str, dict]]] = {key: [] for key in quotas}
    counts = Counter()
    for row in read_jsonl(FULL):
        email_id = row["email_id"]
        group = group_by_id.get(email_id)
        if group is None:
            raise ValueError(f"full source ID absent from leakage sidecar: {email_id}")
        if email_id in prior_ids or group in banned_groups:
            continue
        stratum = screening_stratum(row)
        if stratum is None:
            continue
        counts[stratum] += 1
        if quotas[stratum] == 0:
            continue
        bucket = shortlists[stratum]
        bucket.append((stable_rank(email_id, args.selection_seed), row))
        if len(bucket) > quotas[stratum] * 8:
            bucket.sort(key=lambda item: item[0])
            del bucket[quotas[stratum] * 4:]

    selected: list[tuple[str, dict]] = []
    used_groups = set(banned_groups)
    used_bodies: set[str] = set()
    for stratum, quota in quotas.items():
        if quota == 0:
            continue
        for _, row in sorted(shortlists[stratum], key=lambda item: item[0]):
            group = group_by_id[row["email_id"]]
            body = " ".join(row["current_message"].split()).casefold()
            if group in used_groups or body in used_bodies:
                continue
            selected.append((stratum, row))
            used_groups.add(group)
            used_bodies.add(body)
            if sum(item[0] == stratum for item in selected) == quota:
                break
    if len(selected) != sum(quotas.values()):
        actual = Counter(category for category, _ in selected)
        raise ValueError(f"only {len(selected)} records met disjoint stratum quotas: {dict(actual)}; screening pool: {dict(counts)}")
    # Interleave strata to make every 300-row annotation tranche diverse.
    by_stratum = {key: [row for category, row in selected if category == key] for key in quotas}
    ordered: list[tuple[str, dict]] = []
    while any(by_stratum.values()):
        for stratum in quotas:
            if by_stratum[stratum]:
                ordered.append((stratum, by_stratum[stratum].pop(0)))

    seed_content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for _, row in ordered)
    manifest = {
        "manifest_version": "1.0.0",
        "selection_name": args.selection_name,
        "selection_seed": args.selection_seed,
        "status": "screening_only_pending_blind_review",
        "selection_rationale": (
            "Deterministic project-context and PM-function cue screening, with 50 cue-bearing hard-negative candidates. No screening cue assigns a label. Every selected full-source leakage component is unique and disjoint from previously selected IDs/components."
            if args.profile == "balanced" else
            "Deterministic rare-function project-context cue screening to improve REPORT_REQUEST, DEPARTMENTAL_INPUT, APPROVAL, FOLLOW_UP, DEADLINE, and MEETING coverage. Cues never assign labels. Every full-source leakage component is unique and disjoint from prior selections."
        ),
        "source_dataset": "enron",
        "source_file": "ai/data/interim/enron_full.jsonl",
        "leakage_sidecar": "ai/data/interim/leakage_groups.jsonl",
        "selected_count": len(ordered),
        "screening_pool_counts": dict(sorted(counts.items())),
        "screening_quotas": quotas,
        "records": [
            {"order": index, "email_id": row["email_id"], "thread_id": row["thread_id"],
             "source_dataset": row["source_dataset"], "screening_stratum": stratum,
             "current_chars": len(row["current_message"]),
             "current_sha256": hashlib.sha256(row["current_message"].encode("utf-8")).hexdigest(),
             "leakage_group_id": group_by_id[row["email_id"]]}
            for index, (stratum, row) in enumerate(ordered, 1)
        ],
    }
    manifest_content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and args.output.read_text(encoding="utf-8") != seed_content:
        raise ValueError("existing extension seed differs; refusing overwrite")
    if args.manifest.exists() and args.manifest.read_text(encoding="utf-8") != manifest_content:
        raise ValueError("existing extension manifest differs; refusing overwrite")
    args.output.write_text(seed_content, encoding="utf-8", newline="\n")
    args.manifest.write_text(manifest_content, encoding="utf-8", newline="\n")
    print(f"selected {len(ordered)} disjoint screening candidates; seed={args.output}; manifest={args.manifest}")


if __name__ == "__main__":
    main()

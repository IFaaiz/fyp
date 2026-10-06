"""Freeze a reviewed, unlabelled FYP calibration proposal from safe TRAIN only.

The candidate pool and manual rank decisions live under ignored ai/data. This
source-free script revalidates the boundary and every candidate fingerprint
before using any message text, then writes private imports and aggregate-only
reports. It never reads protected or alternate corpus files.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai"))
sys.path.insert(0, str(ROOT / "ai/scripts"))

from src.structured_annotation.workflow import (  # noqa: E402
    _load_boundary,
    _normalize_record,
    _verify_candidate_index_fingerprint,
    _verify_train_isolation,
    sha256_file,
)
import prepare_fyp_calibration_v1 as prep  # noqa: E402


SOURCE = ROOT / "ai/data/experiments/structured_v2_candidates_20261002_v2/isolated_v2/train_screen_candidates.jsonl"
BOUNDARY = ROOT / "ai/data/experiments/structured_v2_candidates_20261002_v2/isolated_v2/boundary_manifest.json"
INDEX = ROOT / "ai/data/processed/structured_v2_expanded_leakage_index_v2.json"
PRIVATE_DIR = ROOT / "ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private"
SCREENED_POOL = PRIVATE_DIR / "screened_candidates_private.jsonl"
MANUAL_SELECTION = PRIVATE_DIR / "manual_selection_private.json"
SOURCE_REVIEW = PRIVATE_DIR / "source_review_private.json"
AUDIT_DECISIONS = PRIVATE_DIR / "manual_audit_decisions_private.json"
REPORT = ROOT / "ai/reports/fyp_calibration_v1_curation_iteration2.md"
SEED = "fyp-calibration-v1-iteration2-20261006"

ALLOCATION_ORDER = ("blind_agreement", "calibration_training", "labeler_human_holdout")
CLASS_ORDER = (
    "commercial_transaction_or_contract",
    "initiative_design_delivery",
    "planning_status_analysis_or_event",
    "policy_regulatory_or_standards",
)

QUOTED_PREFIX_MARKERS = (
    re.compile(r"^\s*>"),
    re.compile(r"^\s*-{2,}\s*(?:original|forwarded)", re.I),
    re.compile(r"^\s*(?:from|sent|to|cc|subject):\s*\S", re.I),
)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl_new(path: Path, rows: list[dict[str, Any]]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return sha256_file(path)


def deterministic_key(value: str, purpose: str) -> str:
    return digest_text(f"{SEED}\0{purpose}\0{value}")


def apportion_classes(
    class_sizes: Counter[str], allocation_targets: dict[str, int],
) -> dict[str, dict[str, int]]:
    """Apportion exact allocation totals across evidence classes by largest remainder."""
    total = sum(class_sizes.values())
    if total <= 0 or sum(allocation_targets.values()) != total:
        raise ValueError("class sizes and allocation targets must have the same positive total")
    matrix: dict[str, dict[str, int]] = {name: {} for name in class_sizes}
    row_remaining: dict[str, int] = {}
    col_remaining = dict(allocation_targets)
    fractional: dict[tuple[str, str], float] = {}
    for class_name, class_size in class_sizes.items():
        row_remaining[class_name] = class_size
        for allocation, count in allocation_targets.items():
            ideal = class_size * count / total
            base = int(ideal)
            matrix[class_name][allocation] = base
            row_remaining[class_name] -= base
            col_remaining[allocation] -= base
            fractional[(class_name, allocation)] = ideal - base
    extras_given: set[tuple[str, str]] = set()
    while sum(row_remaining.values()):
        options = [
            (fractional[(class_name, allocation)], class_name, allocation)
            for class_name in class_sizes
            for allocation in allocation_targets
            if row_remaining[class_name] > 0
            and col_remaining[allocation] > 0
            and (class_name, allocation) not in extras_given
        ]
        if not options:
            raise ValueError("could not apportion evidence classes to allocation totals")
        _, class_name, allocation = max(options, key=lambda item: (item[0], item[1], item[2]))
        matrix[class_name][allocation] += 1
        row_remaining[class_name] -= 1
        col_remaining[allocation] -= 1
        extras_given.add((class_name, allocation))
    if any(col_remaining.values()):
        raise ValueError(f"allocation apportionment mismatch: {col_remaining}")
    return matrix


def proportional_sample_sizes(class_sizes: Counter[str], sample_size: int) -> dict[str, int]:
    """Choose an exact stratified sample size from a larger candidate pool."""
    total = sum(class_sizes.values())
    if sample_size < 0 or sample_size > total:
        raise ValueError("stratified sample size is outside its candidate pool")
    if sample_size == 0:
        return {name: 0 for name in class_sizes}
    sizes: dict[str, int] = {}
    fractions: dict[str, float] = {}
    for class_name, count in class_sizes.items():
        ideal = count * sample_size / total
        sizes[class_name] = int(ideal)
        fractions[class_name] = ideal - sizes[class_name]
    remaining = sample_size - sum(sizes.values())
    for class_name in sorted(class_sizes, key=lambda name: (fractions[name], name), reverse=True)[:remaining]:
        sizes[class_name] += 1
    return sizes


def select_common_audit_rows(
    common_rows: list[dict[str, Any]],
    private_meta_by_source: dict[str, dict[str, Any]],
    audit_size: int = 20,
) -> list[dict[str, Any]]:
    size = min(audit_size, len(common_rows))
    controls = [row for row in common_rows if private_meta_by_source[row["source_id"]]["curation_class_private"] == "scope_boundary_negative"]
    if len(controls) > size:
        raise ValueError("common audit sample cannot contain every boundary control")
    project_rows = [row for row in common_rows if row not in controls]
    remaining = size - len(controls)
    class_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in project_rows:
        class_rows[private_meta_by_source[row["source_id"]]["curation_class_private"]].append(row)
    class_sizes = Counter({name: len(items) for name, items in class_rows.items()})
    if remaining > sum(class_sizes.values()):
        raise ValueError("common agreement pool is too small for the audit sample")
    # Oversample the available project classes proportionally; all three
    # scope-boundary controls are included when present.
    sample_sizes = proportional_sample_sizes(class_sizes, remaining)
    chosen = list(controls)
    for class_name, candidates in class_rows.items():
        candidates.sort(key=lambda row: deterministic_key(
            private_meta_by_source[row["source_id"]]["component_id"], "root-audit-" + class_name,
        ))
        chosen.extend(candidates[:sample_sizes[class_name]])
    chosen.sort(key=lambda row: int(row["position"]))
    if len(chosen) != size:
        raise ValueError("root audit sample size does not match its plan")
    return chosen


def main() -> None:
    data_root = (ROOT / "ai/data").resolve()
    if PRIVATE_DIR.resolve().parent != (data_root / "experiments/fyp_calibration_v1_20261005").resolve():
        raise ValueError("private artifacts must remain beneath the designated ignored experiments directory")
    if any(path.exists() for path in (
        PRIVATE_DIR / "site_import.jsonl",
        PRIVATE_DIR / "site_import_train_common.jsonl",
        PRIVATE_DIR / "site_import_holdout.jsonl",
        PRIVATE_DIR / "manual_audit_train_common_20_private.jsonl",
        PRIVATE_DIR / "calibration_sources_train_common.jsonl",
        PRIVATE_DIR / "calibration_sources_holdout.jsonl",
        PRIVATE_DIR / "selection_metadata_private.jsonl",
        PRIVATE_DIR / "curation_manifest.json",
        PRIVATE_DIR / "holdout_manifest.json",
        PRIVATE_DIR / "allocation_manifest_private.json",
        PRIVATE_DIR / "audit_rollup_private.json",
        REPORT,
    )):
        raise FileExistsError("refusing to overwrite a frozen curation artifact")

    # Boundary/index integrity, global isolation, and exact source fingerprint
    # checks run before any candidate message body is parsed or inspected.
    index_payload, boundary, index_sha, boundary_sha = _load_boundary(
        index_path=INDEX,
        assignments_path=BOUNDARY,
        dataset_id="enron",
        root=ROOT,
    )
    _verify_train_isolation(index_payload, boundary)
    source_sha = sha256_file(SOURCE)
    if source_sha != boundary.get("train_screen_candidates_sha256"):
        raise ValueError("source does not match the frozen isolated_v2 TRAIN_SCREEN bytes")
    if boundary.get("index_path") != INDEX.resolve().relative_to(ROOT).as_posix():
        raise ValueError("boundary manifest names a different global leakage index")

    rows = read_jsonl(SOURCE)
    if len(rows) != 4_285:
        raise ValueError(f"unexpected isolated TRAIN_SCREEN row count: {len(rows)}")
    protected = set(boundary.get("protected_global_ids", []))
    source_ids: set[str] = set()
    for row in rows:
        source_id = row.get("source_id")
        if (
            row.get("source_dataset") != "enron"
            or not isinstance(source_id, str)
            or row.get("email_id") != source_id
            or source_id in source_ids
        ):
            raise ValueError("TRAIN_SCREEN canonical source metadata is invalid or duplicated")
        source_ids.add(source_id)
        qualified = "enron:" + source_id
        if boundary["partitions"].get(qualified) != "TRAIN_SCREEN" or qualified in protected:
            raise ValueError("candidate row is outside TRAIN_SCREEN or also protected")
        if qualified not in index_payload["records"]:
            raise ValueError("TRAIN_SCREEN row is missing from the frozen leakage index")
    for row in rows:
        qualified = "enron:" + str(row["source_id"])
        _verify_candidate_index_fingerprint(
            normalized_record=_normalize_record(row),
            index_record=index_payload["records"][qualified],
        )

    # Recreate and cross-check the private retrieval pool only after the
    # boundary, row partition, and every text fingerprint have passed.
    component_ids = prep.assign_components(rows, index_payload["records"])
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        full_text, authored_ranges, non_authored_tail = prep.authored_offsets(str(row.get("current_message") or ""))
        if not authored_ranges:
            continue
        authored = full_text[authored_ranges[0]["start"]:authored_ranges[0]["end"]]
        cues = prep.source_cues(str(row.get("subject") or ""), authored)
        tier = prep.tier_for(cues, authored)
        if tier is None:
            continue
        component = component_ids["enron:" + str(row["source_id"])]
        candidate = {
            "row": row,
            "full_text": full_text,
            "authored_ranges": authored_ranges,
            "non_authored_tail": non_authored_tail,
            "cues": cues,
            "tier": tier,
            "score": prep.rank_candidate(row, cues),
            "component_id": component,
        }
        previous = grouped.get(component)
        if previous is None or (candidate["score"], row["source_id"]) > (
            previous["score"], previous["row"]["source_id"],
        ):
            grouped[component] = candidate
    tier_order = {"project_context": 0, "project_adjacent": 1, "scope_boundary": 2}
    ranked = sorted(
        grouped.values(),
        key=lambda item: (
            -item["score"],
            tier_order[item["tier"]],
            prep.deterministic_key(item["component_id"], "rank"),
        ),
    )
    if sha256_file(SCREENED_POOL) != json.loads(MANUAL_SELECTION.read_text(encoding="utf-8"))["screened_candidates_sha256"]:
        raise ValueError("manual decisions are not bound to the frozen private retrieval pool")
    private_pool = read_jsonl(SCREENED_POOL)
    if len(private_pool) != len(ranked):
        raise ValueError("private retrieval pool size differs from the verified source screen")
    for rank, (candidate, frozen) in enumerate(zip(ranked, private_pool), start=1):
        current_text_sha = digest_text(candidate["full_text"])
        if (
            frozen.get("retrieval_rank_private") != rank
            or frozen.get("source_id") != candidate["row"]["source_id"]
            or frozen.get("source_sha256") != current_text_sha
            or frozen.get("tier_private") != candidate["tier"]
            or frozen.get("score_private") != candidate["score"]
            or frozen.get("authored_ranges") != candidate["authored_ranges"]
        ):
            raise ValueError("private retrieval pool no longer matches verified TRAIN_SCREEN text")

    selection = json.loads(MANUAL_SELECTION.read_text(encoding="utf-8"))
    review = json.loads(SOURCE_REVIEW.read_text(encoding="utf-8"))
    audit_decisions = json.loads(AUDIT_DECISIONS.read_text(encoding="utf-8"))
    selected_ranks = list(selection["keep_retrieval_ranks"])
    boundary_ranks = list(selection["boundary_control_ranks"])
    if len(set(selected_ranks + boundary_ranks)) != len(selected_ranks) + len(boundary_ranks):
        raise ValueError("manual selection contains duplicate component ranks")
    if selected_ranks != sorted(selected_ranks) or boundary_ranks != sorted(boundary_ranks):
        raise ValueError("manual selection rank order must be stable")
    if len(review.get("selected_sources", [])) != len(selected_ranks) + len(boundary_ranks):
        raise ValueError("manual source-review ledger count differs from selected ranks")
    if len(audit_decisions.get("decisions", [])) != 20:
        raise ValueError("the curation audit must contain exactly 20 decisions")
    audit_counts = Counter(item["manual_decision"] for item in audit_decisions["decisions"])
    if audit_counts != Counter({"keep": 13, "drop": 7}):
        raise ValueError("manual audit decision rollup differs from the reviewed evidence")

    pool_by_rank = {item["retrieval_rank_private"]: item for item in private_pool}
    review_by_rank = {item["retrieval_rank_private"]: item for item in review["selected_sources"]}
    if set(review_by_rank) != set(selected_ranks + boundary_ranks):
        raise ValueError("source-review ledger does not match the manually selected component ranks")
    if len({item["source_id"] for item in review["selected_sources"]}) != len(review["selected_sources"]):
        raise ValueError("manual selection contains duplicate source IDs")

    selected: list[dict[str, Any]] = []
    for rank in selected_ranks + boundary_ranks:
        frozen = pool_by_rank[rank]
        evidence = review_by_rank[rank]
        if evidence["source_id"] != frozen["source_id"]:
            raise ValueError("manual evidence note is bound to a different source row")
        candidate = ranked[rank - 1]
        authored = candidate["full_text"][candidate["authored_ranges"][0]["start"]:candidate["authored_ranges"][0]["end"]]
        if any(marker.search(line) for line in authored.splitlines() for marker in QUOTED_PREFIX_MARKERS):
            raise ValueError("selected authored range contains an obvious forwarded/quoted-message marker")
        source_row = candidate["row"]
        if source_row.get("source_thread_verified") is True and source_row.get("source_thread_id"):
            raise ValueError("unexpected verified Enron thread context; do not invent or export it")
        selected.append({
            **candidate,
            "retrieval_rank_private": rank,
            "curation_decision_private": evidence["decision"],
            "curation_class_private": evidence["primary_evidence_class_private"],
            "evidence_summary_private": evidence["evidence_summary_private"],
        })

    expected_project_count = len(selected_ranks)
    expected_control_count = len(boundary_ranks)
    if expected_control_count > 0.15 * len(selected):
        raise ValueError("scope-boundary controls exceed the 15% cap")
    if expected_project_count + expected_control_count != len(selected):
        raise ValueError("selected project and boundary-control counts do not reconcile")

    # Allocate every boundary control to the three-reviewer blind common set.
    policy = selection.get("allocation_policy", {
        "blind_fraction": 0.50,
        "holdout_fraction": 0.24,
        "minimum_blind_common": 20,
    })
    total_count = len(selected)
    blind_count = min(total_count - 2, max(int(policy["minimum_blind_common"]), round(total_count * policy["blind_fraction"])))
    holdout_count = max(1, round(total_count * policy["holdout_fraction"]))
    holdout_count = min(holdout_count, total_count - blind_count - 1)
    training_count = total_count - blind_count - holdout_count
    if blind_count < expected_control_count or training_count < 1 or holdout_count < 1:
        raise ValueError("dynamic allocation cannot fit common controls, training, and holdout")
    project_allocation_targets = {
        "blind_agreement": blind_count - expected_control_count,
        "calibration_training": training_count,
        "labeler_human_holdout": holdout_count,
    }
    project_items = [item for item in selected if item["curation_decision_private"] == "include_project_related"]
    control_items = [item for item in selected if item["curation_decision_private"] == "include_boundary_control_nonproject"]
    if len(project_items) != expected_project_count or len(control_items) != expected_control_count:
        raise ValueError("manual project/boundary classifications do not match selected totals")
    class_sizes = Counter(item["curation_class_private"] for item in project_items)
    class_matrix = apportion_classes(class_sizes, project_allocation_targets)
    project_by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in project_items:
        project_by_class[item["curation_class_private"]].append(item)
    for class_name, class_candidates in project_by_class.items():
        class_candidates.sort(key=lambda item: deterministic_key(item["component_id"], "allocation-" + class_name))
        cursor = 0
        for allocation in ALLOCATION_ORDER:
            count = class_matrix[class_name][allocation]
            for item in class_candidates[cursor:cursor + count]:
                item["allocation"] = allocation
            cursor += count
        if cursor != len(class_candidates):
            raise ValueError("class allocation did not consume all manually reviewed project sources")
    for item in control_items:
        item["allocation"] = "blind_agreement"

    allocation_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        allocation_rows[item["allocation"]].append(item)
    allocation_counts = {name: len(allocation_rows[name]) for name in ALLOCATION_ORDER}
    if allocation_counts != {
        "blind_agreement": blind_count,
        "calibration_training": training_count,
        "labeler_human_holdout": holdout_count,
    }:
        raise ValueError(f"dynamic allocation totals differ: {allocation_counts}")

    ordered: list[dict[str, Any]] = []
    for allocation in ALLOCATION_ORDER:
        subset = allocation_rows[allocation]
        subset.sort(key=lambda item: deterministic_key(item["component_id"], "position-" + allocation))
        ordered.extend(subset)
    for position, item in enumerate(ordered):
        item["position"] = position

    site_import: list[dict[str, Any]] = []
    curator_export: list[dict[str, Any]] = []
    private_metadata: list[dict[str, Any]] = []
    for item in ordered:
        source_row = item["row"]
        source_id = str(source_row["source_id"])
        allocation = item["allocation"]
        common_blind = allocation == "blind_agreement"
        local_position = sum(1 for prior in allocation_rows[allocation] if prior["position"] < item["position"])
        owner_slot = None if common_blind else local_position % 3
        body = item["full_text"]
        source_sha256 = digest_text(str(source_row.get("subject") or "") + "\n" + body)
        site_row = {
            "source_id": source_id,
            "subject": str(source_row.get("subject") or ""),
            "current_message": body,
            "authored_ranges": item["authored_ranges"],
            "source_sha256": source_sha256,
            "allocation": allocation,
            "position": item["position"],
            "common_blind": common_blind,
            "owner_slot": owner_slot,
        }
        site_import.append(site_row)
        item["site_row"] = site_row
        curator_export.append({
            "source_id": source_id,
            "canonical_email_id": str(source_row["email_id"]),
            "subject": site_row["subject"],
            "current_message": body,
            "authored_ranges": item["authored_ranges"],
            "non_authored_tail_reference_only": item["non_authored_tail"],
            "origin": "public_corpus:Enron Email Dataset",
            "source_hash": source_sha256,
            "source_text_sha256": digest_text(body),
            "component_id": item["component_id"],
            "allocation": allocation,
            "sampling_provenance": "fyp_calibration_v1_iteration2_manual_scope_review",
        })
        private_metadata.append({
            "source_id": source_id,
            "position": item["position"],
            "component_id": item["component_id"],
            "allocation": allocation,
            "private_retrieval_tier": item["tier"],
            "private_retrieval_score": item["score"],
            "private_retrieval_hints": {
                "scope_terms": item["cues"]["anchors"],
                "function_cues": item["cues"]["function_cues"],
                "explicit_request_or_assignment": item["cues"]["explicit_request_or_assignment"],
            },
            "curation_class_private": item["curation_class_private"],
            "curator_evidence_summary_private": item["evidence_summary_private"],
            "source_sha256": source_sha256,
        })

    site_by_id = {row["source_id"]: row for row in site_import}
    metadata_by_id = {row["source_id"]: row for row in private_metadata}
    owner_counts = {
        allocation: {str(slot): sum(
            1 for row in allocation_rows[allocation]
            if row["site_row"]["owner_slot"] == slot
        ) for slot in range(3)}
        for allocation in ("calibration_training", "labeler_human_holdout")
    }
    train_common_rows = [site_by_id[item["row"]["source_id"]] for item in ordered if item["allocation"] != "labeler_human_holdout"]
    holdout_rows = [site_by_id[item["row"]["source_id"]] for item in ordered if item["allocation"] == "labeler_human_holdout"]
    blind_rows = [site_by_id[item["row"]["source_id"]] for item in ordered if item["allocation"] == "blind_agreement"]
    audit_rows = select_common_audit_rows(blind_rows, metadata_by_id, audit_size=20)
    curator_by_id = {row["source_id"]: row for row in curator_export}
    train_common_curator = [curator_by_id[row["source_id"]] for row in train_common_rows]
    holdout_curator = [curator_by_id[row["source_id"]] for row in holdout_rows]

    allocation_hashes = {
        allocation: digest_text("\n".join(
            f"{row['source_id']}\t{row['source_sha256']}"
            for row in site_import if row["allocation"] == allocation
        ))
        for allocation in ALLOCATION_ORDER
    }
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    site_sha = write_jsonl_new(PRIVATE_DIR / "site_import.jsonl", site_import)
    train_common_sha = write_jsonl_new(PRIVATE_DIR / "site_import_train_common.jsonl", train_common_rows)
    holdout_sha = write_jsonl_new(PRIVATE_DIR / "site_import_holdout.jsonl", holdout_rows)
    audit_sha = write_jsonl_new(PRIVATE_DIR / "manual_audit_train_common_20_private.jsonl", audit_rows)
    curator_common_sha = write_jsonl_new(PRIVATE_DIR / "calibration_sources_train_common.jsonl", train_common_curator)
    curator_holdout_sha = write_jsonl_new(PRIVATE_DIR / "calibration_sources_holdout.jsonl", holdout_curator)
    private_sha = write_jsonl_new(PRIVATE_DIR / "selection_metadata_private.jsonl", private_metadata)

    boundary_partition_counts = Counter(boundary["partitions"].values())
    evidence_counts = Counter(item["curation_class_private"] for item in project_items)
    audit_rollup = {
        "status": "reviewed_retrieval_audit_not_a_prevalence_estimate",
        "audit_count": len(audit_decisions["decisions"]),
        "keep_count": audit_counts["keep"],
        "drop_count": audit_counts["drop"],
        "keep_evidence_groups": {
            "commercial_proposal_or_contract_with_current_negotiation_steps": 5,
            "bounded_initiative_meeting_status_or_technical_work": 5,
            "regulatory_or_policy_deliverable_and_followup": 3,
        },
        "drop_evidence_groups": {
            "personal_job_or_travel_message": 2,
            "market_broadcast_or_routine_training_invitation": 2,
            "generic_legal_service_or_finance_transaction_without_project_scope": 3,
        },
        "sample_design": audit_decisions["sampling_design"],
        "source_ids_or_message_text_included": False,
    }
    (PRIVATE_DIR / "audit_rollup_private.json").write_text(
        json.dumps(audit_rollup, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    allocation_manifest = {
        "status": "frozen_allocations_pending_root_common_audit",
        "allocation_counts": allocation_counts,
        "blind_common_count": allocation_counts["blind_agreement"],
        "personal_owner_counts": owner_counts,
        "common_audit_sample_count": len(audit_rows),
        "common_audit_sample_sha256": audit_sha,
        "groups_split_across_allocations": 0,
        "scope_boundary_control_count": expected_control_count,
        "scope_boundary_control_fraction": expected_control_count / total_count,
        "labels_present": False,
        "ai_prelabels_present": False,
    }
    (PRIVATE_DIR / "allocation_manifest_private.json").write_text(
        json.dumps(allocation_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    holdout_manifest = {
        "status": "sealed_unlabelled_holdout_pending_import",
        "source_count": len(holdout_rows),
        "source_ids_and_hashes_sha256": allocation_hashes["labeler_human_holdout"],
        "site_import_holdout_sha256": holdout_sha,
        "curator_export_holdout_sha256": curator_holdout_sha,
        "group_component_count": len({item["component_id"] for item in private_metadata if item["allocation"] == "labeler_human_holdout"}),
        "selection_frozen_before_labeler_prototype": True,
        "labels_present": False,
        "ai_prelabels_present": False,
        "holdout_source_text_in_common_audit": False,
    }
    (PRIVATE_DIR / "holdout_manifest.json").write_text(
        json.dumps(holdout_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    manifest = {
        "status": "frozen_private_proposal_pending_root_common_audit",
        "run_id": "fyp_calibration_v1_iteration2_20261006",
        "created_from": {
            "source_path": SOURCE.resolve().relative_to(ROOT).as_posix(),
            "source_sha256": source_sha,
            "boundary_path": BOUNDARY.resolve().relative_to(ROOT).as_posix(),
            "boundary_sha256": boundary_sha,
            "index_path": INDEX.resolve().relative_to(ROOT).as_posix(),
            "index_sha256": index_sha,
        },
        "boundary_status": boundary.get("status"),
        "accepted_structured_annotations": boundary.get("accepted_structured_annotations"),
        "training_export_permitted": boundary.get("training_export_permitted"),
        "train_screen_rows_verified_before_text_review": len(rows),
        "source_dataset_counts": {"enron": len(site_import)},
        "protected_eval_reserved_count_verified_from_boundary_metadata_only": boundary_partition_counts.get("EVAL_RESERVED", 0),
        "protected_candidate_overlap": 0,
        "global_partition_conflicts": 0,
        "source_fingerprint_matches": len(rows),
        "selected_source_count": total_count,
        "selected_project_related_count": expected_project_count,
        "selected_scope_boundary_control_count": expected_control_count,
        "selected_scope_boundary_control_fraction": expected_control_count / total_count,
        "selected_component_count": len({item["component_id"] for item in selected}),
        "selected_verified_source_thread_count": sum(bool(item["row"].get("source_thread_verified")) for item in selected),
        "allocation_counts": allocation_counts,
        "primary_evidence_class_counts_private": dict(evidence_counts),
        "curation_audit_keep_count": audit_counts["keep"],
        "curation_audit_drop_count": audit_counts["drop"],
        "curation_audit_sample_count": len(audit_decisions["decisions"]),
        "curation_audit_sample_is_prevalence_estimate": False,
        "site_import_sha256": site_sha,
        "site_import_train_common_sha256": train_common_sha,
        "site_import_holdout_sha256": holdout_sha,
        "manual_audit_train_common_sha256": audit_sha,
        "calibration_sources_train_common_sha256": curator_common_sha,
        "calibration_sources_holdout_sha256": curator_holdout_sha,
        "selection_metadata_private_sha256": private_sha,
        "groups_split_across_allocations": 0,
        "leakage_grouping": "frozen global leakage components plus verified source threads when available plus normalized authored-prefix template groups; one representative per selected component",
        "thread_policy": "No selected Enron row has a verified source thread; no thread context was inferred or supplied.",
        "source_policy": "Only the hash-verified isolated_v2 TRAIN_SCREEN source was read. No protected or alternate corpus text was opened.",
        "quote_boundary_policy": "Repository authored-prefix extraction after line-ending normalization; selected prefixes contain no obvious forwarded/header/quote markers; remainder is curator-only reference and is not passed to the app.",
        "reviewer_payload_policy": "Site import rows contain source text and assignment fields only. Retrieval cues and curator evidence remain in a separate private sidecar.",
        "labels_present": False,
        "ai_prelabels_present": False,
        "synthetic_rows_in_real_email_count": 0,
        "annotation_support": "Unknown until human annotation; retrieval classes and curation categories are not labels or class support.",
        "site_import_performed": False,
        "limitation": "The Enron source is historical corporate mail; this enriched sample cannot establish project-domain prevalence or target-domain performance.",
    }
    (PRIVATE_DIR / "curation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    report = f"""# FYP calibration V1 source curation — iteration 2

Date: {date.today().isoformat()}

## Curation result

Prepared a **{total_count}-source unlabelled proposal** from the isolated Enron TRAIN_SCREEN pool. Manual review selected {expected_project_count} messages with current evidence of bounded project or initiative work, plus {expected_control_count} scope-boundary controls ({expected_control_count / total_count:.1%} of the proposal). The old 250-row and intermediate 187/190-row runs remain rejected and were not imported. This proposal has not been imported to the Site; root review of the common set is pending.

The {expected_project_count} project-related sources show four kinds of evidence: {evidence_counts['commercial_transaction_or_contract']} scoped acquisition or contract work with concrete negotiation steps; {evidence_counts['policy_regulatory_or_standards']} active policy, regulatory, or standards deliverables; {evidence_counts['initiative_design_delivery']} implementation, requirements, engineering, or process work; and {evidence_counts['planning_status_analysis_or_event']} project planning, status, modeling, or workshop work. A mention of “project” alone did not qualify a message. Current text needed to show an identifiable initiative and a present deliverable, decision, assignment, review, meeting, milestone, or substantive update. Generic contracts and routine business actions were not included as project sources.

## Manual curation audit

I read a deterministic stratified sample of 20 candidate messages: 10 from the earlier project-context tier, 5 from project-adjacent, and 5 from scope-boundary retrieval. The review retained **{audit_counts['keep']}** and rejected **{audit_counts['drop']}**. This is a judgment check over retrieval candidates, not an estimate of source-pool prevalence.

Retained messages had direct evidence such as an acquisition proposal that led into a defined purchase discussion; contract edits tied to a named transaction; task-force work tied to an initiative; a pipeline status list that asked for completion or delay updates; a workshop program with planned dates; and regulatory work with comment deadlines, legal review, or a draft letter for stakeholder support. Rejected messages included a market-wide approval notice, a resume and job request, a personal travel booking, an annual seminar attendance note, a generic agreement offer, a plain agreement exchange without a bounded initiative, and instructions to transfer funds. Three of those rejected examples are retained only as explicit scope-boundary controls; market broadcasts, personal/HR notices, and routine social or training messages are excluded.

## Source boundary and assignment

All {len(rows):,} source rows were verified against the frozen boundary manifest and global leakage index before any message text was inspected. Every row maps to TRAIN_SCREEN, all source fingerprints match the index, the global isolation check found no partition conflicts, and none overlaps protected candidates. The boundary metadata records {boundary_partition_counts.get('EVAL_RESERVED', 0):,} protected evaluation-reserved records; their text was not opened. No native MailEx, old V1 test, reserved, or other dataset text was read.

The selected rows are {len({item['component_id'] for item in selected})} distinct leakage/thread/template components, with one representative per component and no component split across allocations. All selected Enron thread metadata is unverified, so no conversation context was inferred. The current authored range is stored as exact offsets into normalized `current_message`; obvious quoted/header markers were screened out of the selected prefixes. Any remaining tail is reference-only curator data and is absent from reviewer imports.

| Allocation | Sources | Owner slot 0 | Owner slot 1 | Owner slot 2 |
|---|---:|---:|---:|---:|
| Blind agreement (all three reviewers) | {allocation_counts['blind_agreement']} | — | — | — |
| Calibration training | {allocation_counts['calibration_training']} | {owner_counts['calibration_training']['0']} | {owner_counts['calibration_training']['1']} | {owner_counts['calibration_training']['2']} |
| Sealed human holdout | {allocation_counts['labeler_human_holdout']} | {owner_counts['labeler_human_holdout']['0']} | {owner_counts['labeler_human_holdout']['1']} | {owner_counts['labeler_human_holdout']['2']} |

The common blind set is shared by all three reviewers. Personal training and holdout sources are round-robin assigned. The {len(audit_rows)}-source root audit file contains only sources from the blind common set; it contains no holdout source text. Retrieval hints and evidence notes are stored separately and are not part of the Site payload.

## Private artifacts

- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/site_import.jsonl` — complete private import proposal, including the sealed allocation.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/site_import_train_common.jsonl` — blind and personal training sources only.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/site_import_holdout.jsonl` — separate unlabelled holdout import; do not use it for the common-source audit.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/manual_audit_train_common_20_private.jsonl` — {len(audit_rows)} blind-common sources for root review; no holdout text.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/curation_manifest.json` and `holdout_manifest.json` — aggregate counts and file digests; the holdout manifest contains no source text or individual source IDs.

## Limits

No consented current project or university email source was available in this input, so this remains a public-corpus fallback. The historical Enron energy-sector mail is enriched for relevant work and cannot establish modern project-domain prevalence. The boundary reports zero accepted structured annotations and does not authorize training export. All {total_count} source rows are unlabelled and have no AI prelabels; human label support, agreement, annotation time, and adjudication remain unknown.
"""
    with REPORT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(report)

    print(json.dumps({
        "status": manifest["status"],
        "selected": total_count,
        "project_related": expected_project_count,
        "boundary_controls": expected_control_count,
        "allocation_counts": allocation_counts,
        "curation_audit": {"keep": audit_counts["keep"], "drop": audit_counts["drop"]},
        "train_common_audit_count": len(audit_rows),
        "site_import_sha256": site_sha,
        "train_common_audit_sha256": audit_sha,
        "report": REPORT.relative_to(ROOT).as_posix(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()

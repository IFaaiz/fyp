"""Apply private root curation decisions to a fresh, unlabelled source packet.

Original proposals are immutable. This operation does not annotate emails and
never prints text, source IDs, reviewer identities or sealed holdout contents.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_ROOT = ROOT / "ai/data/experiments/fyp_calibration_v1_20261005"
ALLOCATIONS = ("blind_agreement", "calibration_training", "labeler_human_holdout")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(path: Path, values: list[dict]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as out:
        for value in values:
            out.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    return sha(path)


def private_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError("Curation inputs/outputs must stay in the ignored private experiment directory")
    return resolved


def finalize(proposal: Path, decisions_path: Path, output: Path) -> dict:
    proposal, decisions_path, output = map(private_path, (proposal, decisions_path, output))
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing final packet")
    original = json.loads((proposal / "curation_manifest.json").read_text(encoding="utf-8"))
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    import_path = proposal / "site_import.jsonl"
    if sha(import_path) != original["site_import_sha256"] or sha(import_path) != decisions["proposal_import_sha256"]:
        raise ValueError("Root decisions do not match the immutable proposal bytes")
    for name in ("source", "boundary", "index"):
        record = original["created_from"]
        if sha(ROOT / record[name + "_path"]) != record[name + "_sha256"]:
            raise ValueError("The original source boundary changed")
    if original["protected_candidate_overlap"] or original["global_partition_conflicts"]:
        raise ValueError("The source proposal is not isolated from protected data")
    if sha(proposal / "selection_metadata_private.jsonl") != original["selection_metadata_private_sha256"]:
        raise ValueError("Private proposal provenance changed")

    imports = rows(import_path)
    metadata = {row["source_id"]: row for row in rows(proposal / "selection_metadata_private.jsonl")}
    by_id = {row["source_id"]: row for row in imports}
    if len(by_id) != len(imports) or set(by_id) != set(metadata):
        raise ValueError("Proposal source identity is not unique or provenance is missing")
    reviewed = set(decisions["reviewed_train_common_source_ids"])
    expected_reviewed = {row["source_id"] for row in imports if row["allocation"] != "labeler_human_holdout"}
    if reviewed != expected_reviewed:
        raise ValueError("Every TRAIN/common source must have an explicit root review")
    drops = set(decisions["drop_source_ids"])
    if not drops <= reviewed:
        raise ValueError("Explicit source drops must come from the reviewed TRAIN/common set")
    overrides = {row["source_id"]: row["authored_ranges"] for row in decisions["authored_range_overrides"]}
    if set(overrides) != reviewed - drops:
        raise ValueError("Every retained TRAIN/common source needs reviewed authored ranges")
    for source_id, ranges in overrides.items():
        body = by_id[source_id]["current_message"]
        if not ranges or any(set(r) != {"start", "end"} or type(r["start"]) is not int or type(r["end"]) is not int
                             or not 0 <= r["start"] < r["end"] <= len(body) for r in ranges):
            raise ValueError("Invalid root-reviewed authored range")
        if any(left["end"] > right["start"] for left, right in zip(ranges, ranges[1:])):
            raise ValueError("Authored ranges must be ordered and disjoint")

    retained = [row for row in imports if row["source_id"] not in drops]
    # Conservative additional blocking of named initiatives found in root's
    # TRAIN/common review. Matching holdout sources are removed without showing
    # their bodies or moving them into labeler development prompts.
    patterns = [re.compile(value, re.I) for value in decisions.get("named_topic_patterns_private", [])]
    topic_groups: dict[int, list[dict]] = defaultdict(list)
    for row in retained:
        for number, pattern in enumerate(patterns):
            if pattern.search(row["subject"] + "\n" + row["current_message"]):
                topic_groups[number].append(row)
    heldout_overlap_drops: set[str] = set()
    for number, group in topic_groups.items():
        allocations = {row["allocation"] for row in group}
        if "labeler_human_holdout" in allocations and len(allocations) > 1:
            heldout_overlap_drops.update(row["source_id"] for row in group if row["allocation"] == "labeler_human_holdout")
        if "blind_agreement" in allocations and "calibration_training" in allocations:
            for row in group:
                if row["allocation"] == "calibration_training":
                    row["allocation"] = "blind_agreement"
        for row in group:
            metadata[row["source_id"]]["root_topic_block_private"] = hashlib.sha256(str(number).encode()).hexdigest()
    retained = [row for row in retained if row["source_id"] not in heldout_overlap_drops]
    if not retained:
        raise ValueError("No sources survived the root gate")
    counts = Counter(row["allocation"] for row in retained)
    if counts["blind_agreement"] < 10 or min(counts[name] for name in ALLOCATIONS) < 1:
        raise ValueError("The pilot must retain common, personal TRAIN and sealed holdout sources")
    controls = sum(metadata[row["source_id"]]["curation_class_private"] == "scope_boundary_negative" for row in retained)
    if controls / len(retained) > .15:
        raise ValueError("Boundary controls exceed the curation cap")
    kept_meta = []
    ordered = sorted(retained, key=lambda row: (ALLOCATIONS.index(row["allocation"]), row["position"]))
    personal = Counter()
    for position, row in enumerate(ordered):
        source_id = row["source_id"]
        if hashlib.sha256((row["subject"] + "\n" + row["current_message"]).encode("utf-8")).hexdigest() != row["source_sha256"]:
            raise ValueError("Original source text/hash changed")
        row["position"] = position
        row["common_blind"] = row["allocation"] == "blind_agreement"
        row["owner_slot"] = None if row["common_blind"] else personal[row["allocation"]] % 3
        if not row["common_blind"]:
            personal[row["allocation"]] += 1
        if source_id in overrides:
            row["authored_ranges"] = overrides[source_id]
        if set(row) - {"source_id", "subject", "current_message", "authored_ranges", "source_sha256", "allocation", "position", "common_blind", "owner_slot"}:
            raise ValueError("Reviewer payload contains unapproved fields")
        kept_meta.append({**metadata[source_id], "allocation": row["allocation"], "position": position})
    group_allocations: dict[str, set] = defaultdict(set)
    for meta in kept_meta:
        group_allocations[meta["component_id"]].add(meta["allocation"])
        if meta.get("root_topic_block_private"):
            group_allocations["topic:" + meta["root_topic_block_private"]].add(meta["allocation"])
    if any(len(value) > 1 for value in group_allocations.values()):
        raise ValueError("A leakage or named-topic block crosses final allocations")

    output.mkdir(parents=True)
    full_sha = write_rows(output / "site_import.jsonl", ordered)
    common = [row for row in ordered if row["allocation"] != "labeler_human_holdout"]
    holdout = [row for row in ordered if row["allocation"] == "labeler_human_holdout"]
    common_sha = write_rows(output / "site_import_train_common.jsonl", common)
    holdout_sha = write_rows(output / "site_import_holdout.jsonl", holdout)
    metadata_sha = write_rows(output / "selection_metadata_private.jsonl", kept_meta)
    manifest = {
        "status": "root_approved_unlabelled_pilot", "created_from": original["created_from"],
        "proposal_import_sha256": original["site_import_sha256"], "root_decisions_sha256": sha(decisions_path),
        "selected_source_count": len(ordered), "allocation_counts": dict(counts),
        "selected_scope_boundary_control_count": controls, "root_train_common_reviewed": len(reviewed),
        "root_relevance_drops": len(drops), "sealed_named_topic_overlap_drops": len(heldout_overlap_drops),
        "root_range_overrides": len(overrides), "groups_split_across_allocations": 0,
        "protected_candidate_overlap": 0, "labels_present": False, "ai_prelabels_present": False,
        "gold_annotations": 0, "training_export_permitted": False,
        "site_import_sha256": full_sha, "site_import_train_common_sha256": common_sha,
        "site_import_holdout_sha256": holdout_sha, "selection_metadata_private_sha256": metadata_sha,
        "holdout_policy": "No heldout source text shown to root; existing prefix ranges require independent human verification/adjudication before evaluation.",
        "source_text_policy": "Normalized source body and subject bytes are unchanged; manual evidence-range corrections affect TRAIN/common only.",
        "sampling_limit": "Historical enriched public-corpus pilot; curation judgments are not human class support or target-domain accuracy.",
    }
    (output / "curation_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "holdout_manifest.json").write_text(json.dumps({
        "status": "sealed_unlabelled_human_holdout", "source_count": len(holdout),
        "site_import_holdout_sha256": holdout_sha, "labels_present": False, "root_text_review": False,
    }, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, default=PRIVATE_ROOT / "review_iteration2_private")
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PRIVATE_ROOT / "review_iteration3_private")
    args = parser.parse_args()
    print(json.dumps(finalize(args.proposal, args.decisions, args.output), sort_keys=True))


if __name__ == "__main__":
    main()

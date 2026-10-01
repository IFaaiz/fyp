"""Audit the actual accepted classification dataset; write aggregate data only.

The optional joined JSONL contains email text and must stay in ignored ai/data.
No label is inferred or repaired by this audit.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from scripts.train_silver_classifier import (
    apply_curated_exclusions, eligible_ai_silver, eligibility_reason,
    join_text_free_acceptance_manifest, read_curated_exclusions, sha256_file,
)
from src.datasets.schemas import read_jsonl, write_jsonl
from src.datasets.validation import validate_records
from src.models.silver_classifier import LABEL_ORDER, extract_authored_prefix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", default=[AI_DIR / "data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl"])
    parser.add_argument("--accepted-manifest", type=Path, nargs="+", required=True)
    parser.add_argument("--selection-manifest", type=Path, nargs="*", default=[])
    parser.add_argument("--source-records", type=Path, nargs="+", default=[AI_DIR / "data/interim/enron_full.jsonl"])
    parser.add_argument("--leakage-groups", type=Path, default=AI_DIR / "data/interim/leakage_groups.jsonl")
    parser.add_argument("--exclude-manifest", type=Path, default=AI_DIR / "annotation/training_leakage_exclusions.json")
    parser.add_argument("--output", type=Path, default=AI_DIR / "reports/training_silver_dataset_audit.json")
    parser.add_argument("--joined-output", type=Path)
    args = parser.parse_args()
    if args.joined_output and not args.joined_output.resolve().is_relative_to((AI_DIR / "data").resolve()):
        raise ValueError("joined email text must remain inside ignored ai/data")
    inputs = [row for path in args.input for row in read_jsonl(path)]
    joined, manifest = join_text_free_acceptance_manifest(args.accepted_manifest, args.source_records)
    records = inputs + joined
    keys = [(r["source_dataset"], r["email_id"]) for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source-qualified input IDs")
    validation = validate_records(records)
    if validation["errors"]:
        raise ValueError(f"canonical validation errors: {validation['errors'][:5]}")
    exclusions, exclusion_hash = read_curated_exclusions(args.exclude_manifest)
    records, curated_excluded = apply_curated_exclusions(records, exclusions)
    eligible = [r for r in records if eligible_ai_silver(r)]
    if not eligible:
        raise ValueError("no eligible accepted records")
    wanted = {(r["source_dataset"], r["email_id"]): r for r in eligible}
    groups = {}
    for row in read_jsonl(args.leakage_groups):
        key = (row["source_dataset"], row["email_id"])
        if key in wanted:
            if key in groups or row["thread_id"] != wanted[key]["thread_id"]:
                raise ValueError(f"duplicate or thread-mismatched sidecar entry: {key}")
            groups[key] = row["leakage_group_id"]
    if set(groups) != set(wanted):
        raise ValueError("accepted IDs missing from leakage sidecar")
    selected_groups = set(groups.values())
    component_sizes = Counter()
    component_sources = defaultdict(set)
    for row in read_jsonl(args.leakage_groups):
        group = row["leakage_group_id"]
        if group in selected_groups:
            component_sizes[group] += 1
            component_sources[group].add(row["source_dataset"])
    strata = {}
    for path in args.selection_manifest:
        for row in json.loads(path.read_text(encoding="utf-8"))["records"]:
            strata[(row["source_dataset"], row["email_id"])] = row.get("screening_stratum", "legacy")
    bodies = Counter(" ".join(extract_authored_prefix(r["current_message"]).split()).casefold() for r in eligible)
    lengths = [len(r["current_message"]) for r in eligible]
    prefixes = [extract_authored_prefix(r["current_message"]) for r in eligible]
    counts = Counter(label for row in eligible for label in row["labels"])
    report = {
        "scope": "Provisional AI-silver classification dataset; no human-gold accuracy claim",
        "accepted": len(eligible), "source_counts": dict(Counter(r["source_dataset"] for r in eligible)),
        "label_counts": {label: counts[label] for label in LABEL_ORDER},
        "label_cardinality": dict(sorted(Counter(len(r["labels"]) for r in eligible).items())),
        "average_labels": sum(len(r["labels"]) for r in eligible) / len(eligible),
        "canonical_validation_errors": 0,
        "human_reviewed_or_gold_used": 0,
        "source_qualified_threads": len({(r["source_dataset"], r["thread_id"]) for r in eligible}),
        "selected_leakage_groups": len(selected_groups),
        "selected_components_with_full_corpus_duplicates": sum(n > 1 for n in component_sizes.values()),
        "largest_selected_full_component": max(component_sizes.values()),
        "selected_cross_source_components": sum(len(s) > 1 for s in component_sources.values()),
        "repeated_normalized_authored_bodies": sum(n > 1 for n in bodies.values()),
        "current_length": {
            "min": min(lengths), "median": statistics.median(lengths),
            "mean": statistics.mean(lengths), "max": max(lengths),
            "quartiles": statistics.quantiles(lengths, n=4) if len(lengths) >= 2 else [],
            "empty": sum(n == 0 for n in lengths), "below100": sum(n < 100 for n in lengths),
        },
        "authored_prefix": {
            "empty": sum(not p for p in prefixes), "below100": sum(len(p) < 100 for p in prefixes),
            "trimmed_records": sum(p != r["current_message"].strip() for p, r in zip(prefixes, eligible)),
        },
        "calendar_task_exports": sum(r["current_message"].startswith(("CALENDAR ENTRY", "TASK ASSIGNMENT")) for r in eligible),
        "screening_strata": dict(Counter(strata.get((r["source_dataset"], r["email_id"]), "legacy_pilot_or_expansion") for r in eligible)),
        "curated_excluded": len(curated_excluded),
        "other_excluded_by_reason": dict(Counter(eligibility_reason(r) for r in records if not eligible_ai_silver(r))),
        "acceptance_manifest": manifest,
        "leakage_sidecar_sha256": sha256_file(args.leakage_groups),
        "exclusion_manifest_sha256": exclusion_hash,
        "text_free": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.joined_output:
        args.joined_output.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.joined_output, eligible)
    print(json.dumps({k: report[k] for k in ("accepted", "label_counts", "selected_leakage_groups", "repeated_normalized_authored_bodies", "authored_prefix")}))


if __name__ == "__main__":
    main()

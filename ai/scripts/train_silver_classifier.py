"""Train a leakage-group-safe TF-IDF + OVR logistic-regression silver baseline.

The default run writes a reproducible 80/20 AI-silver train/validation split,
fits on eligible training records only, and saves the model plus an ID-only
manifest. Optional validation metrics are gated behind --evaluate. This is
prototype infrastructure and never a gold-test evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.datasets.schemas import LABELS, read_jsonl
from src.datasets.validation import validate_records
from src.models.silver_classifier import (
    LABEL_ORDER,
    TfidfOneVsRestLogisticRegression,
    calculate_multilabel_metrics,
    classify_record,
    extract_authored_prefix,
)


DEFAULT_INPUT = AI_DIR / "data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl"
DEFAULT_SOURCE_RECORDS = AI_DIR / "data/interim/enron_candidates.jsonl"
DEFAULT_LEAKAGE_GROUPS = AI_DIR / "data/interim/leakage_groups.jsonl"
DEFAULT_EXCLUSIONS = AI_DIR / "annotation/training_leakage_exclusions.json"
DEFAULT_ACCEPTED_MANIFEST = AI_DIR / "annotation/training_expansion_100_silver_decisions.jsonl"
DEFAULT_MODEL = AI_DIR / "data/models/tfidf_ovr_logistic.json"
DEFAULT_SPLIT_MANIFEST = AI_DIR / "data/splits/ai_silver_train_validation.json"
DEFAULT_REPORT = AI_DIR / "data/splits/ai_silver_training_report.json"
MINIMUM_SILVER_RECORDS = 1000


def eligible_ai_silver(record: dict[str, Any]) -> bool:
    """Only fully labelled, explicitly AI-sourced and non-abstaining rows."""
    annotation = record.get("annotation", {})
    labels = record.get("labels")
    return (
        annotation.get("status") == "ai_prelabelled"
        and annotation.get("annotation_source") == "ai"
        and annotation.get("needs_review") is not True
        and isinstance(labels, list)
        and bool(labels)
        and all(label in LABELS for label in labels)
        and bool(extract_authored_prefix(str(record.get("current_message") or "")))
    )


def eligibility_reason(record: dict[str, Any]) -> str:
    annotation = record.get("annotation", {})
    if annotation.get("status") in {"unlabelled"} or annotation.get("needs_review") is True:
        return "abstention_or_needs_review"
    if annotation.get("status") in {"gold", "human_reviewed"}:
        return "human_data_excluded_from_ai_prototype"
    if annotation.get("status") != "ai_prelabelled" or annotation.get("annotation_source") != "ai":
        return "not_ai_prelabelled"
    if not record.get("labels"):
        return "empty_label_set"
    if not extract_authored_prefix(str(record.get("current_message") or "")):
        return "empty_authored_message"
    return "invalid_or_unknown_labels"


def read_curated_exclusions(path: Path) -> tuple[dict[str, str], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    exclusions = payload.get("training_exclusions", {})
    if not isinstance(exclusions, dict) or any(
        not isinstance(email_id, str) or not isinstance(reason, str)
        for email_id, reason in exclusions.items()
    ):
        raise ValueError(f"{path} has an invalid training_exclusions mapping")
    return exclusions, sha256_file(path)


def apply_curated_exclusions(
    records: list[dict[str, Any]], exclusions: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove explicitly unsafe/overlapping IDs before sidecar lookup or splitting."""
    excluded = [row for row in records if row.get("email_id") in exclusions]
    excluded_keys = {id(row) for row in excluded}
    kept = [row for row in records if id(row) not in excluded_keys]
    return kept, excluded


def join_text_free_acceptance_manifest(
    manifest_paths: list[Path] | Path, source_paths: list[Path],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join accepted labels to canonical text without storing text in the manifest."""
    if isinstance(manifest_paths, Path):
        manifest_paths = [manifest_paths]
    manifest_rows = []
    manifest_files = []
    accepted = {}
    statuses = Counter()
    for manifest_path in manifest_paths:
        current_rows = list(read_jsonl(manifest_path))
        manifest_rows.extend(current_rows)
        manifest_files.append({
            "path": str(manifest_path),
            "rows": len(current_rows),
            "sha256": sha256_file(manifest_path),
        })
        allowed_fields = {
            "source_dataset", "email_id", "thread_id", "labels", "status",
            "training_provenance", "acceptance_rule",
        }
        for row in current_rows:
            if not set(row).issubset(allowed_fields) or not {
                "source_dataset", "email_id", "labels", "status", "training_provenance",
            }.issubset(row):
                raise ValueError(
                    "accepted-label manifests must be text-free and contain source_dataset, email_id, "
                    "labels, status, and training_provenance"
                )
            status = row["status"]
            provenance = row["training_provenance"]
            statuses[str(status)] += 1
            if status != "ai_silver" or provenance != "ai_silver":
                continue
            key = (row["source_dataset"], row["email_id"])
            if key in accepted:
                raise ValueError(f"duplicate accepted-manifest record: {key}")
            labels = row["labels"]
            if not isinstance(labels, list) or not labels or any(label not in LABELS for label in labels):
                raise ValueError(f"accepted row must have nonempty known labels: {key}")
            if len(labels) != len(set(labels)):
                raise ValueError(f"accepted row has duplicate labels: {key}")
            if "NON_PROJECT" in labels and len(labels) != 1:
                raise ValueError(f"NON_PROJECT must be exclusive: {key}")
            accepted[key] = row

    source_rows = {}
    for path in source_paths:
        for row in read_jsonl(path):
            key = (row.get("source_dataset"), row.get("email_id"))
            if key not in accepted:
                continue
            if key in source_rows:
                raise ValueError(f"duplicate canonical source record for accepted row: {key}")
            source_rows[key] = row
    missing = set(accepted) - set(source_rows)
    if missing:
        raise ValueError(f"accepted manifest has {len(missing)} IDs without source records: {sorted(missing)[:5]}")

    joined = []
    for key, decision in accepted.items():
        source = source_rows[key]
        if decision.get("thread_id") and source.get("thread_id") != decision["thread_id"]:
            raise ValueError(f"accepted manifest thread_id mismatch for {key}")
        if source.get("labels") or source.get("annotation", {}).get("status") != "unlabelled":
            raise ValueError(f"accepted labels may only be joined to unlabelled source rows: {key}")
        row = dict(source)
        row["labels"] = list(decision["labels"])
        row["spans"] = []
        row["annotation"] = {
            "status": "ai_prelabelled",
            "annotator": "supervisor_audited_ai_silver_manifest",
            "annotation_source": "ai",
            "confidence": None,
            "needs_review": False,
            "span_review_status": "not_adjudicated",
            "intended_use": "classification_prototype_only",
        }
        joined.append(row)
    return joined, {
        "files": manifest_files,
        "rows": len(manifest_rows),
        "accepted_rows": len(accepted),
        "status_counts": dict(sorted(statuses.items())),
        "training_provenance": "ai_silver",
        "text_free": True,
    }


def load_leakage_group_map(
    path: Path, records: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Load selected record groups and verify sidecar thread identity."""
    expected = {
        (record["source_dataset"], record["email_id"]): record["thread_id"]
        for record in records
    }
    groups: dict[tuple[str, str], str] = {}
    sidecar_threads: dict[tuple[str, str], str] = {}
    for row in read_jsonl(path):
        key = (row.get("source_dataset"), row.get("email_id"))
        if key not in expected:
            continue
        group_id = row.get("leakage_group_id")
        thread_id = row.get("thread_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError(f"sidecar has an empty leakage_group_id for {key}")
        if not isinstance(thread_id, str) or thread_id != expected[key]:
            raise ValueError(f"sidecar thread_id mismatch for {key}")
        if key in groups:
            if groups[key] != group_id or sidecar_threads[key] != thread_id:
                raise ValueError(f"conflicting duplicate leakage sidecar row for {key}")
            raise ValueError(f"duplicate leakage sidecar row for {key}")
        groups[key] = group_id
        sidecar_threads[key] = thread_id
    missing = set(expected) - set(groups)
    if missing:
        sample = sorted(missing)[:5]
        raise ValueError(f"leakage sidecar is missing {len(missing)} selected records, e.g. {sample}")
    return groups


def grouped_train_validation_split(
    records: list[dict[str, Any]], leakage_groups: dict[tuple[str, str], str], *,
    validation_ratio: float = 0.2, seed: int = 42,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Keep connected source-qualified threads and leakage groups together."""
    if not 0 < validation_ratio < 1:
        raise ValueError("validation_ratio must be between zero and one")
    if not records:
        raise ValueError("cannot split an empty record list")
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    first_in_thread: dict[tuple[str, str], int] = {}
    first_in_leakage_group: dict[str, int] = {}
    group_ids: list[str] = []
    for index, record in enumerate(records):
        key = (record["source_dataset"], record["email_id"])
        if key not in leakage_groups:
            raise ValueError(f"no leakage_group_id supplied for {key}")
        group_id = leakage_groups[key]
        group_ids.append(group_id)
        thread_key = (record["source_dataset"], record["thread_id"])
        if thread_key in first_in_thread:
            union(index, first_in_thread[thread_key])
        else:
            first_in_thread[thread_key] = index
        if group_id in first_in_leakage_group:
            union(index, first_in_leakage_group[group_id])
        else:
            first_in_leakage_group[group_id] = index

    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        components[find(index)].append(index)
    if len(components) < 2:
        raise ValueError("all records belong to one connected thread/leakage group; no validation split is possible")

    eligible_indices = [i for i, record in enumerate(records) if eligible_ai_silver(record)]
    total_labels = Counter(
        label for index in eligible_indices for label in records[index]["labels"]
    )
    target_validation_count = validation_ratio * len(eligible_indices)
    target_validation_labels = {
        label: validation_ratio * total_labels[label] for label in LABEL_ORDER
    }

    def component_profile(indices: list[int]) -> tuple[int, Counter[str]]:
        selected = [i for i in indices if i in eligible_index_set]
        return len(selected), Counter(
            label for index in selected for label in records[index]["labels"]
        )

    eligible_index_set = set(eligible_indices)
    profiles = {
        root: component_profile(indices)
        for root, indices in components.items()
    }
    rng = random.Random(seed)
    roots = list(components)
    rng.shuffle(roots)
    roots.sort(
        key=lambda root: (
            profiles[root][0],
            len(components[root]),
            max(profiles[root][1].values(), default=0),
        ),
        reverse=True,
    )

    validation_roots: set[int] = set()
    validation_count = 0
    validation_labels: Counter[str] = Counter()

    def validation_objective(count: int, label_counts: Counter[str]) -> float:
        size_scale = max(target_validation_count, 1.0)
        score = 2.0 * ((count - target_validation_count) ** 2) / size_scale
        for label in LABEL_ORDER:
            target = target_validation_labels[label]
            scale = max(target, 1.0)
            score += ((label_counts[label] - target) ** 2) / scale
        return score

    for root in roots:
        component_count, component_labels = profiles[root]
        with_validation = validation_objective(
            validation_count + component_count,
            validation_labels + component_labels,
        )
        without_validation = validation_objective(validation_count, validation_labels)
        if with_validation < without_validation:
            validation_roots.add(root)
            validation_count += component_count
            validation_labels.update(component_labels)

    if not validation_roots:
        smallest = min(roots, key=lambda root: (profiles[root][0], len(components[root]), root))
        validation_roots.add(smallest)
    if len(validation_roots) == len(components):
        largest = max(roots, key=lambda root: (profiles[root][0], len(components[root]), -root))
        validation_roots.remove(largest)

    splits = {"train": [], "validation": []}
    split_groups = {"train": set(), "validation": set()}
    for root, indices in components.items():
        name = "validation" if root in validation_roots else "train"
        for index in indices:
            splits[name].append(records[index])
            split_groups[name].add(group_ids[index])
    for name in splits:
        splits[name].sort(key=lambda row: (row["source_dataset"], row["email_id"]))

    seen_threads: dict[tuple[str, str], str] = {}
    seen_groups: dict[str, str] = {}
    for name, partition in splits.items():
        for record in partition:
            thread = (record["source_dataset"], record["thread_id"])
            group_id = leakage_groups[(record["source_dataset"], record["email_id"])]
            if thread in seen_threads and seen_threads[thread] != name:
                raise AssertionError(f"thread crosses split boundary: {thread}")
            if group_id in seen_groups and seen_groups[group_id] != name:
                raise AssertionError(f"leakage group crosses split boundary: {group_id}")
            seen_threads[thread] = name
            seen_groups[group_id] = name

    summary = {
        "method": "connected components of source-qualified threads and leakage_group_id",
        "seed": seed,
        "validation_ratio_target": validation_ratio,
        "connected_groups": len(components),
        "partition_records": {name: len(rows) for name, rows in splits.items()},
        "partition_eligible_ai_silver": {
            name: sum(eligible_ai_silver(row) for row in rows)
            for name, rows in splits.items()
        },
        "partition_label_counts": {
            name: label_counts([row for row in rows if eligible_ai_silver(row)])
            for name, rows in splits.items()
        },
        "partition_leakage_groups": {
            name: sorted(split_groups[name]) for name in splits
        },
    }
    return splits, summary


def label_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(label for record in records for label in record["labels"])
    return {label: counts[label] for label in LABEL_ORDER}


def _multilabel_distribution(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(len(record["labels"])) for record in records)
    return {str(index): counts.get(str(index), 0) for index in range(1, len(LABEL_ORDER) + 1)}


def _source_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(record["source_dataset"] for record in records)
    return dict(sorted(counts.items()))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_input_hash(paths: list[Path]) -> tuple[list[dict[str, Any]], str]:
    files = []
    combined = hashlib.sha256()
    for path in paths:
        item = {"path": str(path), "sha256": sha256_file(path)}
        files.append(item)
        combined.update(item["path"].encode("utf-8"))
        combined.update(b"\0")
        combined.update(item["sha256"].encode("ascii"))
        combined.update(b"\n")
    return files, combined.hexdigest()


def _source_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=AI_DIR.parent,
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _keyword_prediction(record: dict[str, Any]) -> list[str]:
    """Small transparent cue baseline; cues are not annotation labels."""
    text = (
        str(record.get("subject") or "") + "\n"
        + extract_authored_prefix(str(record.get("current_message") or ""))
    ).lower()
    matches = []
    rules = {
        "MEETING": r"\b(?:meeting|conference call|agenda|reschedul|minutes?)\b",
        "DEADLINE": r"\b(?:deadline|due\s+(?:by|on|date)|no later than)\b",
        "REPORT_REQUEST": r"\b(?:submit|send|provide|prepare|request).{0,80}\b(?:report|minutes|presentation|plan|document)\b|\b(?:report|minutes|presentation|plan|document).{0,80}\b(?:submit|send|provide|prepare|request)\b",
        "DEPARTMENTAL_INPUT": r"\b(?:department|group|team).{0,80}\b(?:input|feedback|data|response)\b|\b(?:input|feedback|data).{0,50}\b(?:from|by)\s+(?:the\s+)?(?:department|group|team)\b",
        "ACTION_REQUEST": r"\b(?:please|can you|need you to|assigned to).{0,100}\b(?:review|prepare|send|update|complete|contact|investigate|coordinate)\b",
        "FOLLOW_UP": r"\b(?:follow[- ]?up|remind(?:er)?|checking back|still waiting|chasing)\b",
        "APPROVAL": r"\b(?:approval|approve|sign[- ]?off|authorize)\b",
        "GENERAL_UPDATE": r"\b(?:update|status|progress|completed|blocker)\b",
    }
    import re
    for label in LABEL_ORDER[:-1]:
        if re.search(rules[label], text):
            matches.append(label)
    return matches or ["NON_PROJECT"]


def _evaluate(model, train_rows, validation_rows) -> dict[str, Any]:
    expected = [row["labels"] for row in validation_rows]
    model_predictions = [model.predict(row)["labels"] for row in validation_rows]
    prevalence = {
        label: sum(label in row["labels"] for row in train_rows) / len(train_rows)
        for label in LABEL_ORDER
    }
    frequency_predictions = [
        [label for label in LABEL_ORDER if prevalence[label] >= 0.5]
        for _ in validation_rows
    ]
    for row in frequency_predictions:
        if "NON_PROJECT" in row and len(row) > 1:
            row[:] = ["NON_PROJECT"]
    keyword_predictions = [_keyword_prediction(row) for row in validation_rows]
    non_project_predictions = [["NON_PROJECT"] for _ in validation_rows]
    return {
        "scope": "Diagnostic agreement with AI-silver validation labels only; not gold accuracy.",
        "records": len(validation_rows),
        "baselines": {
            "always_non_project": calculate_multilabel_metrics(expected, non_project_predictions),
            "train_label_frequency_0_5": calculate_multilabel_metrics(expected, frequency_predictions),
            "keyword_cues": calculate_multilabel_metrics(expected, keyword_predictions),
        },
        "tfidf_ovr_logistic": calculate_multilabel_metrics(expected, model_predictions),
        "label_prevalence_from_training": prevalence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="*", default=[DEFAULT_INPUT],
                        help="canonical labelled JSONL files, such as the audited pilot silver batch")
    parser.add_argument("--accepted-manifest", type=Path, nargs="+", default=[DEFAULT_ACCEPTED_MANIFEST],
                        help="text-free accepted labels with source_dataset/email_id/labels/training_provenance")
    parser.add_argument("--no-accepted-manifest", action="store_true",
                        help="train only from canonical labelled --input files")
    parser.add_argument("--source-records", type=Path, nargs="+", default=[DEFAULT_SOURCE_RECORDS],
                        help="canonical JSONL sources used to join a text-free accepted-label manifest")
    parser.add_argument("--leakage-groups", type=Path, default=DEFAULT_LEAKAGE_GROUPS)
    parser.add_argument("--exclude-manifest", type=Path, default=DEFAULT_EXCLUSIONS)
    parser.add_argument("--shortage-report", type=Path, help="nonempty documented shortage rationale to permit fewer than 1,000 rows")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--split-manifest", type=Path, default=DEFAULT_SPLIT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-ratio", type=float, default=0.2)
    parser.add_argument("--c", type=float, default=1.0)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--max-iter", type=int, default=200)
    parser.add_argument("--learning-rate", type=float, default=1.0)
    parser.add_argument("--optimizer", choices=("python", "sklearn"), default="python",
                        help="optional standard lbfgs fitting; JSON prediction stays dependency-free")
    parser.add_argument("--evaluate", action="store_true", help="compute AI-silver validation diagnostics after training")
    parser.add_argument("--predict-text", help="predict one current-message string using --model")
    parser.add_argument("--predict-jsonl", type=Path, help="predict canonical records from JSONL using --model")
    parser.add_argument("--subject", default="", help="subject paired with --predict-text")
    args = parser.parse_args()

    if args.predict_text is not None or args.predict_jsonl is not None:
        model = TfidfOneVsRestLogisticRegression.load(args.model)
        if args.predict_text is not None:
            rows = [{"email_id": None, "subject": args.subject, "current_message": args.predict_text}]
        else:
            rows = list(read_jsonl(args.predict_jsonl))
        print(json.dumps([classify_record(model, row) for row in rows], ensure_ascii=False, indent=2))
        return 0

    all_records = []
    seen = set()
    for path in args.input:
        for record in read_jsonl(path):
            key = (record.get("source_dataset"), record.get("email_id"))
            if key in seen:
                raise ValueError(f"duplicate source-qualified email_id across input files: {key}")
            seen.add(key)
            all_records.append(record)
    acceptance_manifest = None
    if args.accepted_manifest and not args.no_accepted_manifest:
        joined, acceptance_manifest = join_text_free_acceptance_manifest(
            args.accepted_manifest, args.source_records,
        )
        for record in joined:
            key = (record.get("source_dataset"), record.get("email_id"))
            if key in seen:
                raise ValueError(f"accepted row duplicates a canonical input row: {key}")
            seen.add(key)
            all_records.append(record)
    if not all_records:
        raise ValueError("input files contain no records")
    report = validate_records(all_records)
    if report["errors"]:
        raise ValueError("input failed canonical validation: " + "; ".join(report["errors"][:8]))

    exclusions, exclusion_hash = read_curated_exclusions(args.exclude_manifest)
    records, excluded = apply_curated_exclusions(all_records, exclusions)
    excluded_counts = Counter(eligibility_reason(row) for row in records if not eligible_ai_silver(row))
    eligible_records = [row for row in records if eligible_ai_silver(row)]
    if not eligible_records:
        raise ValueError("no eligible AI-silver records remain after abstention and provenance filtering")
    groups = load_leakage_group_map(args.leakage_groups, eligible_records)
    splits, split_summary = grouped_train_validation_split(
        eligible_records, groups, validation_ratio=args.validation_ratio, seed=args.seed,
    )
    train_rows = splits["train"]
    validation_rows = splits["validation"]
    if not train_rows:
        raise ValueError("the leakage-safe training partition has no eligible AI-silver records")
    eligible_total = len(train_rows) + len(validation_rows)
    if eligible_total < MINIMUM_SILVER_RECORDS:
        if args.shortage_report is None or not args.shortage_report.is_file():
            raise ValueError(
                f"only {eligible_total} eligible rows; at least {MINIMUM_SILVER_RECORDS} are required "
                "unless --shortage-report documents why fewer high-confidence rows are available"
            )
        if len(args.shortage_report.read_text(encoding="utf-8").strip()) < 40:
            raise ValueError("--shortage-report must contain a concrete, nontrivial explanation")
    if args.evaluate and not validation_rows:
        raise ValueError("cannot evaluate: leakage-safe validation partition has no eligible AI-silver rows")

    model = TfidfOneVsRestLogisticRegression(
        c=args.c, threshold=args.threshold, max_iter=args.max_iter,
        learning_rate=args.learning_rate, seed=args.seed,
        optimizer=args.optimizer,
    )
    model.fit(train_rows)
    evaluation = _evaluate(model, train_rows, validation_rows) if args.evaluate else None
    input_paths = list(args.input)
    if acceptance_manifest:
        input_paths.extend(args.source_records)
        input_paths.extend(args.accepted_manifest)
    input_files, input_hash = combined_input_hash(input_paths)
    leakage_hash = sha256_file(args.leakage_groups)
    model.metadata = {
        "purpose": "ai_silver_classification_prototype_only",
        "input_files": input_files,
        "input_sha256": input_hash,
        "leakage_sidecar": str(args.leakage_groups),
        "leakage_sidecar_sha256": leakage_hash,
        "curated_exclusion_manifest": str(args.exclude_manifest),
        "curated_exclusion_manifest_sha256": exclusion_hash,
        "accepted_manifest": acceptance_manifest,
        "excluded_email_ids": sorted(row["email_id"] for row in excluded),
        "split_seed": args.seed,
        "human_reviewed_or_gold_used": 0,
        "gold_test_used": False,
        "validation_evaluated": bool(args.evaluate),
    }
    args.model.parent.mkdir(parents=True, exist_ok=True)
    model.save(args.model)

    partition_report = {
        "input_records_before_curated_exclusions": len(all_records),
        "curated_manifest_excluded": len(excluded),
        "records_after_curated_exclusions": len(records),
        "eligible_records_split": len(eligible_records),
        "eligible_ai_silver_records": len(train_rows) + len(validation_rows),
        "eligible_ai_silver_used_for_training": len(train_rows),
        "eligible_ai_silver_reserved_for_validation": len(validation_rows),
        "other_records_excluded_from_model": len(records) - len(train_rows) - len(validation_rows),
        "other_excluded_by_reason": dict(sorted(excluded_counts.items())),
        "human_reviewed_or_gold_used": 0,
        "label_counts_train": label_counts(train_rows),
        "label_counts_validation": label_counts(validation_rows),
        "multi_label_distribution_train": _multilabel_distribution(train_rows),
        "source_counts_train": _source_counts(train_rows),
        "source_counts_validation": _source_counts(validation_rows),
        "accepted_manifest": acceptance_manifest,
    }
    split_manifest = {
        **split_summary,
        "input_files": input_files,
        "input_sha256": input_hash,
        "leakage_sidecar_sha256": leakage_hash,
        "exclusion_manifest_sha256": exclusion_hash,
        "curated_excluded_ids_and_reasons": {
            row["email_id"]: exclusions[row["email_id"]] for row in excluded
        },
        "partitions": {
            name: [
                {
                    "source_dataset": row["source_dataset"],
                    "email_id": row["email_id"],
                    "thread_id": row["thread_id"],
                    "leakage_group_id": groups[(row["source_dataset"], row["email_id"])],
                }
                for row in splits[name]
            ]
            for name in ("train", "validation")
        },
        "training_data_summary": partition_report,
        "validation_metrics_created": bool(args.evaluate),
        "final_gold_test_claim": False,
    }
    _write_json(args.split_manifest, split_manifest)

    report_payload = {
        "scope": "AI-silver prototype training only; no gold accuracy claim.",
        "model": {
            "type": "TF-IDF + one-vs-rest logistic regression",
            "implementation": "scikit-learn fitting with portable JSON weights" if args.optimizer == "sklearn" else "standard-library sparse optimizer",
            "solver": "lbfgs" if args.optimizer == "sklearn" else "deterministic full-batch gradient descent",
            "regularization": "mean binary cross-entropy + L2 ||w||^2/(2*C*n)",
            "C": args.c,
            "threshold": args.threshold,
            "optimizer": args.optimizer,
            "max_iter": args.max_iter,
            "learning_rate": args.learning_rate,
        },
        "data": partition_report,
        "validation_metrics": evaluation,
        "validation_evaluated": bool(args.evaluate),
        "gold_test_evaluated": False,
        "model_path": str(args.model),
        "split_manifest_path": str(args.split_manifest),
        "source_commit_sha": _source_commit_sha(),
    }
    _write_json(args.report, report_payload)
    print(json.dumps({
        "model": str(args.model),
        "split_manifest": str(args.split_manifest),
        "training_records": len(train_rows),
        "validation_records": len(validation_rows),
        "validation_metrics_created": bool(args.evaluate),
        "scope": report_payload["scope"],
        "accepted_manifest": acceptance_manifest,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

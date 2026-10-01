"""Build a blind, training-reused human calibration queue for transfer experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = PROJECT_ROOT / "ai"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.datasets.schemas import LABELS
from src.datasets.validation import validate_record
from src.models.silver_classifier import LABEL_ORDER, extract_authored_prefix
from src.models.transfer_diagnostic import (
    load_shared_partitions,
    sha256_file,
    validate_snapshot,
)


EXPERIMENT_DIR = AI_ROOT / "data" / "experiments" / "tonight_20261002"
ANNOTATION_DIR = AI_ROOT / "annotation"
OUTPUT_DIR = AI_ROOT / "data" / "annotated" / "human" / "transfer_calibration"
ORIGINAL_SNAPSHOT = EXPERIMENT_DIR / "original_silver_snapshot.jsonl"
CORRECTED_SNAPSHOT = EXPERIMENT_DIR / "corrected_silver_snapshot.jsonl"
CORRECTED_MANIFEST = ANNOTATION_DIR / "training_silver_v2_manifest.jsonl"
SHARED_SPLIT = ANNOTATION_DIR / "tonight_silver_v2_shared_split.json"
LEAKAGE_OVERRIDES = ANNOTATION_DIR / "tonight_leakage_overrides.json"
FINAL_AUDIT = ANNOTATION_DIR / "tonight_semantic_audit_decisions.jsonl"
NEGATIVE_AUDIT = EXPERIMENT_DIR / "audit_negative_50_decisions.jsonl"
SEED_PATH = OUTPUT_DIR / "canonical_seed.jsonl"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
TEXT_FREE_MANIFEST_PATH = ANNOTATION_DIR / "transfer_calibration_queue_manifest.json"
TARGET_COUNT = 180
EXPECTED_CANONICAL_FIELDS = (
    "email_id", "source_dataset", "thread_id", "turn_index", "subject",
    "raw_body", "current_message", "clean_body", "thread_context", "sender",
    "recipients", "cc", "sent_at", "attachment_names", "labels", "spans",
    "annotation",
)
RARE_LABELS = frozenset({
    "DEADLINE", "REPORT_REQUEST", "DEPARTMENTAL_INPUT", "FOLLOW_UP", "APPROVAL",
})
COMMON_LABELS = ("MEETING", "ACTION_REQUEST", "GENERAL_UPDATE", "NON_PROJECT")
SEED = "tonight-20261002-transfer-calibration-v1"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"expected a JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def unique_by_id(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        email_id = row.get("email_id")
        if not isinstance(email_id, str) or not email_id or email_id in result:
            raise ValueError(f"{label} has a missing or repeated email_id: {email_id!r}")
        result[email_id] = row
    return result


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_key(email_id: str, *, lane: str) -> str:
    return hashlib.sha256(f"{SEED}|{lane}|{email_id}".encode("utf-8")).hexdigest()


def _imbalance(counts: Counter[str]) -> float:
    values = [counts[label] for label in COMMON_LABELS]
    average = sum(values) / len(values)
    return sum((value - average) ** 2 for value in values)


def _project_labels(record: dict[str, Any]) -> set[str]:
    return set(record.get("labels", []))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _source_eligible(
    email_id: str,
    source: dict[str, Any],
    *,
    split_owner: dict[str, str],
    validation_ids: set[str],
    validation_threads: set[tuple[str, str]],
    validation_groups: set[str],
    group_mapping: dict[str, str],
    excluded_ids: set[str],
) -> tuple[bool, str]:
    if email_id in validation_ids:
        return False, "validation_email_id"
    thread_key = (str(source.get("source_dataset") or ""), str(source.get("thread_id") or ""))
    if thread_key in validation_threads:
        return False, "validation_thread"
    group_id = group_mapping.get(email_id)
    if not isinstance(group_id, str) or not group_id:
        raise ValueError(f"leakage override is missing a group for {email_id}")
    if group_id in validation_groups:
        return False, "validation_leakage_group"
    if email_id in excluded_ids:
        return True, "excluded_source"
    partition = split_owner.get(email_id)
    if partition not in {"fit", "tuning"}:
        return False, f"partition_{partition or 'missing'}"
    return True, partition


def _select_balanced_common(
    *,
    selected_reasons: dict[str, set[str]],
    eligible_ids: set[str],
    corrected_by_id: dict[str, dict[str, Any]],
    group_mapping: dict[str, str],
    target_count: int,
) -> None:
    def common_counts() -> Counter[str]:
        counts: Counter[str] = Counter()
        for email_id in selected_reasons:
            record = corrected_by_id.get(email_id)
            if record is not None:
                counts.update(label for label in record["labels"] if label in COMMON_LABELS)
        return counts

    while len(selected_reasons) < target_count:
        counts = common_counts()
        before = _imbalance(counts)
        already_selected_groups = {group_mapping[email_id] for email_id in selected_reasons}
        candidates = []
        for email_id in eligible_ids - set(selected_reasons):
            record = corrected_by_id.get(email_id)
            if record is None:
                continue
            common = set(record["labels"]) & set(COMMON_LABELS)
            if not common:
                continue
            candidates.append((email_id, record, common))
        if not candidates:
            raise ValueError("eligible pool cannot fill the requested queue size")

        fresh_group_candidates = [
            item for item in candidates if group_mapping[item[0]] not in already_selected_groups
        ]
        if fresh_group_candidates:
            candidates = fresh_group_candidates

        def rank(item: tuple[str, dict[str, Any], set[str]]) -> tuple[float, str]:
            email_id, _record, common = item
            after = counts.copy()
            after.update(common)
            gain = before - _imbalance(after)
            return gain, stable_key(email_id, lane="balanced-common")

        chosen_id, _record, _labels = max(candidates, key=rank)
        selected_reasons.setdefault(chosen_id, set()).add("balanced_common_label_coverage")


def build_queue(target_count: int = TARGET_COUNT) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    original_rows = read_jsonl(ORIGINAL_SNAPSHOT)
    corrected_rows = read_jsonl(CORRECTED_SNAPSHOT)
    corrected_manifest = read_jsonl(CORRECTED_MANIFEST)
    original_by_id = unique_by_id(original_rows, "original snapshot")
    corrected_by_id = unique_by_id(corrected_rows, "corrected snapshot")
    if len(original_rows) != 718 or len(corrected_rows) != 674:
        raise ValueError(
            f"expected corrected674 freeze (718 original, 674 corrected); got "
            f"{len(original_rows)} and {len(corrected_rows)}"
        )
    corrected_validation = validate_snapshot(corrected_rows, corrected_manifest)
    split = read_json(SHARED_SPLIT)
    partitions, split_report = load_shared_partitions(
        corrected_rows,
        split,
        snapshot_sha256=sha256_file(CORRECTED_SNAPSHOT),
        silver_manifest_sha256=sha256_file(CORRECTED_MANIFEST),
    )
    partition_owner = {
        row["email_id"]: name
        for name, rows in partitions.items()
        for row in rows
    }
    fit_tuning_ids = {
        row["email_id"]
        for name in ("fit", "tuning")
        for row in partitions[name]
    }
    validation_rows = partitions["validation"]
    validation_ids = {row["email_id"] for row in validation_rows}
    validation_threads = {
        (row["source_dataset"], row["thread_id"]) for row in validation_rows
    }
    validation_groups = {
        row["snapshot_provenance"]["leakage_group_id"] for row in validation_rows
    }

    overrides = read_json(LEAKAGE_OVERRIDES)
    group_mapping = overrides.get("group_mapping")
    if not isinstance(group_mapping, dict) or set(group_mapping) != set(original_by_id):
        raise ValueError("tonight leakage override must map every original source email ID")
    for email_id, row in corrected_by_id.items():
        if group_mapping[email_id] != row["snapshot_provenance"]["leakage_group_id"]:
            raise ValueError(f"corrected snapshot and leakage override differ for {email_id}")

    excluded_ids = set(original_by_id) - set(corrected_by_id)
    if len(excluded_ids) != 44:
        raise ValueError(f"expected 44 uncertain excluded source rows; got {len(excluded_ids)}")
    final_audit = unique_by_id(read_jsonl(FINAL_AUDIT), "final semantic audit")
    for email_id in excluded_ids:
        decision = final_audit.get(email_id)
        if not decision or decision.get("verdict") != "exclude_uncertain" or decision.get("auditor_labels"):
            raise ValueError(f"excluded source row lacks an uncertain, label-free audit decision: {email_id}")

    candidate_sources: dict[str, dict[str, Any]] = {}
    candidate_kind: dict[str, str] = {}
    candidate_partition: dict[str, str] = {}
    validation_exclusions: Counter[str] = Counter()
    for email_id, source in original_by_id.items():
        allowed, kind = _source_eligible(
            email_id,
            source,
            split_owner=partition_owner,
            validation_ids=validation_ids,
            validation_threads=validation_threads,
            validation_groups=validation_groups,
            group_mapping=group_mapping,
            excluded_ids=excluded_ids,
        )
        if not allowed:
            validation_exclusions[kind] += 1
            continue
        if email_id in corrected_by_id and email_id not in fit_tuning_ids:
            continue
        candidate_sources[email_id] = corrected_by_id.get(email_id, source)
        candidate_kind[email_id] = "original_excluded" if email_id in excluded_ids else "corrected674"
        candidate_partition[email_id] = kind

    eligible_ids = set(candidate_sources)
    eligible_excluded_ids = eligible_ids & excluded_ids
    if len(eligible_excluded_ids) != len(excluded_ids):
        raise ValueError("one or more excluded source rows overlap final validation by ID, thread, or leakage group")
    if eligible_ids & validation_ids:
        raise ValueError("eligible queue IDs overlap final validation")

    selected_reasons: dict[str, set[str]] = {}
    training_rare_ids = {
        email_id
        for email_id in eligible_ids & fit_tuning_ids
        if _project_labels(corrected_by_id[email_id]) & RARE_LABELS
    }
    for email_id in training_rare_ids:
        selected_reasons.setdefault(email_id, set()).add("rare_label_coverage")
        if "DEADLINE" in corrected_by_id[email_id]["labels"]:
            selected_reasons[email_id].add("deadline_coverage")
    for email_id in eligible_excluded_ids:
        selected_reasons.setdefault(email_id, set()).add("ambiguous_excluded_source")

    for email_id, decision in final_audit.items():
        if email_id not in eligible_ids or email_id in excluded_ids:
            continue
        old = set(decision.get("existing_labels") or [])
        proposal = decision.get("auditor_proposal_labels")
        final_labels = set(decision.get("auditor_labels") or [])
        proposal_changed = isinstance(proposal, list) and set(proposal) != old
        if decision.get("verdict") == "corrected" or proposal_changed or final_labels != old:
            selected_reasons.setdefault(email_id, set()).add("auditor_disagreement")

    negative_audit = unique_by_id(read_jsonl(NEGATIVE_AUDIT), "negative semantic audit")
    difficult_non_project_ids = {
        email_id
        for email_id, decision in negative_audit.items()
        if email_id in eligible_ids and decision.get("existing_labels") == ["NON_PROJECT"]
    }
    for email_id in difficult_non_project_ids:
        selected_reasons.setdefault(email_id, set()).add("difficult_non_project_review")

    if len(selected_reasons) > target_count:
        raise ValueError(
            f"priority items ({len(selected_reasons)}) exceed target size {target_count}; "
            "revise queue size rather than dropping priority coverage"
        )
    _select_balanced_common(
        selected_reasons=selected_reasons,
        eligible_ids=fit_tuning_ids & eligible_ids,
        corrected_by_id=corrected_by_id,
        group_mapping=group_mapping,
        target_count=target_count,
    )

    priority_rank = {
        "rare_label_coverage": 0,
        "deadline_coverage": 0,
        "ambiguous_excluded_source": 1,
        "auditor_disagreement": 2,
        "difficult_non_project_review": 3,
        "balanced_common_label_coverage": 4,
    }
    ordered_ids = sorted(
        selected_reasons,
        key=lambda email_id: (
            min(priority_rank[reason] for reason in selected_reasons[email_id]),
            stable_key(email_id, lane="queue-order"),
        ),
    )

    seed_rows: list[dict[str, Any]] = []
    message_views: dict[str, dict[str, str]] = {}
    selection_reasons: dict[str, list[str]] = {}
    source_kinds: Counter[str] = Counter()
    partition_counts: Counter[str] = Counter()
    view_modes: Counter[str] = Counter()
    for email_id in ordered_ids:
        source = candidate_sources[email_id]
        record = {field: source[field] for field in EXPECTED_CANONICAL_FIELDS}
        record["labels"] = []
        record["spans"] = []
        record["annotation"] = {
            "status": "unlabelled",
            "annotator": None,
            "annotation_source": None,
            "confidence": None,
        }
        if tuple(record) != EXPECTED_CANONICAL_FIELDS:
            raise ValueError(f"canonical field order/contract drifted for {email_id}")
        errors = validate_record(record)
        if errors:
            raise ValueError(f"selected canonical record {email_id} is invalid: {'; '.join(errors)}")
        if record["labels"] or record["spans"] or record["annotation"].get("status") != "unlabelled":
            raise ValueError(f"queue row is not blank and unlabelled: {email_id}")
        seed_rows.append(record)

        current_message = record["current_message"]
        authored_view = extract_authored_prefix(current_message)
        use_authored = bool(authored_view) and current_message.startswith(authored_view)
        visible_message = authored_view if use_authored else current_message
        mode = "authored_prefix" if use_authored else "canonical_current_message"
        source_row = original_by_id[email_id]
        snapshot_provenance = source_row.get("snapshot_provenance", {})
        message_views[email_id] = {
            "source_sha256": str(snapshot_provenance.get("source_sha256") or ""),
            "source_current_message_sha256": text_sha256(current_message),
            "view_sha256": text_sha256(visible_message),
            "display_mode": mode,
        }
        view_modes[mode] += 1
        source_kinds[candidate_kind[email_id]] += 1
        partition_counts[candidate_partition[email_id]] += 1
        selection_reasons[email_id] = sorted(selected_reasons[email_id])

    seed_text = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in seed_rows
    )
    manifest = {
        "source_dataset": "enron",
        "display_name": "Transfer calibration queue (training-reused, not gold)",
        "selected_email_count": len(seed_rows),
        "selected_email_ids": ordered_ids,
        "screening_status": "targeted_transfer_calibration_selection",
        "labels_prepopulated": False,
        "is_gold": False,
        "label_blind": True,
        "metric_provenance": "Human calibration; seed labels are blank.",
        "training_reused": True,
        "independent_gold": False,
        "intended_use": (
            "Human calibration on fit/tuning records reused from the corrected AI-silver "
            "training pool plus uncertain excluded source rows. These annotations are not "
            "independent gold and must not be reported as final-validation performance."
        ),
        "validation_rare_omitted_intentionally": True,
        "display_view": "authored_prefix_if_exact_prefix",
        "view_policy": (
            "Preserve canonical current_message unchanged. The local annotator displays "
            "extract_authored_prefix only when it is an exact source prefix, moves the "
            "stripped tail into reference-only thread context, and anchors spans to the "
            "unchanged canonical prefix. If text normalization prevents exact-prefix "
            "alignment, display the original canonical current_message."
        ),
        "target_count": target_count,
        "selection_seed": SEED,
        "rare_labels_prioritized": [
            label for label in LABEL_ORDER if label in RARE_LABELS
        ],
        "common_labels_balanced": list(COMMON_LABELS),
        "source_artifacts": {
            "original_snapshot": str(ORIGINAL_SNAPSHOT.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "original_snapshot_sha256": sha256_file(ORIGINAL_SNAPSHOT),
            "corrected_snapshot": str(CORRECTED_SNAPSHOT.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "corrected_snapshot_sha256": sha256_file(CORRECTED_SNAPSHOT),
            "corrected_manifest": str(CORRECTED_MANIFEST.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "corrected_manifest_sha256": sha256_file(CORRECTED_MANIFEST),
            "shared_split": str(SHARED_SPLIT.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "shared_split_sha256": sha256_file(SHARED_SPLIT),
            "leakage_overrides": str(LEAKAGE_OVERRIDES.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "leakage_overrides_sha256": sha256_file(LEAKAGE_OVERRIDES),
        },
        "queue_counts": {
            "selected": len(seed_rows),
            "corrected674_fit_tuning": source_kinds["corrected674"],
            "original_uncertain_excluded": source_kinds["original_excluded"],
            "ambiguous_excluded_source": sum(
                "ambiguous_excluded_source" in reasons for reasons in selected_reasons.values()
            ),
            "rare_label_coverage": sum(
                "rare_label_coverage" in reasons for reasons in selected_reasons.values()
            ),
            "auditor_disagreement": sum(
                "auditor_disagreement" in reasons for reasons in selected_reasons.values()
            ),
            "difficult_non_project_review": sum(
                "difficult_non_project_review" in reasons for reasons in selected_reasons.values()
            ),
            "balanced_common_label_coverage": sum(
                "balanced_common_label_coverage" in reasons for reasons in selected_reasons.values()
            ),
            "by_partition_or_exclusion": dict(sorted(partition_counts.items())),
            "display_modes": dict(sorted(view_modes.items())),
            "excluded_rows_checked_for_validation_overlap": len(excluded_ids),
            "excluded_rows_with_validation_overlap": {},
            "source_snapshot_rows_filtered_by_validation": dict(validation_exclusions),
        },
        "selection_reasons_by_email_id": selection_reasons,
        "message_views": message_views,
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    # Validate the exact JSONL payload before writing it.
    serialized_rows = [json.loads(line) for line in seed_text.splitlines() if line.strip()]
    selected_ids = [row["email_id"] for row in serialized_rows]
    if len(selected_ids) != target_count or len(selected_ids) != len(set(selected_ids)):
        raise ValueError("generated seed has an incorrect count or duplicate IDs")
    if selected_ids != manifest["selected_email_ids"]:
        raise ValueError("generated seed order does not match the manifest")
    if set(serialized_rows[0]) != set(EXPECTED_CANONICAL_FIELDS):
        raise ValueError("generated seed does not have the canonical field contract")
    for row in serialized_rows:
        if set(row) != set(EXPECTED_CANONICAL_FIELDS):
            raise ValueError(f"generated seed row has noncanonical fields: {row['email_id']}")
        if row["email_id"] in validation_ids:
            raise ValueError(f"final-validation ID entered the queue: {row['email_id']}")
        original = original_by_id[row["email_id"]]
        if (row["source_dataset"], row["thread_id"]) in validation_threads:
            raise ValueError(f"final-validation thread entered the queue: {row['email_id']}")
        if group_mapping[row["email_id"]] in validation_groups:
            raise ValueError(f"final-validation leakage group entered the queue: {row['email_id']}")
        if row["current_message"] != original["current_message"]:
            raise ValueError(f"canonical current_message changed for {row['email_id']}")

    source_labels_by_id = {
        email_id: set(corrected_by_id[email_id]["labels"])
        for email_id in selected_reasons if email_id in corrected_by_id
    }
    label_coverage = {
        label: sum(label in labels for labels in source_labels_by_id.values())
        for label in LABEL_ORDER
    }
    report = {
        "command": "ai\\.venv\\Scripts\\python.exe ai\\scripts\\build_transfer_calibration_queue.py",
        "seed_path": str(SEED_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "manifest_path": str(MANIFEST_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "corrected_freeze": corrected_validation["records"],
        "partitions": split_report["partition_records"],
        "final_validation_rare_counts_omitted": {
            label: split_report["partition_label_counts"]["validation"][label]
            for label in LABEL_ORDER if label in RARE_LABELS
        },
        "queue_count": len(seed_rows),
        "queue_source_counts": dict(sorted(source_kinds.items())),
        "queue_partition_counts": dict(sorted(partition_counts.items())),
        "selection_reason_counts": manifest["queue_counts"],
        "visible_source_label_coverage_training_reused_not_gold": label_coverage,
        "display_view_counts": dict(sorted(view_modes.items())),
        "source_snapshot_rows_filtered_by_validation": dict(validation_exclusions),
        "selected_queue_validation_overlap": 0,
        "excluded_source_rows_checked_for_validation_overlap": len(excluded_ids),
        "excluded_source_rows_with_validation_overlap": {},
        "training_reused_not_independent_gold": True,
        "labels_prepopulated": False,
    }
    return seed_rows, manifest, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=TARGET_COUNT, help="target queue size (default: 180)")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be a positive integer")
    seed_rows, manifest, report = build_queue(args.count)
    seed_text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in seed_rows
    )
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    reviewer_dir = OUTPUT_DIR / "reviewers"
    if reviewer_dir.exists() and any(reviewer_dir.iterdir()):
        if not SEED_PATH.exists() or not MANIFEST_PATH.exists() or not TEXT_FREE_MANIFEST_PATH.exists():
            raise RuntimeError("reviewer output exists but the seed/manifest pair is incomplete")
        existing_seed_text = SEED_PATH.read_text(encoding="utf-8")
        existing_manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        tracked_manifest_text = TEXT_FREE_MANIFEST_PATH.read_text(encoding="utf-8")
        if (
            existing_seed_text != seed_text
            or existing_manifest_text != manifest_text
            or tracked_manifest_text != manifest_text
        ):
            raise RuntimeError("refusing to replace a queue that already has reviewer output")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _atomic_write(SEED_PATH, seed_text)
    _atomic_write(MANIFEST_PATH, manifest_text)
    _atomic_write(TEXT_FREE_MANIFEST_PATH, manifest_text)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Pure helpers and data checks for the tonight DistilBERT diagnostic.

PyTorch and Transformers are intentionally imported only by the training CLI,
so repository tools and tests that do not run the neural model need neither
large optional dependency installed.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .silver_classifier import LABEL_ORDER, calculate_multilabel_metrics, extract_authored_prefix


HASHED_SOURCE_FIELDS = ("subject", "current_message", "thread_context")
SOURCE_IDENTITY_FIELDS = ("email_id", "source_dataset", "thread_id", *HASHED_SOURCE_FIELDS)
DECORATIVE_SEPARATOR_RE = re.compile(r"^\s*(?:\*{20,}|-{20,}|_{20,}|={20,}|~{20,})\s*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _record_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("source_dataset") or ""), str(row.get("email_id") or "")


def _member_key(member: Any, unique_ids: set[str]) -> tuple[str, str]:
    if isinstance(member, str):
        if member not in unique_ids:
            raise ValueError(f"split contains an unknown or ambiguous email_id: {member}")
        return "", member
    if not isinstance(member, dict) or not isinstance(member.get("email_id"), str):
        raise ValueError("split members must be IDs or identity objects containing email_id")
    source = member.get("source_dataset")
    return (str(source) if source is not None else "", member["email_id"])


def source_material_sha256(record: dict[str, Any]) -> str:
    material = {
        field: _text(record.get(field))
        for field in SOURCE_IDENTITY_FIELDS
    }
    payload = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_snapshot(
    records: list[dict[str, Any]], manifest_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check the corrected full-text snapshot against its text-free AI-silver manifest."""
    if not records or not manifest_rows:
        raise ValueError("snapshot and text-free manifest must both contain records")
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    email_ids: set[str] = set()
    label_counts: Counter[str] = Counter()
    for row in records:
        key = _record_key(row)
        if not all(isinstance(value, str) and value.strip() for value in (*key, row.get("thread_id"))):
            raise ValueError("snapshot records need source_dataset, email_id, and thread_id")
        if key in by_key or key[1] in email_ids:
            raise ValueError(f"duplicate or ambiguous snapshot email_id: {key[1]}")
        email_ids.add(key[1])
        by_key[key] = row

        labels = row.get("labels")
        if not isinstance(labels, list) or not labels or any(label not in LABEL_ORDER for label in labels):
            raise ValueError(f"snapshot row has empty or unknown labels: {key}")
        if len(labels) != len(set(labels)):
            raise ValueError(f"snapshot row has duplicate labels: {key}")
        if "NON_PROJECT" in labels and len(labels) != 1:
            raise ValueError(f"NON_PROJECT must be exclusive: {key}")
        label_counts.update(labels)
        if not all(isinstance(row.get(field), str) for field in HASHED_SOURCE_FIELDS):
            raise ValueError(f"snapshot row lacks source text fields: {key}")
        authored_message = row.get("authored_message")
        extracted_message = extract_authored_prefix(row["current_message"])
        if not isinstance(authored_message, str) or not authored_message:
            raise ValueError(f"snapshot row has no authored body text: {key}")
        if authored_message != extracted_message:
            raise ValueError(f"authored_message differs from the canonical authored-prefix extractor: {key}")

        provenance = row.get("snapshot_provenance")
        if not isinstance(provenance, dict):
            raise ValueError(f"snapshot provenance is missing: {key}")
        if provenance.get("status") != "ai_silver" or provenance.get("training_provenance") != "ai_silver":
            raise ValueError(f"non-AI-silver provenance is forbidden: {key}")
        if any(provenance.get(field) != row.get(field) for field in ("email_id", "source_dataset", "thread_id")):
            raise ValueError(f"snapshot provenance identity mismatch: {key}")
        if provenance.get("labels") != labels:
            raise ValueError(f"snapshot provenance labels mismatch: {key}")
        authored_hash = hashlib.sha256(authored_message.encode("utf-8")).hexdigest()
        if provenance.get("authored_message_sha256") != authored_hash:
            raise ValueError(f"authored_message hash mismatch: {key}")
        if not all(
            isinstance(provenance.get(field), str) and provenance[field].strip()
            for field in ("leakage_group_id", "source_acceptance_manifest", "acceptance_rule")
        ):
            raise ValueError(f"snapshot acceptance provenance is incomplete: {key}")
        annotation = row.get("annotation", {})
        if (
            not isinstance(annotation, dict)
            or annotation.get("annotation_source") != "ai"
            or annotation.get("status") != "ai_prelabelled"
        ):
            raise ValueError(f"non-AI annotation source/status found in AI-silver snapshot: {key}")

        expected_field_hashes = provenance.get("source_hashes")
        if not isinstance(expected_field_hashes, dict) or set(expected_field_hashes) != set(HASHED_SOURCE_FIELDS):
            raise ValueError(f"source_hashes missing from snapshot provenance: {key}")
        for field in HASHED_SOURCE_FIELDS:
            expected = hashlib.sha256(_text(row.get(field)).encode("utf-8")).hexdigest()
            if expected_field_hashes.get(field) != expected:
                raise ValueError(f"source hash mismatch for {field}: {key}")
        if provenance.get("source_sha256") != source_material_sha256(row):
            raise ValueError(f"canonical source hash mismatch: {key}")

    manifest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    allowed_manifest_fields = {
        "email_id", "source_dataset", "thread_id", "labels", "leakage_group_id",
        "source_hashes", "source_sha256", "authored_message_sha256", "source_acceptance_manifest",
        "acceptance_rule", "status", "training_provenance",
    }
    for item in manifest_rows:
        key = _record_key(item)
        if not all(key) or key in manifest_by_key:
            raise ValueError(f"duplicate or invalid text-free manifest key: {key}")
        if set(item) != allowed_manifest_fields:
            raise ValueError(f"text-free manifest fields are missing or unexpected: {key}")
        if item.get("status") != "ai_silver" or item.get("training_provenance") != "ai_silver":
            raise ValueError(f"manifest contains a non-AI-silver row: {key}")
        manifest_by_key[key] = item
    if set(manifest_by_key) != set(by_key):
        raise ValueError("snapshot IDs do not exactly match the text-free manifest IDs")
    for key, row in by_key.items():
        provenance = row["snapshot_provenance"]
        item = manifest_by_key[key]
        for field in (
            "thread_id", "labels", "leakage_group_id", "source_hashes", "source_sha256",
            "authored_message_sha256", "source_acceptance_manifest", "acceptance_rule", "status", "training_provenance",
        ):
            left = item.get(field)
            right = provenance.get(field)
            if left != right:
                raise ValueError(f"snapshot and text-free manifest differ at {field}: {key}")

    return {
        "records": len(records),
        "label_counts": {label: label_counts[label] for label in LABEL_ORDER},
        "source_counts": dict(sorted(Counter(row["source_dataset"] for row in records).items())),
        "ai_silver_records": len(records),
        "human_or_gold_records": 0,
    }


def _normalize_partition_members(
    members: Any, records_by_key: dict[tuple[str, str], dict[str, Any]], unique_ids: set[str],
    partition_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(members, list):
        raise ValueError(f"split partition {partition_name!r} must be a list")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for member in members:
        key = _member_key(member, unique_ids)
        if not key[0]:
            matches = [candidate for candidate in records_by_key if candidate[1] == key[1]]
            if len(matches) != 1:
                raise ValueError(f"split email_id is not unique in snapshot: {key[1]}")
            key = matches[0]
        if key not in records_by_key:
            raise ValueError(f"split contains an unknown snapshot record: {key}")
        if key in seen:
            raise ValueError(f"split partition {partition_name!r} repeats {key}")
        seen.add(key)
        record = records_by_key[key]
        if isinstance(member, dict):
            for field in ("thread_id", "leakage_group_id"):
                expected = member.get(field)
                if expected is not None and expected != _identity_value(record, field):
                    raise ValueError(f"split {field} mismatch for {key}")
        result.append(record)
    return result


def _identity_value(record: dict[str, Any], field: str) -> Any:
    if field == "leakage_group_id":
        return record["snapshot_provenance"].get(field)
    return record.get(field)


def _validate_partition_isolation(partitions: dict[str, list[dict[str, Any]]]) -> None:
    thread_owner: dict[tuple[str, str], str] = {}
    group_owner: dict[str, str] = {}
    for name, rows in partitions.items():
        for row in rows:
            thread = (row["source_dataset"], row["thread_id"])
            group = row["snapshot_provenance"].get("leakage_group_id")
            if not isinstance(group, str) or not group.strip():
                raise ValueError(f"empty leakage_group_id for {row['email_id']}")
            if thread in thread_owner and thread_owner[thread] != name:
                raise ValueError(f"thread crosses split boundary: {thread}")
            if group in group_owner and group_owner[group] != name:
                raise ValueError(f"leakage group crosses split boundary: {group}")
            thread_owner[thread] = name
            group_owner[group] = name


def grouped_tuning_split(
    train_rows: list[dict[str, Any]], *, ratio: float = 0.2, seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fallback inner split that keeps thread/leakage components together."""
    if not 0 < ratio < 1 or len(train_rows) < 2:
        raise ValueError("cannot create a tuning split from fewer than two rows")
    parent = list(range(len(train_rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    first_thread: dict[tuple[str, str], int] = {}
    first_group: dict[str, int] = {}
    for index, row in enumerate(train_rows):
        thread = (row["source_dataset"], row["thread_id"])
        group = row["snapshot_provenance"]["leakage_group_id"]
        if thread in first_thread:
            union(index, first_thread[thread])
        else:
            first_thread[thread] = index
        if group in first_group:
            union(index, first_group[group])
        else:
            first_group[group] = index
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(train_rows)):
        components[find(index)].append(index)
    if len(components) < 2:
        raise ValueError("outer training set has fewer than two independent leakage groups")
    profiles = {
        root: (len(indices), Counter(label for i in indices for label in train_rows[i]["labels"]))
        for root, indices in components.items()
    }
    total_labels = Counter(label for row in train_rows for label in row["labels"])
    target_size = ratio * len(train_rows)
    target_labels = {label: ratio * total_labels[label] for label in LABEL_ORDER}
    roots = list(components)
    import random
    rng = random.Random(seed)
    rng.shuffle(roots)
    roots.sort(key=lambda root: profiles[root][0], reverse=True)
    selected: set[int] = set()
    size = 0
    counts: Counter[str] = Counter()

    def objective(candidate_size: int, candidate_counts: Counter[str]) -> float:
        score = ((candidate_size - target_size) / max(target_size, 1.0)) ** 2
        for label in LABEL_ORDER:
            goal = target_labels[label]
            score += ((candidate_counts[label] - goal) / max(goal, 1.0)) ** 2
        return score

    for root in roots:
        count, labels = profiles[root]
        if objective(size + count, counts + labels) < objective(size, counts):
            selected.add(root)
            size += count
            counts.update(labels)
    if not selected:
        selected.add(min(roots, key=lambda root: (profiles[root][0], root)))
    if len(selected) == len(components):
        selected.remove(max(selected, key=lambda root: (profiles[root][0], root)))
    tuning = [train_rows[i] for root in components if root in selected for i in components[root]]
    fit = [train_rows[i] for root in components if root not in selected for i in components[root]]
    if not fit or not tuning:
        raise ValueError("group-safe tuning split left an empty fit or tuning partition")
    _validate_partition_isolation({"fit": fit, "tuning": tuning})
    return fit, tuning


def load_shared_partitions(
    records: list[dict[str, Any]], split: dict[str, Any], *,
    snapshot_sha256: str, silver_manifest_sha256: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load fixed fit/tuning/validation IDs and verify hashes plus leakage boundaries."""
    records_by_key = {_record_key(row): row for row in records}
    unique_ids = {row["email_id"] for row in records}
    if len(unique_ids) != len(records):
        raise ValueError("snapshot email_id values must be globally unique")
    declared_hashes = {
        "snapshot_sha256": snapshot_sha256,
        "full_text_snapshot_sha256": snapshot_sha256,
        "snapshot_manifest_sha256": silver_manifest_sha256,
        "silver_manifest_sha256": silver_manifest_sha256,
        "corrected_manifest_sha256": silver_manifest_sha256,
        "manifest_sha256": silver_manifest_sha256,
    }
    manifest_hash_bound = False
    for field, actual in declared_hashes.items():
        expected = split.get(field)
        if expected is not None and expected != actual:
            raise ValueError(f"split {field} does not match the supplied snapshot")
        if field in {"snapshot_manifest_sha256", "silver_manifest_sha256", "corrected_manifest_sha256", "manifest_sha256"} and expected is not None:
            manifest_hash_bound = True
    snapshot_info = split.get("snapshot")
    if isinstance(snapshot_info, dict):
        for field, actual in (("sha256", snapshot_sha256), ("manifest_sha256", silver_manifest_sha256)):
            expected = snapshot_info.get(field)
            if expected is not None and expected != actual:
                raise ValueError(f"split snapshot.{field} does not match supplied input")
            if field == "manifest_sha256" and expected is not None:
                manifest_hash_bound = True
    if not manifest_hash_bound:
        raise ValueError("shared split must bind to the corrected text-free manifest SHA-256")
    raw = split.get("partitions")
    if not isinstance(raw, dict):
        raise ValueError("shared split manifest must contain a partitions object")
    partitions: dict[str, list[dict[str, Any]]] = {}
    if {"fit", "tuning", "validation"}.issubset(raw):
        names = ("fit", "tuning", "validation")
        for name in names:
            partitions[name] = _normalize_partition_members(raw[name], records_by_key, unique_ids, name)
    elif {"train", "validation"}.issubset(raw):
        # Existing baseline split format: inner tuning is carved only from outer train.
        train_rows = _normalize_partition_members(raw["train"], records_by_key, unique_ids, "train")
        partitions["fit"], partitions["tuning"] = grouped_tuning_split(train_rows)
        partitions["validation"] = _normalize_partition_members(
            raw["validation"], records_by_key, unique_ids, "validation",
        )
    else:
        raise ValueError("split needs fit/tuning/validation or train/validation partitions")

    owners: dict[tuple[str, str], str] = {}
    all_group_keys: set[tuple[str, str]] = set()
    for name, rows in partitions.items():
        for row in rows:
            key = _record_key(row)
            if key in owners:
                raise ValueError(f"record appears in more than one split partition: {key}")
            owners[key] = name
            all_group_keys.add(key)
    if all_group_keys != set(records_by_key):
        raise ValueError("split partition membership must cover the snapshot exactly once")
    _validate_partition_isolation(partitions)
    return partitions, {
        "partition_records": {name: len(rows) for name, rows in partitions.items()},
        "partition_label_counts": {
            name: {label: sum(label in row["labels"] for row in rows) for label in LABEL_ORDER}
            for name, rows in partitions.items()
        },
        "partition_leakage_groups": {
            name: len({row["snapshot_provenance"]["leakage_group_id"] for row in rows})
            for name, rows in partitions.items()
        },
        "fixed_outer_validation": True,
        "validation_used_for_training_or_threshold_selection": False,
    }


def record_text(record: dict[str, Any]) -> str:
    subject = _text(record.get("subject")).strip()
    body = _text(record.get("authored_message"))
    if not body:
        raise ValueError(f"record {record.get('email_id')} has no hash-validated authored_message")
    body = "\n".join(line for line in body.splitlines() if not DECORATIVE_SEPARATOR_RE.fullmatch(line)).strip()
    return f"[SUBJECT] {subject}\n[BODY] {body}"


def target_matrix(label_rows: Iterable[list[str]]) -> list[list[int]]:
    return [[int(label in set(labels)) for label in LABEL_ORDER] for labels in label_rows]


def positive_weights(label_rows: list[list[str]]) -> tuple[list[float], dict[str, dict[str, Any]]]:
    """Compute raw negative/positive weights using only the supplied fit labels."""
    if not label_rows:
        raise ValueError("fit label rows must not be empty")
    weights: list[float] = []
    report: dict[str, dict[str, Any]] = {}
    for label in LABEL_ORDER:
        positive = sum(label in labels for labels in label_rows)
        negative = len(label_rows) - positive
        weight = negative / positive if positive else 1.0
        weights.append(weight)
        report[label] = {
            "positive": positive,
            "negative": negative,
            "pos_weight": weight,
            "weight_unavailable_no_positive_fit_examples": positive == 0,
        }
    return weights, report


def exclusive_predictions(
    probability_rows: list[list[float]], thresholds: list[float],
) -> list[list[str]]:
    """Match the TF-IDF model's NON_PROJECT versus strongest-project resolution."""
    if len(thresholds) != len(LABEL_ORDER):
        raise ValueError("threshold count must match LABEL_ORDER")
    result: list[list[str]] = []
    non_project_index = LABEL_ORDER.index("NON_PROJECT")
    for probabilities in probability_rows:
        if len(probabilities) != len(LABEL_ORDER):
            raise ValueError("probability width must match LABEL_ORDER")
        labels = [label for label, probability, threshold in zip(LABEL_ORDER, probabilities, thresholds) if probability >= threshold]
        if "NON_PROJECT" in labels and len(labels) > 1:
            strongest_project = max(
                probabilities[index] for index in range(len(LABEL_ORDER)) if index != non_project_index
            )
            if probabilities[non_project_index] >= strongest_project:
                labels = ["NON_PROJECT"]
            else:
                labels.remove("NON_PROJECT")
        result.append(labels)
    return result


def tune_thresholds(
    expected_rows: list[list[str]], probability_rows: list[list[float]],
) -> tuple[list[float], dict[str, dict[str, Any]]]:
    """Tune independent label F1 cutoffs on the dedicated inner tuning partition."""
    if len(expected_rows) != len(probability_rows) or not expected_rows:
        raise ValueError("expected and probability tuning rows must have equal nonzero lengths")
    thresholds: list[float] = []
    report: dict[str, dict[str, Any]] = {}
    for index, label in enumerate(LABEL_ORDER):
        actual = [label in row for row in expected_rows]
        support = sum(actual)
        if not support:
            threshold = 0.5
            best_f1 = 0.0
        else:
            candidates = sorted({0.05, 0.95, 0.5, *(round(step / 100, 2) for step in range(5, 96, 5)), *(float(row[index]) for row in probability_rows)})
            scored = []
            for candidate in candidates:
                tp = sum(is_positive and row[index] >= candidate for is_positive, row in zip(actual, probability_rows))
                fp = sum(not is_positive and row[index] >= candidate for is_positive, row in zip(actual, probability_rows))
                fn = support - tp
                precision = tp / (tp + fp) if tp + fp else 0.0
                recall = tp / support
                f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
                scored.append((f1, -abs(candidate - 0.5), candidate))
            best_f1, _, threshold = max(scored)
        thresholds.append(threshold)
        report[label] = {
            "threshold": threshold,
            "tuning_positive_support": support,
            "tuning_records": len(expected_rows),
            "best_binary_f1_before_exclusivity": best_f1,
            "unstable_support_below_20": support < 20,
        }
    return thresholds, report


def full_diagnostic_metrics(expected: list[list[str]], predicted: list[list[str]]) -> dict[str, Any]:
    metrics = calculate_multilabel_metrics(expected, predicted)
    per_label = metrics["per_label"]
    for row in per_label.values():
        row["unstable_support_below_20"] = row["support"] < 20
    metrics["macro_precision"] = sum(row["precision"] for row in per_label.values()) / len(LABEL_ORDER)
    metrics["macro_recall"] = sum(row["recall"] for row in per_label.values()) / len(LABEL_ORDER)
    metrics["exact_set_accuracy"] = metrics["subset_match_rate"]
    metrics["no_label_predictions"] = sum(not row for row in predicted)
    metrics["no_label_expected"] = sum(not row for row in expected)
    metrics["scope"] = "AI-silver diagnostic metrics; not gold, final, or production accuracy."
    return metrics


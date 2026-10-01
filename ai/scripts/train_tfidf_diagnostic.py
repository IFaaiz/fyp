"""Run a fixed-split TF-IDF diagnostic against the corrected AI-silver freeze.

The outer validation partition is evaluated only after fitting on `fit` and
choosing per-label thresholds on `tuning`. The report contains aggregate
metrics and hashes only; it never writes source text or row-level predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = AI_DIR.parent
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from scripts.train_silver_classifier import _keyword_prediction
from src.models.silver_classifier import LABEL_ORDER, TfidfOneVsRestLogisticRegression
from src.models.transfer_diagnostic import (
    exclusive_predictions,
    full_diagnostic_metrics,
    load_shared_partitions,
    sha256_file,
    tune_thresholds,
    validate_snapshot,
)


DEFAULT_ROOT = AI_DIR / "data/experiments/tonight_20261002"
DEFAULT_SNAPSHOT = DEFAULT_ROOT / "corrected_silver_snapshot.jsonl"
DEFAULT_MANIFEST = DEFAULT_ROOT / "corrected_silver_manifest.jsonl"
DEFAULT_SPLIT = AI_DIR / "data/splits/tonight_silver_v2_shared_split.json"
DEFAULT_OUTPUT = AI_DIR / "reports/tonight_tfidf_diagnostic.json"
SEED = 20261002
HISTORICAL_MINIMUM_RECORDS = 1000
CV_FOLDS = 5


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"expected a JSON object at {path}:{line_number}")
            rows.append(value)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _source_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_DIR,
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for import_name, version_attribute in (
        ("numpy", "__version__"), ("scipy", "__version__"), ("sklearn", "__version__"),
    ):
        try:
            module = __import__(import_name)
            versions["scikit_learn" if import_name == "sklearn" else import_name] = str(
                getattr(module, version_attribute)
            )
        except ImportError:
            versions["scikit_learn" if import_name == "sklearn" else import_name] = None
    return versions


def _prevalence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {label: sum(label in row["labels"] for row in rows) for label in LABEL_ORDER}
    denominator = len(rows)
    return {
        "records": denominator,
        "positive_counts": counts,
        "positive_fraction": {
            label: counts[label] / denominator if denominator else None for label in LABEL_ORDER
        },
        "no_label_records": sum(not row["labels"] for row in rows),
        "non_project_only_records": sum(row["labels"] == ["NON_PROJECT"] for row in rows),
    }


def _component_groups(rows: list[dict[str, Any]]) -> list[list[int]]:
    """Build connected groups so neither a thread nor leakage group crosses folds."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    first_thread: dict[tuple[str, str], int] = {}
    first_leakage: dict[str, int] = {}
    for index, row in enumerate(rows):
        thread_key = (str(row["source_dataset"]), str(row["thread_id"]))
        leakage_key = str(row["snapshot_provenance"]["leakage_group_id"])
        if thread_key in first_thread:
            union(index, first_thread[thread_key])
        else:
            first_thread[thread_key] = index
        if leakage_key in first_leakage:
            union(index, first_leakage[leakage_key])
        else:
            first_leakage[leakage_key] = index
    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        groups[find(index)].append(index)
    return list(groups.values())


def _make_group_folds(
    rows: list[dict[str, Any]], *, folds: int, seed: int,
) -> tuple[list[list[int]] | None, list[str], dict[str, Any]]:
    components = _component_groups(rows)
    support = {label: sum(label in row["labels"] for row in rows) for label in LABEL_ORDER}
    positive_groups = {
        label: sum(any(label in rows[index]["labels"] for index in group) for group in components)
        for label in LABEL_ORDER
    }
    common = [
        label for label in LABEL_ORDER
        if support[label] >= 20 and positive_groups[label] >= folds
    ]
    base_report: dict[str, Any] = {
        "method": "deterministic greedy assignment of connected thread/leakage components",
        "fold_count": folds,
        "fit_records": len(rows),
        "independent_components": len(components),
        "fit_positive_support": support,
        "positive_components": positive_groups,
        "common_labels_evaluated": common,
        "rare_or_group_limited_labels_unstable": [label for label in LABEL_ORDER if label not in common],
        "threshold_policy": "fixed 0.5 in every fold; no threshold tuning on the held-out fold",
    }
    if len(components) < folds:
        return None, common, {**base_report, "status": "skipped", "reason": "fewer than five independent components"}
    if not common:
        return None, common, {**base_report, "status": "skipped", "reason": "no labels have at least 20 positives in at least five independent components"}

    group_profiles = []
    for component_index, indices in enumerate(components):
        counts = Counter(label for index in indices for label in rows[index]["labels"] if label in common)
        rarity = sum(count / max(support[label], 1) for label, count in counts.items())
        group_profiles.append((component_index, len(indices), counts, rarity))
    target_size = len(rows) / folds
    target_labels = {label: support[label] / folds for label in common}

    def objective(sizes: list[int], label_counts: list[Counter[str]]) -> float:
        score = sum(((size - target_size) / max(target_size, 1.0)) ** 2 for size in sizes)
        for label in common:
            scale = max(target_labels[label], 1.0)
            score += sum(((count[label] - target_labels[label]) / scale) ** 2 for count in label_counts)
        return score

    best: tuple[float, list[list[int]], list[Counter[str]]] | None = None
    rng = random.Random(seed)
    for _attempt in range(256):
        randomized = list(group_profiles)
        rng.shuffle(randomized)
        randomized.sort(key=lambda item: (item[3], item[1]), reverse=True)
        fold_groups: list[list[int]] = [[] for _ in range(folds)]
        fold_sizes = [0] * folds
        fold_counts = [Counter() for _ in range(folds)]
        for group_index, group_size, counts, _rarity in randomized:
            candidate_scores = []
            for fold_index in range(folds):
                sizes_after = list(fold_sizes)
                counts_after = [Counter(value) for value in fold_counts]
                sizes_after[fold_index] += group_size
                counts_after[fold_index].update(counts)
                candidate_scores.append((objective(sizes_after, counts_after), fold_index))
            _, chosen = min(candidate_scores)
            fold_groups[chosen].append(group_index)
            fold_sizes[chosen] += group_size
            fold_counts[chosen].update(counts)
        record_folds = [
            [index for group_index in selected for index in components[group_index]]
            for selected in fold_groups
        ]
        score = objective(fold_sizes, fold_counts)
        if best is None or score < best[0]:
            best = (score, record_folds, fold_counts)
        if all(all(fold_counts[i][label] > 0 for label in common) for i in range(folds)):
            best = (score, record_folds, fold_counts)
            break
    assert best is not None
    _score, record_folds, fold_counts = best
    missing = {
        f"fold_{index + 1}": [label for label in common if not fold_counts[index][label]]
        for index in range(folds)
    }
    if any(missing.values()):
        return None, common, {
            **base_report, "status": "skipped",
            "reason": "could not place at least one real positive for every common label in each held-out fold",
            "missing_common_positive_support_by_fold": missing,
        }
    return record_folds, common, {
        **base_report, "status": "feasible", "fold_record_counts": [len(value) for value in record_folds],
        "fold_common_positive_counts": [dict(value) for value in fold_counts],
    }


def _common_macro_f1(metrics: dict[str, Any], labels: list[str]) -> float | None:
    if not labels:
        return None
    return sum(metrics["per_label"][label]["f1"] for label in labels) / len(labels)


def _cross_validation(rows: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    folds, common, report = _make_group_folds(rows, folds=CV_FOLDS, seed=seed)
    if folds is None:
        return report
    fold_reports = []
    for fold_index, validation_indices in enumerate(folds):
        held_out = set(validation_indices)
        train_rows = [row for index, row in enumerate(rows) if index not in held_out]
        validation_rows = [rows[index] for index in validation_indices]
        model = TfidfOneVsRestLogisticRegression(
            c=1.0, threshold=0.5, max_iter=1000, seed=seed, optimizer="sklearn",
        )
        started = time.perf_counter()
        model.fit(train_rows)
        fit_seconds = time.perf_counter() - started
        probabilities = [
            [model.predict_proba(row)[label] for label in LABEL_ORDER]
            for row in validation_rows
        ]
        predictions = exclusive_predictions(probabilities, [0.5] * len(LABEL_ORDER))
        expected = [row["labels"] for row in validation_rows]
        metrics = full_diagnostic_metrics(expected, predictions)
        fold_reports.append({
            "fold": fold_index + 1,
            "fit_records": len(train_rows),
            "held_out_records": len(validation_rows),
            "fit_seconds": fit_seconds,
            "metrics": metrics,
            "common_label_macro_f1": _common_macro_f1(metrics, common),
            "held_out_positive_support": {
                label: sum(label in row["labels"] for row in validation_rows) for label in LABEL_ORDER
            },
        })
    micro_f1_values = [entry["metrics"]["micro_f1"] for entry in fold_reports]
    common_macro_values = [entry["common_label_macro_f1"] for entry in fold_reports]
    report.update({
        "status": "complete",
        "folds": fold_reports,
        "mean_fold_micro_f1": sum(micro_f1_values) / len(micro_f1_values),
        "mean_fold_common_label_macro_f1": sum(common_macro_values) / len(common_macro_values),
        "scope": "Exploratory grouped folds within the fixed fit partition only; not used to select the final model.",
    })
    return report


def _latency_report(model: TfidfOneVsRestLogisticRegression, rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample = rows[: min(24, len(rows))]
    if not sample:
        return {"sample_records": 0, "single_record_ms": None, "batch_ms_per_record": None}
    model.predict_proba(sample[0])
    single_repetitions = 10
    started = time.perf_counter()
    for _ in range(single_repetitions):
        model.predict_proba(sample[0])
    single_elapsed = time.perf_counter() - started
    batch_repetitions = 3
    started = time.perf_counter()
    for _ in range(batch_repetitions):
        for row in sample:
            model.predict_proba(row)
    batch_elapsed = time.perf_counter() - started
    return {
        "sample_records": len(sample),
        "single_record_repetitions": single_repetitions,
        "single_record_ms": 1000 * single_elapsed / single_repetitions,
        "batch_repetitions": batch_repetitions,
        "batch_ms_per_record": 1000 * batch_elapsed / (batch_repetitions * len(sample)),
        "measurement": "CPU wall clock; includes TF-IDF transform and all nine label scores; first sample warmed once",
    }


def run(snapshot_path: Path, manifest_path: Path, split_path: Path, output_path: Path) -> dict[str, Any]:
    for path in (snapshot_path, manifest_path, split_path):
        if not path.is_file():
            raise FileNotFoundError(f"required corrected-freeze input does not exist: {path}")
    snapshot_rows = read_jsonl(snapshot_path)
    manifest_rows = read_jsonl(manifest_path)
    snapshot_report = validate_snapshot(snapshot_rows, manifest_rows)
    snapshot_hash = sha256_file(snapshot_path)
    manifest_hash = sha256_file(manifest_path)
    split_payload = json.loads(split_path.read_text(encoding="utf-8"))
    partitions, split_report = load_shared_partitions(
        snapshot_rows, split_payload,
        snapshot_sha256=snapshot_hash,
        silver_manifest_sha256=manifest_hash,
    )

    fit_rows = partitions["fit"]
    tuning_rows = partitions["tuning"]
    validation_rows = partitions["validation"]
    model = TfidfOneVsRestLogisticRegression(
        c=1.0, threshold=0.5, max_iter=1000, seed=SEED, optimizer="sklearn",
    )
    training_started = time.perf_counter()
    model.fit(fit_rows)
    training_seconds = time.perf_counter() - training_started

    tuning_started = time.perf_counter()
    tuning_probabilities = [
        [model.predict_proba(row)[label] for label in LABEL_ORDER] for row in tuning_rows
    ]
    tuning_inference_seconds = time.perf_counter() - tuning_started
    thresholds, threshold_report = tune_thresholds(
        [row["labels"] for row in tuning_rows], tuning_probabilities,
    )
    validation_started = time.perf_counter()
    validation_probabilities = [
        [model.predict_proba(row)[label] for label in LABEL_ORDER] for row in validation_rows
    ]
    validation_inference_seconds = time.perf_counter() - validation_started
    validation_expected = [row["labels"] for row in validation_rows]
    fixed_predictions = exclusive_predictions(
        validation_probabilities, [0.5] * len(LABEL_ORDER),
    )
    tuned_predictions = exclusive_predictions(validation_probabilities, thresholds)
    always_np_predictions = [["NON_PROJECT"] for _ in validation_rows]
    keyword_predictions = [_keyword_prediction(row) for row in validation_rows]

    # Match TfidfOneVsRestLogisticRegression.save() byte-for-byte for a portable
    # size estimate, while keeping this run's only persisted artifact the report.
    model_bytes = (
        json.dumps(model.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    convergence = {
        label: {
            "iterations": model.classifiers[label]["iterations"],
            "converged": model.classifiers[label]["converged"],
            "fit_positive_support": model.classifiers[label]["training_positive"],
            "fit_negative_support": model.classifiers[label]["training_negative"],
        }
        for label in LABEL_ORDER
    }
    cv_started = time.perf_counter()
    cv_report = _cross_validation(fit_rows, SEED)
    cv_seconds = time.perf_counter() - cv_started

    report = {
        "scope": "AI-silver diagnostic metrics; not gold, final, or production accuracy.",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "training_ready": False,
        "historical_gate": {
            "minimum_ai_silver_records": HISTORICAL_MINIMUM_RECORDS,
            "corrected_snapshot_ai_silver_records": len(snapshot_rows),
            "minimum_met": len(snapshot_rows) >= HISTORICAL_MINIMUM_RECORDS,
            "prototype_override_used": True,
            "override_reason": "One-off diagnostic explicitly requested on the corrected fixed split; this override does not grant training readiness.",
            "training_ready": False,
        },
        "model": {
            "family": "TF-IDF + one-vs-rest logistic regression",
            "optimizer": "scikit-learn LogisticRegression(solver='lbfgs')",
            "C": 1.0,
            "max_iter": 1000,
            "seed": SEED,
            "portable_model_serialized_bytes": len(model_bytes),
            "portable_model_serialized_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "portable_model_persisted": False,
            "fit_seconds": training_seconds,
            "label_convergence": convergence,
            "optimizer_package_versions": model.optimizer_versions,
        },
        "fixed_split": {
            "fit_prevalence": _prevalence(fit_rows),
            "tuning_prevalence": _prevalence(tuning_rows),
            "validation_prevalence": _prevalence(validation_rows),
            "thresholds_tuned_on_tuning_only": threshold_report,
            "tuning_probability_seconds": tuning_inference_seconds,
            "validation_metrics": {
                "tfidf_threshold_0_5": full_diagnostic_metrics(validation_expected, fixed_predictions),
                "tfidf_threshold_tuned": full_diagnostic_metrics(validation_expected, tuned_predictions),
                "always_non_project": full_diagnostic_metrics(validation_expected, always_np_predictions),
                "existing_keyword_baseline": full_diagnostic_metrics(validation_expected, keyword_predictions),
            },
            "inference_latency": _latency_report(model, validation_rows),
            "validation_prediction_seconds": validation_inference_seconds,
            "validation_prediction_ms_per_record": (
                1000 * validation_inference_seconds / len(validation_rows) if validation_rows else None
            ),
            "final_validation_used_for_training_or_threshold_selection": False,
        },
        "group_safe_5fold_diagnostic": cv_report,
        "group_safe_5fold_seconds": cv_seconds,
        "label_order": list(LABEL_ORDER),
        "input": {
            "snapshot": str(snapshot_path),
            "snapshot_sha256": snapshot_hash,
            "text_free_manifest": str(manifest_path),
            "text_free_manifest_sha256": manifest_hash,
            "shared_split": str(split_path),
            "shared_split_sha256": sha256_file(split_path),
            "source_commit_sha": _source_commit_sha(),
            "implementation_sha256": {
                "train_tfidf_diagnostic.py": sha256_file(Path(__file__).resolve()),
                "transfer_diagnostic.py": sha256_file(AI_DIR / "src/models/transfer_diagnostic.py"),
                "silver_classifier.py": sha256_file(AI_DIR / "src/models/silver_classifier.py"),
                "train_silver_classifier.py": sha256_file(AI_DIR / "scripts/train_silver_classifier.py"),
            },
            "snapshot_validation": snapshot_report,
            "split_validation": split_report,
            "provenance": "Corrected AI-silver snapshot only; human/gold rows excluded and rejected.",
            "source_text_written_to_report": False,
        },
        "packages": _package_versions(),
        "gold_test_evaluated": False,
        "human_or_gold_rows_used": 0,
    }
    _write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--split-manifest", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.snapshot, args.manifest, args.split_manifest, args.output)
    fixed = report["fixed_split"]["validation_metrics"]
    print(json.dumps({
        "report": str(args.output),
        "snapshot_records": report["input"]["snapshot_validation"]["records"],
        "partition_records": report["input"]["split_validation"]["partition_records"],
        "fit_seconds": report["model"]["fit_seconds"],
        "tfidf_fixed_micro_f1": fixed["tfidf_threshold_0_5"]["micro_f1"],
        "tfidf_tuned_micro_f1": fixed["tfidf_threshold_tuned"]["micro_f1"],
        "training_ready": report["training_ready"],
        "cv_status": report["group_safe_5fold_diagnostic"]["status"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

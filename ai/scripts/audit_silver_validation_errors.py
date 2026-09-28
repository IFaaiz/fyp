"""Produce an ID-only diagnostic worksheet for AI-silver validation mistakes.

This compares model predictions to provisional silver labels. It does not
estimate accuracy against human gold or change the trained model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from scripts.train_silver_classifier import (
    eligible_ai_silver, join_text_free_acceptance_manifest,
    read_curated_exclusions,
)
from src.datasets.schemas import read_jsonl
from src.models.silver_classifier import TfidfOneVsRestLogisticRegression


def category(expected: set[str], predicted: set[str]) -> str:
    if not predicted:
        return "empty_prediction"
    if expected == {"NON_PROJECT"} and predicted != {"NON_PROJECT"}:
        return "spurious_project_on_negative"
    if expected != {"NON_PROJECT"} and predicted == {"NON_PROJECT"}:
        return "missed_project_as_negative"
    return "project_label_mismatch"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, nargs="+", default=[AI_DIR / "data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl"])
    parser.add_argument("--accepted-manifest", type=Path, nargs="+", required=True)
    parser.add_argument("--source-records", type=Path, nargs="+", required=True)
    parser.add_argument("--exclude-manifest", type=Path, default=AI_DIR / "annotation/training_leakage_exclusions.json")
    parser.add_argument("--split-manifest", type=Path, default=AI_DIR / "data/splits/ai_silver_train_validation.json")
    parser.add_argument("--model", type=Path, default=AI_DIR / "data/models/tfidf_ovr_logistic.json")
    parser.add_argument("--output", type=Path, default=AI_DIR / "data/splits/ai_silver_validation_errors.jsonl")
    parser.add_argument("--summary", type=Path, default=AI_DIR / "data/splits/ai_silver_validation_error_summary.json")
    args = parser.parse_args()

    records = [row for path in args.input for row in read_jsonl(path)]
    joined, _ = join_text_free_acceptance_manifest(args.accepted_manifest, args.source_records)
    records.extend(joined)
    exclusions, _ = read_curated_exclusions(args.exclude_manifest)
    by_key = {}
    for row in records:
        key = (row["source_dataset"], row["email_id"])
        if key in by_key:
            raise ValueError(f"duplicate input key: {key}")
        if row["email_id"] not in exclusions and eligible_ai_silver(row):
            by_key[key] = row
    split = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    selected = split["partitions"]["validation"]
    model = TfidfOneVsRestLogisticRegression.load(args.model)
    if model.metadata.get("input_sha256") != split.get("input_sha256"):
        raise ValueError("model and validation split have different source input hashes")
    if model.metadata.get("leakage_sidecar_sha256") != split.get("leakage_sidecar_sha256"):
        raise ValueError("model and validation split have different leakage sidecars")
    errors = []
    false_negatives = Counter()
    false_positives = Counter()
    categories = Counter()
    for member in selected:
        key = (member["source_dataset"], member["email_id"])
        row = by_key.get(key)
        if row is None:
            raise ValueError(f"validation split ID missing from eligible source: {key}")
        expected = set(row["labels"])
        predicted = set(model.predict(row)["labels"])
        if expected == predicted:
            continue
        missing = sorted(expected - predicted)
        extra = sorted(predicted - expected)
        false_negatives.update(missing)
        false_positives.update(extra)
        kind = category(expected, predicted)
        categories[kind] += 1
        errors.append({
            "source_dataset": key[0], "email_id": key[1],
            "expected_ai_silver_labels": sorted(expected),
            "predicted_labels": sorted(predicted),
            "false_negative_labels": missing,
            "false_positive_labels": extra,
            "error_category": kind,
        })
    errors.sort(key=lambda row: (hashlib.sha256(row["email_id"].encode("utf-8")).hexdigest(), row["email_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in errors), encoding="utf-8", newline="\n")
    summary = {
        "scope": "AI-silver validation diagnostic, not human-gold accuracy",
        "validation_rows": len(selected),
        "error_rows": len(errors),
        "error_categories": dict(sorted(categories.items())),
        "false_negative_labels": dict(sorted(false_negatives.items())),
        "false_positive_labels": dict(sorted(false_positives.items())),
        "manual_review_target": min(50, len(errors)),
        "manual_review_ids": [row["email_id"] for row in errors[:50]],
        "text_free": True,
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"validation_rows": len(selected), "errors": len(errors), "manual_review_target": summary["manual_review_target"]}))


if __name__ == "__main__":
    main()

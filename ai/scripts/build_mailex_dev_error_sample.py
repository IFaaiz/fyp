"""Create a private, source-bearing stratified DEV error-review sample.

The output is restricted to the ignored MailEx experiment audit directory.
It includes source text and native event records for authorized manual review;
do not copy the generated JSONL into public reports or commits.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = ROOT / "ai"
sys.path.insert(0, str(AI_ROOT))

from src.mailex_extraction.metrics import (  # noqa: E402
    _assign_diagnostic_events,
    _assign_primary_records,
    _event_exact,
    _validate_rows,
    span_iou,
    _span_exact,
    score_rows,
)
from src.mailex_extraction.gliner_backend import DEV_SHA256, sha256_file  # noqa: E402


SAFE_ROOT = AI_ROOT / "data" / "experiments" / "mailex_extraction_v1"
PRIVATE_AUDIT = SAFE_ROOT / "private_dev_audit"
DEFAULT_SEED = 20261004


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"row {line_number} must be an object")
            rows.append(row)
    return rows


def event_trigger_summary(gold_event, pred_event) -> tuple[float | None, bool | None]:
    if gold_event is None or pred_event is None:
        return None, None
    if not gold_event.trigger.segments or not pred_event.trigger.segments:
        return None, None
    return span_iou(gold_event.trigger, pred_event.trigger), _span_exact(gold_event.trigger, pred_event.trigger)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--per-stratum", type=int, default=25)
    args = parser.parse_args()
    gold_path = SAFE_ROOT / "dev_fyp_safe.jsonl"
    if sha256_file(gold_path) != DEV_SHA256:
        raise ValueError("safe DEV gold fingerprint mismatch")
    try:
        args.output.resolve().relative_to(PRIVATE_AUDIT.resolve())
    except ValueError as exc:
        raise ValueError("source-bearing sample output must stay inside private_dev_audit") from exc
    if args.output.exists():
        raise FileExistsError("refusing to overwrite a private review artifact")

    gold_rows = read_jsonl(gold_path)
    pred_rows = read_jsonl(args.predictions)
    # Full evaluator validation enforces exact text identity and all offsets.
    score_rows(gold_rows, pred_rows, split="dev")
    source_counts: Counter[str] = Counter()
    gold_by_id = _validate_rows(gold_rows, gold=True, source_counts=source_counts)
    pred_by_id = _validate_rows(pred_rows, gold=False, source_counts=source_counts)
    raw_gold = {row["message_id"]: row for row in gold_rows if row.get("split") == "dev"}
    raw_pred = {row["message_id"]: row for row in pred_rows if row.get("split") == "dev"}

    candidates: dict[str, list[dict[str, Any]]] = {
        "same_type_record_error": [],
        "residual_event_alignment": [],
        "missed_gold_event": [],
        "unmatched_predicted_event": [],
    }
    for message_id in sorted(set(gold_by_id) | set(pred_by_id)):
        gold_message = gold_by_id.get(message_id)
        pred_message = pred_by_id.get(message_id)
        gold_events = gold_message.events if gold_message else ()
        pred_events = pred_message.events if pred_message else ()
        primary_pairs = _assign_primary_records(gold_events, pred_events)
        primary_gold = {gi for gi, _ in primary_pairs}
        primary_pred = {pi for _, pi in primary_pairs}
        residual_gold_indices = [i for i in range(len(gold_events)) if i not in primary_gold]
        residual_pred_indices = [i for i in range(len(pred_events)) if i not in primary_pred]
        residual_pairs_local = _assign_diagnostic_events(
            [gold_events[i] for i in residual_gold_indices],
            [pred_events[i] for i in residual_pred_indices],
        )
        diagnostic_pairs = [
            (residual_gold_indices[gi], residual_pred_indices[pi])
            for gi, pi in residual_pairs_local
        ]
        classified_gold = primary_gold | {gi for gi, _ in diagnostic_pairs}
        classified_pred = primary_pred | {pi for _, pi in diagnostic_pairs}

        for gi, pi in primary_pairs:
            if not _event_exact(gold_events[gi], pred_events[pi]):
                candidates["same_type_record_error"].append((message_id, gi, pi))
        for gi, pi in diagnostic_pairs:
            candidates["residual_event_alignment"].append((message_id, gi, pi))
        for gi in range(len(gold_events)):
            if gi not in classified_gold:
                candidates["missed_gold_event"].append((message_id, gi, None))
        for pi in range(len(pred_events)):
            if pi not in classified_pred:
                candidates["unmatched_predicted_event"].append((message_id, None, pi))

    randomizer = random.Random(args.seed)
    sampled: list[tuple[str, str, int | None, int | None]] = []
    for stratum, choices in candidates.items():
        if len(choices) < args.per_stratum:
            raise ValueError(f"stratum {stratum!r} has only {len(choices)} candidates")
        selected = randomizer.sample(choices, args.per_stratum)
        sampled.extend((stratum, *selection) for selection in selected)

    output_rows = []
    for sample_index, (stratum, message_id, gold_index, pred_index) in enumerate(sampled, 1):
        gold_raw = raw_gold.get(message_id)
        pred_raw = raw_pred.get(message_id)
        gold_event = gold_by_id.get(message_id).events[gold_index] if gold_index is not None else None
        pred_event = pred_by_id.get(message_id).events[pred_index] if pred_index is not None else None
        trigger_iou, trigger_exact = event_trigger_summary(gold_event, pred_event)
        output_rows.append({
            "sample_index": sample_index,
            "message_id": message_id,
            "source_text": (gold_raw or pred_raw)["text"],
            "category": stratum,
            "categories": [stratum],
            "gold_event_index": gold_index,
            "prediction_event_index": pred_index,
            "gold_event": gold_raw["events"][gold_index] if gold_raw is not None and gold_index is not None else None,
            "predicted_event": pred_raw["events"][pred_index] if pred_raw is not None and pred_index is not None else None,
            "message_gold_events": gold_raw["events"] if gold_raw is not None else [],
            "message_predicted_events": pred_raw["events"] if pred_raw is not None else [],
            "trigger_iou": trigger_iou,
            "trigger_exact": trigger_exact,
            "phase10_primary_category": None,
            "phase10_categories": [],
            "issue_attribution": ["pending_manual_review"],
            "review_status": "pending_manual_review",
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({
        "status": "complete",
        "sample_count": len(output_rows),
        "sample_seed": args.seed,
        "sampled_per_stratum": args.per_stratum,
        "strata": {name: len(rows) for name, rows in candidates.items()},
        "selected": {name: args.per_stratum for name in candidates},
        "gold_sha256": DEV_SHA256,
        "prediction_sha256": sha256_file(args.predictions),
        "output": args.output.name,
        "phase10_labels": "pending manual review",
        "source_bearing": True,
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

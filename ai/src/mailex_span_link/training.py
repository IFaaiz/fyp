"""Training, evaluation, runtime gates, and private run logging for the diagnostic."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import subprocess
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer

from src.mailex_extraction.compact import canonical_rows, encode_features, inventory, set_seed
from src.mailex_extraction.metrics import score_rows
from .model import SpanLinkModel, propose_spans, token_span_bounds, trigger_token_indices


AI_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AI_ROOT.parent
CONFIG_PATH = AI_ROOT / "config" / "mailex_span_link_preregistration.json"
TRAIN_PATH = REPO_ROOT / "ai" / "data" / "experiments" / "mailex_extraction_v1" / "train_fyp_safe.jsonl"
DEV_PATH = REPO_ROOT / "ai" / "data" / "experiments" / "mailex_extraction_v1" / "dev_fyp_safe.jsonl"
ENCODER_PATH = AI_ROOT / "data" / "cache" / "distilbert-base-uncased"
PRIVATE_ROOT = AI_ROOT / "data" / "experiments" / "mailex_span_link_diagnostic"
BUDGET_LEDGER_PATH = PRIVATE_ROOT / "budget_ledger.json"


class BudgetExpired(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(value)
    return rows


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _verify_preregistration(config: Mapping[str, Any]) -> dict[str, str]:
    """Refuse a run if the registered config is absent from or differs from HEAD."""
    relative = CONFIG_PATH.relative_to(REPO_ROOT).as_posix()
    committed = subprocess.run(["git", "rev-parse", f"HEAD:{relative}"], cwd=REPO_ROOT,
                               check=True, capture_output=True, text=True).stdout.strip()
    working = subprocess.run(["git", "hash-object", str(CONFIG_PATH)], cwd=REPO_ROOT,
                             check=True, capture_output=True, text=True).stdout.strip()
    if not committed or committed != working:
        raise RuntimeError("preregistration config is not identical to the committed HEAD blob")
    return {"commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                                     check=True, capture_output=True, text=True).stdout.strip(),
            "config_git_blob": committed,
            "config_sha256": _sha256(CONFIG_PATH)}


def _validate_fixed_inputs(config: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    train_record = config["scope"]["training_data"]
    dev_record = config["scope"]["development_data"]
    for path, registered, expected_split in ((TRAIN_PATH, train_record, "train"),
                                             (DEV_PATH, dev_record, "dev")):
        if path.relative_to(REPO_ROOT).as_posix() != registered["path"]:
            raise RuntimeError("fixed data path differs from preregistration")
        if _sha256(path) != registered["sha256"]:
            raise RuntimeError(f"{expected_split} input hash differs from preregistration")
    train_rows = canonical_rows(_load_jsonl(TRAIN_PATH))
    dev_rows = canonical_rows(_load_jsonl(DEV_PATH))
    empty_counts: dict[str, int] = {}
    for rows, registered, name in ((train_rows, train_record, "train"), (dev_rows, dev_record, "dev")):
        events = [event for row in rows for event in row["events"]]
        arguments = [argument for event in events for argument in event["arguments"]]
        if (len(rows), len(events), len(arguments)) != (
                registered["messages"], registered["events"], registered["arguments"]):
            raise RuntimeError(f"{name} counts differ from preregistration")
        for row in rows:
            if row.get("split") != name:
                raise RuntimeError(f"{name} view contains an unexpected split value")
        empty_model_rows = [row for row in rows if not row["tokens"]]
        supervised_empty = [row for row in empty_model_rows if row["events"]
                            or any(event["arguments"] for event in row["events"])]
        if name == "train" and supervised_empty:
            raise RuntimeError("zero-token TRAIN row carries supervision; fail closed instead of excluding it")
        empty_counts[f"{name}_zero_model_token_rows"] = len(empty_model_rows)
        empty_counts[f"{name}_zero_model_token_rows_with_events"] = sum(bool(row["events"])
                                                                           for row in empty_model_rows)
        empty_counts[f"{name}_zero_model_token_rows_with_arguments"] = sum(
            len(event["arguments"]) for row in empty_model_rows for event in row["events"])
    empty_counts["train_effective_model_rows"] = len(train_rows) - empty_counts["train_zero_model_token_rows"]
    return train_rows, dev_rows, empty_counts


def _load_prior_budget_usage() -> tuple[float, list[dict[str, Any]], str]:
    """Carry one registered wall budget across all diagnostic attempts."""
    if BUDGET_LEDGER_PATH.is_file():
        ledger = json.loads(BUDGET_LEDGER_PATH.read_text(encoding="utf-8"))
        if ledger.get("budget_seconds") != 3600:
            raise RuntimeError("existing private budget ledger does not match the registered one-hour cap")
        attempts = list(ledger.get("attempts", []))
        return (float(ledger.get("total_spent_seconds", 0.0)), attempts,
                str(ledger["first_attempt_started_utc"]))

    attempts: list[dict[str, Any]] = []
    starts: list[datetime] = []
    runs_dir = PRIVATE_ROOT / "runs"
    if runs_dir.is_dir():
        for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
            metadata_path = run_dir / "run_metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
            try:
                directory_time = datetime.strptime(run_dir.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                starts.append(directory_time - timedelta(seconds=60))
            except ValueError:
                raw_started = metadata.get("started_utc")
                if raw_started:
                    starts.append(datetime.fromisoformat(raw_started.replace("Z", "+00:00")))
            epoch_seconds = 0.0
            for history_path in run_dir.glob("seed_*/training_history.json"):
                history = json.loads(history_path.read_text(encoding="utf-8"))
                epoch_seconds += sum(float(epoch.get("epoch_seconds", 0.0))
                                     for epoch in history.get("epochs", []))
            spent = max(epoch_seconds, float(metadata.get("elapsed_gpu_wall_seconds", 0.0)))
            if spent > 0.0:
                attempts.append({"run_id": metadata.get("run_id", run_dir.name),
                                 "status": metadata.get("status", "interrupted_or_partial"),
                                 "gpu_wall_seconds": spent,
                                 "source": "maximum of saved run wall time and saved epoch times"})
    if not starts:
        raise RuntimeError("one-hour attempt deadline has no recoverable first-attempt timestamp")
    return (sum(float(item["gpu_wall_seconds"]) for item in attempts), attempts,
            min(starts).astimezone(timezone.utc).isoformat())


def _save_budget_ledger(attempts: list[dict[str, Any]], run_id: str,
                        status: str, run_seconds: float, first_attempt_started_utc: str) -> dict[str, Any]:
    updated = [item for item in attempts if item.get("run_id") != run_id]
    updated.append({"run_id": run_id, "status": status,
                    "gpu_wall_seconds": float(run_seconds),
                    "source": "run monotonic elapsed, including interrupted partial epoch time"})
    total = sum(float(item["gpu_wall_seconds"]) for item in updated)
    ledger = {"schema_version": 1, "budget_seconds": 3600,
              "training_deadline_seconds": 3300, "attempts": updated,
              "first_attempt_started_utc": first_attempt_started_utc,
              "first_attempt_timestamp_source": "conservative timestamp: 60 seconds before the earliest persisted run directory name",
              "total_spent_seconds": total,
              "remaining_gpu_seconds": max(0.0, 3600 - total),
              "elapsed_wall_seconds_since_first_attempt": max(
                  0.0, (datetime.now(timezone.utc)
                        - datetime.fromisoformat(first_attempt_started_utc)).total_seconds()),
              "remaining_wall_seconds": max(
                  0.0, 3600 - (datetime.now(timezone.utc)
                               - datetime.fromisoformat(first_attempt_started_utc)).total_seconds())}
    _write_json(BUDGET_LEDGER_PATH, ledger)
    return ledger


def _all_gold_spans(row: Mapping[str, Any]) -> set[tuple[int, int]]:
    spans = set()
    for event in row["events"]:
        for argument in event["arguments"]:
            spans.add(token_span_bounds(row, argument))
    return spans


def _boundary_target(row: Mapping[str, Any], device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    count = len(row["tokens"])
    starts = torch.zeros(count, dtype=torch.float32, device=device)
    ends = torch.zeros(count, dtype=torch.float32, device=device)
    for span in _all_gold_spans(row):
        starts[span[0]] = 1.0
        ends[span[1]] = 1.0
    return starts, ends


def _sample_negative_spans(positive: set[tuple[int, int]], token_count: int,
                           rng: random.Random) -> set[tuple[int, int]]:
    if token_count <= 0:
        return set()
    target = min(64, max(8, 4 * len(positive)))
    negatives: set[tuple[int, int]] = set()
    # Add endpoint-neighbour hard negatives first, including long-span boundary
    # perturbations; no span-width cutoff is used.
    for start, end in sorted(positive):
        for candidate in ((start - 1, end), (start + 1, end), (start, end - 1), (start, end + 1)):
            if 0 <= candidate[0] <= candidate[1] < token_count and candidate not in positive:
                negatives.add(candidate)
                if len(negatives) >= target:
                    return negatives
    widths = [end - start + 1 for start, end in positive] or [1]
    attempts = 0
    while len(negatives) < target and attempts < target * 30:
        attempts += 1
        width = min(token_count, max(1, rng.choice(widths)))
        start = rng.randrange(0, token_count - width + 1)
        candidate = (start, start + width - 1)
        if candidate not in positive:
            negatives.add(candidate)
    return negatives


def _positive_weight(target: torch.Tensor) -> torch.Tensor:
    positive = target.sum()
    if positive <= 0:
        return target.new_tensor(1.0)
    negative = target.numel() - positive
    return torch.sqrt(negative.clamp_min(1.0) / positive).clamp(1.0, 50.0)


def _role_positive_weights(train_rows: Sequence[Mapping[str, Any]], role_keys: Sequence[tuple[str, str]],
                           device: torch.device) -> torch.Tensor:
    counts = Counter((argument["role"], argument.get("qualifier") or "")
                     for row in train_rows for event in row["events"] for argument in event["arguments"])
    total = sum(counts.values())
    values = [min(50.0, max(1.0, math.sqrt(max(1, total - counts[key]) / max(1, counts[key]))))
              for key in role_keys]
    return torch.tensor(values, dtype=torch.float32, device=device)


def _training_row_loss(model: SpanLinkModel, row: Mapping[str, Any], words: torch.Tensor,
                       seed: int, epoch: int, row_index: int,
                       role_pos_weights: torch.Tensor) -> tuple[torch.Tensor, dict[str, float]]:
    if len(words) == 0:
        raise ValueError("zero-token model rows must be skipped before span losses")
    start_logits, end_logits = model.boundary_logits(words)
    start_target, end_target = _boundary_target(row, words.device)
    start_loss = F.binary_cross_entropy_with_logits(start_logits.float(), start_target,
                                                    pos_weight=_positive_weight(start_target))
    end_loss = F.binary_cross_entropy_with_logits(end_logits.float(), end_target,
                                                  pos_weight=_positive_weight(end_target))
    boundary_loss = (start_loss + end_loss) * 0.5

    positives = _all_gold_spans(row)
    rng = random.Random((seed * 1_000_003) + (epoch * 10_007) + row_index)
    negatives = _sample_negative_spans(positives, len(row["tokens"]), rng)
    candidate_spans = sorted(positives | negatives)
    span_reps = model.span_representations(words, candidate_spans)
    span_logits = model.span_logits(span_reps)
    proposal_target = torch.tensor([1.0 if item in positives else 0.0 for item in candidate_spans],
                                   dtype=torch.float32, device=words.device)
    proposal_loss = F.binary_cross_entropy_with_logits(span_logits.float(), proposal_target,
                                                       pos_weight=_positive_weight(proposal_target))

    candidate_index = {span: index for index, span in enumerate(candidate_spans)}
    link_losses = []
    for event in row["events"]:
        role_logits = model.role_logits(span_reps, words, candidate_spans, event["event_type"],
                                        trigger_token_indices(row, event["trigger"]))
        target = torch.zeros_like(role_logits, dtype=torch.float32)
        for argument in event["arguments"]:
            key = (argument["role"], argument.get("qualifier") or "")
            role_index = model.role_keys.index(key)
            span_index = candidate_index[token_span_bounds(row, argument)]
            target[span_index, role_index] = 1.0
        if target.numel():
            link_losses.append(F.binary_cross_entropy_with_logits(role_logits.float(), target,
                                                                  pos_weight=role_pos_weights))
    link_loss = torch.stack(link_losses).mean() if link_losses else words.new_zeros(())
    total = boundary_loss + proposal_loss + link_loss
    components = {"boundary": float(boundary_loss.detach()),
                  "proposal": float(proposal_loss.detach()),
                  "link": float(link_loss.detach())}
    return total, components


def _candidate_predictions(model: SpanLinkModel, row: Mapping[str, Any], words: torch.Tensor,
                           threshold: float) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    spans = propose_spans(model, words)
    span_reps = model.span_representations(words, spans)
    events = []
    for event in row["events"]:
        trigger_indices = trigger_token_indices(row, event["trigger"])
        logits = model.role_logits(span_reps, words, spans, event["event_type"], trigger_indices)
        probabilities = logits.sigmoid().detach().float().cpu()
        arguments = []
        for candidate_index, (start, end) in enumerate(spans):
            left = row["token_offsets"][start][0]
            right = row["token_offsets"][end][1]
            source_start = row["model_source_token_indices"][start]
            source_end = row["model_source_token_indices"][end] + 1
            for role_index, (role, qualifier) in enumerate(model.role_keys):
                if probabilities[candidate_index, role_index].item() < threshold:
                    continue
                arguments.append({
                    "role": role,
                    "qualifier": qualifier or None,
                    "segments": [{"start": left, "end": right, "text": row["text"][left:right],
                                  "token_start": source_start, "token_end": source_end}],
                })
        events.append({"event_id": event.get("event_id"), "event_type": event["event_type"],
                       "trigger": copy.deepcopy(event["trigger"]), "arguments": arguments})
    prediction = {"message_id": row["message_id"], "split": row["split"],
                  "text": row["text"], "events": events,
                  "diagnostic_span_proposals": [
                      {"start": row["token_offsets"][start][0],
                       "end": row["token_offsets"][end][1],
                       "token_start": row["model_source_token_indices"][start],
                       "token_end": row["model_source_token_indices"][end] + 1}
                      for start, end in spans]}
    return prediction, spans


@torch.inference_mode()
def predict_rows(model: SpanLinkModel, rows: Sequence[Mapping[str, Any]], features: Sequence[Any],
                 device: torch.device, threshold: float = 0.5,
                 batch_size: int = 4) -> tuple[list[dict[str, Any]], dict[str, int]]:
    model.eval()
    output: list[dict[str, Any]] = []
    proposed_gold = gold_groups = 0
    for begin in range(0, len(rows), batch_size):
        row_batch = rows[begin:begin + batch_size]
        feature_batch = features[begin:begin + batch_size]
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16,
                            enabled=device.type == "cuda"):
            word_vectors = model.encode(row_batch, feature_batch, device, encoder_batch_size=4)
        for row, words in zip(row_batch, word_vectors):
            prediction, spans = _candidate_predictions(model, row, words, threshold)
            output.append(prediction)
            proposed = set(spans)
            for event in row["events"]:
                for argument in event["arguments"]:
                    gold_groups += 1
                    proposed_gold += token_span_bounds(row, argument) in proposed
    return output, {"gold_argument_groups": gold_groups,
                    "gold_argument_groups_with_predicted_candidate": proposed_gold,
                    "candidate_span_recall": proposed_gold / gold_groups if gold_groups else 0.0}


def _metric_values(result: Mapping[str, Any]) -> dict[str, float]:
    role_micro = result["argument_records"]["role_exact"]["micro"]["f1"]
    partial_record = result["events"]["record_partial"]["f1"]
    return {"role_exact_f1": float(role_micro), "partial_record_f1": float(partial_record)}


def _segment_geometry(argument: Mapping[str, Any]) -> tuple[int, int] | None:
    segments = argument.get("segments", [])
    if len(segments) != 1:
        return None
    return int(segments[0]["start"]), int(segments[0]["end"])


def _span_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union else 0.0


def create_one_pass_error_sample(dev_rows: Sequence[Mapping[str, Any]], seed: int,
                                 prediction_path: Path, output_dir: Path) -> dict[str, Any]:
    """Write one deterministic, source-bearing DEV sample for private review."""
    predictions = _load_jsonl(prediction_path)
    if len(predictions) != len(dev_rows):
        raise RuntimeError("error-analysis predictions do not cover the fixed DEV rows")
    counts: Counter[str] = Counter()
    cases: dict[str, list[dict[str, Any]]] = {}
    for row, prediction in zip(dev_rows, predictions):
        if row["message_id"] != prediction["message_id"] or row["text"] != prediction["text"]:
            raise RuntimeError("error-analysis prediction order/text does not match fixed DEV")
        predicted_events = prediction["events"]
        proposal_geometries = {(int(span["start"]), int(span["end"]))
                               for span in prediction.get("diagnostic_span_proposals", [])}
        for event_index, gold_event in enumerate(row["events"]):
            predicted_event = predicted_events[event_index]
            gold_args = gold_event["arguments"]
            pred_args = predicted_event["arguments"]
            gold_records = set()
            for argument in gold_args:
                geometry = _segment_geometry(argument)
                if geometry is None:
                    continue
                key = (argument["role"], argument.get("qualifier") or "", *geometry)
                gold_records.add(key)
                exact = any((item["role"], item.get("qualifier") or "", *_segment_geometry(item)) == key
                            for item in pred_args if _segment_geometry(item) is not None)
                if exact:
                    counts["exact_gold_argument"] += 1
                    continue
                if geometry not in proposal_geometries:
                    category = "proposal_miss"
                elif any(_segment_geometry(item) == geometry for item in pred_args):
                    category = "role_or_qualifier_link_error"
                elif any(item["role"] == argument["role"]
                         and (item.get("qualifier") or "") == (argument.get("qualifier") or "")
                         and _segment_geometry(item) is not None
                         and _span_iou(_segment_geometry(item), geometry) >= 0.5 for item in pred_args):
                    category = "boundary_error"
                elif any(item["role"] == argument["role"]
                         and (item.get("qualifier") or "") == (argument.get("qualifier") or "")
                         and _segment_geometry(item) == geometry
                         for other_index, other in enumerate(predicted_events) if other_index != event_index
                         for item in other["arguments"]):
                    category = "wrong_event_link"
                else:
                    category = "candidate_present_link_missed"
                counts[category] += 1
                cases.setdefault(category, []).append({
                    "category": category,
                    "message_id": row["message_id"],
                    "text": row["text"],
                    "event_index": event_index,
                    "event_type": gold_event["event_type"],
                    "trigger": gold_event["trigger"],
                    "gold_argument": argument,
                    "gold_event_arguments": gold_args,
                    "predicted_event_arguments": pred_args,
                    "proposal_count": len(proposal_geometries),
                })
            for argument in pred_args:
                geometry = _segment_geometry(argument)
                if geometry is None:
                    continue
                key = (argument["role"], argument.get("qualifier") or "", *geometry)
                if key in gold_records:
                    continue
                if any(item["role"] == argument["role"]
                       and (item.get("qualifier") or "") == (argument.get("qualifier") or "")
                       and _segment_geometry(item) is not None
                       and _span_iou(_segment_geometry(item), geometry) >= 0.5 for item in gold_args):
                    category = "false_positive_boundary"
                else:
                    category = "false_positive_role_or_link"
                counts[category] += 1
                cases.setdefault(category, []).append({
                    "category": category,
                    "message_id": row["message_id"],
                    "text": row["text"],
                    "event_index": event_index,
                    "event_type": gold_event["event_type"],
                    "trigger": gold_event["trigger"],
                    "predicted_argument": argument,
                    "gold_event_arguments": gold_args,
                    "predicted_event_arguments": pred_args,
                    "proposal_count": len(proposal_geometries),
                })

    sampler = random.Random(20261005)
    sample_rows = []
    for category in sorted(cases):
        selected = list(cases[category])
        sampler.shuffle(selected)
        sample_rows.extend(selected[:20])
    sample_path = (output_dir / "error_analysis_sample_private.jsonl").resolve()
    _write_jsonl(sample_path, sample_rows)
    aggregate = {
        "seed": seed,
        "selection": "median primary score among the three registered seed checkpoints",
        "case_counts": dict(sorted(counts.items())),
        "private_sample_path": sample_path.relative_to(REPO_ROOT).as_posix(),
        "private_sample_rows": len(sample_rows),
        "sampling": "one deterministic sample of up to 20 cases per automatic category, seed 20261005",
        "contains_source_text": False,
    }
    _write_json(output_dir / "error_analysis_source_free_summary.json", aggregate)
    return aggregate


def _runtime_message(row: Mapping[str, Any], tokenizer: Any, model: SpanLinkModel,
                     threshold: float = 0.5) -> float:
    start = time.perf_counter()
    with torch.inference_mode():
        feature = encode_features(row, tokenizer, max_length=512, stride=128)
        words = model.encode([row], [feature], torch.device("cpu"), encoder_batch_size=4)[0]
        _candidate_predictions(model, row, words, threshold)
    return (time.perf_counter() - start) * 1000.0


def runtime_guard(model: SpanLinkModel, tokenizer: Any,
                  dev_rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any],
                  *, repeats: bool) -> dict[str, Any]:
    limits = config["runtime_guard"]
    torch.set_num_threads(int(limits["cpu_threads"]))
    model.to("cpu")
    model.eval()
    params_bytes = sum(parameter.numel() * parameter.element_size() for parameter in model.parameters())
    estimated_float32_weight_bytes = sum(parameter.numel() for parameter in model.parameters()) * 4
    if estimated_float32_weight_bytes > limits["checkpoint_weights_max_bytes_decimal"]:
        raise RuntimeError("initialized model exceeds the preregistered decimal weight-size limit")

    typical_length = 39
    typical = next((row for row in dev_rows if len(row["tokens"]) == typical_length), None)
    longest = max(dev_rows, key=lambda row: len(row["tokens"]))
    if typical is None or len(longest["tokens"]) != 721:
        raise RuntimeError("fixed DEV runtime-guard examples are missing or changed")
    warmups = 3
    typical_repeats = 25 if repeats else 1
    longest_repeats = 5 if repeats else 1
    for _ in range(warmups):
        _runtime_message(typical, tokenizer, model)
    typical_ms = [_runtime_message(typical, tokenizer, model) for _ in range(typical_repeats)]
    for _ in range(warmups):
        _runtime_message(longest, tokenizer, model)
    longest_ms = [_runtime_message(longest, tokenizer, model) for _ in range(longest_repeats)]
    typical_median = float(np.median(typical_ms))
    longest_median = float(np.median(longest_ms))
    actual_weight_bytes = sum(parameter.numel() * parameter.element_size() for parameter in model.parameters())
    limits_pass = (
        typical_median <= limits["median_39_token_dev_message_max_ms"]
        and longest_median <= limits["longest_721_token_dev_message_max_ms"]
        and estimated_float32_weight_bytes <= limits["checkpoint_weights_max_bytes_decimal"]
    )
    return {
        "device": "cpu",
        "cpu_threads": torch.get_num_threads(),
        "typical_native_tokens": typical_length,
        "typical_repetitions": typical_repeats,
        "typical_median_ms": typical_median,
        "longest_native_tokens": len(longest["tokens"]),
        "longest_repetitions": longest_repeats,
        "longest_median_ms": longest_median,
        "float32_weight_size_estimate_bytes_decimal": int(estimated_float32_weight_bytes),
        "initialized_parameter_bytes": int(params_bytes),
        "passed": limits_pass,
    }


def _verify_private_output_ignored(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    relative = path.relative_to(REPO_ROOT).as_posix() + "/span_link_ignore_probe.tmp"
    result = subprocess.run(["git", "check-ignore", "--quiet", relative], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise RuntimeError("private diagnostic output directory is not ignored by Git")


def _cuda_budget_check(start_time: float, prior_gpu_seconds: float,
                       first_attempt_started_utc: str,
                       config: Mapping[str, Any]) -> None:
    budget = config["compute_budget"]
    current_run_seconds = time.monotonic() - start_time
    cumulative_gpu_seconds = prior_gpu_seconds + current_run_seconds
    if cumulative_gpu_seconds >= budget["training_deadline_seconds"]:
        raise BudgetExpired(f"cumulative training cutoff reached ({cumulative_gpu_seconds:.1f}s)")
    first_attempt = datetime.fromisoformat(first_attempt_started_utc)
    elapsed_wall = (datetime.now(timezone.utc) - first_attempt).total_seconds()
    if elapsed_wall >= budget["max_total_gpu_wall_seconds"]:
        raise BudgetExpired(f"one-hour first-attempt wall deadline reached ({elapsed_wall:.1f}s)")
    reserved = torch.cuda.max_memory_reserved()
    if reserved > budget["max_cuda_reserved_bytes"]:
        raise RuntimeError(f"CUDA reserved memory {reserved} exceeds preregistered limit")
    free_bytes, _ = torch.cuda.mem_get_info(0)
    if free_bytes + torch.cuda.memory_reserved() < budget["max_cuda_reserved_bytes"]:
        raise RuntimeError("GPU exclusivity guard detected another process consuming the registered memory budget")


def _fit_seed(seed: int, model: SpanLinkModel, train_rows: Sequence[Mapping[str, Any]],
              dev_rows: Sequence[Mapping[str, Any]], train_features: Sequence[Any],
              dev_features: Sequence[Any], tokenizer: Any, event_types: Sequence[str],
              role_keys: Sequence[tuple[str, str]], output_dir: Path,
              config: Mapping[str, Any], run_start: float, prior_gpu_seconds: float,
              first_attempt_started_utc: str) -> dict[str, Any]:
    training = config["training"]
    device = torch.device("cuda:0")
    model.to(device)
    model.train()
    model.encoder.gradient_checkpointing_enable()
    role_pos_weights = _role_positive_weights(train_rows, role_keys, device)
    encoder_params = list(model.encoder.parameters())
    head_params = [parameter for name, parameter in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = torch.optim.AdamW([
        {"params": encoder_params, "lr": training["encoder_learning_rate"]},
        {"params": head_params, "lr": training["head_learning_rate"]},
    ], weight_decay=training["weight_decay"])

    history: list[dict[str, Any]] = []
    best_f1 = -1.0
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    best_metrics: dict[str, Any] | None = None
    no_improvement = 0
    max_epochs = int(training["max_epochs_per_seed"])
    patience = int(training["early_stopping_patience_epochs"])
    grad_clip = float(training["gradient_clipping_norm"])
    encoder_batch = int(training["batch_size_messages"])

    for epoch in range(1, max_epochs + 1):
        _cuda_budget_check(run_start, prior_gpu_seconds, first_attempt_started_utc, config)
        epoch_started = time.monotonic()
        model.train()
        row_order = list(range(len(train_rows)))
        random.Random(seed + epoch).shuffle(row_order)
        epoch_totals = Counter()
        optimizer.zero_grad(set_to_none=True)
        seen = 0
        for batch_start in range(0, len(row_order), encoder_batch):
            _cuda_budget_check(run_start, prior_gpu_seconds, first_attempt_started_utc, config)
            selected = row_order[batch_start:batch_start + encoder_batch]
            selected = [index for index in selected if train_rows[index]["tokens"]]
            if not selected:
                continue
            batch_rows = [train_rows[index] for index in selected]
            batch_features = [train_features[index] for index in selected]
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                batch_words = model.encode(batch_rows, batch_features, device, encoder_batch_size=4)
                row_losses = []
                batch_components = Counter()
                for local_index, (row_index, row, words) in enumerate(zip(selected, batch_rows, batch_words)):
                    loss, parts = _training_row_loss(model, row, words, seed, epoch, row_index,
                                                     role_pos_weights)
                    if not math.isfinite(float(loss.detach())) or not all(math.isfinite(value) for value in parts.values()):
                        raise FloatingPointError(f"non-finite training loss at registered seed/epoch/train-row index {seed}/{epoch}/{row_index}")
                    row_losses.append(loss)
                    for name, value in parts.items():
                        epoch_totals[name] += value
                        batch_components[name] += value
                loss = torch.stack(row_losses).mean()
            loss.backward()
            gradients_finite = all(parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
                                  for parameter in model.parameters())
            if not gradients_finite:
                raise FloatingPointError(f"non-finite gradient before optimizer step at seed/epoch {seed}/{epoch}")
            if seen == 0:
                print(json.dumps({
                    "stage": "first_batch_finite_before_optimizer_step",
                    "seed": seed,
                    "epoch": epoch,
                    "loss": float(loss.detach()),
                    "mean_boundary_loss": batch_components["boundary"] / max(1, len(row_losses)),
                    "mean_span_proposal_loss": batch_components["proposal"] / max(1, len(row_losses)),
                    "mean_event_link_loss": batch_components["link"] / max(1, len(row_losses)),
                    "gradients_finite": gradients_finite,
                }, sort_keys=True), flush=True)
            clipped_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            if not math.isfinite(float(clipped_norm)):
                raise FloatingPointError(f"non-finite clipped gradient norm before optimizer step at seed/epoch {seed}/{epoch}")
            gradients_finite_after_clip = all(
                parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
                for parameter in model.parameters())
            if not gradients_finite_after_clip:
                raise FloatingPointError(f"non-finite clipped gradient before optimizer step at seed/epoch {seed}/{epoch}")
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            seen += len(selected)
            _cuda_budget_check(run_start, prior_gpu_seconds, first_attempt_started_utc, config)

        dev_predictions, candidate_stats = predict_rows(
            model, dev_rows, dev_features, device, threshold=training["link_threshold"], batch_size=4)
        dev_metrics = score_rows(dev_rows, dev_predictions, split="dev")
        values = _metric_values(dev_metrics)
        epoch_record = {
            "epoch": epoch,
            "messages_seen": seen,
            "mean_boundary_loss": epoch_totals["boundary"] / max(1, seen),
            "mean_span_proposal_loss": epoch_totals["proposal"] / max(1, seen),
            "mean_event_link_loss": epoch_totals["link"] / max(1, seen),
            **values,
            "candidate_span_recall": candidate_stats["candidate_span_recall"],
            "epoch_seconds": time.monotonic() - epoch_started,
            "cuda_max_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        }
        history.append(epoch_record)
        print(json.dumps({"stage": "epoch_complete", "seed": seed, **epoch_record}, sort_keys=True),
              flush=True)
        if values["role_exact_f1"] > best_f1:
            best_f1 = values["role_exact_f1"]
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            best_metrics = dev_metrics
            best_predictions = dev_predictions
            best_candidate_stats = candidate_stats
            no_improvement = 0
        else:
            no_improvement += 1
        _write_json(output_dir / f"seed_{seed}" / "training_history.json", {
            "seed": seed, "epochs": history, "selection_metric": config["training"]["checkpoint_selection"],
            "selected_epoch_so_far": best_epoch,
        })
        if no_improvement >= patience:
            break

    if best_state is None or best_metrics is None:
        raise RuntimeError(f"seed {seed} produced no selectable checkpoint")
    model.load_state_dict(best_state)
    seed_dir = output_dir / f"seed_{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    weights_path = seed_dir / "weights.pt"
    torch.save({name: value.detach().cpu() for name, value in model.state_dict().items()}, weights_path)
    actual_weight_file_bytes = weights_path.stat().st_size
    if actual_weight_file_bytes > config["runtime_guard"]["checkpoint_weights_max_bytes_decimal"]:
        raise RuntimeError(f"seed {seed} checkpoint exceeds the registered file-size limit")
    _write_jsonl(seed_dir / "dev_predictions.jsonl", best_predictions)
    _write_json(seed_dir / "dev_metrics.json", best_metrics)
    _write_json(seed_dir / "candidate_coverage.json", best_candidate_stats)
    return {
        "seed": seed,
        "selected_epoch": best_epoch,
        "epochs_run": len(history),
        **_metric_values(best_metrics),
        "candidate_stats": best_candidate_stats,
        "checkpoint_sha256": _sha256(weights_path),
        "checkpoint_file_bytes": actual_weight_file_bytes,
        "max_epoch_cuda_memory_reserved_bytes": max(
            (item["cuda_max_memory_reserved_bytes"] for item in history), default=0),
        "history": history,
        "checkpoint_path": str(weights_path.relative_to(REPO_ROOT).as_posix()),
    }


@torch.no_grad()
def finite_training_loss_preflight(model: SpanLinkModel,
                                   train_rows: Sequence[Mapping[str, Any]],
                                   train_features: Sequence[Any],
                                   role_keys: Sequence[tuple[str, str]], seed: int,
                                   output_dir: Path, config: Mapping[str, Any],
                                   run_start: float, prior_gpu_seconds: float,
                                   first_attempt_started_utc: str) -> dict[str, Any]:
    """Check every effective TRAIN row's initial losses before any optimizer step."""
    device = torch.device("cuda:0")
    model.to(device)
    model.train()
    role_pos_weights = _role_positive_weights(train_rows, role_keys, device)
    row_order = list(range(len(train_rows)))
    random.Random(seed + 1).shuffle(row_order)
    cpu_rng = torch.get_rng_state()
    cuda_rng = torch.cuda.get_rng_state_all()
    totals = Counter()
    messages_checked = batches_checked = 0
    max_reserved = 0
    try:
        for batch_start in range(0, len(row_order), config["training"]["batch_size_messages"]):
            _cuda_budget_check(run_start, prior_gpu_seconds, first_attempt_started_utc, config)
            indices = row_order[batch_start:batch_start + config["training"]["batch_size_messages"]]
            indices = [index for index in indices if train_rows[index]["tokens"]]
            if not indices:
                continue
            rows = [train_rows[index] for index in indices]
            features = [train_features[index] for index in indices]
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                vectors = model.encode(rows, features, device, encoder_batch_size=4)
                batch_losses = []
                for index, row, words in zip(indices, rows, vectors):
                    loss, parts = _training_row_loss(model, row, words, seed, 1, index, role_pos_weights)
                    if not math.isfinite(float(loss)) or not all(math.isfinite(value) for value in parts.values()):
                        raise FloatingPointError(f"non-finite initial TRAIN loss at train-row index {index}")
                    batch_losses.append(loss)
                    for name, value in parts.items():
                        totals[name] += value
                batch_loss = torch.stack(batch_losses).mean()
            if not math.isfinite(float(batch_loss)):
                raise FloatingPointError("non-finite batch mean in initial TRAIN loss preflight")
            messages_checked += len(indices)
            batches_checked += 1
            max_reserved = max(max_reserved, int(torch.cuda.max_memory_reserved()))
            _cuda_budget_check(run_start, prior_gpu_seconds, first_attempt_started_utc, config)
    finally:
        # Preserve the seeded dropout stream so the subsequent fit begins with
        # the same seed state as a direct registered run.
        torch.set_rng_state(cpu_rng)
        torch.cuda.set_rng_state_all(cuda_rng)
    if messages_checked != sum(bool(row["tokens"]) for row in train_rows):
        raise RuntimeError("initial loss preflight did not visit every effective TRAIN row")
    result = {
        "status": "all_initial_train_losses_finite",
        "effective_train_rows_checked": messages_checked,
        "batches_checked": batches_checked,
        "zero_token_no_supervision_rows_skipped": len(train_rows) - messages_checked,
        "mean_boundary_loss": totals["boundary"] / max(1, messages_checked),
        "mean_span_proposal_loss": totals["proposal"] / max(1, messages_checked),
        "mean_event_link_loss": totals["link"] / max(1, messages_checked),
        "max_cuda_memory_reserved_bytes": max_reserved,
        "optimizer_steps": 0,
    }
    _write_json(output_dir / "initialized_train_loss_preflight.json", result)
    print(json.dumps({"stage": "initial_train_loss_preflight", **result}, sort_keys=True), flush=True)
    return result


def run_experiment() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("experiment_id") != "mailex_native_span_link_oracle_v1":
        raise RuntimeError("unexpected diagnostic configuration")
    commit_info = _verify_preregistration(config)
    train_rows, dev_rows, preprocessing_stats = _validate_fixed_inputs(config)
    _verify_private_output_ignored(PRIVATE_ROOT)
    prior_gpu_seconds, prior_attempts, first_attempt_started_utc = _load_prior_budget_usage()
    elapsed_wall_before_run = (datetime.now(timezone.utc)
                               - datetime.fromisoformat(first_attempt_started_utc)).total_seconds()
    if elapsed_wall_before_run >= config["compute_budget"]["max_total_gpu_wall_seconds"]:
        raise BudgetExpired(f"first-attempt one-hour deadline already expired ({elapsed_wall_before_run:.1f}s)")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    output_dir = PRIVATE_ROOT / "runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)

    event_types, role_keys = inventory(train_rows)
    if len(event_types) != 11 or len(role_keys) != 50:
        raise RuntimeError("TRAIN-derived native label inventory differs from the preregistered compact view")
    encoder_config = str(ENCODER_PATH)
    tokenizer = AutoTokenizer.from_pretrained(encoder_config, local_files_only=True, use_fast=True)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; diagnostic cannot silently switch to CPU training")
    props = torch.cuda.get_device_properties(0)
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    if free_bytes < config["compute_budget"]["max_cuda_reserved_bytes"]:
        raise RuntimeError("exclusive GPU preflight failed: less than the registered 10 GiB is free")
    if props.name != "NVIDIA GeForce RTX 5070":
        raise RuntimeError(f"CUDA device changed from initialized preregistration evidence: {props.name}")
    torch.set_num_threads(int(config["runtime_guard"]["cpu_threads"]))

    # Construct one seed-17 initialization, run the CPU/runtime/size gate, then
    # use this same initialized model for seed 17 if the preflight passes.
    set_seed(config["training"]["seeds"][0])
    model = SpanLinkModel(encoder_config, event_types, role_keys, pretrained=True)
    cpu_guard = runtime_guard(model, tokenizer, dev_rows, config, repeats=True)
    _write_json(output_dir / "initialized_cpu_runtime_guard.json", cpu_guard)
    print(json.dumps({"stage": "initialized_cpu_runtime_guard", **cpu_guard,
                      "cuda_device": props.name, "cuda_free_bytes_before_training": int(free_bytes),
                      "cuda_total_bytes": int(total_bytes)}, sort_keys=True), flush=True)
    if not cpu_guard["passed"]:
        raise RuntimeError("initialized model failed a preregistered CPU latency/weight-size guard")

    train_features = [encode_features(row, tokenizer, max_length=512, stride=128) for row in train_rows]
    dev_features = [encode_features(row, tokenizer, max_length=512, stride=128) for row in dev_rows]
    start_time = time.monotonic()
    _write_json(output_dir / "run_metadata.json", {
        "run_id": run_id,
        "status": "training",
        "commit": commit_info["commit"],
        "preregistration_git_blob": commit_info["config_git_blob"],
        "preregistration_sha256": commit_info["config_sha256"],
        "train_sha256": config["scope"]["training_data"]["sha256"],
        "dev_sha256": config["scope"]["development_data"]["sha256"],
        "seeds": config["training"]["seeds"],
        "cuda_device": props.name,
        "cuda_total_memory_bytes": int(total_bytes),
        "cuda_free_memory_before_training_bytes": int(free_bytes),
        "cpu_pretraining_guard": cpu_guard,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "first_attempt_started_utc": first_attempt_started_utc,
        "elapsed_wall_seconds_since_first_attempt_before_training": elapsed_wall_before_run,
        "prior_gpu_wall_seconds_across_attempts": prior_gpu_seconds,
        "remaining_gpu_wall_seconds_at_attempt_start": max(
            0.0, config["compute_budget"]["max_total_gpu_wall_seconds"] - prior_gpu_seconds),
        "remaining_first_attempt_wall_seconds_before_training": max(
            0.0, config["compute_budget"]["max_total_gpu_wall_seconds"] - elapsed_wall_before_run),
        "train_preprocessing_counts": preprocessing_stats,
        "train_effective_model_rows": preprocessing_stats["train_effective_model_rows"],
        "train_zero_token_rows_skipped_for_no_supervision": preprocessing_stats["train_zero_model_token_rows"],
        "prior_attempts": prior_attempts,
    })
    summaries = []
    run_status = "complete"
    preflight_summary = None
    try:
        preflight_summary = finite_training_loss_preflight(
            model, train_rows, train_features, role_keys, config["training"]["seeds"][0],
            output_dir, config, start_time, prior_gpu_seconds, first_attempt_started_utc)
        initial_metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
        initial_metadata["initial_train_loss_preflight"] = preflight_summary
        _write_json(output_dir / "run_metadata.json", initial_metadata)
        for seed_index, seed in enumerate(config["training"]["seeds"]):
            _cuda_budget_check(start_time, prior_gpu_seconds, first_attempt_started_utc, config)
            free_now, _ = torch.cuda.mem_get_info(0)
            if free_now < config["compute_budget"]["max_cuda_reserved_bytes"]:
                raise RuntimeError("exclusive GPU preflight failed before starting a registered seed")
            if seed_index:
                set_seed(seed)
                model = SpanLinkModel(encoder_config, event_types, role_keys, pretrained=True)
            seed_summary = _fit_seed(seed, model, train_rows, dev_rows, train_features, dev_features,
                                     tokenizer, event_types, role_keys, output_dir, config, start_time,
                                     prior_gpu_seconds, first_attempt_started_utc)
            summaries.append(seed_summary)

            # Release CUDA before applying the registered per-seed CPU guard.
            model.to("cpu")
            torch.cuda.empty_cache()
            trained_guard = runtime_guard(model, tokenizer, dev_rows, config, repeats=True)
            seed_summary["cpu_runtime_guard"] = trained_guard
            if not trained_guard["passed"]:
                run_status = "runtime_guard_failed"
                raise RuntimeError(f"seed {seed} failed the preregistered trained-checkpoint CPU runtime guard")
            _write_json(output_dir / f"seed_{seed}" / "cpu_runtime_guard.json", trained_guard)
            del model
            torch.cuda.empty_cache()
    except BudgetExpired as exc:
        run_status = "incomplete_budget"
        message = str(exc)
    except Exception as exc:
        run_status = run_status if run_status == "runtime_guard_failed" else "failed"
        message = f"{type(exc).__name__}: {exc}"
    except KeyboardInterrupt:
        run_status = "interrupted"
        message = "KeyboardInterrupt received; no additional seed or recipe was started."
    else:
        message = None

    if run_status == "complete":
        if len(summaries) != len(config["training"]["seeds"]):
            run_status = "incomplete_budget"
        else:
            role_scores = [item["role_exact_f1"] for item in summaries]
            partial_scores = [item["partial_record_f1"] for item in summaries]
            success = (float(np.mean(role_scores)) >= 0.50 and float(np.mean(partial_scores)) >= 0.711)
            primary_sd = float(np.std(role_scores, ddof=1))
            secondary_sd = float(np.std(partial_scores, ddof=1))
            median_seed = sorted(summaries, key=lambda item: (item["role_exact_f1"], item["seed"]))[1]
            error_summary = create_one_pass_error_sample(
                dev_rows, median_seed["seed"],
                output_dir / f"seed_{median_seed['seed']}" / "dev_predictions.jsonl", output_dir)
            aggregate = {
                "status": "complete",
                "success_rule_met": success,
                "seed_count": len(summaries),
                "primary_role_exact_f1": {"mean": float(np.mean(role_scores)), "sample_sd": primary_sd,
                                           "per_seed": role_scores},
                "secondary_partial_record_f1": {"mean": float(np.mean(partial_scores)),
                                                 "sample_sd": secondary_sd, "per_seed": partial_scores},
                "seeds": summaries,
                "one_pass_error_analysis": error_summary,
                "current_attempt_wall_seconds": time.monotonic() - start_time,
                "cumulative_gpu_wall_seconds_before_attempt": prior_gpu_seconds,
                "first_attempt_started_utc": first_attempt_started_utc,
                "primary_baseline": 0.461,
                "secondary_baseline": 0.681,
            }
            _write_json(output_dir / "aggregate_results.json", aggregate)
    metadata = {
        "run_id": run_id,
        "status": run_status,
        "commit": commit_info["commit"],
        "preregistration_git_blob": commit_info["config_git_blob"],
        "preregistration_sha256": commit_info["config_sha256"],
        "train_sha256": config["scope"]["training_data"]["sha256"],
        "dev_sha256": config["scope"]["development_data"]["sha256"],
        "seeds_completed": [item["seed"] for item in summaries],
        "seed_summaries": summaries,
        "current_attempt_wall_seconds": time.monotonic() - start_time if "start_time" in locals() else 0.0,
        "elapsed_gpu_wall_seconds": prior_gpu_seconds + (time.monotonic() - start_time)
        if "start_time" in locals() else prior_gpu_seconds,
        "prior_gpu_wall_seconds_across_attempts": prior_gpu_seconds,
        "first_attempt_started_utc": first_attempt_started_utc,
        "elapsed_wall_seconds_since_first_attempt": max(
            0.0, (datetime.now(timezone.utc)
                  - datetime.fromisoformat(first_attempt_started_utc)).total_seconds()),
        "remaining_wall_seconds_from_first_attempt": max(
            0.0, 3600 - (datetime.now(timezone.utc)
                         - datetime.fromisoformat(first_attempt_started_utc)).total_seconds()),
        "train_preprocessing_counts": preprocessing_stats,
        "train_effective_model_rows": preprocessing_stats["train_effective_model_rows"],
        "train_zero_token_rows_skipped_for_no_supervision": preprocessing_stats["train_zero_model_token_rows"],
        "initial_train_loss_preflight": preflight_summary,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    if message:
        metadata["terminal_message"] = message
    _write_json(output_dir / "run_metadata.json", metadata)
    run_seconds = max(0.0, time.monotonic() - start_time) if "start_time" in locals() else 0.0
    budget_ledger = _save_budget_ledger(prior_attempts, run_id, run_status, run_seconds,
                                        first_attempt_started_utc)
    metadata["cumulative_gpu_wall_seconds_after_attempt"] = budget_ledger["total_spent_seconds"]
    metadata["remaining_gpu_wall_seconds_after_attempt"] = budget_ledger["remaining_gpu_seconds"]
    _write_json(output_dir / "run_metadata.json", metadata)
    result = {"status": run_status, "run_id": run_id,
              "output_dir": output_dir.relative_to(REPO_ROOT).as_posix(),
              "seeds_completed": [item["seed"] for item in summaries],
              "current_attempt_wall_seconds": metadata["current_attempt_wall_seconds"],
              "cumulative_gpu_wall_seconds": budget_ledger["total_spent_seconds"],
              "remaining_gpu_wall_seconds": budget_ledger["remaining_gpu_seconds"],
              "remaining_first_attempt_wall_seconds": budget_ledger["remaining_wall_seconds"]}
    if message:
        result["terminal_message"] = message
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


"""Private GLiNER2.5 MailEx benchmark runner.

Examples (from the repository root):
  ai/.venv/Scripts/python.exe ai/scripts/run_mailex_gliner.py preflight
  ai/.venv/Scripts/python.exe ai/scripts/run_mailex_gliner.py zero-shot --threshold 0.5
  ai/.venv/Scripts/python.exe ai/scripts/run_mailex_gliner.py train

Model/runtime packages and corpus-derived outputs are private under ai/data.
This runner never opens TEST and has no network/API inference path.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "src"))

from mailex_extraction.gliner_backend import (  # noqa: E402
    AI_ROOT,
    CHECKPOINT_DIR,
    CHECKPOINT_REVISION,
    DATA_DIR,
    DEV_SHA256,
    PRIVATE_ROOT,
    TRAIN_SHA256,
    MailExOntology,
    OffsetSchemaTransformer,
    build_schema,
    build_training_record,
    derive_ontology,
    iter_jsonl,
    load_extractor,
    prediction_row,
    private_package_versions,
    sha256_file,
    verify_sha256,
)


MAX_ENCODER_POSITIONS = 512
MAX_SCHEMA_SUBWORDS = 320
MAX_WORDS_PER_CHUNK = 240
CHUNK_OVERLAP_WORDS = 24


def _internal_schema(model: Any, ontology: MailExOntology, event_types: Sequence[str]):
    return build_schema(model, ontology, event_types)


def _schema_subwords(model: Any, schema: Any) -> int:
    record = model.processor.transform_and_format("", copy.deepcopy(schema.build()))
    return len(record.input_ids)


def _pack_event_types(model: Any, ontology: MailExOntology):
    """Greedily group TRAIN event schemas under a measured prompt budget."""
    groups: list[tuple[tuple[str, ...], dict[str, Any], int]] = []
    pending: list[str] = []
    for event_type in ontology.event_types:
        candidate = [*pending, event_type]
        schema = _internal_schema(model, ontology, candidate)
        prompt_length = _schema_subwords(model, schema)
        if prompt_length <= MAX_SCHEMA_SUBWORDS:
            pending = candidate
            continue
        if not pending:
            raise ValueError(
                f"single event schema {event_type!r} needs {prompt_length} subwords, "
                f"over budget {MAX_SCHEMA_SUBWORDS}"
            )
        prior = _internal_schema(model, ontology, pending)
        groups.append((tuple(pending), prior, _schema_subwords(model, prior)))
        pending = [event_type]
        schema = _internal_schema(model, ontology, pending)
        prompt_length = _schema_subwords(model, schema)
        if prompt_length > MAX_SCHEMA_SUBWORDS:
            raise ValueError(f"single event schema {event_type!r} exceeds prompt budget")
    if pending:
        schema = _internal_schema(model, ontology, pending)
        groups.append((tuple(pending), schema, _schema_subwords(model, schema)))
    return groups


def _input_length(model: Any, text: str, schema: Any) -> int:
    record = model.processor.transform_and_format(text, copy.deepcopy(schema.build()))
    return len(record.input_ids)


def _text_chunks(model: Any, text: str, schema: Any):
    """Window a long body by GLiNER word boundaries, enforcing 512 wordpieces.

    The model's documented max_len is a word-token setting. This code measures
    the final encoded sequence, including schema prompt and special tokens, so
    DeBERTa's 512-position limit is respected without silent truncation.
    Returned windows use original body character boundaries; overlapping
    windows are later deduplicated by exact source offsets.
    """
    if not text.strip():
        return [], []
    if _input_length(model, text, schema) <= MAX_ENCODER_POSITIONS:
        return ([(0, len(text))] if text else []), [_input_length(model, text, schema)]
    words = list(model.processor.word_splitter(text, lower=True))
    if not words:
        return [], []
    chunks = []
    chunk_lengths = []
    begin = 0
    while begin < len(words):
        end = min(len(words), begin + MAX_WORDS_PER_CHUNK)
        while end > begin:
            char_start = 0 if begin == 0 else words[begin][1]
            char_end = len(text) if end == len(words) else words[end - 1][2]
            encoded_len = _input_length(model, text[char_start:char_end], schema)
            if encoded_len <= MAX_ENCODER_POSITIONS:
                break
            shrink = max(1, math.ceil((end - begin) / 8))
            end -= shrink
        if end <= begin:
            raise ValueError("one GLiNER word plus the schema exceeds encoder positions")
        char_start = 0 if begin == 0 else words[begin][1]
        char_end = len(text) if end == len(words) else words[end - 1][2]
        chunks.append((char_start, char_end))
        encoded_len = _input_length(model, text[char_start:char_end], schema)
        if encoded_len > MAX_ENCODER_POSITIONS:
            raise RuntimeError("chunk passed length check but exceeds encoder positions")
        # Count the actual encoded subword length for audit metadata.
        chunk_lengths.append(encoded_len)
        if end == len(words):
            break
        begin = max(begin + 1, end - CHUNK_OVERLAP_WORDS)
    return chunks, chunk_lengths


def _merge_chunk_outputs(
    grouped_outputs: Sequence[tuple[int, Mapping[str, Any]]],
    event_types: Sequence[str],
    text: str,
) -> dict[str, Any]:
    """Shift offsets; remove only identical full records repeated in overlap.

    Records sharing an anchor but carrying different arguments remain separate.
    Overlap windows are never unioned by trigger, which could mix two native
    event instances that happen to use the same trigger span.
    """
    merged: dict[str, list[dict[str, Any]]] = {event_type: [] for event_type in event_types}
    seen: dict[str, set[tuple[Any, ...]]] = {event_type: set() for event_type in event_types}

    def _span_key(span: Any) -> tuple[Any, ...]:
        if not isinstance(span, Mapping):
            return ("raw", str(span))
        return (span.get("start"), span.get("end"), str(span.get("text", "")))

    def _record_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
        trigger_value = record.get("trigger")
        if isinstance(trigger_value, Mapping):
            trigger_key = _span_key(trigger_value)
        else:
            trigger_key = ("raw", str(trigger_value))
        arguments = []
        for name in sorted(key for key in record if key != "trigger"):
            value = record[name]
            spans = value if isinstance(value, list) else [value]
            arguments.append((name, tuple(sorted((_span_key(item) for item in spans), key=repr))))
        return (trigger_key, tuple(arguments))

    for offset, output in grouped_outputs:
        for event_type in event_types:
            records = output.get(event_type, []) or []
            if not isinstance(records, list):
                records = [records]
            for source_record in records:
                if not isinstance(source_record, Mapping):
                    continue
                record = copy.deepcopy(dict(source_record))
                trigger = record.get("trigger")
                if isinstance(trigger, Mapping):
                    trigger = dict(trigger)
                    if isinstance(trigger.get("start"), int):
                        trigger["start"] += offset
                    if isinstance(trigger.get("end"), int):
                        trigger["end"] += offset
                    record["trigger"] = trigger

                for field_name, value in list(record.items()):
                    if field_name == "trigger":
                        continue
                    if isinstance(value, list):
                        shifted = []
                        for span in value:
                            if isinstance(span, Mapping):
                                span = dict(span)
                                if isinstance(span.get("start"), int):
                                    span["start"] += offset
                                if isinstance(span.get("end"), int):
                                    span["end"] += offset
                            shifted.append(span)
                        record[field_name] = shifted
                key = _record_key(record)
                if key not in seen[event_type]:
                    merged[event_type].append(record)
                    seen[event_type].add(key)
    return merged


def _infer_one_group(model: Any, text: str, schema: Any,
                     event_types: Sequence[str], threshold: float):
    chunks, chunk_lengths = _text_chunks(model, text, schema)
    if not chunks:
        return {}, 0, 0, []
    chunk_outputs = []
    for start, end in chunks:
        chunk = text[start:end]
        raw = model.extract(
            chunk,
            schema,
            threshold=threshold,
            include_spans=True,
            include_confidence=True,
        )
        chunk_outputs.append((start, raw))
    return (
        _merge_chunk_outputs(chunk_outputs, event_types, text),
        len(chunks),
        max(chunk_lengths, default=0),
        chunks,
    )


def run_zero_shot(threshold: float) -> Path:
    train_path = DATA_DIR / "train_fyp_safe.jsonl"
    dev_path = DATA_DIR / "dev_fyp_safe.jsonl"
    train_hash = verify_sha256(train_path, TRAIN_SHA256)
    dev_hash = verify_sha256(dev_path, DEV_SHA256)
    ontology = derive_ontology(train_path, verify_fingerprint=False)
    model = load_extractor(device="cuda" if _cuda_available() else "cpu")
    packs = _pack_event_types(model, ontology)
    dev_rows = list(iter_jsonl(dev_path))
    combined_outputs: list[dict[str, Any]] = [dict() for _ in dev_rows]
    diagnostics = Counter()
    for event_types, schema, schema_subwords in packs:
        for index, row in enumerate(dev_rows):
            output, chunk_count, max_encoded, chunks = _infer_one_group(
                model, str(row.get("text", "")), schema, event_types, threshold
            )
            combined_outputs[index].update(output)
            diagnostics["schema_group_runs"] += 1
            diagnostics["schema_subwords_total"] += schema_subwords
            diagnostics["windows_total"] += chunk_count
            diagnostics["messages_with_multiple_windows"] += int(chunk_count > 1)
            diagnostics["max_encoder_sequence_subwords"] = max(
                diagnostics["max_encoder_sequence_subwords"], max_encoded
            )
            words = list(model.processor.word_splitter(str(row.get("text", "")), lower=True))
            diagnostics["body_word_tokens_total"] += len(words)
            covered = {
                i for i, (_, word_start, word_end) in enumerate(words)
                if any(start <= word_start and word_end <= end
                       for start, end in chunks)
            }
            diagnostics["body_word_tokens_covered"] += len(covered)
            if (index + 1) % 50 == 0:
                print(f"schema_group={'|'.join(event_types)} rows={index + 1}/{len(dev_rows)}", flush=True)

    output_dir = DATA_DIR / "predictions"
    output_dir.mkdir(parents=True, exist_ok=True)
    # Preserve the first run, which used upstream's synthetic-period collator.
    # This is the corrected source-byte-exact no-append pass.
    output_path = output_dir / "zero_shot_gliner2_5_small_native_text_dev.jsonl"
    counts = Counter()
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for source, prediction in zip(dev_rows, combined_outputs):
            row, row_counts = prediction_row(source, prediction, ontology)
            counts.update(row_counts)
            counts["messages"] += 1
            counts["events_by_type"] += len(row["events"])
            for event in row["events"]:
                counts[f"event_type:{event['event_type']}"] += 1
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "model_id": "fastino/gliner2.5-small-v1",
        "model_revision": CHECKPOINT_REVISION,
        "checkpoint_dir": str(CHECKPOINT_DIR),
        "train_sha256": train_hash,
        "dev_sha256": dev_hash,
        "threshold": threshold,
        "inference_device": "cuda" if _cuda_available() else "cpu",
        "batch_size": 1,
        "cpu_threads": 4,
        "text_collator": "source_bytes_exact_no_append",
        "encoder_max_positions": MAX_ENCODER_POSITIONS,
        "schema_prompt_budget_subwords": MAX_SCHEMA_SUBWORDS,
        "schema_groups": [
            {"event_types": list(types), "schema_subwords": n}
            for types, _, n in packs
        ],
        "diagnostics": dict(diagnostics),
        "prediction_diagnostics": dict(counts),
        "package_versions": private_package_versions(),
        "prediction_sha256": sha256_file(output_path),
    }
    (output_dir / "zero_shot_gliner2_5_small_dev.metadata.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "prediction_path": str(output_path),
        "prediction_sha256": report["prediction_sha256"],
        "messages": counts["messages"],
        "events": counts["events_by_type"],
        "grounded_trigger_segments": counts["grounded_trigger_segments"],
        "grounded_argument_segments": counts["grounded_argument_segments"],
        "ungrounded_segments": counts["ungrounded_segments"],
        "schema_groups": len(packs),
        "windows_total": diagnostics["windows_total"],
        "device": report["inference_device"],
    }, indent=2))
    return output_path


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def run_preflight() -> dict[str, Any]:
    verify_sha256(CHECKPOINT_DIR / "model.safetensors", "4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b")
    model = load_extractor(device="cpu")
    param_count = sum(parameter.numel() for parameter in model.parameters())
    smoke_text = "I sent it to you. I sent it to you."
    schema = (
        model.create_schema()
        .structure("Smoke_Action", mode="natural", anchor="trigger", occurrence_policy="all")
        .field("trigger", dtype="str", cardinality="required_one")
        .field("speaker", dtype="list", cardinality="zero_or_more")
    )
    result = model.extract(
        smoke_text, schema, threshold=0.1,
        include_spans=True, include_confidence=True,
    )
    grounded = []
    for record in result.get("Smoke_Action", []) or []:
        for field in ("trigger", "speaker"):
            values = record.get(field)
            values = values if isinstance(values, list) else [values]
            for value in values:
                if isinstance(value, Mapping) and isinstance(value.get("start"), int) and isinstance(value.get("end"), int):
                    assert smoke_text[value["start"]:value["end"]] == value.get("text")
                    grounded.append(field)
    preflight_dir = PRIVATE_ROOT / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    cuda_result_count = None
    with tempfile.TemporaryDirectory(prefix="roundtrip_", dir=preflight_dir) as temp_dir:
        model.save_pretrained(temp_dir)
        reloaded = load_extractor(device="cpu", checkpoint=Path(temp_dir))
        reloaded.extract(
            smoke_text, schema, threshold=0.1,
            include_spans=True, include_confidence=True,
        )
        if _cuda_available():
            reloaded.to("cuda")
            cuda_result = reloaded.extract(
                smoke_text, schema, threshold=0.1,
                include_spans=True, include_confidence=True,
            )
            cuda_result_count = sum(len(value or []) for value in cuda_result.values() if isinstance(value, list))
    result_info = {
        "model_id": "fastino/gliner2.5-small-v1",
        "model_revision": CHECKPOINT_REVISION,
        "checkpoint_weight_sha256": "4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b",
        "parameter_count": param_count,
        "architecture": getattr(model, "architecture", None),
        "cpu_roundtrip": True,
        "cuda_available": _cuda_available(),
        "cuda_smoke_records": cuda_result_count,
        "synthetic_grounded_fields": len(grounded),
        "package_versions": private_package_versions(),
    }
    print(json.dumps(result_info, indent=2))
    return result_info


def run_train() -> None:
    """Fine-tune with exact TRAIN offsets; called only after DEV review."""
    AutoExtractor = __import__("mailex_extraction.gliner_backend", fromlist=["_gliner_imports"])._gliner_imports()
    import torch
    from gliner2.processor import SchemaTransformer
    from gliner2.training.trainer import ExtractorTrainer, TrainingConfig

    train_path = DATA_DIR / "train_fyp_safe.jsonl"
    dev_path = DATA_DIR / "dev_fyp_safe.jsonl"
    verify_sha256(train_path, TRAIN_SHA256)
    verify_sha256(dev_path, DEV_SHA256)
    ontology = derive_ontology(train_path, verify_fingerprint=False)
    torch.set_num_threads(4)
    model = AutoExtractor.from_pretrained(str(CHECKPOINT_DIR), local_files_only=True)
    base_processor = model.processor
    offset_cls = OffsetSchemaTransformer.make(SchemaTransformer)
    processor = offset_cls(
        tokenizer=base_processor.tokenizer,
        sampling_config=base_processor.sampling_config,
        token_pooling=base_processor.token_pooling,
        word_splitter=base_processor.word_splitter,
    )
    model.processor = processor
    packed_schemas = _pack_event_types(model, ontology)
    train_rows = list(iter_jsonl(train_path))
    dev_rows = list(iter_jsonl(dev_path))
    train_data, train_audit = _build_training_examples(train_rows, model, ontology, packed_schemas)
    eval_data, dev_audit = _build_training_examples(
        dev_rows, model, ontology, packed_schemas, allow_unseen_train_labels=True
    )
    output_dir = PRIVATE_ROOT / "checkpoints" / "mailex_gliner2_5_small_finetuned_seed42_batch4"
    config = TrainingConfig(
        output_dir=str(output_dir),
        experiment_name="mailex_gliner2_5_small_seed42_batch4",
        num_epochs=3,
        batch_size=4,
        eval_batch_size=4,
        encoder_lr=1e-5,
        task_lr=2e-5,
        eval_strategy="epoch",
        early_stopping=True,
        early_stopping_patience=2,
        num_workers=0,
        pin_memory=True,
        seed=42,
        deterministic=False,
        validate_data=False,
        # Do not let the processor trim exact-target offsets by word count.
        # The window builder and strict collator enforce the 512 wordpiece cap.
        max_len=None,
        report_to_wandb=False,
        save_best=True,
        save_total_limit=2,
        strict_training=True,
        fp16=False,
        bf16=bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported()),
    )
    trainer = ExtractorTrainer(model, config, processor=processor)
    history = trainer.train(train_data=train_data, eval_data=eval_data)
    (output_dir / "mailex_training_summary.json").write_text(
        json.dumps({
            "train_sha256": TRAIN_SHA256,
            "dev_sha256": DEV_SHA256,
            "seed": 42,
            "config": config.to_dict(),
            "history": history,
            "train_rows": len(train_data),
            "dev_rows": len(eval_data),
            "source_train_rows": len(train_rows),
            "source_dev_rows": len(dev_rows),
            "schema_groups": [
                {"event_types": list(types), "schema_subwords": n}
                for types, _, n in packed_schemas
            ],
            "train_window_audit": train_audit,
            "dev_window_audit": dev_audit,
            "package_versions": private_package_versions(),
        }, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output_dir": str(output_dir), "epochs": config.num_epochs,
                      "train_rows": len(train_data), "dev_rows": len(eval_data),
                      "train_window_audit": train_audit,
                      "dev_window_audit": dev_audit}, indent=2))


def _build_training_examples(
    source_rows: Sequence[Mapping[str, Any]],
    model: Any,
    ontology: MailExOntology,
    packed_schemas: Sequence[tuple[tuple[str, ...], Any, int]],
    *,
    allow_unseen_train_labels: bool = False,
):
    """Create one exact-offset example per source window and inference schema pack.

    Gold events are assigned to the first window that contains their anchor and
    every argument segment. An event that cannot fit intact in one encoder
    window is counted and omitted rather than trained with missing arguments as
    false negatives. DEV labels absent from TRAIN are also counted and omitted
    as whole records; the model ontology never gains labels from DEV. All packed
    event groups remain present in every window as positive or negative record
    supervision.
    """
    examples = []
    audit = Counter()
    for source_row in source_rows:
        text = str(source_row.get("text", ""))
        for event_types, schema_obj, _schema_len in packed_schemas:
            eligible = [
                event for event in source_row.get("events", [])
                if event.get("event_type") in event_types
            ]
            audit["gold_events_in_packed_groups"] += len(eligible)
            audit["gold_argument_segments_in_packed_groups"] += sum(
                len(argument.get("segments", []))
                for event in eligible
                for argument in event.get("arguments", [])
            )
            if not text.strip():
                audit["empty_text_group_examples_skipped"] += 1
                audit["dropped_events_empty_text"] += len(eligible)
                audit["dropped_argument_segments_empty_text"] += sum(
                    len(argument.get("segments", []))
                    for event in eligible
                    for argument in event.get("arguments", [])
                )
                continue
            chunks, _ = _text_chunks(model, text, schema_obj)
            if not chunks:
                raise ValueError("nonempty MailEx body produced no encoder windows")
            chunk_events: list[list[dict[str, Any]]] = [[] for _ in chunks]
            for event in eligible:
                event_bindings = ontology.fields_by_event[event["event_type"]]
                binding_keys = {(binding.role, binding.qualifier) for binding in event_bindings}
                missing_pairs = {
                    (argument.get("role"), argument.get("qualifier"))
                    for argument in event.get("arguments", [])
                    if (argument.get("role"), argument.get("qualifier")) not in binding_keys
                }
                argument_segment_count = sum(
                    len(argument.get("segments", []))
                    for argument in event.get("arguments", [])
                )
                if missing_pairs:
                    if not allow_unseen_train_labels:
                        raise ValueError(
                            f"TRAIN event has labels missing from its TRAIN ontology: {sorted(missing_pairs)!r}"
                        )
                    audit["dropped_events_unseen_train_label"] += 1
                    audit["dropped_argument_segments_unseen_train_label"] += argument_segment_count
                    continue
                trigger_segments = event.get("trigger", {}).get("segments", [])
                if not trigger_segments:
                    audit["dropped_events_missing_trigger"] += 1
                    audit["dropped_argument_segments_missing_trigger"] += argument_segment_count
                    continue
                pivot = min(trigger_segments, key=lambda segment: (int(segment["start"]), int(segment["end"])))
                all_spans = [(int(pivot["start"]), int(pivot["end"]))]
                for argument in event.get("arguments", []):
                    all_spans.extend(
                        (int(segment["start"]), int(segment["end"]))
                        for segment in argument.get("segments", [])
                    )
                candidate_indices = [
                    index for index, (start, end) in enumerate(chunks)
                    if start <= int(pivot["start"]) and int(pivot["end"]) <= end
                ]
                chosen = next((index for index in candidate_indices
                               if all(chunks[index][0] <= start and end <= chunks[index][1]
                                      for start, end in all_spans)), None)
                if chosen is None:
                    audit["dropped_events_not_intact_in_any_window"] += 1
                    audit["dropped_argument_segments_not_intact_in_any_window"] += argument_segment_count
                    continue
                window_start, window_end = chunks[chosen]
                local = copy.deepcopy(dict(event))
                local["trigger"] = {
                    **dict(event.get("trigger", {})),
                    # The natural head needs one contiguous pivot; other source
                    # segments remain in the untouched native gold dataset.
                    "segments": [{
                        **dict(pivot),
                        "start": int(pivot["start"]) - window_start,
                        "end": int(pivot["end"]) - window_start,
                        "text": text[int(pivot["start"]):int(pivot["end"])],
                    }],
                }
                for argument in local.get("arguments", []):
                    argument["segments"] = [{
                        **dict(segment),
                        "start": int(segment["start"]) - window_start,
                        "end": int(segment["end"]) - window_start,
                        "text": text[int(segment["start"]):int(segment["end"])],
                    } for segment in argument.get("segments", [])]
                    audit["represented_argument_segments"] += len(argument["segments"])
                chunk_events[chosen].append(local)
                audit["represented_events"] += 1
            for window_index, (start, end) in enumerate(chunks):
                chunk_row = {
                    **dict(source_row),
                    "text": text[start:end],
                    "events": chunk_events[window_index],
                }
                examples.append(build_training_record(
                    chunk_row, ontology, model, event_types
                ))
                audit["windows"] += 1
                audit["examples"] += 1
                audit["events_per_example_total"] += len(chunk_events[window_index])
                audit["max_events_per_example"] = max(
                    audit["max_events_per_example"], len(chunk_events[window_index])
                )
                if len(chunk_events[window_index]) > 32:
                    audit["examples_over_32_gold_events"] += 1
    return examples, dict(audit)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "zero-shot", "train"))
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    if args.command == "preflight":
        run_preflight()
    elif args.command == "zero-shot":
        run_zero_shot(args.threshold)
    else:
        run_train()


if __name__ == "__main__":
    main()

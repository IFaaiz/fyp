"""Native-record GLiNER inference with a one-time committed TEST gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "src"))

import torch
from mailex_extraction.gliner_backend import (
    CHECKPOINT_REVISION,
    DATA_DIR,
    DEV_SHA256,
    GLINER2_SOURCE_COMMIT,
    TRAIN_SHA256,
    FieldBinding,
    MailExOntology,
    iter_jsonl,
    load_extractor,
    prediction_row,
    private_package_versions,
    sha256_file,
    verify_sha256,
)
from mailex_extraction.metrics import (
    reserve_test_run,
    score_rows,
    validate_committed_test_lock,
)
from run_mailex_gliner import (
    _infer_one_group,
    _pack_event_types,
)


def _load_frozen_ontology(path: Path) -> MailExOntology:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("source_split") != "train":
        raise ValueError("GLiNER schema must be the frozen TRAIN-only ontology")
    if data.get("train_sha256") != TRAIN_SHA256:
        raise ValueError("GLiNER schema was not built from the authorized TRAIN fingerprint")
    if data.get("model_revision") != CHECKPOINT_REVISION:
        raise ValueError("GLiNER schema checkpoint revision differs from this backend")
    if data.get("gliner2_source_commit") != GLINER2_SOURCE_COMMIT:
        raise ValueError("GLiNER schema source commit differs from this backend")
    from mailex_extraction.gliner_backend import VENDOR_ROOT, private_package_versions
    vendor = str(VENDOR_ROOT)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    expected_runtime = data.get("runtime_versions")
    if not isinstance(expected_runtime, dict):
        raise ValueError("GLiNER schema does not freeze runtime package versions")
    actual_runtime = private_package_versions()
    for name in ("gliner2", "torch", "transformers"):
        if actual_runtime.get(name) != expected_runtime.get(name):
            raise ValueError(f"GLiNER runtime {name} differs from the frozen schema")
    fields = {
        event_type: tuple(
            FieldBinding(str(item["field_name"]), str(item["role"]), item.get("qualifier"))
            for item in items
        )
        for event_type, items in data["fields_by_event"].items()
    }
    events = tuple(str(event_type) for event_type in data["event_types"])
    if set(fields) != set(events):
        raise ValueError("GLiNER schema event types and field map differ")
    return MailExOntology(events, fields)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite predictions: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _require_private_output(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(DATA_DIR.resolve())
    except ValueError as exc:
        raise ValueError("MailEx predictions and metrics must stay under the private experiment directory") from exc
    return resolved


def _run(args: argparse.Namespace) -> None:
    lock_info = None
    finalist = None
    threshold = args.threshold
    output_path = Path(args.output).resolve()
    metrics_path = (
        Path(args.metrics).resolve()
        if args.metrics
        else output_path.with_suffix(".metrics.json")
    )
    if args.split == "test":
        if args.metrics:
            raise ValueError("TEST predictions are saved for the separate locked evaluator")
    else:
        _require_private_output(output_path)
        _require_private_output(metrics_path)
        if output_path.exists() or metrics_path.exists():
            raise FileExistsError("DEV/TRAIN output exists; choose fresh prediction and metrics paths")

    if args.split == "test":
        if not args.selection_lock or not args.finalist_id:
            raise ValueError("TEST requires --selection-lock and --finalist-id")
        # This validates the committed manifest and frozen artifact hashes,
        # without parsing source rows.
        lock_info = validate_committed_test_lock(args.selection_lock)
        lock = lock_info["manifest"]
        root = lock_info["repository_root"]
        matches = [item for item in lock["finalists"] if item["run_id"] == args.finalist_id]
        if len(matches) != 1 or args.finalist_id != "gliner_small_selected":
            raise ValueError("TEST requires the unique GLiNER small finalist")
        finalist = matches[0]
        if Path(args.input).resolve() != (root / lock["gold_path"]).resolve():
            raise ValueError("TEST input differs from the locked gold path")
        expected_output = (root / finalist["expected_output_path"]).resolve()
        if Path(args.output).resolve() != expected_output:
            raise ValueError("TEST output differs from the frozen finalist output path")
        frozen_threshold = float(finalist["thresholds"]["record"])
        if threshold is not None and float(threshold) != frozen_threshold:
            raise ValueError("TEST record threshold differs from the frozen finalist threshold")
        threshold = frozen_threshold
        if args.device != finalist.get("inference_device"):
            raise ValueError("TEST device differs from the frozen finalist device")
        if not 0 < frozen_threshold <= 1:
            raise ValueError("frozen GLiNER threshold must be in (0, 1]")
        if args.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("the frozen GLiNER finalist requires an available CUDA device")
        checkpoint_relative = finalist["config"].get("checkpoint_directory")
        if not checkpoint_relative:
            raise ValueError("GLiNER finalist does not freeze a checkpoint directory")
        checkpoint_path = (root / checkpoint_relative).resolve()
        if Path(args.checkpoint).resolve() != checkpoint_path:
            raise ValueError("TEST checkpoint directory differs from the frozen finalist")
        schema_map = finalist.get("schema", {})
        if len(schema_map) != 1:
            raise ValueError("GLiNER finalist must freeze exactly one ontology file")
        schema_relative = next(iter(schema_map))
        if Path(args.schema).resolve() != (root / schema_relative).resolve():
            raise ValueError("TEST schema differs from the frozen TRAIN ontology")
        schema_path = Path(args.schema).resolve()
        if not schema_path.is_file():
            raise FileNotFoundError(schema_path)
        ontology = _load_frozen_ontology(schema_path)
        weight_paths = [
            (root / relative).resolve()
            for relative in finalist["model_weights"]
        ]
        if not weight_paths or any(checkpoint_path not in path.parents for path in weight_paths):
            raise ValueError("frozen GLiNER weights do not belong to the selected checkpoint")
        preprocessor = finalist["preprocessing"]
        if not any(relative.endswith("mailex_extraction_environment.json")
                   for relative in preprocessor):
            raise ValueError("GLiNER runtime environment is not frozen in the finalist")
        required_preprocessing = {checkpoint_relative + "/config.json"}
        token_names = (
            "tokenizer.json", "tokenizer_config.json", "vocab.txt",
            "special_tokens_map.json", "added_tokens.json", "spm.model",
            "sentencepiece.bpe.model",
        )
        for name in token_names:
            if (checkpoint_path / name).is_file():
                required_preprocessing.add((Path(checkpoint_relative) / name).as_posix())
        encoder_config = checkpoint_path / "encoder_config"
        if encoder_config.is_dir():
            for local_path in encoder_config.rglob("*.json"):
                required_preprocessing.add(local_path.relative_to(root).as_posix())
        if not required_preprocessing.issubset(set(preprocessor)):
            missing = sorted(required_preprocessing - set(preprocessor))
            raise ValueError(f"GLiNER checkpoint preprocessing is not fully frozen: {missing}")
        # Reserve once before opening/parsing the TEST JSONL. The reservation
        # is deliberately consumed even if inference later fails.
        reserve_test_run(args.selection_lock, args.finalist_id)
        if sha256_file(Path(args.input)) != lock["gold_sha256"]:
            raise ValueError("TEST input digest differs from the committed lock")
        if expected_output.exists():
            raise FileExistsError("frozen TEST output already exists")
    else:
        if args.selection_lock or args.finalist_id:
            raise ValueError("selection-lock options are only valid for TEST")
        if args.split == "dev":
            expected = DATA_DIR / "dev_fyp_safe.jsonl"
            if Path(args.input).resolve() != expected.resolve():
                raise ValueError("DEV input must be the approved FYP-safe view")
            verify_sha256(expected, DEV_SHA256)
        elif args.split == "train":
            expected = DATA_DIR / "train_fyp_safe.jsonl"
            if Path(args.input).resolve() != expected.resolve():
                raise ValueError("TRAIN input must be the approved FYP-safe view")
            verify_sha256(expected, TRAIN_SHA256)
        if threshold is None:
            threshold = 0.5
    if not 0 < float(threshold) <= 1:
        raise ValueError("record threshold must be in (0, 1]")

    if args.split != "test":
        schema_path = Path(args.schema).resolve()
        if not schema_path.is_file():
            raise FileNotFoundError(schema_path)
        ontology = _load_frozen_ontology(schema_path)

    started = time.perf_counter()
    model = load_extractor(device=args.device, checkpoint=Path(args.checkpoint))
    model.eval()
    load_seconds = time.perf_counter() - started
    packed = _pack_event_types(model, ontology)

    # This is the first point that reads source rows. TEST reservation and all
    # lock checks above have already succeeded.
    source_rows = list(iter_jsonl(Path(args.input)))
    if any(row.get("split") != args.split for row in source_rows):
        raise ValueError("Input contains a row from a different split")
    combined = [dict() for _ in source_rows]
    diagnostics: dict[str, Any] = {
        "schema_groups": [], "windows": 0, "max_encoder_sequence_subwords": 0,
        "schema_group_runs_with_multiple_windows": 0,
    }
    started = time.perf_counter()
    for event_types, schema, schema_subwords in packed:
        diagnostics["schema_groups"].append({
            "event_types": list(event_types), "schema_subwords": schema_subwords,
        })
        for index, source in enumerate(source_rows):
            output, window_count, max_encoded, _chunks = _infer_one_group(
                model, str(source.get("text", "")), schema, event_types, float(threshold)
            )
            combined[index].update(output)
            diagnostics["windows"] += window_count
            diagnostics["max_encoder_sequence_subwords"] = max(
                diagnostics["max_encoder_sequence_subwords"], max_encoded
            )
            diagnostics["schema_group_runs_with_multiple_windows"] += int(window_count > 1)
        print(f"completed schema group {'|'.join(event_types)}", flush=True)
    if str(args.device).startswith("cuda"):
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started

    predictions = []
    from collections import Counter
    aggregate = Counter()
    for source, output in zip(source_rows, combined):
        row, counts = prediction_row(source, output, ontology)
        predictions.append(row)
        aggregate.update(counts)
    _write_jsonl(output_path, predictions)

    if args.split == "test":
        print(json.dumps({
            "status": "test_predictions_saved",
            "run_id": args.finalist_id,
            "prediction_sha256": sha256_file(Path(args.output)),
            "messages": len(predictions),
            "inference_seconds": inference_seconds,
            "load_seconds": load_seconds,
            "diagnostics": diagnostics,
        }, indent=2), flush=True)
        return

    metrics = score_rows(source_rows, predictions, split=args.split)
    metrics["run"] = {
        "architecture": "GLiNER2.5 Small natural trigger-anchored native records",
        "threshold": threshold,
        "checkpoint": str(Path(args.checkpoint).resolve()),
        "checkpoint_revision": CHECKPOINT_REVISION,
        "input_sha256": sha256_file(Path(args.input)),
        "schema_sha256": sha256_file(schema_path),
        "prediction_sha256": sha256_file(Path(args.output)),
        "inference_device": args.device,
        "package_versions": private_package_versions(),
        "diagnostics": diagnostics,
        "prediction_diagnostics": dict(aggregate),
        "inference_seconds": inference_seconds,
        "load_seconds": load_seconds,
    }
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({
        "split": args.split,
        "messages": len(predictions),
        "events": aggregate.get("records", 0),
        "grounded_trigger_segments": aggregate.get("grounded_trigger_segments", 0),
        "grounded_argument_segments": aggregate.get("grounded_argument_segments", 0),
        "role_exact_f1": metrics["argument_records"]["role_exact"]["micro"]["f1"],
        "record_f1": metrics["events"]["record_partial"]["f1"],
        "prediction_sha256": sha256_file(Path(args.output)),
        "metrics_path": str(metrics_path),
        "inference_seconds": inference_seconds,
        "load_seconds": load_seconds,
    }, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metrics")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--split", choices=("train", "dev", "test"), default="dev")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--selection-lock")
    parser.add_argument("--finalist-id")
    args = parser.parse_args()
    _run(args)


if __name__ == "__main__":
    main()

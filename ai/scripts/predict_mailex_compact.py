"""Source-grounded compact inference; TEST requires a committed selection lock."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import torch
from mailex_extraction.compact import (AutoTokenizer, CompactExtractor, canonical_rows,
    encode_features, predict, read_rows, sha256, write_jsonl)
from mailex_extraction.metrics import reserve_test_run, score_rows, validate_committed_test_lock


def load_checkpoint(path, device):
    path = Path(path)
    config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    torch.set_num_threads(config.get("torch_cpu_threads", 4))
    tokenizer = AutoTokenizer.from_pretrained(config["encoder"], local_files_only=True, use_fast=True)
    model = CompactExtractor(config["encoder"], config["event_types"], config["role_keys"],
                             loss_family=config.get("loss_family", "weighted_multilabel_bce"), pretrained=False).to(device)
    model.load_state_dict(torch.load(path / "model.pt", map_location=device, weights_only=True))
    model.eval()
    return model, tokenizer, config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--split", choices=["train", "dev", "test"], default="dev")
    parser.add_argument("--mode", choices=["end_to_end", "gold_type", "gold_type_trigger"], default="end_to_end")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--selection-lock")
    parser.add_argument("--finalist-id")
    args = parser.parse_args()
    lock = None
    if args.split == "test":
        if not args.selection_lock or not args.finalist_id or args.mode != "end_to_end":
            parser.error("TEST requires --selection-lock, --finalist-id and end_to_end mode")
        info = validate_committed_test_lock(args.selection_lock)
        lock = info["manifest"]
        root = info["repository_root"]
        if Path(args.input).resolve() != (root / lock["gold_path"]).resolve() or sha256(args.input) != lock["gold_sha256"]:
            parser.error("TEST input differs from the frozen gold file")
        finalist = next(item for item in lock["finalists"] if item["run_id"] == args.finalist_id)
        if Path(args.output).resolve() != (root / finalist["expected_output_path"]).resolve():
            parser.error("TEST output differs from the frozen finalist path")
        threshold = finalist["thresholds"]["bio"]
        if args.threshold is not None and args.threshold != threshold:
            parser.error("TEST threshold differs from the frozen threshold")
        if (Path(args.checkpoint) / "model.pt").resolve() not in {(root / path).resolve() for path in finalist["model_weights"]}:
            parser.error("TEST checkpoint is not a frozen finalist weight file")
        reserve_test_run(args.selection_lock, args.finalist_id)
    else:
        threshold = args.threshold
    started = time.perf_counter()
    model, tokenizer, config = load_checkpoint(args.checkpoint, args.device)
    load_seconds = time.perf_counter() - started
    threshold = config["threshold"] if threshold is None else threshold
    rows = canonical_rows(read_rows(args.input))
    if any(row["split"] != args.split for row in rows):
        raise ValueError("Input contains a different split")
    features = [encode_features(row, tokenizer, config["max_length"], config["stride"]) for row in rows]
    started = time.perf_counter()
    predictions = predict(model, rows, features, args.device, threshold, args.mode)
    if args.device.startswith("cuda"):
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    write_jsonl(args.output, predictions)
    if args.split == "test":
        # The separately gated evaluator records the one-time receipt. It can
        # score these saved predictions without any second model inference.
        print(json.dumps({"status": "test_predictions_saved", "prediction_sha256": sha256(args.output),
                          "inference_seconds": inference_seconds, "load_seconds": load_seconds}), flush=True)
        return
    metrics = score_rows(rows, predictions, split=args.split)
    metrics["run"] = {"mode": args.mode, "threshold": threshold, "inference_seconds": inference_seconds,
                      "load_seconds": load_seconds, "weights_sha256": sha256(Path(args.checkpoint) / "model.pt"),
                      "input_sha256": sha256(args.input), "prediction_sha256": sha256(args.output)}
    Path(args.metrics).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({"arg_role_f1": metrics["argument_records"]["role_exact"]["micro"]["f1"],
                      "arg_overlap_f1": metrics["argument_records"]["span_overlap"]["f1"],
                      "record_f1": metrics["events"]["record_partial"]["f1"],
                      "predicted_events": metrics["events"]["predicted"], "inference_seconds": inference_seconds}), flush=True)


if __name__ == "__main__":
    main()

"""Small, explicit DEV-only confidence grid for a fixed compact checkpoint."""
import argparse
import json
from pathlib import Path

from predict_mailex_compact import load_checkpoint
from mailex_extraction.compact import canonical_rows, encode_features, predict, read_rows, sha256, write_jsonl
from mailex_extraction.metrics import score_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    rows = canonical_rows(read_rows(args.input))
    if any(r["split"] != "dev" for r in rows):
        raise ValueError("Calibration must use DEV only")
    model, tokenizer, config = load_checkpoint(args.checkpoint, args.device)
    features = [encode_features(r, tokenizer, config["max_length"], config["stride"]) for r in rows]
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    result = {"dev_sha256": sha256(args.input), "weight_sha256": sha256(Path(args.checkpoint)/"model.pt"),
              "grid_declared_before_execution": [0.3, 0.5, 0.7, 0.9],
              "selection_metric": "argument_records.role_exact.micro.f1", "runs": []}
    for threshold in result["grid_declared_before_execution"]:
        predictions = predict(model, rows, features, args.device, threshold)
        path = out/f"dev_threshold_{threshold}.jsonl"
        write_jsonl(path, predictions)
        metrics = score_rows(rows, predictions, split="dev")
        (out/f"dev_threshold_{threshold}.metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        item = {"threshold": threshold, "argument_role_exact_f1": metrics["argument_records"]["role_exact"]["micro"]["f1"],
                "event_record_partial_f1": metrics["events"]["record_partial"]["f1"],
                "event_record_exact_f1": metrics["events"]["record_exact"]["f1"],
                "prediction_sha256": sha256(path)}
        result["runs"].append(item)
        print(json.dumps(item), flush=True)
    result["selected_threshold"] = max(result["runs"], key=lambda x: (x["argument_role_exact_f1"], -x["threshold"]))["threshold"]
    (out/"calibration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

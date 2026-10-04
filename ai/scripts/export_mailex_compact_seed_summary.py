"""Export source-free DEV metrics for the three full-safe compact seeds.

The exporter reads only trainer config, selected-epoch, checkpoint-hash and
DEV calibration JSON metadata. It never opens JSONL rows or TEST artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any


AI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = AI_ROOT / "reports" / "mailex_extraction_results" / "compact_seed_robustness_2e5.json"
DEFAULT_RUNS = {
    17: "compact_categorical_lr2e5_seed17",
    23: "compact_categorical_lr2e5_seed23_resumed_20261004",
    41: "compact_categorical_lr2e5_seed41_resumed_20261004",
}
EXPECTED_GRID = [0.3, 0.5, 0.7, 0.9]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path.name}")
    return value


def _load_run(seed: int, run_dir: Path) -> dict[str, Any]:
    config = _read_json(run_dir / "config.json")
    recipe = {"seed": seed, "lr": 2e-5, "head_lr": 1e-3,
              "batch_size": 8, "epochs": 8, "patience": 2,
              "loss_family": "categorical_bio"}
    if any(config.get(key) != value for key, value in recipe.items()):
        raise ValueError(f"seed or shared recipe mismatch in {run_dir.name}")
    selected = _read_json(run_dir / "selected_epoch.json")
    calibration = _read_json(run_dir / "calibration" / "calibration.json")
    weight_hash_path = run_dir / "checkpoint_sha256.txt"
    if not weight_hash_path.is_file():
        raise FileNotFoundError(weight_hash_path)
    checkpoint_hash = weight_hash_path.read_text(encoding="ascii").strip()
    weight_digest = hashlib.sha256()
    with (run_dir / "model.pt").open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            weight_digest.update(chunk)
    if weight_digest.hexdigest() != checkpoint_hash:
        raise ValueError(f"actual checkpoint bytes changed in {run_dir.name}")
    if calibration.get("grid_declared_before_execution") != EXPECTED_GRID:
        raise ValueError(f"unexpected threshold grid in {run_dir.name}")
    if calibration.get("selection_metric") != "argument_records.role_exact.micro.f1":
        raise ValueError(f"unexpected DEV selection metric in {run_dir.name}")
    if calibration.get("weight_sha256") != checkpoint_hash:
        raise ValueError(f"checkpoint hash does not match calibration in {run_dir.name}")
    if calibration.get("dev_sha256") != config.get("dev_sha256"):
        raise ValueError(f"DEV input hash mismatch in {run_dir.name}")
    runs = calibration.get("runs", [])
    if [row.get("threshold") for row in runs] != EXPECTED_GRID:
        raise ValueError(f"incomplete or reordered threshold results in {run_dir.name}")
    best = max(runs, key=lambda row: (row["argument_role_exact_f1"], -row["threshold"]))
    if calibration.get("selected_threshold") != best["threshold"]:
        raise ValueError(f"selected threshold does not match the declared criterion in {run_dir.name}")
    return {
        "seed": seed,
        "best_epoch_at_threshold_0_5": int(selected["epoch"]),
        "fixed_0_5_role_exact_f1": float(selected["score"]),
        "selected_threshold": float(best["threshold"]),
        "role_exact_f1": float(best["argument_role_exact_f1"]),
        "event_record_partial_f1": float(best["event_record_partial_f1"]),
        "event_record_exact_f1": float(best["event_record_exact_f1"]),
        "selected_prediction_sha256": str(best["prediction_sha256"]),
        "checkpoint_sha256": checkpoint_hash,
        "train_input_sha256": str(config["train_sha256"]),
        "dev_input_sha256": str(config["dev_sha256"]),
        "threshold_grid": [
            {
                "threshold": float(item["threshold"]),
                "role_exact_f1": float(item["argument_role_exact_f1"]),
                "event_record_partial_f1": float(item["event_record_partial_f1"]),
                "event_record_exact_f1": float(item["event_record_exact_f1"]),
                "prediction_sha256": str(item["prediction_sha256"]),
            }
            for item in runs
        ],
    }


def export_summary(ai_root: Path = AI_ROOT, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    experiment_root = ai_root / "data" / "experiments" / "mailex_extraction_v1"
    seeds = [_load_run(seed, experiment_root / run_name) for seed, run_name in DEFAULT_RUNS.items()]
    hashes = {(row["train_input_sha256"], row["dev_input_sha256"]) for row in seeds}
    if len(hashes) != 1:
        raise ValueError("the three seeds did not use identical TRAIN/DEV inputs")
    summary = {}
    for field in ("role_exact_f1", "event_record_partial_f1", "event_record_exact_f1"):
        values = [row[field] for row in seeds]
        summary[field] = {
            "mean": statistics.mean(values),
            "sample_standard_deviation": statistics.stdev(values),
            "n": len(values),
        }
    result = {
        "schema": "mailex_compact_seed_robustness_v1",
        "test_accessed": False,
        "split_variant": "mailex_native_fyp_safe_v1",
        "architecture": "shared DistilBERT categorical BIO with event-conditioned arguments",
        "selection_protocol": {
            "checkpoint_epoch": "DEV role-exact micro F1 at threshold 0.5, patience 2",
            "inference_threshold": "highest DEV role-exact micro F1 over the declared grid; lower threshold wins ties",
            "grid": EXPECTED_GRID,
        },
        "shared_train_input_sha256": seeds[0]["train_input_sha256"],
        "shared_dev_input_sha256": seeds[0]["dev_input_sha256"],
        "seeds": seeds,
        "summary": summary,
        "privacy": "Aggregate metrics and hashes only; no message text or source identifiers.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai-root", type=Path, default=AI_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = export_summary(args.ai_root, args.output)
    print(json.dumps({"output": str(args.output), "summary": result["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

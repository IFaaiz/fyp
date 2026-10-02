"""Attach the callable Nx9 prediction contract to selected lexical bundles."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from joblib import dump, load

AI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI))

from src.models.optimization_benchmark import LABEL_ORDER, load_partition, score_probabilities  # noqa: E402
from src.models.optimization_lexical import predict  # noqa: E402


def main():
    report_path = AI / "reports/optimization_lexical.json"
    model_dir = AI / "data/models/optimization/lexical"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dev = load_partition("dev")
    expected = [row["labels"] for row in dev]
    for run_id in report["selection"]["final_test_candidate_ids"]:
        entry = next(run for run in report["runs"] if run["run_id"] == run_id)
        path = model_dir / f"{run_id}.joblib"
        model = load(path)
        thresholds = entry["thresholds"]
        mode = entry["task"]
        model.thresholds = thresholds
        model.decode_mode = mode
        model.fallback = False
        model.metadata.update({
            "run_id": run_id,
            "decode_mode": mode,
            "fallback": False,
            "thresholds": thresholds,
            "threshold_method": entry["threshold_method"],
            "metric_provenance": "AI-SILVER DIAGNOSTIC PERFORMANCE",
        })
        dump(model, path, compress=3)

        start = time.perf_counter()
        probabilities = None
        for _ in range(3):
            probabilities = predict(model, dev)
        latency = (time.perf_counter() - start) * 1000.0 / (3 * max(len(dev), 1))
        if probabilities.shape != (len(dev), len(LABEL_ORDER)):
            raise ValueError(f"{run_id}: expected {len(dev)}x9 probabilities, got {probabilities.shape}")
        if not np.isfinite(probabilities).all() or np.any(probabilities < 0) or np.any(probabilities > 1):
            raise ValueError(f"{run_id}: invalid probability values")
        measured = score_probabilities(
            expected, probabilities,
            thresholds=[thresholds[label] for label in LABEL_ORDER], mode=mode,
        )
        for metric in ("macro_f1", "micro_f1"):
            if abs(float(measured[metric]) - float(entry["dev"][metric])) > 1e-10:
                raise ValueError(f"{run_id}: loaded model {metric} differs from registry")
        entry["model_artifact"] = str(path.relative_to(AI))
        entry["model_size_bytes"] = path.stat().st_size
        entry["inference_time_ms_per_record"] = float(latency)
        entry["predictor_contract"] = {
            "callable": "src.models.optimization_lexical.predict(bundle, rows)",
            "output": "finite Nx9 probabilities in benchmark LABEL_ORDER",
            "decode_mode": mode,
            "fallback": False,
            "thresholds_in_bundle_metadata": True,
        }
        print(json.dumps({
            "run_id": run_id,
            "macro_f1": measured["macro_f1"],
            "micro_f1": measured["micro_f1"],
            "model_size_bytes": entry["model_size_bytes"],
            "decode_mode": mode,
        }))

    report["predictor_contract"] = {
        "callable": "src.models.optimization_lexical.predict(bundle, rows)",
        "probability_columns": list(LABEL_ORDER),
        "selected_model_bundles_validated_on": "DEV only",
        "test_data_loaded": False,
    }
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

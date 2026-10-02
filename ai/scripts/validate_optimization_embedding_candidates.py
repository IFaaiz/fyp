"""CPU smoke-test exported embedding bundles against their DEV artifacts."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Keep this API smoke check off the shared GPU. Set before torch is imported.
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import numpy as np

AI_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = AI_DIR.parent
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.models.optimization_benchmark import load_partition
from src.models.optimization_embeddings import predict

REPORT_PATH = AI_DIR / "reports/optimization_embeddings.json"
OUTPUT_PATH = AI_DIR / "data/experiments/optimization_20261002/embeddings/embedding_candidate_validation.json"


def main() -> int:
    registry = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    candidates = registry["final_candidates"]
    dev_rows = load_partition("dev")
    train_rows = load_partition("train")
    outcomes = []
    for candidate in candidates:
        started = time.perf_counter()
        probabilities = predict(candidate["model_path"], dev_rows)
        elapsed = time.perf_counter() - started
        expected = np.load(candidate["dev_probabilities_path"], allow_pickle=False)
        oof = np.load(candidate["train_oof_probabilities_path"], allow_pickle=False)
        if probabilities.shape != (len(dev_rows), 9):
            raise ValueError(f"predict() returned invalid shape for {candidate['run_id']}: {probabilities.shape}")
        if oof.shape != (len(train_rows), 9):
            raise ValueError(f"TRAIN OOF array has invalid shape for {candidate['run_id']}: {oof.shape}")
        if not np.isfinite(probabilities).all() or not np.isfinite(oof).all():
            raise ValueError(f"non-finite probabilities for {candidate['run_id']}")
        max_abs_diff = float(np.max(np.abs(probabilities - expected)))
        outcome = {
            "run_id": candidate["run_id"],
            "predict_contract_shape": list(probabilities.shape),
            "train_oof_shape": list(oof.shape),
            "max_abs_difference_from_saved_dev_probabilities": max_abs_diff,
            "cpu_smoke_seconds": elapsed,
            "api_contract_ok": max_abs_diff <= 5e-4,
            "test_used_or_read": False,
        }
        if not outcome["api_contract_ok"]:
            raise ValueError(f"saved bundle/API probabilities differ for {candidate['run_id']}: {max_abs_diff}")
        outcomes.append(outcome)
        print(f"{candidate['run_id']}: {probabilities.shape}, max_abs_diff={max_abs_diff:.2g}, {elapsed:.2f}s", flush=True)
    payload = {
        "scope": "CPU inference bundle smoke test; only canonical TRAIN/DEV rows were loaded",
        "candidate_count": len(outcomes),
        "candidates": outcomes,
        "test_used_or_read": False,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Export the DEV-selected per-label specialist combination in frozen row order."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.models.optimization_benchmark import benchmark_hash, load_partition

EXP = AI_DIR / "data/experiments/optimization_20261002/embeddings"
REGISTRY = AI_DIR / "reports/optimization_embeddings_frozen.json"


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    specialist = registry["per_label_specialists"]
    expected_dev_ids = [row["email_id"] for row in load_partition("dev")]
    expected_train_ids = [row["email_id"] for row in load_partition("train")]
    dev = json.loads((EXP / "dev_probabilities.json").read_text(encoding="utf-8"))
    oof = json.loads((EXP / "train_oof_probabilities.json").read_text(encoding="utf-8"))
    if dev["row_ids"] != expected_dev_ids or oof["row_ids"] != expected_train_ids:
        raise ValueError("probability rows differ from the frozen benchmark order")
    selected = {row["label_index"]: row["selected_run_id"] for row in specialist["selected_heads"]}
    dev_probs = [[dev["probabilities"][selected[i]][row][i] for i in range(9)] for row in range(len(dev["row_ids"]))]
    oof_probs = [[oof["probabilities"][selected[i]][row][i] for i in range(9)] for row in range(len(oof["row_ids"]))]
    thresholds = specialist["oof_thresholds"]
    dev_path = EXP / "dev_probabilities_specialists.json"
    oof_path = EXP / "train_oof_probabilities_specialists.json"
    write_json(dev_path, {
        "row_ids": dev["row_ids"],
        "run_ids": ["per_label_specialists"],
        "probabilities": {"per_label_specialists": dev_probs},
        "thresholds_train_oof_only": {"per_label_specialists": thresholds},
        "prediction_modes": {"per_label_specialists": "flat"},
        "selected_heads": specialist["selected_heads"],
        "selection_partition": "DEV; candidate selection is not a held-out estimate",
        "benchmark_sha256": benchmark_hash(),
    })
    write_json(oof_path, {
        "row_ids": oof["row_ids"],
        "run_ids": ["per_label_specialists"],
        "probabilities": {"per_label_specialists": oof_probs},
        "scope": "each column comes from the selected model's grouped TRAIN OOF probabilities; thresholds are TRAIN OOF only",
        "selected_heads": specialist["selected_heads"],
        "benchmark_sha256": benchmark_hash(),
    })
    print(json.dumps({"dev_path": str(dev_path.resolve()), "train_oof_path": str(oof_path.resolve()), "thresholds": thresholds}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

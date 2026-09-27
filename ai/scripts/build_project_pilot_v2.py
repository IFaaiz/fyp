"""Build the second, non-overlapping, unlabelled Enron AI pilot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))
from scripts.build_project_pilot import POOL_PATH, build_project_pilot_seed
from src.datasets.schemas import read_jsonl

CONFIG_PATH = AI_DIR / "annotation" / "project_pilot_50_v2_ids.json"
FIRST_CONFIG_PATH = AI_DIR / "annotation" / "project_pilot_50_ids.json"
FIRST_SEED_PATH = AI_DIR / "data" / "annotated" / "human" / "project_pilot_50" / "annotation_seed_50.jsonl"
OUTPUT_DIR = AI_DIR / "data" / "annotated" / "ai" / "project_pilot_50_v2"


def build_second_pilot_seed() -> Path:
    current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    first = json.loads(FIRST_CONFIG_PATH.read_text(encoding="utf-8"))
    selected = current.get("selected_email_ids")
    if not isinstance(selected, list):
        raise ValueError("second pilot config has no selected_email_ids list")
    overlap = set(selected) & set(first["selected_email_ids"])
    if overlap:
        raise ValueError(f"second pilot overlaps first pilot: {sorted(overlap)[:3]}")
    first_rows = list(read_jsonl(FIRST_SEED_PATH))
    first_threads = {row["thread_id"] for row in first_rows}
    first_bodies = {" ".join(row["current_message"].split()) for row in first_rows}
    for row in read_jsonl(POOL_PATH):
        if row.get("email_id") not in selected:
            continue
        if row["thread_id"] in first_threads:
            raise ValueError(f"second pilot overlaps a first-pilot thread: {row['thread_id']}")
        if " ".join(row["current_message"].split()) in first_bodies:
            raise ValueError(f"second pilot repeats a first-pilot message body: {row['email_id']}")
    return build_project_pilot_seed(config_path=CONFIG_PATH, output_dir=OUTPUT_DIR)


if __name__ == "__main__":
    print(build_second_pilot_seed())

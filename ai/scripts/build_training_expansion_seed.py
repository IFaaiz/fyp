"""Rebuild or verify the immutable 100-email AI-only expansion seed."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.datasets.schemas import read_jsonl, write_jsonl
from src.datasets.validation import validate_record

CONFIG = AI_DIR / "annotation/training_expansion_100_ids.json"
POOL = AI_DIR / "data/interim/enron_candidates.jsonl"
HUMAN_MANIFEST = AI_DIR / "data/annotated/human/label_studio_seed/manifest.json"
OLD_CONFIGS = [
    AI_DIR / "annotation/project_pilot_50_ids.json",
    AI_DIR / "annotation/project_pilot_50_v2_ids.json",
    HUMAN_MANIFEST,
]
OUTPUT = AI_DIR / "data/annotated/ai/training_expansion_100/annotation_seed_100.jsonl"


def build(config_path: Path = CONFIG, pool_path: Path = POOL, output_path: Path = OUTPUT) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ids = config.get("selected_email_ids")
    if not isinstance(ids, list) or len(ids) != 100 or len(set(ids)) != 100:
        raise ValueError("selection must contain 100 unique email IDs")
    if set(config.get("strata", {})) != set(ids):
        raise ValueError("strata must cover exactly the selected IDs")
    prior_ids = set()
    for path in OLD_CONFIGS:
        prior_ids.update(json.loads(path.read_text(encoding="utf-8"))["selected_email_ids"])
    if set(ids) & prior_ids:
        raise ValueError("new seed overlaps a prior pilot or human assignment")

    pool = list(read_jsonl(pool_path))
    by_id = {row["email_id"]: row for row in pool}
    if len(by_id) != len(pool):
        raise ValueError("candidate pool has duplicate IDs")
    missing = set(ids) - set(by_id)
    if missing:
        raise ValueError(f"selected IDs missing from pool: {sorted(missing)[:3]}")
    prior_threads = {by_id[email_id]["thread_id"] for email_id in prior_ids if email_id in by_id}
    prior_bodies = {
        " ".join(by_id[email_id]["current_message"].split()).casefold()
        for email_id in prior_ids if email_id in by_id
    }
    thread_counts = Counter(row["thread_id"] for row in pool)
    selected = [by_id[email_id] for email_id in ids]
    bodies = []
    for row in selected:
        email_id = row["email_id"]
        if row["thread_id"] in prior_threads or thread_counts[row["thread_id"]] != 1:
            raise ValueError(f"selected thread overlaps or is not singleton: {email_id}")
        body = " ".join(row["current_message"].split()).casefold()
        if body in prior_bodies:
            raise ValueError(f"selected message repeats prior body: {email_id}")
        bodies.append(body)
        if row["source_dataset"] != "enron" or row["labels"] or row["spans"]:
            raise ValueError(f"selected record is not an unlabelled Enron source: {email_id}")
        if row["annotation"]["status"] != "unlabelled" or validate_record(row):
            raise ValueError(f"selected record is invalid or already annotated: {email_id}")
    if len(set(bodies)) != len(bodies):
        raise ValueError("selected seed has duplicate normalized bodies")

    if output_path.exists():
        existing = list(read_jsonl(output_path))
        if existing != selected:
            raise ValueError("existing seed differs from selected source rows; refusing overwrite")
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, selected)
    return output_path


if __name__ == "__main__":
    print(build())

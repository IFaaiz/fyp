"""Build the separately screened, unlabelled 50-email Enron pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AI_DIR.parent
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.datasets.schemas import read_jsonl
from src.datasets.validation import validate_record

CONFIG_PATH = AI_DIR / "annotation" / "project_pilot_50_ids.json"
POOL_PATH = AI_DIR / "data" / "interim" / "enron_candidates.jsonl"
OLD_MANIFEST_PATH = AI_DIR / "data" / "annotated" / "human" / "label_studio_seed" / "manifest.json"
OUTPUT_DIR = AI_DIR / "data" / "annotated" / "human" / "project_pilot_50"
SEED_NAME = "annotation_seed_50.jsonl"
PILOT_SIZE = 50


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def build_project_pilot_seed(
    *, config_path: Path = CONFIG_PATH, pool_path: Path = POOL_PATH,
    output_dir: Path = OUTPUT_DIR, old_manifest_path: Path = OLD_MANIFEST_PATH,
) -> Path:
    """Create once, then verify in place; never replace a used pilot seed."""
    config = _read_json(config_path)
    ids = config.get("selected_email_ids")
    if (not isinstance(ids, list) or len(ids) != PILOT_SIZE
            or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != PILOT_SIZE):
        raise ValueError(f"pilot config must list {PILOT_SIZE} unique email IDs")
    old_manifest = _read_json(old_manifest_path)
    overlap = set(ids) & set(old_manifest.get("selected_email_ids", []))
    if overlap:
        raise ValueError(f"pilot IDs overlap the old 250-email seed: {sorted(overlap)[:3]}")

    seed_path = output_dir / SEED_NAME
    manifest_path = output_dir / "manifest.json"
    if seed_path.exists() or manifest_path.exists():
        if not seed_path.exists() or not manifest_path.exists():
            raise ValueError("pilot seed and manifest must either both exist or both be absent")
        manifest = _read_json(manifest_path)
        if (manifest.get("selected_email_count") != PILOT_SIZE
                or manifest.get("selected_email_ids") != ids
                or manifest.get("source_dataset") != "enron"):
            raise ValueError("existing pilot manifest differs from the curated ID list")
        existing = list(read_jsonl(seed_path))
        if [row.get("email_id") for row in existing] != ids:
            raise ValueError("existing pilot seed order differs from its manifest")
        if any(validate_record(row) for row in existing):
            raise ValueError("existing pilot seed contains invalid canonical records")
        return seed_path

    if (output_dir / "reviewers").exists() and any((output_dir / "reviewers").iterdir()):
        raise ValueError("reviewer output exists without its pilot seed; refusing to rebuild")

    selected: dict[str, dict[str, Any]] = {}
    pool_thread_counts: Counter[str] = Counter()
    wanted = set(ids)
    digest = hashlib.sha256()
    with pool_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    for row in read_jsonl(pool_path):
        pool_thread_counts[str(row.get("thread_id"))] += 1
        email_id = row.get("email_id")
        if email_id not in wanted:
            continue
        if email_id in selected:
            raise ValueError(f"duplicate selected email ID in candidate pool: {email_id}")
        if row.get("source_dataset") != "enron":
            raise ValueError(f"selected record {email_id} is not Enron")
        if row.get("labels") != [] or row.get("spans") != []:
            raise ValueError(f"selected record {email_id} has prefilled annotation")
        if row.get("annotation", {}).get("status") != "unlabelled":
            raise ValueError(f"selected record {email_id} is already annotated")
        if not str(row.get("current_message", "")).strip():
            raise ValueError(f"selected record {email_id} has empty current_message")
        errors = validate_record(row)
        if errors:
            raise ValueError(f"selected record {email_id} is invalid: {'; '.join(errors)}")
        selected[email_id] = row
    missing = wanted - set(selected)
    if missing:
        raise ValueError(f"curated IDs missing from candidate pool: {sorted(missing)[:5]}")
    rows = [selected[email_id] for email_id in ids]
    selected_thread_counts = Counter(str(row["thread_id"]) for row in rows)
    partial_threads = [
        thread_id for thread_id, count in selected_thread_counts.items()
        if count != pool_thread_counts[thread_id]
    ]
    if partial_threads:
        raise ValueError(f"pilot selection splits candidate-pool threads: {partial_threads[:3]}")
    manifest = {
        "source_dataset": "enron",
        "display_name": "Project email pilot",
        "input_pool": str(pool_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "input_pool_sha256": digest.hexdigest(),
        "selection_config": str(config_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "selected_email_count": PILOT_SIZE,
        "selected_email_ids": ids,
        "screening_status": "provisional_relevance_screen_only",
        "labels_prepopulated": False,
        "is_gold": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(seed_path, "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows))
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return seed_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(build_project_pilot_seed())


if __name__ == "__main__":
    main()

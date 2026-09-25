"""Create identical, blank A/B Label Studio assignments from a real Enron pool."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.annotation.label_studio import records_to_tasks, select_enron_seed_records, source_thread_key
from src.annotation.label_studio_config import make_label_studio_config
from src.datasets.schemas import read_jsonl


def find_gold_records(extra_paths: list[Path], candidate_rows: list[dict]) -> list[dict]:
    paths = set(extra_paths)
    human_dir = AI_DIR / "data" / "annotated" / "human"
    if human_dir.exists():
        paths.update(human_dir.rglob("*.jsonl"))
    gold = [row for row in candidate_rows if row.get("annotation", {}).get("status") == "gold"]
    for path in sorted(paths):
        if path.exists():
            gold.extend(row for row in read_jsonl(path)
                        if row.get("annotation", {}).get("status") == "gold")
    return gold


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=AI_DIR / "data" / "interim" / "enron_candidates.jsonl")
    parser.add_argument("--output-dir", type=Path, default=AI_DIR / "data" / "annotated" / "human" / "label_studio_seed")
    parser.add_argument("--count", type=int, default=250, help="real Enron records, from 200 to 300 inclusive")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--gold-records", type=Path, action="append", default=[], help="extra canonical JSONL to scan for gold threads")
    parser.add_argument("--metadata-sidecar", type=Path, help="candidate metadata JSONL; defaults to the matching .metadata.jsonl when present")
    args = parser.parse_args()
    rows = list(read_jsonl(args.input))
    gold_rows = find_gold_records(args.gold_records, rows)
    sidecar = args.metadata_sidecar or args.input.with_name(args.input.stem + ".metadata.jsonl")
    if args.metadata_sidecar and not sidecar.is_file():
        raise FileNotFoundError(f"metadata sidecar does not exist: {sidecar}")
    metadata_rows = list(read_jsonl(sidecar)) if sidecar.exists() else None
    sample, excluded, eligible_count, sampling_report = select_enron_seed_records(
        rows, gold_rows, count=args.count, seed=args.seed,
        metadata_records=metadata_rows,
    )
    # The two assignment files deliberately share IDs and order but contain no annotations or predictions.
    all_gold_context = gold_rows + rows
    tasks_a = records_to_tasks(sample, assignment="A", gold_records=all_gold_context)
    tasks_b = records_to_tasks(sample, assignment="B", gold_records=all_gold_context)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_a = args.output_dir / "reviewer_a_tasks.json"
    output_b = args.output_dir / "reviewer_b_tasks.json"
    output_a.write_text(json.dumps(tasks_a, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_b.write_text(json.dumps(tasks_b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = args.output_dir / "label_studio_config.xml"
    config.write_text(make_label_studio_config(AI_DIR / "annotation" / "label_schema.json"), encoding="utf-8")
    def repo_path(path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(AI_DIR.parent.resolve()).as_posix()
        except ValueError:
            return str(path)

    manifest = {
        "source_dataset": "enron", "input_pool": repo_path(args.input),
        "metadata_sidecar": repo_path(sidecar) if metadata_rows is not None else None,
        "requested_count": args.count, "seed": args.seed,
        "selected_email_ids": [row["email_id"] for row in sample],
        "unique_threads": len({source_thread_key(row) for row in sample}),
        "eligible_count": eligible_count, "excluded_counts": excluded,
        "sampling": sampling_report, "label_studio_config": repo_path(config),
        "assignment_A": repo_path(output_a), "assignment_B": repo_path(output_b),
        "assignment_ids_match": [task["data"]["email_id"] for task in tasks_a] == [task["data"]["email_id"] for task in tasks_b],
        "annotations_prepopulated": False, "predictions_prepopulated": False,
        "is_human_reviewed": False, "is_gold": False,
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": args.count, "eligible": eligible_count, "excluded_counts": excluded,
                      "sampling": sampling_report, "assignment_A": repo_path(output_a),
                      "assignment_B": repo_path(output_b), "manifest": repo_path(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

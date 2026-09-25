"""Report inter-rater agreement and write human adjudication queues."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.annotation.agreement import compare_reviewer_records
from src.datasets.schemas import read_jsonl, write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-a", type=Path, required=True, help="canonical JSONL imported from assignment A")
    parser.add_argument("--reviewer-b", type=Path, required=True, help="canonical JSONL imported from assignment B")
    parser.add_argument("--report", type=Path, required=True, help="agreement metrics JSON output")
    parser.add_argument("--disagreements", type=Path, help="disagreement queue JSONL; defaults beside report")
    parser.add_argument("--decisions-template", type=Path, help="blank adjudication decisions JSONL; defaults beside report")
    args = parser.parse_args()
    report = compare_reviewer_records(read_jsonl(args.reviewer_a), read_jsonl(args.reviewer_b))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    disagreements_path = args.disagreements or args.report.with_name(args.report.stem + ".disagreements.jsonl")
    template_path = args.decisions_template or args.report.with_name(args.report.stem + ".adjudication_template.jsonl")
    write_jsonl(disagreements_path, report["disagreements"])
    templates = []
    for row in report["disagreements"]:
        templates.append({
            "email_id": row["email_id"], "final": False, "adjudicator": None,
            "labels": None, "spans": None, "resolution_note": None,
            "reviewer_a": row["labels"]["A"], "reviewer_b": row["labels"]["B"],
            "spans_a": row["spans"]["A"], "spans_b": row["spans"]["B"],
        })
    write_jsonl(template_path, templates)
    print(json.dumps({"paired_records": report["paired_records"],
                      "compared_records": report["compared_records"],
                      "excluded_unresolved_records": report["excluded_unresolved_records"],
                      "disagreements": len(report["disagreements"]), "report": str(args.report),
                      "disagreement_queue": str(disagreements_path), "decisions_template": str(template_path),
                      "agreement_is_not_gold": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

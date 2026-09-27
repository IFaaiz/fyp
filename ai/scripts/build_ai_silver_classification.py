"""Build a classification-only AI silver batch from the direct pilot audit.

The result is for prototyping. It is never human-reviewed or gold, and no
reviewer spans are copied because their semantic boundaries remain unchecked.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.datasets.schemas import LABELS, read_jsonl, write_jsonl
from src.datasets.validation import validate_record

DEFAULT_SEED = AI_DIR / "data/annotated/ai/project_pilot_50_v2/annotation_seed_50.jsonl"
DEFAULT_AUDIT = AI_DIR / "annotation/project_pilot_50_v2_silver_decisions.jsonl"
DEFAULT_OUTPUT = AI_DIR / "data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl"


def build(seed: list[dict], audit: list[dict]) -> list[dict]:
    if len(seed) != len(audit) or not seed:
        raise ValueError("seed and audit must have the same nonzero number of rows")
    seed_ids = [row.get("email_id") for row in seed]
    audit_ids = [row.get("email_id") for row in audit]
    if seed_ids != audit_ids or len(set(seed_ids)) != len(seed_ids):
        raise ValueError("seed and audit IDs must be unique and in identical order")

    output = []
    for source, decision in zip(seed, audit):
        if source.get("labels") != [] or source.get("spans") != []:
            raise ValueError(f"seed {source['email_id']} is already annotated")
        if source.get("annotation", {}).get("status") != "unlabelled":
            raise ValueError(f"seed {source['email_id']} is not unlabelled")
        if decision.get("reviewer") != "primary_agent_direct_ai_audit":
            raise ValueError(f"audit provenance mismatch for {source['email_id']}")
        if decision.get("status") not in {"ai_audit_suggestion", "ai_audit_abstention"}:
            raise ValueError(f"audit status mismatch for {source['email_id']}")
        labels = decision.get("suggested_labels")
        if not isinstance(labels, list) or len(labels) != len(set(labels)):
            raise ValueError(f"invalid suggested labels for {source['email_id']}")
        if any(label not in LABELS for label in labels):
            raise ValueError(f"unknown label for {source['email_id']}")
        if "NON_PROJECT" in labels and len(labels) != 1:
            raise ValueError(f"NON_PROJECT must be exclusive for {source['email_id']}")
        if not isinstance(decision.get("needs_review"), bool):
            raise ValueError(f"missing needs_review boolean for {source['email_id']}")
        if not labels and decision["status"] != "ai_audit_abstention":
            raise ValueError(f"empty label set must be an abstention for {source['email_id']}")
        if labels and decision["status"] != "ai_audit_suggestion":
            raise ValueError(f"labelled decision must be a suggestion for {source['email_id']}")

        eligible = bool(labels) and not decision["needs_review"]
        row = dict(source)
        row["labels"] = labels if eligible else []
        row["spans"] = []
        row["annotation"] = {
            "status": "ai_prelabelled" if eligible else "unlabelled",
            "annotator": "primary_agent_direct_ai_audit" if eligible else None,
            "annotation_source": "ai" if eligible else None,
            "confidence": None,
            "needs_review": not eligible,
            "ambiguity_note": decision.get("reason") if not eligible else None,
            "span_review_status": "not_adjudicated",
            "intended_use": "classification_prototype_only",
        }
        errors = validate_record(row)
        if errors:
            raise ValueError(f"invalid output for {source['email_id']}: {'; '.join(errors)}")
        output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    inputs = {args.seed.resolve(), args.audit.resolve()}
    if args.output.resolve() in inputs:
        parser.error("output must not overwrite an input")
    try:
        args.output.resolve().relative_to((AI_DIR / "data").resolve())
    except ValueError:
        parser.error("output must be under ignored ai/data/")
    seed = list(read_jsonl(args.seed))
    audit = list(read_jsonl(args.audit))
    output = build(seed, audit)
    write_jsonl(args.output, output)
    counts = Counter(row["annotation"]["status"] for row in output)
    print(json.dumps({"records": len(output), "ai_prelabelled": counts["ai_prelabelled"],
                      "unlabelled": counts["unlabelled"], "spans_copied": 0,
                      "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

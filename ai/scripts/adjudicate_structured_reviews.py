"""Ingest, compare and adjudicate offline structured review envelopes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.structured_annotation.workflow import (  # noqa: E402
    add_root_decision,
    compare_run,
    export_accepted_train,
    finalize_run,
    ingest_adjudication,
    ingest_envelope,
    ingest_third_initial,
    prepare_accepted_handoff,
    prepare_adjudication,
    prepare_third_initial,
    summarize_run,
)


def _print(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="validate and store one A/B offline envelope")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--role", choices=("A", "B"), required=True)
    p.add_argument("--envelope", type=Path, required=True)

    p = sub.add_parser("compare", help="compare A/B primitives and report gates without text")
    p.add_argument("--run-dir", type=Path, required=True)

    p = sub.add_parser("prepare-third", help="prepare the adjudicator's source-only initial packet")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--reviewer-id", required=True)

    p = sub.add_parser("ingest-third-initial", help="freeze adjudicator's independent initial verdict")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--envelope", type=Path, required=True)

    p = sub.add_parser("prepare-adjudication", help="reveal A/B only after third initial verdict is frozen")
    p.add_argument("--run-dir", type=Path, required=True)

    p = sub.add_parser("ingest-adjudication", help="validate third reviewer post-blind resolution")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--envelope", type=Path, required=True)

    p = sub.add_parser("root-decision", help="record explicit root approval/rejection by source hash")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--source-id", required=True)
    p.add_argument("--annotation-sha256", required=True)
    p.add_argument("--decision", choices=("approve", "reject", "review_required"), required=True)
    p.add_argument("--root-id", required=True)
    p.add_argument("--reason", required=True)

    p = sub.add_parser("finalize", help="write accepted/rejected decisions and progress counts")
    p.add_argument("--run-dir", type=Path, required=True)

    p = sub.add_parser("status", help="show accepted/rejected/review-required counts")
    p.add_argument("--run-dir", type=Path, required=True)

    p = sub.add_parser("prepare-handoff", help="write a private accepted review handoff, never model permission")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--output", type=Path)

    p = sub.add_parser("export-train", help="copy handoff to accepted_train.jsonl only after root authorization")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--authorization", type=Path, required=True)
    p.add_argument("--evaluation-boundary", type=Path, required=True)
    p.add_argument("--handoff", type=Path)

    args = parser.parse_args()
    if args.command == "ingest":
        result = ingest_envelope(run_dir=args.run_dir, role=args.role, envelope_path=args.envelope)
    elif args.command == "compare":
        result = compare_run(run_dir=args.run_dir)
    elif args.command == "prepare-third":
        result = prepare_third_initial(run_dir=args.run_dir, reviewer_identity=args.reviewer_id)
    elif args.command == "ingest-third-initial":
        result = ingest_third_initial(run_dir=args.run_dir, envelope_path=args.envelope)
    elif args.command == "prepare-adjudication":
        result = prepare_adjudication(run_dir=args.run_dir)
    elif args.command == "ingest-adjudication":
        result = ingest_adjudication(run_dir=args.run_dir, envelope_path=args.envelope)
    elif args.command == "root-decision":
        result = add_root_decision(
            run_dir=args.run_dir, source_id=args.source_id,
            annotation_sha256=args.annotation_sha256, decision=args.decision,
            root_identity=args.root_id, reason=args.reason,
        )
    elif args.command == "finalize":
        result = finalize_run(run_dir=args.run_dir)
    elif args.command == "status":
        result = summarize_run(run_dir=args.run_dir)
    elif args.command == "prepare-handoff":
        result = prepare_accepted_handoff(run_dir=args.run_dir, output_path=args.output)
    elif args.command == "export-train":
        result = export_accepted_train(
            run_dir=args.run_dir, output_path=args.output,
            authorization_path=args.authorization,
            evaluation_boundary_path=args.evaluation_boundary,
            handoff_path=args.handoff,
        )
    else:
        raise AssertionError("unreachable command")
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

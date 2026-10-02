"""Preflight and, only with --fit, train authorized structured baselines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from src.structured_models import (  # noqa: E402
    InsufficientTrainingExamples,
    PREDECLARED_MINIMUM_PER_CLASS,
    TrainingGateError,
    fit_and_save_baselines,
    preflight_authorized_export,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one orchestrator-authorized accepted_train.jsonl and preflight "
            "the preregistered TF-IDF baselines. Training requires an explicit --fit."
        )
    )
    parser.add_argument("--accepted-train", required=True, type=Path)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument(
        "--minimum-per-class", type=int, default=PREDECLARED_MINIMUM_PER_CLASS,
        help="minimum positive and negative examples per head; cannot be below the preregistered 20",
    )
    parser.add_argument("--fit", action="store_true", help="fit and save models after every gate passes")
    parser.add_argument(
        "--output-dir", type=Path,
        help="required with --fit; must be a new directory below ai/data/",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.fit and args.output_dir is None:
        print("--output-dir is required with --fit", file=sys.stderr)
        return 2
    if not args.fit and args.output_dir is not None:
        print("--output-dir is only accepted with --fit", file=sys.stderr)
        return 2

    registry_path = AI_ROOT / "config" / "dataset_registry.json"
    try:
        export, preflight = preflight_authorized_export(
            args.accepted_train,
            args.authorization,
            registry_path,
            minimum_per_class=args.minimum_per_class,
        )
    except TrainingGateError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    report = {
        "status": "READY_NO_FIT_REQUESTED" if preflight.ready else "BLOCKED_INSUFFICIENT_COUNTS",
        "accepted_rows": len(export.rows),
        "accepted_source_ids_sha256": export.manifest["accepted_source_ids_sha256"],
        "preflight": preflight.to_dict(),
        "models_trained": 0,
        "evaluation_performed": False,
    }
    if not preflight.ready:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    if args.fit:
        try:
            metadata = fit_and_save_baselines(export, preflight, args.output_dir)
        except (TrainingGateError, OSError) as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        report["status"] = "TRAINED_NO_EVALUATION"
        report["models_trained"] = metadata["models_trained"]
        report["artifacts"] = str(args.output_dir.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

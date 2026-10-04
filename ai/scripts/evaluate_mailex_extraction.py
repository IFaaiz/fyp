"""Evaluate native MailEx event-record predictions.

Example:
  .venv/Scripts/python.exe scripts/evaluate_mailex_extraction.py \
    --gold data/experiments/mailex_extraction_v1/dev_fyp_safe.jsonl \
    --predictions data/experiments/mailex_extraction_v1/dev_predictions.jsonl \
    --output data/experiments/mailex_extraction_v1/dev_metrics.json --split dev

The command reads only the two paths supplied by the caller. It does not load
models, discover datasets, or write source text to the report. TEST additionally
requires a committed, clean selection lock and a prior one-time inference
reservation; TEST is never read by this module automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT))

from src.mailex_extraction.metrics import (  # noqa: E402
    EvaluationDataError,
    score_rows,
    validate_committed_test_lock,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvaluationDataError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise EvaluationDataError(f"{path}:{line_number}: JSONL rows must be objects")
            rows.append(value)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_repo_path(repository_root: Path, value: str, *, name: str) -> Path:
    path = (repository_root / value).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise EvaluationDataError(f"{name} must resolve within the repository") from exc
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path, help="native MailEx gold JSONL")
    parser.add_argument("--predictions", required=True, type=Path, help="message-level prediction JSONL")
    parser.add_argument("--split", choices=("train", "dev", "test"), default="dev",
                        help="split to score; TEST requires the frozen selection lock")
    parser.add_argument("--output", type=Path,
                        help="optional JSON report path; otherwise print the source-free report")
    parser.add_argument("--selection-lock", type=Path,
                        help="committed text-only selection manifest (required for TEST)")
    parser.add_argument("--finalist-id", help="locked finalist run_id (required for TEST)")
    args = parser.parse_args()

    try:
        if args.output and args.output.resolve() in {args.gold.resolve(), args.predictions.resolve()}:
            raise EvaluationDataError("report output path must differ from both input files")
        if args.split != "test":
            if args.selection_lock or args.finalist_id:
                raise EvaluationDataError("selection-lock arguments are only valid for TEST scoring")
            result = score_rows(_read_jsonl(args.gold), _read_jsonl(args.predictions), split=args.split)
        else:
            if not args.selection_lock or not args.finalist_id:
                raise EvaluationDataError("TEST requires --selection-lock and --finalist-id")
            lock_info = validate_committed_test_lock(args.selection_lock)
            manifest = lock_info["manifest"]
            finalist_rows = [item for item in manifest["finalists"] if item["run_id"] == args.finalist_id]
            if len(finalist_rows) != 1:
                raise EvaluationDataError(f"finalist {args.finalist_id!r} is not uniquely locked")
            finalist = finalist_rows[0]
            expected_gold = _safe_repo_path(lock_info["repository_root"], manifest["gold_path"], name="locked TEST gold")
            expected_predictions = _safe_repo_path(
                lock_info["repository_root"],
                finalist.get("expected_output_path", finalist.get("expected_private_output_path")),
                name="locked finalist output")
            gold_path = args.gold.resolve()
            predictions_path = args.predictions.resolve()
            if gold_path != expected_gold:
                raise EvaluationDataError("--gold path differs from the committed selection lock")
            if predictions_path != expected_predictions:
                raise EvaluationDataError("--predictions path differs from the committed finalist output path")
            if not predictions_path.is_file():
                raise EvaluationDataError("locked finalist prediction output does not exist")

            private_dir = lock_info["repository_root"] / "ai" / "data" / "experiments" / "mailex_extraction_v1" / "private_test"
            reservation = private_dir / f"{args.finalist_id}.reservation.json"
            receipt = private_dir / f"{args.finalist_id}.receipt.json"
            evaluation_started = private_dir / f"{args.finalist_id}.evaluation_started.json"
            if not reservation.is_file():
                raise EvaluationDataError("TEST inference has no one-time reservation marker")
            try:
                reservation_payload = json.loads(reservation.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise EvaluationDataError("TEST inference reservation marker is malformed") from exc
            if (reservation_payload.get("run_id") != args.finalist_id
                    or reservation_payload.get("selection_lock_sha256") != lock_info["sha256"]
                    or reservation_payload.get("expected_output_path") != expected_predictions.relative_to(lock_info["repository_root"]).as_posix()):
                raise EvaluationDataError("TEST inference reservation does not match this lock/finalist")
            if receipt.exists() or evaluation_started.exists():
                raise EvaluationDataError("TEST evaluation is one-time and already reserved or complete for this finalist")
            if args.output and args.output.exists():
                raise EvaluationDataError("TEST metrics output already exists")
            # This exclusive marker prevents concurrent or repeated scoring.
            with evaluation_started.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"run_id": args.finalist_id,
                                         "selection_lock_sha256": lock_info["sha256"],
                                         "status": "evaluation_started"}, sort_keys=True) + "\n")
            prediction_sha256 = _sha256_file(predictions_path)
            gold_sha256 = _sha256_file(gold_path)
            if gold_sha256 != manifest["gold_sha256"]:
                raise EvaluationDataError("locked TEST gold digest changed before read")
            gold_rows = _read_jsonl(gold_path)
            prediction_rows = _read_jsonl(predictions_path)
            if (_sha256_file(gold_path) != gold_sha256
                    or _sha256_file(predictions_path) != prediction_sha256):
                raise EvaluationDataError("locked TEST inputs changed while being read")
            result = score_rows(gold_rows, prediction_rows, split="test", test_authorization=manifest)
            receipt_payload = {
                "schema_version": 1,
                "status": "complete",
                "run_id": args.finalist_id,
                "selection_lock_sha256": lock_info["sha256"],
                "gold_sha256": gold_sha256,
                "predictions_sha256": prediction_sha256,
                "metrics": result,
            }
            with receipt.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(receipt_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8", newline="\n")
    except (OSError, EvaluationDataError) as exc:
        parser.exit(2, f"evaluation failed: {exc}\n")

    if args.split == "test":
        sys.stdout.write(json.dumps({"status": "complete", "run_id": args.finalist_id,
                                     "prediction_sha256": prediction_sha256,
                                     "receipt": str(receipt)}, sort_keys=True) + "\n")
    else:
        serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

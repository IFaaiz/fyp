"""Synthetic control-flow tests for the GLiNER predictor's DEV/TEST gates.

These tests use a temporary DEV-shaped JSONL and nonexistent TEST-shaped paths.
They never open the corpus TEST file, load model weights, or run inference.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT))
sys.path.insert(0, str(AI_ROOT / "scripts"))
sys.path.insert(0, str(AI_ROOT / "src"))

from mailex_extraction.gliner_backend import MailExOntology, iter_jsonl as read_jsonl  # noqa: E402
from mailex_extraction import metrics as metrics_module  # noqa: E402
from mailex_extraction.metrics import EvaluationDataError  # noqa: E402
from scripts import predict_mailex_gliner as predictor  # noqa: E402


class _FakeModel:
    def eval(self):
        return self


def _predictor_args(*, split: str, source: Path, output: Path, schema: Path,
                    checkpoint: Path, metrics: Path | None = None) -> Namespace:
    return Namespace(
        input=str(source),
        checkpoint=str(checkpoint),
        schema=str(schema),
        output=str(output),
        metrics=str(metrics) if metrics is not None else None,
        device="cpu",
        split=split,
        threshold=0.5,
        selection_lock=None,
        finalist_id=None,
    )


def _synthetic_locked_case(root: Path):
    """A committed-lock-shaped fixture whose TEST-shaped body is synthetic."""
    source_path = root / "synthetic_test_rows.jsonl"
    source_row = {
        "message_id": "synthetic-test-only",
        "thread_id": "synthetic",
        "split": "test",
        "text": "Synthetic request arrives tomorrow.",
        "tokens": ["Synthetic", "request", "arrives", "tomorrow."],
        "token_offsets": [],
        "events": [],
    }
    source_path.write_text(json.dumps(source_row) + "\n", encoding="utf-8")
    checkpoint = root / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"synthetic weights")
    schema = root / "train_only_schema.json"
    schema.write_text("{}", encoding="utf-8")
    output_path = root / "ai" / "data" / "experiments" / "mailex_extraction_v1" / "private_test" / "predictions.jsonl"
    checkpoint_relative = checkpoint.relative_to(root).as_posix()
    schema_relative = schema.relative_to(root).as_posix()
    finalist = {
        "run_id": "gliner_small_selected",
        "architecture": "synthetic",
        "config": {"checkpoint_directory": checkpoint_relative},
        "thresholds": {"record": 0.5},
        "inference_device": "cpu",
        "expected_output_path": output_path.relative_to(root).as_posix(),
        "model_weights": {f"{checkpoint_relative}/model.safetensors": "a" * 64},
        "code": {"synthetic.py": "b" * 64},
        "preprocessing": {
            f"{checkpoint_relative}/config.json": "c" * 64,
            "ai/config/mailex_extraction_environment.json": "d" * 64,
        },
        "evaluator": {"synthetic_evaluator.py": "e" * 64},
        "schema": {schema_relative: "f" * 64},
    }
    manifest = {
        "schema_version": 1,
        "status": "locked",
        "split": "test",
        "gold_path": source_path.relative_to(root).as_posix(),
        "gold_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "finalists": [finalist],
    }
    lock_info = {"manifest": manifest, "repository_root": root, "sha256": "1" * 64}
    args = _predictor_args(
        split="test", source=source_path, output=output_path, schema=schema,
        checkpoint=checkpoint,
    )
    args.selection_lock = str(root / "synthetic_committed_lock.json")
    args.finalist_id = finalist["run_id"]
    return args, lock_info, finalist, source_path, output_path, schema


class GLiNERPredictorGateTests(unittest.TestCase):
    def test_synthetic_dev_run_reads_only_approved_synthetic_dev_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dev_path = root / "dev_fyp_safe.jsonl"
            schema_path = root / "train_only_schema.json"
            output_path = root / "predictions.jsonl"
            metrics_path = root / "metrics.json"
            text = "Rina sent the agenda."
            source_row = {
                "message_id": "synthetic-thread::turn_0",
                "thread_id": "synthetic-thread",
                "split": "dev",
                "text": text,
                "tokens": text.split(),
                "token_offsets": [],
                "events": [],
            }
            dev_path.write_text(json.dumps(source_row) + "\n", encoding="utf-8")
            schema_path.write_text("{}", encoding="utf-8")
            expected_dev_hash = hashlib.sha256(dev_path.read_bytes()).hexdigest()
            ontology = MailExOntology(("Synthetic_Event",), {"Synthetic_Event": ()})
            args = _predictor_args(
                split="dev", source=dev_path, output=output_path,
                schema=schema_path, checkpoint=root / "unused-checkpoint",
                metrics=metrics_path,
            )
            read_paths: list[Path] = []

            def guarded_iter_jsonl(path):
                resolved = Path(path).resolve()
                self.assertEqual(resolved, dev_path.resolve())
                read_paths.append(resolved)
                yield from read_jsonl(resolved)

            metric_result = {
                "argument_records": {"role_exact": {"micro": {"f1": 0.0}}},
                "events": {"record_partial": {"f1": 0.0}},
            }
            with (
                patch.object(predictor, "DATA_DIR", root),
                patch.object(predictor, "DEV_SHA256", expected_dev_hash),
                patch.object(predictor, "_load_frozen_ontology", return_value=ontology),
                patch.object(predictor, "load_extractor", return_value=_FakeModel()),
                patch.object(predictor, "_pack_event_types", return_value=[(("Synthetic_Event",), object(), 1)]),
                patch.object(predictor, "_infer_one_group", return_value=({}, 1, 8, [(0, len(text))])),
                patch.object(
                    predictor,
                    "prediction_row",
                    return_value=(
                        {"message_id": source_row["message_id"], "thread_id": source_row["thread_id"],
                         "split": "dev", "text": text, "events": []},
                        {"records": 0, "grounded_trigger_segments": 0,
                         "grounded_argument_segments": 0, "ungrounded_segments": 0},
                    ),
                ),
                patch.object(predictor, "private_package_versions", return_value={}),
                patch.object(predictor, "score_rows", return_value=metric_result),
                patch.object(predictor, "iter_jsonl", side_effect=guarded_iter_jsonl),
                patch.object(predictor, "reserve_test_run") as reserve,
                patch.object(predictor, "validate_committed_test_lock") as validate_lock,
            ):
                predictor._run(args)

            self.assertEqual(read_paths, [dev_path.resolve()])
            reserve.assert_not_called()
            validate_lock.assert_not_called()
            self.assertTrue(output_path.is_file())
            self.assertTrue(metrics_path.is_file())

    def _assert_locked_gate_rejects_before_source(self, case, message: str) -> None:
        args, lock_info, _finalist, _source_path, _output_path, _schema = case
        with (
            patch.object(predictor, "validate_committed_test_lock", return_value=lock_info),
            patch.object(metrics_module, "validate_committed_test_lock", return_value=lock_info),
            patch.object(predictor, "_load_frozen_ontology", return_value=MailExOntology(("Synthetic_Event",), {"Synthetic_Event": ()})),
            patch.object(predictor, "iter_jsonl") as read_input,
            patch.object(predictor, "load_extractor") as load_model,
            patch.object(predictor, "reserve_test_run") as reserve,
        ):
            with self.assertRaisesRegex(ValueError, message):
                predictor._run(args)
        read_input.assert_not_called()
        load_model.assert_not_called()
        reserve.assert_not_called()

    def test_locked_device_mismatch_fails_before_reservation_or_input(self):
        with tempfile.TemporaryDirectory() as directory:
            case = _synthetic_locked_case(Path(directory))
            case[2]["inference_device"] = "cuda"
            self._assert_locked_gate_rejects_before_source(case, "TEST device differs")

    def test_locked_threshold_mismatch_fails_before_reservation_or_input(self):
        with tempfile.TemporaryDirectory() as directory:
            case = _synthetic_locked_case(Path(directory))
            case[0].threshold = 0.7
            self._assert_locked_gate_rejects_before_source(case, "TEST record threshold differs")

    def test_locked_checkpoint_mismatch_fails_before_reservation_or_input(self):
        with tempfile.TemporaryDirectory() as directory:
            case = _synthetic_locked_case(Path(directory))
            case[0].checkpoint = str(Path(directory) / "different-checkpoint")
            self._assert_locked_gate_rejects_before_source(case, "checkpoint directory differs")

    def test_missing_schema_config_map_fails_before_reservation_or_input(self):
        with tempfile.TemporaryDirectory() as directory:
            case = _synthetic_locked_case(Path(directory))
            case[2]["schema"] = {}
            self._assert_locked_gate_rejects_before_source(case, "exactly one ontology file")

    def test_missing_checkpoint_preprocessing_config_fails_before_reservation_or_input(self):
        with tempfile.TemporaryDirectory() as directory:
            case = _synthetic_locked_case(Path(directory))
            case[2]["preprocessing"].pop("checkpoint/config.json")
            self._assert_locked_gate_rejects_before_source(case, "preprocessing is not fully frozen")

    def test_existing_locked_output_is_rejected_before_hashing_or_reading_input(self):
        with tempfile.TemporaryDirectory() as directory:
            args, lock_info, _finalist, _source_path, output_path, _schema = _synthetic_locked_case(Path(directory))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("already present\n", encoding="utf-8")
            real_reserve = metrics_module.reserve_test_run
            reservations = []

            def reserve_with_real_checks(lock_path, run_id):
                reservations.append((lock_path, run_id))
                return real_reserve(lock_path, run_id)

            with (
                patch.object(predictor, "validate_committed_test_lock", return_value=lock_info),
                patch.object(metrics_module, "validate_committed_test_lock", return_value=lock_info),
                patch.object(predictor, "_load_frozen_ontology", return_value=MailExOntology(("Synthetic_Event",), {"Synthetic_Event": ()})),
                patch.object(predictor, "reserve_test_run", side_effect=reserve_with_real_checks),
                patch.object(predictor, "iter_jsonl") as read_input,
                patch.object(predictor, "load_extractor") as load_model,
                patch.object(predictor, "sha256_file", wraps=predictor.sha256_file) as hash_file,
            ):
                with self.assertRaisesRegex(EvaluationDataError, "output already exists"):
                    predictor._run(args)

            self.assertEqual(len(reservations), 1)
            read_input.assert_not_called()
            load_model.assert_not_called()
            hash_file.assert_not_called()

    def test_valid_synthetic_locked_run_reserves_before_reading_synthetic_input(self):
        with tempfile.TemporaryDirectory() as directory:
            args, lock_info, _finalist, source_path, output_path, schema_path = _synthetic_locked_case(Path(directory))
            events: list[str] = []
            real_reserve = metrics_module.reserve_test_run

            def reserve_then_record(lock_path, run_id):
                events.append("reserve")
                return real_reserve(lock_path, run_id)

            def only_synthetic_input(path):
                resolved = Path(path).resolve()
                self.assertEqual(resolved, source_path.resolve())
                events.append("read_synthetic_source")
                yield from read_jsonl(resolved)

            ontology = MailExOntology(("Synthetic_Event",), {"Synthetic_Event": ()})
            fake_model = _FakeModel()
            with (
                patch.object(predictor, "validate_committed_test_lock", return_value=lock_info),
                patch.object(metrics_module, "validate_committed_test_lock", return_value=lock_info),
                patch.object(predictor, "reserve_test_run", side_effect=reserve_then_record),
                patch.object(predictor, "_load_frozen_ontology", return_value=ontology),
                patch.object(predictor, "load_extractor", return_value=fake_model),
                patch.object(predictor, "_pack_event_types", return_value=[(("Synthetic_Event",), object(), 1)]),
                patch.object(predictor, "_infer_one_group", return_value=({}, 1, 8, [(0, 36)])),
                patch.object(
                    predictor,
                    "iter_jsonl",
                    side_effect=only_synthetic_input,
                ),
                patch.object(
                    predictor,
                    "prediction_row",
                    return_value=(
                        {"message_id": "synthetic-test-only", "thread_id": "synthetic",
                         "split": "test", "text": "Synthetic request arrives tomorrow.", "events": []},
                        {"records": 0, "grounded_trigger_segments": 0,
                         "grounded_argument_segments": 0, "ungrounded_segments": 0},
                    ),
                ),
                patch.object(predictor, "private_package_versions", return_value={}),
                redirect_stdout(io.StringIO()),
            ):
                predictor._run(args)

            self.assertEqual(events, ["reserve", "read_synthetic_source"])
            self.assertTrue((output_path.parent / "gliner_small_selected.reservation.json").is_file())
            self.assertTrue(output_path.is_file())

    def test_test_split_without_lock_fails_before_input_or_model_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nonexistent_test = root / "test_input_must_not_be_opened.jsonl"
            args = _predictor_args(
                split="test", source=nonexistent_test, output=root / "predictions.jsonl",
                schema=root / "schema.json", checkpoint=root / "checkpoint",
            )
            with (
                patch.object(predictor, "iter_jsonl") as read_input,
                patch.object(predictor, "load_extractor") as load_model,
                patch.object(predictor, "reserve_test_run") as reserve,
                patch.object(predictor, "validate_committed_test_lock") as validate_lock,
            ):
                with self.assertRaisesRegex(ValueError, "TEST requires --selection-lock and --finalist-id"):
                    predictor._run(args)

            self.assertFalse(nonexistent_test.exists())
            read_input.assert_not_called()
            load_model.assert_not_called()
            reserve.assert_not_called()
            validate_lock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

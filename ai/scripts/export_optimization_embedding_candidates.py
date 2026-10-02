"""Export exact-order numeric arrays and a root-friendly candidate manifest.

Only the frozen optimization TRAIN/DEV partitions are loaded. No email text is
written by this exporter; the arrays contain probabilities only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

AI_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = AI_DIR / "data/experiments/optimization_20261002/embeddings"
REPORT_PATH = AI_DIR / "reports/optimization_embeddings.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_bundle(registry: dict[str, Any], name: str) -> dict[str, Any]:
    for item in registry.get("bundles", []):
        if item.get("bundle_name") == name:
            return item
    raise KeyError(f"embedding bundle is not registered: {name}")


def _metrics(registry: dict[str, Any], run_id: str) -> dict[str, Any]:
    for item in registry.get("runs", []):
        if item.get("run_id") == run_id:
            return item
    for item in registry.get("additional_ablations", []):
        if item.get("run_id") == run_id:
            return item
    if run_id == "per_label_specialists":
        return registry["per_label_specialists"]
    contrastive = registry.get("contrastive_fewshot", {}).get("run")
    if contrastive and contrastive.get("run_id") == run_id:
        return contrastive
    raise KeyError(f"no run metrics found for candidate: {run_id}")


def _arrays_for_run(
    run_id: str,
    dev_path: Path,
    oof_path: Path,
    expected_dev_ids: list[str],
    expected_train_ids: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    dev_payload = _json(dev_path)
    oof_payload = _json(oof_path)
    if dev_payload.get("row_ids") != expected_dev_ids:
        raise ValueError(f"DEV probability row order mismatch: {run_id}")
    if oof_payload.get("row_ids") != expected_train_ids:
        raise ValueError(f"TRAIN OOF probability row order mismatch: {run_id}")
    try:
        dev_values = np.asarray(dev_payload["probabilities"][run_id], dtype=np.float32)
        oof_values = np.asarray(oof_payload["probabilities"][run_id], dtype=np.float32)
    except KeyError as exc:
        raise KeyError(f"probability artifact does not contain {run_id}") from exc
    for name, values, expected in (
        ("DEV", dev_values, len(expected_dev_ids)),
        ("TRAIN OOF", oof_values, len(expected_train_ids)),
    ):
        if values.shape != (expected, 9) or not np.isfinite(values).all():
            raise ValueError(f"{name} probabilities for {run_id} have invalid shape or values: {values.shape}")
    return dev_values, oof_values


def _save_probability_array(run_id: str, split: str, values: np.ndarray) -> Path:
    output = EXPERIMENT_DIR / "standardized_candidates" / f"{run_id}__{split}_probabilities.npy"
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, values, allow_pickle=False)
    return output.resolve()


def _candidate_specs(registry: dict[str, Any]) -> list[dict[str, Any]]:
    main_dev = EXPERIMENT_DIR / "dev_probabilities.json"
    main_oof = EXPERIMENT_DIR / "train_oof_probabilities.json"
    specialist_dev = EXPERIMENT_DIR / "dev_probabilities_specialists.json"
    specialist_oof = EXPERIMENT_DIR / "train_oof_probabilities_specialists.json"
    ablation_dev = EXPERIMENT_DIR / "dev_probabilities_long_ablation.json"
    ablation_oof = EXPERIMENT_DIR / "train_oof_probabilities_long_ablation.json"

    specs = [
        {"run_id": "minilm_flat_lr_c1_none", "source_dev": main_dev, "source_oof": main_oof},
        {"run_id": "minilm_hier_lr_c0.1", "source_dev": main_dev, "source_oof": main_oof},
        {"run_id": "per_label_specialists", "source_dev": specialist_dev, "source_oof": specialist_oof},
    ]
    if any(item.get("run_id") == "minilm_subject_body_two_chunks_lr_c1" for item in registry.get("additional_ablations", [])):
        specs.append({"run_id": "minilm_subject_body_two_chunks_lr_c1", "source_dev": ablation_dev, "source_oof": ablation_oof})
    if registry.get("contrastive_fewshot", {}).get("run"):
        contrastive = registry["contrastive_fewshot"]["run"]
        specs.append({
            "run_id": contrastive["run_id"],
            "bundle_name": "setfit_style_contrastive",
            "source_dev": Path(contrastive["dev_probabilities_path"]),
            "source_oof": Path(contrastive["train_oof_probabilities_path"]),
        })
    return specs


def _latency_seconds(run: dict[str, Any], run_id: str, registry: dict[str, Any]) -> tuple[float, str]:
    if run_id == "per_label_specialists":
        manifest = _json(EXPERIMENT_DIR / "frozen_feature_manifest.json")
        feature_keys = sorted({item["feature_key"] for item in run["selected_heads"]})
        encode_ms = 0.0
        for key in feature_keys:
            feature = manifest["features"][key]
            count = int(feature.get("train_records", 0)) + int(feature.get("dev_records", 0))
            if count:
                encode_ms += 1000.0 * float(feature.get("encode_seconds", 0.0)) / count
        head_ms = 1000.0 * float(registry["runs"][3].get("dev_inference_seconds", 0.0)) / max(int(run["dev_metrics"]["records"]), 1)
        return (encode_ms + head_ms) / 1000.0, "sum of measured frozen-encoder view throughput plus one measured sklearn-head pass; amortized per record"
    if "estimated_end_to_end_ms_per_record" in run:
        return float(run["estimated_end_to_end_ms_per_record"]) / 1000.0, "measured feature-encoding throughput plus measured sklearn-head inference"
    if "single_record_encoder_latency_ms" in run:
        head_ms = float(run.get("dev_inference_ms_per_record", 0.0))
        return (float(run["single_record_encoder_latency_ms"]) + head_ms) / 1000.0, "measured single-record encoder forward plus measured sklearn-head inference"
    feature_key = run.get("features", {}).get("text_view")
    sequence_mode = run.get("features", {}).get("sequence_mode", "head")
    manifest = _json(EXPERIMENT_DIR / "frozen_feature_manifest.json")
    if sequence_mode == "head_tail":
        feature_name = "minilm_subject_body_head_tail"
    elif sequence_mode == "two_chunks":
        feature_name = "minilm_subject_body_two_chunks"
    else:
        feature_name = f"minilm_{feature_key}" if feature_key else "minilm_subject_body"
    feature = manifest["features"][feature_name]
    count = int(feature.get("train_records", 0)) + int(feature.get("dev_records", 0))
    encode_ms = 1000.0 * float(feature.get("encode_seconds", 0.0)) / max(count, 1)
    head_ms = float(run.get("dev_head_inference_ms_per_record", 0.0))
    return (encode_ms + head_ms) / 1000.0, "measured feature-cache encoder throughput plus measured sklearn-head inference; amortized per record"


def main() -> int:
    from src.models.optimization_benchmark import LABEL_ORDER, benchmark_hash, load_partition

    registry = _json(REPORT_PATH)
    train_rows = load_partition("train")
    dev_rows = load_partition("dev")
    train_ids = [str(row["email_id"]) for row in train_rows]
    dev_ids = [str(row["email_id"]) for row in dev_rows]
    train_order_hash = hashlib.sha256("\n".join(train_ids).encode("utf-8")).hexdigest()
    dev_order_hash = hashlib.sha256("\n".join(dev_ids).encode("utf-8")).hexdigest()

    candidates = []
    for spec in _candidate_specs(registry):
        run_id = spec["run_id"]
        run = _metrics(registry, run_id)
        bundle_name = spec.get("bundle_name") or (
            "best_flat" if run_id == "minilm_flat_lr_c1_none"
            else "best_hierarchical" if run_id == "minilm_hier_lr_c0.1"
            else run_id
        )
        bundle = _find_bundle(registry, bundle_name)
        dev_values, oof_values = _arrays_for_run(
            run_id, Path(spec["source_dev"]), Path(spec["source_oof"]), dev_ids, train_ids,
        )
        dev_array = _save_probability_array(run_id, "dev", dev_values)
        oof_array = _save_probability_array(run_id, "train_oof", oof_values)
        thresholds_map = bundle.get("thresholds_train_oof_only", run.get("oof_thresholds", run.get("thresholds_train_oof_only")))
        if isinstance(thresholds_map, dict):
            thresholds = [float(thresholds_map[label]) for label in LABEL_ORDER]
        elif thresholds_map is not None:
            thresholds = [float(value) for value in thresholds_map]
        else:
            raise ValueError(f"thresholds are missing for {run_id}")
        if len(thresholds) != 9:
            raise ValueError(f"expected 9 thresholds for {run_id}, got {len(thresholds)}")
        latency, latency_basis = _latency_seconds(run, run_id, registry)
        mode = bundle.get("prediction_mode", run.get("prediction_mode", run.get("mode", "flat")))
        fallback = bool(bundle.get("fallback", run.get("fallback", False)))
        model_size = int(bundle.get("package_size_bytes", run.get("package_size_bytes", run.get("model_package_size_bytes", 0))))
        candidate = {
            "run_id": run_id,
            "model_path": str(Path(bundle["bundle_path"]).resolve()),
            "mode": mode,
            "fallback": fallback,
            "thresholds": thresholds,
            "threshold_source": "TRAIN grouped OOF only",
            "dev_used_for_fit": False,
            "dev_used_for_candidate_selection": True,
            "dev_metric_selection_note": (
                "Per-label heads and feature views were chosen using DEV labels; DEV F1 is strongly selection-biased."
                if run_id == "per_label_specialists"
                else "DEV is used for candidate screening/inclusion; this score is diagnostic and selection-biased."
            ),
            "dev_metrics": run["dev_metrics"],
            "train_oof_probabilities_path": str(oof_array),
            "dev_probabilities_path": str(dev_array),
            "train_oof_probabilities_sha256": _sha256(oof_array),
            "dev_probabilities_sha256": _sha256(dev_array),
            "train_oof_row_order_sha256": train_order_hash,
            "dev_row_order_sha256": dev_order_hash,
            "train_records": len(train_ids),
            "dev_records": len(dev_ids),
            "model_size_bytes": model_size,
            "inference_seconds_per_record": latency,
            "inference_latency_basis": latency_basis,
            "benchmark_sha256": benchmark_hash(),
            "test_used_or_read": False,
        }
        candidates.append(candidate)

    registry["final_candidates"] = candidates
    registry["final_candidate_export"] = {
        "scope": "DEV candidates only; numeric probabilities, exact canonical row order; TEST unread",
        "label_order": LABEL_ORDER,
        "dev_row_order_sha256": dev_order_hash,
        "train_oof_row_order_sha256": train_order_hash,
        "probability_array_format": "NumPy .npy, float32, N x 9, allow_pickle=false",
        "benchmark_sha256": benchmark_hash(),
    }
    REPORT_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidates": [{"run_id": item["run_id"], "dev_macro_f1": item["dev_metrics"]["macro_f1"], "dev_micro_f1": item["dev_metrics"]["micro_f1"], "model_path": item["model_path"], "dev_probabilities_path": item["dev_probabilities_path"], "train_oof_probabilities_path": item["train_oof_probabilities_path"]} for item in candidates]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

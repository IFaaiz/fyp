"""Run bounded TRAIN/DEV lexical optimization experiments; never loads TEST."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

AI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI))

from src.models.optimization_benchmark import (  # noqa: E402
    DATA, LABEL_ORDER, benchmark_hash, cv_splits, load_partition,
    oof_thresholds, score_probabilities, targets,
)
from src.models.optimization_lexical import (  # noqa: E402
    FUNCTION_LABELS, BinaryHead, LabelDependencyModel,
    LexicalDependencyBundle, LexicalFeatureEncoder, LexicalModel,
    LexicalSpecialistBundle, make_model,
)


MODEL_DIR = AI / "data/models/optimization/lexical"
OUTPUT_DIR = DATA / "lexical"
REPORT = AI / "reports/optimization_lexical.json"
CS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
ALGORITHMS = ("logistic", "linear_svc")
PROFILES = (
    "word_1_1", "word_1_2", "word_1_3",
    "char_3_5", "char_3_6", "char_4_6",
    "word_1_2_char_3_5", "word_1_2_char_3_6", "word_1_3_char_4_6",
)
EXACT_AGREEMENT_RULES = {
    "exact_unflagged_blind_agreement_third_audit_gate",
    "exact_unflagged_blind_agreement_supervisor_spot_audit",
}
SEED = 20261004


def _key(*values: Any) -> str:
    value = "_".join(str(v) for v in values)
    return value.replace(".", "p").replace("-", "m").replace(" ", "_")


def _candidate_id(spec: dict[str, Any]) -> str:
    return _key(
        spec["task"], spec["profile"], spec["algorithm"], f"C{spec['c']:g}",
        spec.get("text_mode", "subject_body"),
        "domain" if spec.get("use_domain", True) else "nodomain",
        spec.get("class_weight", "none"),
        f"cap{spec['weight_cap']:g}" if spec.get("weight_cap") is not None else "nocap",
        spec.get("training_subset", "all"),
    )


def _fit_model(rows, spec, *, encoder=None):
    """Fit one configuration while fitting vocabularies only on these rows."""
    feature_encoder = encoder or LexicalFeatureEncoder(
        spec["profile"], text_mode=spec.get("text_mode", "subject_body"),
        use_domain=spec.get("use_domain", True),
    ).fit(rows)
    matrix = feature_encoder.transform(rows)
    model = make_model(
        profile=spec["profile"], algorithm=spec["algorithm"], c=spec["c"],
        task=spec["task"], text_mode=spec.get("text_mode", "subject_body"),
        use_domain=spec.get("use_domain", True),
        class_weight=spec.get("class_weight", "none"),
        weight_cap=spec.get("weight_cap"),
    )
    model.encoder = feature_encoder
    model.metadata = {"candidate_id": _candidate_id(spec), "seed": SEED}
    if spec["task"] == "flat":
        model._fit_heads(matrix, targets(rows), LABEL_ORDER)
    else:
        scope_y = np.asarray([int("NON_PROJECT" not in r["labels"]) for r in rows], dtype=np.int8)
        model._fit_head(matrix, scope_y, "PROJECT")
        model.heads["NON_PROJECT"] = BinaryHead(None)
        project_mask = np.asarray(["NON_PROJECT" not in r["labels"] for r in rows])
        project_rows = [r for r, is_project in zip(rows, project_mask) if is_project]
        model._fit_heads(matrix[project_mask], targets(project_rows)[:, :len(FUNCTION_LABELS)], FUNCTION_LABELS)
    return model


def _component_names(task):
    return list(LABEL_ORDER) if task == "flat" else ["PROJECT", *FUNCTION_LABELS]


def _raw_components(model, rows):
    matrix = model.encoder.transform(rows)
    return {name: model.heads[name].raw_score(matrix) for name in _component_names(model.task)}


def _fit_platt(raw_scores, y):
    y = np.asarray(y, dtype=np.int8)
    if np.sum(y) < 15 or len(y) - np.sum(y) < 15:
        return None
    estimator = LogisticRegression(C=1.0, solver="lbfgs", max_iter=500, random_state=SEED)
    estimator.fit(np.asarray(raw_scores, dtype=np.float64).reshape(-1, 1), y)
    return estimator


def _raw_to_probabilities(scores, y, folds, algorithm, task):
    """Cross-fit SVC Platt maps by the frozen TRAIN groups; no in-fold targets."""
    calibrated: dict[str, np.ndarray] = {}
    calibrators: dict[str, Any] = {}
    is_project = np.asarray(["NON_PROJECT" not in labels for labels in y])
    for name, raw in scores.items():
        if algorithm == "logistic":
            calibrated[name] = np.asarray(raw, dtype=np.float64)
            continue
        target = is_project.astype(np.int8) if name == "PROJECT" else np.asarray([int(name in labels) for labels in y], dtype=np.int8)
        eligible = is_project if task == "hierarchical" and name != "PROJECT" else np.ones(len(y), dtype=bool)
        prediction = np.zeros(len(y), dtype=np.float64)
        all_rows = np.arange(len(y))
        for _, held_indices in folds:
            held = np.asarray(held_indices, dtype=int)
            training = np.setdiff1d(all_rows, held, assume_unique=False)
            training = training[eligible[training]]
            held_eligible = eligible[held]
            cal = _fit_platt(np.asarray(raw)[training], target[training])
            raw_held = np.clip(np.asarray(raw)[held], -30, 30)
            fallback = 1.0 / (1.0 + np.exp(-raw_held))
            if cal is not None:
                fallback[held_eligible] = cal.predict_proba(np.asarray(raw)[held[held_eligible]].reshape(-1, 1))[:, 1]
            prediction[held] = fallback
        final_fit = np.flatnonzero(eligible)
        calibrators[name] = _fit_platt(np.asarray(raw)[final_fit], target[final_fit])
        calibrated[name] = prediction
    if task == "flat":
        return np.column_stack([calibrated[label] for label in LABEL_ORDER]), calibrators
    project_probability = calibrated["PROJECT"]
    output = np.zeros((len(y), len(LABEL_ORDER)), dtype=np.float64)
    output[:, -1] = 1.0 - project_probability
    for index, label in enumerate(FUNCTION_LABELS):
        output[:, index] = calibrated[label]
    return output, calibrators


def _attach_calibrators(model, calibrators):
    for name, calibrator in calibrators.items():
        model.heads[name].calibration = calibrator


def _metrics(labels, probabilities, thresholds, mode):
    return score_probabilities(labels, probabilities, thresholds=thresholds, mode=mode)


def _model_size_estimate(model):
    encoder = model.encoder
    vocab_size = 0
    for vectorizer in encoder.vectorizers.values():
        vocab_size += sum(len(token.encode("utf-8")) + 8 for token in vectorizer.vocabulary_)
        vocab_size += int(vectorizer.idf_.nbytes)
    if encoder.domain_vectorizer is not None:
        vocab_size += sum(len(str(item).encode("utf-8")) + 8 for item in encoder.domain_vectorizer.feature_names_)
    weights = 0
    for head in model.heads.values():
        if isinstance(head.estimator, LogisticRegression) or head.estimator is not None:
            coef = getattr(head.estimator, "coef_", None)
            intercept = getattr(head.estimator, "intercept_", None)
            if coef is not None:
                weights += int(coef.nbytes)
            if intercept is not None:
                weights += int(intercept.nbytes)
    return int(vocab_size + weights + 2048)


def _eval_run(run_id, spec, model, dev, dev_labels, probabilities, *, training_seconds=0.0,
              thresholds=None, threshold_method="fixed_0.5", task=None, cv_details=None):
    mode = task or spec.get("task", "flat")
    threshold_list = [0.5] * len(LABEL_ORDER) if thresholds is None else list(map(float, thresholds))
    metrics = _metrics(dev_labels, probabilities, threshold_list, mode)
    start = time.perf_counter()
    for _ in range(2):
        model.predict_proba(dev)
    latency_ms = (time.perf_counter() - start) * 500.0 / max(len(dev), 1)
    versions = {
        "scikit_learn": importlib.metadata.version("scikit-learn"),
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
    }
    return {
        "run_id": run_id,
        "family": spec.get("category", "lexical_grid"),
        "model": spec.get("model", f"{spec.get('algorithm')} one-vs-rest {mode}"),
        "features": spec.get("features", spec.get("profile")),
        "task": mode,
        "training_records": spec.get("training_records"),
        "dev_records": len(dev),
        "seed": SEED,
        "hyperparameters": {k: v for k, v in spec.items() if k not in {"category", "model", "features"}},
        "class_weight": spec.get("class_weight", "none"),
        "threshold_method": threshold_method,
        "thresholds": {label: threshold_list[i] for i, label in enumerate(LABEL_ORDER)},
        "dev": metrics,
        "training_time_seconds": float(training_seconds),
        "inference_time_ms_per_record": float(latency_ms),
        "model_size_estimated_bytes": _model_size_estimate(model),
        "packages": versions,
        "cv_selection_details": cv_details,
        "artifact_key": run_id,
    }


def _fold_oof(spec, train, folds, train_labels, *, training_rows=None):
    """Generate grouped OOF raw component scores for one configuration."""
    component_scores = {key: np.zeros(len(train), dtype=np.float64) for key in _component_names(spec["task"])}
    durations = 0.0
    for train_idx, held_idx in folds:
        fit_rows = [train[i] for i in train_idx]
        if training_rows is not None:
            fit_rows = [row for row in fit_rows if training_rows(row)]
        start = time.perf_counter()
        model = _fit_model(fit_rows, spec)
        durations += time.perf_counter() - start
        raw = _raw_components(model, [train[i] for i in held_idx])
        for key, values in raw.items():
            component_scores[key][held_idx] = values
    probabilities, calibrators = _raw_to_probabilities(component_scores, train_labels, folds, spec["algorithm"], spec["task"])
    return probabilities, calibrators, durations


def _fit_final(spec, train, *, training_rows=None):
    fit_rows = list(train) if training_rows is None else [row for row in train if training_rows(row)]
    start = time.perf_counter()
    model = _fit_model(fit_rows, spec)
    return model, time.perf_counter() - start, len(fit_rows)


def _run_spec(spec, train, dev, folds, train_labels, dev_labels, *, threshold_cv=True, training_rows=None):
    run_id = _candidate_id(spec)
    model, full_seconds, fit_n = _fit_final(spec, train, training_rows=training_rows)
    spec = dict(spec, training_records=fit_n)
    dev_prob = model.predict_proba(dev)
    if threshold_cv:
        oof, calibrators, oof_seconds = _fold_oof(spec, train, folds, train_labels, training_rows=training_rows)
        _attach_calibrators(model, calibrators)
        dev_prob = model.predict_proba(dev)
        thresholds, details = oof_thresholds(train_labels, oof, mode=spec["task"])
        method = "5-fold frozen grouped TRAIN OOF; SVC Platt cross-fit when >=15 positive/negative examples; macro F1 threshold objective"
        full_seconds += oof_seconds
    else:
        oof = None
        thresholds = np.full(len(LABEL_ORDER), 0.5)
        details = None
        method = "fixed 0.5 DEV screening; not final-candidate threshold"
    entry = _eval_run(run_id, spec, model, dev, dev_labels, dev_prob,
                      training_seconds=full_seconds, thresholds=thresholds,
                      threshold_method=method, cv_details=details)
    return model, oof, dev_prob, entry, thresholds, details


def _summary_support(rows):
    return {label: int(sum(label in row["labels"] for row in rows)) for label in LABEL_ORDER}


def _hash_ids(rows):
    return hashlib.sha256("|".join(row["email_id"] for row in rows).encode()).hexdigest()


def _plain_metrics(metrics):
    return json.loads(json.dumps(metrics, allow_nan=False))


def main():
    # The shared loader accepts only TRAIN/DEV. This runner never names TEST.
    train = load_partition("train")
    dev = load_partition("dev")
    folds = cv_splits(train)
    train_labels = [row["labels"] for row in train]
    dev_labels = [row["labels"] for row in dev]
    target_matrix = targets(train)
    print(f"TRAIN={len(train)} DEV={len(dev)} benchmark={benchmark_hash()}", flush=True)
    print(f"TRAIN supports={_summary_support(train)} DEV supports={_summary_support(dev)}", flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, Any]] = {}
    models: dict[str, Any] = {}
    oof_probs: dict[str, np.ndarray] = {}
    dev_probs: dict[str, np.ndarray] = {}
    specs: dict[str, dict[str, Any]] = {}
    from joblib import dump

    def checkpoint(name):
        """Persist resumable screening outputs outside the tracked tree."""
        checkpoint_dir = OUTPUT_DIR / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / f"{name}.json").write_text(
            json.dumps({"benchmark_sha256": benchmark_hash(), "completed_runs": list(entries.values())}, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        np.savez_compressed(checkpoint_dir / f"{name}_dev_probabilities.npz", **dev_probs)
        if name.startswith("flat_"):
            profile = name[len("flat_"):]
            bundle_keys = [rid for rid in models if specs[rid].get("category") == "flat_grid" and specs[rid].get("profile") == profile]
        elif name.startswith("hierarchical_"):
            profile = name[len("hierarchical_"):]
            bundle_keys = [rid for rid in models if specs[rid].get("category") == "hierarchy_grid" and specs[rid].get("profile") == profile]
        elif name == "screened_ablation":
            bundle_keys = [rid for rid in models if specs[rid].get("category") not in {"flat_grid", "hierarchy_grid"}]
        else:
            bundle_keys = [rid for rid in models if rid in entries]
        dump({rid: models[rid] for rid in bundle_keys}, checkpoint_dir / f"{name}_models.joblib", compress=1)

    with threadpool_limits(limits=1):
        # Predeclare the exact finite lexical grid: 9 representations x 7 C x 2 estimators.
        core_specs = [
            {"task": "flat", "profile": profile, "algorithm": algorithm, "c": c,
             "text_mode": "subject_body", "use_domain": True, "class_weight": "none", "category": "flat_grid"}
            for profile in PROFILES for algorithm in ALGORITHMS for c in CS
        ]
        core_by_profile: dict[str, list[str]] = defaultdict(list)
        for profile in PROFILES:
            group = [spec for spec in core_specs if spec["profile"] == profile]
            encoder = LexicalFeatureEncoder(profile, text_mode="subject_body", use_domain=True).fit(train)
            x_train, x_dev = encoder.transform(train), encoder.transform(dev)
            for spec in group:
                run_id = _candidate_id(spec)
                start = time.perf_counter()
                model = _fit_model(train, spec, encoder=encoder)
                full_fit = time.perf_counter() - start
                probabilities = model.predict_proba_matrix(x_dev)
                entry = _eval_run(run_id, spec, model, dev, dev_labels, probabilities,
                                  training_seconds=full_fit, thresholds=[0.5] * 9,
                                  threshold_method="fixed 0.5 DEV screening; TRAIN OOF thresholds fitted on family finalists")
                entries[run_id], models[run_id], dev_probs[run_id], specs[run_id] = entry, model, probabilities, dict(spec, training_records=len(train))
                core_by_profile[profile].append(run_id)
            print(f"screened lexical profile {profile}: {len(group)} settings", flush=True)
            checkpoint(f"flat_{profile}")

        # Balanced PROJECT/NON_PROJECT hierarchy, covering the best word, char,
        # and combined feature profile chosen from the predeclared flat grid.
        family_profiles = {
            "word": PROFILES[:3], "char": PROFILES[3:6], "combined": PROFILES[6:9],
        }
        selected_profiles: list[str] = []
        for family, family_members in family_profiles.items():
            best = max((entries[rid] for profile in family_members for rid in core_by_profile[profile]),
                       key=lambda item: (item["dev"]["macro_f1"], item["dev"]["micro_f1"]))
            selected_profiles.append(best["hyperparameters"]["profile"])
        hierarchy_specs = [
            {"task": "hierarchical", "profile": profile, "algorithm": algorithm, "c": c,
             "text_mode": "subject_body", "use_domain": True, "class_weight": "none", "category": "hierarchy_grid"}
            for profile in dict.fromkeys(selected_profiles) for algorithm in ALGORITHMS for c in CS
        ]
        for profile in dict.fromkeys(selected_profiles):
            profile_specs = [spec for spec in hierarchy_specs if spec["profile"] == profile]
            for spec in profile_specs:
                run_id = _candidate_id(spec)
                model, fit_seconds, fit_n = _fit_final(spec, train)
                spec = dict(spec, training_records=fit_n)
                probability = model.predict_proba(dev)
                entry = _eval_run(run_id, spec, model, dev, dev_labels, probability,
                                  training_seconds=fit_seconds, thresholds=[0.5] * 9,
                                  threshold_method="fixed 0.5 DEV screening; selected settings receive grouped TRAIN OOF")
                entries[run_id], models[run_id], dev_probs[run_id], specs[run_id] = entry, model, probability, spec
            print(f"screened hierarchy profile {profile}: {len(profile_specs)} settings", flush=True)
            checkpoint(f"hierarchical_{profile}")

        # Domain, subject/body, and moderate positive-weight ablations on the
        # best flat DEV-screen configuration, then a high-confidence-only fit.
        best_flat_screen = max((entries[rid] for rids in core_by_profile.values() for rid in rids),
                               key=lambda item: (item["dev"]["macro_f1"], item["dev"]["micro_f1"]))
        best_spec = specs[best_flat_screen["run_id"]]
        fixed_ablation_specs = [
            dict(best_spec, text_mode="subject_only", category="subject_body_ablation"),
            dict(best_spec, text_mode="body_only", category="subject_body_ablation"),
            dict(best_spec, use_domain=False, category="structured_feature_ablation"),
            dict(best_spec, class_weight="sqrt", weight_cap=3.0, category="moderate_weight_ablation"),
            dict(best_spec, class_weight="sqrt", weight_cap=5.0, category="moderate_weight_ablation"),
            dict(best_spec, class_weight="sqrt", weight_cap=8.0, category="moderate_weight_ablation"),
        ]
        for spec in fixed_ablation_specs:
            run_id = _candidate_id(spec)
            model, fit_seconds, fit_n = _fit_final(spec, train)
            spec = dict(spec, training_records=fit_n)
            probability = model.predict_proba(dev)
            entry = _eval_run(run_id, spec, model, dev, dev_labels, probability,
                              training_seconds=fit_seconds, thresholds=[0.5] * 9,
                              threshold_method="fixed 0.5 DEV screening; selected ablations receive TRAIN OOF thresholds")
            entries[run_id], models[run_id], dev_probs[run_id], specs[run_id] = entry, model, probability, spec

        # This is an acceptance-rule proxy only. It does not assign numeric
        # audit confidence or imply that direct supervisor audits are weaker.
        exact_agreement_ids = {
            row["email_id"] for row in train
            if row.get("snapshot_provenance", {}).get("acceptance_rule") in EXACT_AGREEMENT_RULES
        }
        exact_only_spec = dict(best_spec, training_subset="exact_agreement_acceptance_rule_proxy", category="acceptance_rule_proxy_ablation")
        exact_id = _candidate_id(exact_only_spec)
        exact_model, exact_seconds, exact_n = _fit_final(exact_only_spec, train, training_rows=lambda row: row["email_id"] in exact_agreement_ids)
        exact_only_spec = dict(exact_only_spec, training_records=exact_n)
        exact_prob = exact_model.predict_proba(dev)
        entries[exact_id] = _eval_run(exact_id, exact_only_spec, exact_model, dev, dev_labels, exact_prob,
                                      training_seconds=exact_seconds, thresholds=[0.5] * 9,
                                      threshold_method="fixed 0.5 DEV screening; exact-agreement acceptance-rule proxy subset")
        models[exact_id], dev_probs[exact_id], specs[exact_id] = exact_model, exact_prob, exact_only_spec

        checkpoint("screened_ablation")

        # TRAIN/DEV screening selects a compact set for grouped OOF threshold
        # tuning. Include the best flat setting of each representation family,
        # per-label DEV winners, best hierarchy per family, and ablations.
        selected_oof_ids: set[str] = set()
        for family_members in family_profiles.values():
            best = max((entries[rid] for profile in family_members for rid in core_by_profile[profile]),
                       key=lambda item: (item["dev"]["macro_f1"], item["dev"]["micro_f1"]))
            selected_oof_ids.add(best["run_id"])
            selected_profile = best["hyperparameters"]["profile"]
            # Prespecified word/char/combined C=1 and C=4 anchors each receive
            # grouped TRAIN OOF thresholds, making feature comparisons aligned.
            for algorithm in ALGORITHMS:
                for c in (1.0, 4.0):
                    anchored = next(rid for rid in core_by_profile[selected_profile]
                                    if specs[rid]["algorithm"] == algorithm and specs[rid]["c"] == c)
                    selected_oof_ids.add(anchored)
        for label in LABEL_ORDER:
            best = max((entry for rid, entry in entries.items() if rid in models and specs[rid].get("task") == "flat" and not specs[rid].get("legacy") and specs[rid].get("training_subset", "all") == "all" and specs[rid].get("category") == "flat_grid"),
                       key=lambda item: (item["dev"]["per_label"][label]["f1"], item["dev"]["per_label"][label]["recall"], item["dev"]["per_label"][label]["precision"]))
            selected_oof_ids.add(best["run_id"])
        for family_members in family_profiles.values():
            family_hier = [entry for entry in entries.values() if entry.get("task") == "hierarchical" and specs[entry["run_id"]]["profile"] in family_members]
            if family_hier:
                selected_oof_ids.add(max(family_hier, key=lambda item: (item["dev"]["macro_f1"], item["dev"]["micro_f1"]))["run_id"])
        for category in ("subject_body_ablation", "structured_feature_ablation", "moderate_weight_ablation", "acceptance_rule_proxy_ablation"):
            variants = [rid for rid in models if specs[rid].get("category") == category]
            if category in {"subject_body_ablation", "moderate_weight_ablation"}:
                selected_oof_ids.update(variants)
            elif variants:
                selected_oof_ids.add(max(variants, key=lambda rid: (entries[rid]["dev"]["macro_f1"], entries[rid]["dev"]["micro_f1"])))

        # Produce grouped OOF arrays for each selected config. Every fold
        # vectorizer and classifier sees TRAIN rows outside that fold only.
        for run_id in sorted(selected_oof_ids):
            if run_id in oof_probs:
                continue
            spec = specs[run_id]
            is_exact_subset = spec.get("training_subset") == "exact_agreement_acceptance_rule_proxy"
            selector = (lambda row: row["email_id"] in exact_agreement_ids) if is_exact_subset else None
            oof, calibrators, cv_seconds = _fold_oof(spec, train, folds, train_labels, training_rows=selector)
            _attach_calibrators(models[run_id], calibrators)
            oof_probs[run_id] = oof
            thresholds, details = oof_thresholds(train_labels, oof, mode=spec["task"])
            models[run_id].thresholds = {label: float(thresholds[i]) for i, label in enumerate(LABEL_ORDER)}
            models[run_id].metadata.update({
                "decode_mode": spec["task"], "fallback": False,
                "threshold_method": "5-fold frozen grouped TRAIN OOF",
                "thresholds": models[run_id].thresholds,
                "threshold_details": details,
            })
            dev_probs[run_id] = models[run_id].predict_proba(dev)
            entry = _eval_run(run_id, spec, models[run_id], dev, dev_labels, dev_probs[run_id],
                              training_seconds=entries[run_id]["training_time_seconds"] + cv_seconds,
                              thresholds=thresholds,
                              threshold_method="5-fold frozen grouped TRAIN OOF; SVC Platt cross-fit when >=15 positive/negative examples; macro F1 threshold objective",
                              task=spec["task"], cv_details=details)
            entries[run_id] = entry
            print(f"OOF thresholds complete: {run_id} (DEV macro={entry['dev']['macro_f1']:.4f})", flush=True)

        # Label-specific specialists choose each head from the predeclared full
        # flat DEV grid, then use that head's own TRAIN OOF threshold.
        specialist_sources: dict[str, str] = {}
        for label in LABEL_ORDER:
            candidates = [rid for rid in entries if rid in models and specs[rid].get("category") == "flat_grid" and rid in oof_probs]
            specialist_sources[label] = max(
                candidates,
                key=lambda rid: (entries[rid]["dev"]["per_label"][label]["f1"],
                                 entries[rid]["dev"]["per_label"][label]["recall"],
                                 entries[rid]["dev"]["per_label"][label]["precision"]),
            )
        specialist_keys = sorted(set(specialist_sources.values()))
        specialist_models = {rid: models[rid] for rid in specialist_keys}
        specialist_thresholds = {label: entries[rid]["thresholds"][label] for label, rid in specialist_sources.items()}
        specialists = LexicalSpecialistBundle(specialist_models, specialist_sources, specialist_thresholds,
                                              metadata={"seed": SEED, "selection": "per-label DEV F1 from the 126-run flat grid; TRAIN OOF threshold per source"})
        specialist_id = "per_label_lexical_specialists_oof_thresholds"
        specialist_oof = np.zeros((len(train), 9), dtype=np.float64)
        specialist_dev = np.zeros((len(dev), 9), dtype=np.float64)
        for label_index, label in enumerate(LABEL_ORDER):
            source = specialist_sources[label]
            source_col = LABEL_ORDER.index(label)
            specialist_oof[:, label_index] = oof_probs[source][:, source_col]
            specialist_dev[:, label_index] = dev_probs[source][:, source_col]
        specialist_metrics = _metrics(dev_labels, specialist_dev, [specialist_thresholds[l] for l in LABEL_ORDER], "flat")
        entries[specialist_id] = {
            "run_id": specialist_id, "family": "per_label_specialists", "model": "Independent label-specific lexical estimators",
            "features": "per-label selection from full word/char/combo TF-IDF registry; structured domain features",
            "task": "flat", "training_records": len(train), "dev_records": len(dev), "seed": SEED,
            "hyperparameters": {"source_run_by_label": specialist_sources}, "class_weight": "per-source setting",
            "threshold_method": "each chosen source model's 5-fold grouped TRAIN OOF threshold",
            "thresholds": specialist_thresholds, "dev": specialist_metrics,
            "training_time_seconds": float(sum(entries[rid]["training_time_seconds"] for rid in specialist_keys)),
            "inference_time_ms_per_record": None, "model_size_estimated_bytes": int(sum(entries[rid]["model_size_estimated_bytes"] for rid in specialist_keys)),
            "packages": {"scikit_learn": importlib.metadata.version("scikit-learn")}, "cv_selection_details": None,
            "artifact_key": specialist_id,
        }
        models[specialist_id], oof_probs[specialist_id], dev_probs[specialist_id] = specialists, specialist_oof, specialist_dev
        specs[specialist_id] = {"task": "flat", "category": "per_label_specialists", "training_records": len(train)}

        # TRAIN-only second stage learns label dependencies from grouped OOF
        # base probabilities. Its own OOF meta predictions are cross-fitted.
        best_flat_final_id = max(
            (rid for rid in selected_oof_ids if specs[rid].get("task") == "flat" and not specs[rid].get("legacy") and specs[rid].get("category") == "flat_grid"),
            key=lambda rid: (entries[rid]["dev"]["macro_f1"], entries[rid]["dev"]["micro_f1"]),
        )
        base_oof, base_dev = oof_probs[best_flat_final_id], dev_probs[best_flat_final_id]
        dependency_candidates = []
        for c in (0.1, 0.5, 1.0, 2.0):
            meta_oof = np.zeros_like(base_oof)
            for train_idx, held_idx in folds:
                meta = LabelDependencyModel(c).fit(base_oof[train_idx], target_matrix[train_idx])
                meta_oof[held_idx] = meta.predict_proba(base_oof[held_idx])
            meta_full = LabelDependencyModel(c).fit(base_oof, target_matrix)
            thresholds, detail = oof_thresholds(train_labels, meta_oof, mode="flat")
            meta_dev = meta_full.predict_proba(base_dev)
            met = _metrics(dev_labels, meta_dev, thresholds, "flat")
            dependency_candidates.append((met["macro_f1"], met["micro_f1"], c, meta_oof, meta_dev, meta_full, thresholds, detail))
        _, _, dep_c, dep_oof, dep_dev, dep_model, dep_thresholds, dep_details = max(dependency_candidates, key=lambda item: (item[0], item[1]))
        dependency = LexicalDependencyBundle(models[best_flat_final_id], dep_model,
                                             {label: float(dep_thresholds[i]) for i, label in enumerate(LABEL_ORDER)},
                                             metadata={"base_run_id": best_flat_final_id, "C": dep_c,
                                                       "training_features": "base-model TRAIN OOF Nx9 probabilities", "seed": SEED})
        dependency_id = "train_oof_label_dependency_correction"
        dep_metrics = _metrics(dev_labels, dep_dev, dep_thresholds, "flat")
        entries[dependency_id] = {
            "run_id": dependency_id, "family": "label_dependency", "model": "Base lexical classifier + second-stage OVR logistic regression",
            "features": "strictly grouped-OOF base probabilities (Nx9)", "task": "flat", "training_records": len(train),
            "dev_records": len(dev), "seed": SEED, "hyperparameters": {"base_run_id": best_flat_final_id, "C": dep_c},
            "class_weight": "none", "threshold_method": "5-fold meta-model OOF from base TRAIN OOF probabilities",
            "thresholds": {label: float(dep_thresholds[i]) for i, label in enumerate(LABEL_ORDER)}, "dev": dep_metrics,
            "training_time_seconds": 0.0, "inference_time_ms_per_record": None,
            "model_size_estimated_bytes": int(entries[best_flat_final_id]["model_size_estimated_bytes"] + sum(getattr(h.estimator, "coef_", np.zeros((1, 9))).nbytes for h in dep_model.heads.values())),
            "packages": {"scikit_learn": importlib.metadata.version("scikit-learn")}, "cv_selection_details": dep_details,
            "artifact_key": dependency_id,
        }
        models[dependency_id], oof_probs[dependency_id], dev_probs[dependency_id] = dependency, dep_oof, dep_dev
        specs[dependency_id] = {"task": "flat", "category": "label_dependency", "training_records": len(train)}
        print(f"label dependency C={dep_c:g}: DEV macro={dep_metrics['macro_f1']:.4f}", flush=True)

    # Final family finalists are selected only from TRAIN/DEV. The root-owned
    # evaluator may later inspect no more than this set on the sealed TEST.
    best_flat_id = max((rid for rid in selected_oof_ids if specs[rid].get("task") == "flat" and specs[rid].get("category") == "flat_grid"),
                       key=lambda rid: (entries[rid]["dev"]["macro_f1"], entries[rid]["dev"]["micro_f1"]))
    best_hier_id = max((rid for rid in selected_oof_ids if specs[rid].get("task") == "hierarchical"),
                       key=lambda rid: (entries[rid]["dev"]["macro_f1"], entries[rid]["dev"]["micro_f1"]))
    best_ablation_id = max((rid for rid in selected_oof_ids if specs[rid].get("category") in {"subject_body_ablation", "structured_feature_ablation", "moderate_weight_ablation", "acceptance_rule_proxy_ablation"}),
                           key=lambda rid: (entries[rid]["dev"]["macro_f1"], entries[rid]["dev"]["micro_f1"]))
    final_ids = [best_flat_id, best_hier_id, specialist_id,
                 max((dependency_id, best_ablation_id), key=lambda rid: (entries[rid]["dev"]["macro_f1"], entries[rid]["dev"]["micro_f1"]))]
    final_ids = list(dict.fromkeys(final_ids))

    # Main report contains no email text. OOF/dev probability arrays and model
    # bundles are ignored artifacts under the approved experiment directories.
    for candidate_id in final_ids:
        artifact_path = MODEL_DIR / f"{candidate_id}.joblib"
        candidate = models[candidate_id]
        candidate_thresholds = entries[candidate_id]["thresholds"]
        candidate_mode = entries[candidate_id]["task"]
        candidate.thresholds = candidate_thresholds
        candidate.decode_mode = candidate_mode
        candidate.fallback = False
        if hasattr(candidate, "metadata"):
            candidate.metadata.update({
                "run_id": candidate_id, "decode_mode": candidate_mode, "fallback": False,
                "thresholds": candidate_thresholds, "threshold_method": entries[candidate_id]["threshold_method"],
                "metric_provenance": "AI-SILVER DIAGNOSTIC PERFORMANCE",
            })
        dump(models[candidate_id], artifact_path, compress=3)
        entries[candidate_id]["model_artifact"] = str(artifact_path.relative_to(AI))
        entries[candidate_id]["model_size_bytes"] = artifact_path.stat().st_size
        entries[candidate_id]["final_test_candidate"] = True
    for candidate_id in entries:
        entries[candidate_id].setdefault("final_test_candidate", False)

    np.savez_compressed(OUTPUT_DIR / "dev_probabilities.npz", **{rid: arr for rid, arr in dev_probs.items()})
    np.savez_compressed(OUTPUT_DIR / "train_oof_probabilities.npz", **{rid: arr for rid, arr in oof_probs.items()})
    prediction_meta = {
        "benchmark_sha256": benchmark_hash(),
        "train_membership_sha256": _hash_ids(train), "dev_membership_sha256": _hash_ids(dev),
        "train_email_ids": [row["email_id"] for row in train], "dev_email_ids": [row["email_id"] for row in dev],
        "train_oof_run_ids": sorted(oof_probs), "dev_run_ids": sorted(dev_probs),
        "probability_columns": list(LABEL_ORDER), "test_data_loaded": False,
    }
    (OUTPUT_DIR / "prediction_manifest.json").write_text(json.dumps(prediction_meta, indent=2) + "\n", encoding="utf-8")
    registry = {
        "title": "AI-SILVER DIAGNOSTIC PERFORMANCE — lexical optimization experiments",
        "metric_provenance": "AI-SILVER DIAGNOSTIC PERFORMANCE; no human or gold labels",
        "benchmark_sha256": benchmark_hash(), "seed": SEED,
        "partitions": {"train": len(train), "dev": len(dev), "test": 102,
                       "train_support": _summary_support(train), "dev_support": _summary_support(dev),
                       "train_membership_sha256": _hash_ids(train), "dev_membership_sha256": _hash_ids(dev)},
        "acceptance_rule_ablation": {
            "proxy_rule": sorted(EXACT_AGREEMENT_RULES), "train_proxy_count": len(exact_agreement_ids),
            "train_all_count": len(train),
            "interpretation": "acceptance-rule proxy only; no numeric audit confidence assigned, and direct supervisor audit is not claimed to be lower quality",
            "train_acceptance_rule_support": dict(Counter(r["snapshot_provenance"]["acceptance_rule"] for r in train)),
            "dev_acceptance_rule_support": dict(Counter(r["snapshot_provenance"]["acceptance_rule"] for r in dev)),
        },
        "selection": {"primary": "DEV macro F1", "secondary": "DEV micro F1",
                      "test_access": "none in lexical runner; test candidate list exported for root evaluator",
                      "final_test_candidate_ids": final_ids,
                      "legacy_baseline_reference": "ai/reports/optimization_reference.json; root fitted original word unigram/bigram TF-IDF C=1 with grouped TRAIN OOF thresholds",
                      "grid": {"profiles": list(PROFILES), "algorithms": list(ALGORITHMS), "C": list(CS),
                               "flat_grid_runs": len(core_specs), "hierarchy_runs": len(hierarchy_specs)}},
        "test_metrics": None,
        "runs": list(entries.values()),
        "artifacts": {"dev_probabilities": str((OUTPUT_DIR / "dev_probabilities.npz").relative_to(AI)),
                      "train_oof_probabilities": str((OUTPUT_DIR / "train_oof_probabilities.npz").relative_to(AI)),
                      "prediction_manifest": str((OUTPUT_DIR / "prediction_manifest.json").relative_to(AI))},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(registry, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "runs": len(entries), "final_test_candidate_ids": final_ids,
        "finalists": [{"run_id": rid, "dev_macro_f1": entries[rid]["dev"]["macro_f1"],
                       "dev_micro_f1": entries[rid]["dev"]["micro_f1"]} for rid in final_ids],
        "registry": str(REPORT), "artifacts": str(OUTPUT_DIR),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()

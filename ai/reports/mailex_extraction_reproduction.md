# Reviewing and reproducing the native extraction benchmark

Run commands from the repository root in PowerShell. Read
[the current handoff](mailex_extraction_reviewer_status.md) first: progress
reports are not a final selection or a TEST result.

## Public evidence

The repository includes native conversion, both extractors, the independent
evaluator, numeric learning curves, DEV calibration grids, aggregate metrics,
checkpoint hashes, source audits and measured runtime. The source-bearing
JSONL files, full private reviews, corpus identifiers, weights and downloaded
dependency runtimes remain local under ignored `ai/data/` paths.

The corpus archive and model revisions are identified in
[the native audit](mailex_native_extraction_audit.md),
[the compact report](mailex_extraction_baseline.md) and
[the GLiNER report](mailex_extraction_training.md). The named FYP-safe view
also requires the private protected-boundary manifest and leakage index.
A public checkout alone cannot reconstruct that private boundary.

## Independent checks

With the documented Python environment available:

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '4'
$env:PYTHONPATH = 'ai'
& ai/.venv/Scripts/python.exe -m unittest ai/tests/test_mailex_native.py ai/tests/test_mailex_extraction_metrics.py ai/tests/test_mailex_gliner_predictor_gates.py
```

These synthetic checks do not require source emails or model inference.
Use `--help` on preparation scripts for the native conversion and FYP-safe
exclusion parameters. Reproduction must use new output directories rather
than overwrite preserved experiment artifacts.

## Compact fit and DEV calibration

The retained recipe is illustrated below with a new reproduction directory.
The same recipe is used for seeds 17, 23 and 41; each is fitted independently.

```powershell
& ai/.venv/Scripts/python.exe ai/scripts/run_mailex_compact.py --train ai/data/experiments/mailex_extraction_v1/train_fyp_safe.jsonl --dev ai/data/experiments/mailex_extraction_v1/dev_fyp_safe.jsonl --encoder ai/data/cache/distilbert-base-uncased --output ai/data/experiments/mailex_extraction_reproduction_seed17 --epochs 8 --patience 2 --lr 2e-5 --head-lr 1e-3 --batch-size 8 --seed 17
& ai/.venv/Scripts/python.exe ai/scripts/calibrate_mailex_compact.py --input ai/data/experiments/mailex_extraction_v1/dev_fyp_safe.jsonl --checkpoint ai/data/experiments/mailex_extraction_reproduction_seed17 --output ai/data/experiments/mailex_extraction_reproduction_seed17/calibration
```

The calibration script declares its four thresholds before execution. The
independent evaluator can score saved DEV predictions without loading a model:

```powershell
& ai/.venv/Scripts/python.exe ai/scripts/evaluate_mailex_extraction.py --gold ai/data/experiments/mailex_extraction_v1/dev_fyp_safe.jsonl --predictions ai/data/experiments/mailex_extraction_reproduction_seed17/calibration/dev_threshold_0.7.jsonl --split dev --output ai/data/experiments/mailex_extraction_reproduction_seed17/independent_dev_metrics.json
```

## GLiNER implementation

The runner uses the pinned local `gliner2==2.0.0` boundary implementation and
`fastino/gliner2.5-small-v1` revision from its report. It verifies TRAIN/DEV
fingerprints, builds seven measured schema packs, and uses explicit native
offsets for training. Inspect `run_mailex_gliner.py` for the actual bounded
recipe and fresh output namespace before reproducing a fit.

`predict_mailex_gliner.py` accepts the frozen TRAIN ontology JSON, a saved
checkpoint, explicit split/device/threshold and a new prediction output path.
All model-emitted spans are checked against their original source slices.
The independent evaluator uses the complete native gold view rather than the
smaller representable trainer-validation view.

## TEST protocol

**The actual two-finalist TEST is complete and closed.** The source-free lock
was committed and pushed as `f6b4bde` before inference. Aggregate metrics and
receipts are linked in [the final report](mailex_extraction_final.md).

The enforced protocol first commits the source-free selection lock with
weight, schema, code, preprocessing,
evaluator and threshold hashes. Both inference CLIs then require that lock
and its exact finalist identifier, input and output paths. An exclusive
private reservation is created before TEST rows are parsed. The evaluator
creates a separate one-time receipt with the saved prediction hash.

The completed result exporter `ai/scripts/export_mailex_extraction_test_results.py`
checks saved receipt/metric equality, gold/prediction byte hashes and the
pre-TEST committed lock. It republishes numerical aggregates without decoding
source rows, inference or rescoring. Re-exporting these receipts is safe;
re-evaluating TEST is not part of reproduction.

Review the committed lock and aggregate receipts. Do not
rerun TEST to reproduce a number, recalibrate thresholds from it, or use the
closed V1 TEST/protected V2 sources for this benchmark.

# AI email dataset foundation

## Active workstream — 4 October 2026

[Native MailEx extraction reviewer handoff](reports/mailex_extraction_reviewer_status.md)
is the entry point for the current benchmark: actual compact training and DEV
results, GLiNER Small fitting status, native ontology/evaluator, error audits,
runtime measurements, and the outstanding committed selection/TEST gate.
This sprint preserves the historical classifier and V2 artifacts below.
The progress checkpoint is not a final model selection or TEST result.

This directory prepares English Outlook-style project emails for a future multi-label classifier and information extractor. V1 uses subject, body, thread context, Outlook metadata, and attachment filenames. It does not read attachment contents. The 22-page *FYP Proposal Report* controls this V1 scope; the 10-page revised proposal describes later attachment extraction.

## Current measured prototype — 2 October 2026

[Completed model optimization and measured results](reports/ai_silver_model_optimization.md): **668 AI-silver records**, frozen TRAIN/DEV/TEST **462/104/102**, 293 recorded development configurations/calibration stages, five locked candidates evaluated once, and all 46 primary-model errors source-read. On the same TEST, the DEV-selected ensemble scores **0.652 micro / 0.412 macro F1**, versus the freshly trained original TF-IDF reference **0.698 / 0.403**. The requested large improvement was not achieved. There are **zero human classification labels**; these are AI-silver diagnostic results. Model selection, thresholds and TEST labels remain frozen.

The saved local ensemble runs on JSONL emails containing `email_id`, `subject` and `body` (or `current_message`/`authored_message`):

```powershell
ai\.venv\Scripts\python.exe ai\scripts\predict_optimization_classifier.py --input emails.jsonl --output predictions.jsonl
```

The inference CLI has been smoke-checked against its saved bundle. Predictions are a diagnostic prototype; scores are not calibrated confidence. Full email data and model/encoder bundles stay local under ignored `ai/data/**`; a fresh clone requires those local artifacts. The [experiment registry](reports/optimization_experiment_registry.json) and [final metrics](reports/optimization_final_test.json) preserve the measured evidence. This TEST has now been inspected; another optimization cycle needs a new independent test.

### Historical experiment and deferred human calibration

[Earlier audit and TF-IDF/DistilBERT comparison](reports/tonight_training_comparison.md): 674 frozen AI-silver records; fit/tuning/validation 426/110/138; 50 source-read transformer errors; 180-row calibration queue. Its scores are from a different split and are not comparable head-to-head with the completed sprint. Six uncertain references were excluded in the [668-row next-training manifest](annotation/tonight_next_training_manifest.jsonl). Human annotation remains deferred at the user's request. When it is resumed, launch the prepared queue from the repository root:

```powershell
ai\.venv\Scripts\python.exe ai\annotation\simple_annotator\app.py --reviewer faaiz --seed-path ai\data\annotated\human\transfer_calibration\canonical_seed.jsonl --output-dir ai\data\annotated\human\transfer_calibration\reviewers
```

This queue reuses training/tuning records plus excluded sources and is not independent gold. The trained transformer checkpoints and full email data stay local under ignored `ai/data/**`.

## Canonical JSONL

Each line is one email with source-qualified `email_id`, `thread_id`, `turn_index`, `subject`, preserved `raw_body`, derived `current_message` and `clean_body`, `thread_context`, metadata (`sender`, `recipients`, `cc`, `sent_at`, `attachment_names`), independent `labels`, exact `spans`, and `annotation` status. Span `start` is inclusive and `end` exclusive in `current_message`, or `subject` when `field` says so. Empty labels on an unlabelled record mean unknown. Human-reviewed unrelated mail uses `NON_PROJECT`. MailEx `raw_body` is reconstructed from official annotation tokens because its JSON does not contain the original RFC822 body; the downloaded archive itself is preserved unchanged.

The nine classification labels are MEETING, DEADLINE, REPORT_REQUEST, DEPARTMENTAL_INPUT, ACTION_REQUEST, FOLLOW_UP, APPROVAL, GENERAL_UPDATE, and NON_PROJECT. The eleventh extraction type is DEADLINE_TIME. All project labels may co-occur; NON_PROJECT stands alone. See [annotation guidelines](annotation/annotation_guidelines.md) and [schema decisions](reports/schema_decisions.md) for operational decisions. Source datasets do not automatically supply gold FYP classification labels. AI prelabels are review candidates only.

## Run

Use Python 3.10+ from the repository root:

```powershell
python -m unittest discover -s ai/tests -t ai -v
python ai/scripts/prepare_mailex.py
python ai/scripts/prepare_enron.py --maildir ai/data/raw/enron/full/maildir --output ai/data/interim/enron_full.jsonl
python ai/scripts/create_candidate_pool.py --input ai/data/interim/enron_full.jsonl --output ai/data/interim/enron_candidates.jsonl --secondary-thread-links --thread-mode whole
python ai/scripts/validate_dataset.py ai/data/processed/mailex.jsonl
# Current AI-only pilot: compare two independent local prelabel files:
ai/.venv/Scripts/python.exe ai/scripts/compare_ai_pilot.py --reviewer-a ai/data/annotated/ai/project_pilot_50/reviewer_a.jsonl --reviewer-b ai/data/annotated/ai/project_pilot_50/reviewer_b.jsonl --report ai/reports/ai_pilot_agreement.json
# Second blind AI pilot, using a separate seed and reviewer files:
ai/.venv/Scripts/python.exe ai/scripts/build_project_pilot_v2.py
ai/.venv/Scripts/python.exe ai/scripts/compare_ai_pilot.py --pilot-seed ai/data/annotated/ai/project_pilot_50_v2/annotation_seed_50.jsonl --reviewer-a ai/data/annotated/ai/project_pilot_50_v2/reviewers/reviewer_a.jsonl --reviewer-b ai/data/annotated/ai/project_pilot_50_v2/reviewers/reviewer_b.jsonl --report ai/reports/ai_pilot_v2_agreement.json --disagreements ai/data/annotated/ai_reviewed/project_pilot_50_v2/disagreements.jsonl
# Build the directly audited, classification-only AI silver batch:
ai/.venv/Scripts/python.exe ai/scripts/build_ai_silver_classification.py
# When human-reviewed records become available later:
python ai/scripts/create_splits.py ai/data/annotated/human/reviewed.jsonl
```

MailEx defaults to the extracted official release under `ai/data/raw/mailex/extracted/data/full_data`. The full CMU Enron archive has been downloaded and extracted under `ai/data/raw/enron/full/maildir`; the completed run and current pool are measured in [dataset progress](reports/dataset_progress.md). Source provenance is in [MailEx source](reports/mailex_source.md) and [Enron source](data/raw/enron/README.md). Raw downloaded data and generated JSONL under `ai/data/` are ignored by Git. Keep original input files unchanged. Validate records before splitting. Splits group all messages from a source-qualified thread; synthetic records are restricted to training and never become gold.

## Workflow

1. Obtain MailEx and Enron from the documented sources and retain their raw files.
2. Run preparation scripts to create canonical, initially unlabelled records and source-specific extraction proposals where justified.
3. Select project candidates and random negatives for independent human annotation. Keyword selection is only for sampling.
4. Review a 200–300 email seed with two annotators where feasible. Resolve disagreements and freeze guidelines.
5. Build a real, human-reviewed 300–500 email gold test set, isolated by thread, before reporting model accuracy or deployment readiness. AI-only prototypes may be built from the silver batch but must not be evaluated as if it were gold.

The two AI-only pilots and their limits are in the [first review](reports/ai_pilot_review.md) and [second review](reports/ai_pilot_v2_review.md). The [direct audit](reports/ai_pilot_v2_correctness_audit.md), [silver-batch report](reports/ai_silver_classification.md), and [v3 protocol](annotation/ai_review_protocol_v3.md) document the corrected classification-only prototype set. Human annotation is deferred; when resumed, use the [simple local annotator](annotation/simple_annotator/README.md). Label Studio remains an alternative. See [dataset progress](reports/dataset_progress.md) for executed counts and current limitations.

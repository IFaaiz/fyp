# Reviewer handoff: completed native MailEx extraction benchmark

**Completed 5 October 2026, Asia/Karachi. Start with [the final report](mailex_extraction_final.md).**

## Decision and measured result

Decision **D**: neither tested extractor is sufficiently reliable for unattended
Outlook extraction. The compact baseline wins this comparison. Next candidate:
one shared compact encoder, explicit span candidates, and event-conditioned
multi-label argument role/link scoring. That replacement is not trained yet.

| Locked finalist | DEV exact role F1 | TEST exact role F1 | TEST partial record F1 | TEST exact record F1 | CPU 39-word email |
|---|---:|---:|---:|---:|---:|
| Compact seed 23, epoch 8, threshold 0.7 | 0.345117 | 0.339138 | 0.472232 | 0.199578 | 25.5 ms |
| GLiNER Small seed 42, epoch 3, threshold 0.2 | 0.223518 | 0.231894 | 0.186966 | 0.035132 | 828.4 ms |

Zero-shot Small has zero DEV argument/record F1 and no TEST run. Base was not
trained because fine-tuned Small clearly loses on native DEV role/record quality.
Three completed compact seeds have DEV role F1 mean 0.341117, sample SD 0.003487.
Selected compact DEV gold-type-plus-trigger oracle role F1 is 0.461000.
There is no ensemble, production-readiness claim or FYP schema adaptation.

## What to review first

1. [Final quality/runtime tables, decision and limitations](mailex_extraction_final.md).
2. [Native ontology, malformed-case and duplicate audit](mailex_native_extraction_audit.md).
3. [Independent matching/evaluation rules](mailex_extraction_evaluator.md).
4. [Actual compact fitting and oracles](mailex_extraction_baseline.md),
   [seed robustness](mailex_extraction_compact_seeds.md), and
   [paired subject ablation](mailex_subject_ablation.md).
5. [GLiNER strict zero-shot](mailex_extraction_zero_shot.md),
   [actual fitting/configuration and known representation limits](mailex_extraction_training.md),
   and [independently scored DEV thresholds](mailex_extraction_gliner_dev_metrics.md).
6. [Supervisor source-level DEV audits](mailex_extraction_error_analysis.md).
7. [Selected-checkpoint CPU/GPU runtime](mailex_extraction_runtime.md).
8. [Reproduction and private artifact requirements](mailex_extraction_reproduction.md).

## TEST chronology and receipts

The source-free [finalist lock](../config/mailex_extraction_selection_lock.json)
was committed and pushed as **f6b4bde before either TEST inference**. It fixes
architecture, weights, schemas, thresholds, evaluator, preprocessing, decoding,
encoder/tokenizer artifacts and code. Root personally validated all hashes and
HEAD bytes, then ran each finalist once and scored its saved predictions once.

[Compact aggregate receipt](mailex_extraction_results/compact_selected_test.receipt.json)
and [GLiNER aggregate receipt](mailex_extraction_results/gliner_small_selected_test.receipt.json)
contain the lock/gold/prediction hashes and complete aggregate scores. No private
reservation paths, email text, source IDs or prediction rows are exported.
TEST is now closed. Do not rerun it, tune thresholds against it or infer on
old V1 TEST/protected V2 records. Public aggregates may be checked directly.

## Evidence and preservation

The supervisor personally reviewed 100 usable TRAIN conversions, 100 seed-17
DEV error cases and 100 selected seed-23 DEV error cases from 80 messages,
plus targeted GLiNER full-source probes at both DEV thresholds. Native gold
was not relabeled. An independent Luna subagent verified DEV scores and
ran 31 synthetic native/evaluator/predictor-gate tests; all passed.

Final byte checks preserved **77 closed V1 files and 231 snapshotted V2 files**,
zero changed or missing. Starting preserved HEAD:
`e3fe3c88476d942b72e85708be0b394b3c8ced4d`. Historical failures, incomplete
attempts, old zero-shot output and earlier measurements remain retained.

## Data and reproducibility boundaries

Official source: 1,200/150/150 threads; 3,117/414/405 messages; 11 native event
types, 25 case-sensitive roles. Faithful native conversion has 18,149 argument
runs, correcting 50 runs previously lost by case folding.

The named FYP-safe subset uses 1,061/131/135 threads, 2,762/361/363 messages
and 5,729/828/772 events. Known protected FYP matches and connected leakage
components are excluded by whole thread. Official cross-split duplicates
remain documented. These are not untouched official MailEx scores or proof
of complete original Enron identity separation. Native labels are not a
complete FYP project-management ontology.

GitHub contains code, native schema, actual sanitized fit configs, environment
versions, aggregates and hashes. The [compact results index](mailex_extraction_results/compact_runs.json)
links completed grids, configs and numeric training curves. GLiNER's saved
checkpoint is real; its post-fit serialization failure lost returned histories,
which were not invented. Its representability/overlap-supervision limitations
and different checkpoint selection criterion are disclosed.

Raw emails, source-bearing predictions/IDs, full reviews, private FYP boundary
metadata, dependency runtimes and weights remain local under ignored ai/data.
A fresh clone cannot reconstruct that private boundary or checkpoints by itself.
The source-free TEST exporter verifies committed lock/artifact hashes and
receipt equality without inference, rescoring or decoding source rows.

## Implementation review targets

Inspect native conversion, shared compact encoder/BIO decoder, GLiNER native
processor/backend, and independent event-instance metrics in ai/src. Check
role case/qualifiers, exact source offsets, deterministic one-to-one matching,
full-input coverage and one-time TEST gates. Configured subagents use only
GPT-6 Luna with xhigh reasoning; responsibilities and native-source reviews
were delegated under the user's authorization.

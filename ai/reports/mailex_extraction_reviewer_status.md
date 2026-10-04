# Reviewer handoff: native MailEx extraction bake-off

**Progress checkpoint: 2026-10-04, Asia/Karachi. This is not a final selection or TEST result.**

## What changed

The active task is native event/argument extraction for the Outlook FYP.
The nine-label classifier and structured V2 work are preserved. The starting
commit was `e3fe3c88476d942b72e85708be0b394b3c8ced4d`. The supervisor verified
77 closed V1 files and 231 snapshotted V2 files: zero changed/missing, with no
closed-experiment inference. The old V1 TEST and protected V2 source text are
not used in this bake-off.

Read these first:

1. [Benchmark scope and preservation](mailex_extraction_benchmark.md).
2. [Native data/ontology audit](mailex_native_extraction_audit.md).
3. [Independent evaluator rules](mailex_extraction_evaluator.md).
4. [Actual compact fitting and oracle results](mailex_extraction_baseline.md).
5. [Paired subject ablation](mailex_subject_ablation.md).
6. [Source-level DEV error analysis](mailex_extraction_error_analysis.md).
7. [Compact seed robustness](mailex_extraction_compact_seeds.md).
8. [GLiNER zero-shot evidence](mailex_extraction_zero_shot.md) and
   [fine-tuning status](mailex_extraction_training.md).
9. [Measured runtime](mailex_extraction_runtime.md).
10. [Review and reproduction commands](mailex_extraction_reproduction.md).

Machine-readable aggregate compact configs, metrics, calibration results and
weight hashes are in [mailex_extraction_results](mailex_extraction_results/).
TRAIN-only ontology and actual dependency versions are in
`ai/config/mailex_native_extraction_schema.json` and
`ai/config/mailex_extraction_environment.json`.

## Verified results so far

All quality figures below use DEV only. Native arguments remain attached to
individual event records; no flattening into entity bags or FYP labels occurs.

| Completed candidate | DEV role exact F1 | Partial record F1 | Exact record F1 | Selection |
|---|---:|---:|---:|---|
| DistilBERT categorical BIO, LR 2e-5, seed 17 | 0.338717 | 0.487985 | 0.179377 | Epoch 6; threshold 0.7 |
| Same recipe, fresh seed 23 | 0.345117 | 0.500899 | 0.189087 | Epoch 8; threshold 0.7 |
| Same model, LR 1e-5, seed 17 | 0.289388 | 0.438334 | 0.144867 | Epoch 6; threshold 0.7 |
| Paired body-only ablation | 0.3366 | 0.4901 | 0.1840 | Epoch 8; threshold 0.7 |
| Paired subject+body ablation | 0.3444 | 0.4898 | 0.1851 | Epoch 8; threshold 0.7 |
| GLiNER2.5 Small zero-shot, first completed pass | 0.0000 | 0.0000 | 0.0000 | Threshold 0.5; 28 predicted events, no arguments |
| GLiNER2.5 Small fine-tuned, best epoch 3 | 0.223518 | 0.183657 | 0.038894 | Threshold 0.2; independently scored full native DEV |

The paired ablations use 352 DEV messages, not the main benchmark's 361;
compare them only to each other. Subject added 0.78 absolute role-F1 points
but no record-quality gain in this one-seed ablation. The main input remains
body only. Encoder LR 2e-5 is retained for the compact final recipe.

For compact seed 17 at threshold 0.7, supplying native event type and full
trigger raises exact role F1 from 0.338717 to 0.443041. Supplying only event
type gives 0.212274 because it cannot distinguish repeated same-type instances
without anchors. The model has 20% trigger-conditioning dropout during fitting.

The first independent-BCE architecture trial failed with fragmented BIO spans;
it was stopped and replaced by the categorical architecture. This is an actual
failed fit, documented separately, and will not be tested.

The supervisor personally inspected 100 usable TRAIN conversions and 100 frozen
DEV error cases from 84 messages. An independent agent reproduced the compact
DEV scores; 20 focused native-conversion/evaluator tests passed. No non-source
segments were found in the frozen compact or first zero-shot predictions.
That verifies substring grounding, not semantic correctness of extracted facts.

## Runtime already measured

Compact weights: 266,443,579 bytes; 66,601,862 parameters. Four CPU threads.
On the Windows development PC, median latency over five repetitions was
36.3 ms for a 39-word DEV email and 607.5 ms for the longest, 721-word email.
RTX 5070 medians were 13.0 ms and 78.6 ms respectively. CPU model load took
1.09 s, and fresh-process imports plus readiness took 7.57 s; filesystem caches
were not flushed. Peak CPU-process working set was 1.41 GB. These initial
measurements may overlap another fitting process; final selected-checkpoint
measurements will be reported before the final recommendation.

## Data boundaries and limitations

The official package has TRAIN/DEV/TEST 1,200/150/150 threads and
3,117/414/405 turns, 11 event types and 25 case-sensitive role names. Faithful
native BIO conversion yields 18,149 argument runs, correcting the earlier
18,099 case-folded result. The 50 extra runs are actual role-case transitions.

Model inputs use the explicitly named `mailex_native_fyp_safe_v1` subset:
1,061/131/135 threads; 2,762/361/363 turns; 5,729/828/772 events. Known protected
FYP fingerprint matches and their connected leakage components are excluded
by whole thread. The official conversion is separately retained. Published
cross-split duplicates are documented, not silently relabeled or moved.
These results are not untouched official MailEx scores or proof that every
original Enron identity is isolated.

MailEx native labels are preserved even when source review finds questionable
roles. The task ontology is not a complete FYP project-management schema.
Current accuracy does not justify unattended Outlook actions or adaptation
to all FYP primitives yet.

## Completion status before TEST

- Compact robustness seed 41, using the retained LR 2e-5 recipe.
  Seeds 17 and 23 are complete. Seed 41 ran out of GPU memory during its first
  optimizer step while GLiNER was active; its incomplete output is preserved.
  Fits now run one at a time. No three-seed conclusion is claimed yet.
- GLiNER Small fine-tuning is complete. Its public trainer matches repeated text
  by surface string and appends punctuation. A narrow native processor override
  retains exact occurrences and original text. A repeated-text two-event fixture
  passed finite forward/backward checks. The first full trainer attempt failed
  before optimization; a corrected batch-2 run passed real optimizer steps.
  The stable batch-4 fit completed three epochs and 14,010 optimizer updates.
  Both declared native DEV thresholds are independently scored. The selected
  0.2 threshold trails the compact baseline substantially. The runner failed
  only while serializing the returned training history; actual weights were
  saved, and unavailable epoch losses are not estimated.
- GLiNER full TRAIN model view covers 98.31% of events and 97.80% of argument
  segments. Missing triggers and records that cannot fit intact in any bounded
  window are explicitly counted. Final DEV evaluation uses the entire native
  gold split, including unsupported examples and unseen role/qualifier pairs.
- Final fitted-checkpoint CPU/GPU runtime and final error
  audit if the selected checkpoint changes.
- Final architecture choice, source-free selection manifest, committed TEST
  lock, and one-time TEST inference for each finalist.

**There is no committed selection lock and no model inference on native TEST
at this progress checkpoint. No final winner or production-readiness claim.**

GLiNER Base is not trained: Small's measured native DEV quality is clearly
below the compact baseline, so a larger GLiNER fit is not justified. The
pre-TEST quality/runtime preference is recorded in the benchmark report.
Large annotation expansion, V1 TEST reuse, V2 speech heads, thread-state
models, dashboard integration, DAPT, OCR and new datasets are outside this sprint.

## How to review this commit

Review `ai/src/datasets/mailex_native.py`, `ai/src/mailex_extraction/compact.py`,
`ai/src/mailex_extraction/gliner_backend.py`, and the independent `metrics.py`.
The corresponding scripts implement preparation, fitting, DEV calibration,
runtime measurement, and gated inference/evaluation. Focus on event-instance
association, exact source offsets, native role case/qualifiers, full-input
coverage, and TEST reservation/manifest enforcement.

Raw email text, full reviews, source-bearing predictions, corpus-derived IDs,
downloaded dependency runtimes and weights are intentionally excluded from
Git. The GitHub reviewer can inspect algorithms and aggregate evidence; exact
private examples and checkpoints are available only in the authorized local
workspace. Reproducing the protected FYP-safe view requires its private
boundary/index metadata. Subsequent progress and final results will be pushed
as separate commits; this checkpoint should not be mistaken for a frozen
final experiment or a TEST result.

The matched-cohort CPU GLiNER measurement is complete: 1.130 s for the same
39-word message and 8.583 s for the same 721-word maximum used by the compact
benchmark. The long email needs 31 GLiNER schema-window runs. Its eight-email
cohort takes 16.259 s; peak working set is 1.468 GB. These measurements use the
pretrained checkpoint. Final fitted-checkpoint CPU/GPU measurements remain
pending; host contention and operating-system caching limit timing comparisons.

The supervisor additionally inspected 100 frozen seed-23 DEV error cases from
80 messages. The separate audit preserves native gold labels and records
fragmented actions, wrong-event arguments, duplicate records and plausible
unannotated facts. Residual event-alignment samples include same-type and
unrelated pairs, so they are not automatically confirmed classification errors.

The GLiNER batch-4 best epoch-three weights have SHA-256
`907904ef8c171c9ca9aa61f33856ce2819882bccd5d077c44ce4343b4fe437a4`.
The supervisor verified the actual file bytes and inspected full DEV sources
with predictions at both thresholds. The corrected strict zero-shot pass is
saved separately from the original punctuation-normalized pass. GLiNER Base
is not justified by the measured DEV gap. The combined synthetic suite now
passes 31 cases; all TEST-shaped fixtures are temporary synthetic inputs.

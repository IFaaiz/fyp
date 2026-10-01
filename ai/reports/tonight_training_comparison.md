# Tonight: audited silver, actual model results, and next decision

Local date: **2 October 2026**. **Every score below is an AI-silver diagnostic metric.** No human/gold, final-accuracy or production-accuracy claim is made.

## A. Semantic audit

Starting HEAD: `7c6096700582ef8db9da5780fee3bc28149c6e9b` (committed checkpoint 617). The verified accepted local working state was **718**, including previously completed work. Expansion stopped and that state was frozen before this audit.

- Audited: **413** unique sources: all **353 project-positive** messages, including all **93 priority-label** records, plus **60 negatives** (50 deterministic sample + 10 additional calendar cases).
- Final source-based decisions: **346 confirmed; 23 corrected; 44 excluded uncertain**. The supervisor adjudicated every proposal and rare-label case.
- Frozen experiment silver v2: **674**. Full text stays ignored; [the manifest](../annotation/training_silver_v2_manifest.jsonl) is text-free.
- Subsequent error review quarantined **6 more scope-uncertain references** for future fitting: **668 remain eligible for the next training iteration** in [the next-training manifest](../annotation/tonight_next_training_manifest.jsonl). Tonight's fixed evaluation remains unchanged.

| Label | Original 718 | Frozen experiment 674 | Next eligible 668 |
|---|---:|---:|---:|
| MEETING | 98 | 93 | 91 |
| DEADLINE | 62 | 57 | 56 |
| REPORT_REQUEST | 11 | 9 | 9 |
| DEPARTMENTAL_INPUT | 8 | 17 | 17 |
| ACTION_REQUEST | 121 | 107 | 105 |
| FOLLOW_UP | 13 | 10 | 10 |
| APPROVAL | 17 | 13 | 13 |
| GENERAL_UPDATE | 237 | 212 | 208 |
| NON_PROJECT | 365 | 357 | 357 |

Known risks: all labels remain AI silver; 305 retained negatives had no new full semantic review; historical Enron differs from modern Outlook project mail; rare functions have too few examples. The 1,000-row training-readiness gate remains unmet; the requested explicit diagnostic override was used. [Full audit and changes](tonight_semantic_audit.md).

## Shared experiment design

- Fixed outer development/validation: **536 / 138** (about 80/20).
- Both models fit on the same **426** rows; thresholds are selected only on **110** separate development rows; final validation has **138**.
- Source-qualified threads, canonical leakage components and 42 reviewed near-copy/template links stay within one partition. Hash-validated [shared split](../annotation/tonight_silver_v2_shared_split.json).
- Seeds: outer/model **20261002**, inner split **20261003**. No validation class frequencies enter weights or threshold selection.
- Inputs: subject + current authored message. Quoted history is excluded from model input.

## B. TF-IDF baseline

Actual fitted model: word/bigram TF-IDF + nine one-vs-rest scikit-learn logistic regressions, `lbfgs`, `C=1`, `max_iter=1000`. All labels converged. Fit **426**, tuning **110**, validation **138**.

Fit time: **1.82 s**. Portable JSON serialization: **21.25 MB**. CPU warmed single-message score time: **0.099 ms** (not directly comparable with GPU transformer latency).

The TF-IDF model was fitted and measured; its portable export was not persisted. Automatic approval review rejected the subagent's extra artifact write as outside its assigned script/report scope. The report accurately records `portable_model_persisted=false`; rerunning the command below regenerates the experiment.

### Full fixed-validation comparison

| Model / threshold | Micro P | Micro R | Micro F1 | Macro P | Macro R | Macro F1 | Exact set | Hamming | No-label |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Always NON_PROJECT | 0.536 | 0.396 | 0.455 | 0.060 | 0.111 | 0.078 | 0.536 | 0.143 | 0 |
| Existing keyword/rule | 0.323 | 0.289 | 0.305 | 0.236 | 0.279 | 0.215 | 0.210 | 0.198 | 0 |
| TF-IDF / 0.5 | 0.787 | 0.374 | 0.507 | 0.197 | 0.109 | 0.111 | 0.507 | 0.110 | 49 |
| TF-IDF / tuned | 0.649 | 0.604 | 0.626 | 0.486 | 0.363 | 0.363 | 0.587 | 0.109 | 3 |
| DistilBERT weighted / 0.5 | 0.171 | 0.369 | 0.234 | 0.173 | 0.537 | 0.165 | 0.000 | 0.364 | 0 |
| DistilBERT weighted / tuned | 0.194 | 0.283 | 0.230 | 0.272 | 0.348 | 0.170 | 0.022 | 0.285 | 1 |
| DistilBERT unweighted / 0.5 | 0.820 | 0.487 | 0.611 | 0.185 | 0.162 | 0.169 | 0.558 | 0.093 | 27 |
| DistilBERT unweighted / tuned | 0.406 | 0.604 | 0.486 | 0.246 | 0.390 | 0.248 | 0.428 | 0.192 | 6 |

Five-fold diagnostic CV was completed inside the fit partition with connected thread/group components intact and fixed 0.5 thresholds. Each fold has positives for MEETING, DEADLINE, ACTION_REQUEST, GENERAL_UPDATE and NON_PROJECT. Mean fold micro F1 **0.475**; mean common-label macro F1 **0.168**. Rare-label fold scores are explicitly unstable; this CV does not validate tuned final-split performance. [Baseline JSON](tonight_tfidf_diagnostic.json) includes every fold, convergence, thresholds, prevalence and per-label metrics.

## C. Transfer learning

- Actual pretrained encoder: **distilbert-base-uncased**, revision `12040accade4e8a0f71eabdb258fecc2e7e948be`.
- Encoder plus **nine logits**, binary multi-label targets and **BCEWithLogitsLoss**; no softmax.
- **66,960,393 total/trainable parameters**; whole model fine-tuned for **3 epochs**, batch **8**, learning rate **5e-5**, AdamW weight decay **0.01**.
- Device: **NVIDIA GeForce RTX 5070**, Torch **2.11.0+cu128**, Transformers **4.57.6**, Python **3.12.14**.
- Strict deterministic algorithms and eager attention. The earlier warn-only run was archived after a nondeterministic CUDA-attention warning; the repeat used unchanged data, seed and hyperparameters.
- Fit-token distribution p50 **166**, p90 **475**, p95 **607**, p99 **863**. Selected length **512** (model limit); truncated **32 fit / 5 tuning / 5 validation** messages. One reviewed approval request fell after the cutoff.

| Variant | Training time | Weights | Package incl. tokenizer | GPU single-message incl. tokenizer |
|---|---:|---:|---:|---:|
| Weighted | 26.72 s | 267.85 MB | 268.80 MB | 14.92 ms |
| Unweighted | 11.08 s | 267.85 MB | 268.80 MB | 13.97 ms |

Training times exclude dependency/checkpoint downloads and saved-model hashing. Inference is warmed local CUDA forward plus tokenizer, not full Outlook/application latency.

### Fit-only positive weights

| Label | Positives in fit | Weight |
|---|---:|---:|
| MEETING | 56 | 6.607 |
| DEADLINE | 33 | 11.909 |
| REPORT_REQUEST | 5 | 84.200 |
| DEPARTMENTAL_INPUT | 10 | 41.600 |
| ACTION_REQUEST | 67 | 5.358 |
| FOLLOW_UP | 6 | 70.000 |
| APPROVAL | 8 | 52.250 |
| GENERAL_UPDATE | 132 | 2.227 |
| NON_PROJECT | 227 | 0.877 |

Weights use negative/positive counts from the 426 fitting rows only. Raw weighting **did not help** this run: it amplified broad rare-label predictions and nearly eliminated correct NON_PROJECT predictions.

### Per-label results for both threshold policies

Cells are **precision / recall / F1**. `*` means validation support below 20: unstable, not evidence of a reliable class.

#### TF-IDF

| Label | Support | 0.5 P/R/F1 | Tuned P/R/F1 |
|---|---:|---|---|
| MEETING | 21 | 0.000 / 0.000 / 0.000 | 0.714 / 0.476 / 0.571 |
| DEADLINE * | 15 | 0.000 / 0.000 / 0.000 | 0.667 / 0.133 / 0.222 |
| REPORT_REQUEST * | 2 | 0.000 / 0.000 / 0.000 | 0.062 / 0.500 / 0.111 |
| DEPARTMENTAL_INPUT * | 3 | 0.000 / 0.000 / 0.000 | 1.000 / 0.333 / 0.500 |
| ACTION_REQUEST | 24 | 0.000 / 0.000 / 0.000 | 0.320 / 0.333 / 0.327 |
| FOLLOW_UP * | 2 | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| APPROVAL * | 3 | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| GENERAL_UPDATE | 43 | 1.000 / 0.093 / 0.170 | 0.844 / 0.628 / 0.720 |
| NON_PROJECT | 74 | 0.776 / 0.892 / 0.830 | 0.771 / 0.865 / 0.815 |

#### Weighted DistilBERT

| Label | Support | 0.5 P/R/F1 | Tuned P/R/F1 |
|---|---:|---|---|
| MEETING | 21 | 0.224 / 0.524 / 0.314 | 0.444 / 0.381 / 0.410 |
| DEADLINE * | 15 | 0.169 / 0.867 / 0.283 | 0.133 / 0.133 / 0.133 |
| REPORT_REQUEST * | 2 | 0.023 / 0.500 / 0.043 | 0.020 / 1.000 / 0.039 |
| DEPARTMENTAL_INPUT * | 3 | 0.033 / 1.000 / 0.064 | 0.056 / 0.333 / 0.095 |
| ACTION_REQUEST | 24 | 0.667 / 0.083 / 0.148 | 0.300 / 0.125 / 0.176 |
| FOLLOW_UP * | 2 | 0.050 / 1.000 / 0.095 | 0.000 / 0.000 / 0.000 |
| APPROVAL * | 3 | 0.000 / 0.000 / 0.000 | 0.032 / 0.333 / 0.059 |
| GENERAL_UPDATE | 43 | 0.394 / 0.860 / 0.540 | 0.461 / 0.814 / 0.588 |
| NON_PROJECT | 74 | 0.000 / 0.000 / 0.000 | 1.000 / 0.014 / 0.027 |

#### Unweighted DistilBERT

| Label | Support | 0.5 P/R/F1 | Tuned P/R/F1 |
|---|---:|---|---|
| MEETING | 21 | 0.000 / 0.000 / 0.000 | 0.258 / 0.762 / 0.386 |
| DEADLINE * | 15 | 0.000 / 0.000 / 0.000 | 0.250 / 0.067 / 0.105 |
| REPORT_REQUEST * | 2 | 0.000 / 0.000 / 0.000 | 0.037 / 1.000 / 0.071 |
| DEPARTMENTAL_INPUT * | 3 | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| ACTION_REQUEST | 24 | 0.000 / 0.000 / 0.000 | 0.211 / 0.167 / 0.186 |
| FOLLOW_UP * | 2 | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| APPROVAL * | 3 | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| GENERAL_UPDATE | 43 | 0.852 / 0.535 / 0.657 | 0.620 / 0.721 / 0.667 |
| NON_PROJECT | 74 | 0.810 / 0.919 / 0.861 | 0.843 / 0.797 / 0.819 |

The unweighted 0.5 model emits only NON_PROJECT and GENERAL_UPDATE: all seven other labels have zero recall. Its improved NON_PROJECT F1 (0.861 vs tuned TF-IDF 0.815) does not establish a stronger nine-label classifier. Tuned TF-IDF has the higher overall macro F1 (**0.363**) and better meeting/action behavior. Neither system currently handles all rare functions reliably.

Threshold tuning helped TF-IDF but lowered transformer micro F1. Unweighted transformer macro F1 rose with tuning, while many rare predictions became false positives; weighting and tuning do not provide a usable rare-label solution here.

[Transformer JSON](tonight_transfer_diagnostic.json) includes all thresholds, per-label prevalence/predicted counts, versions, checkpoint hashes, class weights and logs. Trained weighted/unweighted checkpoints are local in ignored `ai/data/models/tonight/`. [Saved-checkpoint reload smoke](tonight_transfer_checkpoint_smoke.json) reproduced a finite nine-output prediction.

## D. Simple baselines

Always NON_PROJECT: micro F1 **0.455**, macro F1 **0.078**. Keyword/rule: micro F1 **0.305**, macro F1 **0.215**. Tuned TF-IDF improves both over these simple baselines. The unweighted transformer improves micro F1 largely through the two dominant classes; its macro F1 at 0.5 is below the keyword baseline.

## E. Error analysis

**50 actual validation error sources personally read by the supervisor.** The weighted tuned system made 135 exact-set errors among 138 validation messages. Selection prioritized rare-reference errors and then one error per component under deterministic ranking; category counts are diagnostic, not population estimates.

- Attached/reviewed document vs requested deliverable: **27**.
- Project scope vs operations/external notices: **25**.
- Partial multi-label miss: **19**.
- Approval scope: **15**; generic update overuse: **13**; deadline/date role: **12**.
- Six unresolved silver-reference cases are quarantined for future fitting; original evaluation scores remain frozen.

[Source-based error report](transfer_learning_error_analysis.md) and [50 text-free decisions/error IDs](transfer_learning_error_analysis.json).

## F. Human queue

**180** blank-label examples, using the existing simple annotator: **136 fit/tuning + 44 excluded uncertain sources**. No validation IDs, threads or leakage groups enter this queue. The queue is **training-reused calibration, not independent gold**.

Accepted training-side rare coverage: REPORT_REQUEST **7/7**, DEPARTMENTAL_INPUT **14/14**, FOLLOW_UP **8/8**, APPROVAL **10/10**; DEADLINE **42/42**. These counts overlap. Additional ambiguous rare examples are among the 44 excluded sources. The validation rare examples are intentionally omitted.

The queue also includes 33 difficult audited negatives, 28 accepted auditor-disagreement cases and a deterministic common-label balancing fill. No AI/model labels are shown. Authored-message display is hash-bound to the canonical prefix; quoted tails remain reference-only and span offsets stay anchored to source text.

Run from `E:\Projects\FYP` (uses the existing virtual-environment Python, so it avoids the missing global Python alias):

```powershell
ai\.venv\Scripts\python.exe ai\annotation\simple_annotator\app.py --reviewer faaiz --seed-path ai\data\annotated\human\transfer_calibration\canonical_seed.jsonl --output-dir ai\data\annotated\human\transfer_calibration\reviewers
```

The existing store and Flask GET smoke checks pass. This calibration must not later be reported as independent final-validation accuracy.

## G. Decision for tomorrow

**Priority: human calibration + active learning.** Review the 180-row queue, especially scope ambiguity and rare requests/approvals/contributions, then collect a fresh untouched evaluation set from the intended project-email domain.

The measured prototype is useful as an engineering checkpoint and a candidate-suggestion baseline. Direct DistilBERT transfer learning has learned some status/non-project distinction, but **has not shown a nine-label improvement over tuned TF-IDF** on this data. Do not advance to DAPT, stronger-encoder shopping or extraction before correcting these label and coverage limits.

After calibration, use training-only experiments to investigate capped/smoothed class weights, joint NON_PROJECT/threshold resolution and handling long messages. Any new result needs a fresh untouched evaluation boundary; these 138 silver validation messages have now been inspected.

## Verification

**120 repository tests pass.** Snapshot/source/hash isolation checks, all 180 blank queue records, Flask read/draft-save smoke, and the saved transformer reload smoke pass. No raw email text or model weights are committed.

## Reproduce and verify

```powershell
ai\.venv\Scripts\python.exe ai\scripts\freeze_tonight_silver.py
ai\.venv\Scripts\python.exe ai\scripts\train_tfidf_diagnostic.py
ai\.venv\Scripts\python.exe ai\scripts\train_transfer_diagnostic.py --checkpoint-dir ai\data\cache\distilbert-base-uncased --compare-unweighted
ai\.venv\Scripts\python.exe ai\scripts\build_transfer_calibration_queue.py
ai\.venv\Scripts\python.exe -m unittest discover -s ai/tests -t ai -q
```

These commands require the local ignored source/audit artifacts. Source text and downloaded/fine-tuned weights are intentionally absent from Git. Optional dependency versions are pinned in [requirements-training.txt](../requirements-training.txt) and [requirements-transfer.txt](../requirements-transfer.txt). Run the historical freeze only to reproduce tonight; future training must apply [the quarantine](../annotation/tonight_post_experiment_quarantine.json) and use [the 668-row manifest](../annotation/tonight_next_training_manifest.jsonl).

Frozen manifest SHA-256: `0e022f93fcdaff59f21ca2c4406ce1f07e1b60a0f22f609ab9fcbca3d3e015fc`.
Shared split SHA-256: `ebcdf58b3ffdaf9be854a3bad4ab5bfa79cffc52cb2d0899a07a742db049a1d5`.
Training reports record source HEAD plus exact implementation hashes because the run used the audited working tree before its result commit. No model was selected as a final production winner.

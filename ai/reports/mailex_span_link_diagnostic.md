# MailEx span-link diagnostic audit

**Status: INCOMPLETE.** The diagnostic stopped during seed 17, epoch 3. No seed finished checkpoint selection and the per-seed CPU gate, seeds 23 and 41 were not started, and no trained checkpoint or aggregate result was saved. The preregistered three-seed success rule cannot be evaluated. The run does not establish production or end-to-end accuracy; it is an oracle-conditioned argument-structure diagnostic.

## Preregistration and data integrity

The working preregistration is byte-identical to the committed file at `bce517aed6b216fca6bbf209cd8d32f565551b20` (blob `8cbf8a44eb333aa6584bc0fb3838ea470921e7ea`, SHA-256 `c7b9fd18c447cd5883f0969416426cdc847903e586c6337c0cfcc2b118a84988`). The authorized TRAIN and DEV files match their registered SHA-256 values. No test, private-test, or protected-evaluation split was read for this audit.

## Saved attempt history

| Run | Saved evidence | Audit status |
| --- | --- | --- |
| `20261005T183144Z_33d70a3a` | Initialized CPU gate passed (39-token median 82.967 ms; 721-token median 385.951 ms; initialized parameter bytes 267,073,748). Run metadata records 2.859 seconds and `ValueError: native span maps over a discontinuity in source token offsets`. | Failed before any seed; no history or checkpoint. |
| `20261005T183312Z_140529c7` | Initialized CPU gate passed (79.802 ms; 349.553 ms; 267,073,748 bytes). Seed 17 has one saved epoch (106.078 s): role-exact F1 0.180894, linked partial-record F1 0.136620, candidate-span recall 0.719568. The saved boundary and span-proposal mean losses are NaN; event-link mean loss is 0.047290. | Incomplete attempt. Metadata remains `training`; no checkpoint or terminal summary. Preserve this NaN history as a failed run. |
| `20261005T185355Z_1aa450e8` | Corrected initialized CPU gate passed (39-token median 82.552 ms; 721-token median 378.074 ms; initialized parameter bytes 267,073,748). Initial-loss preflight recorded finite losses for 2,501 effective TRAIN rows in 691 batches, with zero optimizer steps; 261 empty unsupervised TRAIN rows were skipped. Seed 17 saved epochs 1–3. | Interrupted/incomplete. Metadata remains `training`; no selected checkpoint, trained-weight size, per-seed CPU gate, or terminal summary was saved. Seeds 23 and 41 have no run history. |

In the corrected attempt, seed 17's highest saved role-exact score is at epoch 2: **0.273255** role-exact F1 and **0.418265** linked partial-record F1. Candidate-span recall at that epoch is 0.763936. Epoch 3 fell to 0.209676 role-exact F1 and 0.389139 partial-record F1. These are partial DEV observations, not a completed seed result. The initialized parameter-size guard passed; the actual saved-checkpoint file-size guard did not run because no checkpoint was written.

## Budget and completion

The first-attempt timestamp is 2026-10-05 18:30:44 UTC, recovered conservatively from the earliest persisted run directory. The fixed one-hour wall deadline was 19:30:44 UTC. It had expired by 2 hours, 3 minutes, 29 seconds at the audit time of 21:34:13 UTC.

There is no persisted `budget_ledger.json`, because the interrupted attempt did not reach its finalizer. The saved prior-attempt usage is 108.937 seconds. The corrected run's three completed epoch durations total 385.422 seconds. The corrected run began at 18:54:02.821 UTC and its last history write was at 19:01:01.733 UTC, so its saved run interval alone is at least 418.911 seconds. Together, the saved evidence gives a **minimum of 527.848 seconds** across attempts; this is not an exact cumulative total because the interrupted run's final monotonic duration was never persisted. The wall deadline has expired regardless of any unspent portion of the separate compute-time cap.

## Scope and report handling

The source changes applied to the diagnostic handle zero-width tokens in the model view, exclude only empty TRAIN rows without supervision while failing closed on supervised empty rows, check losses and gradients for finite values, and rerank all valid pairs from the top 32 start and top 32 end positions before keeping at most 96 proposals. The corrected run's initialized CPU timings and parameter-size estimate are within the preregistered limits (150 ms, 2,000 ms, and 350,000,000 bytes respectively). The per-seed saved-checkpoint gates remain unverified.

This report contains aggregate metadata and metrics only. It does not include source text, message identifiers, predictions, or private error samples. No error-analysis pass, inference launch, or test-split evaluation was performed for this audit.

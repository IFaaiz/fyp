# New AI annotation progress

Date: 2026-10-03
Scope: structured V2 review workflow and source-bound candidate preparation. This report contains aggregate counts and synthetic contract-test results only; it contains no corpus text or annotations.

## Source boundary

The frozen V2 boundary remains the 2026-10-02 checkpoint. It has 4,285 `TRAIN_SCREEN` candidates, 600 `EVAL_RESERVED` candidates, 11,889 `HISTORICAL_EXPOSED` identities, and 600 additional protected reserve IDs that remain outside the named partitions. The global index covers 28,129 records. Candidate ID membership, candidate-file hashes, protected-ID mapping, and partition/component isolation were checked in the metadata audit; the frozen boundary has zero cross-partition component conflicts.

These are source counts. They do not measure project relevance, primitive support, or accepted annotations.

## Review workflow

The offline workflow prepares hash-bound source-only A/B packets. It supports deterministic contiguous batches through `record_offset` and `record_limit`, bound to the full candidate file and the actual global index and partition manifest. EVAL defaults to the frozen `EVAL_RESERVED` partition. Primitive/evidence differences trigger third review even when derived FYP labels match. Every EVAL record requires a third source-only verdict before the adjudication packet reveals A/B.

High-risk labels and relations require an explicit root decision bound to the selected annotation. Root may reject an uncertain source so it does not hold a batch open; an uncertain annotation remains ineligible for acceptance. Finalization, handoff, explicit authorization, export, and `verify_accepted_train_provenance` recompute the source, schema/mapper, reviewer, adjudication, decision, isolation, registry, boundary, and export bindings.

On 2026-10-03, metadata-only packet preparation succeeded for one 16-record `TRAIN_SCREEN` batch and one 16-record `EVAL` batch. They have no ingested reviewer annotations, accepted decisions, handoff, training authorization, or model fit.

## Synthetic verification

The synthetic suite uses invented text and a temporary fixture registry/index. It exercises a TRAIN A/B disagreement with matching labels, C initial review before A/B reveal, a hash-bound root approval, accepted handoff, authorized export, and public provenance verification. It also checks that uncertain rows cannot be accepted; all EVAL rows require C; invalid source-read attestations, partition/protected-ID mismatches, source/schema/validator/mapper drift, and forged stored A/C packets, review/adjudication artifacts, comparison, decision, root, handoff, export, registry, or authorization fail closed.

Commands run from `ai/`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_structured_review_workflow -v
.\.venv\Scripts\python.exe -m unittest tests.test_structured_model_gates -v
```

Results: 7 workflow tests passed; 21 model-gate tests passed. These synthetic tests establish workflow contracts only. They are not annotations, source-content audits, training data, model fits, or evaluation results.

## Current annotation status

Real candidate annotations accepted: **0**.
Human-gold labels: **0**.
New training authorizations: **0**.
New model fits and V2 performance claims: **0**.

The next substantive milestone is source-grounded review on TRAIN candidates, followed by the complete EVAL A/B/C process and external review of any proposed TRAIN export. Acquisition, rights, identity, or primitive-support gaps remain as recorded in `structured_pipeline_evaluation.md`.

## Root verification update

The root ran 132 focused tests on 2026-10-03: all passed, including 7 workflow, 21 model-gate and 12 preserved Enron parser tests. The 77-file closed-V1 integrity check passed with no missing or changed files and no training/inference performed. Exact duplicate model inputs now count once; conflicting primitive targets fail closed.

The user explicitly approved full assigned-email review after automatic review had rejected full reads under brief-excerpt permission. A real 16-source TRAIN_SCREEN review is in progress at `ai/data/structured_review/v2_train_batch001_review_20261003/`; A and B each confirm they read all 16 complete sources independently. This reading attestation is not an accepted annotation or model result. The earlier `v2_train_batch001_20261003` packet preparation was unused because the agent-thread limit required assignment to existing workers.

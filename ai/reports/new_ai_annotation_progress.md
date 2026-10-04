# New AI annotation progress

Updated: 2026-10-04
Scope: structured V2 review workflow and source-bound candidate preparation. This report contains aggregate counts and synthetic contract-test results only; it contains no corpus text or annotations.

## Source boundary

The frozen V2 boundary remains the 2026-10-02 checkpoint. It has 4,285 `TRAIN_SCREEN` candidates, 600 `EVAL_RESERVED` candidates, 11,889 `HISTORICAL_EXPOSED` identities, and 600 additional protected reserve IDs that remain outside the named partitions. The global index covers 28,129 records. Candidate ID membership, candidate-file hashes, protected-ID mapping, and partition/component isolation were checked in the metadata audit; the frozen boundary has zero cross-partition component conflicts.

These are source counts. They do not measure project relevance, primitive support, or accepted annotations.

## Review workflow

The offline workflow prepares hash-bound source-only A/B packets. It supports contiguous batches and explicit ordered `record_indices`, both bound to the exact full candidate file, global index and frozen partition manifest. Status is read-only; explicit finalization writes decisions only when every row has a complete outcome. Eligible interim rows are reported as provisional. EVAL defaults to the frozen `EVAL_RESERVED` partition. Primitive/evidence differences trigger third review even when derived FYP labels match. Every EVAL record requires a third source-only verdict before the adjudication packet reveals A/B.

High-risk labels and relations require an explicit root decision bound to the selected annotation. Root may reject an uncertain source so it does not hold a batch open; an uncertain annotation remains ineligible for acceptance. Finalization, handoff, explicit authorization, export, and `verify_accepted_train_provenance` recompute the source, schema/mapper, reviewer, adjudication, decision, isolation, registry, boundary, and export bindings.

On 2026-10-03, metadata-only packet preparation succeeded for one 16-record `TRAIN_SCREEN` batch and one 16-record `EVAL` batch. They have no ingested reviewer annotations, accepted decisions, handoff, training authorization, or model fit.

## Synthetic verification

The synthetic suite uses invented text and a temporary fixture registry/index. It exercises a TRAIN A/B disagreement with matching labels, C initial review before A/B reveal, a hash-bound root approval, accepted handoff, authorized export, and public provenance verification. It also checks that uncertain rows cannot be accepted; all EVAL rows require C; invalid source-read attestations, partition/protected-ID mismatches, source/schema/validator/mapper drift, and forged stored A/C packets, review/adjudication artifacts, comparison, decision, root, handoff, export, registry, or authorization fail closed.

Commands run from `ai/`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_structured_review_workflow -v
.\.venv\Scripts\python.exe -m unittest tests.test_structured_model_gates -v
```

Results: 11 workflow tests passed; 21 model-gate tests passed. These synthetic tests establish workflow contracts only. They are not annotations, source-content audits, training data, model fits, or evaluation results.

## Current annotation status

Two real 16-source TRAIN batches completed the independent A/B, frozen source-only C initial, post-blind adjudication and root checks. Of 32 sources, **16 were accepted and 16 excluded**. Accepted support is 15 NON_PROJECT and 1 PROJECT. Two private, explicitly authorized `accepted_train.jsonl` exports (8 rows each) passed full provenance verification and the actual model preflight. Both fail the predeclared minimum of 20 unique examples per scope class; no model was fitted.

Human-gold labels: **0**. Accepted EVAL annotations and new evaluation predictions: **0**. This is a source-grounded AI-silver seed, not an accuracy result. Exact evidence/primitive disagreements affected 31/32 initial A/B pairs; derived-label sets agreed on 28/32 after the deadline fix. Agreement is a review-process diagnostic, not correctness.

Root excluded four additional rows after C: two insufficient scope judgments, one omitted current delivery act, and one forwarded-header-only current view. Original proposals remain private and preserved. A new 78-source TRAIN-only seed assignment combines the first 32 random candidates and 46 lexical-recall candidates with fresh independent reviewers. Recall words generate no labels. Its acceptance remains pending; it is not counted in the 16 accepted rows.

The 78-source review was interrupted before any complete A/B/C preview envelope was saved. On 2026-10-04, root prepared `v2_train_seed078_resumed_20261004` with the actual new reviewer identities and verified identical source order, hashes and bundle. Prior drafts remain preserved; the resumed reviewers must independently read the full assigned sources. Incomplete drafts and read-progress notes cannot be ingested or counted as acceptance.

Details and hashes: `structured_annotation_pilot.json`.

## Semantic TRAIN retrieval

The cached, unmodified `all-MiniLM-L6-v2` encoder screened all **4,285 isolated TRAIN candidates** across nine fixed synthetic primitive/negative queries on 2026-10-03. Head, middle and tail retrieval windows produced 5,923 encoded views. Each query ranks sources by its maximum window similarity; round-robin selection produces a unique diverse review order. This supplies semantic retrieval alongside the initial lexical recall. It is computational screening, not 4,285 source-read AI annotations or accepted labels.

Root verified source, boundary, global-index, score and encoder hashes and all ranking permutations after execution. Supplying the frozen evaluation file failed at the TRAIN-file hash check before text decoding or encoder inference. No old experiment model, evaluation source text, human label or accepted annotation informed retrieval. The encoder was loaded from existing local bytes with network loading disabled. Partial windows can emphasize quoted history; reviewers must read complete assigned messages and determine current scope/functions independently. Private scores and rankings remain under `ai/data`; `structured_semantic_screening.json` contains only aggregate methods and hashes.

## Root verification update

All **137 focused tests** passed, including 53 mapper, 11 workflow, 21 model-gate and 12 preserved Enron parser tests. The 77-file closed-V1 integrity check passed with no changed or missing files, and no old TEST inference or training was performed.

The subsequent 2026-10-04 model-input safeguards passed all 25 model-gate tests. Known unbounded body history is quarantined from speech fitting; speech features exclude subjects and count repeated authored bodies once even across different subjects. Scope retains subject context. Regressions cover history markers, exact authored offsets, forwarded subjects and conflicting body targets. Both earlier real exports passed the updated provenance loader/preflight with unchanged class shortages. No model fit followed these checks.

Actual source review exposed two defects. DEADLINE previously needed a redundant speech act targeting the due relation; the mapper now derives it from a validated current date/target relation. Status previously called incremental finalization and wrote a provisional decision before C was complete; status is now read-only and finalization requires the complete batch. Thirteen partial artifacts from the affected second run were preserved in a private recovery directory; no training export existed at that recovery point. The repaired run subsequently finalized and exported successfully.

The user explicitly approved full assigned-email annotation/adjudication review after automatic review had rejected full reads under brief-excerpt permission. Later separate relevance-pool display was rejected; that display stopped, and source-bound annotation assignments proceeded under the granted permission. Every raw message, evidence string, annotation, export and model asset remains Git-ignored. Distinct role identities, source-read attestations and hashes in a shared workspace establish an audit trail; they do not cryptographically prove process independence or constitute human gold.

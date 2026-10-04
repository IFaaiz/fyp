# MailEx compact DEV error analysis

## Scope and integrity

This provisional review covers the categorical compact extractor at BIO threshold `0.7` on the FYP-safe DEV split. It uses 361 messages and 828 gold event records. The frozen safe-gold SHA-256 is `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`; the prediction SHA-256 is `1ba0824e0e74f1fdc64b649cfc9c464ed4748f7a1ebb146b2a1bc4984fd1382a`.

I independently scored the frozen rows with the final evaluator. Numeric metrics match the saved DEV report. The evaluator wording correction made after scoring changed only the definition strings, not the matching or scores. TEST and protected rows were not read.

The full, source-bearing review sample is kept in the ignored private experiment directory at `ai/data/experiments/mailex_extraction_v1/private_dev_audit/selected_100_threshold_0.7_phase10_review.jsonl`. It contains 100 deterministic cases from 84 messages, with full message text, gold and predicted event records, and phase-10 labels for private review. Sampling used seed `20261004`, with 25 cases from each of four strata: same-type record errors, residual wrong-type diagnostics, missed gold events, and unmatched predicted events.

A supervisor independently reviewed all 100 full-text cases. That review confirmed the main patterns below: fragmented long action arguments, participants copied from nearby clauses, missed imperative and deadline events, phone-call and promise event-type confusions, discontinuous trigger limitations, and occasional event predictions on social or fictional content. The sample remains a stratified diagnostic set, not a prevalence estimate.

## DEV metrics

| Measure | Result |
|---|---:|
| Event type identification micro F1 | 0.6638 |
| Exact event record F1, excluding trigger | 0.1794 |
| Partial event record F1, excluding trigger | 0.4880 |
| Exact argument record F1 | 0.3383 |
| Exact role F1 | 0.3387 |
| Argument extent overlap F1 | 0.4490 |
| Exact trigger F1 | 0.4103 |
| Partial trigger F1 | 0.5199 |

The extractor predicted 1,034 event records and 2,576 argument records. The evaluator aligned 150 gold events as missed, 356 predictions as spurious, and 60 residual pairs as possible event type errors. It also counted 344 missed triggers and 550 spurious trigger candidates. Within primary same-type event pairs, 322 gold arguments and 573 predicted arguments had no matching extent; there were 42 wrong-role and 21 wrong-qualifier matches.

The 60 type errors are diagnostic alignments, not 60 confirmed class mistakes. In the reviewed sample, two residual pairs joined unrelated events based on overlap cues; those cases are labeled `other` in the private review. Read the confusion count as a review queue.

All 361 prediction rows retained the exact gold message text. The evaluator found zero invalid or non-source prediction segments. It retained 42 flagged gold events and 23 flagged gold arguments as diagnostics.

## Phase-10 sample categories

Each reviewed sample case received one primary category, so these counts sum to 100. The sample was deliberately stratified and does not estimate category prevalence across DEV.

| Primary category | Cases |
|---|---:|
| Event missed | 25 |
| Event type wrong | 25 |
| Trigger boundary | 3 |
| Argument missed | 6 |
| Argument boundary | 7 |
| Argument assigned to wrong event | 11 |
| Argument role confusion | 1 |
| Shared argument | 0 |
| Context/revision confusion | 2 |
| Long text/truncation | 2 |
| Duplicate event | 3 |
| Pronoun participant | 0 |
| Date role confusion | 2 |
| Current-vs-context confusion | 0 |
| Other | 13 |

The sample also had overlapping error tags. Eleven cases had a trigger boundary problem, 14 had a missed argument, 14 had an argument boundary or fragmentation problem, two had role confusion, three had a clear pronoun-participant error, one involved a repeated shared mention, two showed context/revision confusion, one showed a current/context distinction, and three were duplicate event predictions. Six missed records were clear request, action, or deadline-like events. Two unmatched event examples showed social or fictional content being emitted as events. These overlapping observations are recorded as such and are not added to the primary-category counts.

## Error sources and limits

- **Model errors:** missed clear requests and actions, excess event triggers, duplicate records, and participants copied from nearby clauses. The low-threshold regime overproduced events; raising the threshold to `0.7` reduced predicted events from 1,391 to 1,034 in the same DEV split.
- **Representation limits:** five reviewed long action descriptions were emitted as separate argument records although the gold argument was one continuous span. Three reviewed gold triggers had discontinuous segments, which this compact decoder cannot group into one event trigger.
- **Annotation diagnostics:** four reviewed cases carried source-converter flags. Review also found two unusual native role choices; those labels remain unchanged in scoring. A long gold data value ended at an unusual list boundary in one reviewed case, while the prediction continued well beyond that boundary.
- **Long messages:** one reviewed message exceeded 512 native tokens. The encoder creates overlapping windows and checks that every source token is represented, so the observed long-span errors are under-extraction or over-extension rather than silent right truncation.

The primary event score is type-sensitive and associates arguments within their event records. The separate trigger score uses its own one-to-one trigger matching. Exact span equality requires the same segment-boundary set; equal union geometry alone is partial overlap, not exact credit.

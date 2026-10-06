# FYP calibration V1 source curation — iteration 2

Date: 2026-10-06

> **Superseded by root-approved iteration 3.** This report preserves the
> iteration 2 proposal and its review notes as historical context. The current
> aggregate counts, root review, and pending Site-import status are in the
> [iteration 3 curation report](fyp_calibration_v1_curation.md). For local
> single-packet review, see the [offline desktop prototype](../../desktop/README.md).

## Curation result

Prepared a **50-source unlabelled proposal** from the isolated Enron TRAIN_SCREEN pool. Manual review selected 47 messages with current evidence of bounded project or initiative work, plus 3 scope-boundary controls (6.0% of the proposal). The old 250-row and intermediate 187/190-row runs remain rejected and were not imported. This proposal has not been imported to the Site; root review of the common set is pending.

The 47 project-related sources show four kinds of evidence: 15 scoped acquisition or contract work with concrete negotiation steps; 13 active policy, regulatory, or standards deliverables; 11 implementation, requirements, engineering, or process work; and 8 project planning, status, modeling, or workshop work. A mention of “project” alone did not qualify a message. Current text needed to show an identifiable initiative and a present deliverable, decision, assignment, review, meeting, milestone, or substantive update. Generic contracts and routine business actions were not included as project sources.

## Manual curation audit

I read a deterministic stratified sample of 20 candidate messages: 10 from the earlier project-context tier, 5 from project-adjacent, and 5 from scope-boundary retrieval. The review retained **13** and rejected **7**. This is a judgment check over retrieval candidates, not an estimate of source-pool prevalence.

Retained messages had direct evidence such as an acquisition proposal that led into a defined purchase discussion; contract edits tied to a named transaction; task-force work tied to an initiative; a pipeline status list that asked for completion or delay updates; a workshop program with planned dates; and regulatory work with comment deadlines, legal review, or a draft letter for stakeholder support. Rejected messages included a market-wide approval notice, a resume and job request, a personal travel booking, an annual seminar attendance note, a generic agreement offer, a plain agreement exchange without a bounded initiative, and instructions to transfer funds. Three of those rejected examples are retained only as explicit scope-boundary controls; market broadcasts, personal/HR notices, and routine social or training messages are excluded.

## Source boundary and assignment

All 4,285 source rows were verified against the frozen boundary manifest and global leakage index before any message text was inspected. Every row maps to TRAIN_SCREEN, all source fingerprints match the index, the global isolation check found no partition conflicts, and none overlaps protected candidates. The boundary metadata records 600 protected evaluation-reserved records; their text was not opened. No native MailEx, old V1 test, reserved, or other dataset text was read.

The selected rows are 50 distinct leakage/thread/template components, with one representative per component and no component split across allocations. All selected Enron thread metadata is unverified, so no conversation context was inferred. The current authored range is stored as exact offsets into normalized `current_message`; obvious quoted/header markers were screened out of the selected prefixes. Any remaining tail is reference-only curator data and is absent from reviewer imports.

| Allocation | Sources | Owner slot 0 | Owner slot 1 | Owner slot 2 |
|---|---:|---:|---:|---:|
| Blind agreement (all three reviewers) | 25 | — | — | — |
| Calibration training | 13 | 5 | 4 | 4 |
| Sealed human holdout | 12 | 4 | 4 | 4 |

The common blind set is shared by all three reviewers. Personal training and holdout sources are round-robin assigned. The 20-source root audit file contains only sources from the blind common set; it contains no holdout source text. Retrieval hints and evidence notes are stored separately and are not part of the Site payload.

## Private artifacts

- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/site_import.jsonl` — complete private import proposal, including the sealed allocation.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/site_import_train_common.jsonl` — blind and personal training sources only.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/site_import_holdout.jsonl` — separate unlabelled holdout import; do not use it for the common-source audit.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/manual_audit_train_common_20_private.jsonl` — 20 blind-common sources for root review; no holdout text.
- `ai/data/experiments/fyp_calibration_v1_20261005/review_iteration2_private/curation_manifest.json` and `holdout_manifest.json` — aggregate counts and file digests; the holdout manifest contains no source text or individual source IDs.

## Limits

No consented current project or university email source was available in this input, so this remains a public-corpus fallback. The historical Enron energy-sector mail is enriched for relevant work and cannot establish modern project-domain prevalence. The boundary reports zero accepted structured annotations and does not authorize training export. All 50 source rows are unlabelled and have no AI prelabels; human label support, agreement, annotation time, and adjudication remain unknown.

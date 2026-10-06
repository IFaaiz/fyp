# Direct-label human calibration Round 1 plan

Date: 6 October 2026. This is a launch plan, not a report of completed human work. No human responses were opened for this plan, and no AI corpus pilot was run.

## Current frozen source inventory

The root-approved, unlabelled iteration-3 curation report records 47 imported Enron public-corpus fallback sources: 24 common blind, 12 personal calibration TRAIN, and 11 sealed human holdout. The import receipt is frozen. The report says the source set has no human labels or AI prelabels and no GOLD annotations. Its exact-source hashes and original assignment metadata remain the authority for source identity.

The 24 common blind sources remain the shared core of Round 1. To reach 30 double-annotated emails, add the first six records from the 12 existing `calibration_training` assignments in immutable source order. The sealed 11 holdout sources are excluded from this round and from its exports. The 24 existing sources plus those six are all calibration/TRAIN material; none is final evaluation data.

## Safe assignment pathway

After the schema-only runtime migration, an authenticated round queue read calls `prepareRound` to initialize and freeze a separate additive assignment overlay with `round_id: fyp-direct-round-1`; an owner-only endpoint is the manual fallback. Preparation names the unchanged 24 common source IDs and hashes, then the six selected `calibration_training` source IDs and hashes. The overlay assigns all 30 sources to registered reviewer slots 0 and 1. It does not edit the frozen source rows, replace their original allocation/owner slots, overwrite drafts, or copy any holdout source. A source hash or body mismatch blocks assignment. The overlay is prepared by the round action, not seeded by the runtime migration.

The six added sources are existing personal TRAIN records, selected by the frozen manifest’s immutable source position. Their inclusion in the new shared round is an additional review assignment; their original TRAIN membership and source hashes remain recorded. Reviewers independently annotate all 30 under `fyp-direct-label-v1`. Slot 2 may submit an additional blind annotation, but does not block release of the slot-0/slot-1 pair export after both have frozen all 30 records. The app export must return only this round’s assignments and submitted responses from the selected reviewers; omit the sealed holdout allocation. The round overlay stays versioned separately from the imported source manifest.

## Annotation and adjudication sequence

1. Deploy and freeze the direct-label interface, `fyp-direct-label-v1` validator, guide, and two-review export behavior before reviewers begin. Existing Structured V1 drafts/submissions stay in their legacy tables and keep their original version and meaning. New direct-label drafts/submissions use separate direct-review tables, even for a source a reviewer already saw in the legacy interface. Do not migrate them automatically.
2. Assign the same 30 source records to slots 0 and 1. Keep peer answers and any AI labels hidden until both submissions are frozen. Server provenance records annotator, time, blind status, and schema version; the pair export binds every answer to the immutable source hash.
3. Each reviewer selects scope, directly selects FYP labels, marks evidence and field spans, fills simple support links, and marks ambiguity with `needs_review`. The frozen policy in [the direct-label guide](../annotation/fyp_direct_label_v1_annotation_guide.md) covers action requests, report delivery, deadlines, departmental input, follow-ups, approvals, and general updates.
4. Compare the two submitted JSONL files or select both reviewers from the same filtered app export with `ai/scripts/compare_direct_annotations.py`. For an app export, pass its path for both `--reviewer-a` and `--reviewer-b` and provide `--reviewer-a-id` / `--reviewer-b-id`. Review scope agreement, exact label-set agreement, per-label supports/disagreements, descriptive micro/macro F1, exact and overlap span F1, review exclusions, and support relations separately. Do not interpret either reviewer as ground truth.

Example with one app export:

```powershell
python ai/scripts/compare_direct_annotations.py `
  --reviewer-a ai/data/annotated/human/fyp_direct_round_1/export.json `
  --reviewer-b ai/data/annotated/human/fyp_direct_round_1/export.json `
  --reviewer-a-id REVIEWER_SLOT_0_ID `
  --reviewer-b-id REVIEWER_SLOT_1_ID `
  --report ai/data/annotated/human/fyp_direct_round_1/agreement.json
```

For individual JSONL files, omit both reviewer-ID options and pass each file once. The same comparator rejects legacy Structured V1 annotation records instead of reinterpreting them.
5. An independent adjudicator reviews disagreements against the source, records a decision and concise reason, and keeps the two frozen blind records unchanged. Preserve original and adjudicated forms with provenance. Any genuine guide ambiguity is logged and resolved before expanding the round. A material rule change requires a versioned guide/schema decision and recheck of affected round records.
6. Promote only individually adjudicated, validated, eligible human records to human TRAIN. Keep uncertain records marked for review. Do not score this calibration set as a final held-out evaluation set, and do not auto-promote through a label tier field.

## Measurements and limits

Use paired source IDs and verify source hashes when the inputs provide them; the round app export includes the frozen source hashes. Scope agreement includes `UNCERTAIN` choices. Label, span, and support-relation metrics use only pairs where both scope decisions are definite and neither record needs review. Report excluded unresolved records as their own counts. Span exact match requires the same field, type, half-open offsets, and text; overlap match uses positive character overlap and maximum one-to-one matching per field/type so a span cannot support several matches. These are inter-annotator agreement measures, not accuracy.

The 47-source selection is deliberately enriched and based on a historical public corpus. It is useful for calibration workflow and rule consistency; it does not establish modern FYP-email prevalence or model accuracy. The current source allocation report establishes 11 holdout records, but this plan does not read their source bodies or any annotator responses. No gold count or agreement result exists until the human round and adjudication are complete.

## Launch gate

The direct schema, two independent reviewer paths, submission locking, two-review export gate, and additive 30-source overlay are verified with synthetic route and real SQLite migration fixtures. Production publication status is recorded in `fyp_direct_label_redesign_2026-10-06.md`. After successful publication, the first authenticated queue read freezes the overlay from the existing source hashes and shows the shared round first. Check that the shared first-round count is 30; an unexpected frozen inventory requires owner review rather than selecting from holdout. Actual two-person completion, private export and adjudication remain pending human work, so no human agreement or gold readiness is claimed before then.

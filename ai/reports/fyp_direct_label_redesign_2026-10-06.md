# Direct FYP human annotation — 2026-10-06

## Implemented workflow

Read the current message → decide project relevance → choose the actual FYP labels → highlight supporting words and fields → check and submit. New reviews use **fyp-direct-label-v1**. The five-act model and deterministic derived-label mapper are retained for legacy records and extraction research, and are not required for new human reviews.

The UI has four short steps, direct multilabel checkboxes, a plain-language example beside every label, per-label evidence tabs, copy/paste exact-phrase fallback, reusable highlights, an always-available guide, visible save state, independent-review attestation and locked submissions. Dates, documents and names are extraction fields beneath labels, not a hidden classification mechanism.

## Frozen label definitions and overlap policy

| Label | Meaning |
| --- | --- |
| MEETING | Arrange, confirm, change, cancel or substantively discuss a specific project meeting, call or workshop. |
| DEADLINE | Set, change, confirm or follow up a due date/time for project work or a deliverable. A meeting or occurrence date alone does not count. |
| REPORT_REQUEST | Request, expect or chase preparation/provision/submission of a formal project document or deliverable. Delivery alone does not count. |
| DEPARTMENTAL_INPUT | Request, track or report a contribution, input, data, feedback or decision from an organizational unit. Mere department mention does not count. |
| ACTION_REQUEST | Request or direct a distinct operational task. Do not duplicate the same report transfer, departmental input or approval transaction. |
| FOLLOW_UP | Remind, chase, check or escalate an earlier expectation; requires current reminder evidence. A first request or reply subject alone does not count. |
| APPROVAL | Request or communicate formal approval, sign-off or authorization, including rejection, withholding and conditions. Ordinary review/comments are not approval. |
| GENERAL_UPDATE | Meaningful project progress, completion, blocker, decision or work-state change. Never an informational fallback. |

- Report due Friday: REPORT_REQUEST + DEADLINE. Add ACTION_REQUEST only for a separate operational act.
- Departmental figures due Thursday: DEPARTMENTAL_INPUT + DEADLINE. Add REPORT_REQUEST only when the figures are an identified formal deliverable; a raw data request alone is insufficient.
- Ordinary review of a draft: ACTION_REQUEST. Formal request to approve it: APPROVAL.
- Communicated formal approval decision: APPROVAL + GENERAL_UPDATE.
- Explicit changed due date: DEADLINE + GENERAL_UPDATE.
- Completed/submitted departmental contribution: DEPARTMENTAL_INPUT + GENERAL_UPDATE.
- Report delivered: GENERAL_UPDATE. Missing report: GENERAL_UPDATE, and FOLLOW_UP only where current words actually chase the earlier expectation.
- First report request is not FOLLOW_UP. Reminder of a report request can have both labels.
- All co-occurrences are selected by the human. The system never adds a project label from an event state or span.

## Schema and validation

Classification (`scope`, `labels`) is distinct from extraction (`spans`, `label_support`). Spans use exact Unicode code-point offsets in subject/current message. Every selected project label requires linked current-message EVIDENCE. Subject fields can support extraction but cannot establish a label trigger; quoted history and excluded signatures cannot supply evidence.

DEADLINE requires DEADLINE_DATE or DEADLINE_TIME plus an applies-to description. REPORT_REQUEST requires REQUESTED_DOCUMENT. DEPARTMENTAL_INPUT requires DEPARTMENT and INPUT. ACTION_REQUEST requires ACTION_ITEM. APPROVAL requires APPROVAL_TARGET. FOLLOW_UP requires a simple target category. Missing specialized details may be represented with a per-label review question plus global needs_review and reason; the current trigger is still mandatory. Unclear follow-up targets require review.

NON_PROJECT is exclusive, has no project support/extraction and is set by relevance. UNCERTAIN requires a reason and review, with no project labels. PROJECT with no selected functions requires review instead of a forced fallback. Unknown labels/types/properties, duplicate IDs/coordinates, unsupported field associations, dangling links and orphan spans are rejected.

These are structural/source checks. They cannot prove that a highlighted phrase semantically denotes a true deadline, formal deliverable, actual unit contribution or reminder. Independent human judgment and adjudication remain necessary.

## Historical records and provenance

Existing drafts/submissions are not converted or overwritten. Legacy drafts open in a marked Structured V1 form, keep their stored mapper version (missing legacy mapper means 1.0), and submit through their original validator. The API rejects schema changes for saved records. New records use separate direct_reviews and direct_review_revisions tables. A reviewer can retain a legacy draft/submission and create a fresh direct review for the same source; neither record is converted or overwrites the other. Existing submitted reviews remain frozen; optimistic revisions and atomic revision logging remain.

The server replaces client provenance on every save. Drafts are UNANNOTATED; attested submissions are BLIND_HUMAN, stamped with authenticated identity/time and no AI prelabels. No submission becomes GOLD automatically. Unresolved cases, synthetic examples and AI-only labels cannot become real human gold. GOLD additionally requires a separate accepted human adjudicator. The blind UI does not show AI or peer responses. No stored human answer rows were inspected during this implementation.

## Actual calibration round

An additive, hash-bound round assignment overlay preserves the 24 frozen common blind emails and shares six existing calibration TRAIN emails chosen by immutable position. Source bytes, hashes, original allocation and personal ownership are unchanged. The 11 sealed holdout sources are excluded from this overlay and from first-round exports. The overlay initializes idempotently on an authenticated queue read only when the expected eligible source counts exist; the owner can also prepare it through Study controls. The generated schema-only migrations create the overlay and separate direct-review tables.

The first two registered reviewers independently review all 30 shared emails. A third can also complete them; third-reviewer participation is not required to unlock two-reviewer comparison. Export stays locked until both initial reviewers complete the shared round; only complete submitted participants and shared sources are exported. These examples remain in the intended 250 calibration set. No new AI annotation pilot was run and no human agreement or accuracy result is invented.

Legacy answers remain legacy and are not mixed into direct-label agreement. Existing legacy reviews do not prevent new direct double-annotations of the same source; they remain separately accessible in the legacy form.

## Agreement tooling

`ai/scripts/compare_direct_annotations.py` accepts direct JSONL or the private app export, selecting two reviewers explicitly where needed. Reports scope agreement, exact label-set agreement, per-label support/agreement/disagreements, descriptive interannotator micro/macro F1, exact span F1 and overlap span F1. Overlap matching is one-to-one within source field/type. Unresolved judgments are reported separately from clear label agreement. Relations, if supplied, are separate. Neither reviewer is treated as ground truth; legacy schemas are rejected and holdout is excluded.

## Remaining boundaries

No policy choice blocks starting the human round. Whether a cost breakdown is a formal deliverable, whether a team name identifies an organizational unit, whether business context demonstrates a bounded initiative, and whether terse missing-item wording genuinely chases an expectation still require source-level judgment. Flag those cases; adjudicate actual disagreements and version any later rule change explicitly.

## Verification and publication

Verified 40 Python tests (17 legacy, 8 direct validation, 13 agreement, 2 actual SQLite migration/round tests), 178 Node checks (51 legacy validation, 12 legacy guidance, 69 direct validation, 46 format/API/transition checks), TypeScript with no errors, and the production Worker build. The independent code review found no remaining actionable defect after fixes. Synthetic unit/route/SQLite tests do not establish live human usability or labeling accuracy; no live review submission was created for testing. The private audience is retained. Git contains source, schemas, guides, tests and this report; corpus content and reviewer responses remain private.

Published **Site version 6** successfully at https://fyp-email-calibration.faaiznoman713.chatgpt.site, from Site source commit `5788dfd2d9ed78eb11c69d8930fc9cbada46e0f6`. Custom private audience was retained. The bundled packager encountered the existing broken Windows WSL installation; native Windows tar packaged the verified production output and hosting manifest successfully. No WSL repair or system installation was performed.

**Ready for the first human round:** reload/sign in, then review the shared first-round emails shown first. The next authenticated queue read freezes the 30-email overlay from the existing eligible inventory; Study controls can repeat the idempotent preparation check. The initial two registered reviewers independently complete all 30, then the owner exports for comparison/adjudication. Actual agreement and human gold remain pending. The third reviewer can join later without blocking this two-person round.

# Data-first calibration and product schedule

Checkpoint date: 6 October 2026. The proposal dated July 2026 specifies a ten-month / forty-week plan. Its milestones are relative weeks; it does not establish an actual submission or defense date or the team's current academic week. The owner has not yet provided that date. Calendar commitments below are therefore measured from calibration launch and adjusted after the first human throughput sample.

## Immediate sequence

| Stage | Deliverable / exit condition | Timing |
|---|---|---|
| Contract and app | Executable V1 schema, guide, synthetic checks, private three-person review app | Current implementation checkpoint |
| First throughput sample | Each student submits ten shared examples independently; record active minutes and uncertainty | First available review sessions |
| Blind calibration | All three finish the frozen shared subset; personally assigned TRAIN/holdout sources stay separate | Estimate after the first ten: remaining review count × measured median minutes |
| Agreement and adjudication | Scope agreement, exact spans, linked role tuples, supports, uncertainty; resolve disagreements and correct guide | Immediately after shared round completion |
| Schema freeze (Gate A) | Accept rules only if supported agreement and audit are adequate; rerun a fresh blind subset after material changes | Before model training or labeler scaling |
| Labeler prototype (Gate B) | Structured outputs, exact-source validator, recorded model/run, abstention; prompt examples from human TRAIN only | After schema freeze |
| Held-out labeler evaluation | Blind adjudicated human holdout; per-label supports, structured/span/link scores and abstention; no synthetic pooled into evaluation | Before creating a larger silver batch |
| Gold expansion (Gate C) | Measured team capacity determines target; consented university/project sources preferred if authorized | After calibration timing/adjudication evidence |
| Span-link diagnostic (Gate D) | INCOMPLETE: no completed seed or saved trained checkpoint; earliest-attempt deadline expired | Closed for this architecture cycle; do not restart |

The retrieved corpus sample is deliberately enriched, not natural project-email prevalence. No human agreement or gold count is assumed. A heldout is not research gold merely because one student submits it; explicit review/adjudication remains required.

## Protect the desktop product

Reserve at least half of the team's development sessions for the Windows product while calibration runs asynchronously. Review the actual submission date with the supervisor before committing optional features.

| Product milestone | Acceptance demonstration | Ordering |
|---|---|---|
| Dashboard review flow | Manual corrections, source traceability, event cards and needs-confirmation state using synthetic fixtures | In parallel with calibration |
| Outlook 2016 ingest | Local pywin32 folder reading, stable deduplication and current/quoted separation; no automatic email sending | Before end-to-end integration |
| Local archive | Excel/local persistence, recoverable saves, normalized event relationships and audit trail | With dashboard review flow |
| Thread reasoning | Small initial verified transition set for changes, completion, delivery and reminders; unresolved links surface for review | After event schema stabilizes |
| Domain baseline (Gate E) | Leakage-safe FYP human supervision; simple baseline before added complexity | After human gold exists |
| Product readiness (Gate F) | Dashboard remains useful with abstention and human correction; source evidence and reminders validated end-to-end | Before model freeze |
| Final model/evaluation freeze | Fixed model, thresholds and independent real-source evaluation; closed historical TEST remains closed | Before final report claims |
| Report, installation and defense | Reproducible local install, user walkthrough, limitations, aggregate evidence and demo recovery plan | Reserve final academic buffer after actual deadline is known |

The proposal places Outlook prototyping at week 11, archive at 13, extraction at 15/19, dashboard at 21, thread logic at 22, reminders at 24, search at 27, integration at 35, pilot at 38 and report/viva at 40. These are planning anchors, not verified calendar deadlines. LAN multi-user desktop operation remains a later phase; the shared research annotation Site does not change the offline inference architecture.

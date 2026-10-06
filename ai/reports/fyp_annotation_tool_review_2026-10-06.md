# FYP annotation tool and schema review — 2026-10-06

## Result

The existing Structured V1 event model can represent the project-management work this tool targets. It supports multiple event instances in one email, evidence spans linked to individual events and roles, event states and attributes, dates, thread relations, and explicit uncertainty. A new schema version is not needed for this iteration.

The review improved the labeling guidance, made deterministic FYP labels visible in the app, and versioned their derivation so historical annotations keep their original meaning. The app and schema are suitable for a supervised human pilot. They are not yet a source of gold training data: there are no completed human calibration and adjudication results.

## Changes

- Added a read-only **Derived FYP labels** preview after source evidence and required fields validate. Annotators edit the event or its evidence instead of changing a derived label directly.
- Made the in-app scope rules more concrete. They distinguish a defined initiative or deliverable from routine business, and explain that a contract, data request, staffing message, raw data file, or request for comments does not by itself prove project scope, a report, or an approval.
- Clarified that a completed or cancelled task and a submitted, delivered, missing, or reviewed document already derive `GENERAL_UPDATE`; annotators should not add a duplicate status event for that same act.
- Added mapper version `fyp-derived-labels-1.1`. It derives `GENERAL_UPDATE` for the supported task and document states above. An annotation without this optional version continues to use the historical 1.0 mapping. New annotations use 1.1; saved drafts retain their recorded mapping through later saves and submission, with a missing historical version treated as 1.0. Existing submitted annotations are left frozen. The event schema remains V1.
- The server stamps provenance on draft and submitted records instead of trusting client-supplied provenance. Drafts remain unannotated; submission still requires the annotator's independent-review attestation.

## Blind AI design pilot

Two independent GPT-6 Luna runs at xhigh reviewed the same 24 common-pool cases before the guidance changes; two fresh independent runs reviewed the same cases after the changes. The reviewers did not see one another's annotations. The sealed holdout was not used. These figures measure AI-to-AI agreement only; they are not accuracy, human agreement, or proof that the guide caused the changes.

| Measure | Before revised guidance | After revised guidance |
| --- | ---: | ---: |
| Exact scope agreement | 17/24 (70.8%) | 19/24 (79.2%) |
| Exact derived-label-set agreement | 11/24 (45.8%) | 12/24 (50.0%) |
| `needs_review` agreement | 16/24 (66.7%) | 18/24 (75.0%) |
| Strict exact-span micro F1 | 0.316 | 0.371 |
| Strict exact event-role-link micro F1 | 0.321 | 0.318 |
| Valid annotations | 48/48, zero errors | 48/48, zero errors |
| Stored mapper labels disagreed with recomputation | 0 | 0 |

Span overlap counts an exact match only when case, field, span type, start, end, and text all match. Event-role-link overlap also requires the event kind, state and class, role, and exact linked span to match. These strict measures are useful for locating disagreement, not for deciding which reviewer is correct.

Scope, label-set, review-flag, and exact-span agreement improved in the second run; exact event-role-link F1 was essentially unchanged. The amount of annotation still varied: the first pair marked 39 and 47 events, while the second pair marked 64 and 43. This means boundary and event-selection guidance needs real human calibration and adjudication before expanding the dataset.

## Additional stress test

A user-supplied long-message example was represented as eight event instances with 24 evidence spans. The validator accepted it, and deterministic mapping did not treat a meeting date as a deadline. This checks schema capacity for dense messages; it is a single interpretive example, not a human gold annotation.

## Verification

- Python Structured V1 tests: 17 passed.
- App validation: 16 synthetic fixtures and 51 checks passed.
- In-app guidance: 12 checks passed, including the scope, document, and approval contrasts.
- TypeScript: `tsc --noEmit` passed.
- Production build: completed successfully.
- Both AI passes independently validated 24/24 annotations with zero hard errors and zero mapper mismatches. Uncertainty warnings were retained rather than edited away.

The AI pilot did not measure time per email or usability with the three human annotators. The next readiness gate is a blind human overlap pilot in the app, followed by adjudication of disagreements and measurement of completion time. Keep AI annotations as silver suggestions until that work is complete; do not call them gold or use them as human ground truth.

## Data handling

The report contains aggregate results only. Email bodies, source identifiers, reviewer identities, and per-case annotation files remain local and excluded from Git. The shared app's current access list was preserved.

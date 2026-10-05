# FYP Structured Schema V1 migration decision

**Decision date:** 2026-10-05  
**Decision:** Keep the existing V2/native formats intact and add an isolated, versioned V1 annotation contract for calibration and review.

## Decision

V1 is a new annotation and derived-label layer. It does not migrate or rewrite existing records. V1 collapses the prior collection of task-specific structures into five event kinds—MEETING, ACTION, DOCUMENT, APPROVAL, and STATUS—with one state field per event kind. Action and document subtypes remain attributes; they are not extra event kinds or model heads.

V1 represents evidence as exact, typed spans in the current source, then connects those spans to events with explicit roles. Shared evidence is one span linked to each applicable event. Prior-message facts are referred to by resolved source and event IDs through FOLLOW_UP_OF or SUPERSEDES relations. Prior spans are not copied into the current record. Scope is PROJECT, NON_PROJECT, or UNCERTAIN. Labels are derived from validated facts and are not annotator-entered fields.

## Evidence reviewed

The decision uses the existing implementation and guidance as design input:

- `ai/config/structured_primitive_schema.json` — existing structured schema and its event/argument representation.
- `ai/annotation/structured_v2_review_guidelines.md` — V2 annotation and review boundary guidance; it reports no human gold set.
- `ai/reports/structured_annotation_schema.md` — schema rationale and existing annotation design.
- `ai/src/structured/mapper.py` — existing mapping behavior used to preserve the nine downstream labels.
- Proposal scope and alignment material — attachment contents, organizational hierarchy, persistence, and dashboard behaviors are separate work areas.

The existing V2 shape was more granular, splitting actors, actions, documents, departments, temporal facts, meetings, deadlines, approvals, statuses, thread changes, and act types into separate collections. V1 keeps the useful typed evidence and relation ideas while reducing the number of annotator decisions and making event ownership explicit. Exact offsets and the nine derived labels preserve traceability and downstream compatibility.

No protected TEST/EVAL source records were opened. The V1 examples are synthetic and explicitly marked as such; they are schema fixtures only, not human calibration evidence, gold data, or accuracy results.

## Compatibility and migration

- The public canonical schema, V2 schema and annotation files, and native MailEx artifacts remain unchanged.
- V1 records use `schema_version: fyp-structured-v1` and live in new `fyp_structured_v1_*` files and the `ai/src/fyp_structured_v1` package.
- There is no bulk conversion from V2 to V1. If selected records are later annotated in V1, preserve the original record and store the V1 annotation separately with its source reference and provenance.
- `NON_PROJECT` remains a supported completed decision and is exclusive: it carries no events or relations. `UNCERTAIN`, unresolved prior links, unclear roles, and OTHER/UNCERTAIN classes require review and suppress derived labels.
- Each current event needs an authored current-message EVENT_ANCHOR. Subject text may support scope or arguments, but cannot anchor a current event. Exact spans use zero-based, end-exclusive Python Unicode code-point offsets.

## Provenance and label status

V1 distinguishes source origin (REAL_EMAIL, PUBLIC_CORPUS, SYNTHETIC, UNKNOWN), annotation tier (UNSET, GOLD, SILVER, SYNTHETIC), and production mode (including blind human and AI-assisted human work). A blind individual submission stays UNSET until adjudication. GOLD requires explicit human review plus annotator and timing metadata; an AI-assisted adjudicated record retains AI run/protocol details and the human disposition. The contract makes these fields representable but does not assert that any human-reviewed examples exist.

The nine labels—MEETING, DEADLINE, REPORT_REQUEST, DEPARTMENTAL_INPUT, ACTION_REQUEST, FOLLOW_UP, APPROVAL, GENERAL_UPDATE, and NON_PROJECT—are deterministic mapper outputs. V1 abstains on uncertain or review-needed records. Current guidance establishes no human gold set, so there is not yet evidence to claim calibrated label quality, annotator agreement, model readiness, or evaluation performance.

## Open work before calibration or training

1. Finish parity review between the Python validator and the Sites form/backend validator, especially source ranges, role compatibility, provenance, relations, and review warnings.
2. Freeze the form contract and guide after owner review; keep the synthetic fixtures as contract tests, not as a substitute for human annotation.
3. Select a permitted, representative calibration sample and define privacy handling, source references, and authorized annotators. No real sample or timeline is specified here.
4. Collect independent blind annotations that remain unexposed to prelabels, then adjudicate disagreements with identity and timing recorded. Measure agreement and annotation effort before making quality or staffing claims.
5. Keep AI-assisted examples SILVER until a human explicitly reviews them under the agreed protocol. Define a separate blind evaluation set before any evaluation use; reject synthetic and AI-assisted records from that set.
6. Decide, based on the calibration results, whether to revise the schema/guide and whether to train or evaluate a model. Do not train or report performance from the current synthetic fixtures.

## New V1 artifacts

- `ai/config/fyp_structured_v1_schema.json` — executable JSON Schema and shared x-semantics contract.
- `ai/src/fyp_structured_v1/validation.py` and `mapper.py` — Python structural/semantic validation and derived labels.
- `ai/annotation/fyp_structured_v1_annotation_guide.md` — annotation rules and contrastive decisions.
- `ai/annotation/fyp_structured_v1_synthetic_examples.jsonl` — synthetic provenance-marked machine-readable cases.
- `ai/tests/test_fyp_structured_v1.py` — contract checks for offsets, evidence, links, relations, provenance, review, and labels.

These additions establish an executable V1 contract. The separate Sites UI/JS parity work is tracked by its owner and is not claimed complete by this report.

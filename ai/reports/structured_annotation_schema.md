# Internal structured annotation schema and mapper

Status: internal v2-alpha review artifact
Canonical contract: unchanged; this schema is not a replacement for `ai/annotation/label_schema.json`.

## Purpose

The structured annotation separates scope, speech acts, entities, events, dates, and relations. The mapper derives the existing nine FYP labels from exact evidence plus typed targets and states. It does not extract primitives, run keyword rules, or accept a separate final-label prediction. The test strings are synthetic contract fixtures, not training annotations or claims about real-email accuracy.

Schema: `ai/config/structured_primitive_schema.json`
Implementation: `ai/src/structured/validation.py`, `ai/src/structured/mapper.py`
Tests: `ai/tests/test_structured_mapper.py`

## Python API

```python
from src.structured import map_labels, validate_annotation

validation = validate_annotation(
    annotation,
    current_source_id="authentic-source-message-id",
    sources={
        "authentic-source-message-id": {
            "subject": "Project Orion",
            "current_message": "Please send the revised report by Friday.",
        },
        "earlier-source-message-id": {
            "subject": "Report request",
            "current_message": "Please prepare the revised report.",
        },
    },
)

result = map_labels(
    annotation,
    current_source_id="authentic-source-message-id",
    sources=sources,
)
# result.labels, result.needs_review, result.explanations,
# result.review_reasons, result.validation_errors
json_safe = result.to_dict()
```

`ValidationResult.valid` is false when shape, exact-text evidence, IDs, enums, source references, or cross-field relations fail. Invalid input returns no labels and requires review. The mapper never repairs invalid data.

Every evidence item identifies a source ID, field (`subject` or `current_message`), inclusive start, exclusive end, and exact text. Offsets are Python Unicode code points. The current source ID is an explicit argument and is also stored on the annotation. Every act and every relation that can create a label needs current-source `current_message` evidence.

The caller supplies exact source strings separately. If a supplied `current_message` contains quotes/forwarded history, also supply `authored_ranges: [{start, end}]`; current evidence must fit completely within one range. When ranges are omitted, the caller asserts that `current_message` already contains only authored current text. The validator does not guess quote boundaries. Context evidence must name an authentic earlier source in the same `sources` map. It can establish a prior expectation for a chase or help resolve identity; it cannot replace evidence of the current act.

## Primitive inventory

| Collection | Main fields and constrained states |
|---|---|
| `project_scope` | `PROJECT`, `NON_PROJECT`, or `UNCERTAIN`; categorical confidence and exact subject/current-message evidence |
| `actors` | Person/group/department/role/unknown; named status, name evidence and confidence |
| `actions` | requested, assigned, committed, completed, cancelled; category: operational, document transfer, departmental contribution, approval transaction, other, uncertain; optional actor reference |
| `documents` | requested, expected, submitted, delivered, missing, reviewed, unknown; document type: project deliverable, other, uncertain; named or explicit unnamed state |
| `departments` | contributor, owner, recipient, mention-only; names and supporting evidence |
| `temporal_entities` | Separate exact-text `DATE` and `TIME` items, linked by ID |
| `meetings` | proposed, scheduled, rescheduled, cancelled, completed; optional date/time/participant IDs |
| `deadlines` | Explicit due-relation evidence; date/time IDs; target must be an existing action or document |
| `approvals` | requested, granted, rejected, withheld, conditional; formal, informal, uncertain; typed target |
| `status_updates` | progress, completed, blocker, decision, work-state change, other |
| `thread_changes` | current chase, escalation, future follow-up instruction, state changes; typed target and prior-expectation evidence |
| `acts` | Speech act, typed target, evidence, categorical confidence. There is no final-label/function field. |

All item IDs are globally unique across primitive collections. Evidence IDs are unique in their own collection. References resolve to the expected collection; unknown keys and enum values are rejected. Confidence uses only `supported` or `uncertain`, never fabricated numeric probability.

## Deterministic mapping rules

| Existing label | Required supported structure |
|---|---|
| `MEETING` | Current act targets a specific meeting; proposal/schedule/reschedule/cancel state must agree with its speech act. A bare scheduling transaction does not also create `GENERAL_UPDATE`. |
| `DEADLINE` | Current deadline act, explicit due-relation evidence, at least one current date/time entity, and an existing action/document target. A meeting date or testing window cannot be a deadline target. |
| `REPORT_REQUEST` | `REQUEST` targets a requested `PROJECT_DELIVERABLE`, or an explicitly evidenced implicit formal deliverable. A document merely expected, due, delivered, or mentioned is not a request. A supported current chase of a formal deliverable also derives this label. |
| `DEPARTMENTAL_INPUT` | Request/inform/remind targets a department whose role is explicitly `contributor`. Recipient and mention-only roles do not qualify. |
| `ACTION_REQUEST` | `REQUEST` targets an operational action in requested/assigned state. Document transfer, departmental contribution, approval transaction, and other action categories do not qualify. A separate operational request can coexist with a document request. |
| `FOLLOW_UP` | Current request/reminder targets a current-chase/escalation thread change and an explicit-current or context-supported prior expectation. An unknown prior expectation is suppressed and requires review. A future instruction to follow up is an operational action, not a current chase. |
| `APPROVAL` | Compatible request/decision speech act targets a formal approval record. Informal or uncertain formality cannot emit the label. |
| `GENERAL_UPDATE` | A current act targets a substantive status update in a known status category. Generic `other` is review-only. |
| `NON_PROJECT` | Supported out-of-scope scope decision; exclusive. Uncertainty elsewhere preserves the label but sets `needs_review`. |

An uncertain scope returns an empty label list and requires review. An uncertain high-risk target/relation suppresses its dependent label while independent supported labels may still emit. Every emitted label includes a rule ID and evidence IDs in `explanations`; suppressed candidates and review reasons are also surfaced.

## Validation and review boundaries

- Due dates require a due relation and an existing action/document target; linked date/time text must occur in the current message.
- Context-only evidence cannot create a current speech act, request, deadline, or status update.
- A context-dependent chase must cite earlier source evidence. A current explicit chase may establish the expectation without an earlier message. Unknown chase context is not converted into a fact.
- Explicit requests may use unnamed/implicit entities only through an explicit target type and supporting evidence; an implicit document request must identify its target as a project deliverable or remain uncertain.
- Formal approval does not follow from ordinary review, agreement, attendance, or receipt.
- A bare department mention or copy recipient does not establish a contribution.
- Completed actions and delivered documents remain representable as states; they do not become new requests merely because they contain action/document language.
- NON_PROJECT records can retain actor/date entities, but those entities’ uncertainty still marks the mapped result for review.
- No source text, canonical schema, annotation guidelines, V1 artifact, or review workflow was changed for this work.

## Verification

Focused command:

```powershell
cd ai
.\.venv\Scripts\python.exe -m unittest tests.test_structured_mapper
```

Result: 52 tests passed. The suite covers illustrative guideline examples and boundaries, non-BMP Python offsets, forged/missing evidence, quote ranges, wrong-target dates, scope uncertainty, uncertainty propagation, formal-vs-informal approval, implicit targets, department recipient/mention boundaries, action/document coexistence, and malformed values. These tests validate code contracts only; they are not model training or annotation truth.

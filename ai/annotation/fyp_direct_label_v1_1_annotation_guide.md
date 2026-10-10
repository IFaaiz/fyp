# FYP direct-label annotation guide v1.1

**Schema:** `fyp-direct-label-v1.1`
**Use:** shared human calibration and later human-adjudicated FYP training data

This guide applies to new v1.1 records. The v1 schema, records, reports, and guide remain historical and unchanged. Do not convert old records or derive these labels from another act ontology.

## 1. Annotation order

1. Decide scope from the current authored message and permitted thread context.
2. Select the direct FYP labels that the current message supports.
3. Mark current-message evidence and any applicable extraction fields.
4. Save a draft or submit. Mark genuine uncertainty for review.

Do not build an event graph. During blind annotation, do not view peer answers or AI suggestions.

## 2. Scope and direct labels

Choose one scope:

- `PROJECT`: the current message concerns a bounded initiative, workstream, milestone, or project deliverable.
- `NON_PROJECT`: the message is clearly routine, personal, or unrelated work. Select only `NON_PROJECT`.
- `UNCERTAIN`: available evidence does not establish project relevance. Leave labels empty and mark `needs_review`.

For `PROJECT`, select every directly supported label; multiple labels are allowed when distinct acts or updates are present.

| Label | Use when the current message… |
|---|---|
| `MEETING` | Schedules, confirms, changes, cancels, or substantively discusses a specific project meeting, call, or workshop. |
| `DEADLINE` | Sets, changes, confirms, or follows up on a due date or time for a project action or deliverable. |
| `REPORT_REQUEST` | Requests or follows up on preparing, submitting, or providing a formal project document or deliverable. |
| `DEPARTMENTAL_INPUT` | Requests, tracks, or reports a project contribution, input, data, feedback, or decision from a department or unit. |
| `ACTION_REQUEST` | Requests, assigns, or directs a concrete operational project task distinct from another selected act. |
| `FOLLOW_UP` | Reminds, chases, checks, or escalates a previously expected project action, response, document, approval, or contribution. |
| `APPROVAL` | Requests, grants, rejects, withholds, or conditions formal project approval, sign-off, or authorization. |
| `GENERAL_UPDATE` | Communicates meaningful project progress, completion, blocker, decision, status, or change in work state. |

Preserve these boundaries:

- A meeting date is not a deadline; a normal date alone does not imply `DEADLINE`.
- Mentioning or delivering a document is not `REPORT_REQUEST`.
- Mentioning a department does not imply `DEPARTMENTAL_INPUT`; mentioning a person does not assign responsibility.
- “Please review” is not `APPROVAL` unless formal sign-off or authorization is requested.
- A `Re:` subject alone is not `FOLLOW_UP`; current reminder or chase wording is needed.
- `GENERAL_UPDATE` is not a fallback. Do not add `ACTION_REQUEST` for the same act already represented by `REPORT_REQUEST`, `DEPARTMENTAL_INPUT`, or `APPROVAL`.
- Current authored wording determines labels. Thread history can clarify a current reminder, but quoted historical text cannot create a current act or serve as its evidence.

## 3. Evidence and extraction fields

Every selected project label needs at least one `EVIDENCE` span from the current authored message. `EVIDENCE` is an auxiliary support highlight, not an extraction target. Scope evidence may also use it.

The only extraction-span types for v1.1 are these 11:

`MEETING_DATE`, `MEETING_TIME`, `DEADLINE_DATE`, `DEADLINE_TIME`, `ACTION_ITEM`, `RESPONSIBLE_PARTY`, `DEPARTMENT`, `REQUESTED_DOCUMENT`, `PARTICIPANT`, `AGENDA`, `PROJECT`.

Add an extraction span when its information is stated and useful. Each span must be accurate and match the exact source text; fields are not prerequisites for selecting a semantically supported label. Do not fabricate omitted details. `INPUT` and `APPROVAL_TARGET` are not v1.1 extraction types.

Strongly prefer marking ACTION_ITEM for an explicitly written operational task
and DEADLINE_DATE / DEADLINE_TIME for an explicitly written due date or time.
These remain optional for semantically clear implicit cases.

- “The submission is overdue” can support `DEADLINE` without an explicit date span. Do not mark it for review solely because the date is absent.
- `APPROVAL` does not require an approval-target span. Use current-message evidence and any applicable stated fields.
- For `DEPARTMENTAL_INPUT`, use the direct label and mark `DEPARTMENT` when a department is stated. A clear contribution request can be labeled even when no department argument is written.
- A date, person, department, or document span may support more than one label when appropriate. Reuse its span ID rather than duplicating the span.

Use exact, minimal offsets into `subject` or `current_message`. Offsets are Unicode code-point positions with half-open ranges `[start, end)`; the stored text must equal the source field slice. Do not anchor spans to quoted history, signatures, or email metadata. Preserve the source hash and server-stamped provenance.

## 4. Review and comparison

Use `needs_review` for genuine scope or label uncertainty, unclear interpretation, an unresolved thread reference, or another case that needs adjudication. Missing optional extraction fields alone are not a review reason. `UNCERTAIN` scope must have no selected labels and must be marked for review.

The comparison report scores scope for every aligned pair. Label and extraction agreement use only pairs where both scope choices are definite and neither record needs review. Extraction exact and overlap metrics count only the 11 extraction types. Auxiliary `EVIDENCE` agreement is reported separately and never contributes to extraction counts, F1 denominators, or extraction support counts. Agreement is descriptive; neither reviewer is gold, and no record is promoted automatically.

The first shared round contains 30 eligible real/public-corpus emails, shown independently to the first two reviewers with peer answers hidden. These emails are part of the human calibration dataset, not a disposable pilot or final test set. The sealed holdout remains excluded, and adjudication remains separate.

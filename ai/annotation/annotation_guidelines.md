# Email annotation guidelines

Version: 1.0.0
Canonical format: one JSON object per email in JSONL.
Scope: English-language Outlook 2016 project emails for V1.

## 1. Purpose and scope

Annotate the current email message so that the future system can identify project-management communication and extract the meeting, deadline, responsibility, action, document, department, agenda, and project details needed for an Excel archive and dashboard. A message may serve several functions at once. Treat classification as multi-label.

For this dataset phase, use the longer FYP Proposal Report as the controlling scope: subject, current email body, Outlook metadata, thread context, and attachment filenames are available. Do not annotate text from PDF, Word, or scanned attachment contents. Preserve `raw_body`; use `current_message` as the main content for labels and span offsets. The revised proposal discusses attachment-content extraction, but that is a later extension and is outside this V1 annotation task.

Each record follows the shared contract: `email_id`, `source_dataset`, `thread_id`, `turn_index`, `subject`, `raw_body`, `current_message`, `clean_body`, `thread_context`, `sender`, `recipients`, `cc`, `sent_at`, `attachment_names`, `labels`, `spans`, and `annotation`. Store records as JSONL. Never replace or rewrite raw source text to make an annotation easier.

## 2. Classification procedure

1. Read `subject` and `current_message`. Use `thread_context` and metadata only to resolve references, determine whether the current message is a follow-up, or understand who a pronoun refers to. Do not copy old messages' labels or spans onto the current message.
2. Decide whether the current message contains any in-scope project-management content. Assign each supported label independently.
3. If the message is clearly unrelated to project-management work, assign only `NON_PROJECT`.
4. If classification evidence is missing, conflicting, or too incomplete to decide, keep `labels` empty, set status to `unlabelled`, and record `needs_review: true` with a short `ambiguity_note` when available. For ordinary unresolved annotations, leave `spans` empty. Exception: preserve directly mapped spans from an annotated source such as MailEx only when the mapping is explicit and the text offsets are verified; set `annotation_source` to `dataset`. These provisional spans do not supply classification labels and are not human-reviewed or gold. An empty label array is never a negative target.
5. Record span text exactly and calculate offsets against the selected source field. Do not normalize, paraphrase, or infer text that is absent.

The complete machine-readable label inventory is in `label_schema.json`. The definitions and boundary instructions below control annotation decisions.

## 3. Classification labels

### MEETING

Apply when the current message schedules, confirms, changes, cancels, or substantively discusses a specific project meeting, including a design review, status meeting, planning meeting, or meeting agenda. A specific date or time is not required if the meeting itself is clear.

- Positive: “The design review is moved to Friday.”
- Positive: “Can we meet next week to review the launch plan?”
- Negative: “I have a dentist appointment Friday.” (`NON_PROJECT`, if fully reviewed.)
- Negative: “Please send the report by Friday.” (deadline and document request, but no meeting.)

Do not label general references to people “meeting” socially or an unrelated calendar entry.

### DEADLINE

Apply when a project action or deliverable has a stated, changed, confirmed, or chased due date/time. The date may be explicit (“30 September”), relative (“next Friday”), or conventional (“COB tomorrow”). A date with no due/finish meaning is not a deadline.

- Positive: “The report is due Friday.”
- Positive: “The deadline has moved from 26 to 30 September.”
- Negative: “The review meeting is Friday.” (meeting date only.)
- Negative: “We completed the task yesterday.” (status only; no deadline.)

Annotate a due date as `DEADLINE_DATE` and an explicitly stated due time as `DEADLINE_TIME`. For “submit by 5 PM”, label `DEADLINE` and span “5 PM” as `DEADLINE_TIME`; for “by Friday at 3 PM”, span “Friday” and “3 PM” separately. “COB” is a conventional time expression; annotate it as written, without assuming a local clock time.

### REPORT_REQUEST

Apply when the current message explicitly asks for preparation, submission, provision, or delivery of a project report or formal project deliverable, or explicitly follows up on an earlier such request. This project label covers the document-request class, including reports, presentations, meeting minutes, plans, and comparable project documents. A bare statement that a report is due is a `DEADLINE`, not by itself a `REPORT_REQUEST`; the named expected deliverable may still be extracted as `REQUESTED_DOCUMENT`.

- Positive: “Please send the revised report.”
- Positive: “The minutes of meeting are still missing; please share them today.”
- Positive: “Prepare a presentation for the steering committee.”
- Negative: “The final report is due Friday.” (use `DEADLINE`; a due statement alone is not a request, though `final report` may be a `REQUESTED_DOCUMENT` span.)
- Negative: “The final report was sent yesterday.” (completed status alone; use `GENERAL_UPDATE` if it reports project status.)
- Negative: “Please approve the report.” (approval request alone; do not infer a request to send or prepare it.)

A stated due date can co-occur as `DEADLINE`. A request for numbers, feedback, or departmental input without a requested formal document is not automatically `REPORT_REQUEST`.

### DEPARTMENTAL_INPUT

Apply when the current message requests, tracks, or reports a project contribution from a department or organizational unit. Inputs include data, estimates, feedback, decisions, review comments, and other contributions needed by the project.

- Positive: “Finance, please provide the revised cost estimate.”
- Positive: “We are still waiting for Marketing’s launch figures.”
- Negative: “Finance approved the report.” (apply `APPROVAL`; add this label only if the department is supplying project input.)
- Negative: “The Finance Department changed its office hours.” (`NON_PROJECT`, if unrelated to project work.)

Use `DEPARTMENT` for the exact department/unit name when it performs or is asked for the input. A department name mentioned incidentally is not enough.

### ACTION_REQUEST

Apply when the current message asks, directs, or assigns a concrete project task that is not merely the document submission, departmental input, or formal approval already captured by another request label. This closes the action-only gap without treating an in-scope task as `NON_PROJECT` or forcing `GENERAL_UPDATE`.

- Positive: “Ali, please contact the vendor and confirm installation.” → `ACTION_REQUEST`; annotate “Ali” as `RESPONSIBLE_PARTY` and “contact the vendor and confirm installation” as `ACTION_ITEM`.
- Positive: “Please test the new release by Friday.” → `ACTION_REQUEST` + `DEADLINE`.
- Negative: “Please send the revised report.” → `REPORT_REQUEST` alone when sending that document is the only requested work.
- Negative: “Finance, provide the revised figures.” → `DEPARTMENTAL_INPUT` alone when providing those figures is the only requested work.
- Negative: “Please approve the plan.” → `APPROVAL` alone when approval is the only requested work.

If a message separately asks for an operational task and a report, assign both `ACTION_REQUEST` and `REPORT_REQUEST`. A project task reported as already completed is usually `GENERAL_UPDATE`, not `ACTION_REQUEST`. This is a classification label; an `ACTION_ITEM` span can appear with other labels without automatically adding `ACTION_REQUEST`.
### FOLLOW_UP

Apply when the current message reminds, chases, checks, or escalates a previously expected or assigned project action, response, or deliverable. Thread context may show that a short question is a follow-up; the current message must still perform the check/reminder.

- Positive: “Following up on the report due yesterday—when can we expect it?”
- Positive with context: earlier thread requests Finance’s figures; current message says “Could you send those figures today?”
- Negative: “Please send the initial project plan.” (new request without prior expectation.)
- Negative: “Follow up with the vendor after the meeting.” (a new action instruction to follow up in the future is an `ACTION_ITEM`, but not necessarily a current `FOLLOW_UP`.)

Follow-up can co-occur with `REPORT_REQUEST`, `DEPARTMENTAL_INPUT`, `DEADLINE`, or `APPROVAL` if the current message expresses those functions too.

### APPROVAL

Apply when the current message asks for, grants, rejects, withholds, or makes conditional a formal project approval, sign-off, or authorization. Both the request and the decision are relevant.

- Positive: “Please approve the revised project plan.”
- Positive: “The steering group has approved the revised schedule.”
- Positive: “Approval is conditional on the security review.”
- Negative: “Please review the plan and send comments.” (review is not necessarily approval.)
- Negative: “I approve of the new coffee machine.” (`NON_PROJECT` if outside project work.)

Do not infer approval from silence, attendance, receipt, or a positive-sounding comment without an explicit approval decision/request.

### GENERAL_UPDATE

Apply when the current message states a project status, progress, completion, blocker, decision, or change in work state. This label is additive, not a fallback exclusive class.

- “Testing of Phase 2 was completed yesterday.” → `GENERAL_UPDATE`
- “The testing phase is complete and the final report is due Friday.” → `GENERAL_UPDATE` + `DEADLINE`
- “The testing phase is complete. Please submit the final report by Friday.” → `GENERAL_UPDATE` + `DEADLINE` + `REPORT_REQUEST`
- “The design review is moved to Friday.” → `MEETING`; add `GENERAL_UPDATE` only if the email also reports project progress/status, not for a bare scheduling transaction.
- “Attached is the weekly status report.” → `GENERAL_UPDATE` if it communicates status; add `REPORT_REQUEST` only if the current message explicitly asks for the document or follows up on an earlier request; a bare due-date statement is not enough.

Do not use `GENERAL_UPDATE` for a greeting, acknowledgment, or unrelated news that conveys no project status or progress. When the current message only says “Thanks” or “Agreed,” use `unlabelled` if its function cannot be established as an in-scope update; do not copy labels from the quoted history.

### NON_PROJECT

Use this internal filter label for a clearly reviewed email outside the defined project-management scope, such as personal arrangements, general company/social notices, unrelated commercial discussion, or an email whose only topic has no project meeting, due action, formal project document, departmental input, follow-up, approval, or progress/status content, or a concrete project task.

- Positive: “Would you like to have lunch tomorrow?” → `NON_PROJECT`
- Positive: an unrelated personal travel receipt with no project relevance → `NON_PROJECT`
- Negative: “The migration is complete; the audit report is due Friday.” → project labels, never `NON_PROJECT`.
- Negative: a bare or ambiguous fragment with no context → leave unlabelled and review; do not assume it is unrelated.

`NON_PROJECT` must be the only classification label on a record. A message that contains both unrelated chatter and a project action receives the project labels only; do not add `NON_PROJECT` to mixed content.

## 4. Multi-label and ambiguity rules

Assign all labels supported by the current message. Do not use a ranking, softmax, or “main intent” choice. Examples:

| Current message | Labels |
| --- | --- |
| “The review is Friday at 3 PM.” | `MEETING` |
| “Please submit the report by Thursday.” | `DEADLINE`, `REPORT_REQUEST` |
| “Ali, contact the vendor and confirm installation.” | `ACTION_REQUEST` |
| “Finance will send the estimates by Thursday; please approve the plan.” | `DEPARTMENTAL_INPUT`, `DEADLINE`, `APPROVAL` |
| “The pilot is complete. Marketing’s figures are overdue; please send them by COB.” | `GENERAL_UPDATE`, `DEPARTMENTAL_INPUT`, `FOLLOW_UP`, `DEADLINE` |
| “The design review is moved to Friday at 3 PM. Send the revised report by Thursday for approval.” | `MEETING`, `DEADLINE`, `REPORT_REQUEST`, `APPROVAL` |

Do not add a label merely because a keyword appears. For instance, “I’ll follow up with you next week” can be a future action rather than a follow-up already occurring; “approved vendor list” may name a document without expressing an approval request or decision.

When context does not settle an interpretation, do not guess. Keep classification `labels` empty, set `annotation.status` to `unlabelled`, and add a brief ambiguity note / `needs_review: true` where available. Leave ordinary spans empty; only explicit source-mapped provisional spans may remain, as described in Section 7. `human_reviewed` with no labels is allowed only after a reviewer explicitly resolves that none of the defined labels applies; document the out-of-inventory reason and exclude that record from positive-label training. It does not mean `NON_PROJECT` or a negative example. Use `NON_PROJECT` for confirmed out-of-scope messages.

## 5. Extraction spans

### Span source and offsets

- By default, `start` and `end` refer to `current_message`. Add `field: "subject"` only when the annotated text occurs in `subject` and not in `current_message`.
- `start` is inclusive and `end` is exclusive. Offsets count Python Unicode string code points, not bytes or UTF-16 code units.
- `text` must exactly equal `record[field][start:end]`, including case and punctuation internal to the phrase. Trim surrounding whitespace and unrelated punctuation.
- Keep the shortest complete phrase that expresses the span. Do not normalize “next Friday” to a calendar date or “COB” to a time.
- If the exact text occurs more than once, identify each distinct relevant occurrence or flag the record for review if it is unclear which occurrence is intended. Never invent an offset for text that does not occur in the selected field.
- Overlapping spans are allowed when one phrase has two roles. For “submit the revised budget report,” `ACTION_ITEM` may cover the action phrase and `REQUESTED_DOCUMENT` may cover “revised budget report.”
- Span offsets must not point into `raw_body`, `clean_body`, or `thread_context`. Raw text remains available for audit; the annotation source is fixed as above.

### Span definitions and boundary examples

| Span label | Annotate | Boundary guidance |
| --- | --- | --- |
| `MEETING_DATE` | Meeting calendar or relative-date expression | “Friday” in “meet Friday at 3 PM”; do not include the separate time. |
| `MEETING_TIME` | Meeting time expression | “3 PM”; include a range or zone only when part of the stated time (“10–11 AM PKT”). |
| `DEADLINE_DATE` | Due-date expression tied to an action/deliverable | “Friday”, “tomorrow”, “30 September”; keep a separately stated due time outside this span. |
| `DEADLINE_TIME` | Explicit due-time or conventional end-of-day expression | “5 PM”, “3 PM”, or “COB”; do not infer a clock time from a date-only deadline. |
| `PARTICIPANT` | Named attendee or group explicitly participating in a meeting/activity | Annotate “Ali” in “Ali and Sara will attend”; not every person appearing in the message. |
| `RESPONSIBLE_PARTY` | Explicitly named owner/assignee/committer | Annotate “Ali” in “Ali will prepare the report.” Do not annotate an email address copied from metadata or bare “I/we”; resolve pronouns only for interpretation. |
| `DEPARTMENT` | Relevant department/unit name | Annotate “Finance Department”; omit possessive punctuation if it is not part of the name. |
| `AGENDA` | Explicit discussion topic | Annotate “Q3 launch risks” in “Agenda: Q3 launch risks”; do not annotate the label word “Agenda:” alone. |
| `ACTION_ITEM` | Complete requested, assigned, committed, or explicitly chased action | Annotate “submit the revised report,” not just “submit” and not the adjacent deadline. In “has Finance sent the Q3 cost figures?”, annotate “sent the Q3 cost figures” when the thread establishes that it is the action being checked. |
| `REQUESTED_DOCUMENT` | Named document/material that is explicitly requested, stated as expected, or being followed up | Annotate “final report” in “The final report is due Friday”; a `REQUESTED_DOCUMENT` span does not automatically imply `REPORT_REQUEST`. Preserve meaningful modifiers such as “monthly” or “signed.” |
| `PROJECT` | Specific project name or identifier | Annotate “Orion migration”; do not annotate “the project.” |

Annotate only explicit textual evidence. When the message says a report is requested but never names the document, a `REPORT_REQUEST` label is appropriate and a `REQUESTED_DOCUMENT` span is not. The dataset does not currently have a separate approval-target span; do not create unregistered span labels.

## 6. Metadata, quoted text, and thread context

Outlook already provides `sender`, `recipients`, `cc`, `sent_at`, conversation/thread identity, and attachment filenames. Preserve these as metadata. Do not generate NLP spans for those fields, copy names from recipients into `PARTICIPANT`, or infer a textual `RESPONSIBLE_PARTY` solely because someone sent or received the email. An attachment filename is metadata, not a `REQUESTED_DOCUMENT` span; annotate the document span only if the current message text refers to the requested document.

Annotate the current authored message, not quoted/forwarded content. A reply may quote an earlier request; the earlier request's classification and spans belong to its own message record. A short current reply such as “Could you send that today?” can be labeled as `FOLLOW_UP` if `thread_context` establishes a previous request. Do not re-annotate the old document name or owner unless repeated in the current message. If quoted text cannot be separated reliably, annotate only clear unquoted current text and flag uncertainty.

Use thread context as evidence to resolve “it,” “those figures,” whether a request is a follow-up, or whether a date/responsibility revises a prior one. Keep the current message's date/owner span anchored in current text. If a reply only says “Confirmed” and the context contains a deadline, do not copy the contextual deadline into its spans. Record enough `thread_id`, `turn_index`, and `thread_context` to support later thread-aware reconciliation.

## 7. Uncertainty and annotation status

- `unlabelled`: classification has not been human-adjudicated. `labels` must be empty. Usually `spans` is empty too, but it may contain provisional spans directly mapped from source-dataset annotations when `annotation.annotation_source` is `dataset`. These mapped spans are not human-reviewed or gold. An optional concise `ambiguity_note` says what must be resolved; do not put chain-of-thought in the record.
- `ai_prelabelled`: machine suggestions not yet checked by a person. Preserve model confidence if available and set `needs_review` for low-confidence or ambiguous cases. Never promote AI output directly to gold.
- `human_reviewed`: a person checked the classification and all spans, including any source-mapped spans, and corrected or confirmed them. A human-reviewed record with an empty label array is reserved for an explicit “none of the current labels applies” resolution; it is not a negative label and should be excluded from label-training examples. Confirmed unrelated messages use `NON_PROJECT`. Set `annotation_source` to `human`.
- `gold`: a real email with labels/spans reviewed under the gold procedure. Only a designated human annotator can produce it. Gold status requires human review and must not include unreviewed dataset-mapped spans.

### Source-mapped provisional spans

MailEx source annotations may map directly to this project’s extraction labels. Keep such spans on an unlabelled record only when the mapping is documented, the text is present in `current_message` or `subject`, and the offsets are verified. The record remains `source_dataset: "mailex"`, `labels: []`, `annotation.status: "unlabelled"`, and `annotation.annotation_source: "dataset"`. Do not infer a classification label from an extraction span. During human annotation, review every mapped span, remove or correct unsupported mappings, and annotate classification in the same review pass. Only after that full pass may the record become `human_reviewed` with `annotation_source: "human"`. If a source argument cannot be mapped confidently or aligned to text, omit that span and record the uncertainty for review.

Confidence should reflect the annotation source’s certainty, not email importance. If a span is unclear, retain clear spans and flag the disputed part for review; do not fabricate a clean answer.

## 8. Human review and quality plan

Start with roughly 200–300 real emails sampled across candidate and random pools, retaining whole threads during sampling/splitting. Prefer two independent annotators for the seed batch. They should annotate without seeing one another's labels, then adjudicate disagreements and revise these guidelines before expanding the batch.

Measure agreement per label as a binary decision (present/absent among adjudicated examples), plus per-label precision, recall, and F1 between annotators. Cohen's kappa may be reported per binary label when the sample supports it; do not report one pooled kappa as if multi-label classification were one mutually exclusive class. Track span agreement separately, for example exact-boundary match and overlap F1, and inspect disagreement examples by label.

Review every low-confidence or ambiguous AI-prelabelled record, oversample rare labels for review, and preserve `annotation_source` and annotator identity. A reviewer changing an AI prelabel must produce a `human_reviewed` record; keep provenance so a later user can distinguish model suggestions from human decisions.

## 9. Synthetic examples and data splits

The examples under `examples/` are illustrative synthetic records, not sourced emails. Mark them `source_dataset: "synthetic"` to identify their origin. Use `annotation_source: "human"` when a person has reviewed and labelled a fixture; reserve `annotation_source: "synthetic"` for generated examples that remain unlabelled. Keep them outside the gold set and out of reported real-data evaluation. If synthetic augmentation is used later, label it explicitly, keep it small relative to real data, and report real-data and synthetic-data counts separately.

For real records, all messages in a conversation must remain in one train/validation/test split. Group by source plus `thread_id` where IDs may collide across datasets. Gold threads must be isolated from training, validation, prompt tuning, and hyperparameter tuning. The eventual gold set should contain roughly 300–500 real, human-reviewed messages; do not mark examples as gold just to fill a target.

## 10. Annotation checklist

Before saving a reviewed record, confirm:

- Every applicable label is present, and no exclusive single-class decision was made.
- `NON_PROJECT` appears alone and only for a confirmed out-of-scope message.
- `GENERAL_UPDATE` is used for status/progress and may co-occur with other labels.
- Labels describe the current message; context only helps interpret it.
- Each span is an exact source substring with the right `field`, inclusive start, and exclusive end.
- Metadata and attachment filenames remain in their metadata fields.
- Empty labels are not used as a negative training target.
- Synthetic records are not marked gold; thread IDs remain available for grouped splits.

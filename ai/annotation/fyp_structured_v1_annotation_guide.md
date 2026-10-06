# FYP Structured Schema V1 annotation guide

**Version:** fyp-structured-v1  
**Status:** calibration contract draft  
**Scope:** English Outlook email subject and current message text for project-management information.

This is a new internal annotation contract. It does not change the public canonical email schema, structured V2, or native MailEx records. The V1 form should collect scope, exact spans, events, role links, event relations, review status, and provenance. The nine FYP labels are mapper outputs; annotators do not select them independently.

## 1. What to annotate

Annotate the current email’s project facts and communicative acts:

- meetings and their state, time, participants, agenda, and location;
- operational actions, their owners and due dates;
- requested or delivered project documents;
- formal approval requests and decisions;
- substantive project status;
- department contributions;
- links from each event to its arguments;
- current follow-ups and changes that supersede a prior event.

Use a separate event ID for each distinct event. A message may contain several events of the same kind. One exact span may link to more than one event when it is genuinely shared.

## 2. Source and evidence rules

### Current authored text

Every span records the current source ID, field (subject or current_message), exact text, zero-based end-exclusive Python Unicode code-point offsets, and a type.

All spans and scope evidence refer to current_source_id. Prior records are represented by actual source_id/event_id relation targets; do not copy their spans into the current annotation. The caller must supply authored body ranges whenever a current-message span is used. Put each range in sources[current_source_id].authored_ranges. A span must fit wholly inside one range. Do not guess quote boundaries. Exclude quoted or forwarded history and boilerplate signatures from current-message evidence. Embedded draft/example/hypothetical scripts are reference content: annotate the current author’s request, delivery or comment without treating a proposed script as an actual project status.

An event’s EVENT_ANCHOR must link to an EVENT_TRIGGER span in the current authored message. A subject span may support project scope or an argument, but it cannot anchor a current event.

### Subject, metadata, and context

The subject may support scope and arguments. A subject alone cannot establish a current event.

Outlook sender, recipient, CC, sent time, thread identity, and attachment filename are metadata. Preserve them as metadata; do not turn them into textual spans or infer an owner, participant, request, or department contribution from them. An attachment name is not a requested-document span. The body must support the event.

Thread context may resolve a pronoun, identify a prior expectation, or establish that a current message is a follow-up or supersession. It may not create a current event, current span, current due date, current owner, or current label. Refer to prior facts using their actual source_id and event_id. Do not copy quoted history into the current annotation.

## 3. Scope

The scope object contains value, one or more evidence_span_ids, and a short reason.

- **PROJECT:** current evidence shows a bounded initiative, a project deliverable, or coordination of project work. A project name alone is not enough; the current message must do project work.
- **NON_PROJECT:** the message is clearly outside project-management work. It is exclusive: no events, event-span links, or event relations. A supported NON_PROJECT decision can be complete with needs_review false.
- **UNCERTAIN:** the message does not establish whether it concerns a project. Record the best exact scope evidence and explain the missing distinction. Set needs_review true.

Routine facilities, personal, recruiting, finance administration, or general corporate operations are not project work merely because they include a date, department, request, or meeting.

## 4. Exact span types and boundaries

| Type | What to select | Boundary rule |
|---|---|---|
| EVENT_TRIGGER | Words that express the current event’s act or state | Include the operative phrase, such as “please send”, “is scheduled”, or “was delivered”. Exclude unrelated arguments and dates. |
| ACTION | A complete task or work contribution | Include the verb and essential object, such as “test the release candidate”; omit the person and due expression. |
| DOCUMENT | A named project document or deliverable | Keep meaningful modifiers: “revised project plan”, “monthly status report”. Do not include the request verb. If only “it” is present, use the context event and do not invent a document span. |
| ACTOR | Explicit person, group, department, or role | Select the exact name; set actor_kind to PERSON, GROUP, DEPARTMENT, or ROLE. Do not infer from sender/recipient metadata or annotate bare “I/we” as a named person. |
| MEETING | The identifiable meeting name or phrase | Select “design review” or “the planning meeting”, not its date. |
| LOCATION | A place, room, or explicit online meeting location | Select “Room 2” or the stated venue. Do not infer a location from metadata. |
| DATE, TIME | The exact written date or time expression | Keep date and time separate: “Friday” and “3 PM”. Do not normalize relative dates or infer a clock time. |
| APPROVAL_TARGET | The item on which formal authorization is requested or decided | Select “revised budget”, not the approval verb. |
| STATUS | The phrase that states progress, completion, blocker, decision, or work-state change | Select the shortest complete status phrase that preserves the reported fact. |
| AGENDA | A stated meeting topic | Select the topic, not the word “Agenda”. |
| PROJECT | A specific initiative name or identifier | Select “Orion migration”; a generic “the project” is not a name. |
| OTHER | Exact text supporting a scope decision where no narrower span type applies | Use sparingly, for example “badge replacement inventory” as evidence of routine non-project operations. |

Do not expand a span to a whole sentence. Do not omit words that change the meaning. Overlapping spans are permitted where two distinct typed facts occupy the same text. Reuse one span ID for one source/type/field/range; link that span to multiple events when it is shared.

## 5. Events and states

Every event has a unique id, kind, state, and certainty (SUPPORTED or UNCERTAIN). Use the smallest event unit that preserves a distinct requested, scheduled, approved, or reported fact.

| Kind | State values | Additional field and rule |
|---|---|---|
| MEETING | proposed, scheduled, rescheduled, cancelled, completed | No separate schedule/reschedule/cancel event head. A reschedule is a MEETING event in rescheduled state. |
| ACTION | requested, assigned, committed, completed, cancelled | Required action_class: OPERATIONAL, DOCUMENT_TRANSFER, DEPARTMENTAL_CONTRIBUTION, APPROVAL_TRANSACTION, OTHER, or UNCERTAIN. Use ACTION for a concrete work task. |
| DOCUMENT | requested, expected, submitted, delivered, missing, reviewed | Required document_class: PROJECT_DELIVERABLE, OTHER, or UNCERTAIN. Reports, plans, minutes, and formal project deliverables qualify as PROJECT_DELIVERABLE; figures, comments, and ordinary inputs do not become reports just because they are written down. |
| APPROVAL | requested, granted, rejected, withheld, conditional | This kind asserts a formal project approval, sign-off, or authorization. It replaces separate approve/reject heads. |
| STATUS | progress, completed, blocker, decision, work_state_change | Use for an explicitly reported substantive project update. Do not use as a fallback for an unclear message. |

certainty UNCERTAIN, action_class OTHER or UNCERTAIN, and document_class OTHER or UNCERTAIN require needs_review true and a reason. V1 deliberately routes these boundary cases to review.

### Distinct, repeated, and shared events

Create two events when the email requests two tasks, even if they share the same owner or due date. Give each event its own current EVENT_ANCHOR and link the relevant ACTION, DOCUMENT, date, actor, or department spans to that event.

Represent a shared person, department, or date once as a span and add one link for each event it applies to. Never duplicate the span merely to create two links. If “by Friday” applies to a coordinated action and document request, link the same DATE span to both events with DUE_DATE.

## 6. Event-to-span roles

A link explicitly asserts that one span fills a role for one event. Its certainty is SUPPORTED or UNCERTAIN. The executable x-semantics object in the JSON Schema defines the complete type/kind compatibility matrix and required roles.

| Role | Meaning |
|---|---|
| EVENT_ANCHOR | Current authored EVENT_TRIGGER for this specific event. Required on every event. |
| ACTION, DOCUMENT | The task or deliverable attached to this event. |
| RESPONSIBLE_PARTY | Person, group, role, or department explicitly assigned, responsible, or committed to the event. Mention alone is insufficient. |
| CONTRIBUTOR | A department explicitly asked to provide project input. Must link to ACTOR with actor_kind DEPARTMENT. |
| RECIPIENT, MENTION_ONLY | A recipient or incidental mention. Neither role establishes departmental contribution or responsibility. |
| PARTICIPANT | Explicit meeting attendee or participating group. |
| MEETING_NAME, LOCATION, MEETING_DATE, MEETING_TIME, AGENDA | Meeting identity, venue, calendar date/time, and topic. |
| DUE_DATE, DUE_TIME | A date/time explicitly linked as the action or document’s due value. |
| OCCURRENCE_DATE, OCCURRENCE_TIME | A date/time when work occurred or was reported, not when it is due. |
| APPROVAL_TARGET, APPROVER | Item under authorization and the explicit approving/requesting person or group. |
| STATUS | Current status fact. |
| PROJECT | Explicit project name attached to the event. |

A DATE span is not a deadline because of its type alone. The DUE role is an event-specific judgment and requires wording that makes the date due; a meeting date, occurrence date, message timestamp, availability window, or historical date is not a due date.

## 7. Event relations and thread context

Use only these V1 relations:

- FOLLOW_UP_OF: a current request or reminder follows a prior event or expectation.
- SUPERSEDES: a current event explicitly replaces or revises an actual earlier event.

A relation contains its current source_event_id, relation kind, current-authored evidence_span_ids, certainty, and a target source_id/event_id. The target must resolve to a real event in supplied context records. SUPERSEDES always requires a target of the same kind. A rescheduled meeting references the prior meeting event; a new meeting has no supersession relation.

A FOLLOW_UP_OF relation may use target null only when current wording explicitly says it is following up or reminding. This records the current fact without inventing a prior event. Set needs_review true and a reason; automatic label derivation abstains until review resolves it. If review finds no prior expectation, remove the relation and annotate any genuinely new request as a new event.

Do not add FOLLOW_UP_OF just because earlier mail exists. The current authored message must perform a reminder, chase, check, or escalation.

## 8. Derived FYP labels

Annotate the facts; the deterministic mapper derives these labels. derive_labels returns no labels if the record is invalid, uncertain in scope, or marked needs_review. A supported NON_PROJECT decision returns only NON_PROJECT.

| Derived label | Required V1 facts | Do not emit it for |
|---|---|---|
| MEETING | Supported current MEETING event | A bare date/time or social/routine calendar item |
| DEADLINE | Supported ACTION or DOCUMENT event linked to supported DUE_DATE or DUE_TIME | Meeting date, occurrence date, availability, or message timestamp |
| REPORT_REQUEST | DOCUMENT event in requested state and document_class PROJECT_DELIVERABLE | Expected-only, submitted, delivered, missing, or reviewed document; ordinary action; approval; figures/comments |
| DEPARTMENTAL_INPUT | ACTION event with action_class DEPARTMENTAL_CONTRIBUTION and a supported department CONTRIBUTOR link | Department mention, recipient, owner, or a department’s office/admin update |
| ACTION_REQUEST | ACTION event with class OPERATIONAL and state requested or assigned | Pure document transfer, departmental input, approval transaction, or completed work |
| FOLLOW_UP | Supported current event and resolved FOLLOW_UP_OF relation with current reminder/request evidence | A first request, future instruction to follow up, or unresolved prior reference |
| APPROVAL | Supported APPROVAL event in any V1 approval state | Ordinary review/comment request, receipt, silence, or positive sentiment |
| GENERAL_UPDATE | Supported STATUS event; a completed/cancelled ACTION; or a submitted/delivered/missing/reviewed DOCUMENT | A plain request, planned meeting, expected document, or unsupported/fallback label |
| NON_PROJECT | Supported scope.value NON_PROJECT and no project events or relations | Ambiguous scope; use UNCERTAIN and review |

Co-occurrence is allowed. For example, an operational task and a separate report request can yield both ACTION_REQUEST and REPORT_REQUEST; the same due date may yield DEADLINE for both linked events. A completed task or delivered document also yields GENERAL_UPDATE. Do not duplicate an event to obtain extra labels.

### Quick worked examples

These short examples are invented for training. Highlight only the words that appear in the current message; connect each date, person, and document to the event it belongs to.

| Current message says… | Annotate… | Derived result |
|---|---|---|
| “Please test the Orion login.” | Task → requested; ACTION words “test the Orion login” | ACTION_REQUEST |
| “Please test the Orion login by Friday.” | Task → requested; link Friday as its DUE_DATE | ACTION_REQUEST, DEADLINE |
| “Please send the Orion progress report.” | Document → requested; identify it as a project deliverable | REPORT_REQUEST |
| “The Orion progress report was delivered.” | Document → delivered | GENERAL_UPDATE, not REPORT_REQUEST |
| “Please approve the Orion budget.” | Approval → requested | APPROVAL |
| “The Orion change is approved.” / “The Orion change is rejected.” | Approval → granted / rejected | APPROVAL |
| “Let’s review the Orion launch on Friday.” | Meeting → proposed; Friday is its MEETING_DATE | MEETING, not DEADLINE |
| “Move the Orion review to Monday instead.” | Meeting → rescheduled; use SUPERSEDES only if the earlier meeting is available and confirmed | MEETING |
| “Orion testing is blocked by the missing access key.” | Project update → blocker | GENERAL_UPDATE |
| “Finance, provide the Orion cost estimate by Friday.” | Task → requested; Finance is a department CONTRIBUTOR; link Friday as its DUE_DATE | DEPARTMENTAL_INPUT, DEADLINE |
| First: “Please send the Orion report.” Later: “Following up on that request—please send it today.” | A Document event in each message; add FOLLOW_UP_OF only when the first event is verified | REPORT_REQUEST; later also FOLLOW_UP |
| Current: “Done, the Orion report was sent today.” Quoted: “Please send the report by Friday.” | Label the current delivery only. The quoted request is context, not a new current task. | GENERAL_UPDATE |
| “Maya, test the interface by Friday; Leo, review the budget by Monday.” | Create two Task events; attach each person and deadline to the matching task | ACTION_REQUEST, DEADLINE |
| “Meet Friday; the report is due Monday.” | Create a Meeting with Friday as MEETING_DATE and a separate Document with Monday as DUE_DATE | MEETING, REPORT_REQUEST, DEADLINE |
| “Please book the routine weekly office room.” | If no initiative or deliverable connects it to project work, choose NON_PROJECT; do not label the meeting | NON_PROJECT |
| “Please arrange a call Friday.” | If project relevance cannot be established from the available context, choose UNCERTAIN and explain | No automatic labels until reviewed |

Do not derive departmental input from a department name alone. Do not derive a deadline from a meeting date. A request for review/comments is not automatically an approval.

#### Tricky scope and document boundaries

| Situation | Decision | Why |
|---|---|---|
| “Please confirm this month’s contract price and update the recurring invoice.” | NON_PROJECT if it is routine contract administration with no bounded initiative. | Contract or pricing words alone do not establish a project. |
| “Review the new capacity principles and send comments before the working-group meeting.” | PROJECT when the message establishes a defined workstream, deliverable and milestone. | Coordinated work can be project-related without using the word “project.” |
| “Send the raw receivables data by Thursday.” | Use DOCUMENT only if the source shows it is project work; raw data is not automatically a project report. If the project connection or document class is unclear, choose UNCERTAIN / NEEDS_REVIEW. | A file or dataset is not automatically a requested report deliverable. |
| “Please review the draft and send comments.” / “Please approve the draft.” | The first is a Task/input request; the second is Approval. | Review or comments alone do not ask for formal authorization. |

## 9. Difficult contrastive decisions

Use the synthetic fixture IDs in fyp_structured_v1_synthetic_examples.jsonl as executable illustrations. They are not real email samples, gold annotations, or accuracy evidence.

- **Deadline vs ordinary date:** meeting_date_not_deadline links Friday as MEETING_DATE; completed_action_is_status links Friday as OCCURRENCE_DATE. Neither derives DEADLINE. operational_action_request links Friday as DUE_DATE and does.
- **Current request vs quoted historical request:** follow_up_with_quoted_history anchors only “Could you send” in the caller-supplied authored range. The quoted request has no current span; the prior event is referenced by IDs.
- **First request vs follow-up:** first_report_request has no relation. follow_up_with_quoted_history references the earlier document event. follow_up_unresolved_prior records explicit reminder wording with a null prior reference and requires review.
- **Report request vs delivery:** document_request_with_deadline is a requested deliverable. document_delivery_not_request is a delivered document; it derives GENERAL_UPDATE, not REPORT_REQUEST.
- **Report vs ordinary action:** two_events_shared_owner_and_deadline models an operational task and a distinct launch-deck request. A document transfer by itself is not an operational action.
- **Approval vs review:** formal_approval records granted authorization. ordinary_review_not_approval is a progress/status report with comments, not approval.
- **Department contribution vs mention/recipient:** department_contribution_request gives Finance a CONTRIBUTOR role. department_recipient_only gives Finance RECIPIENT; it does not derive DEPARTMENTAL_INPUT.
- **Responsible party vs merely mentioned person:** only an explicit assignment/commitment is RESPONSIBLE_PARTY. Do not attach an incidental name or sender metadata. The shared-owner fixture links Maya to both requested events because the sentence assigns both tasks to her.
- **Action request vs completed status:** operational_action_request is requested work. completed_action_is_status is completed work and derives GENERAL_UPDATE.
- **General update vs operational request:** a status assertion receives STATUS; a requested task receives ACTION. Do not mark both unless the email makes both assertions.
- **Rescheduled vs new meeting:** meeting_rescheduled_supersedes changes an existing meeting and references the earlier event. A newly proposed meeting gets a new MEETING event without SUPERSEDES.
- **Project vs corporate operations:** routine_corporate_operations is exclusive NON_PROJECT even though it contains a meeting and a date. meeting_without_project_context remains UNCERTAIN because no bounded project is established.

## 10. Uncertainty and review

Use uncertainty explicitly. Do not force an unclear date into DUE_DATE, a review into APPROVAL, an incidental person into RESPONSIBLE_PARTY, or a generic department mention into CONTRIBUTOR.

Set needs_review true with at least one concise review_reasons entry when:

- scope is UNCERTAIN;
- an event, event-span link, or relation has certainty UNCERTAIN;
- action/document class is OTHER or UNCERTAIN;
- a current follow-up has no resolvable prior event;
- source ranges, event identity, target attachment, or role attachment cannot be resolved.

Valid uncertainty is not a malformed annotation. The validator returns it as a review warning. The label mapper abstains while review is required. After review, correct the annotation or preserve an explicit adjudicated uncertainty according to the calibration protocol; do not silently remove the review flag to obtain labels.

## 11. Annotation and source provenance

Provenance describes both source origin and how the facts were produced:

- data_origin: REAL_EMAIL, PUBLIC_CORPUS, SYNTHETIC, or UNKNOWN;
- annotation_tier: UNSET, GOLD, SILVER, or SYNTHETIC;
- annotation_mode: UNANNOTATED, BLIND_HUMAN, AI_ASSISTED_HUMAN, AI_ONLY, RULE_BASED, or SYNTHETIC_GENERATION;
- annotator and annotation time;
- whether AI prelabels were shown;
- human-review identity, time, and decision;
- for AI assistance, provider, model, checkpoint, protocol version, run ID, timestamp, and human disposition;
- a source reference for real/public records and a synthetic case ID for generated records.

A blind annotator must be identifiable and timed; blind_prelabels_shown is false and ai_assistance is null. Each independent blind submission remains UNSET until adjudication. Do not show AI or another annotator’s answers in the blind subset.

AI-assisted annotation records the AI provenance and whether the human accepted, modified, or rejected its output. GOLD requires explicit human review and a named/timed annotator; a tier dropdown by itself is insufficient. An AI-only prediction remains SILVER. A synthetic source always remains SYNTHETIC and cannot be GOLD or evaluation data.

Derived labels use a separate rule version recorded on each new annotation. Records without `derived_label_version` retain the original `fyp-derived-labels-1.0` interpretation; new review records use `fyp-derived-labels-1.1`. Changing mapper rules must not silently change labels derived from older saved annotations.

For evaluation, validation requires blind, human-reviewed GOLD from a real email or public corpus. Evaluation must not contain synthetic, unknown-origin, AI-only, or AI-assisted examples. Current repository guidance reports no human gold yet; this guide does not claim a human calibration set exists.

## 12. Implementation boundary

The JSON Schema is the executable shape contract. Its x-semantics object defines span/role compatibility, event-kind compatibility, required roles, review classes, and derived-label rules for both the Python core and review interface. Cross-record source slices, authored ranges, role links, context event resolution, and provenance are validated by the V1 validator.

This schema is email-text focused. Attachment contents, organizational hierarchy, final Outlook/Excel persistence, and dashboard behavior remain separate product work. No private email text is included in the schema, guide, or synthetic fixtures.

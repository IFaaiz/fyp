# Structured V2 source review

This records the generic rubric used in the AI reviewer briefs. It contains no corpus examples or accepted annotations. The JSON schema, validator, mapper and packet bindings remain the executable contract. Reviewer identity strings and attestations in a shared workspace are an audit trail, not cryptographic proof of independence. There is no human gold.

## Scope

`PROJECT` needs evidence of a bounded initiative, project deliverable, or coordination of project work. A named project can supply context, but its name alone does not establish the current function. Review the actual current text.

Routine trading, record maintenance, general recruiting, industry newsletters and personal activity do not become project work merely because they mention a project, date, request, department or meeting. When the source does not establish whether the work belongs to a project, use `UNCERTAIN`. Do not force ambiguous business activity into either a positive or a confident negative.

Synthetic illustrations:

- A project integration demo with a stated schedule supports project scope and a meeting event.
- A birthday lunch invitation supports non-project scope.
- A request for an unspecified report can leave project scope uncertain.
- A meeting time without an identifiable project context can leave project scope uncertain.

## Current content and evidence

Read every assigned subject and complete current-message field. Retained forwarded headers and quoted history cannot create current actions or events. If the current authored content is unavailable, mark the limitation. Context cannot establish an authenticated earlier source identity by itself.

Use exact Unicode code-point offsets. Name and date evidence should isolate the actual words. Request and due-relation evidence must include the operative wording; a noun alone does not prove a request or a deadline. Avoid using a whole paragraph as a name or date span. Verify source IDs, fields, offsets and hashes against the assigned packet.

## Primitive judgments

- Record every clearly supported current communicative act relevant to the project, including attachment delivery. An omitted known act can create a false negative for a speech-act head.
- A date becomes a deadline only through an explicit date-to-action or date-to-document due relation. Meeting dates, availability and message timestamps are separate.
- Representatives, teams and groups are not automatically named departments. A recipient is not automatically a contributor or responsible owner.
- Ordinary feedback and document review are not formal authorization. Planned authorization, a request, and a granted decision have different states.
- A follow-up needs a current chase and an established prior expectation. A previous conversation alone may leave that expectation unknown.
- Separate operational work from document transfer, departmental contribution and approval transactions. Do not duplicate an action merely to increase final-label support.
- Keep delivery, substantive progress and event state grounded in current evidence. Future intentions are not completed work.

## Review and acceptance

A and B use source-only packets. Any primitive/evidence disagreement requires a third review for TRAIN; every EVAL source requires a third review. The third source-only initial verdict is frozen before A/B are revealed. Root checks high-risk and ambiguous selections against the sources.

Shape validation does not prove semantic correctness or complete act coverage. Resolve mistakes before ingestion where possible; preserve frozen artifacts. An unresolved or incomplete annotation can be excluded from TRAIN. Do not invent certainty, source facts or rare positives to satisfy support thresholds.

Status is read-only. Explicit finalization persists a batch only after every source has a complete accepted or rejected outcome. Accepted handoffs require separate root authorization and full provenance verification before model use. The 20-per-class support floor remains in force. Evaluation claims, when available, must be titled **AI-SILVER DIAGNOSTIC PERFORMANCE**.

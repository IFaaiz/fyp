# Direct correctness audit of the second AI pilot

I read the subject and full current message for all 50 emails in the second blind pilot, applied the [canonical annotation guidelines](../annotation/annotation_guidelines.md) and [v2 protocol](../annotation/ai_review_protocol_v2.md), and then compared my decisions with the two saved reviewer outputs. This is an **AI audit**, not human adjudication or a gold test set. I preserved both blind reviewer files. The item-level audit, including every suggested label set, short reasons, and span findings, is local and ignored at `ai/data/annotated/ai/project_pilot_50_v2/supervisor_direct_audit.jsonl`.

## Classification findings

| Direct audit result | Emails |
| --- | ---: |
| Audited | 50 |
| Suggested label set matches both reviewers | 30 |
| Matches only reviewer A | 2 |
| Matches only reviewer B | 8 |
| Matches neither reviewer | 6 |
| Abstained because project scope is unresolved | 4 |

These match counts describe agreement with my audit, **not measured accuracy**. Reviewer B matched more of my suggestions (38/50) than reviewer A (32/50), but I also found errors on records where the two reviewers agreed.

| Email | Direct finding |
| --- | --- |
| `enron-629c39b94c0ef839922bc394` — Business Review | Reviewer A used `NON_PROJECT`; the current message schedules a workstream review with a project-related agenda, supporting `MEETING`. |
| `enron-cd2d3ce1cc551e6cd4dc287c` — testing progress | Reviewer A added `MEETING` and `FOLLOW_UP`. The Wednesday and Thursday blocks are testing sessions, and the message asks people to execute tests. `ACTION_REQUEST` and `GENERAL_UPDATE` are better supported. |
| `enron-3e61922f8ffad76ada74c8cf` — curve schedule | Both added `ACTION_REQUEST` although the current message presents a plan and seeks a future discussion; it does not assign a separate concrete task. Its April 23 date is the process start, not a deadline. |
| `enron-8c887a01418d35057a5b0ea1` — Follow Up Items | Both added `ACTION_REQUEST` for a previously reported checklist review and a conditional request for information. The current project status and planned session support `GENERAL_UPDATE` and `MEETING`. |
| `enron-b59f7d4b4be8c8861113f9c7` — Doorstep Review | Both added `ACTION_REQUEST`, although this message reports a task already assigned to Beth and a changed review schedule. `GENERAL_UPDATE` is supported. |
| `enron-ae110a2ad9dac09afd1bf57a` — RTO advocacy | Both added `REPORT_REQUEST` for a request to list upcoming meetings. The message describes planned advocacy documents but does not request those formal documents from recipients. `ACTION_REQUEST`, `DEADLINE`, and `GENERAL_UPDATE` are better supported. |
| `enron-6a27a95215a5f21b9aa2f3bc` — LM6000 Documents | Reviewer A added `APPROVAL` from the expectation that documents be signed. No explicit approval decision or request appears. |
| `enron-51730ac5c0e544a597560004` — Woodside meeting | Reviewer A abstained; the message is commercial prospecting without an established project. `NON_PROJECT` is the better scoped choice. |

Four messages remain abstentions in my audit: `enron-0f27878725f61971fc2c51e6`, `enron-ebe8f2fc3935dc5b4af28331`, `enron-9111485979a861943e29295d`, and `enron-7282643e9f325c8d2ca0d873`. Their commercial/operational work could be routine business or part of a managed project; the current messages do not settle the FYP scope. They must not become `NON_PROJECT` negatives or positive training examples based on my guess.

## Span findings

I reviewed the reviewers' date, task, and document span lists against the messages. Both files had already passed mechanical exact-substring/offset validation; that does not validate semantic roles. The item-level audit records 14 emails with specific span or closely related label concerns. Examples:

- `enron-cd2d3ce1cc551e6cd4dc287c`: reviewer A marked test windows as `MEETING_DATE` and `MEETING_TIME`.
- `enron-30760d7401b5151d50118b8a`: reviewer A marked October 15–19 as `DEADLINE_DATE` even though it dates RTO meetings.
- `enron-ca67c7634b2b0f0a4b02537d`: reviewer B marked the supplied blank template as `REQUESTED_DOCUMENT`; the requested output is the completed forecast.
- `enron-ebe8f2fc3935dc5b4af28331`: reviewer A marked an existing report name as `REQUESTED_DOCUMENT`, though the sender requests an updated software version.
- `enron-1fcfd6751170660300f642f7`: reviewer B marked an already prepared interim report as `REQUESTED_DOCUMENT`.

The date, task, and document review was targeted; it did not fully adjudicate every participant, department, agenda, or project-name span. Neither reviewer output should be used as verified span truth. The original 250-email seed, existing human output, and gold data were not changed.

## Use of this audit

The audit provides concrete corrections and unresolved cases for the next guideline and model iteration. It does not provide a defensible precision/recall estimate: the auditor is another AI, the historical Enron sample differs from the intended Outlook project mail, and the unresolved scope cases remain open. Keep these records labeled as AI suggestions and exclude the four abstentions from negative-label training.

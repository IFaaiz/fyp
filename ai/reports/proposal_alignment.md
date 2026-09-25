# Proposal alignment — 25 September 2026

I reviewed both root proposal PDFs, treating **FYP Proposal Revised.pdf** as the later scope statement. The original proposal describes an Outlook 2016 and Excel desktop workflow that classifies project emails, extracts meetings, deadlines, documents, owners, and actions, uses thread history, and drives reminders and a dashboard. The revised proposal keeps that workflow and explicitly adds information extraction from Word, PDF, and scanned-image attachments, plus hierarchy-aware access and views for senior managers, project managers, and team members. Both proposals specify English-language operation.

## Current AI/NLP dataset coverage

The current canonical email dataset covers email subject and message-body annotation, sender/recipient/CC/date metadata, thread context, and attachment **filenames**. It includes explicit meeting, deadline, report/document, departmental-input, action, follow-up, approval, and update labels, with exact textual spans for dates, times, people, departments, agenda, actions, requested documents, and projects. This matches the email-text portion of the proposal and supports later rule-based reminders. `DEADLINE_TIME` was added because a precise due time is needed to schedule an alert.

## Remaining proposal scope

1. **Attachment content:** The revised proposal requires reading Word, PDF, and scanned-image contents and extracting project details linked to the parent email. The current dataset does not contain attachment text or document-level spans. The CMU Enron release omits attachments, so its email records cannot validate this requirement. A separate authorized attachment corpus, document/OCR extraction pipeline, link-to-email schema, annotation guide, and evaluation set are needed before claiming attachment accuracy.
2. **Organizational hierarchy:** Sender and recipient addresses are captured, but the current records do not map them to senior manager, project manager, or team-member roles. That mapping and access rules belong to an authorized organization directory or application configuration. They should not be inferred from historical Enron addresses.
3. **Outlook, Excel, dashboard, and reminders:** Those product modules are outside this dataset-engineering pass. The NLP output and later validation rules must eventually integrate with them. No end-to-end Outlook/Excel or alert KPI has been measured here.

The immediate annotation round should stay focused on human-reviewed email text. The attachment and hierarchy requirements should be tracked as separate follow-on work before the final system is described as satisfying the revised proposal.

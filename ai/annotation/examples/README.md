# Annotation examples

`annotation_examples.jsonl` contains thirteen small synthetic records illustrating multi-label decisions, label co-occurrence, current-message versus thread-context evidence, subject spans, exact extraction boundaries, a confirmed `NON_PROJECT` message, a human-resolved empty-label acknowledgment, and an unresolved ambiguous reply.

| Record | Point illustrated |
| --- | --- |
| `example-multi-label` | Meeting, deadline, document request, and approval can all apply. |
| `example-status-only` | Project completion is `GENERAL_UPDATE`. |
| `example-status-deadline-no-request` | A status and due date do not automatically create a request label. |
| `example-status-deadline-request` | Status, deadline, and explicit submission request co-occur. |
| `example-department-input` | Departmental input, deadline, and responsible party spans. |
| `example-thread-follow-up` | Context can establish follow-up; spans still point into the current message. |
| `example-subject-and-approval` | Subject-field spans use `field: "subject"`. |
| `example-meeting-agenda` | Meeting date, time, participants, agenda, and project spans. |
| `example-non-project` | Confirmed out-of-scope email uses only `NON_PROJECT`. |
| `example-unlabelled-acknowledgement` | A human-resolved empty label array is not a negative training target. |
| `example-ambiguous-yes` | An unresolved short reply remains `unlabelled` and requires review. |
| `example-action-only` | A concrete task receives `ACTION_REQUEST` without forcing `GENERAL_UPDATE`. |
| `example-deadline-time` | A due date and due time receive separate spans. |

These records are documentation fixtures. They are not real Outlook/Enron/MailEx emails, are not gold data, and must not be included in real-data metrics or the gold test set. Each has `source_dataset: "synthetic"`. Human-curated examples have `annotation_source: "human"`; the unresolved example retains synthetic provenance. None is gold. Span offsets were generated from the exact string values using Python string indexing, with exclusive end offsets.

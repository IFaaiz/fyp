# Third audit summary — training silver rows 301–600

## Coverage

- Source tranche: 300 rows, seed positions 301–600.
- Required audit set: 215 rows, calculated with `expected_audit_ids` from `ai/scripts/adjudicate_training_silver_1400.py`.
- Selection: 175 disagreement-or-flag rows; 18 exact, unflagged agreements selected for rare-label and/or multilabel coverage (6 met both criteria); and 22 of 107 ordinary exact, unflagged agreements, the deterministic SHA256 sample rounded up to 20%.
- Output validation: 215 records, in seed order, with no duplicate or missing required IDs. Every record has exactly `email_id`, `labels`, and `needs_review`; labels are in the registered inventory and `NON_PROJECT` is exclusive.
- Output is ignored by Git under the existing `ai/data/**` rule.

## Audit outcomes

| Measure | Rows |
| --- | ---: |
| Needs review / empty labels | 122 |
| At least one assigned label | 93 |
| `GENERAL_UPDATE` | 53 |
| `ACTION_REQUEST` | 40 |
| `REPORT_REQUEST` | 12 |
| `FOLLOW_UP` | 11 |
| `DEADLINE` | 11 |
| `MEETING` | 9 |
| `NON_PROJECT` | 13 |
| `APPROVAL` | 3 |
| `DEPARTMENTAL_INPUT` | 2 |

Label counts are multilabel and therefore do not sum to the number of rows with labels.

## Pattern findings

- Imported calendar placeholders dominated abstentions: 118 selected rows had calendar-entry content; 111 lacked enough current-message detail to establish a project meeting or action and were left for review. Seven clearly reflected general, personal, or out-of-office scheduling and were assigned `NON_PROJECT`.
- Project status messages commonly combined progress with a separate request, follow-up, or deliverable. Those functions were labeled independently where the current message supported them.
- Attached or referenced materials were not treated as requests by themselves. `REPORT_REQUEST` was used when the current message asked for a formal project document or deliverable; operational review or editing tasks were handled as `ACTION_REQUEST` when distinct.
- Dates attached only to events, test windows, or migration schedules were not treated as deadlines unless the current message stated a due point for project work.
- Short acknowledgments, bare attachment handoffs, and other messages whose current function or project scope could not be resolved were left unlabelled and marked for review.

## Conservative AI-silver gate

The supervisor's [text-free decision manifest](../annotation/training_silver_second300_decisions.jsonl)
retains 61 of the 300 rows: 45 project-related and 16 `NON_PROJECT`.
Exclusive exclusion reasons are 157 sparse calendar/task exports, 72 other
disagreements/flags/abstentions, 6 third-audit vetoes, 2 supervisor scope
vetoes, and 2 curated leakage exclusions. The calendar-export gate prevents
low-information Outlook boilerplate from dominating the training set, even
where two reviewers agreed on `NON_PROJECT`.

The supervisor joined this and the earlier accepted manifests to the canonical
full-Enron source. All 272 manifest-accepted rows passed schema validation;
with the 41-row pilot, a read-only leakage-safe split placed 247 in training
and 66 in validation across 313 connected groups with no boundary violation.
The 1,000-row fitting gate remains closed.

## Status

This is an independent AI third-audit output. It is not human-reviewed and makes no gold-label claim. The separate supervisor gate admits only high-confidence AI-silver records for prototype training; human adjudication remains necessary for any gold or final accuracy claim.

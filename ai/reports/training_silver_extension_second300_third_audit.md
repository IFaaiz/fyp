# Independent third-AI audit: extension1200 rows 301–600

## Scope and method

- Audited every ID selected by `expected_audit_ids`: reviewer disagreements/flags, rare multilabel agreements, and the fixed ordinary sample.
- Decisions were made independently from the full authored current message; thread context was used only to resolve references.
- This is provisional AI silver review, not human-reviewed or gold data. The seed and reviewer annotations were left unchanged.

## Aggregate results

- Required and audited records: 202 of 202.
- Abstentions (`labels=[]`, `needs_review=true`): 10.
- Label assignments (multi-label records contribute to each applicable label):
  - ACTION_REQUEST: 95
  - APPROVAL: 21
  - DEADLINE: 52
  - DEPARTMENTAL_INPUT: 3
  - FOLLOW_UP: 11
  - GENERAL_UPDATE: 119
  - MEETING: 57
  - NON_PROJECT: 28
  - REPORT_REQUEST: 8

No source email text or case-level identifiers are included in this report.

## Strict acceptance gate

Of 300 reviewed records, 180 had exact, nonempty, unflagged label-set agreement
(label order is immaterial). The independent audit vetoed 14 of those sets.
The text-free [decision manifest](../annotation/training_silver_extension_second300_decisions.jsonl)
therefore retains **166** records and excludes **134**: 120 original reviewer
disagreements, flags, or abstentions and 14 audit vetoes. No disagreement was
promoted by a third-reviewer tie-break.

Accepted records include 68 `NON_PROJECT`, 98 project-related records, and 44
multi-label records. Accepted supports are `ACTION_REQUEST` 30, `APPROVAL` 9,
`DEADLINE` 19, `DEPARTMENTAL_INPUT` 1, `FOLLOW_UP` 2, `GENERAL_UPDATE` 72,
`MEETING` 30, `NON_PROJECT` 68, and `REPORT_REQUEST` 1. These supports overlap.

The supervisor inspected rare-label agreement examples, all nine accepted
approval examples, and hard negatives covering routine HR training, an automated
invoice notice, and recruitment mail. The current authored text, rather than
a quoted request or incidental project term, controlled the boundary checks.
All accepted IDs join to canonical source records; combined with earlier
corrected batches there are **617 eligible records** in **617 distinct leakage
groups**, with zero canonical validation errors. This remains below the
1,000-record training gate, with limited rare-label support. The count reflects
a later supervisor exclusion of one ambiguous Phase 2 date in the first
replacement tranche; the 166 accepted rows in this tranche are unchanged.

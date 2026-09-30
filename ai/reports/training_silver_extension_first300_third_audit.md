# Third audit: training silver extension, first 300

## Scope and method

This was an independent AI-only audit of the first 300 frozen seed rows. The required set was computed with `expected_audit_ids` from `ai/scripts/adjudicate_training_silver_1400.py`, using both blind reviewer files. It includes 143 disagreement or flagged rows, 51 exact unflagged rare-label or multilabel agreements, and 22 rows from the deterministic 20% ordinary-agreement sample, for 216 required records total.

The audit considered each current authored message. Quoted or forwarded history was not used as current evidence; thread context served only as reference. The audit output contains only `email_id`, `labels`, and `needs_review`. This report reproduces no email text.

## Results

The 216 decisions contain 10 abstentions with `labels: []` and `needs_review: true`, and 20 clear `NON_PROJECT` decisions. The remaining decisions assign one or more supported project labels. Label counts overlap because classification is multilabel.

| Label | Count |
| --- | ---: |
| `ACTION_REQUEST` | 98 |
| `APPROVAL` | 16 |
| `DEADLINE` | 53 |
| `DEPARTMENTAL_INPUT` | 10 |
| `FOLLOW_UP` | 17 |
| `GENERAL_UPDATE` | 134 |
| `MEETING` | 60 |
| `NON_PROJECT` | 20 |
| `REPORT_REQUEST` | 22 |

## Patterns and uncertainties

Project status commonly appeared alongside a separate request, approval, or expected deliverable, so multiple labels were retained where each function was supported. Meeting dates and business event dates were separated from deadlines; a date was treated as a deadline when the current message tied it to expected completion, submission, response, or delivery. Reminders were distinguished from instructions to perform a future follow-up.

The remaining uncertainty is concentrated in scope or communicative function: some short acknowledgements, document transfers, and commercial or regulatory discussions did not make clear whether they represented a managed project action or an out-of-scope business exchange. Those cases were left unlabelled for further review instead of being treated as negative examples. Administrative and industry notices were marked `NON_PROJECT` only when the message clearly lacked an in-scope project-management function.

## Status

This is an AI audit artifact for the silver-data acceptance gate. It is not human-reviewed data and is not gold. The 10 abstentions remain excluded from positive-label training unless a later reviewer resolves them.

## Strict adjudication outcome

The text-free [decision manifest](../annotation/training_silver_extension_first300_decisions.jsonl)
retains **139 of 300** reviewed records: 66 `NON_PROJECT` and 73 with at least
one project label, including 31 multi-label records. It excludes 143 reviewer
disagreements, flags, or abstentions; 16 otherwise exact agreements vetoed by
the independent audit; and two supervisor scope/date-role vetoes. No disputed or flagged
record was accepted by a tie-break. The accepted label supports are:

| Label | Accepted records |
| --- | ---: |
| `ACTION_REQUEST` | 29 |
| `APPROVAL` | 2 |
| `DEADLINE` | 10 |
| `DEPARTMENTAL_INPUT` | 1 |
| `FOLLOW_UP` | 3 |
| `GENERAL_UPDATE` | 47 |
| `MEETING` | 23 |
| `NON_PROJECT` | 66 |
| `REPORT_REQUEST` | 3 |

The supervisor read accepted examples from every label, including all three
`REPORT_REQUEST` examples and the sole `DEPARTMENTAL_INPUT` example. The
canonical join resolves every accepted ID and verifies its source thread;
combined with prior accepted data there are **451** eligible AI-silver records
in **451** distinct full-corpus leakage groups after the 30 September supervisor
scope and date-role corrections. The later second replacement tranche brings
the cumulative count to 617. Rare-label support remains low,
so this is not yet the 1,000-record training set.

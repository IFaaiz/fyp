# Separate thread-change evaluation design — 30 September 2026

The classification dataset labels the current email's function. Thread-change
evaluation will instead link the same meeting, action, or document across
ordered messages and check how its state changed. No verified thread-change
examples exist yet. The 2,110 heuristic Enron pairs remain unverified candidates.

The local MailEx conversion contains 1,500 real source threads: 888 have two
messages, 406 have three, and 206 have four or more. **1,333 threads** have at
least two nonempty current messages. These counts were recomputed from
`ai/data/processed/mailex.jsonl`. Source thread structure establishes message
membership, not project scope, entity identity, or change truth.

Use the [pair label schema](../annotation/thread_change_label_schema.json) to
collect ordered pairs with stable source IDs, source hashes, a leakage group,
before/after state, links to the same entity, exact authored evidence, and human
annotation provenance. A pair may need intervening turns to resolve references;
preserve their IDs and context without treating an old quotation as a new change.
Store source text and human working outputs in ignored data paths. Publish only
text-free manifests and aggregate reports.

| Change | Evidence needed |
| --- | --- |
| Deadline moved later or earlier | Same action/deliverable, old and new comparable due points |
| Meeting rescheduled | Same meeting, explicit replacement of its date/time/location |
| Meeting cancelled | Explicit cancellation of the linked meeting |
| Owner changed | Same action, explicit transfer from an earlier owner to a new owner |
| New action assigned | A concrete new project task and its assignment |
| Document requested | Explicit request for a linked formal project deliverable |
| Document delivered | Explicit delivery of that requested document |
| Document still missing | Current evidence that the expected document remains outstanding |
| Follow-up or escalation | Current check, reminder, or escalation tied to earlier expected work |
| No change | Fully reviewed pair without a supported change; include repeated dates, acknowledgements, and unrelated entities |

Begin with 30–50 human calibration pairs from separate leakage components to
resolve entity-link and evidence disagreements. Aim next for 300–500 independent
human-adjudicated evaluation pairs across these changes and hard negatives;
attempt 25–40 positives per change where naturally available, without forcing
scarce labels. Record shortages. Human gold must be held apart from both
classification training groups and calibration/tuning groups. AI suggestions
can assist collection but cannot establish verified change labels.

Two humans should independently check source thread membership, chronology,
project scope, entity identity, before/after state, change labels, and evidence.
An adjudicator resolves disagreement. Ambiguous chronology, missing earlier
state, unclear entity identity, or unclear project scope remains unlabelled.
Relative dates require the source timestamp/time zone; missing metadata is a
reason to abstain from deadline direction rather than invent a date.

Report per-change precision, recall, F1 and support; exact change-set match;
entity-link correctness; evidence-span correctness; and state-transition
correctness. Report error types separately for entity confusion, quoted-text
copying, date normalization, missed changes, spurious changes, and missing
context. Classification baseline training can proceed independently of this
future human-reviewed evaluation workstream.

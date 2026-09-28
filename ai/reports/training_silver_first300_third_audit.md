# First 300 training candidates — independent AI audit and silver gate

Two GPT-6 Luna xhigh agents reviewed the frozen first 300 Enron messages
independently using the project-management taxonomy. A third GPT-6 Luna xhigh
agent inspected all 145 rows with a disagreement or review flag, all 40
rare-label or multi-label exact unflagged agreements, and a deterministic
SHA-256 sample of 23 of the remaining 115 exact unflagged agreements. The
third audit therefore covers all 208 required IDs; 18 additional ordinary
agreements were inspected when the auditor initially used input-order sampling.

The third agent saved 208 text-free audit calls locally. Its shell failed while
adding the correct sample. It sent the 18 missing calls to the supervisor,
who checked the IDs against the frozen source and transcribed them, and fixed
one one-character ID typo in the saved audit file. The final local audit has
226 unique rows, including 42 abstentions. The adjudication script verifies
all required IDs are present and rejects missing coverage or duplicates.

| Gate result | Rows |
| --- | ---: |
| Reviewed by both blind agents | 300 |
| Accepted AI-silver | 145 |
| Disagreement, review flag, or abstention excluded | 143 |
| Third-audit veto of exact agreement | 7 |
| Supervisor scope veto | 2 |
| Curated leakage exclusion | 3 |

Accepted rows comprise 89 `NON_PROJECT` and 56 project-related records; 31
records have multiple project labels. Label counts are `ACTION_REQUEST` 24,
`APPROVAL` 6, `DEADLINE` 16, `DEPARTMENTAL_INPUT` 3, `FOLLOW_UP` 1,
`GENERAL_UPDATE` 38, `MEETING` 14, and `NON_PROJECT` 89. No
`REPORT_REQUEST` survived this strict batch gate. Counts overlap on
multi-label records. The [text-free decisions](../annotation/training_silver_first300_decisions.jsonl)
join to canonical full-Enron text by source-qualified ID and use canonical
source thread IDs, including verified aliases for the reviewed seed.

The supervisor reread targeted rare/multi-label agreements and a deterministic sample
of 20 clear `NON_PROJECT` agreements. Two exact agreements were vetoed for
uncertain managed-project scope. The supervisor also checked independent
third-audit mismatches and retained the conservative exclusion rule: a third
agent's tie-break does not promote an original disagreement or review flag.
This is AI-silver training material, not human-reviewed gold; it supplies no
accuracy estimate. The current accepted total with the prior 41-record pilot
and 66-record expansion is **252**.

The supervisor joined the accepted IDs to canonical full-Enron source rows:
all 211 manifest-accepted rows passed canonical validation. With the earlier
41-row pilot, a read-only leakage-group/thread split produced 199 training and
53 validation assignments across 252 connected groups, with no split-boundary
violation. This is an integration check; the 1,000-row training gate still
prevents fitting or evaluation on this small batch.

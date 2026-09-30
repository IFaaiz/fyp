# Supervisor quality corrections — 30 September 2026

The supervisor reread every currently accepted example carrying
`DEPARTMENTAL_INPUT` (7), `APPROVAL` (9 before correction), `REPORT_REQUEST` (9),
or `FOLLOW_UP` (9). Counts overlap. The source text was inspected locally and
is not reproduced here. The reread found one accepted external regulatory
approval notice whose current text did not establish the team's managed-project
scope. Its ID was added to the supervisor-veto sidecar, and the first 300-row
decision manifest was regenerated. A row comparison confirmed that exactly
this one decision changed from `ai_silver` to `excluded_uncertain` with empty
labels. The corrected first tranche contains 144 accepted rows; cumulative
eligible silver falls from 453 to **452**. This is a conservative exclusion,
not a new gold annotation.

The reread also found a concrete feature-cleaning defect. A Lotus quoted block
starting with a sender name, angle-bracket email address, and `on` timestamp
was retained when the timestamp was not on its own line. The feature cleaner
now recognizes that anchor only when nearby mail-header fields corroborate the
boundary. The real affected source now yields only its short authored reply.
Two fixtures verify both quote removal and preservation of a sender/date line
without a corroborating mail-header block. Source messages and frozen reviewer
seeds are preserved.

The corrected 452-row local join passes canonical validation with zero errors.
The complete unit suite passes **106 tests**. All labels remain provisional
AI silver; a human calibration set and independent 300–500-record human gold
set are still required for final FYP evaluation. No classifier has been fitted
on this partial set.

At the later 618-row checkpoint, the supervisor read a deterministic SHA-256
sample of 20 accepted `NON_PROJECT` records, including full tails of longer
authored messages. The [text-free sampling log](../annotation/training_silver_negative_semantic_sample.json)
records IDs, source hashes, and boundary categories. The sample contains
personal/social mail, promotions, organizational notices, routine HR work,
automated invoice reminders, operational approvals, external regulatory
notices, commercial document transfer, and non-project business meetings.
No clear label error was found in those 20 cases; this qualitative sampling
does not estimate gold accuracy. Twelve of the 618 accepted current messages
are calendar/task exports, and all 618 source records are Enron. Target-domain
Outlook performance remains unverified.

A separate deterministic [positive sample](../annotation/training_silver_positive_semantic_sample.json)
contains three accepted examples per common positive label (12 sampling
assignments). Reading full authored text identified one shared deadline-label
error: a revised Phase 2 target date did not establish a required completion
point rather than a start or launch. That entire record was excluded through
the reproducible supervisor gate, leaving **617** eligible records. The
original silver labels are retained in the text-free sampling log for traceability;
the acceptance manifest holds empty labels for the excluded case. The other
sampled cases had no clear label error on this qualitative AI check.

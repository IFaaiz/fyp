# Silver training selection correction — 28 September 2026

The provisional 1,400-message selection was screened with project and PM cue
words. A supervisor check after the first two blind 300-message tranches found
that many later rows are sparse Outlook calendar or task exports. In particular,
seed rows 601–1,100 contain 498 calendar/task exports out of 500. The repeated
`Outlook Migration Team` chair or a cue in the title often does not establish
the meeting's project purpose. This was a candidate-selection error, not a
classification result. Blind review stopped after row 600; the already reviewed
601–740 decisions are preserved as ignored working data and are not accepted
for training by any manifest.

In rows 301–600, independent reviewers produced 200 exact label-set agreements.
Only 125 were exact, unflagged, and nonempty: 72 `NON_PROJECT` and 53 with at
least one project label. Fifty-four of those 125 are calendar/task exports.
Two of the 125 are in the curated leakage exclusion list, leaving at most 123
before third audit and supervisor checks. These are *candidates*, not accepted
silver training rows. The final gate for this tranche excludes sparse
calendar/task exports even when two reviewers agree, because the repeated
calendar boilerplate contributes little project-management evidence.

The replacement 1,200-message screening seed comes from the full Enron source.
It uses the authored prefix of `current_message` for screening, requires at
least 100 authored characters, removes obvious calendar/task exports and
embedded forwarded blocks, and requires early project context for the seven
project-enriched screening strata. Fifty cue-bearing records without a project
marker are retained as hard-negative candidates. Screening is not labelling.
Every selected source thread, normalized `current_message`, and full-corpus leakage
group is unique, and selected leakage groups are disjoint from the previous
1,400 selection and pilot/human assignment IDs. The ignored seed preserves raw
source text; the committed
[manifest](../annotation/training_silver_extension_1200_manifest.json) contains
IDs, hashes, screening strata, and leakage group IDs only.

Two blind AI reviewers are reviewing the replacement seed. A third independent
AI auditor checks every disagreement or review flag, all rare/multi-label
agreements, and a deterministic 20% sample of other agreements. A strict
adjudication gate excludes disagreements, flags, audit vetoes, and curated
leakage exclusions from high-confidence training. AI-silver remains provisional
and is not human gold.

A further 600-message reserve pool was screened with the `rare_project` profile
after the 1,200-message seed was frozen. Its text-free
[manifest](../annotation/training_silver_extension_600_manifest.json) contains
120 document-request, 100 departmental-input, 90 approval, 90 follow-up, 90
deadline, 90 meeting, and 20 other-project cue candidates. These are screening
strata, not labels. All 600 IDs, threads, and leakage groups are unique within
the reserve, and its leakage groups are disjoint from both the original 1,400
selection and the 1,200-message replacement. The ignored seed holds source text.
An initial review of its first 25 records found off-scope and quoted-message
risks, so none are accepted before blind review and independent audit.

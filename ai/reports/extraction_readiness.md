# Extraction readiness is separate from classification

MailEx supplies **2,922 unique provisional span proposals**, all marked
`requires_project_scope_human_review`. There are **zero human-reviewed or gold
FYP extraction spans**. Its 3,936 converted messages remain unlabelled for
FYP classification, and 327 have empty reconstructed message text. These
figures come from `mailex_stats.json` and the preserved source conversion;
they describe source coverage, not trustworthy extractor training labels.

| Provisional mapped span | Count | Current interpretation |
| --- | ---: | --- |
| ACTION_ITEM | 1,380 | Source action description; project scope and action semantics need review |
| PARTICIPANT | 603 | Meeting member; not necessarily an FYP assignee |
| MEETING_DATE | 389 | Meeting date in MailEx events; project scope needs review |
| AGENDA | 367 | Meeting agenda proposal; project scope needs review |
| MEETING_TIME | 240 | Meeting time in MailEx events; project scope needs review |

`DEADLINE_DATE`, `DEADLINE_TIME`, `RESPONSIBLE_PARTY`, `DEPARTMENT`,
`PROJECT`, and `REQUESTED_DOCUMENT` have **no direct canonical MailEx span
proposals**. MailEx retains 13,928 ambiguous source argument segments; these
must not be silently converted into the missing labels. Its token-joined text
also differs from the original Enron formatting, so offsets need checking
against the exact text used for any extraction model.

The next extraction gate is a separately sampled, human-reviewed calibration
set covering each span type and true negatives. A practical initial target is
roughly **50–100 verified positive instances per type**, plus ambiguous and
negative contexts, before deciding which types are learnable; rare types may
need targeted sampling beyond that. This is a collection target, not an
accuracy guarantee or a claim that those examples already exist. Date and
time recognition can start with deterministic parsing tied to a verified
meeting or deadline role. Names, departments, and project names may use
NER plus rules; `ACTION_ITEM`, `AGENDA`, and `REQUESTED_DOCUMENT` need
semantic review and likely structured extraction. No final extractor should
be trained or evaluated on these unverified proposals as truth.

Thread changes such as deadline moves, meeting reschedules, owner changes,
missing documents, and escalation need their own human-reviewed pair-level
dataset. The existing Enron heuristic links are candidates, not verified
conversation truth. MailEx's real thread structure is promising for sampling,
but it does not itself supply FYP change labels.
The separate [thread-change evaluation design](thread_change_evaluation_plan.md)
defines linked before/after states, authored evidence, human adjudication, and
cross-task leakage isolation for that future dataset.

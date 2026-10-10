# Final FYP pre-labeling audit — 10 October 2026

## Frozen contract

New human annotations use **fyp-direct-label-v1.1**. Scope remains PROJECT,
NON_PROJECT or UNCERTAIN. Humans directly choose the eight project labels:
MEETING, DEADLINE, REPORT_REQUEST, DEPARTMENTAL_INPUT, ACTION_REQUEST, FOLLOW_UP,
APPROVAL and GENERAL_UPDATE. NON_PROJECT is exclusive. No event graph, derived
label ontology, AI suggestions or peer prelabels are exposed.

Exactly 11 extraction targets remain:

1. MEETING_DATE
2. MEETING_TIME
3. DEADLINE_DATE
4. DEADLINE_TIME
5. ACTION_ITEM
6. RESPONSIBLE_PARTY
7. DEPARTMENT
8. REQUESTED_DOCUMENT
9. PARTICIPANT
10. AGENDA
11. PROJECT

EVIDENCE is auxiliary support. Each selected project label still needs
current-authored-message EVIDENCE. It is excluded from extraction agreement
counts, denominators and F1, with separate support-evidence metrics. INPUT and
APPROVAL_TARGET are rejected in new records; historical v1 remains preserved.

Extraction fields are optional. Annotated fields must be exact, grounded and
accurate. Explicit ACTION_ITEM and due dates/times are strongly encouraged.
Clear overdue deadlines or approval decisions do not require invented targets
or needs_review solely for absent fields. Needs_review covers semantic ambiguity,
uncertain scope or unresolved references; an UNCLEAR follow-up target needs a
reason and review. Label evidence cannot come only from quoted old messages.

Meeting dates are not deadlines; document delivery is not a document request;
department/person mentions do not establish input/responsibility. Ordinary
review is not formal approval. Re: alone is not follow-up. GENERAL_UPDATE is not
a fallback, and ACTION_REQUEST is not automatically added to another request.
The validator checks the human contract without automatically classifying text.

## Live state and safe version boundary

Pre-deployment metadata inspection found **one direct v1 draft and zero direct
submissions**. The draft is preserved under v1 in direct_reviews, with its
revision history. Version 1.1 uses new direct_label_reviews and
direct_label_review_revisions tables. Migration 0003 only creates these tables;
it does not update, delete, transform or backfill old records or sources.

The existing draft owner can download their original v1 record read-only. It
does not prefill the new review. Stale v1 writes return 409. Structured V1
storage, validator, schema, mapper, provenance and submitted records retain
their original meaning. Historical direct v1 schema/validator/comparator/test
snapshots are available. Previous reports, MailEx experiments and closed TEST
results are unchanged.

## Shared human calibration round

Live metadata confirms **47 sources total**, with **30 frozen round members**:
24 existing shared sources plus six existing calibration TRAIN sources.
All round source hashes match. **Zero holdout sources** occur in the round;
the **11 sealed holdout sources** remain excluded from round export.

Queue SQL already sorts round members first, then original source position.
Initial and next-email UI navigation chooses the first unfinished source in
that queue. That behavior is retained and tested; it prioritizes the shared 30
before unrelated personal assignments. Each reviewer works independently and
submitted records are frozen. Export requires the first two registered
reviewers to complete the same round; a third complete reviewer can be included.
All 30 count toward actual human calibration, not a disposable pilot or final
TEST. Individual submissions remain UNSET and require separate adjudication
before GOLD. No new dataset or model experiment was created.

## Verification and publication

Final checks passed. Tests use synthetic fixtures, not human answers or corpus
text. Three GPT-6 Luna xhigh subagents handled validator, agreement-tooling and
independent UI/API/migration checks; the root integrated and published them.

| Gate | Result |
| --- | --- |
| Python: Structured V1, direct v1, direct v1.1, both agreement versions, round migration | 70 tests passed |
| Legacy app validator | 51 checks passed |
| Legacy guidance / Unicode matching | 12 checks passed |
| Historical direct v1 validator | 69 checks passed |
| Current direct v1.1 validator | 76 checks passed |
| API, storage/version separation, locking, export and queue | 62 checks passed |
| Four-step UI/guidance contract | 16 checks passed |
| Total app checks | 286 passed |
| TypeScript typecheck | Passed |
| Production Vinext build | Passed |
| Whitespace / patch integrity | git diff --check passed |

The Python runtime lacks jsonschema; its supported fallback evaluator was tested.
The app validator independently checks the same contract. UI checks inspect
guidance, field choices and navigation code; they are not a browser interaction
test. No live annotation was created or submitted for verification.

The explicit synthetic scenarios cover: dated and implicit/overdue deadlines;
meeting dates without adding DEADLINE; document request versus delivered update;
department input versus a department merely copied; approval versus ordinary
review; current follow-up evidence; distinct operational ACTION_REQUEST;
NON_PROJECT exclusivity; UNCERTAIN without labels; quoted-history-only evidence
rejection; all 11 extraction types; rejection of INPUT / APPROVAL_TARGET; and
separate EVIDENCE metrics with no extraction contribution. Labels are human
semantic judgments, not automatically inferred from these fixtures.

### Verified production release

- Site version: **7**; deployment status: **succeeded**.
- URL: https://fyp-email-calibration.faaiznoman713.chatgpt.site/
- Pushed Site source SHA: `3bb97dc3394eb205f13089c817614deaa51103d5`.
- Audience: existing **custom/private** policy verified unchanged after release.
- Live schema includes both v1.1 tables, confirming migration 0003 applied.
- Post-release state: old direct table still has one draft and zero submissions;
  the new v1.1 review table is empty and ready for humans.
- Post-release round: 30 members; manifest identical to pre-release inspection;
  47 sources total, zero round hash mismatches, zero holdout members, 11 holdout
  sources retained.

The standard Windows packager required the broken local WSL installation.
Native Windows tar packaged the verified build instead, including hosting
metadata and all schema-only migrations. The Sites service accepted the exact
pushed source SHA and archive before deploying successfully. No WSL repair,
dependency upgrade, audience change or model research was performed.

The app retains the four-step Relevance → FYP labels → Evidence → Submit flow,
all 11 field choices, phrase reuse, exact copy/paste matching, draft saving,
uncertainty flags and next-email navigation. Current-message/source-hash checks,
server provenance stamps, same-origin writes, authenticated ownership,
revision locking, concurrent-save protection, peer blindness and submission
freezing remain enforced.

The next activity after a READY verdict is actual independent human annotation,
followed by comparison and separate adjudication. Training readiness and human
agreement are not claimed before that work.

**READY TO START HUMAN LABELING**

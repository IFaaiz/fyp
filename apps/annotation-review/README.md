# FYP Review Room

Private research annotation app. The Windows/Outlook product remains offline;
this website collects human research labels only.

## Frozen reviewer flow — fyp-direct-label-v1.1

1. **Relevance:** read the current authored message; choose PROJECT, NON_PROJECT
   or UNCERTAIN and give a short reason. History is context only.
2. **FYP labels:** select all supported categories: MEETING, DEADLINE,
   REPORT_REQUEST, DEPARTMENTAL_INPUT, ACTION_REQUEST, FOLLOW_UP, APPROVAL,
   GENERAL_UPDATE. NON_PROJECT is exclusive; UNCERTAIN has no project labels.
3. **Evidence / extraction:** highlight current-message EVIDENCE for every
   selected project label. Add extraction fields when explicitly written.
   Reuse a source phrase or use exact copy/paste matching as needed.
4. **Submit:** flag genuine semantic uncertainty or unresolved references,
   confirm independent human review, save a draft or submit and move next.
   Drafts autosave every ten seconds. Submitted blind answers are frozen.

The first round shares **30 existing real emails**: 24 blind sources plus six
eligible TRAIN sources in an additive hash-bound assignment overlay. All 30
are actual human calibration data, not a disposable pilot or final TEST.
Queue ordering places round members first; initial and next-email selection
pick the first unfinished entry. No ordering redesign was needed. The first two
registered reviewers must complete the round before private export unlocks;
a third complete reviewer can be included. Personal assignments follow.
Peer answers and AI suggestions are hidden. All 11 holdout sources are excluded
from the round/export. Individual submissions remain UNSET until separate
adjudication; they are never automatically GOLD.

### Extraction and support

Exactly 11 extraction targets:

- MEETING_DATE
- MEETING_TIME
- DEADLINE_DATE
- DEADLINE_TIME
- ACTION_ITEM
- RESPONSIBLE_PARTY
- DEPARTMENT
- REQUESTED_DOCUMENT
- PARTICIPANT
- AGENDA
- PROJECT

All 11 are available under any selected label when accurate and explicitly
written. ACTION_ITEM and deadline dates are strongly encouraged when present.
Missing fields do not invalidate a clear label or force needs_review. Exact
text, Unicode offsets and provenance are checked whenever a field is annotated.
Do not invent omitted dates, documents, people or actions.

**EVIDENCE is auxiliary support**, not a twelfth extraction target. It is required
for each project label and scored separately as support_evidence; extraction
exact/overlap metrics exclude it. INPUT and APPROVAL_TARGET are rejected in new
annotations. FOLLOW_UP may have no explicit target; an UNCLEAR target requires
a reason and review because that signals an unresolved reference.

Rules & examples explains the preserved boundaries: meeting dates are not due
dates; document delivery is not a request; department/person mentions do not
imply input/responsibility; ordinary review is not approval; Re: alone is not a
follow-up; GENERAL_UPDATE is not a fallback. Multiple labels require distinct
supported acts, without constructing an event graph or deriving labels.

## Version and storage boundaries

Before deployment, live metadata showed **one direct v1 draft and zero direct
submissions**. New v1.1 reviews use direct_label_reviews and
 direct_label_review_revisions. Migration 0003 creates these tables only.
The old draft remains in direct_reviews under its original schema and can be
downloaded by its owner through the read-only format=direct-v1 route. It is
never converted or used to prefill a new review. Stale v1 writes return 409.

Structured V1 records keep their original schema, mapper, revisions and tables;
the explicit legacy link still opens them. Historical direct v1 validators,
schemas and comparison code are retained as versioned snapshots. Source hashes,
original allocations and the sealed holdout are unchanged.

Sites access remains custom with the existing authorized accounts. Authentication
uses forwarded ChatGPT identities and D1 storage. ADMIN_EMAIL and IMPORT_KEY are
production secrets; no real account identity, credential, raw email or human
annotation belongs in Git. The read-only WebMCP guide never writes reviews.

## Development and checks

Use Node 22.13+ and the locked dependencies. The Sites starter and Vite plugin
are retained. The public GitHub mirror excludes dependencies and runtime data.

```powershell
npm ci
node node_modules/typescript/bin/tsc --noEmit
node tests/validation.mjs
node tests/guidance.mjs
node tests/direct-validation-v1.mjs
node tests/direct-validation.mjs
node tests/direct-api.mjs
node tests/final-ui.mjs
npm run build
```

Python mirrors are ai/src/fyp_direct_label_v1_1 (current),
ai/src/fyp_direct_label_v1 and ai/src/fyp_structured_v1 (historical).
The current guide is ai/annotation/fyp_direct_label_v1_1_annotation_guide.md;
the aggregate freeze report is ai/reports/fyp_prelabeling_final_audit_2026-10-10.md.

### Fresh local database

Apply migrations only to an appropriate local database; production publication
uses the Sites migration workflow. For a fresh checkout, after npm run build:

```powershell
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_crazy_caretaker.sql
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0001_curvy_shadowcat.sql
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0002_harsh_nightshade.sql
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0003_thin_blacklash.sql
npm run dev -- --host 127.0.0.1 --port 3000
```

The local mock account is restricted to loopback. Owner tools may use
ADMIN_EMAIL=seedy@sites.test in an ignored local .env. Without an authorized
private import packet the queue is empty. Tests use synthetic fixtures only.

Human agreement, adjudicated gold and training readiness remain unmeasured
until the actual human round and separate adjudication are complete.

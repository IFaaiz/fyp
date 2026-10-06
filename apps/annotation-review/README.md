# FYP Review Room

Private research annotation app for three students. The deployed Outlook product remains offline; this website collects human research labels only.

## Reviewer flow

1. Sign in using your own allowed ChatGPT account.
2. Open your unfinished email. Read the current authored message; quoted history is reference only.
3. Choose project relevance and give a short reason. Relevance highlights are optional.
4. Directly choose all applicable FYP labels: MEETING, DEADLINE, REPORT_REQUEST, DEPARTMENTAL_INPUT, ACTION_REQUEST, FOLLOW_UP, APPROVAL, GENERAL_UPDATE. NON_PROJECT comes exclusively from relevance.
5. Highlight current words under every selected label, then add required/optional extraction fields. Use **Rules & examples** or the exact copy/paste fallback when needed. A separate action label requires a distinct operational task.
6. Mark uncertainty for review. Drafts save every ten seconds and can resume on another device after saving.
7. Confirm independent human review and submit. Submitted blind answers are frozen.

The first round shares 30 existing real emails: the original 24 blind sources plus six eligible TRAIN sources in an additive hash-bound assignment overlay. It initializes on the first authenticated queue read; Study controls offers an idempotent preparation button. The first two registered reviewers must complete this round before private export unlocks. A third complete reviewer can be included. The remaining sources keep personal assignments. Peer answers are hidden. Holdout sources are excluded from this round and its export. Individual submissions remain UNSET until adjudication, never automatically GOLD.

New annotations use **fyp-direct-label-v1** in separate direct-review tables. Older Structured V1 drafts/submissions retain their original schema/mapper and storage. A reviewer can start a direct review of the same source without changing an old record, and open an old review through the explicit legacy link. Submitted records remain frozen in both formats.

## Storage and access

Sites platform access must remain `custom` with only the three named accounts. The app uses forwarded ChatGPT identities and D1 storage; it has no shared-password account chooser. Production ADMIN_EMAIL is a Sites secret. IMPORT_KEY permits the owner-authorized private corpus-loading helper and must never be put in Git or browser code. The platform service bearer is sent only to the exact registered Site origin.

Raw source emails and human exports are runtime data. They are absent from this source checkout and the public FYP Git repository. D1 migrations contain schema only. New deployments preserve existing review records.

## Development and checks

Use Node 22.13 or later. Dependencies are locked in package-lock.json. The original Sites starter scripts and `sites()` Vite plugin are retained.

- `npm run dev` starts the local preview; its mock account is seedy@sites.test, restricted to loopback.
- `node node_modules/typescript/bin/tsc --noEmit` checks types.
- `node tests/validation.mjs` checks all 16 synthetic schema fixtures and source/reference mutations.
- `node tests/direct-validation.mjs` checks direct-label evidence/provenance constraints.
- `node tests/direct-api.mjs` checks format, independent-save and export boundaries.
- `npm run db:generate` appends Drizzle schema migrations.
- Use the Sites build and publication helpers for deployment.

The public source mirror is `apps/annotation-review` in IFaaiz/fyp. It excludes node_modules, local test databases, credentials and real emails. Matching direct schema/validation is in ai/src/fyp_direct_label_v1. The legacy validator/mapper remains in ai/src/fyp_structured_v1. The direct guide and implementation report are in ai/annotation/fyp_direct_label_v1_annotation_guide.md and ai/reports/fyp_direct_label_redesign_2026-10-06.md.

## Fresh local checkout

This GitHub mirror contains the deployed application source and adds these local
setup notes. It excludes generated compiler state, runtime databases and emails.
From this directory with Node 22.13+ and npm installed:

```powershell
npm ci
npm run build
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_crazy_caretaker.sql
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0001_curvy_shadowcat.sql
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0002_harsh_nightshade.sql
npm run dev -- --host 127.0.0.1 --port 3000
```

Apply that initial schema command only to a fresh local database; later schema
changes require appended migrations. The schema-only command was checked against
a separate empty local D1 database. To expose local owner tools, set
`ADMIN_EMAIL=seedy@sites.test` in an ignored `.env` file before starting dev.
This is the starter's loopback mock account, not a production reviewer identity.
The queue starts empty without the authorized private corpus import packet.
`node tests/validation.mjs` uses synthetic fixtures without any corpus.

## Current limits

Direct FOLLOW_UP uses current reminder evidence and a simple prior-expectation category, without an event graph. Unclear targets require review. Legacy event-relation research remains available separately. Human agreement and adjudicated training readiness remain pending actual submissions.

The read-only WebMCP guide tool never writes annotations or claims to be a human reviewer. Browser/WebMCP runtime verification was unavailable in the current Windows sandbox; contract tests, HTTP authentication/save checks and the production build were run.

## Guided labeling interface

The app uses four steps: **Relevance → FYP labels → Evidence → Submit**. All eight final categories have plain-language definitions and examples. Required evidence is shown separately from optional fields. Highlighted evidence stays visible in the email; faded reference lines cannot become current evidence. Copy/paste finds only exact allowed occurrences, and phrases can be reused for extraction fields.

**Rules & examples** opens a keyboard-accessible guide. **Submit & next** opens the next unfinished source. Drafts autosave, accounts stay independent and original source assignments remain intact.

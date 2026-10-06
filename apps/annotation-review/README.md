# FYP Review Room

Private research annotation app for three students. The deployed Outlook product remains offline; this website collects human research labels only.

## Reviewer flow

1. Sign in using your own allowed ChatGPT account.
2. Open your unfinished email. Read the current authored message; quoted history is reference only.
3. Choose project relevance, give a short reason and add exact relevance evidence.
4. Add one event per distinct current act. Select its state, highlight its event words and connect the relevant people, dates, actions and documents.
5. Use the built-in guide and worked example. If highlighting fails, expand **Paste exact text**, copy the words and choose their occurrence.
6. Mark uncertainty for review. Drafts save every ten seconds and can resume on another device after saving.
7. Confirm independent human review and submit. Submitted blind answers are frozen.

All three students review the common blind subset; the other sources have personal assignments. Peers cannot read each other's answers. The owner sees aggregate progress; full export unlocks only when all three complete the shared subset. Individual submissions remain UNSET until adjudication, never automatically GOLD.

## Storage and access

Sites platform access must remain `custom` with only the three named accounts. The app uses forwarded ChatGPT identities and D1 storage; it has no shared-password account chooser. Production ADMIN_EMAIL is a Sites secret. IMPORT_KEY permits the owner-authorized private corpus-loading helper and must never be put in Git or browser code. The platform service bearer is sent only to the exact registered Site origin.

Raw source emails and human exports are runtime data. They are absent from this source checkout and the public FYP Git repository. D1 migrations contain schema only. New deployments preserve existing review records.

## Development and checks

Use Node 22.13 or later. Dependencies are locked in package-lock.json. The original Sites starter scripts and `sites()` Vite plugin are retained.

- `npm run dev` starts the local preview; its mock account is seedy@sites.test, restricted to loopback.
- `node node_modules/typescript/bin/tsc --noEmit` checks types.
- `node tests/validation.mjs` checks all 16 synthetic schema fixtures and source/reference mutations.
- `npm run db:generate` appends Drizzle schema migrations.
- Use the Sites build and publication helpers for deployment.

The public source mirror is `apps/annotation-review` in IFaaiz/fyp. It excludes node_modules, local test databases, credentials and real emails. Python's matching validator and mapper are in ai/src/fyp_structured_v1.

## Fresh local checkout

This GitHub mirror contains the deployed application source and adds these local
setup notes. It excludes generated compiler state, runtime databases and emails.
From this directory with Node 22.13+ and npm installed:

```powershell
npm ci
npm run build
node node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_crazy_caretaker.sql
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

The current public-corpus source packet has no verified prior thread events. Follow-ups can be captured with unresolved targets and review notes; full resolved SUPERSEDES relations require a later adjudicated context packet. This app does not invent thread identities. Human agreement and training readiness remain pending actual submissions.

The read-only WebMCP guide tool never writes annotations or claims to be a human reviewer. Browser/WebMCP runtime verification was unavailable in the current Windows sandbox; contract tests, HTTP authentication/save checks and the production build were run.

## Guided labeling interface

The app uses three steps: **Relevance → Label message → Check & submit**. Five plain-language choices (Meeting, Task, Document, Approval, Project update) include local examples. Required evidence is shown separately from optional names and dates. Highlighted evidence stays visible in the email; faded reference lines cannot become current evidence. Copy-and-paste finds only exact allowed occurrences. Tasks and updates can explicitly reuse the same phrase for their two required typed evidence fields.

**Help & examples** opens a keyboard-accessible guide. **Submit & next email** opens the next unfinished source. Drafts, independent account access, frozen submissions and existing assignments are preserved.

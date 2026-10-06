# FYP V1 calibration reviewer handoff

Checkpoint: 6 October 2026, Asia/Karachi. This is the current reviewer entry point;
the historical native MailEx benchmark remains closed.

## Decisions and delivered artifacts

1. Add an isolated V1 annotation contract; preserve V2 and historical datasets.
   Five event kinds, states, exact Unicode code-point spans, role links and
   explicit thread relations feed the nine deterministic downstream labels.
   Uncertain or review-needed records abstain. See the
   [migration decision](fyp_structured_v1_migration_decision.md),
   [schema](../config/fyp_structured_v1_schema.json) and
   [guide](../annotation/fyp_structured_v1_annotation_guide.md).
2. Use independent blind human calibration to establish the schema's quality.
   Individual submissions remain UNSET, with zero automatic GOLD promotion.
   No human agreement or model accuracy is claimed at this checkpoint.
3. Publish a private research annotation website with account identity, separate
   assignments, current-message evidence, labeling rules, autosaved drafts,
   optimistic revision checks and frozen blind submissions. The owner can see
   aggregate progress; peer answers export only after all three complete the
   common blind subset. Real emails are runtime data, absent from GitHub.
4. Stop the bounded native span-link diagnostic as incomplete. Zero of three
   seeds completed, no trained checkpoint was saved, and the earliest-attempt
   one-hour wall deadline has expired. The best partial corrected seed-17 DEV
   role-exact / linked partial-record F1 was 0.273255 / 0.418265. These observations
   are neither a three-seed mean nor end-to-end FYP accuracy. Read the
   [diagnostic audit](mailex_span_link_diagnostic.md); do not reset its budget.

## Published review app

- Site: [FYP Review Room](https://fyp-email-calibration.faaiznoman713.chatgpt.site).
- Project ID: `appgprj_6ac3e8e078408191904e6dbfdcc76eb4`.
- Pushed Site source: `c7a9e41d1880d6e8989dd926371e6af7682fa611`.
- Deployment: `appgdep_6ac4fb7498ec8191bceeae0046757861`; native status succeeded,
  with runtime environment revision 3.
- GitHub source mirror: [apps/annotation-review](../../apps/annotation-review/README.md).
  It copies the committed Site application source, excludes generated compiler
  state, and adds fresh-clone local setup notes in its README.
- Access remains private (`custom`): the owner and one authorized external
  reviewer are allowed, policy revision 2. The last teammate’s ChatGPT account
  address is still pending. Account addresses are omitted from this report.
  Three-person agreement/export remains gated until the third reviewer joins
  and all three complete the common blind subset.
- All 47 curated emails were imported: 24 common blind, 12 personal calibration
  TRAIN and 11 human holdout. Root audited all 38 proposed TRAIN/common sources,
  rejected two weak inclusions and corrected 36 evidence ranges. One overlapping
  holdout was conservatively removed without disclosing its content. Three
  boundary controls remain. See the [curation report](fyp_calibration_v1_curation.md).
  Historical enriched Enron is a fallback; no human labels or accuracy are claimed.
  The heldout prefix ranges still require independent human verification.

The website is a research data collection tool. The final Outlook 2016 Windows
product still requires local inference, ingestion, archive and dashboard work.

## Offline product progress

A loopback-only, dependency-free [desktop review prototype](../../desktop/README.md)
loads exact V1 packets, validates corrections and saves local records with hash-only
audit metadata. Imported GOLD is read-only; stale tabs receive HTTP 409. Synthetic
HTTP smoke checks passed. This prototype has no inference, Outlook ingestion, Excel
export, reminders or production audit recovery. Its editor is still structured JSON.

## Agreement and data handling

`ai/scripts/score_fyp_calibration_v1.py` consumes the app's actual private export
shape, checks exact-source V1 validation and canonical blind provenance, and
withholds metrics until all three submitted the common subset. It reports
scope Fleiss' kappa/unanimity, label supports and pairwise agreement, exact spans,
event-role tuples, uncertainty and measured active time. TRAIN and human holdout
are excluded from these agreement metrics. The report is aggregate only and
does not promote submissions to GOLD.

The source import helper verifies the frozen JSONL hash and sends batches to the
exact registered Site origin. Platform and import credentials travel through
hidden stdin and session memory; none is written to Git or shell arguments.
Private human exports must stay under ignored `ai/data/`. Separate human TRAIN
from the protected human holdout before constructing future labeler prompts.

## Verification and limitations

- Python V1 contract and agreement suites: 30 tests passed, using hand-authored
  synthetic fixtures. The agreement suite includes an unmocked complete path
  with the exact Site export fields, canonical provenance and Unicode offsets.
- Browser/server validator: 16 synthetic fixtures and 29 checks passed.
- Site TypeScript check and Cloudflare-compatible production build passed.
- Import guards passed six localhost synthetic checks: initial insert, idempotent
  re-import, changed-range conflict, bad digest, inconsistent assignment, overlapping
  ranges. Production corpus import inserted 47; its SHA matches the frozen packet.
- Local HTTP checks exercised unauthenticated rejection, save/recovery,
  stale-revision and frozen-submit rejection, server-assigned UNSET provenance,
  invalid offsets and authored/quoted boundaries. Local SQLite checks covered
  three identities, personal/common assignments and separate review answers.
- Preservation checks: 77 closed-experiment files and 231 checkpoint-manifest
  files remained intact; the checks performed no training or inference.
- Interactive browser selection and WebMCP runtime QA could not run: the Windows
  computer-use process failed to initialize. The UI includes a paste-exact-text
  fallback; do not describe its browser interactions as verified.
- Initial packets do not contain verified prior events. Unresolved follow-ups
  can be recorded with review notes; resolved supersession awaits verified
  context packets. No prior event identities are invented.
- A subagent's initial broad text search accidentally traversed raw corpus
  directories. Visible matches were MailEx TRAIN and the Enron maildir, and the
  output was truncated; protected TEST/EVAL visibility cannot be established
  from that output. It was not used to construct fixtures, rules or evaluations.
  Subsequent searches were confined to named source files. No new TEST/EVAL
  evaluation was run; preservation hashes alone cannot prove content was unseen.

## Next gates

Collect the first ten common sources independently per student and measure
effort/uncertainty, then complete blind calibration and human adjudication.
Freeze the schema only after agreement and source audits support it. Build an
automated labeler from human TRAIN examples, assess it on the separately
adjudicated human holdout, and scale SILVER only if that evaluation supports it.
Do not train on the synthetic contract fixtures or treat individual reviews as
gold. Follow the [relative product/calibration schedule](fyp_calibration_v1_schedule.md);
the actual submission/defense date is still unknown.

Re-import verification accepted all 47 frozen sources and inserted zero additional rows; immutable source text, authored ranges and assignments matched.

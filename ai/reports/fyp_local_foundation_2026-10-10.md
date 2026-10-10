# Local product foundation and reviewer handoff — 10 October 2026

Starting main was `c32f85f505edd9ba0b91b5efe11e28741b83df4c`, verified against
GitHub before edits. Three GPT-6 Luna xhigh subagents handled independent source
research and product implementation; the root agent integrated and reviewed it.
The repository's existing subagent TOML already contains the requested defaults.

## What changed

- New `desktop/local_product/` and `desktop/run_local_product.py`: .eml,
  normalized JSONL, optional .msg, and classic Outlook COM adapters; authored
  text isolation; rule suggestions; SQLite; Excel; basic PySide6 archive viewer.
- Local archive schema v2 has an additive provisional extraction column.
  Source scope/labels/spans and methods remain separate from rule or AI outputs.
- Eight direct FYP labels and 11 extraction targets retained. Missing detail
  stays unknown. No intermediate act layer, forced spans, inferred owners or
  synthesized dates. EVIDENCE remains auxiliary.
- Rule classification uses current authored text. Extraction supplies sparse
  exact-offset meeting/deadline date/time, requested-document and action cues;
  unsupported targets stay empty. Mixed date-role sentences abstain. Raw
  relative dates are not resolved to calendar values.
- JSONL acquisition URLs, checksums, reply-ID lists, split, leakage group,
  metadata quality and terms are retained in provenance. Source text stays local.
- Optional adapter runs the existing frozen AI-silver diagnostic classifier;
  inference does not retrain, tune, open TEST or require an online model API.
- Outlook import is read-only, newest first and bounded to 200 Inbox items by
  default (CLI range 1–5000). It reads MAPI message/reply/reference identifiers
  through PropertyAccessor and filenames through COM. No live mailbox was read.
- .msg opens with delayed attachment initialization, then reads only long/short
  filename metadata streams via the installed extract-msg public APIs. It does
  not construct attachment objects or access/save their payloads.
- SQLite is canonical; Excel writes literal string cells, strips invalid XML
  control characters and marks cell truncation at Excel's limit. Full stored
  text remains in SQLite. Export uses a temporary sibling and atomic replacement.
- Reimport is transactional and idempotent by source ID. Changed subject/current
  text on a source with owned annotations fails closed, preserving original text
  and annotation offsets.
- PySide supports local file import, bounded Outlook import, filter, sort,
  selection, authored/quoted text, provisional extraction and Excel export. Mail
  headings render as plain text. A conditional system-font fallback fixes an
  offscreen Windows font-discovery failure without bundling any font files.
- [Source inventory](fyp_source_inventory_2026-10.md), acquisition config/code,
  two independent research reports and current README pointers added.

The legacy `desktop/offline_dashboard.py`, annotation Site/schema/migrations,
first 30-email human round, historical datasets/reports/model artifacts and
closed MailEx TEST/results were preserved. No Site deployment was performed.

## Evidence and actual counts

| Check | Actual result |
|---|---|
| Existing parser/sampling/thread and annotation-contract regressions | **78 passed**, synthetic fixtures; no corpus TEST evaluation. |
| New public-mail normalization/mining tests | **14 passed**, synthetic and cached-fixture contracts; no network tests or human records. |
| Local product adapter/archive/Excel/extraction/preprocessing tests | **34 passed** in the workspace environment. |
| Total focused tests | **126 passed**. |
| Bounded source acquisition | 93 messages: 81 Apache and 12 W3C. 16 noise exclusions; 44 blank candidates; no acquisition failures. |
| Real JSONL import, first stage | 30 naturalistic Apache messages → SQLite 30 rows/12 threads → Excel 30 email rows/12 thread rows. Reimport: zero inserted, 30 updated; no duplicates. Rule ABSTAIN on all 30; zero extraction suggestions. |
| Real EML path | Those same 30 unchanged RFC822 payloads written as local .eml inputs → separate SQLite 30 rows/12 threads → Excel 30 rows. Decoded body and filenames round-tripped; replay added zero duplicates. |
| Real JSONL import, expanded stage | All 44 candidates → SQLite **44 rows/21 threads** → Excel Emails 44, Threads 21, Extraction Suggestions **7**. Source text/metadata/checksums remained consistent and source labels/spans stayed empty. |
| Expanded rule counts | **8 REVIEW / 36 ABSTAIN**. These are cue statuses, not predicted-correct counts. |
| Expanded extraction counts | Seven provisional exact-text suggestions: two DEADLINE_DATE, four MEETING_DATE, one ACTION_ITEM. No validated extraction accuracy measured. |
| Existing AI-silver bridge | One new Apache message scored on CPU with model downloads disabled; selected frozen run `ensemble_blend_1_0_3_0`, nine scores, REVIEW, human_gold=false. No training or TEST used. |
| PySide real-data smoke | 44 model rows; filtering W3C gives 10; selected authored text displayed; readable system font verified by inspecting rendered screenshot. |
| Human labels/gold generated by this work | **0 / 0**. |

The EML and JSONL checks reuse the same source messages and are not separate
datasets or independent accuracy samples. Functional round-tripping is evidence
that the pipeline works, not evidence of NLP correctness.

## What failed and was corrected

1. Historical W3C Windows-1252 pages were initially decoded as UTF-8, producing
   replacement characters. Declared charsets now decode strictly; no replacement
   characters remain in the selected W3C bodies.
2. Purposively selected W3C pages initially entered the naturalistic track.
   They now enter only ENRICHED_CHALLENGE; naturalistic sampling is restricted
   to the 65 eligible Apache fixed-month messages.
3. JSONL list-valued In-Reply-To, Outlook hidden MAPI properties, source metadata
   retention and parent-without-References grouping needed explicit handling.
   These are fixed and tested.
4. Quote-only inputs could become authored evidence, and Outlook header-block
   detection could remove preceding authored lines. Boundary tests now preserve
   authored requests and isolate quote/forward-only mail. HTML-only hidden
   script/style text and blockquotes are also excluded from current evidence.
5. The first MSG fake used a `rawAttachments` attribute absent from the pinned
   extract-msg version. An installed-library API audit caught it. The adapter
   now delays attachment construction and reads only documented directory/string
   metadata; the fake contract matches those APIs and rejects payload access.
6. The first offscreen screenshot rendered square glyphs despite a passing
   widget smoke. Inspecting the actual image caught the font problem; the
   corrected viewer now renders text legibly.
7. Preserving annotations while overwriting their source text would invalidate
   offsets. Annotated text conflicts now reject the transaction.

## Limits and current risks

This is a working local foundation, not a complete production dashboard. Real
Outlook 2016 COM and a real standalone MSG file have not yet been exercised;
their tests use fake adapters. The core .eml/JSONL path and real public-message
SQLite/Excel/PySide path were exercised. Outlook currently reads the default
Inbox; folder selection, incremental synchronization and scheduled imports are
not implemented. UI import is synchronous and bounded, not a background worker.

Authored-text isolation is conservative; unmarked or interleaved reply prose
can require manual review. Thread grouping is based on supplied/header anchors,
not semantic thread-state reasoning. No reminders, calendar writeback,
missing-document detection, human annotation editor, gold adjudication or
final-model selection was added. No accuracy claim follows from these checks.

The new sample is small, source/month-biased, and has no departmental-input
cues. Source rights are separate from public visibility; W3C training rights
remain NOT_CLEARED. Candidates are UNASSIGNED and do not form a new TEST.
Future training needs a global thread/template overlap audit and adjudicated
human gold. Raw mail, addresses, reviews, model weights, SQLite/Excel artifacts
and screenshots remain ignored local files.

The optional MSG library is GPL-licensed; the README and optional dependency
file record this. Private local use works; distribution/packaging terms need
review before shipping an executable. The desktop archive uses the Windows
user's local storage permissions; encryption and multi-user access controls are
not implemented.

## Run the verified local archive

From the repository root, this machine already has `desktop/.venv` with the
core and optional Windows dependencies. Fresh clones need the install steps in
[desktop README](../../desktop/README.md#local-email-archive-foundation); raw
sources and weights are deliberately not shipped in Git.

```powershell
# Mine/replay the documented bounded public sources:
python ai/scripts/acquire_project_mail.py --limit 120
python ai/scripts/acquire_project_mail.py --offline --limit 120

# Import, export and view (use the installed desktop interpreter):
desktop/.venv/Scripts/python.exe desktop/run_local_product.py import ai/data/project_mail/2026-10-10/candidates.jsonl --db ai/data/project_mail/2026-10-10/product_smoke/archive.sqlite3
desktop/.venv/Scripts/python.exe desktop/run_local_product.py export --db ai/data/project_mail/2026-10-10/product_smoke/archive.sqlite3 --xlsx ai/data/project_mail/2026-10-10/product_smoke/archive.xlsx
desktop/.venv/Scripts/python.exe desktop/run_local_product.py gui --db ai/data/project_mail/2026-10-10/product_smoke/archive.sqlite3

# User-initiated classic Outlook check; not run by this audit:
desktop/.venv/Scripts/python.exe desktop/run_local_product.py import-outlook --limit 200 --db desktop/.local/outlook_archive.sqlite3

# Focused local product tests:
desktop/.venv/Scripts/python.exe -m unittest discover -s desktop/tests -t . -v
```

On this machine the installed primary Python can run the acquisition commands
if `python` is still an unavailable Windows alias. Optional AI-silver inference
uses `ai/.venv/Scripts/python.exe` with `import ... --ai-silver`; a fresh clone
has no local model bundles. Its scores are diagnostic, not calibrated confidence.

## Next action

1. Team members complete the existing private blind 30-email round; score
   version-matched submissions and adjudicate separately. No auto-labelled GOLD.
2. Review public-source rights/privacy and select from the 44 blank candidates;
   use consented real project email for missing departmental/report language.
3. Test a bounded user-selected classic Outlook mailbox/MSG file locally, then
   add folder selection and incremental import while preserving provenance.
4. Build reviewed fields and explicit thread-state updates/reminders on top of
   SQLite; improve sparse baselines against new human DEV examples before
   considering a new bounded extraction experiment. Historical TEST stays closed.

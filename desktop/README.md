# Offline FYP review dashboard

This is a small Windows-friendly review prototype for FYP Structured Annotation V1. It uses only Python’s standard library plus the repository’s V1 validation and mapper modules. The selected interpreter is `ai/.venv/Scripts/python.exe`; no packages need to be installed.

## Start

From the repository root in PowerShell:

```powershell
& ai/.venv/Scripts/python.exe desktop/offline_dashboard.py
```

Open the exact loopback URL printed by the server, normally `http://127.0.0.1:8765/`. The process listens only on `127.0.0.1`. Stop it with **Ctrl+C**.

The dashboard opens a hand-authored synthetic example on startup. The amber badge and notice identify it as synthetic demo data; it is not real email or a human-reviewed gold record. Use **Synthetic examples** to select another standalone fixture, or **Open V1 packet file** to load a UTF-8 JSON packet.

## Packet file

The packet must be one JSON object with exactly these top-level fields:

```json
{
  "source": {
    "source_id": "source-id",
    "subject": "Message subject",
    "current_message": "Authored message text",
    "authored_ranges": [{"start": 0, "end": 21}]
  },
  "annotation": {
    "schema_version": "fyp-structured-v1"
  }
}
```

Provide the full annotation record required by `ai/config/fyp_structured_v1_schema.json`. Current-message spans must use exact offsets into `current_message` and fall within `authored_ranges`; the repository validator checks both conditions. Subject spans use exact subject offsets. The dashboard does not open a filesystem path supplied inside JSON, and it does not read mailboxes or source folders.

The annotation editor is a JSON structured editor. It supports corrections to scope, event states/classes, review status and reasons, spans, and event-span evidence links. **Validate annotation** runs the repository validator against the original source. The deterministic mapper runs only after valid annotation; its normal V1 review rules suppress labels while review is required. Provenance remains locked to the incoming packet for the session.

## Save and reload

Use **Save local review** to write under the ignored `ai/data/product_review/` directory:

- `originals/<id>.json` is created once with exclusive file creation and never overwritten by the dashboard.
- `records/<id>.json` contains the current packet and local review note.
- `audit/<id>.jsonl` appends a timestamp, annotation hash, validation counts, review state, and review-note hash for each save. It contains no source body or subject. Earlier annotation contents are not snapshotted, so the hash-only trail cannot reconstruct prior edits.

The app never raises an annotation tier or adds human-review provenance. Incoming `GOLD` packets open read-only because an edit would make their earlier human-review claim stale. Saved records use a revision check; if a second tab saves first, a stale tab gets a conflict and must reload. It does not auto-send messages, connect to Outlook, write Excel files, schedule reminders, call a model, or load remote assets. All review and storage operations stay on the local machine. Imported material is written only after an explicit save.

## Limits

This is a single-user prototype. It has no account system, access control between local Windows users, encrypted storage, multi-message context browser, email ingestion, workbook export, reminders, collaborative adjudication, or deployment path. The current packet format supplies one current source; cross-message relations that need prior context remain invalid unless a future packet/context workflow is added. The two synthetic fixtures that require prior-message context are therefore omitted from the standalone demo picker. Do not treat this prototype’s local audit files as a production audit system.

## Local email archive foundation

`run_local_product.py` is a separate local product foundation. It does not
replace or alter `offline_dashboard.py`. It imports `.eml`, `.msg`, normalized
JSONL, or the classic Outlook Inbox into a canonical SQLite archive, keeps
quoted history separate from current authored text, adds review-only rule cues,
stores sparse exact-text extraction suggestions in a separate provisional field,
exports `Emails`, `Threads`, and `Extraction Suggestions` workbook sheets, and
provides a small PySide6 archive browser.

The rule baseline only suggests possible labels. A cue gets `REVIEW`; no cue
gets `ABSTAIN`. It never writes those suggestions into the source `labels`,
scope, span, or annotation-method fields. A separate sparse extractor may
suggest exact-text spans; those stay provisional in their own SQLite field and
Excel sheet with `human_gold=false`, and never change source spans. Both systems
abstain on unsupported details and require review. The saved FYP label set is the eight approved project labels
plus exclusive `NON_PROJECT`; `PROJECT`/`UNCERTAIN` are scope values. The 11
approved extraction types are retained, with auxiliary `EVIDENCE` accepted as
evidence rather than an extraction target.

Install the core Windows dependencies and optional adapters in an ignored
workspace-local environment:

```powershell
py -3.12 -m venv desktop/.venv
desktop/.venv/Scripts/python.exe -m pip install -r desktop/requirements-windows.txt
```

`requirements-windows.txt` installs the PySide6 Essentials viewer, openpyxl, `extract-msg`
for standalone `.msg` files, and pywin32 for classic Outlook COM. The
`extract-msg` dependency is GPL-licensed; see `requirements-msg.txt` and review
its terms before distributing an application that includes it. `.eml` and
JSONL import plus SQLite do not depend on `extract-msg` or Outlook. No package
is needed to run the tests with Python's standard-library `unittest`, except
openpyxl for the Excel checks and PySide6 for the UI smoke.

Import the supplied normalized corpus (or a folder containing `.eml`, `.msg`,
and/or `.jsonl` files):

```powershell
desktop/.venv/Scripts/python.exe desktop/run_local_product.py import E:/path/to/corpus --db E:/path/to/archive.sqlite3
desktop/.venv/Scripts/python.exe desktop/run_local_product.py import-outlook --limit 200 --db E:/path/to/archive.sqlite3
desktop/.venv/Scripts/python.exe desktop/run_local_product.py export --db E:/path/to/archive.sqlite3 --xlsx E:/path/to/archive.xlsx
desktop/.venv/Scripts/python.exe desktop/run_local_product.py gui --db E:/path/to/archive.sqlite3
```

The default archive lives under the current user's local application-data
directory. The Excel writer stores email text as literal strings, marks cells
over the Excel 32,767-character limit, and leaves the full text in SQLite.
Attachment contents are never extracted or saved; only attachment filenames
are kept. The current Outlook adapter sorts the default Inbox by received time
and reads at most 200 newest messages by default (CLI limit range 1–5000) when
the user starts an import. It does not modify Outlook items. Tests use a fake
COM object, not a live mailbox.

The JSONL adapter accepts `source_id`, `source_name`, `project_or_list`,
`message_id`, `in_reply_to`, `references`, `thread_id`, `subject`, `sender`,
`recipients`, `timestamp`, `body_raw`, `current_message`, `quoted_history`,
`attachment_names`, `provenance`, `license_or_terms_note`, `labels`, `scope`,
`spans`, and `annotation_method`. It also accepts the repository's `email_id`,
`source_dataset`, `raw_body`, `body`, `sent_at`, and `project` aliases. Imported
annotations require an explicit `annotation_method`; duplicate source IDs
update unannotated message text and source provenance while preserving
already-owned annotations. If an annotated source reimport changes its subject
or current authored text, the transaction fails closed so span offsets and
annotations stay tied to their original text.
Additional source fields such as source URLs, checksums, split, leakage group,
and metadata quality are retained under `provenance.source_metadata`.

Run the focused product tests with:

```powershell
desktop/.venv/Scripts/python.exe -m unittest discover -s desktop/tests -t . -v
```

The UI is an archive browser skeleton. It does not yet provide annotation
editing, thread-state reasoning, reminders, or missing-document detection.

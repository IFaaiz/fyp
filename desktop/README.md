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

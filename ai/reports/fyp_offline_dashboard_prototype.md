# Offline FYP dashboard prototype

**Status:** Local prototype implemented 2026-10-06. This report contains no email text or source identifiers.

## What is available

The new `desktop/` app is a dependency-free, loopback-only review dashboard for the V1 `{source, annotation}` packet. It shows source identity, exact span excerpts and offsets, linked event cards, scope, and review state. The structured JSON editor can correct V1 fields; the repository validator checks exact slices and authored ranges before the deterministic mapper runs. Review-required annotations do not emit derived labels.

The synthetic picker uses the hand-authored fixture file, removes expected-label metadata from loaded packets, and marks the demo synthetic in the interface. Of 16 fixtures, 14 validate as standalone packets; two require earlier-message context and are omitted from this picker. Two of the 14 standalone-valid examples retain a human-review flag.

Saving creates a local immutable original packet, a current editable record, and an append-only metadata audit entry under ignored `ai/data/product_review/`. The audit entry records annotation and note hashes, timestamp, review state, and validation counts; it does not include source text. Provenance is locked to the imported packet. Imported GOLD packets are read-only, and concurrent tabs use a revision check that rejects stale saves with HTTP 409.

## Verification

The configured virtualenv has no `jsonschema` package, so the repository validator’s dependency-free fallback was exercised.

| Check | Result |
|---|---|
| Python and JavaScript syntax | Passed |
| Loopback bind address | `127.0.0.1` |
| Valid synthetic correction and derived label | Passed after server-side V1 validation |
| Incorrect exact evidence text | Rejected; mapper returned no labels |
| Save, reload, and second save | Passed; source and review note reloaded, original `created_at` stayed stable |
| Older tab after a newer save | Rejected with HTTP 409 |
| Imported GOLD edit | Rejected as read-only |
| Cross-origin mutation and unexpected Host | Rejected with HTTP 403 and 400 |
| Encoded traversal route and oversized request | Rejected with HTTP 404 and 400 |

Smoke records were removed after verification; no sample review was left in the local saved-record list.

## Limits

This is a single-user prototype without account isolation, encrypted storage, mailbox/Outlook ingestion, Excel output, reminders, model inference, external network requests, collaborative adjudication, or deployment support. The editor is a JSON editor rather than field-by-field controls. Packets with cross-message relations cannot be reviewed without their prior context. The audit stores hashes and state metadata, not full prior annotation snapshots, so it cannot reconstruct earlier edits; the current record retains only the latest annotation and review note. Do not use its local audit files as a production audit system.

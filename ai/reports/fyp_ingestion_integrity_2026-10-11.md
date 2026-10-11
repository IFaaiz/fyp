# Ingestion integrity packet — 11 October 2026

Starting and remote main: `3df6c0edaeaa4a06c368f8ee08581e889a0c6ec0`.
Delivery branch: `codex/ingestion-reviewed-workflow`. Revised proposal is
authoritative. This packet fixes archive integrity; it is not the complete FYP.

## Changes

MIME attachment boundaries exclude attached-email bodies from outer authored
text. Raw bodies survive adapter parsing. Versioned authored/quoted/uncertain
ranges preserve inline replies and explicitly withhold uncertain history.
SQLite schema 3 separates canonical messages from adapter observations and
source permissions. Conservative envelope/time/content identity handles absent
and reused IDs without granting combined access. Revision snapshots preserve
source history. UTC ordering retains sent/received meaning and unknown zones.
Conversation grouping resolves transitive and late parents, observation aliases
and decoded Thread-Index roots. Derived outputs bind to input revision, model,
schema and settings; stale outputs are cleared and reviewed conflicts fail closed.

Added a separate project-item contract, read-only Outlook installation preflight,
and integrity-checked SQLite backup. Migration/rollback procedures are in
`desktop/MIGRATIONS.md`; the complete revised scope is tracked in
`desktop/ACCEPTANCE.md`.

## Actual verification

`desktop/.venv/Scripts/python.exe -m unittest discover -s desktop/tests -t . -v`:
76 tests passed, including independent failure regressions, additive migration,
source-scope preservation, replay, stale predictions, timezone ordering,
Thread-Index and late-parent chains, uncertain inline segmentation, exact raw
body preservation, literal Excel cells, backup/restore and actual offscreen Qt
sorting. Fixtures are synthetic. EML tests parse generated real files; MSG and
Outlook are mocked. No private corpus, model weights or closed historical TEST
examples/evaluations were read or run.

`desktop/tests/reproduce_ingestion_v2.py` against the frozen starting commit
reproduced all six defect categories using synthetic inputs. It prints only
Boolean defect results. The current suite asserts repaired behavior separately.

`doctor-outlook`: Windows, pywin32 and classic COM registration present; Office
installation version `16.0.20430.20146`, product `O365HomePremRetail`.
No mailbox was opened. This is installation evidence, not live interoperability.
The user reports no Outlook test setup. An authorized profile/folder compatibility
test remains outstanding; no indiscriminate Inbox scan was performed.

## Limits and next packet

The current archive viewer remains a read-only browser. Deterministic outputs
remain review suggestions with no new accuracy claim. Attachment content, OCR,
LAN roles/authentication, background synchronization, durable reminders and
installer/clean-machine verification are outstanding. Next: persistent reviewed
candidate/item/history ledger, optimistic corrections and reversal, a localhost
service accessed by a desktop dashboard, and approved-item Excel export.
Full LAN permissions and document evidence will follow this first vertical path.

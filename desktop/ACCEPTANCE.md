# Revised proposal requirements-to-tests matrix

Authoritative scope: `FYP Proposal Revised.pdf` (10 pages), especially pages 3-8.
The older report is historical context. January 2027 submission is assumed;
feature freeze 20 December 2026; installable release/docs 31 December 2026.
Dates are targets. A test named here is not evidence until its actual run is
recorded in the handoff. All current automated desktop fixtures are synthetic.

| ID | Mandatory behavior | Component / acceptance evidence | Current status / remaining gate |
|---|---|---|---|
| I1 | Attached email/document never becomes outer-author evidence | `test_mime_integrity.py`: nested RFC822, HTML, multipart, unnamed attachments | Implemented; bounded attachment-content parsers remain separate |
| I2 | One canonical message, adapter observations, collision/replay safety | `test_ingestion_integrity.py`, independent `test_integrity_review.py` | Verified by synthetic suite (76 passed); conservative ambiguous observations remain separate |
| I3 | UTC ordering plus original sent/received/unknown/date-only values | `test_time_contract.py`, `test_ingestion_integrity.py` | Implemented time contract; storage migration verified synthetically |
| I4 | Transitive replies, late parents, cross-adapter aliases, Thread-Index roots | `test_time_contract.py`, `test_ingestion_integrity.py` | Verified by synthetic suite (76 passed); semantic grouping not claimed |
| I5 | Source revisions, derivation binding, stale results, reviewed conflicts | `test_ingestion_integrity.py`, old annotation-conflict regression | Verified by synthetic suite (76 passed); model settings must be explicitly fingerprinted |
| I6 | Raw evidence and authored/quoted/uncertain ranges, inline replies | `test_inline_integrity.py`, `test_preprocessing.py` | Implemented; explicit history tails stay uncertain and visible |
| R1 | Windows desktop application | PySide archive viewer; future service-client project dashboard | Partial; clean-machine installer/offline CPU verification outstanding |
| R2 | Classic Outlook, selected folders, bounded background sync/recovery | Adapter mocks `test_adapters.py`; `doctor-outlook` installation preflight | Partial; selected folders/checkpoints/background jobs and authorized live profile test outstanding |
| R3 | English classification / eleven-target extraction / explicit review | `test_baseline.py`, `test_extraction.py`; frozen direct v1.1 contract | Sparse offline deterministic candidates only; new bounded model comparison/human validation outstanding |
| R4 | Word document content with exact document evidence | Planned isolated DOCX parser and legacy DOC policy | Not implemented; encrypted/corrupt/macros/unsupported/time/size-limit tests required |
| R5 | PDF content with exact document evidence | Planned isolated text-PDF parser | Not implemented; page limits/encryption/corruption/isolation tests required |
| R6 | Scanned-image content/OCR with uncertainty | Planned PNG/JPEG/TIFF and scanned-PDF OCR | Not implemented; pixel/page/time limits, incorrect OCR and coordinate tests required |
| R7 | Task, meeting, document-request, input, approval, follow-up identities | Separate `fyp-project-item-v1` product contract | Pending reviewed ledger; several independent items per thread required |
| R8 | Later reschedule/reassign/deliver/complete/cancel/correct, undo/history | Planned candidate → review → transition ledger | Pending; out-of-order/conflict/replay/concurrent-edit tests required |
| R9 | Dashboard, search, filters, settings and roles | Archive filtering exists; project-service views planned | Partial; read-only email table is not completed project dashboard |
| R10 | Durable reminders/alerts and missing-document expectations | Planned persistent jobs/delivery dedup and sync coverage | Not implemented; obsolete-job cancellation/restart/sleep/outage tests required |
| R11 | Excel recordkeeping/export | `test_store_export.py`, literal/formula/truncation checks | Email/thread/suggestion export implemented; approved-item/history and authorization-scoped export pending |
| R12 | Senior-manager/project-manager/team-member access/views | Planned server users, roles, projects, departments, assignments | Not implemented; source permissions separate from derived item permissions, denial/revocation/audit tests required |
| R13 | Single-user local and authenticated LAN service/client operation | Planned single API/service host with local SQLite | Archive single-user only; LAN TLS/auth/concurrent-client tests outstanding; never shared writable DB/Excel |
| R14 | Security, storage, backup/restore and installation documentation | `.gitignore`, transactional schema migration; integrity-checked online backup | Partial; synthetic restore passed; protected documents, license notices and clean-machine release required |
| R15 | Honest evaluation and review workload | Preserved aggregate reports; frozen historical TEST closed | No new accuracy claim; future unexposed permitted item/link/transition set required |

No raw email, private review, attachment, screenshot, credential, runtime DB or
model weight is committed. Code searches positively allowlist source/test/docs;
corpus directories including MailEx `full_data` are never search targets.

## Current acceptance commands

```powershell
desktop/.venv/Scripts/python.exe -m unittest discover -s desktop/tests -t . -v
desktop/.venv/Scripts/python.exe desktop/run_local_product.py doctor-outlook
```

Installation metadata is not a live Outlook interoperability result. Model
reports are historical aggregate evidence, not new production accuracy.

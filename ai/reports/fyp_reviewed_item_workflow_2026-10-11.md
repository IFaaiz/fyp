# Persistent reviewed-item workflow — 11 October 2026

Branch: `codex/ingestion-reviewed-workflow`. Builds on the pushed ingestion
integrity commit `5b2473e`. Primary agent integrated and reviewed bounded
GPT-6 Luna xhigh workers. The revised proposal remains the final delivery scope.

## Implemented behavior

The PySide6 desktop now completes Email → deterministic candidate → approve /
correct / reject → persistent item → search/filter dashboard → explicit later
update → Excel. It calls one authenticated loopback application service; it never
opens SQLite. A random owner token stays in process memory. The service binds
only `127.0.0.1`, requires the token on every implemented endpoint, rejects
untrusted Host/Origin and ambiguous/oversized JSON, and returns bounded generic
errors without echoing source data. The client refuses redirects to protect its
token and performs requests off the GUI thread. Closing waits for active requests.

Product schema `fyp-project-item-v1` is separate from frozen direct-label-v1.1
and archive schema 3. Persistent candidates carry exact evidence, canonical
source fingerprint/revision, unresolved review flags and an explicit optional
target item/version. Approval creates an independent identity or applies a patch
to that target. Several items can belong to one conversation. Owners and normalized
dates are not invented by heuristic suggestions. A reviewer supplies confirmed
dates/owners and a reason for corrections. Candidate predictions remain separate
from approved facts; no human-gold tier is asserted by this workflow.

Replay requires the same decision/version/fields/note and creates no new item or
event. A different replay or competing target edit conflicts. Changed source
evidence cannot be approved; stale attempts remain conflicts on replay. Approved
facts survive reimport with explicit warnings from any altered historical source.
History records before/after state, field differences, exact evidence and notes;
triggers prevent update/delete through SQLite. Undo appends a reversal; reversing
creation retains a cancelled identity. Warnings conservatively retain obsolete
history conflicts; automatic reconciliation is pending.

The desktop shows readable approved fields and history, exact evidence, original
raw message and quoted/uncertain history, target links and review warnings.
Existing-item forms send only changed fields, including intentional clears.
`Items`, `History` and `Metadata` Excel sheets use one consistent database
snapshot, literal formula-safe strings, bounded cells and atomic publication.
The online backup preserves the ledger as well as source revisions.

## Actual primary verification

```powershell
$env:FYP_TEST_LOCALHOST_API='1'
desktop/.venv/Scripts/python.exe -m unittest discover -s desktop/tests -t . -q
```

**99 tests passed, no skips**, final primary run: 9.637 seconds. This includes:

- The ingestion regressions and independent primary review checks.
- Generated EML and JSONL files plus real adapter code paths with mocked MSG
  metadata and Outlook COM: four observations become one canonical message,
  each scope remains distinct, and replay retains one revision.
- Exact evidence rejection, multiple items per thread, unresolved dates,
  candidate decisions/replay, source revision conflicts, corrections and reversal.
- Actual simultaneous HTTP target approvals: exactly one succeeds, one conflicts,
  and only one transition is appended. Unauthorized access, untrusted origin/host,
  invalid/unknown/duplicate JSON keys and oversized bodies fail without echoing
  synthetic private sentinels.
- Actual offscreen Qt client through the authenticated HTTP service: Suggest →
  Approve → SQLite item → displayed history. Separate controls test corrections,
  explicit targeting, status/search and in-flight window closing.
- Excel workbook contents/literal formulas and backup restoration/reopen through
  the service, retaining item IDs, versions and history.

Primary synthetic demonstration: four messages imported twice, two project items.
One report goes from Friday 16 October to Monday 19 October, changes from Sam
to Alex, and reaches reviewer-confirmed DELIVERED at version 4; its meeting stays
separate. Actual native Qt renders were visually inspected using synthetic text
only. Runtime databases, images and preview script remain ignored, outside Git.
The offscreen platform had an empty font database; the UI now reads installed
Segoe UI as a local font fallback for legible rendering.

`git diff --check` passed. Python/Qt/openpyxl functional evidence is local to this
Windows environment; it is not a clean-machine installer or scale certification.
The sandbox initially denied loopback sockets (WinError 10013); narrowly scoped
approved test execution succeeded. No pending approval block remains.

## Run and boundaries

```powershell
desktop/.venv/Scripts/python.exe desktop/run_local_product.py dashboard --demo
desktop/.venv/Scripts/python.exe desktop/run_local_product.py dashboard --db E:/private/project.sqlite3
desktop/.venv/Scripts/python.exe desktop/run_local_product.py export-items --db E:/private/project.sqlite3 --xlsx E:/private/items.xlsx
```

The demo is identified as synthetic and defaults to a separate database.
Dashboard launch never opens Outlook. Existing host-side file import remains
available. See `desktop/README.md`, `desktop/MIGRATIONS.md` and the single revised
requirements matrix `desktop/ACCEPTANCE.md`.

This is a usable single-owner review workflow, not the completed FYP. LAN
accounts/roles/project/source permissions, selected-folder background Outlook
sync/checkpoints, isolated Word/PDF/OCR content, settings, durable reminders and
alerts, protected document storage and an installable clean-machine release remain
mandatory. Current API lists are unpaginated and the client caps responses at
32 MiB; large-archive measurement and pagination remain needed. Date-only item
deadlines await project/calendar timezone policy before timed reminder scheduling.
Filename-only imports do not satisfy the final attachment-content requirement;
delivery here is an explicit review action. No reminders or outbound emails are
sent by this packet.

Outlook installation preflight passed, but there is no authorized test setup yet;
no live mailbox read was performed. Historical classifier/MailEx TEST is still
closed. No raw corpus, model weight, private source/review or credential entered
Git; no new training/evaluation or accuracy claim was made.

Next concrete packet: server-owned users/roles/projects/assignments and separate
source/item authorization, with denial/revocation/export tests, followed by LAN
transport/client configuration and bounded selected-folder synchronization.
Attachment parsers/OCR and durable reminder work remain visible in the matrix.
Targets remain feature freeze 20 December and release/docs 31 December 2026;
January 2027 is reserved for submission fixes and presentation.

# Archive v2 → v3 migration and rollback

The ingestion release retains `emails.source_id` as the canonical key of an
existing archive record. It adds observations, source aliases, input revisions,
derivation metadata and UTC ordering. Schema changes and backfill run in one
SQLite transaction; a failure rolls back. Newer databases fail closed when
opened by an older application. No corpus/model/research annotation table is
migrated. The frozen direct-label-v1.1 annotation contract is unchanged.

## Before opening an existing archive

Take a snapshot while the archive is still at its old schema. The backup command
uses SQLite's consistent backup API, checks integrity and refuses overwrite;
it runs before `EmailStore` initialization or migration:

```powershell
desktop/.venv/Scripts/python.exe desktop/run_local_product.py backup --db E:/private/archive.sqlite3 --to E:/private/backups/archive-before-v3.sqlite3
```

Keep backups protected with the same Windows permissions as the source. They
contain private source text and reviews. Never commit or share them as reports.

## Compatibility and identity policy

- Existing canonical rows and annotations are retained. The migration does not
  destructively combine historical duplicate rows. A future historical-merge
  tool must review competing facts/permissions explicitly; new imports dedup.
- Adapter observations retain their own headers/provenance and access-scope
  values. `UNSPECIFIED` is unknown access, never a public or organization grant.
  Deduplication is an identity operation, not authorization.
- Compatible Message-ID plus envelope/body/attachment evidence can alias across
  adapters. Reused IDs with incompatible evidence remain separate; ambiguous
  source IDs fail closed. Missing IDs require stronger envelope/time evidence.
  Ambiguous observations may remain duplicate rather than inventing identity.
- Raw sent/received timestamps and uncertain values stay available. Only known
  instants participate in UTC ordering. Date-only, naive and malformed values
  never gain an assumed timezone.
- Reply graphs may change canonical conversation IDs when late ancestors arrive.
  Raw adapter hints remain in observations. Project item identity must be
  independent of conversation identity; a thread is never a single task.
- Derived results bind to input revision/fingerprint and processing contract.
  Changed input invalidates active predictions. An owned annotation conflict
  rejects the import transaction rather than moving offsets to changed text.
  Revisions retain earlier local source evidence for audit.

## Restore / rollback

Close clients and stop the application/service. Copy the pre-migration backup to
a **different** protected database filename, preserving the original and its
SQLite sidecar files. Point the old application version at that copied backup;
never lower `PRAGMA user_version` or remove migration columns by hand. Alternatively
open the restored snapshot with the current version and allow its migration.
Verify `PRAGMA integrity_check` and expected record counts before resuming.

The synthetic backup test restores into a separate archive and checks integrity
and message content. It is a functional restore drill, not a real organizational
disaster-recovery certification. A clean-machine/operator restore drill remains
part of the December release gates in `ACCEPTANCE.md`.

## Reviewed item ledger

Starting the project dashboard or approved-item export adds `product_meta`,
`item_candidates`, `items`, and `item_history` transactionally. This product
contract is `fyp-project-item-v1`, with its own schema version 1; archive
`PRAGMA user_version` remains 3. No historical research annotation is changed.
Explicit canonical IDs bind product evidence; ambiguous adapter alias lookup
remains fail-closed through the archive compatibility API.

History rows preserve before/after facts, field differences, exact candidate
evidence, source fingerprint/revision and the review note. SQLite triggers reject
history updates/deletes. Undo appends a new event; undoing creation retains a
cancelled item. A source reimport never rewrites approved facts. A changed source
in any applied history produces a conservative conflict warning, even if a later
update has linked another source. Re-review is required to resolve those warnings;
automatic reconciliation is not implemented.

The consistent backup includes all ledger tables and immutable history. The
HTTP integration fixture restores it to a new database and verifies the same
item identities, versions and history. An old archive viewer does not provide
the new reviewed workflow; rollback to a pre-ledger backup also excludes reviews
made after that backup. Preserve the current database and backup before rollback.

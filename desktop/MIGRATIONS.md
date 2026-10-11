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

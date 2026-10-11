"""Consistent SQLite snapshots; source databases are never implicitly created."""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import tempfile


def backup_database(source: str | Path, destination: str | Path) -> Path:
    origin, target = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
    if not origin.is_file():
        raise ValueError("The source database does not exist")
    if target.exists() or origin == target:
        raise ValueError("Backup destination must be a new file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".sqlite3", delete=False) as handle:
        scratch = Path(handle.name)
    try:
        with closing(sqlite3.connect(origin.as_uri() + "?mode=ro", uri=True)) as input_db, closing(sqlite3.connect(scratch)) as output_db:
            input_db.backup(output_db)
            if output_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
        # Windows rename refuses an existing target. On POSIX an exclusive link
        # avoids rename's overwrite behavior. Both publish the complete snapshot.
        if os.name == "nt":
            os.rename(scratch, target)
        else:
            os.link(scratch, target)
    finally:
        scratch.unlink(missing_ok=True)
    return target

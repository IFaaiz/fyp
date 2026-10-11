from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from desktop.local_product.backup import backup_database
from desktop.local_product.models import EmailRecord
from desktop.local_product.store import EmailStore
from desktop.tests.support import temporary_directory


class BackupTests(unittest.TestCase):
    def test_backup_restores_archive_and_rejects_overwrite(self):
        with temporary_directory() as folder:
            origin, target = Path(folder) / "archive.sqlite3", Path(folder) / "restored.sqlite3"
            store = EmailStore(origin)
            store.import_records([EmailRecord(source_id="synthetic", source_name="synthetic", body_raw="A", current_message="A")])
            backup_database(origin, target)
            restored = EmailStore(target)
            self.assertEqual(restored.count(), 1)
            self.assertEqual(restored.get_email("synthetic")["body_raw"], "A")
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            with self.assertRaises(ValueError):
                backup_database(origin, target)
            with self.assertRaises(ValueError):
                backup_database(Path(folder) / "absent.sqlite3", Path(folder) / "bad.sqlite3")

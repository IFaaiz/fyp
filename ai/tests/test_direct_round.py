"""Exercise the additive round/schema migrations with synthetic fixture rows."""

import json
import re
import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "annotation-review"


class DirectRoundMigrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(
            """
            CREATE TABLE reviewers (
              user_id TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT NOT NULL,
              slot INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL
            );
            CREATE TABLE sources (
              id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, subject TEXT NOT NULL,
              body TEXT NOT NULL, source_json TEXT NOT NULL, sha256 TEXT NOT NULL,
              allocation TEXT NOT NULL, common_blind INTEGER NOT NULL,
              owner_slot INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE reviews (
              source_id TEXT NOT NULL REFERENCES sources(id), user_id TEXT NOT NULL REFERENCES reviewers(user_id),
              annotation_json TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
              active_ms INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              submitted_at TEXT, PRIMARY KEY(source_id,user_id)
            );
            CREATE TABLE review_revisions (
              id TEXT PRIMARY KEY, source_id TEXT NOT NULL, user_id TEXT NOT NULL,
              revision INTEGER NOT NULL, annotation_json TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        self.db.executemany(
            "INSERT INTO reviewers VALUES(?,?,?,?,?)",
            [(f"reviewer-{slot}", f"r{slot}@example.test", f"Reviewer {slot}", slot, "t0") for slot in range(3)],
        )

        fixture_sources = []
        for position in range(24):
            fixture_sources.append((f"blind-{position + 1:02d}", position, "blind_agreement", 1, position % 3))
        for ordinal in range(8):
            fixture_sources.append((f"train-{ordinal + 1:02d}", 24 + ordinal, "calibration_training", 0, ordinal % 3))
        fixture_sources.append(("holdout-01", 32, "labeler_human_holdout", 0, 2))
        self.db.executemany(
            "INSERT INTO sources(id,position,subject,body,source_json,sha256,allocation,common_blind,owner_slot,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                (source_id, position, f"Synthetic {source_id}", "Synthetic fixture only", json.dumps({"data_origin": "SYNTHETIC"}),
                 f"hash-{source_id}", allocation, common_blind, owner_slot, "t0")
                for source_id, position, allocation, common_blind, owner_slot in fixture_sources
            ],
        )
        self.original_allocations = self.db.execute(
            "SELECT id,position,sha256,allocation,common_blind,owner_slot FROM sources ORDER BY position"
        ).fetchall()
        self.db.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            ("blind-01", "reviewer-0", json.dumps({"schema_version": "fyp-structured-v1", "marker": "legacy"}),
             "draft", 4, 10, "t0", "t1", None),
        )

        for migration in ("0001_curvy_shadowcat.sql", "0002_harsh_nightshade.sql"):
            self.db.executescript((APP / "drizzle" / migration).read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()

    def test_actual_round_insert_is_ordered_training_only_and_additive(self):
        round_source = (APP / "lib" / "round.ts").read_text(encoding="utf-8")
        match = re.search(
            r"d\.prepare\(`(INSERT OR IGNORE INTO calibration_round_sources[\s\S]*?)`\)\.bind\(roundId,new Date\(\)\.toISOString\(\)\)\.run\(\)",
            round_source,
        )
        self.assertIsNotNone(match, "prepareRound must keep one explicit source-selection statement")
        statement = match.group(1)
        self.assertIn("common_blind=1 OR id IN", statement)
        self.assertRegex(statement, r"allocation='calibration_training' AND common_blind=0 ORDER BY position LIMIT 6")
        self.assertNotIn("labeler_human_holdout", statement)

        self.db.execute(statement, ("fyp-direct-round-1", "t-round"))
        actual = self.db.execute(
            "SELECT source_id,position FROM calibration_round_sources WHERE round_id=? ORDER BY position",
            ("fyp-direct-round-1",),
        ).fetchall()
        self.assertEqual(len(actual), 30)
        self.assertEqual([source_id for source_id, _ in actual[:24]], [f"blind-{i:02d}" for i in range(1, 25)])
        self.assertEqual([source_id for source_id, _ in actual[24:]], [f"train-{i:02d}" for i in range(1, 7)])
        self.assertNotIn("holdout-01", [source_id for source_id, _ in actual])

        # Repeating setup is idempotent and preserves the exact source snapshot.
        self.db.execute(statement, ("fyp-direct-round-1", "t-round-2"))
        self.assertEqual(actual, self.db.execute(
            "SELECT source_id,position FROM calibration_round_sources WHERE round_id=? ORDER BY position",
            ("fyp-direct-round-1",),
        ).fetchall())
        self.assertEqual(self.original_allocations, self.db.execute(
            "SELECT id,position,sha256,allocation,common_blind,owner_slot FROM sources ORDER BY position"
        ).fetchall())

    def test_legacy_and_direct_records_can_coexist_for_same_reviewer_and_source(self):
        self.db.execute(
            "INSERT INTO direct_reviews VALUES(?,?,?,?,?,?,?,?,?)",
            ("blind-01", "reviewer-0", json.dumps({"schema_version": "fyp-direct-label-v1", "marker": "direct"}),
             "submitted", 1, 20, "t2", "t3", "t3"),
        )
        legacy = self.db.execute("SELECT annotation_json,revision FROM reviews WHERE source_id=? AND user_id=?", ("blind-01", "reviewer-0")).fetchone()
        direct = self.db.execute("SELECT annotation_json,revision FROM direct_reviews WHERE source_id=? AND user_id=?", ("blind-01", "reviewer-0")).fetchone()
        self.assertEqual(json.loads(legacy[0]), {"schema_version": "fyp-structured-v1", "marker": "legacy"})
        self.assertEqual(legacy[1], 4)
        self.assertEqual(json.loads(direct[0]), {"schema_version": "fyp-direct-label-v1", "marker": "direct"})
        self.assertEqual(direct[1], 1)


if __name__ == "__main__":
    unittest.main()

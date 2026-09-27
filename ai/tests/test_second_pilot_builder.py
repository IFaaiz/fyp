"""Safety checks for the second pilot seed."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_project_pilot_v2


class SecondPilotBuilderTests(unittest.TestCase):
    def test_rejects_first_pilot_thread_even_with_a_new_email_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            current, first = base / "second.json", base / "first.json"
            first_seed, pool = base / "first.jsonl", base / "pool.jsonl"
            current.write_text(json.dumps({"selected_email_ids": ["enron-new"]}), encoding="utf-8")
            first.write_text(json.dumps({"selected_email_ids": ["enron-old"]}), encoding="utf-8")
            first_seed.write_text(json.dumps({
                "email_id": "enron-old", "thread_id": "shared-thread", "current_message": "Old body"
            }) + "\n", encoding="utf-8")
            pool.write_text(json.dumps({
                "email_id": "enron-new", "thread_id": "shared-thread", "current_message": "New body"
            }) + "\n", encoding="utf-8")
            with patch.object(build_project_pilot_v2, "CONFIG_PATH", current), patch.object(
                build_project_pilot_v2, "FIRST_CONFIG_PATH", first
            ), patch.object(build_project_pilot_v2, "FIRST_SEED_PATH", first_seed), patch.object(
                build_project_pilot_v2, "POOL_PATH", pool
            ), patch.object(build_project_pilot_v2, "OUTPUT_DIR", base / "output"):
                with self.assertRaisesRegex(ValueError, "overlaps a first-pilot thread"):
                    build_project_pilot_v2.build_second_pilot_seed()
            self.assertFalse((base / "output").exists())

    def test_rejects_overlap_with_first_pilot_before_writing_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            current = base / "second.json"
            first = base / "first.json"
            current.write_text(json.dumps({"selected_email_ids": ["enron-repeat"]}), encoding="utf-8")
            first.write_text(json.dumps({"selected_email_ids": ["enron-repeat"]}), encoding="utf-8")
            with patch.object(build_project_pilot_v2, "CONFIG_PATH", current), patch.object(
                build_project_pilot_v2, "FIRST_CONFIG_PATH", first
            ), patch.object(build_project_pilot_v2, "OUTPUT_DIR", base / "output"):
                with self.assertRaisesRegex(ValueError, "overlaps first pilot"):
                    build_project_pilot_v2.build_second_pilot_seed()
            self.assertFalse((base / "output").exists())


if __name__ == "__main__":
    unittest.main()

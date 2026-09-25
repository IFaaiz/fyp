"""Integration tests for the local two-reviewer annotator backend."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.annotation.agreement import compare_reviewer_records
from src.annotation.label_studio import python_to_utf16_offset
try:
    from ai.annotation.simple_annotator import create_app
    from ai.annotation.simple_annotator import store as annotator_store
except ModuleNotFoundError:
    from annotation.simple_annotator import create_app
    from annotation.simple_annotator import store as annotator_store
from src.datasets.schemas import read_jsonl, write_jsonl
from src.datasets.validation import validate_record


AI_DIR = Path(__file__).resolve().parents[1]
SEED_PATH = AI_DIR / "data" / "annotated" / "human" / "label_studio_seed" / "reviewer_a_transport.jsonl"
MANIFEST_PATH = SEED_PATH.with_name("manifest.json")


class SimpleAnnotatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_records = list(read_jsonl(SEED_PATH))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="simple-annotator-")
        self.addCleanup(self.temp.cleanup)
        self.temp_dir = Path(self.temp.name)
        self.output_dir = self.temp_dir / "reviewer-output"

    def _app(self, reviewer="reviewer_a", *, limit=None, seed_path=SEED_PATH, output_dir=None):
        app = create_app(
            reviewer=reviewer,
            limit=limit,
            seed_path=seed_path,
            output_dir=output_dir or self.output_dir,
        )
        app.config.update(TESTING=True)
        return app

    def _put(self, client, index, *, labels=None, spans=None, needs_review=False, note=""):
        return client.put(
            f"/api/email/{index}",
            json={
                "labels": [] if labels is None else labels,
                "spans": [] if spans is None else spans,
                "needs_review": needs_review,
                "note": note,
            },
        )

    def _output_files(self):
        return sorted(self.output_dir.rglob("*.jsonl"))

    def _rows_from(self, path):
        return list(read_jsonl(path))

    def _edited_seed(self, *, subject, current_message):
        """Keep the real seed IDs/order while controlling text for offset cases."""
        records = copy.deepcopy(self.seed_records)
        record = records[0]
        record["subject"] = subject
        record["raw_body"] = current_message
        record["current_message"] = current_message
        record["clean_body"] = current_message
        path = self.temp_dir / "controlled-real-seed.jsonl"
        write_jsonl(path, records)
        (self.temp_dir / "manifest.json").write_text(
            json.dumps({"selected_email_ids": self.manifest["selected_email_ids"]}),
            encoding="utf-8",
        )
        return path

    def _utf16_span(self, source, text, label, *, field="current_message", start=None):
        if start is None:
            start = source.rfind(text)
        self.assertGreaterEqual(start, 0, f"{text!r} must occur in {field}")
        end = start + len(text)
        return {
            "field": field,
            "start": python_to_utf16_offset(source, start),
            "end": python_to_utf16_offset(source, end),
            "text": text,
            "label": label,
        }

    def test_real_seed_order_limit_and_resume(self):
        """The app opens the manifest's real 250 records in their published order."""
        client = self._app(limit=4).test_client()
        state = client.get("/api/state").get_json()

        self.assertEqual(state["reviewer"], "reviewer_a")
        self.assertEqual(state["total"], 4)
        self.assertEqual(state["limit"], 4)
        self.assertEqual(state["first_unfinished"], 0)
        self.assertEqual([row["email_id"] for row in self.seed_records], self.manifest["selected_email_ids"])
        self.assertEqual(len(self.seed_records), 250)

        for index in range(3):
            task = client.get(f"/api/email/{index}").get_json()
            self.assertEqual(task["index"], index)
            self.assertEqual(task["email_id"], self.manifest["selected_email_ids"][index])
            self.assertEqual(task["source"]["current_message"], self.seed_records[index]["current_message"])
        self.assertGreaterEqual(client.get("/api/email/4").status_code, 400)

        # Saving a later item first must not move the resume point past the first gap.
        self.assertEqual(self._put(client, 1, labels=["MEETING"]).status_code, 200)
        state = client.get("/api/state").get_json()
        self.assertEqual(state["completed"], 1)
        self.assertEqual(state["first_unfinished"], 0)
        self.assertEqual(self._put(client, 0, labels=["DEADLINE"]).status_code, 200)

        resumed = self._app(limit=4).test_client().get("/api/state").get_json()
        self.assertEqual(resumed["completed"], 2)
        self.assertEqual(resumed["first_unfinished"], 2)

    def test_empty_draft_stays_unlabelled_and_does_not_count_as_reviewed(self):
        client = self._app(limit=2).test_client()
        response = self._put(client, 0)
        self.assertEqual(response.status_code, 200, response.get_json())

        state = client.get("/api/state").get_json()
        self.assertEqual(state["completed"], 0)
        self.assertEqual(state["first_unfinished"], 0)
        rows = self._rows_from(self._output_files()[0])
        self.assertEqual(len(rows), 250)
        self.assertEqual(rows[0]["labels"], [])
        self.assertEqual(rows[0]["spans"], [])
        self.assertEqual(rows[0]["annotation"]["status"], "unlabelled")
        self.assertEqual(rows[0]["annotation"]["annotator"], "reviewer_a")
        self.assertEqual(rows[0]["annotation"]["annotation_source"], "human")

    def test_partial_span_draft_autosaves_restores_and_stays_out_of_canonical_labels(self):
        body = "Café 😀, send the report by Friday."
        seed_path = self._edited_seed(subject="Weekly report", current_message=body)
        client = self._app(seed_path=seed_path, limit=2).test_client()
        draft_span = self._utf16_span(body, "Friday", "DEADLINE_DATE")

        with patch.object(annotator_store.os, "replace", wraps=os.replace) as replace:
            response = self._put(client, 0, spans=[draft_span])
            self.assertEqual(response.status_code, 200, response.get_json())
            replace.assert_called()

        self.assertEqual(list(self.output_dir.glob("*.tmp")), [])
        self.assertEqual(list(self.output_dir.glob(".*.tmp")), [])
        restored = client.get("/api/email/0").get_json()
        self.assertEqual(restored["spans"], [draft_span])
        self.assertFalse(restored["completed"])
        state = client.get("/api/state").get_json()
        self.assertEqual(state["completed"], 0)
        self.assertEqual(state["first_unfinished"], 0)

        draft_path = self.output_dir / "reviewer_a.drafts.json"
        self.assertTrue(draft_path.exists())
        draft_data = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertIn(self.seed_records[0]["email_id"], draft_data["email_ids"])
        self.assertEqual(draft_data["spans"][0][0]["text"], "Friday")

        # Draft spans are only an editing aid; any canonical export stays unlabelled and span-free.
        canonical_path = self.output_dir / "reviewer_a.jsonl"
        if canonical_path.exists():
            row = self._rows_from(canonical_path)[0]
            self.assertEqual(row["labels"], [])
            self.assertEqual(row["spans"], [])
            self.assertEqual(row["annotation"]["status"], "unlabelled")

        resumed = self._app(seed_path=seed_path, limit=2).test_client()
        self.assertEqual(resumed.get("/api/email/0").get_json()["spans"], [draft_span])
        response = self._put(resumed, 0, labels=["DEADLINE"], spans=[draft_span])
        self.assertEqual(response.status_code, 200, response.get_json())
        if draft_path.exists():
            self.assertNotIn(self.seed_records[0]["email_id"], json.loads(draft_path.read_text(encoding="utf-8")))
        canonical_row = self._rows_from(self.output_dir / "reviewer_a.jsonl")[0]
        self.assertEqual(canonical_row["spans"][0]["text"], "Friday")

    def test_needs_review_exports_unlabelled_record_and_clears_prior_labels_and_spans(self):
        body = self.seed_records[0]["current_message"]
        selected = "lease"
        span = self._utf16_span(body, selected, "PROJECT")
        client = self._app(limit=2).test_client()

        self.assertEqual(self._put(client, 0, labels=["MEETING"], spans=[span]).status_code, 200)
        response = self._put(
            client, 0, labels=["MEETING"], spans=[span],
            needs_review=True, note="The fragment needs more context.",
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        row = self._rows_from(self._output_files()[0])[0]
        self.assertEqual(row["email_id"], self.seed_records[0]["email_id"])
        self.assertEqual(row["labels"], [])
        self.assertEqual(row["spans"], [])
        self.assertEqual(row["annotation"]["status"], "unlabelled")
        self.assertEqual(row["annotation"]["annotation_source"], "human")
        self.assertEqual(row["annotation"]["annotator"], "reviewer_a")
        self.assertTrue(row["annotation"]["needs_review"])
        self.assertEqual(row["annotation"]["ambiguity_note"], "The fragment needs more context.")
        state = client.get("/api/state").get_json()
        self.assertEqual(state["completed"], 1)
        self.assertEqual(state["first_unfinished"], 1)

    def test_reviewers_are_isolated_and_each_save_is_atomic_autosave(self):
        original_bytes = SEED_PATH.read_bytes()
        client_a = self._app("reviewer_a", limit=2).test_client()
        client_b = self._app("reviewer_b", limit=2).test_client()

        # Persist the complete canonical array through a temporary file and atomic replace.
        with patch.object(annotator_store.os, "replace", wraps=os.replace) as replace:
            response = self._put(client_a, 0, labels=["MEETING"])
            self.assertEqual(response.status_code, 200, response.get_json())
            replace.assert_called()
            destinations = [call.args[1] for call in replace.call_args_list]
            self.assertIn(self.output_dir.resolve() / "reviewer_a.jsonl", destinations)

        files_after_a = self._output_files()
        self.assertEqual(list(self.output_dir.glob("*.tmp")), [])
        self.assertEqual(list(self.output_dir.glob(".*.tmp")), [])
        self.assertEqual(len(files_after_a), 1)
        rows_a = self._rows_from(files_after_a[0])
        self.assertEqual(len(rows_a), 250)
        self.assertEqual([row["email_id"] for row in rows_a], self.manifest["selected_email_ids"])
        self.assertEqual(rows_a[0]["annotation"]["annotator"], "reviewer_a")
        self.assertEqual(rows_a[0]["annotation"]["status"], "human_reviewed")
        for index, row in enumerate(rows_a):
            self.assertEqual(validate_record(row), [], row["email_id"])
            for source_field in set(self.seed_records[index]) - {"labels", "spans", "annotation"}:
                self.assertEqual(row[source_field], self.seed_records[index][source_field])

        # A second reviewer starts from the blank seed and writes a separate file.
        self.assertEqual(client_b.get("/api/email/0").get_json()["labels"], [])
        self.assertEqual(self._put(client_b, 0, labels=["DEADLINE"]).status_code, 200)
        files = self._output_files()
        self.assertEqual(len(files), 2)
        outputs = [self._rows_from(path) for path in files]
        reviewer_rows = {rows[0]["annotation"]["annotator"]: rows for rows in outputs}
        self.assertEqual(set(reviewer_rows), {"reviewer_a", "reviewer_b"})
        self.assertEqual(reviewer_rows["reviewer_a"][0]["labels"], ["MEETING"])
        self.assertEqual(reviewer_rows["reviewer_b"][0]["labels"], ["DEADLINE"])

        # All exported rows remain real Enron records, never gold, AI, or synthetic.
        for rows in outputs:
            self.assertEqual(len(rows), 250)
            for row in rows:
                self.assertEqual(validate_record(row), [], row["email_id"])
                self.assertEqual(row["source_dataset"], "enron")
                self.assertNotIn(row["annotation"]["status"], {"gold", "ai_prelabelled"})
                self.assertNotEqual(row["annotation"].get("annotation_source"), "ai")
                self.assertNotEqual(row["annotation"].get("annotation_source"), "synthetic")
        self.assertEqual(SEED_PATH.read_bytes(), original_bytes)

        # Full canonical reviewer exports remain consumable by the existing agreement API.
        report = compare_reviewer_records(
            reviewer_rows["reviewer_a"], reviewer_rows["reviewer_b"],
        )
        self.assertEqual(report["paired_records"], 250)
        self.assertEqual(report["compared_records"], 1)
        self.assertEqual(report["excluded_unresolved_records"], 249)
        self.assertTrue(report["agreement_is_not_gold"])

    def test_utf16_offsets_preserve_unicode_repeated_text_punctuation_fields_and_overlap(self):
        body = "Café 😀, send Café😀; Café."
        subject = "RE: café 😀; café?"
        seed_path = self._edited_seed(subject=subject, current_message=body)
        client = self._app(seed_path=seed_path, limit=2).test_client()

        last_cafe = body.rfind("Café")
        body_spans = [
            self._utf16_span(body, "Café", "PROJECT", start=last_cafe),
            self._utf16_span(body, "😀; Café.", "ACTION_ITEM", start=body.rfind("😀")),
        ]
        last_subject_cafe = subject.rfind("café")
        subject_spans = [
            self._utf16_span(subject, "café?", "DEADLINE_DATE", field="subject", start=last_subject_cafe),
            self._utf16_span(subject, "😀; café", "MEETING_DATE", field="subject", start=subject.rfind("😀")),
        ]
        response = self._put(client, 0, labels=["MEETING"], spans=body_spans + subject_spans)
        self.assertEqual(response.status_code, 200, response.get_json())

        row = self._rows_from(self._output_files()[0])[0]
        spans = row["spans"]
        body_saved = [span for span in spans if span["field"] == "current_message"]
        subject_saved = [span for span in spans if span["field"] == "subject"]
        self.assertEqual(len(body_saved), 2)
        self.assertEqual(len(subject_saved), 2)
        self.assertEqual(body_saved[0]["start"], last_cafe)
        self.assertEqual(body_saved[0]["end"], last_cafe + len("Café"))
        self.assertEqual(body_saved[0]["text"], "Café")
        self.assertEqual(body_saved[1]["text"], "😀; Café.")
        self.assertEqual(subject_saved[0]["text"], "café?")
        self.assertEqual(subject_saved[1]["text"], "😀; café")
        self.assertGreater(body_spans[0]["start"], body_saved[0]["start"])
        self.assertTrue(
            body_saved[0]["start"] < body_saved[1]["end"]
            and body_saved[1]["start"] < body_saved[0]["end"],
            "overlapping spans should retain their independently selected ranges",
        )
        self.assertTrue(
            subject_saved[0]["start"] < subject_saved[1]["end"]
            and subject_saved[1]["start"] < subject_saved[0]["end"],
        )

    def test_validation_rejects_exclusive_label_invalid_field_and_text_mismatch(self):
        body = "Café 😀, send Café😀; Café."
        subject = "RE: café 😀; café?"
        seed_path = self._edited_seed(subject=subject, current_message=body)
        client = self._app(seed_path=seed_path, limit=2).test_client()
        good = self._utf16_span(body, "Café", "PROJECT")
        cross_field = self._utf16_span(body, "send", "ACTION_ITEM")

        invalid_sets = [
            {"labels": ["NON_PROJECT", "MEETING"], "spans": []},
            {"labels": ["NOT_A_LABEL"], "spans": []},
            {"labels": ["MEETING"], "spans": [{**good, "field": "metadata"}]},
            {
                "labels": ["MEETING"],
                # The offsets name "Café" in the message, while the selected field is subject.
                "spans": [{**cross_field, "field": "subject"}],
            },
            {"labels": ["MEETING"], "spans": [{**good, "text": "Wrong text"}]},
        ]
        # UTF-16 offset 1 unit into this emoji is not a legal span boundary.
        emoji_index = body.index("😀")
        invalid_sets.append({
            "labels": ["MEETING"],
            "spans": [{
                "field": "current_message",
                "start": python_to_utf16_offset(body, emoji_index) + 1,
                "end": python_to_utf16_offset(body, emoji_index + 2),
                "text": "😀,",
                "label": "ACTION_ITEM",
            }],
        })
        # Persist a valid draft first, then prove invalid edits leave it intact.
        self.assertEqual(self._put(client, 0).status_code, 200)
        output_path = self._output_files()[0]
        before_rejections = output_path.read_bytes()
        for payload in invalid_sets:
            response = client.put("/api/email/0", json={**payload, "needs_review": False, "note": ""})
            self.assertGreaterEqual(response.status_code, 400, response.get_json())

        state = client.get("/api/state").get_json()
        self.assertEqual(state["completed"], 0)
        self.assertEqual(state["first_unfinished"], 0)
        self.assertEqual(output_path.read_bytes(), before_rejections)
        rows = self._rows_from(output_path)
        self.assertEqual(rows[0]["labels"], [])
        self.assertEqual(rows[0]["spans"], [])
        self.assertEqual(rows[0]["annotation"]["status"], "unlabelled")

    def test_edit_replaces_previous_classification_and_span_values(self):
        body = "Please send the report by Friday."
        span_friday = self._utf16_span(body, "Friday", "DEADLINE_DATE")
        span_report = self._utf16_span(body, "report", "REQUESTED_DOCUMENT")
        seed_path = self._edited_seed(subject="Weekly report", current_message=body)
        client = self._app(seed_path=seed_path, limit=2).test_client()

        self.assertEqual(self._put(client, 0, labels=["DEADLINE"], spans=[span_friday]).status_code, 200)
        self.assertEqual(self._put(client, 0, labels=["REPORT_REQUEST"], spans=[span_report]).status_code, 200)

        row = self._rows_from(self._output_files()[0])[0]
        self.assertEqual(row["labels"], ["REPORT_REQUEST"])
        self.assertEqual(len(row["spans"]), 1)
        self.assertEqual(row["spans"][0]["text"], "report")
        self.assertEqual(row["annotation"]["status"], "human_reviewed")
        self.assertEqual(client.get("/api/state").get_json()["completed"], 1)


if __name__ == "__main__":
    unittest.main()

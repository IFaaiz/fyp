"""Synthetic contract tests; no network, human annotations or TEST access."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.project_mail.pipeline import acquire, allowed_public_url, digest, group_templates, join_threads, normalize, parse_archive, screen, select

SPEC = {"name": "apache_test", "project_or_list": "dev@subversion.apache.org", "format": "mbox",
        "url": "https://lists.apache.org/api/mbox.lua?list=dev&domain=subversion.apache.org&d=2024-01",
        "terms_reviewed": True, "terms_url": "https://www.apache.org/foundation/public-archives.html", "terms_note": "Synthetic test only"}

def record(body, identity="one", refs=""):
    raw = (f"From: author@example.test\nTo: dev@example.test\nDate: Mon, 1 Jan 2024 09:00:00 +0000\nMessage-ID: <{identity}@example.test>\nReferences: {refs}\nSubject: Project coordination\n\n{body}\n").encode()
    return normalize(raw, SPEC, SPEC["url"], "2026-10-10T00:00:00Z")

class CandidateTests(unittest.TestCase):
    def test_current_message_cues_do_not_label_or_use_history(self):
        r = record("Thanks.\n\nOn Monday someone wrote:\n> Please approve by Friday.")
        self.assertEqual(screen(r)["weak_cue_categories"], [])
        self.assertEqual(r["labels"], [])
        self.assertEqual(r["annotation_tier"], "UNSET")
        self.assertIn("approve", r["quoted_history"])

    def test_quote_only_is_noise(self):
        self.assertIn("no_current_authored_text", screen(record("> Please approve."))["noise_reasons"])

    def test_hard_negative_kept_without_label(self):
        r = record("The report is attached. Please review it.")
        self.assertIn("document_delivery_or_mention", screen(r)["hard_negative_cues"])
        self.assertIn("review_without_approval_cue", screen(r)["hard_negative_cues"])
        self.assertEqual(r["labels"], [])

    def test_explicit_thread_links_and_template_groups(self):
        rows = [record("Please test the project.", "one"), record("Testing complete.", "two", "<one@example.test>"), record("Different work.", "three")]
        join_threads(rows)
        group_templates(rows)
        self.assertEqual(rows[0]["thread_id"], rows[1]["thread_id"])
        self.assertEqual(rows[0]["leakage_group"], rows[1]["leakage_group"])
        self.assertNotEqual(rows[0]["thread_id"], rows[2]["thread_id"])
        self.assertTrue(all(r["split"] == "UNASSIGNED" for r in rows))

    def test_template_group_across_threads(self):
        body = "Please review the comprehensive project proposal addressing deadlines milestones work assignments ownership release requirements documentation testing implementation and deployment."
        rows = [record(body + " version 123", "one"), record(body + " version 987", "two")]
        join_threads(rows)
        group_templates(rows)
        self.assertNotEqual(rows[0]["thread_id"], rows[1]["thread_id"])
        self.assertEqual(rows[0]["leakage_group"], rows[1]["leakage_group"])

    def test_bot_filter_does_not_discard_human_list_mail(self):
        human = record("Please review the release.")
        self.assertFalse(screen(human)["noise_reasons"])
        bot = copy.deepcopy(human)
        bot["sender"] = "jira@example.test"
        self.assertIn("automation_or_housekeeping", screen(bot)["noise_reasons"])

    def test_seeded_naturalistic_and_enriched_sampling(self):
        rows = [record(f"Please review project task number {i} with {'deadline' if i%2 else 'meeting'}.", str(i)) for i in range(20)]
        join_threads(rows)
        group_templates(rows)
        a, summary = select(copy.deepcopy(rows), limit=12)
        b, _ = select(copy.deepcopy(rows), limit=12)
        self.assertEqual([r["source_id"] for r in a], [r["source_id"] for r in b])
        self.assertEqual(summary["sampling_tracks"]["NATURALISTIC"], 3)
        self.assertEqual(summary["gold_generated"], 0)
        self.assertTrue(all(not r["labels"] for r in a))

    def test_url_rejects_private_routes_and_credentials(self):
        self.assertTrue(allowed_public_url(SPEC["url"]))
        for url in [SPEC["url"].replace("list=dev", "list=private"), "https://auth.w3.org/", "https://localhost/x", "https://user:password@lists.apache.org/api/mbox.lua", "https://lists.w3.org/Archives/Member/x/"]:
            self.assertFalse(allowed_public_url(url))

    def test_purposive_pages_do_not_enter_naturalistic_track(self):
        rows = [record("Please review the project.", "purpose"), record("Thanks for the note.", "natural")]
        rows[0]["acquisition_sampling_frame"] = "PURPOSIVE_HTML"
        join_threads(rows)
        group_templates(rows)
        chosen, summary = select(rows, limit=4)
        self.assertEqual(summary["naturalistic_frame_size"], 1)
        self.assertEqual(next(r for r in chosen if r["source_id"] == rows[0]["source_id"])["sampling_track"], "ENRICHED_CHALLENGE")

    def test_cache_hash_and_terms_fail_closed(self):
        temp_root = Path(__file__).resolve().parents[1] / "data" / "test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            path = Path(tmp)/"test.mbox"
            path.write_bytes(b"From sender Mon Jan 1 00:00:00 2024\nSubject: Test\n\nbody\n")
            receipt = path.with_suffix(".mbox.acquisition.json")
            receipt.write_text(json.dumps({"url": SPEC["url"], "sha256": digest(path.read_bytes()), "retrieved_at": "original-time"}))
            self.assertEqual(acquire(SPEC, path)["retrieved_at"], "original-time")
            path.write_bytes(b"Changed")
            with self.assertRaises(ValueError):
                acquire(SPEC, path)
            with self.assertRaises(ValueError):
                acquire({**SPEC, "terms_reviewed": False}, path)

    def test_mbox_metadata_and_attachment_content_excluded(self):
        raw = b"From: sender@example.test\nTo: recipient@example.test\nMessage-ID: <mime@example.test>\nSubject: Project\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=BOUND\n\n--BOUND\nContent-Type: text/plain\n\nPlease review.\n--BOUND\nContent-Type: text/plain\nContent-Disposition: attachment; filename=secret.txt\n\nSECRET_ATTACHMENT\n--BOUND--\n"
        r = normalize(raw, SPEC, "synthetic", "t0")
        self.assertEqual(r["attachment_names"], ["secret.txt"])
        self.assertNotIn("SECRET_ATTACHMENT", r["current_message"])

    def test_w3c_rendered_body_and_navigation_are_separate(self):
        spec = {**SPEC, "name": "w3c_test", "format": "w3c_html",
                "url": "https://lists.w3.org/Archives/Public/w3c-wai-gl/2026JulSep/0094.html"}
        html = '''<!-- subject="Project agenda" --><!-- email="author&#64;example.test" -->
        <!-- sent="Mon, 1 Jan 2024 09:00:00 +0000" --><!-- id="child@example.test" -->
        <li><span class="to"><span class="heading">To:</span> dev@example.test</span></li>
        <li><a href="0093.html">In reply to: Parent</a></li>
        <!-- body="start" --><pre class="body">Please join the meeting.<br>By Friday.
        <script>HIDDEN_SCRIPT</script><a href="https://example.test">Agenda</a>

On Monday someone wrote:
&gt; approve the report</pre><!-- body="end" -->
        <p>Navigation footer</p>'''
        temp_root = Path(__file__).resolve().parents[1] / "data" / "test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            path = Path(tmp)/"message.html"
            path.write_bytes(html.encode("utf-8"))
            row = parse_archive(path, spec, "t0")[0]
        self.assertIn("Please join the meeting", row["current_message"])
        self.assertNotIn("approve", row["current_message"])
        self.assertNotIn("Navigation footer", row["body_raw"])
        self.assertNotIn("HIDDEN_SCRIPT", row["body_raw"])
        self.assertEqual(row["sender"], "author@example.test")
        self.assertEqual(row["recipients"], ["dev@example.test"])
        self.assertFalse(row["metadata_quality"]["raw_headers_available"])
        self.assertEqual(row["raw_message_sha256"], digest(html.encode()))
        parent = record("Parent meeting.", "parent")
        parent["source_url_or_reference"] = spec["url"].replace("0094", "0093")
        join_threads([parent, row])
        self.assertEqual(parent["thread_id"], row["thread_id"])
        self.assertEqual(row["in_reply_to"], [])
        self.assertEqual(row["references"], [])
        self.assertEqual(row["archive_parent_source_id"], parent["source_id"])

    def test_w3c_missing_body_fails_closed(self):
        spec = {**SPEC, "format": "w3c_html"}
        temp_root = Path(__file__).resolve().parents[1] / "data" / "test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            path = Path(tmp)/"wrong.html"
            path.write_text('<html>Login or index navigation</html>')
            with self.assertRaises(ValueError):
                parse_archive(path, spec, "t0")

    def test_w3c_declared_charset_and_cfc_deadline(self):
        spec = {**SPEC, "format": "w3c_html"}
        html = '<meta charset="WINDOWS-1252" /><!-- subject="Project" --><!-- id="one" --><pre class="body">Call for consensus – ends Monday at noon.</pre>'
        temp_root = Path(__file__).resolve().parents[1] / "data" / "test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            path = Path(tmp)/"message.html"
            path.write_bytes(html.encode("cp1252"))
            row = parse_archive(path, spec, "t0")[0]
        self.assertIn("–", row["current_message"])
        self.assertNotIn("\ufffd", row["current_message"])
        self.assertIn("DEADLINE", screen(row)["weak_cue_categories"])

if __name__ == "__main__":
    unittest.main()

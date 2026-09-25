from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.datasets.candidate_filter import select_candidate_records, write_candidate_pool
from src.datasets.enron import (
    parse_enron_bytes,
    prepare_enron_jsonl,
    scan_enron_index,
)
from src.datasets.schemas import read_jsonl
from src.datasets.validation import validate_record
from src.datasets.threading import (
    apply_secondary_thread_suggestions, assign_thread_metadata,
    suggest_secondary_thread_links,
)


RFC822_MESSAGE = b"""Message-ID: <msg-1@example.test>
Date: Mon, 01 Jan 2024 10:00:00 +0000
From: Alex Doe <alex@example.test>
To: Pat <pat@example.test>, team@example.test
Cc: Morgan <morgan@example.test>
Subject: =?utf-8?Q?Review_=E2=80=93_project_plan?=
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="example-boundary"

--example-boundary
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 8bit

Please review the project plan by Friday.

-----Original Message-----
From: Pat <pat@example.test>
Earlier text
--example-boundary
Content-Type: application/pdf; name="minutes.pdf"
Content-Disposition: attachment; filename="minutes.pdf"
Content-Transfer-Encoding: base64

JVBERi0=
--example-boundary--
"""


def _message(message_id: str, body: str, *, references: str = "", date: str = "") -> bytes:
    headers = [
        f"Message-ID: <{message_id}>",
        "From: sender@example.test",
        "To: receiver@example.test",
        "Subject: Common project subject",
        "Content-Type: text/plain; charset=utf-8",
    ]
    if references:
        headers.append(f"References: {references}")
    if date:
        headers.append(f"Date: {date}")
    return ("\r\n".join(headers) + "\r\n\r\n" + body).encode("utf-8")


class EnronParserTests(unittest.TestCase):
    def test_parses_rfc822_metadata_body_and_attachment_filename(self) -> None:
        parsed = parse_enron_bytes(RFC822_MESSAGE, source_path="mailbox/inbox/1.")

        self.assertEqual(parsed.message_id, "msg-1@example.test")
        self.assertEqual(parsed.subject, "Review – project plan")
        self.assertEqual(parsed.sender, "alex@example.test")
        self.assertEqual(parsed.recipients, ("pat@example.test", "team@example.test"))
        self.assertEqual(parsed.cc, ("morgan@example.test",))
        self.assertIn("Please review the project plan by Friday.", parsed.raw_body)
        self.assertEqual(parsed.attachment_names, ("minutes.pdf",))

    def test_uses_enron_custom_address_headers_as_fallback(self) -> None:
        raw = b"""Message-ID: <custom@example.test>
X-From: Phillip K Allen
X-To: tim.belden@enron.com
X-cc: legal@example.com
Subject: Forecast
Content-Type: text/plain; charset=us-ascii

Here is our forecast.
"""
        parsed = parse_enron_bytes(raw)

        self.assertEqual(parsed.sender, "Phillip K Allen")
        self.assertEqual(parsed.recipients, ("tim.belden@enron.com",))
        self.assertEqual(parsed.cc, ("legal@example.com",))

    def test_deduplicates_copied_message_and_keeps_source_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maildir"
            (root / "mailbox-a").mkdir(parents=True)
            (root / "mailbox-b").mkdir(parents=True)
            content = _message("copy@example.test", "Same original message")
            first = root / "mailbox-a" / "1."
            second = root / "mailbox-b" / "1."
            first.write_bytes(content)
            second.write_bytes(content)

            entries, stats = scan_enron_index(root)

            self.assertEqual(len(entries), 1)
            self.assertEqual(stats["source_files"], 2)
            self.assertEqual(stats["duplicate_messages_removed"], 1)
            self.assertEqual(stats["source_file_bytes"], 2 * len(content))
            self.assertEqual(stats["parser_defects"], 0)
            self.assertEqual(first.read_bytes(), content)
            self.assertEqual(second.read_bytes(), content)

    def test_prepares_canonical_unlabelled_records_with_thread_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maildir"
            mailbox = root / "mailbox"
            mailbox.mkdir(parents=True)
            (mailbox / "1.").write_bytes(_message(
                "root@example.test", "Please review the plan.",
                date="Mon, 01 Jan 2024 10:00:00 +0000",
            ))
            (mailbox / "2.").write_bytes(_message(
                "reply@example.test", "I will send it Friday.",
                references="<root@example.test>",
                date="Mon, 01 Jan 2024 11:00:00 +0000",
            ))
            output = Path(temp_dir) / "records.jsonl"

            stats = prepare_enron_jsonl(root, output)
            records = list(read_jsonl(output))

            self.assertEqual(stats["messages_written"], 2)
            self.assertEqual(stats["threads"], 1)
            self.assertEqual([record["turn_index"] for record in records], [0, 1])
            self.assertEqual(records[0]["thread_id"], records[1]["thread_id"])
            self.assertIn("Please review the plan.", records[1]["thread_context"])
            for record in records:
                self.assertEqual(record["labels"], [])
                self.assertEqual(record["annotation"]["status"], "unlabelled")
                self.assertEqual(validate_record(record), [])


class EnronThreadTests(unittest.TestCase):
    def test_links_explicit_references_and_does_not_join_by_subject_only(self) -> None:
        rows = [
            {"email_id": "e1", "message_id": "root@example.test", "references": [], "in_reply_to": [], "sent_at": "2024-01-01T10:00:00+00:00", "source_path": "a"},
            {"email_id": "e2", "message_id": "reply@example.test", "references": ["root@example.test"], "in_reply_to": [], "sent_at": "2024-01-01T11:00:00+00:00", "source_path": "b"},
            {"email_id": "e3", "message_id": "other@example.test", "references": [], "in_reply_to": [], "sent_at": "2024-01-01T12:00:00+00:00", "source_path": "c"},
        ]

        assigned = assign_thread_metadata(rows)

        self.assertEqual(assigned["e1"][0], assigned["e2"][0])
        self.assertEqual(assigned["e1"][1], 0)
        self.assertEqual(assigned["e2"][1], 1)
        self.assertNotEqual(assigned["e1"][0], assigned["e3"][0])




class EnronHeuristicThreadSuggestionTests(unittest.TestCase):
    @staticmethod
    def message(email_id: str, subject: str, sent_at: str, sender: str,
                recipients: list[str], thread_id: str | None = None) -> dict:
        return {
            "email_id": email_id, "thread_id": thread_id or f"singleton-{email_id}",
            "subject": subject, "sent_at": sent_at, "sender": sender,
            "recipients": recipients, "cc": [],
        }

    def test_suggests_only_reciprocal_one_to_one_reply_pair(self) -> None:
        rows = [
            self.message("root", "Quarterly project review schedule",
                         "2024-01-01T10:00:00Z", "alice@example.test", ["bob@example.test"]),
            self.message("reply", "Re: Quarterly project review schedule",
                         "2024-01-02T10:00:00Z", "bob@example.test", ["alice@example.test"]),
        ]
        suggestions = suggest_secondary_thread_links(rows)
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion["email_ids"], ["reply", "root"])
        self.assertEqual(suggestion["thread_link_method"],
                         "heuristic_subject_reciprocal_participants_time")
        self.assertEqual(suggestion["confidence"], "high_rule_match_uncalibrated")
        self.assertNotIn("thread_id", suggestion)

    def test_derived_pair_preserves_source_ids_and_adds_prior_message_context(self) -> None:
        rows = [
            self.message("root", "Quarterly project review schedule",
                         "2024-01-01T10:00:00Z", "alice@example.test", ["bob@example.test"]),
            self.message("reply", "Re: Quarterly project review schedule",
                         "2024-01-02T10:00:00Z", "bob@example.test", ["alice@example.test"]),
        ]
        rows[0]["current_message"] = "Please review the project schedule."
        rows[1]["current_message"] = "I will send the revised schedule Friday."
        derived = apply_secondary_thread_suggestions(rows, suggest_secondary_thread_links(rows))
        earlier, later = derived
        self.assertEqual(earlier["source_thread_id"], "singleton-root")
        self.assertEqual(later["source_thread_id"], "singleton-reply")
        self.assertEqual(earlier["thread_id"], later["thread_id"])
        self.assertEqual(later["thread_link_method"], "heuristic")
        self.assertEqual(later["thread_link_confidence"], "high_unverified")
        self.assertIn("Please review the project schedule.", later["thread_context"])
        self.assertEqual(rows[0]["thread_id"], "singleton-root")
        self.assertEqual(rows[1]["thread_id"], "singleton-reply")

    def test_rejects_same_sender_self_recipient_pair(self) -> None:
        rows = [
            self.message("first", "Quarterly project review schedule",
                         "2024-01-01T10:00:00Z", "alice@example.test", ["alice@example.test"]),
            self.message("reply", "Re: Quarterly project review schedule",
                         "2024-01-01T11:00:00Z", "alice@example.test", ["alice@example.test"]),
        ]
        self.assertEqual(suggest_secondary_thread_links(rows), [])

    def test_skips_oversized_subject_buckets_and_reports_coverage(self) -> None:
        rows = [
            self.message("root", "Quarterly project review schedule",
                         "2024-01-01T10:00:00Z", "alice@example.test",
                         ["bob@example.test", "carol@example.test"]),
            self.message("bob", "Re: Quarterly project review schedule",
                         "2024-01-01T11:00:00Z", "bob@example.test",
                         ["alice@example.test"]),
            self.message("carol", "Re: Quarterly project review schedule",
                         "2024-01-01T12:00:00Z", "carol@example.test",
                         ["alice@example.test"]),
        ]
        diagnostics = {}

        suggestions = suggest_secondary_thread_links(
            rows, max_subject_bucket_size=2, diagnostics=diagnostics,
        )

        self.assertEqual(suggestions, [])
        self.assertEqual(diagnostics["oversized_subject_buckets_skipped"], 1)
        self.assertEqual(diagnostics["oversized_subject_records_skipped"], 3)
        self.assertEqual(diagnostics["one_to_one_suggested_pairs"], 0)

    def test_rejects_asymmetric_old_short_grouped_and_ambiguous_pairs(self) -> None:
        def mail(eid, subject, date, sender, recipients, thread=None):
            return self.message(eid, subject, date, sender, recipients, thread_id=thread)
        rows = [
            mail("a", "Quarterly project review schedule", "2024-01-01T10:00:00Z",
                 "alice@example.test", ["bob@example.test"]),
            mail("asym", "Re: Quarterly project review schedule", "2024-01-02T10:00:00Z",
                 "bob@example.test", ["carol@example.test"]),
            mail("old", "Re: Quarterly project review schedule", "2024-01-20T10:00:00Z",
                 "bob@example.test", ["alice@example.test"]),
            mail("short", "Re: project review", "2024-01-02T10:00:00Z",
                 "bob@example.test", ["alice@example.test"]),
            mail("group-a", "Re: Quarterly project review schedule", "2024-01-02T10:00:00Z",
                 "bob@example.test", ["alice@example.test"], "already-linked"),
            mail("group-b", "Other message", "2024-01-02T11:00:00Z",
                 "carol@example.test", ["alice@example.test"], "already-linked"),
            mail("amb-root", "Project review schedule for this quarter", "2024-02-01T10:00:00Z",
                 "alice@example.test", ["bob@example.test", "carol@example.test"]),
            mail("amb-bob", "Re: Project review schedule for this quarter", "2024-02-01T11:00:00Z",
                 "bob@example.test", ["alice@example.test"]),
            mail("amb-carol", "Re: Project review schedule for this quarter", "2024-02-01T12:00:00Z",
                 "carol@example.test", ["alice@example.test"]),
        ]
        self.assertEqual(suggest_secondary_thread_links(rows), [])

class EnronCandidateTests(unittest.TestCase):
    def test_keyword_candidates_and_random_sample_remain_unlabelled(self) -> None:
        rows = [
            {"email_id": "meeting", "subject": "Review meeting", "current_message": "Please send the agenda.", "thread_context": "", "labels": [], "annotation": {"status": "unlabelled"}},
            {"email_id": "plain-a", "subject": "Lunch", "current_message": "Are you free today?", "thread_context": "", "labels": [], "annotation": {"status": "unlabelled"}},
            {"email_id": "plain-b", "subject": "Travel", "current_message": "The train leaves at noon.", "thread_context": "", "labels": [], "annotation": {"status": "unlabelled"}},
        ]

        first, stats = select_candidate_records(rows, random_sample_count=1, seed=7)
        second, _ = select_candidate_records(rows, random_sample_count=1, seed=7)

        self.assertEqual([row["email_id"] for row in first], [row["email_id"] for row in second])
        self.assertEqual(stats["keyword_candidates"], 1)
        self.assertEqual(stats["random_sample_selected"], 1)
        self.assertEqual(first[0]["email_id"], "meeting")
        self.assertTrue(all(row["labels"] == [] for row in first))
        self.assertTrue(all(row["annotation"]["status"] == "unlabelled" for row in first))

    def test_streamed_pool_emits_stats_without_changing_annotations(self) -> None:
        rows = [
            {"email_id": "a", "subject": "deadline Friday", "current_message": "", "thread_context": "", "labels": [], "annotation": {"status": "unlabelled"}},
            {"email_id": "b", "subject": "hello", "current_message": "How are you?", "thread_context": "", "labels": [], "annotation": {"status": "unlabelled"}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.jsonl"
            output = Path(temp_dir) / "pool.jsonl"
            source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            stats = write_candidate_pool(source, output, random_sample_count=1, seed=3)
            selected = list(read_jsonl(output))

        self.assertEqual(stats["input_records"], 2)
        self.assertEqual(stats["records_selected"], 2)
        self.assertEqual({row["email_id"] for row in selected}, {"a", "b"})
        self.assertTrue(all(row["labels"] == [] for row in selected))
        self.assertTrue(all(row["annotation"]["status"] == "unlabelled" for row in selected))


if __name__ == "__main__":
    unittest.main()

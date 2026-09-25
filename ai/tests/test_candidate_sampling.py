from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.datasets.candidate_filter import select_candidate_records, write_candidate_pool


def row(email_id: str, thread_id: str, turn: int, body: str, *,
        context: str = "", sender: str = "") -> dict:
    return {
        "email_id": email_id, "source_dataset": "enron",
        "thread_id": thread_id, "turn_index": turn, "subject": "",
        "raw_body": body, "current_message": body, "clean_body": body,
        "thread_context": context, "sender": sender, "recipients": [],
        "cc": [], "sent_at": None, "attachment_names": [],
        "labels": [], "spans": [],
        "annotation": {"status": "unlabelled", "annotator": None,
                       "annotation_source": None, "confidence": None},
    }


class CandidateSamplingTests(unittest.TestCase):
    def test_hard_cap_expansion_and_metadata_keep_partial_thread_explicit(self) -> None:
        records = [
            row("a0", "thread-a", 0, "We need a project meeting.", sender="a@enron.com"),
            row("a1", "thread-a", 1, "I can bring the slides.", sender="b@enron.com"),
            row("a2", "thread-a", 2, "Thanks, see you there.", sender="c@enron.com"),
            row("b0", "thread-b", 0, "Lunch next week?", sender="d@enron.com"),
            row("b1", "thread-b", 1, "Tuesday works.", sender="e@enron.com"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.jsonl"
            output = Path(temp) / "pool.jsonl"
            source.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
            stats = write_candidate_pool(
                source, output, target_count=8, random_sample_count=1,
                seed=19, thread_mode="fit",
            )
            selected = [json.loads(x) for x in output.read_text(encoding="utf-8").splitlines()]
            sidecar_path = output.with_name(output.stem + ".metadata.jsonl")
            sidecar = [json.loads(x) for x in sidecar_path.read_text(encoding="utf-8").splitlines()]

        self.assertLessEqual(len(selected), 8)
        self.assertTrue(any(x["email_id"] == "a0" for x in selected))
        self.assertEqual(stats["target_exceeded"], 0)
        self.assertEqual(stats["random_sample_selected"], 1)
        self.assertTrue(any(x["selection_reason"] == "thread_expansion" for x in sidecar))
        self.assertTrue(any(x["thread_complete"] is False for x in sidecar))
        self.assertTrue(all(x["labels"] == [] for x in selected))
        self.assertTrue(all(x["annotation"]["status"] == "unlabelled" for x in selected))

    def test_context_only_strata_fill_slots_without_unsolicited_random_negatives(self) -> None:
        records = [
            row(f"c{i}", f"thread-{i}", 0, "A short reply.", context="Please review the agenda.")
            for i in range(5)
        ]
        selected, stats = select_candidate_records(
            records, target_count=5, random_sample_count=0, seed=8,
        )

        self.assertEqual(len(selected), 5)
        self.assertEqual(stats["selected_context_only_matches"], 5)
        self.assertEqual(stats["selected_random_nonmatching"], 0)
        self.assertTrue(all(x["labels"] == [] for x in selected))
    def test_whole_thread_mode_reports_soft_target_overage(self) -> None:
        records = [
            row("a0", "thread-a", 0, "Please review the agenda for our meeting."),
            row("a1", "thread-a", 1, "I will send my notes."),
            row("a2", "thread-a", 2, "Thanks."),
            row("b0", "thread-b", 0, "Lunch?"),
        ]
        selected, stats = select_candidate_records(
            records, target_count=2, random_sample_count=0, seed=4,
            thread_mode="whole",
        )

        self.assertEqual({x["thread_id"] for x in selected}, {"thread-a"})
        self.assertEqual(len(selected), 3)
        self.assertEqual(stats["target_exceeded"], 1)
        self.assertEqual(stats["full_threads_selected"], 1)
        self.assertEqual(stats["partial_threads_selected"], 0)

    def test_due_false_positives_and_actionable_dates(self) -> None:
        from src.datasets.candidate_filter import candidate_reasons

        not_due = row("not-due", "t1", 0, "The payment is due to a change in the market.")
        actual_due = row("due", "t2", 0, "The project is due Friday.")
        self.assertNotIn("due", candidate_reasons(not_due))
        self.assertIn("due", candidate_reasons(actual_due))

    def test_empty_forwarded_and_bulk_messages_are_conservative(self) -> None:
        from src.datasets.candidate_filter import candidate_reasons

        empty_report = row("empty-report", "t1", 0, "")
        empty_report["subject"] = "Daily report"
        empty_meeting = row("empty-meeting", "t2", 0, "")
        empty_meeting["subject"] = "Planning meeting Friday"
        forwarded = row("forwarded", "t3", 0,
                        "FYI\n-----Original Message-----\nPlease review the action items by Friday.")
        bulk_report = row("bulk-report", "t4", 0,
                          "The weekly earnings report is ready. Please do not reply.")
        self.assertEqual(candidate_reasons(empty_report), [])
        self.assertIn("meeting", candidate_reasons(empty_meeting))
        self.assertEqual(candidate_reasons(forwarded), [])
        self.assertEqual(candidate_reasons(bulk_report), [])

    def test_empty_body_subject_can_keep_explicit_request_language(self) -> None:
        from src.datasets.candidate_filter import candidate_reasons

        record = row("subject-action", "t1", 0, "")
        record["subject"] = "Please review the attached plan"
        self.assertEqual(candidate_reasons(record), ["review", "attached"])

    def test_quote_trim_and_precision_guard_losses_are_reported_as_recall_risk(self) -> None:
        quoted_only = row(
            "quoted-only", "t-quoted", 0,
            "-----Original Message-----\nPlease review the project schedule by Friday.",
        )
        routine_report = row(
            "routine-report", "t-report", 0,
            "The daily report and attachment are ready.",
        )

        _, stats = select_candidate_records(
            [quoted_only, routine_report], target_count=2, random_sample_count=2,
        )

        risk = stats["cue_recall_risk"]
        self.assertEqual(risk["nonempty_current_message_empty_authored_prefix"], 1)
        self.assertEqual(risk["records_losing_any_cue_at_quote_trim"], 1)
        self.assertIn("review", risk["cue_instances_lost_at_quote_trim"])
        self.assertEqual(risk["records_losing_any_cue_at_precision_guard"], 1)
        self.assertIn("report", risk["cue_instances_suppressed_by_precision_guard"])
        self.assertIn("not known false negatives", risk["interpretation"])

    def test_category_stratification_balances_eight_cued_categories(self) -> None:
        bodies = {
            "meeting": "Please schedule a planning meeting.",
            "deadline": "The project deadline is Friday.",
            "report_doc": "Please review the report.",
            "department_input": "Please provide the department input.",
            "follow_up": "Please follow up with the customer.",
            "approval": "Please approve the draft.",
            "update": "Please update the delivery plan.",
            "action_task": "Please complete this task.",
        }
        records = [
            row(f"{category}-{index}", f"t-{category}-{index}", 0, body)
            for category, body in bodies.items()
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.jsonl"
            output = Path(temp) / "pool.jsonl"
            source.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
            stats = write_candidate_pool(
                source, output, target_count=40, random_sample_count=0, seed=21,
            )
            sidecar = [
                json.loads(line)
                for line in output.with_name("pool.metadata.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        counts = {}
        for item in sidecar:
            category = item["primary_sampling_category"]
            counts[category] = counts.get(category, 0) + 1
        self.assertEqual(len(sidecar), 40)
        self.assertEqual(set(counts), set(bodies))
        self.assertEqual(set(counts.values()), {5}, counts)
        self.assertEqual(stats["sampling_category_counts"]["random"]["selected"], 0)


    def test_opt_in_pool_writes_derived_groups_and_keeps_source_ids(self) -> None:
        first = row("root", "canonical-root", 0, "Please review the project schedule.",
                    sender="alice@example.test")
        first.update({
            "subject": "Quarterly project review schedule",
            "sent_at": "2024-01-01T10:00:00Z",
            "recipients": ["bob@example.test"],
        })
        reply = row("reply", "canonical-reply", 0, "I will send the revised schedule Friday.",
                    sender="bob@example.test")
        reply.update({
            "subject": "Re: Quarterly project review schedule",
            "sent_at": "2024-01-02T10:00:00Z",
            "recipients": ["alice@example.test"],
        })
        records = [first, reply]

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "canonical.jsonl"
            output = Path(temp) / "derived.jsonl"
            source.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
            stats = write_candidate_pool(
                source, output, random_sample_count=0, target_count=2, seed=17,
                use_secondary_thread_links=True,
            )
            derived = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            original = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(stats["secondary_thread_linking"]["suggested_pairs"], 1)
        derived_ids = {item["thread_id"] for item in derived}
        self.assertEqual(len(derived_ids), 1)
        self.assertTrue(next(iter(derived_ids)).startswith("enron-heuristic-thread-"))
        self.assertEqual({item["source_thread_id"] for item in derived},
                         {"canonical-root", "canonical-reply"})
        self.assertEqual(original[0]["thread_id"], "canonical-root")
        self.assertEqual(original[1]["thread_id"], "canonical-reply")
        self.assertTrue(any(item["thread_context"] for item in derived))
        self.assertTrue(all(item["thread_link_method"] == "heuristic" for item in derived))
        self.assertTrue(all(item["thread_link_confidence"] == "high_unverified" for item in derived))

    def test_direct_and_context_cues_are_recorded_without_changing_labels(self) -> None:
        record = row(
            "cue", "thread-c", 0, "Review the meeting agenda.",
            context="The report deadline is Friday.",
        )
        selected, _ = select_candidate_records(
            [record], target_count=5, random_sample_count=0,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["labels"], [])
        self.assertEqual(selected[0]["annotation"]["status"], "unlabelled")
        from src.datasets.candidate_filter import candidate_reasons
        self.assertEqual(candidate_reasons(record), ["meeting", "agenda", "deadline", "report", "review"])


if __name__ == "__main__":
    unittest.main()

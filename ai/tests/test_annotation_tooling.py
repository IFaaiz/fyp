import copy
import json
import unittest
from pathlib import Path

from src.annotation.adjudication import apply_adjudication_decisions
from src.annotation.agreement import compare_reviewer_records
from src.annotation.label_studio import (
    assert_no_gold_threads,
    canonical_to_task,
    python_to_utf16_offset,
    select_enron_seed_records,
    task_to_canonical,
    utf16_to_python_offset,
)
from src.annotation.label_studio_config import make_label_studio_config
from src.datasets.schemas import empty_record


class LabelStudioTests(unittest.TestCase):
    def setUp(self):
        self.record = empty_record(
            email_id="enron-e1", source_dataset="enron", thread_id="t1",
            subject="Kickoff 😀 Friday", raw_body="😀 Please submit the report by Friday at 5 PM.",
        )
        self.record.update({
            "sender": "sender@example.com", "recipients": ["reviewer@example.com"],
            "thread_context": "Earlier message: the project review is planned.",
            "sent_at": "2001-01-01T10:00:00Z", "attachment_names": ["plan.docx"],
        })

    def _result(self, field, label, text, control):
        source = self.record[field]
        start = source.index(text)
        end = start + len(text)
        return {
            "from_name": control,
            "to_name": "subject" if field == "subject" else "current_message",
            "type": "labels",
            "value": {"start": python_to_utf16_offset(source, start),
                      "end": python_to_utf16_offset(source, end), "text": text,
                      "labels": [label]},
        }

    def _annotated_task(self, labels, spans=(), decision="Reviewed"):
        task = canonical_to_task(self.record, task_id=1, assignment="A")
        result = [
            {"from_name": "review_decision", "type": "choices", "value": {"choices": [decision]}},
        ]
        if labels:
            result.append({"from_name": "classification", "type": "choices", "value": {"choices": labels}})
        result.extend(spans)
        task["annotations"] = [{"id": 23, "was_cancelled": False, "result": result}]
        return task

    def test_offsets_convert_between_python_and_utf16(self):
        text = "A😀BC"
        self.assertEqual(python_to_utf16_offset(text, 2), 3)
        self.assertEqual(utf16_to_python_offset(text, 3), 2)
        with self.assertRaises(ValueError):
            utf16_to_python_offset(text, 2)

    def test_blank_task_round_trips_full_canonical_record(self):
        task = canonical_to_task(self.record, task_id=1, assignment="A")
        self.assertEqual(task["annotations"], [])
        self.assertEqual(task["predictions"], [])
        self.assertIn("From: sender@example.com", task["data"]["metadata_display"])
        self.assertEqual(task_to_canonical(task, annotator="reviewer-a", allow_unannotated=True), self.record)

    def test_imports_multilabel_and_subject_and_body_spans(self):
        spans = [
            self._result("current_message", "DEADLINE_DATE", "Friday", "message_spans"),
            self._result("current_message", "DEADLINE_TIME", "5 PM", "message_spans"),
            self._result("subject", "MEETING_DATE", "Friday", "subject_spans"),
        ]
        imported = task_to_canonical(
            self._annotated_task(["DEADLINE", "REPORT_REQUEST"], spans), annotator="reviewer-a",
        )
        self.assertEqual(imported["labels"], ["DEADLINE", "REPORT_REQUEST"])
        self.assertEqual(imported["annotation"]["status"], "human_reviewed")
        self.assertEqual(imported["annotation"]["annotation_source"], "human")
        self.assertEqual(imported["spans"][0]["text"], "Friday")
        self.assertEqual(imported["spans"][0]["start"], self.record["current_message"].index("Friday"))
        self.assertEqual(imported["spans"][2]["field"], "subject")
        self.assertNotEqual(imported["annotation"]["status"], "gold")

    def test_non_project_exclusivity_is_rejected(self):
        task = self._annotated_task(["NON_PROJECT", "MEETING"])
        with self.assertRaisesRegex(ValueError, "NON_PROJECT cannot co-occur"):
            task_to_canonical(task, annotator="reviewer-a")

    def test_needs_review_stays_unlabelled(self):
        task = self._annotated_task([], decision="Needs review")
        task["annotations"][0]["result"].append({
            "from_name": "review_note", "type": "textarea", "value": {"text": ["Fragment lacks context"]},
        })
        imported = task_to_canonical(task, annotator="reviewer-a")
        self.assertEqual(imported["labels"], [])
        self.assertEqual(imported["annotation"]["status"], "unlabelled")
        self.assertTrue(imported["annotation"]["needs_review"])

    def test_invalid_utf16_span_boundary_is_rejected(self):
        task = self._annotated_task(["MEETING"])
        task["annotations"][0]["result"].append({
            "from_name": "message_spans", "type": "labels",
            "value": {"start": 1, "end": 2, "text": "😀", "labels": ["ACTION_ITEM"]},
        })
        with self.assertRaisesRegex(ValueError, "splits a surrogate pair"):
            task_to_canonical(task, annotator="reviewer-a")

    def test_gold_threads_are_excluded_source_qualified(self):
        gold = copy.deepcopy(self.record)
        gold["email_id"] = "enron-gold"
        gold["annotation"] = {"status": "gold", "annotator": "reviewer", "annotation_source": "human", "confidence": None}
        safe_other_source = copy.deepcopy(self.record)
        safe_other_source["source_dataset"] = "mailex"
        assert_no_gold_threads([safe_other_source], [gold])
        with self.assertRaisesRegex(ValueError, "gold threads"):
            assert_no_gold_threads([self.record], [gold])

    def test_gold_exclusion_matches_original_and_derived_thread_ids(self):
        gold = copy.deepcopy(self.record)
        gold["email_id"] = "enron-gold-derived"
        gold["thread_id"] = "derived-gold-thread"
        gold["source_thread_id"] = "source-gold-thread"
        gold["annotation"] = {"status": "gold", "annotator": "reviewer",
                              "annotation_source": "human", "confidence": None}

        derived_candidate = copy.deepcopy(self.record)
        derived_candidate["thread_id"] = "derived-candidate-thread"
        derived_candidate["source_thread_id"] = "source-gold-thread"
        with self.assertRaisesRegex(ValueError, "gold threads"):
            assert_no_gold_threads([derived_candidate], [gold])

        original_candidate = copy.deepcopy(self.record)
        original_candidate["thread_id"] = "source-gold-thread"
        self.assertNotIn("source_thread_id", original_candidate)
        with self.assertRaisesRegex(ValueError, "gold threads"):
            assert_no_gold_threads([original_candidate], [gold])

    def test_seed_selector_excludes_every_record_in_a_gold_thread(self):
        candidates = []
        for index in range(205):
            row = empty_record(email_id=f"enron-{index}", source_dataset="enron",
                               thread_id=f"t{index}", raw_body="Message")
            candidates.append(row)
        gold = copy.deepcopy(candidates[0])
        gold["annotation"] = {"status": "gold", "annotator": "reviewer",
                              "annotation_source": "human", "confidence": None}
        sibling = copy.deepcopy(candidates[1])
        sibling["thread_id"] = gold["thread_id"]
        candidates[1] = sibling
        sample, excluded, eligible, report = select_enron_seed_records(
            candidates, [gold], count=200, seed=17,
        )
        sampled_ids = {row["email_id"] for row in sample}
        self.assertEqual(eligible, 203)
        self.assertEqual(excluded["gold_thread"], 2)
        self.assertNotIn(candidates[0]["email_id"], sampled_ids)
        self.assertNotIn(candidates[1]["email_id"], sampled_ids)
        self.assertEqual(len(sample), 200)
        self.assertEqual(report["selected_email_count"], 200)

    def test_seed_selector_excludes_source_threads_of_derived_candidates(self):
        candidates = [
            empty_record(email_id=f"derived-{index}", source_dataset="enron",
                         thread_id=f"derived-thread-{index}", raw_body="Message")
            for index in range(205)
        ]
        for index in (0, 1):
            candidates[index]["source_thread_id"] = "gold-source-thread"
        gold = empty_record(email_id="source-gold", source_dataset="enron",
                            thread_id="gold-source-thread", raw_body="Gold message")
        gold["annotation"] = {"status": "gold", "annotator": "reviewer",
                              "annotation_source": "human", "confidence": None}

        sample, excluded, eligible, _ = select_enron_seed_records(
            candidates, [gold], count=200, seed=17,
        )
        sampled_ids = {row["email_id"] for row in sample}
        self.assertEqual(eligible, 203)
        self.assertEqual(excluded["gold_thread"], 2)
        self.assertNotIn("derived-0", sampled_ids)
        self.assertNotIn("derived-1", sampled_ids)
        self.assertEqual(len(sample), 200)

    def test_seed_reserves_complete_multimessage_pairs_and_keeps_partner_strata(self):
        candidates = []
        metadata = []

        def add_record(email_id, thread_id, stratum, cue, *, turn=0, total=1):
            row = empty_record(email_id=email_id, source_dataset="enron", thread_id=thread_id,
                               raw_body="Message", turn_index=turn)
            candidates.append(row)
            metadata.append({"email_id": email_id, "thread_id": thread_id,
                             "sampling_stratum": stratum, "primary_sampling_cue": cue,
                             "thread_complete": True, "thread_total_count": total})

        pair_ids = []
        for index in range(12):
            thread_id = f"complete-pair-{index}"
            direct_id, random_id = f"pair-direct-{index}", f"pair-random-{index}"
            add_record(direct_id, thread_id, "direct_match", "meeting", turn=0, total=2)
            add_record(random_id, thread_id, "random_nonmatching", "random_nonmatching", turn=1, total=2)
            pair_ids.extend((direct_id, random_id))
        for index in range(200):
            add_record(f"direct-single-{index}", f"direct-single-thread-{index}",
                       "direct_match", f"cue-{index % 2}")
        for index in range(100):
            add_record(f"random-single-{index}", f"random-single-thread-{index}",
                       "random_nonmatching", "random_nonmatching")

        sample, _, eligible, report = select_enron_seed_records(
            candidates, [], count=250, seed=23, metadata_records=metadata,
        )
        selected_ids = {row["email_id"] for row in sample}
        self.assertEqual(eligible, 324)
        self.assertTrue(set(pair_ids).issubset(selected_ids))
        self.assertEqual(report["reserved_complete_multimessage_threads"], 12)
        self.assertEqual(report["reserved_complete_multimessage_emails"], 24)
        self.assertEqual(report["selected_complete_pair_threads"], 12)
        self.assertEqual(report["selected_complete_pair_emails"], 24)
        self.assertEqual(report["selected_by_stratum"]["random_nonmatching"], 63)
        self.assertEqual(report["selected_by_stratum"]["direct_match"], 187)
        self.assertGreaterEqual(report["selected_threads_with_multiple_emails"], 12)
        self.assertEqual(len(sample), 250)

    def test_seed_uses_random_expansion_and_cue_strata(self):
        candidates = []
        metadata = []
        for stratum, number in (("direct_match", 100), ("thread_context_match", 100), ("random_nonmatching", 100)):
            for index in range(number):
                email_id = f"{stratum}-{index}"
                row = empty_record(email_id=email_id, source_dataset="enron", thread_id=email_id, raw_body="Message")
                candidates.append(row)
                metadata.append({"email_id": email_id, "thread_id": email_id, "sampling_stratum": stratum,
                                 "primary_sampling_cue": "random_nonmatching" if stratum == "random_nonmatching" else f"cue-{index % 2}"})
        for thread_number in range(50):
            for turn in range(2):
                email_id = f"exp-{thread_number}-{turn}"
                row = empty_record(email_id=email_id, source_dataset="enron", thread_id=f"exp-thread-{thread_number}",
                                   raw_body=f"Message {turn}", turn_index=turn)
                candidates.append(row)
                metadata.append({"email_id": email_id, "thread_id": row["thread_id"],
                                 "sampling_stratum": "thread_expansion", "primary_sampling_cue": "thread_expansion",
                                 "thread_complete": True, "thread_total_count": 2})
        sample, _, _, report = select_enron_seed_records(
            candidates, [], count=200, seed=31, metadata_records=metadata,
        )
        self.assertEqual(report["selected_by_stratum"]["random_nonmatching"], 50)
        self.assertEqual(report["selected_by_stratum"]["thread_expansion"], 25)
        self.assertEqual(report["selected_by_primary_cue"]["cue-0"] + report["selected_by_primary_cue"]["cue-1"], 125)
        self.assertGreaterEqual(report["selected_threads_with_multiple_emails"], 12)
        self.assertTrue(report["metadata_sidecar_available"])
        self.assertEqual(len(sample), 200)

    def test_seed_rejects_incomplete_metadata_sidecar(self):
        candidates = [
            empty_record(email_id=f"meta-{index}", source_dataset="enron",
                         thread_id=f"thread-{index}", raw_body="Message")
            for index in range(200)
        ]
        metadata = [
            {"email_id": row["email_id"], "thread_id": row["thread_id"],
             "sampling_stratum": "direct_match", "primary_sampling_cue": "meeting"}
            for row in candidates[:-1]
        ]
        with self.assertRaisesRegex(ValueError, "cover exactly the candidate pool"):
            select_enron_seed_records(candidates, [], count=200, metadata_records=metadata)

    def test_config_tracks_shared_label_inventory(self):
        schema = Path(__file__).resolve().parents[1] / "annotation" / "label_schema.json"
        xml = make_label_studio_config(schema)
        self.assertIn('value="ACTION_REQUEST"', xml)
        self.assertIn('choice="multiple"', xml)
        self.assertIn(".htx-text { white-space: pre-wrap; }", xml)
        self.assertIn('value="DEADLINE_TIME"', xml)
        self.assertIn('name="thread_context"', xml)
        self.assertIn('name="metadata_display"', xml)


class AgreementAndAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.base = empty_record(
            email_id="e1", source_dataset="enron", thread_id="t1", raw_body="Call vendor Friday.",
        )

    def _review(self, reviewer, labels, spans=None, status="human_reviewed"):
        row = copy.deepcopy(self.base)
        row["labels"] = list(labels)
        row["spans"] = list(spans or [])
        row["annotation"] = {"status": status, "annotator": reviewer,
                             "annotation_source": "human", "confidence": None}
        if status == "unlabelled":
            row["annotation"]["needs_review"] = True
        return row

    def test_agreement_reports_label_confusion_and_span_overlap(self):
        a_span = {"label": "ACTION_ITEM", "text": "Call vendor", "start": 0, "end": 11, "field": "current_message"}
        b_span = {"label": "ACTION_ITEM", "text": "vendor", "start": 5, "end": 11, "field": "current_message"}
        a = self._review("reviewer-a", ["MEETING", "DEADLINE"], [a_span])
        b = self._review("reviewer-b", ["MEETING"], [b_span])
        report = compare_reviewer_records([a], [b])
        self.assertEqual(report["classification"]["per_label"]["DEADLINE"]["fp"], 1)
        self.assertEqual(report["classification"]["per_label"]["DEADLINE"]["observed_agreement"], 0.0)
        self.assertEqual(report["classification"]["per_label"]["MEETING"]["observed_agreement"], 1.0)
        self.assertEqual(report["classification"]["per_label"]["DEADLINE"]["cohen_kappa"], 0.0)
        self.assertEqual(report["classification"]["exact_set_agreement"], 0.0)
        self.assertEqual(report["classification"]["mean_jaccard"], 0.5)
        overlap = report["spans"]["by_label"]["ACTION_ITEM"]["overlap"]
        self.assertEqual(overlap["tp"], 1)
        self.assertAlmostEqual(overlap["mean_iou"], 6 / 11)

    def test_unresolved_pair_is_excluded_and_reported(self):
        a = self._review("reviewer-a", ["MEETING"])
        b = self._review("reviewer-b", [], status="unlabelled")
        report = compare_reviewer_records([a], [b])
        self.assertEqual(report["compared_records"], 0)
        self.assertEqual(report["excluded_unresolved_records"], 1)
        self.assertTrue(report["disagreements"][0]["unresolved"])
        self.assertTrue(report["agreement_is_not_gold"])

    def test_adjudication_requires_explicit_final_human_decision_and_never_gold(self):
        draft = {"email_id": "e1", "final": False, "adjudicator": "lead", "labels": ["NON_PROJECT"], "spans": []}
        with self.assertRaisesRegex(ValueError, "final=true"):
            apply_adjudication_decisions([self.base], [draft])
        draft["final"] = True
        result = apply_adjudication_decisions([self.base], [draft])[0]
        self.assertEqual(result["annotation"]["status"], "human_reviewed")
        self.assertEqual(result["annotation"]["annotator"], "lead")
        self.assertEqual(result["labels"], ["NON_PROJECT"])


if __name__ == "__main__":
    unittest.main()

import unittest

from src.mailex_extraction.metrics import (
    EvaluationDataError,
    _label_aware_span_matches,
    _thresholded_assignment,
    score_rows,
    validate_test_authorization,
)


def segment(text, start, end, *, value=None):
    return {"start": start, "end": end, "text": text[start:end] if value is None else value}


def locate(text, value, occurrence=0):
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(value, start + 1)
    return segment(text, start, start + len(value))


def arg(text, role, value, *, occurrence=0, qualifier=None, spans=None):
    return {
        "role": role,
        "qualifier": qualifier,
        "segments": spans if spans is not None else [locate(text, value, occurrence)],
    }


def event(event_type, text, trigger=None, arguments=(), *, flags=None):
    trigger_value = {"segments": [trigger]} if trigger else {"segments": []}
    result = {
        "event_type": event_type,
        "trigger": trigger_value,
        "arguments": list(arguments),
    }
    if flags is not None:
        result["flags"] = flags
    return result


def row(text, events, message_id="m1", split="dev"):
    return {"message_id": message_id, "thread_id": message_id, "split": split,
            "text": text, "events": list(events)}


class MailExExtractionMetricsTests(unittest.TestCase):
    def test_repeated_same_type_events_keep_arguments_attached_when_prediction_order_changes(self):
        text = "Alice met Bob; Carol met Dave."
        first = event("Meeting", text, locate(text, "met", 0), [
            arg(text, "Organizer", "Alice"), arg(text, "Attendee", "Bob")])
        second = event("Meeting", text, locate(text, "met", 1), [
            arg(text, "Organizer", "Carol"), arg(text, "Attendee", "Dave")])
        # The model returns the second event first; each argument remains
        # inside the event record that produced it.
        result = score_rows([row(text, [first, second])], [row(text, [second, first])])

        self.assertEqual(result["events"]["aligned"], 2)
        self.assertEqual(result["events"]["record_exact"]["f1"], 1.0)
        self.assertEqual(result["events"]["record_partial"]["f1"], 1.0)
        self.assertEqual(result["argument_records"]["exact"]["f1"], 1.0)

    def test_primary_record_score_ignores_trigger_and_reports_trigger_inclusive_score_separately(self):
        text = "Alice called Bob then Alice emailed."
        gold = event("Contact", text, locate(text, "called"), [arg(text, "Person", "Alice")])
        pred = event("Contact", text, locate(text, "emailed"), [arg(text, "Person", "Alice")])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["events"]["record_exact"]["f1"], 1.0)
        self.assertEqual(result["events"]["record_exact_with_trigger"]["f1"], 0.0)
        self.assertEqual(result["events"]["record_partial"]["f1"], 1.0)
        self.assertEqual(result["events"]["record_partial_with_trigger"]["f1"], 0.5)
        self.assertEqual(result["triggers"]["exact"]["f1"], 0.0)

    def test_wrong_type_and_wrong_role_are_reported_separately(self):
        text = "Meet Friday"
        gold = event("Request_Meeting", text, locate(text, "Meet"),
                     [arg(text, "Meeting Date", "Friday")])
        pred = event("Cancel_Meeting", text, locate(text, "Meet"),
                     [arg(text, "Meeting Location", "Friday")])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["events"]["error_categories"]["wrong_event_type"], 1)
        self.assertEqual(result["argument_records"]["error_categories"]["wrong_role"], 1)
        self.assertEqual(result["events"]["type_identification"]["micro"]["f1"], 0.0)
        self.assertEqual(result["triggers"]["exact"]["f1"], 1.0)

    def test_duplicate_prediction_is_counted_once_and_extra_copy_is_false_positive(self):
        text = "Alice called Bob"
        record = event("Call", text, locate(text, "called"), [arg(text, "Caller", "Alice")])
        result = score_rows([row(text, [record])], [row(text, [record, record])])

        self.assertEqual(result["events"]["aligned"], 1)
        self.assertEqual(result["events"]["error_categories"]["spurious_event"], 1)
        self.assertEqual(result["argument_records"]["exact"]["predicted"], 2)
        self.assertAlmostEqual(result["argument_records"]["exact"]["precision"], 0.5)

    def test_a_shared_source_mention_can_be_scored_in_each_attached_event(self):
        text = "Alice called and Alice replied."
        first = event("Call", text, locate(text, "called"), [arg(text, "Person", "Alice", occurrence=0)])
        second = event("Reply", text, locate(text, "replied"), [arg(text, "Person", "Alice", occurrence=1)])
        result = score_rows([row(text, [first, second])], [row(text, [first, second])])

        self.assertEqual(result["events"]["record_exact"]["f1"], 1.0)
        self.assertEqual(result["argument_records"]["exact"]["support"], 2)
        self.assertEqual(result["argument_records"]["exact"]["true_positive_credit"], 2)

    def test_invalid_prediction_offsets_are_counted_and_cannot_match(self):
        text = "Alice called Bob"
        gold = event("Call", text, locate(text, "called"), [arg(text, "Caller", "Alice")])
        invalid = {"start": 0, "end": 99, "text": "Alice"}
        pred = event("Call", text, locate(text, "called"),
                     [arg(text, "Caller", "Alice", spans=[invalid])])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["source_validation"]["invalid_offset_segments"], 1)
        self.assertEqual(result["source_validation"]["non_source_prediction_segments"], 1)
        self.assertEqual(result["argument_records"]["partial"]["true_positive_credit"], 0)

    def test_source_text_disagreement_is_a_hallucinated_span_even_with_valid_offsets(self):
        text = "Alice called Bob"
        gold = event("Call", text, locate(text, "called"), [arg(text, "Caller", "Alice")])
        wrong_text = {"start": 0, "end": 5, "text": "Alicia"}
        pred = event("Call", text, locate(text, "called"),
                     [arg(text, "Caller", "Alice", spans=[wrong_text])])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["source_validation"]["text_offset_mismatches"], 1)
        self.assertEqual(result["source_validation"]["non_source_prediction_segments"], 1)
        self.assertEqual(result["argument_records"]["partial"]["true_positive_credit"], 0)

    def test_prediction_span_without_surface_text_cannot_earn_offset_only_credit(self):
        text = "Alice called"
        gold = event("Call", text, locate(text, "called"), [arg(text, "Caller", "Alice")])
        pred = event("Call", text, locate(text, "called"), [
            arg(text, "Caller", "", spans=[{"start": 0, "end": 5}])
        ])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["source_validation"]["missing_span_text"], 1)
        self.assertEqual(result["source_validation"]["non_source_prediction_segments"], 1)
        self.assertEqual(result["argument_records"]["span_overlap"]["true_positive_credit"], 0)

    def test_prediction_body_must_be_the_same_source_message(self):
        gold_text = "Amy called Bob"
        changed_text = "Eve called Bob"
        gold = event("Call", gold_text, locate(gold_text, "called"),
                     [arg(gold_text, "Caller", "Amy")])
        pred = event("Call", changed_text, locate(changed_text, "called"),
                     [arg(changed_text, "Caller", "Eve")])

        with self.assertRaisesRegex(EvaluationDataError, "prediction text differs from gold"):
            score_rows([row(gold_text, [gold])], [row(changed_text, [pred])])

    def test_threshold_edges_are_removed_before_assignment(self):
        # If .49 is kept during assignment, the diagonal total is 1.39 and
        # thresholding afterward loses one valid pair. Masking it first picks
        # the two valid .60 cross edges.
        matches = _thresholded_assignment([[0.9, 0.6], [0.6, 0.49]], 0.5)
        self.assertEqual([(i, j) for i, j, _ in matches], [(0, 1), (1, 0)])

    def test_exact_role_matching_maximizes_role_correct_pairs_for_duplicate_spans(self):
        text = "Alice called"
        same_span = locate(text, "Alice")
        gold = event("Call", text, locate(text, "called"), [
            arg(text, "Caller", "", spans=[same_span]),
            arg(text, "Caller", "", spans=[same_span]),
        ])
        pred = event("Call", text, locate(text, "called"), [
            arg(text, "Caller", "", spans=[same_span]),
            arg(text, "Recipient", "", spans=[same_span]),
        ])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["argument_records"]["span_exact"]["f1"], 1.0)
        self.assertAlmostEqual(result["argument_records"]["role_exact"]["micro"]["precision"], 0.5)
        self.assertAlmostEqual(result["argument_records"]["role_exact"]["micro"]["recall"], 0.5)

    def test_overlapping_nested_and_discontinuous_segments_use_interval_union(self):
        text = "alpha x beta"
        gold_span = [segment(text, 0, 5), segment(text, 1, 4), locate(text, "beta")]
        pred_span = [locate(text, "beta"), segment(text, 0, 5)]
        gold = event("Direct_Record", text, arguments=[arg(text, "Entity", "", spans=gold_span)])
        pred = event("Direct_Record", text, arguments=[arg(text, "Entity", "", spans=pred_span)])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["triggers"]["exact"]["status"], "not_applicable")
        self.assertEqual(result["argument_records"]["span_overlap"]["f1"], 1.0)
        self.assertEqual(result["argument_records"]["span_exact"]["f1"], 0.0)
        self.assertEqual(result["argument_records"]["partial"]["f1"], 1.0)
        self.assertEqual(result["events"]["record_exact"]["f1"], 0.0)

    def test_split_segments_and_one_merged_segment_overlap_but_are_not_exact(self):
        text = "alpha beta"
        split = [segment(text, 0, 5), segment(text, 5, 10)]
        merged = [segment(text, 0, 10)]
        gold = event("Direct_Record", text, arguments=[arg(text, "Entity", "", spans=split)])
        pred = event("Direct_Record", text, arguments=[arg(text, "Entity", "", spans=merged)])
        result = score_rows([row(text, [gold])], [row(text, [pred])])

        self.assertEqual(result["argument_records"]["span_overlap"]["f1"], 1.0)
        self.assertEqual(result["argument_records"]["span_exact"]["f1"], 0.0)
        self.assertEqual(result["argument_records"]["role_exact"]["micro"]["f1"], 0.0)
        self.assertEqual(result["argument_records"]["partial"]["f1"], 1.0)

    def test_empty_predictions_are_included_in_message_denominator(self):
        text = "No event"
        gold_event = event("Event", text, locate(text, "event"))
        gold = [row(text, [gold_event]), row(text, [], message_id="m2")]
        pred = [row(text, [], message_id="m1"), row(text, [], message_id="m2")]
        result = score_rows(gold, pred)

        self.assertEqual(result["messages"]["empty_prediction_rate"], 1.0)
        self.assertEqual(result["events"]["type_identification"]["micro"]["recall"], 0.0)

    def test_malformed_gold_offsets_fail_instead_of_being_silently_repaired(self):
        text = "Alice called"
        malformed = {"start": 3, "end": 1, "text": "bad"}
        gold = event("Call", text, arguments=[arg(text, "Caller", "", spans=[malformed])])
        with self.assertRaisesRegex(EvaluationDataError, "malformed gold span"):
            score_rows([row(text, [gold])], [row(text, [])])

    def test_annotation_flags_are_counted_without_silent_repair_or_exclusion(self):
        text = "Alice called"
        flagged = event("Call", text, locate(text, "called"),
                        [arg(text, "Caller", "Alice", qualifier="Context", spans=[locate(text, "Alice")])],
                        flags=["source_review"])
        flagged["arguments"][0]["flags"] = ["offset_review"]
        result = score_rows([row(text, [flagged])], [row(text, [flagged])])

        self.assertEqual(result["source_validation"]["flagged_gold_events"], 1)
        self.assertEqual(result["source_validation"]["flagged_gold_arguments"], 1)
        self.assertEqual(result["events"]["record_exact"]["f1"], 1.0)

    def test_test_split_is_refused(self):
        with self.assertRaisesRegex(EvaluationDataError, "TEST scoring requires a valid"):
            score_rows([], [], split="test")

    def test_test_selection_lock_requires_frozen_digests_without_opening_test_data(self):
        digest = "a" * 64
        lock = {
            "schema_version": 1,
            "status": "locked",
            "split": "test",
            "gold_path": "ai/data/experiments/mailex_extraction_v1/test.jsonl",
            "gold_sha256": digest,
            "finalists": [{
                "run_id": "candidate-a",
                "architecture": "synthetic",
                "config": {},
                "thresholds": {},
                "expected_output_path": "ai/data/experiments/mailex_extraction_v1/private_test/candidate-a.jsonl",
                "model_weights": {"ai/data/model.bin": digest},
                "code": {"ai/scripts/predict.py": digest},
                "preprocessing": {"ai/src/preprocess.py": digest},
                "evaluator": {"ai/src/mailex_extraction/metrics.py": digest},
                "schema": {"ai/annotation/schema.json": digest},
            }],
        }
        validate_test_authorization(lock)
        with self.assertRaisesRegex(EvaluationDataError, "frozen 64-character gold_sha256"):
            validate_test_authorization({**lock, "gold_sha256": "unfrozen"})


if __name__ == "__main__":
    unittest.main()

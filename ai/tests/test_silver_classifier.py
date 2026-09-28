"""Focused tests for the leakage-safe silver baseline infrastructure."""

import tempfile
import unittest
from pathlib import Path

from scripts.train_silver_classifier import (
    apply_curated_exclusions,
    eligible_ai_silver,
    grouped_train_validation_split,
    join_text_free_acceptance_manifest,
    load_leakage_group_map,
)
from src.datasets.schemas import empty_record, write_jsonl
from src.models.silver_classifier import (
    LABEL_ORDER,
    TfidfOneVsRestLogisticRegression,
    calculate_multilabel_metrics,
    extract_authored_prefix,
    record_features,
)


def silver_row(index, *, label="MEETING", source="enron", thread=None):
    row = empty_record(
        email_id=f"{source}-mail-{index}",
        source_dataset=source,
        thread_id=thread or f"{source}-thread-{index}",
        raw_body=f"The meeting schedule is ready, code{index}.",
        subject="Project schedule",
    )
    row["current_message"] = row["raw_body"]
    row["clean_body"] = row["raw_body"]
    if label is None:
        row["annotation"]["needs_review"] = True
    else:
        row["labels"] = [label]
        row["annotation"].update({
            "status": "ai_prelabelled",
            "annotator": "test_ai_silver",
            "annotation_source": "ai",
            "needs_review": False,
            "intended_use": "classification_prototype_only",
        })
    return row


class SilverClassifierTests(unittest.TestCase):
    def test_lotus_header_block_trims_embedded_prior_message(self):
        body = (
            "I have this on my calendar. I do not plan to bring anyone else.\n\n"
            "Sharron Westbrook @ ENRON\n\n08/18/2000 04:22 PM\n"
            "To: Melissa Becker\ncc: Sally Beck\nSubject: Business Review\n"
            "Rick asked me to schedule the prior meeting."
        )
        prefix = extract_authored_prefix(body)
        self.assertIn("I have this on my calendar", prefix)
        self.assertNotIn("Sharron", prefix)
        self.assertNotIn("prior meeting", prefix)

    def test_features_use_only_subject_and_current_message(self):
        row = silver_row(1)
        row["current_message"] = "A concise current update."
        row["raw_body"] = "SECRETQUOTE alpha beta gamma"
        row["clean_body"] = "SECRETQUOTE alpha beta gamma"
        row["thread_context"] = "SECRETQUOTE alpha beta gamma"
        features = record_features(row)
        self.assertFalse(any("secretquote" in feature for feature in features))
        self.assertIn("body:w:concise", features)

    def test_multi_label_targets_follow_fixed_label_order(self):
        targets = TfidfOneVsRestLogisticRegression.encode_targets([
            ["MEETING", "DEADLINE"],
            ["NON_PROJECT"],
        ])
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0][LABEL_ORDER.index("MEETING")], 1)
        self.assertEqual(targets[0][LABEL_ORDER.index("DEADLINE")], 1)
        self.assertEqual(sum(targets[1]), 1)
        self.assertEqual(targets[1][LABEL_ORDER.index("NON_PROJECT")], 1)
        with self.assertRaisesRegex(ValueError, "cannot co-occur"):
            TfidfOneVsRestLogisticRegression.encode_targets([["NON_PROJECT", "MEETING"]])

    def test_prototype_training_excludes_abstentions_human_and_gold(self):
        accepted = silver_row(1)
        abstention = silver_row(2, label=None)
        human = silver_row(3)
        human["annotation"].update({"status": "human_reviewed", "annotation_source": "human"})
        gold = silver_row(4)
        gold["annotation"].update({"status": "gold", "annotation_source": "human"})
        self.assertTrue(eligible_ai_silver(accepted))
        self.assertFalse(eligible_ai_silver(abstention))
        self.assertFalse(eligible_ai_silver(human))
        self.assertFalse(eligible_ai_silver(gold))

    def test_curated_cross_batch_quote_exclusion_happens_before_training(self):
        quoted = silver_row(1)
        quoted["email_id"] = "enron-8e3611db3d1dc3b49f05b802"
        safe = silver_row(2)
        kept, excluded = apply_curated_exclusions(
            [quoted, safe], {quoted["email_id"]: "quoted prior pilot body"},
        )
        self.assertEqual([row["email_id"] for row in kept], [safe["email_id"]])
        self.assertEqual([row["email_id"] for row in excluded], [quoted["email_id"]])

    def test_split_unions_thread_and_cross_source_leakage_groups(self):
        rows = []
        groups = {}
        for index in range(14):
            row = silver_row(index)
            rows.append(row)
            groups[(row["source_dataset"], row["email_id"])] = f"g-{index}"
        rows[0]["thread_id"] = rows[1]["thread_id"] = "shared-thread"
        rows[0]["email_id"] = "enron-original"
        rows[1]["source_dataset"] = "mailex"
        rows[1]["email_id"] = "mailex-copy"
        groups.pop(("enron", "enron-mail-0"))
        groups[("enron", "enron-original")] = "cross-source-duplicate"
        groups.pop(("enron", "enron-mail-1"))
        groups[("mailex", "mailex-copy")] = "cross-source-duplicate"
        # The same thread and same underlying message are connected even if
        # one sidecar edge alone would not be enough.
        groups[("enron", "enron-mail-2")] = "thread-neighbor"
        rows[2]["thread_id"] = "shared-thread"
        splits, summary = grouped_train_validation_split(rows, groups, seed=7)
        owners = {}
        for split_name, partition in splits.items():
            for row in partition:
                thread = (row["source_dataset"], row["thread_id"])
                leakage_id = groups[(row["source_dataset"], row["email_id"])]
                for key in (("thread", thread), ("leakage", leakage_id)):
                    if key in owners:
                        self.assertEqual(owners[key], split_name)
                    else:
                        owners[key] = split_name
        self.assertEqual(
            owners[("thread", ("enron", "shared-thread"))],
            owners[("leakage", "cross-source-duplicate")],
        )
        self.assertEqual(summary["method"], "connected components of source-qualified threads and leakage_group_id")

    def test_leakage_sidecar_requires_key_and_matching_thread(self):
        row = silver_row(1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.jsonl"
            write_jsonl(path, [{
                "source_dataset": row["source_dataset"],
                "email_id": row["email_id"],
                "thread_id": row["thread_id"],
                "leakage_group_id": "group-a",
                "match_kind": "singleton",
            }])
            groups = load_leakage_group_map(path, [row])
            self.assertEqual(groups[(row["source_dataset"], row["email_id"])], "group-a")
            write_jsonl(path, [{
                "source_dataset": row["source_dataset"],
                "email_id": row["email_id"],
                "thread_id": "wrong-thread",
                "leakage_group_id": "group-a",
            }])
            with self.assertRaisesRegex(ValueError, "thread_id mismatch"):
                load_leakage_group_map(path, [row])

    def test_text_free_acceptance_manifest_joins_labels_to_canonical_source(self):
        source = empty_record(
            email_id="enron-accepted", source_dataset="enron",
            thread_id="thread-accepted", raw_body="This source text stays in the canonical file.",
            subject="Source subject",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.jsonl"
            manifest_path = root / "accepted.jsonl"
            write_jsonl(source_path, [source])
            write_jsonl(manifest_path, [{
                "source_dataset": "enron",
                "email_id": "enron-accepted",
                "thread_id": "thread-accepted",
                "labels": ["ACTION_REQUEST"],
                "status": "ai_silver",
                "training_provenance": "ai_silver",
                "acceptance_rule": "reviewed",
            }])
            rows, info = join_text_free_acceptance_manifest(manifest_path, [source_path])
            self.assertEqual(rows[0]["labels"], ["ACTION_REQUEST"])
            self.assertEqual(rows[0]["current_message"], source["current_message"])
            self.assertEqual(rows[0]["annotation"]["status"], "ai_prelabelled")
            self.assertEqual(info["accepted_rows"], 1)
            write_jsonl(manifest_path, [{
                "source_dataset": "enron",
                "email_id": "enron-accepted",
                "labels": ["ACTION_REQUEST"],
                "status": "ai_silver",
                "training_provenance": "ai_silver",
                "current_message": "forbidden text in sidecar",
            }])
            with self.assertRaisesRegex(ValueError, "text-free"):
                join_text_free_acceptance_manifest(manifest_path, [source_path])

    def test_model_save_load_preserves_probabilities(self):
        rows = [
            silver_row(i, label="MEETING" if i % 2 == 0 else "NON_PROJECT")
            for i in range(12)
        ]
        model = TfidfOneVsRestLogisticRegression(max_iter=30).fit(rows)
        probe = silver_row(50)
        before = model.predict(probe)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save(path)
            loaded = TfidfOneVsRestLogisticRegression.load(path)
        self.assertEqual(before, loaded.predict(probe))
        self.assertEqual(set(loaded.classifiers), set(LABEL_ORDER))
        self.assertEqual(loaded.to_dict()["model_type"], "TF-IDF + one-vs-rest logistic regression")

    def test_metric_calculation_on_hand_built_fixture(self):
        expected = [["MEETING"], ["NON_PROJECT"], ["DEADLINE", "ACTION_REQUEST"]]
        predicted = [["MEETING"], ["GENERAL_UPDATE"], ["DEADLINE"]]
        metrics = calculate_multilabel_metrics(expected, predicted)
        self.assertEqual(metrics["records"], 3)
        self.assertAlmostEqual(metrics["micro_precision"], 2 / 3)
        self.assertAlmostEqual(metrics["micro_recall"], 2 / 4)
        self.assertAlmostEqual(metrics["subset_match_rate"], 1 / 3)
        self.assertEqual(metrics["per_label"]["APPROVAL"]["support"], 0)


if __name__ == "__main__":
    unittest.main()

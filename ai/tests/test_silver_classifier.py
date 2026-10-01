"""Focused tests for the leakage-safe silver baseline infrastructure."""

import io
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.train_silver_classifier import (
    apply_curated_exclusions,
    eligible_ai_silver,
    eligibility_reason,
    grouped_train_validation_split,
    join_text_free_acceptance_manifest,
    load_leakage_group_map,
    main as train_main,
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
    @unittest.skipUnless(importlib.util.find_spec("sklearn"), "optional training dependency")
    def test_sklearn_weight_export_matches_reference_and_reloads(self):
        from scipy.sparse import csr_matrix
        from sklearn.linear_model import LogisticRegression

        rows = [silver_row(i, label="MEETING" if i < 4 else "NON_PROJECT") for i in range(8)]
        for i, row in enumerate(rows):
            row["subject"] = "Project review" if i < 4 else "Social plans"
            row["current_message"] = "Meet to review the project plan." if i < 4 else "Lunch with friends."
        model = TfidfOneVsRestLogisticRegression(optimizer="sklearn", c=4, max_iter=1000).fit(rows)
        vectors = model.vectorizer.transform([record_features(row) for row in rows])
        dense = [[v.get(i, 0) for i in range(len(model.vectorizer.vocabulary))] for v in vectors]
        reference = LogisticRegression(C=4, solver="lbfgs", max_iter=1000, tol=model.tolerance, random_state=42)
        reference.fit(csr_matrix(dense), [int("MEETING" in row["labels"]) for row in rows])
        expected = reference.predict_proba(csr_matrix(dense))[:, 1]
        restored = TfidfOneVsRestLogisticRegression.from_dict(model.to_dict())
        for row, probability in zip(rows, expected):
            self.assertAlmostEqual(restored.predict_proba(row)["MEETING"], float(probability), places=10)
            self.assertEqual(restored.predict(row), model.predict(row))
        self.assertEqual(restored.optimizer, "sklearn")
        self.assertTrue(all(x["converged"] for x in model.classifiers.values()))
        self.assertEqual(model.classifiers["APPROVAL"]["training_positive"], 0)
        self.assertLess(restored.predict_proba(rows[0])["APPROVAL"], 0.1)

    def test_sender_email_and_date_trims_lotus_quoted_history(self):
        body = (
            "Thanks for the attachment. How did the presentation go?\n\n"
            "Casey Example <casey@example.test> on 03/14/2001 07:07:48 AM\n"
            "Please respond to casey@example.test\n"
            "To: Morgan Example <morgan@example.test>\n"
            "cc: Taylor Example <taylor@example.test>\n"
            "Subject: Previous project request\n\n"
            "Please submit the report by Friday."
        )
        self.assertEqual(
            extract_authored_prefix(body),
            "Thanks for the attachment. How did the presentation go?",
        )
        row = silver_row(1)
        row["current_message"] = body
        self.assertNotIn("body:w:submit", record_features(row))

    def test_sender_date_without_mail_header_block_remains_authored(self):
        body = (
            "Our attendance record follows.\n"
            "Casey Example <casey@example.test> on 03/14/2001 07:07:48 AM\n"
            "The participant completed the project demonstration."
        )
        self.assertEqual(extract_authored_prefix(body), body)

    def test_bare_email_timestamp_and_column_headers_trim_prior_messages(self):
        for header in (
            "casey@example.test on 03/14/2001 07:07:48 AM\nTo: Morgan\ncc:\nSubject: Prior request",
            "       casey@\n       example.test   To: morgan@example.test\n                      cc:\n       03/14/01       Subject: Prior request\n       09:19 AM",
        ):
            body = "The current task is complete.\n\n" + header + "\n\nPlease submit the report by Friday."
            self.assertEqual(extract_authored_prefix(body), "The current task is complete.")

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

    def test_forward_only_record_cannot_train_from_subject(self):
        row = silver_row(1)
        row["current_message"] = (
            "From: Casey <casey@example.test>\nTo: Morgan <morgan@example.test>\n"
            "Subject: FW: Project meeting\nDate: 03/14/2001\n\n"
            "Schedule the project review for Friday."
        )
        self.assertEqual(extract_authored_prefix(row["current_message"]), "")
        self.assertFalse(eligible_ai_silver(row))
        self.assertEqual(eligibility_reason(row), "empty_authored_message")

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

    def test_cli_excludes_abstentions_before_leakage_sidecar_join(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = [silver_row(1), silver_row(2, label="NON_PROJECT")]
            abstention = silver_row(3, label=None)
            abstention["thread_id"] = "candidate-heuristic-thread"
            input_path = root / "input.jsonl"
            sidecar_path = root / "groups.jsonl"
            exclusions_path = root / "exclusions.json"
            shortage_path = root / "shortage.md"
            report_path = root / "report.json"
            write_jsonl(input_path, accepted + [abstention])
            write_jsonl(sidecar_path, [
                {
                    "source_dataset": row["source_dataset"],
                    "email_id": row["email_id"],
                    "thread_id": row["thread_id"],
                    "leakage_group_id": f"group-{index}",
                }
                for index, row in enumerate(accepted)
            ])
            exclusions_path.write_text('{"training_exclusions": {}}', encoding="utf-8")
            shortage_path.write_text(
                "Fixture shortage: two accepted records are intentional for the CLI regression test.",
                encoding="utf-8",
            )
            argv = [
                "train_silver_classifier.py", "--input", str(input_path),
                "--no-accepted-manifest", "--leakage-groups", str(sidecar_path),
                "--exclude-manifest", str(exclusions_path),
                "--shortage-report", str(shortage_path),
                "--model", str(root / "model.json"),
                "--split-manifest", str(root / "split.json"),
                "--report", str(report_path), "--max-iter", "3",
            ]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(train_main(), 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["data"]["eligible_ai_silver_records"], 2)
            self.assertEqual(report["data"]["other_records_excluded_from_model"], 1)

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

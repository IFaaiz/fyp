from __future__ import annotations

import hashlib
import unittest

from src.models.silver_classifier import LABEL_ORDER
from src.models.transfer_diagnostic import (
    exclusive_predictions,
    load_shared_partitions,
    positive_weights,
    source_material_sha256,
    target_matrix,
    tune_thresholds,
    validate_snapshot,
)


def _record(index: int, label: str) -> tuple[dict, dict]:
    email_id = f"e{index}"
    record = {
        "email_id": email_id,
        "source_dataset": "enron",
        "thread_id": f"thread-{index}",
        "subject": f"subject {index}",
        "current_message": f"authored body {index}",
        "thread_context": "",
        "authored_message": f"authored body {index}",
        "labels": [label],
        "annotation": {"status": "ai_prelabelled", "annotation_source": "ai"},
    }
    field_hashes = {
        field: hashlib.sha256(record[field].encode("utf-8")).hexdigest()
        for field in ("subject", "current_message", "thread_context")
    }
    material_sha = source_material_sha256(record)
    provenance = {
        "email_id": email_id,
        "source_dataset": "enron",
        "thread_id": f"thread-{index}",
        "labels": [label],
        "leakage_group_id": f"group-{index}",
        "source_hashes": field_hashes,
        "source_sha256": material_sha,
        "authored_message_sha256": hashlib.sha256(record["authored_message"].encode("utf-8")).hexdigest(),
        "source_acceptance_manifest": "accepted.jsonl",
        "acceptance_rule": "ai_silver",
        "status": "ai_silver",
        "training_provenance": "ai_silver",
    }
    record["snapshot_provenance"] = provenance
    manifest = dict(provenance)
    return record, manifest


class TransferDiagnosticHelpersTests(unittest.TestCase):
    def test_target_encoding_uses_registered_label_order(self):
        result = target_matrix([["MEETING", "NON_PROJECT"]])
        self.assertEqual(len(result[0]), len(LABEL_ORDER))
        self.assertEqual(result[0][LABEL_ORDER.index("MEETING")], 1)
        self.assertEqual(result[0][LABEL_ORDER.index("NON_PROJECT")], 1)
        self.assertEqual(sum(result[0]), 2)

    def test_positive_weights_use_only_fit_examples(self):
        weights, details = positive_weights([["APPROVAL"], ["NON_PROJECT"], ["NON_PROJECT"]])
        index = LABEL_ORDER.index("APPROVAL")
        self.assertEqual(weights[index], 2.0)
        self.assertEqual(details["APPROVAL"]["positive"], 1)
        self.assertTrue(details["FOLLOW_UP"]["weight_unavailable_no_positive_fit_examples"])
        self.assertEqual(weights[LABEL_ORDER.index("FOLLOW_UP")], 1.0)

    def test_non_project_resolution_matches_existing_model_rule(self):
        row = [0.1] * len(LABEL_ORDER)
        row[LABEL_ORDER.index("MEETING")] = 0.7
        row[LABEL_ORDER.index("NON_PROJECT")] = 0.8
        self.assertEqual(exclusive_predictions([row], [0.5] * len(LABEL_ORDER)), [["NON_PROJECT"]])
        row[LABEL_ORDER.index("NON_PROJECT")] = 0.6
        self.assertEqual(exclusive_predictions([row], [0.5] * len(LABEL_ORDER)), [["MEETING"]])

    def test_thresholds_are_tuned_and_report_small_support(self):
        expected = [["APPROVAL"], ["NON_PROJECT"], ["APPROVAL"]]
        probs = [[0.9 if label == "APPROVAL" else 0.1 for label in LABEL_ORDER] for _ in expected]
        thresholds, report = tune_thresholds(expected, probs)
        self.assertEqual(len(thresholds), len(LABEL_ORDER))
        self.assertTrue(report["APPROVAL"]["unstable_support_below_20"])
        self.assertEqual(report["APPROVAL"]["tuning_positive_support"], 2)

    def test_snapshot_rejects_mismatched_source_hash(self):
        row, manifest = _record(1, "MEETING")
        manifest["source_hashes"]["subject"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "subject"):
            validate_snapshot([row], [manifest])

    def test_snapshot_rejects_human_provenance(self):
        row, manifest = _record(1, "MEETING")
        row["annotation"] = {"status": "human_reviewed", "annotation_source": "human"}
        with self.assertRaisesRegex(ValueError, "annotation source/status"):
            validate_snapshot([row], [manifest])

    def test_snapshot_rejects_unbound_authored_message(self):
        row, manifest = _record(1, "MEETING")
        row["snapshot_provenance"]["authored_message_sha256"] = "0" * 64
        manifest["authored_message_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "authored_message hash"):
            validate_snapshot([row], [manifest])

    def test_shared_split_rejects_manifest_hash_mismatch(self):
        rows_and_manifests = [_record(i, "MEETING") for i in range(3)]
        rows = [pair[0] for pair in rows_and_manifests]
        split = {
            "snapshot_manifest_sha256": "wrong-hash",
            "partitions": {
                "fit": [rows[0]["snapshot_provenance"]],
                "tuning": [rows[1]["snapshot_provenance"]],
                "validation": [rows[2]["snapshot_provenance"]],
            },
        }
        with self.assertRaisesRegex(ValueError, "snapshot_manifest_sha256"):
            load_shared_partitions(rows, split, snapshot_sha256="snapshot", silver_manifest_sha256="manifest")

    def test_shared_split_rejects_thread_or_group_crossing_partitions(self):
        row_a, _ = _record(1, "MEETING")
        row_b, _ = _record(2, "MEETING")
        row_b["thread_id"] = row_a["thread_id"]
        row_b["snapshot_provenance"]["thread_id"] = row_a["thread_id"]
        split = {
            "snapshot_manifest_sha256": "manifest",
            "partitions": {
                "fit": [{"email_id": row_a["email_id"], "source_dataset": "enron", "thread_id": row_a["thread_id"], "leakage_group_id": "group-1"}],
                "tuning": [{"email_id": row_b["email_id"], "source_dataset": "enron", "thread_id": row_b["thread_id"], "leakage_group_id": "group-2"}],
                "validation": [],
            },
        }
        with self.assertRaisesRegex(ValueError, "thread crosses"):
            load_shared_partitions([row_a, row_b], split, snapshot_sha256="snapshot", silver_manifest_sha256="manifest")


if __name__ == "__main__":
    unittest.main()


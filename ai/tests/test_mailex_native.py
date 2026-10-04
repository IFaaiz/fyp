import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import unicodedata

from src.datasets.mailex_native import build_fyp_safe_views, convert_thread


class MailExNativeTests(unittest.TestCase):
    def test_native_conversion_keeps_case_qualifiers_offsets_and_orphan_i(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "thread-one.json"
            source = {
                "sentences": [
                    ["we", "meet", "Fri", ".", "maybe", "later"],
                    [""],
                ],
                "events": {
                    "turn_0": {
                        "Request_Action": {
                            "labels": [[
                                "O", "O",
                                "Request_Action:Context: B-Action Members",
                                "Request_Action:Context: I-Action Members",
                                "O", "O",
                            ]],
                            "triggers": ["{'words': 'meet', 'indices': '1'}"],
                            "extras": ["Request Attribute : Action Members"],
                        },
                        "Amend_Meeting_Data": {
                            "labels": [[
                                "O", "O", "O", "O",
                                "Amend_Meeting_Data:Revision: I-Meeting Date",
                                "O",
                            ]],
                            "triggers": ["{'words': 'later', 'indices': '5'}"],
                            "extras": ["Revision : Meeting Date"],
                        },
                        "Deliver_Data": {
                            "labels": [[
                                "O", "O", "O", "O", "O",
                                "Deliver_Data:B-Deliver members",
                            ]],
                            "triggers": ["{'words': 'later', 'indices': '5'}"],
                            "extras": ["Data Value"],
                        },
                        "O": {
                            "labels": [["O"] * 6],
                            "triggers": [""],
                            "extras": [""],
                        },
                    },
                },
            }
            source_path.write_text(json.dumps(source), encoding="utf-8")

            rows = convert_thread(source_path, "train")
            message = rows[0]
            self.assertEqual(len(rows), 2)
            self.assertEqual(message["text"], "we meet Fri . maybe later")
            self.assertEqual(message["token_offsets"][1], {"start": 3, "end": 7})
            self.assertEqual(len(message["events"]), 3)
            self.assertEqual(len(message["outside_markers"]), 1)

            request = next(event for event in message["events"] if event["event_type"] == "Request_Action")
            argument = request["arguments"][0]
            self.assertEqual(argument["role"], "Action Members")
            self.assertEqual(argument["qualifier"], "context")
            self.assertEqual(argument["source_qualifier"], "Context")
            self.assertEqual(argument["segments"][0]["token_indices"], [2, 3])
            self.assertEqual(argument["segments"][0]["text"], "Fri .")
            self.assertEqual(argument["segments"][0]["start"], 8)
            self.assertEqual(argument["segments"][0]["end"], 13)
            self.assertEqual(request["trigger"]["segments"][0]["text"], "meet")
            self.assertEqual(request["source_extra"], "Request Attribute : Action Members")

            amend = next(event for event in message["events"] if event["event_type"] == "Amend_Meeting_Data")
            self.assertEqual(amend["arguments"][0]["role"], "Meeting Date")
            self.assertEqual(amend["arguments"][0]["qualifier"], "revision")
            self.assertEqual(amend["arguments"][0]["flags"], ["orphan_I_tag"])
            self.assertEqual(amend["source_annotation"]["labels"][4], "Amend_Meeting_Data:Revision: I-Meeting Date")

            deliver = next(event for event in message["events"] if event["event_type"] == "Deliver_Data")
            self.assertEqual(deliver["arguments"][0]["role"], "Deliver members")
            self.assertEqual(rows[1]["tokens"], [""])
            self.assertIn("empty_reconstructed_text", rows[1]["flags"])

    def test_safe_view_expands_protected_component_and_drops_whole_thread(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows_dir = root / "official"
            output_dir = root / "safe"
            rows_dir.mkdir()
            text = "Schedule the review with the planning team during the next available business afternoon."
            normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
            exact_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            native_rows = [
                {"message_id": "thread-a::turn-0", "thread_id": "thread-a", "split": "train", "text": text, "tokens": text.split(), "events": []},
                {"message_id": "thread-a::turn-1", "thread_id": "thread-a", "split": "train", "text": "unmatched continuation", "tokens": ["unmatched", "continuation"], "events": []},
                {"message_id": "thread-b::turn-0", "thread_id": "thread-b", "split": "train", "text": "unrelated message", "tokens": ["unrelated", "message"], "events": []},
            ]
            source_path = rows_dir / "train.jsonl"
            source_path.write_text("".join(json.dumps(row) + "\n" for row in native_rows), encoding="utf-8")
            for split in ("dev", "test"):
                (rows_dir / f"{split}.jsonl").write_text("", encoding="utf-8")

            boundary_path = root / "boundary.json"
            boundary_path.write_text(json.dumps({"protected_ids": ["enron:protected"]}), encoding="utf-8")
            index_path = root / "index.json"
            index_path.write_text(json.dumps({
                "version": "test",
                "records": {
                    "enron:protected": {"dataset": "enron", "leakage_group_id": "g1"},
                    "enron:linked": {"dataset": "enron", "leakage_group_id": "g1", "body_exact_sha256": exact_hash},
                },
                "links": [{"left": "enron:protected", "right": "enron:linked", "reason": "test"}],
            }), encoding="utf-8")
            before_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()

            manifest = build_fyp_safe_views(
                rows_dir=rows_dir,
                boundary_path=boundary_path,
                index_path=index_path,
                output_dir=output_dir,
            )
            safe_rows = [json.loads(line) for line in (output_dir / "train_fyp_safe.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["thread_id"] for row in safe_rows], ["thread-b"])
            counts = manifest["fyp_safe_split_counts"]["train"]
            self.assertEqual(counts["direct_protected_match_messages"], 0)
            self.assertEqual(counts["link_or_group_component_match_messages"], 1)
            self.assertEqual(counts["excluded_threads"], 1)
            self.assertEqual(counts["excluded_messages"], 2)
            self.assertEqual(counts["retained_messages"], 1)
            self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), before_hash)
            manifest_text = json.dumps(manifest)
            self.assertNotIn("enron:protected", manifest_text)
            self.assertNotIn("thread-a", manifest_text)
            self.assertNotIn(text, manifest_text)


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest

from src.datasets.mailex import prepare_mailex
from src.datasets.validation import validate_records


AI_ROOT = Path(__file__).resolve().parents[1]
MAPPING = AI_ROOT / "annotation" / "mailex_mapping.json"


class MailExMappingTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> tuple[Path, Path]:
        data_dir = root / "full_data"
        raw_dir = root / "raw_threads"
        data_dir.mkdir(parents=True)
        raw_dir.mkdir(parents=True)
        source = {
            "sentences": [
                ["Please", "send", "report", "today", "."],
                ["Moved", "meeting", "from", "Monday", "to", "Friday"],
                ["Who", "owns", "the", "meeting", "report", "?"],
                ["I", "can", "attend"],
                ["Friday"],
                ["Thanks"],
            ],
            "events": {
                "turn_0": {
                    "Request_Action": {
                        "labels": [[
                            "O",
                            "Request_Action:B-Action Description",
                            "Request_Action:I-Action Description",
                            "O",
                            "O",
                        ]],
                        "triggers": ["{'words': 'send', 'indices': '1'}"],
                        "extras": [""],
                    }
                },
                "turn_1": {
                    "Amend_Meeting_Data": {
                        "labels": [[
                            "O",
                            "O",
                            "O",
                            "Amend_Meeting_Data:Context: B-Meeting Date",
                            "O",
                            "Amend_Meeting_Data:Revision: B-Meeting Date",
                        ]],
                        "triggers": ["{'words': 'Moved', 'indices': '0'}"],
                        "extras": ["Amend Type : Update"],
                    }
                },
                "turn_2": {
                    "Request_Data": {
                        "labels": [[
                            "O",
                            "O",
                            "O",
                            "O",
                            "Request_Data:Context: B-Data idString",
                            "O",
                        ]],
                        "triggers": ["{'words': 'Who owns', 'indices': '0 1'}"],
                        "extras": ["Request Attribute : Data Owner"],
                    }
                },
            },
        }
        source["events"]["turn_2"]["O"] = {
            "labels": [["O", "O", "O", "O", "O", "O"]],
            "triggers": [""],
            "extras": [""],
        }
        source["events"]["turn_3"] = {
            "Request_Meeting": {
                "labels": [["Request_Meeting:B-Meeting Members", "O", "O"]],
                "triggers": ["{'words': 'attend', 'indices': '2'}"],
                "extras": [""],
            }
        }
        source["events"]["turn_4"] = {
            "Request_Meeting": {
                "labels": [["Request_Meeting:I-Meeting Date"]],
                "triggers": ["{'words': 'Friday', 'indices': '0'}"],
                "extras": [""],
            }
        }
        source["events"]["turn_5"] = {
            "O": {"labels": [["O"]], "triggers": [""], "extras": [""]}
        }
        (data_dir / "t1.json").write_text(json.dumps(source), encoding="utf-8")
        raw = (
            "FROM: sixth@example.com\nTO: team@example.com\nSUBJECT: Re: Schedule\n\n"
            "Thanks\n-----------------------------\n"
            "FROM: fifth@example.com\nTO: team@example.com\nSUBJECT: Re: Schedule\n\n"
            "Friday\n-----------------------------\n"
            "FROM: fourth@example.com\nTO: team@example.com\nSUBJECT: Re: Schedule\n\n"
            "I can attend\n-----------------------------\n"
            "FROM: third@example.com\nTO: team@example.com\nSUBJECT: Re: Schedule\n\n"
            "Who owns the meeting report ?\n-----------------------------\n"
            "FROM: second@example.com\nTO: team@example.com\nSUBJECT: Re: Schedule\n\n"
            "Moved meeting from Monday to Friday\n-----------------------------\n"
            "FROM: first@example.com\nTO: team@example.com\nSUBJECT: Schedule\n\n"
            "Please send report today ."
        )
        (raw_dir / "t1").write_text(raw, encoding="utf-8")
        return data_dir, raw_dir

    def test_real_source_shape_maps_spans_and_keeps_classes_unlabelled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, raw_dir = self._write_fixture(root)
            output = root / "processed.jsonl"
            stats_path = root / "stats.json"
            stats = prepare_mailex(
                data_dir=data_dir,
                raw_threads_dir=raw_dir,
                mapping_path=MAPPING,
                output_path=output,
                stats_path=stats_path,
            )
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(stats["threads"], 1)
        self.assertEqual(stats["messages"], 6)
        self.assertEqual(stats["source_event_count"], 5)
        self.assertEqual(stats["mapped_event_count"], 2)
        self.assertEqual(stats["ambiguous_argument_spans"], 1)
        self.assertEqual(stats["source_o_marker_turns"], 2)
        self.assertEqual(stats["source_o_with_event_turns"], 1)
        self.assertEqual(stats["source_o_only_turns"], 1)
        self.assertEqual(stats["non_event_messages"], 1)
        self.assertEqual(stats["bare_pronoun_participant_spans"], 1)
        self.assertEqual(stats["malformed_bio_argument_spans"], 1)
        self.assertEqual(records[0]["labels"], [])
        self.assertEqual(records[0]["annotation"]["status"], "unlabelled")
        self.assertTrue(all(record["annotation"]["needs_review"] for record in records))
        self.assertEqual(records[0]["sender"], "first@example.com")
        self.assertEqual(records[0]["subject"], "Schedule")
        self.assertEqual(records[1]["thread_context"], records[0]["current_message"])
        self.assertEqual(records[2]["spans"], [])
        self.assertEqual(
            records[2]["annotation"]["source_annotations"]["events"][0]["arguments"][0]["mapping_status"],
            "ambiguous",
        )
        date_spans = [span for span in records[1]["spans"] if span["label"] == "MEETING_DATE"]
        self.assertEqual([span["text"] for span in date_spans], ["Monday", "Friday"])
        self.assertEqual([span["source_qualifier"] for span in date_spans], ["context", "revision"])
        self.assertTrue(all(span["review_status"] == "requires_project_scope_human_review" for span in date_spans))
        self.assertEqual(records[3]["spans"], [])
        pronoun_argument = records[3]["annotation"]["source_annotations"]["events"][0]["arguments"][0]
        self.assertEqual(pronoun_argument["mapping_status"], "unmapped")
        self.assertEqual(pronoun_argument["candidate_label"], "PARTICIPANT")
        self.assertEqual(records[4]["spans"], [])
        malformed_argument = records[4]["annotation"]["source_annotations"]["events"][0]["arguments"][0]
        self.assertTrue(malformed_argument["malformed_bio_start"])
        self.assertEqual(malformed_argument["mapping_status"], "unmapped")
        self.assertEqual(validate_records(records)["errors"], [])


if __name__ == "__main__":
    unittest.main()

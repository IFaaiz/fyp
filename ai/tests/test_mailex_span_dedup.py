import unittest

from src.datasets.mailex import deduplicate_canonical_spans


class MailExSpanDedupTests(unittest.TestCase):
    def test_identical_entity_keeps_both_source_arguments(self):
        first = {
            "field": "current_message", "start": 10, "end": 16,
            "label": "MEETING_DATE", "text": "Friday",
            "source_event_type": "Request_Meeting",
            "source_event_index": 0, "source_role": "Meeting Date",
            "source_qualifier": None, "mapping_status": "direct",
        }
        second = {**first, "source_event_type": "Amend_Meeting_Data", "source_event_index": 1}
        distinct = {**first, "label": "DEADLINE_DATE"}
        spans, duplicates = deduplicate_canonical_spans([first, second, distinct])
        self.assertEqual(duplicates, 1)
        self.assertEqual(len(spans), 2)
        self.assertEqual(
            [p["source_event_type"] for p in spans[0]["source_provenance"]],
            ["Request_Meeting", "Amend_Meeting_Data"],
        )
        self.assertEqual(len(spans[1]["source_provenance"]), 1)


if __name__ == "__main__":
    unittest.main()

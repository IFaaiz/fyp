import json
import unittest
from pathlib import Path

from src.datasets.schemas import LABELS, SPAN_LABELS, read_jsonl
from src.datasets.validation import validate_records


AI_ROOT = Path(__file__).resolve().parents[1]


class TaxonomySyncTests(unittest.TestCase):
    def test_documented_labels_match_validator(self):
        catalog = json.loads((AI_ROOT / "annotation" / "label_schema.json").read_text(encoding="utf-8"))
        self.assertEqual({item["name"] for item in catalog["classification"]["labels"]}, LABELS)
        self.assertEqual({item["name"] for item in catalog["extraction"]["span_labels"]}, SPAN_LABELS)
        self.assertIn("ACTION_REQUEST", LABELS)
        self.assertIn("DEADLINE_TIME", SPAN_LABELS)

    def test_revised_examples_validate(self):
        report = validate_records(read_jsonl(AI_ROOT / "annotation" / "examples" / "annotation_examples.jsonl"))
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["records"], 13)


if __name__ == "__main__":
    unittest.main()

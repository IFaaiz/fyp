import unittest
from desktop.local_product.item_contracts import SCHEMA, validate_fields


class ItemContractTests(unittest.TestCase):
    def test_product_contract_retains_ambiguity_separately(self):
        value = validate_fields({"kind": "DOCUMENT_REQUEST", "title": "Weekly report", "due_text": "Monday"})
        self.assertEqual(SCHEMA, "fyp-project-item-v1")
        self.assertEqual(value["due"], "")
        self.assertEqual(value["owner"], "")
        self.assertEqual(value["due_text"], "Monday")

    def test_due_requires_date_or_known_zone_and_fields_allowlisted(self):
        for invalid in ["Monday", "2026-02-30", "2026-10-11T08:00:00"]:
            with self.assertRaises(ValueError):
                validate_fields({"title": "Task", "due": invalid})
        for value in [{"title": ""}, {"title": "Task", "schema_version": "fyp-direct-label-v1.1"}]:
            with self.assertRaises(ValueError):
                validate_fields(value)
        self.assertEqual(validate_fields({"due": "2026-10-11"}, partial=True), {"due": "2026-10-11"})

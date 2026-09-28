"""Focused checks for validation error categorization."""

import unittest

from scripts.audit_silver_validation_errors import category


class SilverValidationErrorAuditTests(unittest.TestCase):
    def test_empty_prediction_has_its_own_category(self):
        self.assertEqual(category({"NON_PROJECT"}, set()), "empty_prediction")
        self.assertEqual(category({"MEETING"}, set()), "empty_prediction")

    def test_project_scope_confusions(self):
        self.assertEqual(
            category({"NON_PROJECT"}, {"MEETING"}),
            "spurious_project_on_negative",
        )
        self.assertEqual(
            category({"MEETING"}, {"NON_PROJECT"}),
            "missed_project_as_negative",
        )

    def test_project_label_mismatch(self):
        self.assertEqual(
            category({"MEETING", "DEADLINE"}, {"MEETING"}),
            "project_label_mismatch",
        )


if __name__ == "__main__":
    unittest.main()

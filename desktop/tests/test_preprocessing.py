import unittest
from desktop.local_product.preprocessing import split_authored_text
from desktop.local_product.adapters import EmlAdapter
from desktop.local_product.classification import rule_baseline
from desktop.local_product.extraction import extract_rule_suggestions


class PreprocessingTests(unittest.TestCase):
    def test_quote_only_and_forward_only_have_no_authored_evidence(self):
        for body in ("> Please approve by Friday.", "-----Original Message-----\nPlease approve by Friday."):
            current, quoted = split_authored_text(body)
            self.assertEqual(current, "")
            self.assertTrue(quoted)
            record = EmlAdapter.parse_bytes(("Subject: Project\n\n" + body).encode())
            self.assertEqual(rule_baseline(record).status, "ABSTAIN")
            self.assertEqual(extract_rule_suggestions(record)["status"], "ABSTAIN")

    def test_outlook_header_block_does_not_cut_preceding_authored_lines(self):
        body = "Hello,\nPlease update the plan.\n\nFrom: prior@example.test\nSent: Monday\nTo: team@example.test\nSubject: Old project\nPlease approve."
        current, quoted = split_authored_text(body)
        self.assertEqual(current, "Hello,\nPlease update the plan.")
        self.assertTrue(quoted.startswith("From:"))
        self.assertNotIn("approve", current)


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from desktop.local_product.preprocessing import (
    segment_authored_text_v1,
    split_authored_text,
)


class InlineIntegrityTests(unittest.TestCase):
    def test_on_wrote_header_allows_reply_after_marked_quote(self):
        body = (
            "On Monday Alice wrote:\n"
            "> Can we submit Friday?\n"
            "No, please use Monday."
        )

        current, quoted = split_authored_text(body)
        segmentation = segment_authored_text_v1(body)

        self.assertEqual(current, "No, please use Monday.")
        self.assertEqual(
            quoted,
            "On Monday Alice wrote:\n> Can we submit Friday?",
        )
        self.assertFalse(segmentation["uncertain"])
        authored_text = "".join(
            body[item["start"] : item["end"]]
            for item in segmentation["authored_ranges"]
        )
        self.assertEqual(authored_text, "No, please use Monday.")

    def test_on_wrote_marked_quotes_can_interleave_with_multiple_replies(self):
        body = (
            "On Monday Alice wrote:\n"
            "> Can we submit Friday?\n"
            "No, please use Monday.\n"
            "> Should I update the tracker too?\n"
            "Yes, please update it."
        )

        current, quoted = split_authored_text(body)

        self.assertEqual(current, "No, please use Monday.\nYes, please update it.")
        self.assertEqual(
            quoted,
            "On Monday Alice wrote:\n"
            "> Can we submit Friday?\n"
            "> Should I update the tracker too?",
        )

    def test_bare_on_wrote_unmarked_tail_stays_uncertain(self):
        body = "On Monday Alice wrote:\nCan we submit Friday?"

        current, quoted = split_authored_text(body)
        segmentation = segment_authored_text_v1(body)

        self.assertEqual(current, "")
        self.assertEqual(quoted, body)
        self.assertTrue(segmentation["uncertain"])
        self.assertFalse(segmentation["authored_ranges"])

    def test_unmarked_replies_between_quote_lines_remain_current(self):
        body = (
            "Please review the schedule.\n"
            "> Can we move the deadline to Friday?\n"
            "Friday will not work; please use Monday instead.\n"
            "> Should I update the calendar too?\n"
            "Yes, please update the calendar."
        )

        current, quoted = split_authored_text(body)

        self.assertEqual(
            current,
            "Please review the schedule.\n"
            "Friday will not work; please use Monday instead.\n"
            "Yes, please update the calendar.",
        )
        self.assertEqual(
            quoted,
            "> Can we move the deadline to Friday?\n"
            "> Should I update the calendar too?",
        )

    def test_original_message_unmarked_tail_is_uncertain_not_authored(self):
        body = (
            "Thanks, I saw this.\r\n"
            "-----Original Message-----\r\n"
            "From: prior@example.test\r\n"
            "Sent: Monday\r\n"
            "To: team@example.test\r\n"
            "Subject: Old project\r\n"
            "Please approve the old plan.\r\n"
            "--\r\n"
            "Prior sender"
        )

        current, quoted = split_authored_text(body)
        segmentation = segment_authored_text_v1(body)

        self.assertEqual(current, "Thanks, I saw this.")
        self.assertTrue(quoted.startswith("-----Original Message-----"))
        self.assertIn("Please approve the old plan.", quoted)
        self.assertTrue(segmentation["uncertain"])
        self.assertTrue(segmentation["uncertain_ranges"])
        self.assertTrue(segmentation["signature_ranges"])
        self.assertFalse(
            any(
                "Please approve" in body[item["start"] : item["end"]]
                for item in segmentation["authored_ranges"]
            )
        )

    def test_raw_ranges_are_exact_disjoint_and_json_safe(self):
        body = "A🙂\r\n> quoted\r\nreply\r\n--\r\nsignature"
        segmentation = segment_authored_text_v1(body)

        self.assertEqual(segmentation["version"], "authored-segmentation-v1")
        self.assertEqual(segmentation["offset_unit"], "python_string_index")
        self.assertEqual(segmentation["raw_length"], len(body))
        json.dumps(segmentation)

        covered = [None] * len(body)
        for kind in ("authored", "quoted", "uncertain", "signature"):
            for item in segmentation[f"{kind}_ranges"]:
                start, end = item["start"], item["end"]
                self.assertLess(start, end)
                for offset in range(start, end):
                    self.assertIsNone(covered[offset])
                    covered[offset] = kind

        self.assertTrue(all(kind is not None for kind in covered))
        raw_text = {
            kind: "".join(
                body[item["start"] : item["end"]]
                for item in segmentation[f"{kind}_ranges"]
            )
            for kind in ("authored", "quoted", "uncertain", "signature")
        }
        self.assertEqual(raw_text["authored"], "A🙂\r\nreply\r\n")
        self.assertEqual(raw_text["quoted"], "> quoted\r\n")
        self.assertEqual(raw_text["uncertain"], "")
        self.assertEqual(raw_text["signature"], "--\r\nsignature")
        self.assertEqual(covered[0], "authored")
        self.assertEqual(covered[4], "quoted")
        self.assertEqual(covered[14], "authored")
        self.assertEqual(covered[21], "signature")


if __name__ == "__main__":
    unittest.main()

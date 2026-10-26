"""Regression cases grounded in the ten rejected story source pages."""

import json
from pathlib import Path
import unittest

from radar.summary_validation import claim_error, entity_error, number_error


CASES = json.loads((Path(__file__).parent / "fixtures" / "summary-rejections" /
                    "cases.json").read_text(encoding="utf-8"))


class RejectedSummaryCases(unittest.TestCase):
    def test_source_backed_claims_and_real_inventions(self):
        self.assertEqual(len(CASES), 10)
        self.assertEqual(sum(case["verdict"] == "true" for case in CASES), 2)
        for case in CASES:
            with self.subTest(story=case["id"]):
                error = claim_error({"text": case["claim"], "evidence_refs": ["p"]},
                                    {"p": case["evidence"]}, {"p"}, max_length=520)
                if case["verdict"] == "false":
                    self.assertIsNone(error)
                else:
                    self.assertEqual(error, case["reason"])

    def test_diacritic_insensitive_evidence_and_unlisted_vietnamese_syllables(self):
        self.assertIsNone(entity_error("Đà Nẵng công bố công cụ mới.", "Da Nang announced a new tool."))
        self.assertIsNone(entity_error("Doanh nghiệp Giao dịch tại Trung Quốc.", "Chinese firms trade online."))
        self.assertIsNone(entity_error("AI2 ra mắt công cụ.", "Ai2 released a tool."))
        self.assertIsNone(entity_error("Café công bố công cụ.", "Cafe released a tool."))
        self.assertEqual(entity_error("Joe công bố công cụ.", "The company released a tool."),
                         "invented_entity: Joe")
        self.assertEqual(entity_error("Hoa Kỳ công bố công cụ.", "The company released a tool."),
                         "unsupported_name: Hoa Kỳ")
        self.assertEqual(entity_error("Sydney Von Atlas công bố công cụ.",
                                      "Sydney Von Arx worked with Atlas."),
                         "unsupported_name: Sydney Von Atlas")

    def test_percent_range_does_not_license_unrelated_percent(self):
        source = "The cost fell by 40 to 50%."
        self.assertIsNone(number_error("Chi phí giảm 50 phần trăm.", source))
        self.assertEqual(number_error("Chi phí giảm 60 phần trăm.", source),
                         "invented_number: 60")


if __name__ == "__main__":
    unittest.main()

"""Regression cases grounded in rejected story source pages."""

import json
from pathlib import Path
import unittest

from radar.summary_validation import claim_error, entity_error, number_error, validate_summary


CASES = json.loads((Path(__file__).parent / "fixtures" / "summary-rejections" /
                    "cases.json").read_text(encoding="utf-8"))


class RejectedSummaryCases(unittest.TestCase):
    def test_source_backed_claims_and_real_inventions(self):
        self.assertEqual(len(CASES), 27)
        for case in CASES:
            with self.subTest(story=case["id"], reason=case["reason"]):
                if case.get("check") == "partial_flag":
                    error = self.partial_flag_error(case)
                else:
                    entity_evidence = " ".join([case["evidence"], *case.get("article_paragraphs", [])])
                    error = claim_error({"text": case["claim"],
                                         "evidence_refs": case.get("evidence_refs", ["p"])},
                                        {"p": case["evidence"]}, {"p"}, max_length=520,
                                        entity_evidence=entity_evidence,
                                        publication_years=case.get("publication_years", ()))
                if case["verdict"] == "false":
                    self.assertIsNone(error)
                else:
                    self.assertEqual(error, case["reason"])

    def partial_flag_error(self, case):
        claim = lambda text: {"text": text, "evidence_refs": ["p"]}
        output = {"id": case["id"], "status": "ready", "title_vi": claim(case["claim"]),
                  "key_points": [claim(text) for text in (
                      "Anthropic công bố kế hoạch niêm yết cổ phiếu trên Nasdaq.",
                      "Công ty dự định sử dụng mã chứng khoán ANT trên Nasdaq.",
                      "Cổ phiếu hạng A của Anthropic được đề xuất niêm yết.",
                      "Kế hoạch đưa cổ phiếu Anthropic lên Nasdaq được công bố.")],
                  "used_source_ids": ["outlet"], "limitations": []}
        inputs = {"id": case["id"], "sources": [{"id": "outlet", "role": "outlet",
                  "paragraphs": [{"id": "p", "text": case["evidence"]}],
                  "publisher": {"id": "publisher", "text": "Anthropic"}, "body_complete": False}]}
        return validate_summary(inputs, output)[1]

    def test_diacritic_insensitive_evidence_and_unlisted_vietnamese_syllables(self):
        self.assertIsNone(entity_error("Đà Nẵng công bố công cụ mới.", "Da Nang announced a new tool."))
        self.assertIsNone(entity_error("Doanh nghiệp Giao dịch tại Trung Quốc.", "Chinese firms trade online."))
        self.assertIsNone(entity_error("AI2 ra mắt công cụ.", "Ai2 released a tool."))
        self.assertIsNone(entity_error("Café công bố công cụ.", "Cafe released a tool."))
        self.assertEqual(entity_error("Joe công bố công cụ.", "The company released a tool."),
                         "invented_entity: Joe")
        self.assertEqual(entity_error("Hoa Kỳ công bố công cụ.", "The company released a tool."),
                         "unsupported_name: Hoa Kỳ")
        self.assertIsNone(entity_error("Hoa Kỳ công bố công cụ.", "US officials released a tool."))
        self.assertEqual(entity_error("Hoa Kỳ công bố công cụ.", "The company told us about it."),
                         "unsupported_name: Hoa Kỳ")
        self.assertIsNone(entity_error("Allen Institute for AI phát triển LitPivot.",
                                       "Ai2 developed LitPivot."))
        self.assertEqual(entity_error("Donald Trump công bố công cụ.", "Biden discussed the plan."),
                         "invented_entity: Donald")
        self.assertEqual(entity_error("Elon Gates công bố công cụ.", "Musk discussed the plan."),
                         "invented_entity: Elon")
        self.assertEqual(entity_error("Viện Allen công bố công cụ.", "Another institute released a tool."),
                         "invented_entity: Allen")
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

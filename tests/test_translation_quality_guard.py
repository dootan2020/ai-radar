"""Unit tests proving that garbled translations never reach reader-facing output."""

import json
from pathlib import Path
import unittest

from radar import translate as nllb
from radar.translation_pipeline import validated, protected_names, translate_payload
from radar import translation_gemini as gemini


class TranslationQualityGuardTests(unittest.TestCase):
    def test_glossary_repairs_key_technical_terms(self):
        cases = [
            ("Fired OpenAI safety researchers dispute misconduct claims, warn of chilling effect",
             "Các nhà nghiên cứu an toàn OpenAI bị sa thải tranh chấp các tuyên bố về hành vi sai trái, cảnh báo về tác động làm lạnh",
             "Các nhà nghiên cứu an toàn OpenAI bị sa thải tranh chấp các tuyên bố về hành vi sai trái, cảnh báo về hiệu ứng răn đe"),
            ("T-Head unveils Zhenwu V900 AI chip in Alibaba’s push to expand its AI infrastructure stack",
             "T-Head tiết lộ chip AI Zhenwu V900 trong nỗ lực của Alibaba để mở rộng bộ sưu tập cơ sở hạ tầng AI của mình",
             "T-Head tiết lộ chip AI Zhenwu V900 trong nỗ lực của Alibaba để mở rộng ngăn xếp cơ sở hạ tầng AI của mình"),
            ("The Race for AI Supremacy Raises Safety Concerns",
             "Cuộc chạy đua cho sự cao cấp của AI làm dấy lên mối quan tâm về an toàn",
             "Cuộc chạy đua cho vị thế thống trị AI làm dấy lên mối quan tâm về an toàn"),
            ("LivSyn Robotics raises Series A funding for platform connecting robots with AI models",
             "LivSyn Robotics tăng quỹ Series A cho nền tảng kết nối robot với các mô hình AI",
             "LivSyn Robotics gọi vốn Series A cho nền tảng kết nối robot với các mô hình AI"),
        ]
        for src, before, expected in cases:
            with self.subTest(source=src):
                prot = protected_names(src, nllb.CATALOG_NAMES)
                repaired = nllb.apply_glossary(src, before, protected_names=prot)
                self.assertEqual(repaired, expected)
                val = validated(src, before, prot)
                self.assertEqual(val, expected)

    def test_quoted_blunders_are_rejected_and_fall_back_to_english(self):
        """The 4 blunders explicitly quoted by the captain and red-team must NEVER reach reader output."""
        blunder_cases = [
            ("Validate GPU Cluster Readiness Before AI Workloads Land",
             "Thiết lập sẵn sàng của GPU trước khi AI tải trọng làm việc hạ cánh"),
            ("Fired OpenAI safety researchers dispute misconduct claims, warn of chilling effect",
             "Cảnh báo về tác động làm lạnh"),  # without valid glossary repair or raw garbled
            ("Rogue Anthropic AI agent gave police fake tip in unsolved murder case",
             "Một agent AI của Rogue Anthropic đã đưa báo cáo giả cho cảnh sát trong vụ giết người chưa được giải quyết."),
            ("AI Is Throwing a Roadside Picnic",
             "AI đang tổ chức một buổi dã ngoại bên đường"),
            ("Striding AI Unveils H1 and C1 Robots for 24/7 Convenience Stores, Targets 2027 Service Launch",
             "AI tiến bộ tiết lộ H1 và C1 Robot cho cửa hàng tiện nghi 24/7, mục tiêu 2027 Thỏa thuận dịch vụ"),
            ("AI Is Getting Really Good at Messing With Cybercriminals",
             "AI đang trở nên rất giỏi trong việc giao tiếp với tội phạm mạng"),
            ("If AI is conscient, then we are making slaves",
             "Nếu AI có lương tâm, thì chúng ta đang làm nô lệ."),
            ("Super Micro Case ‘Fixer’ Pleads Guilty to Diverting AI Tech",
             "'Fixer' trong vụ Super Micro nhận tội chuyển hướng công nghệ AI"),
        ]
        banned_phrases = [
            "tác động làm lạnh",
            "tải trọng làm việc hạ cánh",
            "tải trọng làm việc",
            "của Rogue Anthropic",
            "dã ngoại bên đường",
            "cửa hàng tiện nghi",
            "giao tiếp với tội phạm mạng",
            "chúng ta đang làm nô lệ",
            "chuyển hướng công nghệ",
        ]
        for src, bad_vi in blunder_cases:
            with self.subTest(source=src):
                prot = protected_names(src, nllb.CATALOG_NAMES)
                val = validated(src, bad_vi, prot)
                # Must be rejected (None)
                self.assertIsNone(val, f"Bad translation should be rejected for: {src}")

                # Reader-facing logic: if validated is None, title_vi is not set and reader gets original English
                reader_title = val if val else src
                for banned in banned_phrases:
                    self.assertNotIn(banned, reader_title,
                                     f"Reader-facing title must not contain banned phrase '{banned}'")

    def test_pipeline_integration_drops_garbled_translations_and_keeps_english(self):
        """Simulate a full payload run with garbled inputs in previous snapshot;
        verify that stories keep original English title and banned text never reaches payload."""
        stories = [
            {"id": "s1", "title": "Validate GPU Cluster Readiness Before AI Workloads Land",
             "title_vi": "Thiết lập sẵn sàng của GPU trước khi AI tải trọng làm việc hạ cánh",
             "kind": "news", "coverage": []},
            {"id": "s2", "title": "Rogue Anthropic AI agent gave police fake tip in unsolved murder case",
             "title_vi": "Một agent AI của Rogue Anthropic đã đưa báo cáo giả cho cảnh sát trong vụ giết người chưa được giải quyết.",
             "kind": "news", "coverage": []},
            {"id": "s3", "title": "AI Is Throwing a Roadside Picnic",
             "title_vi": "AI đang tổ chức một buổi dã ngoại bên đường",
             "kind": "news", "coverage": []},
            {"id": "s4", "title": "The Race for AI Supremacy Raises Safety Concerns",
             "title_vi": "Cuộc chạy đua cho sự cao cấp của AI làm dấy lên mối quan tâm về an toàn",
             "kind": "news", "coverage": []},
        ]
        payload = {"stories": stories, "sources": []}

        # Run pipeline offline without external provider (uses previous translations if valid)
        stats, alive = translate_payload(
            payload,
            nllb_cache={},
            gemini_cache={},
            config=gemini.Config(api_key="offline", confirmed=True),
            transport=lambda *args: {"candidates": []},
            factory=lambda: (_ for _ in ()).throw(ModuleNotFoundError("offline")),
            previous={"stories": stories}
        )

        banned_phrases = [
            "tác động làm lạnh",
            "tải trọng làm việc hạ cánh",
            "tải trọng làm việc",
            "của Rogue Anthropic",
            "dã ngoại bên đường",
        ]

        # s1, s2, s3 had garbled translations -> must be rejected, keeping English title
        self.assertNotIn("title_vi", payload["stories"][0])
        self.assertNotIn("title_vi", payload["stories"][1])
        self.assertNotIn("title_vi", payload["stories"][2])

        # s4 had repairable glossary term -> repaired into faithful Vietnamese
        self.assertEqual(payload["stories"][3].get("title_vi"),
                         "Cuộc chạy đua cho vị thế thống trị AI làm dấy lên mối quan tâm về an toàn")

        # Verify no banned phrases exist in any reader-visible title
        for s in payload["stories"]:
            visible = s.get("title_vi") or s.get("title")
            for banned in banned_phrases:
                self.assertNotIn(banned, visible)


if __name__ == "__main__":
    unittest.main()

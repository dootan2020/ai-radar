"""Unit tests proving general quality guards and glossary terminology rules."""

import json
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
            ("Validate GPU Cluster Readiness Before AI Workloads Land",
             "Kiểm tra mức độ sẵn sàng của cụm GPU trước khi tải trọng làm việc của AI triển khai",
             "Kiểm tra mức độ sẵn sàng của cụm GPU trước khi khối lượng công việc của AI triển khai"),
        ]
        for src, before, expected in cases:
            with self.subTest(source=src):
                prot = protected_names(src, nllb.CATALOG_NAMES)
                repaired = nllb.apply_glossary(src, before, protected_names=prot)
                self.assertEqual(repaired, expected)
                val = validated(src, before, prot)
                self.assertEqual(val, expected)

    def test_general_quality_guards_reject_bad_translations(self):
        """General quality rules reject lost names, lost numbers, untranslated English, and repetitions."""
        cases = [
            # Name lost (AI brand protection)
            ("Striding AI Unveils H1 and C1 Robots for Convenience Stores",
             "AI tiến bộ tiết lộ Robot H1 và C1 cho các cửa hàng",
             "name lost"),
            # Number lost
            ("OpenAI releases 4 new frontier models for research",
             "OpenAI phát hành các mô hình tiên phong mới cho nghiên cứu",
             "number lost"),
            # Number added
            ("Google announces breakthrough in quantum computing",
             "Google công bố 99 bước đột phá trong điện toán lượng tử",
             "number added"),
            # Model returned English (untranslated)
            ("DeepMind publishes new research paper on transformers",
             "DeepMind publishes new research paper on transformers",
             "untranslated"),
            # Repetition
            ("Anthropic scales reasoning capabilities",
             "Anthropic mở rộng khả năng khả năng suy luận suy luận",
             "repetition"),
            # Content dropped (too short)
            ("Comprehensive study on safety alignment benchmarks across major commercial foundation models",
             "Nghiên cứu",
             "too short"),
        ]
        for src, bad_vi, reason_prefix in cases:
            with self.subTest(source=src, reason=reason_prefix):
                prot = protected_names(src, nllb.CATALOG_NAMES)
                rej = nllb.rejection(src, bad_vi, protected_names=prot)
                self.assertIsNotNone(rej)
                self.assertTrue(rej.startswith(reason_prefix), f"Expected reason starting with '{reason_prefix}', got '{rej}'")
                self.assertIsNone(validated(src, bad_vi, prot))

    def test_pipeline_integration_preserves_proper_names_and_validates(self):
        """Pipeline keeps original English title when proper name is lost, and keeps valid glossary translations."""
        stories = [
            {"id": "s1", "title": "Striding AI Unveils H1 and C1 Robots for 24/7 Stores",
             "title_vi": "AI tiến bộ ra mắt robot H1 và C1 cho cửa hàng 24/7",
             "kind": "news", "coverage": []},
            {"id": "s2", "title": "The Race for AI Supremacy Raises Safety Concerns",
             "title_vi": "Cuộc chạy đua cho sự cao cấp của AI làm dấy lên mối quan tâm về an toàn",
             "kind": "news", "coverage": []},
        ]
        payload = {"stories": stories, "sources": []}

        # Offline payload translation without external provider
        stats, alive = translate_payload(
            payload,
            nllb_cache={},
            gemini_cache={},
            config=gemini.Config(api_key="offline", confirmed=True),
            transport=lambda *args: {"candidates": []},
            factory=lambda: (_ for _ in ()).throw(ModuleNotFoundError("offline")),
            previous={"stories": stories}
        )

        # s1 lost protected brand name "Striding AI" -> rejected, keeping original English
        self.assertNotIn("title_vi", payload["stories"][0])
        self.assertEqual(payload["stories"][0]["title"], "Striding AI Unveils H1 and C1 Robots for 24/7 Stores")

        # s2 has repairable technical term -> repaired to faithful Vietnamese
        self.assertEqual(payload["stories"][1].get("title_vi"),
                         "Cuộc chạy đua cho vị thế thống trị AI làm dấy lên mối quan tâm về an toàn")


if __name__ == "__main__":
    unittest.main()

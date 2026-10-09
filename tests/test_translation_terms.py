"""Offline regression and fixed-sample checks for AI terminology corrections."""

import json
from pathlib import Path
import re
import unittest

from radar import translate
from radar.translation_pipeline import validated

FIXTURE = Path(__file__).parent / "fixtures" / "translation-terms-live.json"
WRONG_TERMS = {
    "open weights": re.compile(r"đánh nặng|mở trọng số|trọng lượng mở|mở cân nặng", re.I),
    "denoising": re.compile(r"chỉ trích|phê phán|phê bình", re.I),
    "checkpoint": re.compile(r"điểm kiểm tra", re.I),
    "fine-tuning": re.compile(r"điều chỉnh tinh tế|điều chỉnh tốt", re.I),
    "inference": re.compile(r"suy diễn|việc định nghĩa", re.I),
    "token": re.compile(r"mã thông báo|\bthẻ\b", re.I),
    "benchmark": re.compile(r"điểm chuẩn|tiêu chuẩn đánh giá|băng ghế dự bị", re.I),
    "agent": re.compile(r"đại lý|nhân viên|đặc vụ|tác nhân|(?<!đa )tác tử", re.I),
    "agentic": re.compile(r"(?<!đa )(?:hình dạng |dạng |bằng )?tác tử", re.I),
}
SOURCE_TERMS = {
    "open weights": re.compile(r"open[- ]weights?", re.I),
    "denoising": re.compile(r"denois(?:e|es|ed|ing)", re.I),
    "checkpoint": re.compile(r"checkpoints?", re.I),
    "fine-tuning": re.compile(r"fine[- ]tun(?:e|ed|ing)", re.I),
    "inference": re.compile(r"inference", re.I),
    "token": re.compile(r"tokens?", re.I),
    "benchmark": re.compile(r"benchmarks?", re.I),
    "agent": re.compile(r"\bagents?\b", re.I),
    "agentic": re.compile(r"\bagentic\b", re.I),
}


def errors(rows, translated_key):
    count = 0
    for row in rows:
        text = row[translated_key]
        for term, source_pattern in SOURCE_TERMS.items():
            if source_pattern.search(row["title"]) and WRONG_TERMS[term].search(text):
                count += 1
    return count


class TranslationTermsTests(unittest.TestCase):
    def test_shared_glossary_repairs_both_reported_translation_failures(self):
        cases = (
            ("Meet Qwen-Image-2.1-Turbo — create and edit images in just 8 denoising steps! Open weights now available!",
             "Qwen-Image-2.1-Turbo: Tạo và chỉnh sửa hình ảnh chỉ trích trong 8 bước. Đánh nặng mở sẵn rồi!",
             "Qwen-Image-2.1-Turbo: Tạo và chỉnh sửa hình ảnh khử nhiễu trong 8 bước. Trọng số mở sẵn rồi!"),
            ("8 denoising steps", "8 bước chỉ trích", "8 bước khử nhiễu"),
            ("Open weights now available", "Đánh nặng mở sẵn rồi", "Trọng số mở sẵn rồi"),
            ("Model checkpoint released", "Điểm kiểm tra mô hình đã phát hành", "Checkpoint mô hình đã phát hành"),
        )
        for source, before, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(translate.apply_glossary(source, before), expected)
                # Gemini validation and NLLB composition both call this shared glossary.
                self.assertEqual(validated(source, before, set()), expected)

    def test_agentic_terms_are_kept_in_english_without_changing_multi_agent(self):
        cases = (
            ("Google brings agentic AI to Gemini, starting with businesses",
             "Google đưa AI tác tử lên Gemini", "Google đưa AI agentic lên Gemini"),
            ("Citrini Says Agentic Finance Fosters a New Paradigm",
             "Citrini nhận định Tài chính Tác tử thúc đẩy mô hình mới",
             "Citrini nhận định Tài chính Agentic thúc đẩy mô hình mới"),
            ("SuperNav: An Agentic Navigation System for Any Task in Any Scene",
             "SuperNav: Hệ thống điều hướng bằng tác tử cho mọi tác vụ",
             "SuperNav: Hệ thống điều hướng agentic cho mọi tác vụ"),
            ("Anthropic: Agentic loops invoking multiagent orchestration",
             "Anthropic: Các vòng lặp tác tử kích hoạt điều phối đa tác tử",
             "Anthropic: Các vòng lặp agentic kích hoạt điều phối đa tác tử"),
        )
        for source, before, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(translate.apply_glossary(source, before), expected)

    def test_fixed_live_sample_has_at_least_sixty_titles_and_reduces_errors(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        titles = fixture["titles"]
        self.assertGreaterEqual(len(titles), 60)
        self.assertEqual(len({row["title"] for row in titles}), len(titles))
        before = errors(titles, "title_vi")
        after_rows = [dict(row, after=translate.apply_glossary(row["title"], row["title_vi"])) for row in titles]
        after = errors(after_rows, "after")
        self.assertEqual((before, after), (27, 0))


if __name__ == "__main__":
    unittest.main()

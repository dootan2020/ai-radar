"""Synthetic offline regressions for multilingual identity and measured reasons."""

import unicodedata
import unittest

from radar.clustering import _tokens, canonical_url, cluster_items
from radar.ranking import rank_stories

if __package__:
    from .test_v2_support import NOW, coverage
else:
    from test_v2_support import NOW, coverage


class UnicodeClusteringTests(unittest.TestCase):
    title = "Nghiên cứu trí tuệ nhân tạo mới"

    def pair(self, second_title=None, **changes):
        return [coverage(title=self.title),
                coverage("b", "https://press.example/second",
                         title=second_title or self.title, **changes)]

    def test_accented_words_stay_whole_without_ascii_fragments(self):
        self.assertEqual(_tokens(self.title), {"nghiên", "cứu", "trí", "tuệ", "nhân", "tạo", "mới"})
        self.assertIn("đột", _tokens("Đột phá nghiên cứu"))

    def test_vietnamese_cross_url_titles_merge_in_both_unicode_encodings(self):
        for title in [self.title.upper(), unicodedata.normalize("NFD", self.title)]:
            with self.subTest(title=title):
                stories = cluster_items(self.pair(title), NOW)
                self.assertEqual(len(stories), 1)
                self.assertEqual(len(stories[0]["coverage"]), 2)

    def test_short_generic_vietnamese_titles_remain_separate(self):
        self.assertEqual(len(cluster_items([
            coverage(title="Tin mới"), coverage("b", "https://press.example/b", title="Tin mới")], NOW)), 2)

    def test_vietnamese_cross_url_dates_still_need_known_recent_publication(self):
        for timestamp in [None, "2026-09-30T10:59:59Z"]:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(len(cluster_items(self.pair(published_at=timestamp), NOW)), 2)

    def test_unicode_titles_keep_conflicting_numeric_versions_separate(self):
        items = [coverage(title=self.title + " Orion-5.1"),
                 coverage("b", "https://press.example/b", title=self.title + " Orion-5.2")]
        self.assertEqual(len(cluster_items(items, NOW)), 2)
        self.assertIn("orion-5.1", _tokens(items[0]["title"]))

    def test_accents_and_unrelated_meanings_are_not_collapsed(self):
        self.assertNotEqual(_tokens("cứu"), _tokens("cửu"))
        self.assertEqual(len(cluster_items(self.pair("Nghiên cứu phát triển robot công nghiệp"), NOW)), 2)


class ArxivHtmlIdentityTests(unittest.TestCase):
    def test_html_abs_and_pdf_normalize_for_same_paper_version(self):
        expected = "https://arxiv.org/abs/2610.12345v2"
        for host in ["arxiv.org", "www.arxiv.org", "export.arxiv.org"]:
            with self.subTest(host=host):
                self.assertEqual(canonical_url(f"https://{host}/html/2610.12345v2?utm_source=x#section"), expected)
        items = [coverage(url="https://arxiv.org/html/2610.12345v2", title="One title"),
                 coverage("b", "https://arxiv.org/pdf/2610.12345v2.pdf", title="Different headline")]
        self.assertEqual(len(cluster_items(items, NOW)), 1)

    def test_html_version_never_merges_with_different_or_unspecified_version(self):
        for version in ["v3", ""]:
            with self.subTest(version=version):
                items = [coverage(url="https://arxiv.org/html/2610.12345v2"),
                         coverage("b", "https://arxiv.org/abs/2610.12345" + version)]
                self.assertEqual(len(cluster_items(items, NOW)), 2)


class ReadableHotReasonTests(unittest.TestCase):
    def test_measurements_keep_exact_values_without_exponential_notation(self):
        for value, expected in [(1000000, "1.000.000"), (1000000.0, "1.000.000"),
                                (1234567.25, "1.234.567,25"), (0.000001, "0,000001"), (0, "0")]:
            with self.subTest(value=value):
                items = [coverage("hf", "https://hf.example/a", title="Article one",
                                  metrics={"trending_score": value}),
                         coverage("hf", "https://hf.example/b", title="Article two",
                                  metrics={"trending_score": 2})]
                stories = rank_stories(cluster_items(items, NOW), NOW)
                story = next(row for row in stories if row["url"].endswith("/a"))
                self.assertIn(f"hf: {expected} điểm thịnh hành", story["hot_reason"])
                self.assertEqual(story["hot_signals"]["measurement"]["value"], value)

"""Unit tests for worth scoring, score parts, first-hand detection, and why-line."""

from datetime import datetime, timezone, timedelta
import unittest

from radar.worth import (
    WORTH,
    calculate_worth,
    first_hand_of,
    fmt_vi,
    fmt_speed_vi,
    measure_of,
    uniq_coverage,
    worth_why_line,
    annotate_story_worth,
)

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


class WorthScorePartsTests(unittest.TestCase):
    def test_unmeasured_story_has_only_freshness_part_and_no_invented_attention_or_breadth(self):
        story = {
            "id": "story-1",
            "published_at": "2026-10-04T12:00:00Z",
            "source_count": 1,
            "coverage": [{"source": "press-a", "publisher": "press-a", "metrics": {}}],
            "hot_score": None,
            "hot_signals": {"measurement": None},
        }
        res = calculate_worth(story, NOW)
        # Freshness is 15 at age 0
        self.assertAlmostEqual(res["parts"]["freshness"], 15.0, places=1)
        # No invented attention or breadth
        self.assertNotIn("attention", res["parts"])
        self.assertNotIn("breadth", res["parts"])
        self.assertAlmostEqual(res["score"], 15.0, places=1)
        self.assertFalse(res["evidence"])

    def test_attention_part_scales_to_maximum_at_full_threshold(self):
        story_mid = {
            "id": "story-2",
            "published_at": "2026-10-04T12:00:00Z",
            "source_count": 1,
            "coverage": [{"source": "hn-front", "publisher": "hacker-news", "metrics": {"points": 100}}],
            "hot_score": 30.0,  # 30 / 60 * 35 = 17.5
            "hot_signals": {"measurement": {"source": "hn-front", "metric": "points", "value": 100}},
        }
        res_mid = calculate_worth(story_mid, NOW)
        self.assertIn("attention", res_mid["parts"])
        self.assertAlmostEqual(res_mid["parts"]["attention"], 17.5, places=1)

        story_max = {
            "id": "story-3",
            "published_at": "2026-10-04T12:00:00Z",
            "source_count": 1,
            "coverage": [{"source": "hn-front", "publisher": "hacker-news", "metrics": {"points": 300}}],
            "hot_score": 60.0,  # full at 60 -> 35.0
            "hot_signals": {"measurement": {"source": "hn-front", "metric": "points", "value": 300}},
        }
        res_max = calculate_worth(story_max, NOW)
        self.assertAlmostEqual(res_max["parts"]["attention"], 35.0, places=1)

        # Capped beyond full threshold
        story_over = dict(story_max, hot_score=90.0)
        res_over = calculate_worth(story_over, NOW)
        self.assertAlmostEqual(res_over["parts"]["attention"], 35.0, places=1)

    def test_breadth_part_scales_with_independent_publishers(self):
        # 2 publishers: (2 - 1) / (4 - 1) * 35 = 11.67
        story_2 = {
            "id": "story-b2",
            "published_at": "2026-10-04T12:00:00Z",
            "source_count": 2,
            "coverage": [
                {"source": "src-1", "publisher": "pub-1", "metrics": {}},
                {"source": "src-2", "publisher": "pub-2", "metrics": {}},
            ],
            "hot_score": None,
            "hot_signals": {"measurement": None},
        }
        res_2 = calculate_worth(story_2, NOW)
        self.assertIn("breadth", res_2["parts"])
        self.assertAlmostEqual(res_2["parts"]["breadth"], 11.67, places=2)

        # 4 publishers: full 35.0
        story_4 = {
            "id": "story-b4",
            "published_at": "2026-10-04T12:00:00Z",
            "source_count": 4,
            "coverage": [
                {"source": f"src-{i}", "publisher": f"pub-{i}", "metrics": {}}
                for i in range(4)
            ],
            "hot_score": None,
            "hot_signals": {"measurement": None},
        }
        res_4 = calculate_worth(story_4, NOW)
        self.assertAlmostEqual(res_4["parts"]["breadth"], 35.0, places=1)

    def test_freshness_halves_every_24_hours(self):
        story_24h = {
            "id": "story-f24",
            "published_at": "2026-10-03T12:00:00Z",
            "source_count": 1,
            "coverage": [{"source": "src-1", "publisher": "pub-1", "metrics": {}}],
            "hot_score": None,
            "hot_signals": {"measurement": None},
        }
        res_24h = calculate_worth(story_24h, NOW)
        self.assertAlmostEqual(res_24h["parts"]["freshness"], 7.5, places=1)

        story_48h = dict(story_24h, published_at="2026-10-02T12:00:00Z")
        res_48h = calculate_worth(story_48h, NOW)
        self.assertAlmostEqual(res_48h["parts"]["freshness"], 3.75, places=2)

    def test_first_hand_multiplier_scales_all_parts(self):
        story_fh = {
            "id": "story-fh",
            "published_at": "2026-10-04T12:00:00Z",
            "source_count": 1,
            "coverage": [{"source": "openai-news", "publisher": "openai", "lab": "openai", "metrics": {}}],
            "hot_score": None,
            "hot_signals": {"measurement": None},
        }
        res = calculate_worth(story_fh, NOW)
        # Freshness 15.0 * 1.3 = 19.5
        self.assertAlmostEqual(res["score"], 19.5, places=1)
        self.assertTrue(res["evidence"])


class FirstHandDetectionTests(unittest.TestCase):
    def test_lab_coverage_detected_as_first_hand(self):
        story = {
            "kind": "product",
            "coverage": [
                {"source": "openai-news", "lab": "openai", "published_at": "2026-10-04T10:00:00Z"}
            ]
        }
        fh = first_hand_of(story)
        self.assertIsNotNone(fh)
        self.assertEqual(fh["label"], "OpenAI công bố")
        self.assertEqual(fh["why"], "OpenAI công bố trực tiếp")

    def test_hf_trending_is_not_first_hand(self):
        story = {
            "kind": "model",
            "coverage": [
                {"source": "hf-trending", "lab": "huggingface", "published_at": "2026-10-04T10:00:00Z"}
            ]
        }
        self.assertIsNone(first_hand_of(story))

    def test_paper_kind_detected_as_first_hand_even_without_lab(self):
        story = {
            "kind": "paper",
            "coverage": [
                {"source": "arxiv", "lab": "", "published_at": "2026-10-04T10:00:00Z"}
            ]
        }
        fh = first_hand_of(story)
        self.assertIsNotNone(fh)
        self.assertEqual(fh["label"], "Bài báo gốc")
        self.assertEqual(fh["why"], "bài báo gốc của nhóm nghiên cứu")

    def test_third_party_news_is_not_first_hand(self):
        story = {
            "kind": "other",
            "coverage": [
                {"source": "techcrunch-ai", "lab": "", "published_at": "2026-10-04T10:00:00Z"}
            ]
        }
        self.assertIsNone(first_hand_of(story))


class WhyLineFormattingTests(unittest.TestCase):
    def test_why_line_includes_measurements_first_hand_and_age(self):
        story = {
            "id": "st-why",
            "published_at": "2026-10-04T10:00:00Z",  # 2 hours before NOW
            "coverage": [
                {"source": "openai-news", "publisher": "openai", "lab": "openai", "metrics": {}},
                {"source": "hn-front", "publisher": "hacker-news", "metrics": {"points": 1250}},
            ],
            "hot_score": 45.0,
            "hot_signals": {
                "measurement": {
                    "source": "hn-front",
                    "metric": "points",
                    "value": 1250,
                    "velocity_per_hour": 15.5
                }
            },
        }
        res = calculate_worth(story, NOW, sources_map={"hn-front": {"name": "Hacker News"}})
        why = res["why"]

        self.assertIn("OpenAI công bố trực tiếp", why)
        self.assertIn('<b class="num">2</b> nguồn cùng đưa tin', why)
        self.assertIn('<b class="num">1.250</b> điểm trên Hacker News', why)
        # Age is always last
        self.assertIn('đăng 2 giờ trước', why)

    def test_why_line_includes_speed_when_under_four_parts(self):
        story = {
            "id": "st-speed",
            "published_at": "2026-10-04T10:00:00Z",
            "coverage": [
                {"source": "hn-front", "publisher": "hacker-news", "metrics": {"points": 1250}},
            ],
            "hot_score": 45.0,
            "hot_signals": {
                "measurement": {
                    "source": "hn-front",
                    "metric": "points",
                    "value": 1250,
                    "velocity_per_hour": 15.5
                }
            },
        }
        res = calculate_worth(story, NOW, sources_map={"hn-front": {"name": "Hacker News"}})
        why = res["why"]
        self.assertIn('<b class="num">1.250</b> điểm trên Hacker News', why)
        self.assertIn('tăng <b class="num">15,5</b> điểm mỗi giờ', why)
        self.assertIn('đăng 2 giờ trước', why)

    def test_vietnamese_number_formatting(self):
        self.assertEqual(fmt_vi(1234567), "1.234.567")
        self.assertEqual(fmt_speed_vi(12.5), "12,5")
        self.assertEqual(fmt_speed_vi(12.0), "12")

    def test_annotate_story_in_place(self):
        story = {
            "id": "st-ann",
            "published_at": "2026-10-04T11:00:00Z",
            "coverage": [{"source": "press", "publisher": "press"}],
            "hot_score": None,
            "hot_signals": {"measurement": None}
        }
        annotate_story_worth(story, NOW)
        self.assertIn("worth_score", story)
        self.assertIn("worth_parts", story)
        self.assertIn("worth_why", story)
        self.assertIsInstance(story["worth_score"], float)
        self.assertIsInstance(story["worth_parts"], dict)
        self.assertIsInstance(story["worth_why"], str)


class SourceCountParityTests(unittest.TestCase):
    def js_uniq_coverage(self, coverage, name_of=None):
        """Reference implementation matching site/titles.js uniqCoverage."""
        name_of = name_of or (lambda s: s)
        best = {}
        for i, c in enumerate(coverage or []):
            if not c:
                continue
            src = c.get("source")
            key = str(c.get("publisher") or name_of(src) or src or i).lower()
            metrics = c.get("metrics") or {}
            score = sum(1 for v in metrics.values() if isinstance(v, (int, float)) and not (isinstance(v, float) and (v != v or abs(v) == float('inf'))))
            if key not in best or score > best[key]["score"]:
                best[key] = {"c": c, "i": best[key]["i"] if key in best else i, "score": score}
        return [x["c"] for x in sorted(best.values(), key=lambda x: x["i"])]

    def test_python_and_js_count_sources_the_same_way(self):
        # Case 1: Same publisher with different source names (Finding 4 regression)
        cov1 = [
            {"source": "openai-news", "publisher": "openai", "url": "https://openai.com/post-1", "metrics": {}},
            {"source": "openai-youtube", "publisher": "openai", "url": "https://youtube.com/watch?v=123", "metrics": {}},
        ]
        py_res1 = uniq_coverage(cov1)
        js_res1 = self.js_uniq_coverage(cov1)
        self.assertEqual(len(py_res1), 1)
        self.assertEqual(len(js_res1), 1)

        # Case 2: Different publishers
        cov2 = [
            {"source": "openai-news", "publisher": "openai", "metrics": {}},
            {"source": "anthropic-news", "publisher": "anthropic", "metrics": {}},
            {"source": "google-news", "publisher": "google", "metrics": {}},
        ]
        py_res2 = uniq_coverage(cov2)
        js_res2 = self.js_uniq_coverage(cov2)
        self.assertEqual(len(py_res2), 3)
        self.assertEqual(len(js_res2), 3)

        # Case 3: Metric tie-breaking and order preservation
        cov3 = [
            {"source": "press-a", "publisher": "outlet-x", "metrics": {"points": 10}},
            {"source": "press-b", "publisher": "outlet-y", "metrics": {"points": 50, "comments": 20}},
            {"source": "press-c", "publisher": "outlet-x", "metrics": {"points": 100, "comments": 30}},
        ]
        py_res3 = uniq_coverage(cov3)
        js_res3 = self.js_uniq_coverage(cov3)
        self.assertEqual([c["source"] for c in py_res3], [c["source"] for c in js_res3])
        self.assertEqual([c["source"] for c in py_res3], ["press-c", "press-b"])

        # Case 4: Missing publisher falls back to normalized source name
        sources_map = {
            "s1": {"name": "Tech News (AI)"},
            "s2": {"name": "Tech News"},
        }
        from radar.worth import src_name
        name_of = lambda s: src_name(s, sources_map)
        cov4 = [
            {"source": "s1", "metrics": {}},
            {"source": "s2", "metrics": {}},
        ]
        py_res4 = uniq_coverage(cov4, sources_map=sources_map)
        js_res4 = self.js_uniq_coverage(cov4, name_of=name_of)
        self.assertEqual(len(py_res4), 1)
        self.assertEqual(len(js_res4), 1)


if __name__ == "__main__":
    unittest.main()


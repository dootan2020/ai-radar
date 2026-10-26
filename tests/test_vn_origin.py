"""Shadow trial labels and hourly artifact review."""

from datetime import date
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from radar.shadow_collector import LIVE_FEED_URL, collect_all, parse_generic_feed
from radar.transport import ResponseText
from radar.vn_origin import classify_origin_item
from radar.catalog import RETIRED


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review-vn-origin.py"
spec = importlib.util.spec_from_file_location("review_vn_origin", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class OriginLabelTests(unittest.TestCase):
    def test_local_feed_timestamp_uses_candidate_timezone(self):
        feed = """<rss><channel><item><title>Người Việt thử AI</title>
        <link>https://example.org/story</link>
        <pubDate>10/23/2026 6:31:00\u202fPM</pubDate></item></channel></rss>"""
        items, _, error = parse_generic_feed(feed, {
            "id": "tuoitre-so", "name": "Tuổi Trẻ", "default_tz": "+07:00", "origin_trial": True})
        self.assertIsNone(error)
        self.assertEqual(items[0]["published_at"], "2026-10-23T11:31:00Z")

    def test_real_feed_title_fixture(self):
        fixture = Path(__file__).parent / "fixtures" / "vn-origin-titles.json"
        rows = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rows), 40)
        self.assertTrue(all(row.get("reason") for row in rows))
        for row in rows:
            with self.subTest(title=row["title"]):
                result = classify_origin_item(
                    {"title": row["title"], "summary": row.get("summary", "")}, [],
                    vietnamese_language=row["source"] != "vnexpress-tech")
                self.assertEqual(result["has_vn_entity"], row["vn_origin"])

    def test_domestic_headlines_without_old_entity_terms(self):
        titles = [
            "'Chung cư' cho heo, chuồng trại AI tại triển lãm chăn nuôi",
            "TP HCM vận hành khu đóng gói bán dẫn dùng chung",
            "Gia Lai đề xuất thí điểm taxi bay không người lái",
            "Bộ trưởng Vũ Hải Quân: Sửa luật đo lường để bảo vệ quyền lợi người tiêu dùng",
            "Nhóm nghiên cứu Việt chế tạo xương kim loại từ titan",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(classify_origin_item(
                    {"title": title}, [], vietnamese_language=True)["has_vn_entity"])

    def test_foreign_subject_is_not_overridden_by_vietnamese_summary_mention(self):
        item = {
            "title": "Chinese teen AI prodigy joins ex-Google researchers' startup",
            "summary": "A Vietnamese AI researcher co-founded the startup.",
        }
        self.assertFalse(classify_origin_item(item, [], vietnamese_language=False)["has_vn_entity"])
        self.assertFalse(classify_origin_item(
            {"title": "Sau Úc, AI xâm nhập hệ thống Chính phủ Canada"}, [],
            vietnamese_language=True)["has_vn_entity"])

    def test_shadow_press_sources_remain_retired_from_live(self):
        candidates = json.loads((Path(__file__).parents[1] / "data" / "shadow-candidates.json")
                                .read_text(encoding="utf-8"))["fixed_feeds"]
        trial = {row["id"] for row in candidates if row.get("origin_trial")}
        self.assertTrue(set(RETIRED).issubset(trial))
        self.assertEqual(len(RETIRED), 4)
        self.assertIn("vietnamnet-cong-nghe", trial)

    def test_vietnamese_ai_and_foreign_republish_are_separate_decisions(self):
        domestic = {"title": "FPT ra mắt nền tảng AI tại Hà Nội",
                    "url": "https://example.org/fpt-ai",
                    "published_at": "2026-10-26T02:00:00Z"}
        foreign = {"title": "OpenAI releases a new AI model",
                   "url": "https://example.org/openai-model",
                   "published_at": "2026-10-26T02:00:00Z"}
        self.assertEqual(classify_origin_item(domestic, [])["vn_origin_ai"], True)
        self.assertEqual(classify_origin_item(domestic, [])["likely_foreign_republish"], False)
        self.assertEqual(classify_origin_item(foreign, [])["likely_foreign_republish"], True)
        match = classify_origin_item(domestic, [{"title": domestic["title"],
                                                "url": "https://live.example/fpt-ai",
                                                "published_at": domestic["published_at"]}])
        self.assertEqual(match["live_match_url"], "https://live.example/fpt-ai")
        self.assertTrue(match["likely_foreign_republish"])

    def test_vietnamese_person_requires_a_named_person(self):
        domestic = {"title": "Ông Nguyễn Văn An giới thiệu mô hình AI",
                    "url": "https://example.org/person"}
        foreign = {"title": "Ông Sam Altman giới thiệu mô hình AI",
                   "url": "https://example.org/other"}
        self.assertTrue(classify_origin_item(domestic, [])["has_vn_entity"])
        self.assertFalse(classify_origin_item(foreign, [])["has_vn_entity"])

    def test_collector_labels_only_trial_feed_and_uses_live_snapshot(self):
        candidate = {"id": "vn-test", "name": "Vietnam test", "kind": "fixed feed",
                     "parser": "rss", "origin_trial": True, "url": "https://example.org/rss"}
        feed = """<rss><channel><item><title>Viettel ra mắt AI mới</title>
        <link>https://example.org/story</link><pubDate>Mon, 26 Oct 2026 02:00:00 GMT</pubDate>
        <description>Viettel phát triển nền tảng trí tuệ nhân tạo</description></item></channel></rss>"""
        live = {"stories": [{"title": "Viettel ra mắt AI mới", "url": "https://live.example/story",
                             "published_at": "2026-10-26T02:00:00Z"}]}
        calls = []

        def fetch(url):
            calls.append(url)
            return ResponseText(json.dumps(live) if url == LIVE_FEED_URL else feed,
                                status=200, url=url)

        _, records = collect_all([candidate], fetch_fn=fetch, delay=0, check_robots_policy=False)
        self.assertEqual(calls, [LIVE_FEED_URL, candidate["url"]])
        item = records[0]["items"][0]
        self.assertIn("Viettel", item["summary"])
        self.assertTrue(item["vn_origin"]["vn_origin_ai"])
        self.assertTrue(item["vn_origin"]["likely_foreign_republish"])

    def test_unavailable_live_snapshot_is_visible_in_label(self):
        candidate = {"id": "vn-test", "kind": "fixed feed", "parser": "rss",
                     "origin_trial": True, "url": "https://example.org/rss"}
        feed = """<rss><channel><item><title>FPT ra mắt AI</title>
        <link>https://example.org/story</link></item></channel></rss>"""

        def fetch(url):
            if url == LIVE_FEED_URL:
                raise OSError("offline")
            return ResponseText(feed, status=200, url=url)

        _, records = collect_all([candidate], fetch_fn=fetch, delay=0, check_robots_policy=False)
        self.assertFalse(records[0]["items"][0]["vn_origin"]["live_match_checked"])


class ReviewTests(unittest.TestCase):
    def test_hourly_repeats_count_once_and_sampling_is_stable(self):
        item = {"title": "FPT xây dựng AI tại Việt Nam", "url": "https://example.org/story?utm_source=x",
                "published_at": "2026-10-26T02:00:00Z",
                "vn_origin": {"vn_origin_ai": True, "likely_foreign_republish": False,
                              "live_match_checked": True}}
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(2):
                path = Path(directory) / f"run-{index}.json"
                path.write_text(json.dumps({"records": [{"candidate_id": "vn-test",
                                                        "items": [item]}]}), encoding="utf-8")
                paths.append(path)
            snapshots, daily, sample, unchecked, failed_sources, undated = review.summarize(
                paths, date(2026, 10, 26), 7)
        self.assertEqual(snapshots, 2)
        self.assertEqual(daily[0][1:], (1, 1, 0))
        self.assertEqual(sum(row[1] for row in daily), 1)
        self.assertEqual(len(sample), 1)
        self.assertEqual(unchecked, 0)
        self.assertEqual(failed_sources, 0)
        self.assertEqual(undated, 0)


if __name__ == "__main__":
    unittest.main()

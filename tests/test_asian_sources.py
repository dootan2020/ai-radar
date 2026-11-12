"""Asian newsrooms added so the Vietnamese morning (23:00-06:00 UTC) has original AI news."""

from datetime import datetime, timezone
from pathlib import Path
import unittest

from radar import catalog, v2feeds

FIXTURES = Path(__file__).parent / "fixtures" / "asian-sources"
NOW = datetime(2026, 11, 12, 6, 30, 0, tzinfo=timezone.utc)

ASIAN_SOURCES = {
    # id: (url, publisher, filter_ai)
    "yonhap": ("https://en.yna.co.kr/RSS/news.xml", "yonhap", True),
    "analytics-india-mag": ("https://analyticsindiamag.com/feed/", "analytics-india-magazine", False),
}


def parse_fixture(source_id):
    source = {s["id"]: s for s in catalog.sources(NOW)}[source_id]
    text = (FIXTURES / (source_id + ".xml")).read_text(encoding="utf-8")
    return v2feeds.parse_feed(text, source, NOW.isoformat())


class AsianSourceCatalogTests(unittest.TestCase):
    def test_sources_are_active_press_feeds(self):
        sources = {s["id"]: s for s in catalog.sources(NOW)}
        for source_id, (url, publisher, filter_ai) in ASIAN_SOURCES.items():
            with self.subTest(source_id=source_id):
                src = sources[source_id]
                self.assertEqual(src["url"], url)
                self.assertEqual(src["parser"], "feed")
                self.assertEqual(src["group"], "press")
                self.assertEqual(src["publisher"], publisher)
                self.assertEqual(src["lab"], "")
                self.assertIs(src["filter_ai"], filter_ai)
                self.assertNotIn("disabled", src)
                self.assertNotIn(source_id, catalog.RETIRED)


class AsianSourceFeedTests(unittest.TestCase):
    def test_yonhap_keeps_ai_story_and_drops_general_news(self):
        items = parse_fixture("yonhap")
        self.assertEqual([i["title"] for i in items],
                         ["Samsung, SK hynix monitor Nvidia leadership uncertainty: officials"])
        self.assertEqual(items[0]["published_at"], "2026-11-12T01:21:00Z")
        self.assertEqual(items[0]["publisher"], "yonhap")
        self.assertEqual(items[0]["url"], "https://en.yna.co.kr/view/AEN20261112005800320")

    def test_analytics_india_mag_keeps_every_ai_feature(self):
        items = parse_fixture("analytics-india-mag")
        self.assertEqual(len(items), 2)
        by_title = {i["title"]: i for i in items}
        self.assertEqual(by_title["Cognizant Commits 25,000 Professionals to Deploy Claude in Enterprises"]["published_at"],
                         "2026-11-11T23:52:10Z")
        self.assertEqual(by_title["Virtusa CEO Admits Losing Money on AI, But is Betting the House on Chips"]["published_at"],
                         "2026-11-12T05:45:03Z")

    def test_fixture_stories_fall_in_the_vietnamese_morning(self):
        # 23:00-06:00 UTC is 06:00-13:00 in Vietnam, when US newsrooms are quiet.
        for source_id in ASIAN_SOURCES:
            for item in parse_fixture(source_id):
                with self.subTest(source_id=source_id, title=item["title"]):
                    hour = int(item["published_at"][11:13])
                    self.assertTrue(hour >= 23 or hour < 6)


if __name__ == "__main__":
    unittest.main()

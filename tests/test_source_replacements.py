"""Synthetic offline policy regressions; these are not live feed captures."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from radar import catalog, feeds, pipeline, v2feeds, youtube
from radar.transport import ResponseText

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
DISABLED_IDS = {"import-ai", "dwarkesh-podcast", "latent-space", "google-deepmind"}
ACTIVE_ID = "nvidia-blog"
SYNTHETIC_NEWS = """<rss><channel>
<item><title>Nghiên cứu trí tuệ nhân tạo mới</title>
<link>https://fixture.invalid/ai-news</link>
<pubDate>Fri, 02 Oct 2026 17:00:00 +0700</pubDate></item>
<item><title>Kết quả bóng đá hôm nay</title>
<link>https://fixture.invalid/sport</link>
<pubDate>Fri, 02 Oct 2026 16:00:00 +0700</pubDate></item>
</channel></rss>"""


class SourceReplacementTests(unittest.TestCase):
    def setUp(self):
        self.sources = {row["id"]: row for row in feeds.SOURCES + catalog.sources(NOW)}

    def test_each_disabled_source_keeps_identity_url_and_specific_reason(self):
        for id_ in DISABLED_IDS:
            with self.subTest(source=id_):
                source = self.sources[id_]
                self.assertIs(source["disabled"], True)
                self.assertTrue(source["disabled_reason"])
                self.assertTrue(source["url"].startswith("https://"))
                self.assertIn("hosted runner", source["disabled_reason"])
        self.assertNotIn("disabled", self.sources["dwarkesh-video"])
        self.assertEqual(self.sources["dwarkesh-video"]["publisher"], "dwarkesh")

    def test_active_filtered_feed_keeps_publisher_and_ai_filter(self):
        source = self.sources[ACTIVE_ID]
        self.assertEqual(source["publisher"], "nvidia")
        self.assertNotIn("disabled", source)
        self.assertTrue(source["filter_ai"])
        items = v2feeds.parse_feed(SYNTHETIC_NEWS, source, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], ACTIVE_ID)
        self.assertEqual(items[0]["title"], "Nghiên cứu trí tuệ nhân tạo mới")
        self.assertEqual(items[0]["published_at"], "2026-10-02T10:00:00Z")
        self.assertEqual(items[0]["metrics"], {})

    def test_disabled_sources_are_visible_failed_and_never_requested_or_parsed(self):
        selected = DISABLED_IDS | {ACTIVE_ID}
        jobs = [job for job in pipeline._jobs(True, NOW) if job[0]["id"] in selected]
        active_url = self.sources[ACTIVE_ID]["url"]
        requests = []

        def fetch(url):
            requests.append(url)
            if url != active_url:
                self.fail("Disabled source was requested: " + url)
            return ResponseText(SYNTHETIC_NEWS, status=200, url=url)

        with tempfile.TemporaryDirectory() as folder:
            events = Path(folder) / "events.json"
            events.write_bytes(b"[]")
            with patch.object(pipeline, "_jobs", return_value=jobs), \
                 patch.object(youtube, "collect", return_value=([], [])):
                result = pipeline.build_v2(fetch=fetch, now=NOW, events_path=events)
        self.assertEqual(requests, [active_url])
        records = {row["id"]: row for row in result["sources"]}
        for id_ in DISABLED_IDS:
            with self.subTest(source=id_):
                row = records[id_]
                self.assertIs(row["disabled"], True)
                self.assertFalse(row["ok"])
                self.assertEqual(row["count"], 0)
                self.assertEqual(row["error"], "Disabled: " + row["disabled_reason"])
                self.assertEqual(row["url"], self.sources[id_]["url"])
                self.assertIsNone(row["http_status"])
                self.assertEqual(row["http_requests"], [])
        self.assertTrue(records[ACTIVE_ID]["ok"])
        self.assertEqual(records[ACTIVE_ID]["http_status"], 200)
        self.assertEqual(len(result["stories"]), 1)
        self.assertEqual({row["source"] for row in result["stories"][0]["coverage"]}, {ACTIVE_ID})

    def test_disabled_policy_applies_to_legacy_build_too(self):
        jobs = [job for job in pipeline._jobs() if job[0]["id"] == "google-deepmind"]
        with patch.object(pipeline, "_jobs", return_value=jobs), \
             patch.object(youtube, "collect", return_value=([], [])):
            result = pipeline.build(fetch=lambda url: self.fail("Disabled source fetched"), now=NOW)
        self.assertEqual(result["updates"], [])
        self.assertEqual(len(result["sources"]), 1)
        self.assertTrue(result["sources"][0]["disabled"])
        self.assertFalse(result["sources"][0]["ok"])

    def test_disabled_record_survives_expired_collection_deadline(self):
        jobs = [job for job in pipeline._jobs() if job[0]["id"] == "google-deepmind"]
        with patch.object(pipeline, "_jobs", return_value=jobs), \
             patch.object(youtube, "collect", return_value=([], [])):
            result = pipeline.build(fetch=lambda url: self.fail("Disabled source fetched"), now=NOW, timeout=1e-9)
        record = next(row for row in result["sources"] if row["id"] == "google-deepmind")
        self.assertTrue(record["disabled"])
        self.assertTrue(record["error"].startswith("Disabled: "))
        self.assertNotIn("deadline", record["error"].lower())


if __name__ == "__main__":
    unittest.main()

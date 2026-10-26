"""Replay captured official feeds for the hub's missing source events."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import catalog, feeds, items, pipeline, source_probe, v2feeds, youtube


NOW = datetime(2026, 10, 26, 11, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "hub-nguon"
CASES = {
    "metr": ("metr.xml", {
        "B18": "2026-10-22-red-teaming-openai-agent-monitoring",
        "B19": "2026-10-20-misalignment-risk-report-august-2026-review",
    }),
    "cloudflare-blog": ("cloudflare.xml", {
        "B03": "clairic-extraction-model",
        "B36": "webmcp-commerce",
    }),
    "github-changelog": ("github-changelog.xml", {
        "B34": "2026-10-23-turn-notifications-into-code-with-github-copilot-in-teams",
    }),
    "sakana-blog": ("sakana.xml", {
        "B32": "aquarium-release",
        "B33": "qd-rec",
    }),
}
NAMES = {"metr": "METR", "cloudflare-blog": "Cloudflare Blog",
         "github-changelog": "GitHub Changelog", "sakana-blog": "Sakana AI"}
NON_AI = {
    "cloudflare-blog": ("origin-range-requests", "hyperdrive-mysql"),
    "github-changelog": ("emu-deletions-fix",),
}


class HubNguonReplayTests(unittest.TestCase):
    def test_official_feed_replay_keeps_all_seven_events_and_drops_non_ai(self):
        sources = {source["id"]: source for source in catalog.sources(NOW)}
        found = set()
        for source_id, (fixture, events) in CASES.items():
            with self.subTest(source=source_id):
                source = sources[source_id]
                self.assertEqual(source["name"], NAMES[source_id])
                self.assertEqual(source["filter_ai"], source_id in {"cloudflare-blog", "github-changelog"})
                body = (FIXTURES / fixture).read_text(encoding="utf-8")
                parsed = v2feeds.parse_feed(body, source, NOW)
                urls = {item["url"] for item in parsed}
                self.assertTrue(all(item["source"] == source_id for item in parsed))
                for event, path in events.items():
                    self.assertTrue(any(path in url for url in urls), event)
                    found.add(event)
                for path in NON_AI.get(source_id, ()):
                    self.assertFalse(any(path in url for url in urls), path)
                if source_id == "cloudflare-blog":
                    clairic = next(item for item in parsed if "clairic" in item["url"])
                    self.assertFalse(items.relevant(clairic["title"], clairic["summary"]))
                if source_id == "sakana-blog":
                    self.assertTrue(all(url.startswith("https://sakana.ai/") for url in urls))
                    self.assertTrue(any("qd-rec" in url and "2026-10-19" in item["published_at"]
                                        for item in parsed for url in [item["url"]]))
                legacy = feeds.parse_feed(body, source)
                self.assertTrue(legacy)
                self.assertTrue(all(item["url"].startswith("https://") for item in legacy))
        self.assertEqual(found, {"B03", "B18", "B19", "B32", "B33", "B34", "B36"})

    def test_ai_next_to_japanese_text_is_a_distinct_acronym(self):
        self.assertTrue(items.relevant("オントロジーを基盤に、意思決定・実行を支援するAIエージェントプラットフォーム"))

    def test_replay_reaches_snapshot_coverage(self):
        selected = set(CASES)
        jobs = [job for job in pipeline._jobs(True, NOW) if job[0]["id"] in selected]
        bodies = {job[0]["url"]: (FIXTURES / CASES[job[0]["id"]][0]).read_text(encoding="utf-8")
                  for job in jobs}
        self.assertEqual(len(jobs), 4)
        with tempfile.TemporaryDirectory() as folder:
            events = Path(folder) / "events.json"
            events.write_bytes(b"[]")
            with patch.object(pipeline, "_jobs", return_value=jobs), \
                 patch.object(youtube, "collect", return_value=([], [])):
                snapshot = pipeline.build_v2(fetch=lambda url, **kwargs: bodies[url], now=NOW,
                                             events_path=events, resolve_images=False)
                first = {row["id"]: row for row in snapshot["sources"]}["metr"]
                self.assertEqual(first["last_successful_fetch"], "2026-10-26T11:00:00Z")
                self.assertIsNotNone(first["newest_item_date"])

                def failed_metr(url, **kwargs):
                    if url == next(job[0]["url"] for job in jobs if job[0]["id"] == "metr"):
                        raise OSError("fixture fetch failed")
                    return bodies[url]

                failed_snapshot = pipeline.build_v2(fetch=failed_metr, now=NOW + timedelta(hours=1),
                                                    previous=snapshot, events_path=events,
                                                    resolve_images=False)
                failed = {row["id"]: row for row in failed_snapshot["sources"]}["metr"]
                self.assertFalse(failed["ok"])
                self.assertEqual(failed["last_successful_fetch"], first["last_successful_fetch"])
                self.assertEqual(failed["newest_item_date"], first["newest_item_date"])
                self.assertEqual(failed["last_error"], "OSError: fixture fetch failed")
        urls = {item["url"] for story in snapshot["stories"] for item in story["coverage"]}
        for events_by_source in (events for _, events in CASES.values()):
            for path in events_by_source.values():
                self.assertTrue(any(path in url for url in urls), path)
        for paths in NON_AI.values():
            for path in paths:
                self.assertFalse(any(path in url for url in urls), path)

    def test_health_carries_last_success_and_error_across_silent_fetch(self):
        prior = {"sources": [{"id": "metr", "ok": True, "checked_at": "2026-10-25T11:00:00Z",
                              "http_requests": [{"url": "https://metr.org/feed.xml"}],
                              "newest_item_date": "2026-10-22T07:00:00Z", "last_error": "HTTP 503"}]}
        failed = [{"id": "metr", "ok": False, "error": "Build deadline exceeded", "http_requests": []}]
        source_probe.enrich_source_health(failed, [], NOW, prior)
        self.assertEqual(failed[0]["last_successful_fetch"], "2026-10-25T11:00:00Z")
        self.assertEqual(failed[0]["newest_item_date"], "2026-10-22T07:00:00Z")
        self.assertEqual(failed[0]["last_error"], "Build deadline exceeded")
        recovered = [{"id": "metr", "ok": True, "error": None,
                      "http_requests": [{"url": "https://metr.org/feed.xml"}]}]
        source_probe.enrich_source_health(recovered, [{"source": "metr", "published_at":
                                                       "2026-10-26T10:00:00Z"}], NOW,
                                          {"sources": failed})
        self.assertEqual(recovered[0]["last_successful_fetch"], "2026-10-26T11:00:00Z")
        self.assertEqual(recovered[0]["newest_item_date"], "2026-10-26T10:00:00Z")
        self.assertEqual(recovered[0]["last_error"], "Build deadline exceeded")


if __name__ == "__main__":
    unittest.main()

"""Offline integration uses explicitly synthetic sources; no production writes."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from radar import catalog, feeds, pipeline, youtube
from radar.transport import ResponseText
if __package__:
    from .test_v2_events import event
    from .test_v2_support import NOW
else:
    from test_v2_events import event
    from test_v2_support import NOW


def source(id_, **changes):
    return {"id": id_, "name": id_, "url": "https://fixture.invalid/" + id_,
            "kind": "rss", "parser": "feed", "group": "press", "lab": "",
            "publisher": id_, "first_wave": True} | changes


FEED = '<rss><channel><item><title>AI synthetic architecture released today</title>' \
       '<link>https://lab.example/release</link>' \
       '<pubDate>Fri, 02 Oct 2026 11:00:00 GMT</pubDate></item></channel></rss>'
ORIGINAL_YOUTUBE_COLLECT = youtube.collect


class PipelineV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = Path(self.temp.name) / "events.json"
        self.events.write_bytes(b"[]")
        self.sources = [source("good-a"), source("good-b"), source("timeout"), source("malformed")]
        roster = patch.object(catalog, "sources", side_effect=lambda now: self.sources)
        roster.start()
        self.addCleanup(roster.stop)
        youtube_stub = patch.object(youtube, "collect", return_value=([], []))
        youtube_stub.start()
        self.addCleanup(youtube_stub.stop)

    def fetch(self, url):
        if url.endswith(("good-a", "good-b")):
            return FEED
        if url.endswith("timeout"):
            raise TimeoutError("synthetic source timeout")
        if url.endswith("malformed"):
            return "<html>upstream challenge</html>"
        raise OSError("synthetic unavailable legacy source")

    def build(self, **kwargs):
        return pipeline.build_v2(fetch=self.fetch, now=NOW, events_path=self.events, **kwargs)

    def test_source_failures_keep_successful_coverage_and_separate_diagnostics(self):
        result = self.build()
        self.assertEqual(result["schema_version"], 2)
        records = {row["id"]: row for row in result["sources"]}
        for id_ in ["good-a", "good-b"]:
            self.assertTrue(records[id_]["ok"])
            self.assertEqual(records[id_]["count"], 1)
            self.assertIsNone(records[id_]["http_status"])
        for id_ in ["timeout", "malformed"]:
            self.assertFalse(records[id_]["ok"])
            self.assertTrue(records[id_]["error"])
            self.assertEqual(records[id_]["count"], 0)
        self.assertIsNone(records["timeout"]["http_status"])
        story = next(row for row in result["stories"] if row["url"] == "https://lab.example/release")
        self.assertEqual(story["source_count"], 2)
        self.assertEqual({row["source"] for row in story["coverage"]}, {"good-a", "good-b"})
        self.assertTrue(story["hot_reason"])
        json.dumps(result, allow_nan=False)

    def test_sections_reference_unique_existing_stories(self):
        result = self.build()
        ids = [story["id"] for story in result["stories"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(result["sections"]),
                         {"today", "hot", "models", "papers", "listen", "voices", "community", "upcoming"})
        for section in result["sections"].values():
            self.assertEqual(len(section), len(set(section)))
            self.assertTrue(set(section).issubset(ids))
        for field in ["updates", "hf_releases", "live", "trending"]:
            self.assertIn(field, result)

    def test_legacy_update_projection_preserves_existing_seen_identity(self):
        result = self.build()
        row = result["updates"][0]
        original_source = next(source for source in self.sources if source["id"] == row["source"])
        expected = feeds.parse_feed(FEED, original_source)[0]
        self.assertEqual(row, expected)

    def test_anthropic_research_classification_is_preserved_in_projection_and_story(self):
        research_source = source("anthropic-research", group="lab", publisher="anthropic", lab="anthropic")
        self.sources = [research_source]
        body = FEED.replace("AI synthetic architecture released today", "Measuring everyday work patterns")
        with patch.object(feeds, "SOURCES", []):
            result = pipeline.build_v2(fetch=lambda url: body, now=NOW, events_path=self.events)
        row = next(row for row in result["updates"] if row["source"] == "anthropic-research")
        self.assertEqual(row["kind"], "research")
        item = next(item for story in result["stories"] for item in story["coverage"]
                    if item["source"] == "anthropic-research")
        self.assertEqual(item["kind"], "research")

    def test_prior_snapshot_is_measurement_only_not_republished_content(self):
        old = self.build()
        self.sources = []
        result = self.build(previous=old)
        self.assertEqual(result["stories"], [])
        self.assertTrue(all(not section for section in result["sections"].values()))

    def test_published_snapshot_carries_content_while_measurement_baseline_does_not(self):
        old = self.build()
        self.assertEqual(len(old["stories"]), 1)
        story_id = old["stories"][0]["id"]
        self.sources = []
        # Measurement baseline only (previous): nothing republished
        baseline_only = self.build(previous=old)
        self.assertEqual(baseline_only["stories"], [])
        self.assertNotIn(story_id, [s["id"] for s in baseline_only["stories"]])
        # Published snapshot (published): story is carried
        published_carried = self.build(published=old)
        self.assertEqual(len(published_carried["stories"]), 1)
        self.assertEqual(published_carried["stories"][0]["id"], story_id)
        self.assertTrue(published_carried["stories"][0].get("carried"))



    def test_legacy_snapshot_is_not_advertised_as_a_measurement_baseline(self):
        previous = self.build() | {"schema_version": 1, "generated_at": "2026-10-02T11:00:00Z"}
        result = self.build(previous=previous)
        self.assertIsNone(result["ranking"]["baseline_at"])

    def test_shared_landing_page_does_not_merge_distinct_event_occurrences(self):
        rows = [event(id="conference-london", location="London"),
                event(id="conference-tokyo", location="Tokyo", start_date="2026-10-20", end_date="2026-10-21")]
        self.events.write_bytes(json.dumps(rows).encode("utf-8"))
        result = self.build()
        stories = [story for story in result["stories"] if story["kind"] == "event"]
        self.assertEqual(len(stories), 2)
        self.assertEqual(len({story["id"] for story in stories}), 2)
        self.assertEqual({story["url"] for story in stories}, {rows[0]["url"]})
        self.assertTrue({story["id"] for story in stories}.issubset(result["sections"]["upcoming"]))
        self.assertTrue(all(story["hot_score"] is None for story in stories))

    def test_malformed_calendar_does_not_discard_network_successes(self):
        self.events.write_bytes(b'{"not":"an array"}')
        result = self.build()
        self.assertEqual(result["events"], [])
        self.assertTrue(any(story["url"] == "https://lab.example/release" for story in result["stories"]))
        self.assertTrue(any(not source["ok"] and source["group"] == "event" for source in result["sources"]))

    def test_observed_http_error_retains_status_separate_from_transport_denial(self):
        self.sources = [source("blocked")]
        def denied(url):
            raise HTTPError(url, 429, "synthetic throttling", {}, None)
        result = pipeline.build_v2(fetch=denied, now=NOW, events_path=self.events)
        record = next(row for row in result["sources"] if row["id"] == "blocked")
        self.assertFalse(record["ok"])
        self.assertEqual(record["http_status"], 429)

    def test_http_success_with_invalid_body_is_a_parser_failure_with_observed_200(self):
        self.sources = [source("bad-body")]
        def malformed(url):
            return ResponseText("<html>not an RSS feed</html>", status=200, url=url)
        result = pipeline.build_v2(fetch=malformed, now=NOW, events_path=self.events)
        record = next(row for row in result["sources"] if row["id"] == "bad-body")
        self.assertFalse(record["ok"])
        self.assertEqual(record["http_status"], 200)
        self.assertTrue(record["error"])
        self.assertTrue(record["http_requests"])

    def test_youtube_primary_status_reflects_real_streams_query_request(self):
        self.sources = []
        channels = (youtube.CHANNELS[0], catalog.NVIDIA_CHANNEL)
        def channel_feed(url):
            if "/streams" in url:
                channel = next(channel for channel in channels if "/@" + channel[3] + "/" in url)
                data = {"metadata": {"channelMetadataRenderer": {"externalId": channel[4]}},
                        "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [{"tabRenderer": {
                            "selected": True, "endpoint": {"commandMetadata": {"webCommandMetadata": {
                                "url": "/@" + channel[3] + "/streams"}}},
                            "content": {"richGridRenderer": {"contents": [
                                {"messageRenderer": {"text": {"simpleText": "No streams"}}}]}}}}]}}}
                return ResponseText("var ytInitialData = " + json.dumps(data) + ";", status=200, url=url)
            if "/feeds/videos.xml" in url:
                return ResponseText('<feed xmlns="http://www.w3.org/2005/Atom"/>', status=200, url=url)
            raise OSError("synthetic unavailable source")
        with patch.object(youtube, "collect", ORIGINAL_YOUTUBE_COLLECT), \
             patch.object(youtube, "CHANNELS", (channels[0],)):
            result = pipeline.build_v2(fetch=channel_feed, now=NOW, events_path=self.events)
        record = next(row for row in result["sources"] if row["id"] == channels[0][0])
        self.assertTrue(record["ok"], record)
        self.assertTrue(any("/streams?hl=en" in row["url"] and row["http_status"] == 200
                            for row in record["http_requests"]))
        self.assertEqual(record["http_status"], 200)

    def test_deadline_returns_stable_snapshot_while_late_workers_finish(self):
        release = threading.Event()
        def delayed(url):
            release.wait(1)
            return self.fetch(url)
        started = time.monotonic()
        try:
            result = pipeline.build_v2(fetch=delayed, now=NOW, timeout=0.03, events_path=self.events)
            self.assertLess(time.monotonic() - started, 0.6)
            self.assertTrue(any("deadline" in str(row["error"]).lower() for row in result["sources"]))
            before = json.dumps(result, sort_keys=True)
        finally:
            release.set()
        time.sleep(0.03)
        self.assertEqual(json.dumps(result, sort_keys=True), before)

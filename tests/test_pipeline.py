"""Offline integration, deadline enforcement, and atomic file publication."""

import json
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from radar import feeds, huggingface, pipeline, transport, youtube

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 30, 22, tzinfo=timezone.utc)


def saved(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        sources = [dict(id=id_, name=id_, lab="openai", kind="rss", url="https://fixture.invalid/" + id_)
                   for id_ in ("feed-a", "feed-b", "feed-fails")]
        self.stack.enter_context(patch.object(feeds, "SOURCES", sources))
        self.stack.enter_context(patch.object(huggingface, "SOURCES", [next(s for s in huggingface.SOURCES if s["lab"] == "deepseek")]))
        self.stack.enter_context(patch.object(youtube, "CHANNELS", (youtube.CHANNELS[0],)))

    def fetch(self, url):
        if url.endswith("feed-fails"):
            raise TimeoutError("fixture source timed out")
        if url.endswith(("feed-a", "feed-b")):
            return saved("openai.xml")
        if "/api/models?" in url:
            return saved("hf-releases.json")
        if "huggingface.co/api/trending" in url:
            return saved("hf-trending.json")
        if "github.com/trending" in url:
            return saved("github.html")
        if "/streams" in url:
            return 'var ytInitialData = ' + json.dumps({
                "metadata": {"channelMetadataRenderer": {"externalId": youtube.CHANNELS[0][4]}},
                "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [{"tabRenderer": {
                    "selected": True, "endpoint": {"commandMetadata": {"webCommandMetadata": {
                        "url": "/@OpenAI/streams"}}}, "content": {"richGridRenderer": {"contents": [
                            {"videoRenderer": {"videoId": "Fls_onRviPM"}}]}}}}]}}}) + ';'
        if "/feeds/videos.xml" in url:
            return '<feed xmlns="http://www.w3.org/2005/Atom"/>'
        if "/watch?" in url:
            return saved("youtube-ended.html")
        raise AssertionError("Unmapped URL: " + url)

    def test_exact_contract_partial_failure_and_cross_feed_dedupe(self):
        result = pipeline.build(fetch=self.fetch, now=NOW)
        self.assertEqual(set(result), {"generated_at", "sources", "updates", "hf_releases", "live", "trending"})
        self.assertEqual(result["generated_at"], "2026-09-30T22:00:00Z")
        self.assertEqual(set(result["trending"]), {"github", "huggingface"})
        self.assertEqual(len(result["updates"]), 3)
        self.assertEqual(len(result["hf_releases"]), 3)
        self.assertEqual(len(result["live"]), 1)
        self.assertEqual(len(result["trending"]["github"]), 3)
        self.assertEqual(len(result["trending"]["huggingface"]), 3)
        self.assertEqual(len(result["sources"]), 7)
        by_id = {source["id"]: source for source in result["sources"]}
        self.assertFalse(by_id["feed-fails"]["ok"])
        self.assertIn("TimeoutError", by_id["feed-fails"]["error"])
        self.assertEqual(by_id["feed-fails"]["count"], 0)
        self.assertTrue(by_id["feed-a"]["ok"])
        for source in result["sources"]:
            self.assertEqual(set(source), {"id", "name", "lab", "kind", "ok", "count", "error", "error_vi"})
        self.assertEqual(len({item["id"] for item in result["updates"]}), 3)

    def test_youtube_collector_failure_reports_verified_channels_only(self):
        with patch.object(youtube, "collect", side_effect=RuntimeError("collector unavailable")):
            result = pipeline.build(fetch=self.fetch, now=NOW)
        sources = [source for source in result["sources"] if source["kind"] == "youtube"]
        self.assertEqual({source["id"] for source in sources},
                         {"openai-youtube", "anthropic-youtube", "google-youtube", "deepmind-youtube"})
        self.assertTrue(all(not source["ok"] and "collector unavailable" in source["error"]
                            for source in sources))

    def test_mixed_missing_dates_do_not_break_aggregate_sort(self):
        def fetch(url):
            body = self.fetch(url)
            if url.endswith("feed-a"):
                return body.replace("<pubDate>Wed, 30 Sep 2026 10:30:00 GMT</pubDate>", "")
            if "/api/models?" in url:
                rows = json.loads(body)
                del rows[0]["createdAt"]
                return json.dumps(rows)
            return body
        result = pipeline.build(fetch=fetch, now=NOW)
        self.assertEqual(len(result["updates"]), 3)
        self.assertEqual(len(result["hf_releases"]), 3)
        self.assertIsNone(result["hf_releases"][-1]["created_at"])

    def test_all_failures_still_produce_valid_empty_payload(self):
        def fail(url):
            raise OSError("offline fixture outage")
        result = pipeline.build(fetch=fail, now=NOW)
        self.assertTrue(result["sources"])
        self.assertTrue(all(not source["ok"] and source["error"] for source in result["sources"]))
        for key in ["updates", "hf_releases", "live"]:
            self.assertEqual(result[key], [])
        self.assertEqual(result["trending"], {"github": [], "huggingface": []})
        json.dumps(result, allow_nan=False)

    def test_global_deadline_returns_and_snapshot_does_not_mutate_later(self):
        release = threading.Event()
        def slow(url):
            release.wait(1)
            return self.fetch(url)
        start = time.monotonic()
        try:
            result = pipeline.build(fetch=slow, now=NOW, timeout=0.05)
            self.assertLess(time.monotonic() - start, 0.6)
            self.assertTrue(any("deadline" in str(s["error"]).lower() for s in result["sources"]))
            before = json.dumps(result, sort_keys=True)
        finally:
            release.set()
        time.sleep(0.03)
        self.assertEqual(json.dumps(result, sort_keys=True), before)


class TransportTests(unittest.TestCase):
    def test_timeout_bounds_injected_stalled_transport(self):
        release = threading.Event()
        def stalled(url):
            release.wait(1)
            return "late"
        fetch = transport.Fetcher(time.monotonic() + 1, stalled, timeout=0.03)
        start = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                fetch("https://fixture.invalid")
            self.assertLess(time.monotonic() - start, 0.5)
        finally:
            release.set()

    def test_error_and_nontext_responses_are_explicit(self):
        def fail(url):
            raise OSError("fixture network failure")
        with self.assertRaisesRegex(OSError, "fixture network failure"):
            transport.Fetcher(time.monotonic() + 1, fail)("https://fixture.invalid")
        with self.assertRaisesRegex(ValueError, "text"):
            transport.Fetcher(time.monotonic() + 1, lambda url: b"bytes")("https://fixture.invalid")

    def test_oversized_decoded_response_rejected(self):
        with patch.object(transport, "MAX_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "limit"):
                transport.Fetcher(time.monotonic() + 1, lambda url: "x" * 11)("https://fixture.invalid")


class AtomicWriterTests(unittest.TestCase):
    def test_complete_utf8_json_replaces_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "nested/radar.json"
            pipeline.write_atomic({"title": "Tiếng Việt"}, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"title": "Tiếng Việt"})
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_serialization_failure_preserves_old_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "radar.json"
            target.write_bytes(b'{"old":true}\n')
            with self.assertRaises(ValueError):
                pipeline.write_atomic({"not_json": float("nan")}, target)
            self.assertEqual(target.read_bytes(), b'{"old":true}\n')
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_replace_failure_leaves_old_file_and_cleans_complete_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "radar.json"
            target.write_bytes(b'{"old":true}')
            def fail_replace(temp, destination):
                self.assertEqual(Path(temp).parent, target.parent)
                self.assertEqual(json.loads(Path(temp).read_text()), {"new": True})
                self.assertEqual(target.read_bytes(), b'{"old":true}')
                raise PermissionError("fixture locked destination")
            with patch.object(pipeline.os, "replace", fail_replace):
                with self.assertRaises(PermissionError):
                    pipeline.write_atomic({"new": True}, target)
            self.assertEqual(target.read_bytes(), b'{"old":true}')
            self.assertEqual(list(target.parent.iterdir()), [target])


if __name__ == "__main__":
    unittest.main()

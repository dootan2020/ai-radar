"""Broadcast contracts. Live/upcoming cases are explicit mutations of real metadata."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from radar import feeds, huggingface, youtube

NOW = datetime(2026, 9, 30, 22, tzinfo=timezone.utc)
CHANNEL = youtube.CHANNELS[0]
VIDEO = "Fls_onRviPM"
SAVED = (Path(__file__).parent / "fixtures/youtube-ended.html").read_text(encoding="utf-8")


def player(**broadcast):
    start = SAVED.index("{", SAVED.index("ytInitialPlayerResponse"))
    data = json.JSONDecoder().raw_decode(SAVED[start:])[0]
    if broadcast:
        data["microformat"]["playerMicroformatRenderer"]["liveBroadcastDetails"] = broadcast
    return data


def embed(data):
    return "<script>var ytInitialPlayerResponse = " + json.dumps(data) + ";</script>"


def streams(ids):
    data = {"contents": [{"lockupViewModel": {"contentId": video_id, "contentType": "LOCKUP_CONTENT_TYPE_VIDEO"}} for video_id in ids]}
    return "var ytInitialData = " + json.dumps(data) + ";"


class YoutubeWatchTests(unittest.TestCase):
    def test_saved_real_live_broadcast(self):
        body = (Path(__file__).parent / "fixtures/youtube-live.html").read_text(encoding="utf-8")
        channel = ("nasa-test", "test-only", "NASA", "NASA", "UCLA_DiR1FfKNvjuUpBHmylQ")
        item = youtube.parse_watch(body, "mlfzT_nD6GE", channel, NOW)
        self.assertEqual(item["status"], "live")
        self.assertEqual(item["start_at"], "2026-09-30T21:59:18Z")
        self.assertIsNone(item["end_at"])

    def test_saved_real_ended_broadcast_exact_contract(self):
        self.assertEqual(youtube.parse_watch(SAVED, VIDEO, CHANNEL, NOW), {
            "video_id": VIDEO, "lab": "openai", "channel": "OpenAI",
            "title": "OpenAI DevDay 2026 Keynote (FULL)",
            "url": "https://www.youtube.com/watch?v=" + VIDEO,
            "thumbnail": "https://i.ytimg.com/vi/" + VIDEO + "/hqdefault.jpg",
            "status": "ended", "start_at": "2026-09-29T16:48:03Z", "end_at": "2026-09-29T17:55:42Z",
        })

    def test_live_and_upcoming_classification(self):
        cases = [("live", {"isLiveNow": True, "startTimestamp": "2026-10-01T03:00:00+07:00"}),
                 ("upcoming", {"isLiveNow": False, "startTimestamp": "2026-10-01T19:00:00+07:00"})]
        for status, broadcast in cases:
            with self.subTest(status=status):
                item = youtube.parse_watch(embed(player(**broadcast)), VIDEO, CHANNEL, NOW)
                self.assertEqual(item["status"], status)
                self.assertTrue(item["start_at"].endswith("Z"))
                self.assertIsNone(item["end_at"])

    def test_unknown_start_is_null_for_confirmed_live(self):
        item = youtube.parse_watch(embed(player(isLiveNow=True)), VIDEO, CHANNEL, NOW)
        self.assertIsNone(item["start_at"])
        self.assertEqual(item["status"], "live")

    def test_seven_day_end_boundary_inclusive(self):
        for age, retained in [(timedelta(days=7), True), (timedelta(days=7, seconds=1), False)]:
            end = NOW - age
            data = player(isLiveNow=False, startTimestamp=(end-timedelta(hours=1)).isoformat(), endTimestamp=end.isoformat())
            item = youtube.parse_watch(embed(data), VIDEO, CHANNEL, NOW)
            self.assertEqual(item is not None, retained)

    def test_ordinary_future_upload_is_not_upcoming_broadcast(self):
        data = player()
        del data["microformat"]["playerMicroformatRenderer"]["liveBroadcastDetails"]
        data["videoDetails"]["isLiveContent"] = False
        data["microformat"]["playerMicroformatRenderer"]["publishDate"] = "2026-10-02"
        self.assertIsNone(youtube.parse_watch(embed(data), VIDEO, CHANNEL, NOW))

    def test_missing_malformed_or_mismatched_metadata_fails_explicitly(self):
        bodies = ["<html>Consent required</html>", embed({}), embed(player(isLiveNow=False)),
                  embed(player(isLiveNow=False, startTimestamp="not-a-date"))]
        wrong = player()
        wrong["videoDetails"]["channelId"] = "wrong-channel"
        bodies.append(embed(wrong))
        for body in bodies:
            with self.subTest(body=body[:80]):
                with self.assertRaises(ValueError):
                    youtube.parse_watch(body, VIDEO, CHANNEL, NOW)

    def test_inconsistent_live_or_ended_timestamps_fail(self):
        cases = [dict(isLiveNow=True, startTimestamp="2026-10-02T00:00:00Z"),
                 dict(isLiveNow=True, endTimestamp="2026-09-30T20:00:00Z"),
                 dict(isLiveNow=False, startTimestamp="2026-09-30T21:00:00Z", endTimestamp="2026-09-30T20:00:00Z")]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    youtube.parse_watch(embed(player(**case)), VIDEO, CHANNEL, NOW)


class YoutubeDiscoveryTests(unittest.TestCase):
    def test_catalog_has_only_verified_channels_and_keeps_other_xai_coverage(self):
        self.assertEqual({source["id"] for source in youtube.SOURCES},
                         {channel[0] for channel in youtube.CHANNELS})
        self.assertNotIn("xai-youtube", {source["id"] for source in youtube.SOURCES})
        self.assertTrue(any(source["id"] == "xai-news" and source["lab"] == "xai"
                            for source in feeds.SOURCES))
        self.assertTrue(any(source["id"] == "xai-hf" and source["lab"] == "xai"
                            for source in huggingface.SOURCES))

    def test_healthy_empty_channels_do_not_emit_unconfigured_failures(self):
        def fetch(url):
            if "/streams" in url:
                return 'var ytInitialData = {"contents": [{"messageRenderer": {"text": "No streams"}}]};'
            if "/feeds/videos.xml" in url:
                return '<feed xmlns="http://www.w3.org/2005/Atom"/>'
            raise AssertionError("Unexpected request: " + url)
        items, sources = youtube.collect(fetch, NOW)
        self.assertEqual(items, [])
        self.assertEqual({source["id"] for source in sources},
                         {channel[0] for channel in youtube.CHANNELS})
        self.assertTrue(all(source["ok"] and source["count"] == 0 and source["error"] is None
                            for source in sources))

    def test_modern_stream_ids_deduped(self):
        self.assertEqual(youtube.parse_streams(streams([VIDEO, VIDEO, "invalid"])), [(VIDEO, 1)])

    def test_legacy_urgent_stream_precedes_ended_candidate(self):
        data = {"contents": [{"videoRenderer": {"videoId": VIDEO}},
                             {"videoRenderer": {"videoId": "AbCdEfGhIjK", "upcomingEventData": {"startTime": "1790881200"}}}]}
        parsed = youtube.parse_streams("var ytInitialData = " + json.dumps(data))
        self.assertEqual(parsed[0], ("AbCdEfGhIjK", 0))

    def test_rss_real_schema_filters_invalid_ids(self):
        body = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>' + VIDEO + '</yt:videoId></entry><entry><yt:videoId>invalid</yt:videoId></entry></feed>'
        self.assertEqual(youtube.parse_rss(body), [VIDEO])

    def test_partial_discovery_error_retains_verified_video(self):
        def fetch(url):
            if "/streams" in url:
                return streams([VIDEO, VIDEO])
            if "/feeds/" in url:
                raise TimeoutError("fixture timeout")
            return SAVED
        with patch.object(youtube, "CHANNELS", (CHANNEL,)):
            items, sources = youtube.collect(fetch, NOW)
        self.assertEqual(len(items), 1)
        source = next(row for row in sources if row["id"] == CHANNEL[0])
        self.assertFalse(source["ok"])
        self.assertEqual(source["count"], 1)
        self.assertIn("TimeoutError", source["error"])

    def test_watch_fetches_globally_bounded_and_failures_visible(self):
        calls, lock = [], Lock()
        ids = [f"{number:011d}" for number in range(100)]
        def fetch(url):
            with lock:
                calls.append(url)
            if "/streams" in url:
                return streams(ids)
            if "/feeds/" in url:
                return '<feed xmlns="http://www.w3.org/2005/Atom"/>'
            raise TimeoutError("watch deadline")
        items, sources = youtube.collect(fetch, NOW)
        watches = [url for url in calls if "/watch?" in url]
        self.assertEqual(len(watches), youtube.MAX_WATCH_PAGES)
        self.assertLessEqual(len(calls), 2 * len(youtube.CHANNELS) + youtube.MAX_WATCH_PAGES)
        self.assertEqual(items, [])
        self.assertTrue(all(not source["ok"] for source in sources))


if __name__ == "__main__":
    unittest.main()

"""YouTube Data API v3 collection tests using real fixtures."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request

from radar import catalog, youtube
from radar.transport import Fetcher, SafeRedirectHandler, read_url, sanitize_secret

FIXTURES = Path(__file__).parent / "fixtures" / "youtube_api"
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
OPENAI_CHANNEL = youtube.CHANNELS[0]


def fixture_text(filename):
    return (FIXTURES / filename).read_text(encoding="utf-8")


class YouTubeUploadsPlaylistIdTests(unittest.TestCase):
    """Test uploads playlist ID derivation (UC... -> UU...)."""

    def test_replaces_leading_uc_with_uu(self):
        self.assertEqual(youtube.uploads_playlist_id("UCXZCJLdBC09xxGZ6gcdrc6A"), "UUXZCJLdBC09xxGZ6gcdrc6A")
        self.assertEqual(youtube.uploads_playlist_id("UCHuiy8bXnmK5nisYHUd1J5g"), "UUHuiy8bXnmK5nisYHUd1J5g")
        self.assertEqual(youtube.uploads_playlist_id("UCrDwWp7EBBv4NwvScIpBDOA"), "UUrDwWp7EBBv4NwvScIpBDOA")

    def test_derivation_matches_real_channel_fixtures(self):
        openai_channels = json.loads(fixture_text("openai-channels.json"))
        expected_openai = openai_channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        self.assertEqual(youtube.uploads_playlist_id(OPENAI_CHANNEL[4]), expected_openai)

        nvidia_channels = json.loads(fixture_text("nvidia-channels.json"))
        expected_nvidia = nvidia_channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        self.assertEqual(youtube.uploads_playlist_id(catalog.NVIDIA_CHANNEL[4]), expected_nvidia)


class YouTubeParsingTests(unittest.TestCase):
    """Test parsing real playlistItems.list and videos.list fixtures."""

    def test_parse_playlist_items_extracts_video_ids(self):
        text = fixture_text("openai-playlistitems.json")
        video_ids = youtube.parse_playlist_items(text)
        self.assertEqual(video_ids, [
            "fHEIw5CcN5U",
            "sKltfHvsDQM",
            "Fls_onRviPM",
            "7Bv68f5szSU",
            "uXspbC2srEQ",
        ])

    def test_parse_videos_response_contracts(self):
        text = fixture_text("openai-videos.json")
        items = youtube.parse_videos_response(text, OPENAI_CHANNEL, NOW)
        # openai-videos.json contains 1 broadcast (Fls_onRviPM) and 4 ordinary uploads.
        # Only broadcasts are emitted into items.
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["video_id"], "Fls_onRviPM")
        self.assertEqual(item["title"], "OpenAI DevDay 2026 Keynote (FULL)")
        self.assertEqual(item["lab"], "openai")
        self.assertEqual(item["channel"], "OpenAI")
        self.assertEqual(item["url"], f"https://www.youtube.com/watch?v={item['video_id']}")
        self.assertTrue(item["thumbnail"].startswith("https://"))
        self.assertTrue(item["published_at"])
        self.assertTrue(item["start_at"])
        self.assertEqual(item["status"], "ended")

    def test_stream_recognition_from_real_video_fixture(self):
        text = fixture_text("openai-videos.json")
        items = youtube.parse_videos_response(text, OPENAI_CHANNEL, NOW)
        keynote = next(it for it in items if it["video_id"] == "Fls_onRviPM")
        self.assertEqual(keynote["status"], "ended")
        self.assertEqual(keynote["start_at"], "2026-09-29T16:48:03Z")
        self.assertEqual(keynote["end_at"], "2026-09-29T17:55:42Z")
        self.assertEqual(keynote["published_at"], "2026-09-29T18:42:29Z")
        self.assertEqual(keynote["title"], "OpenAI DevDay 2026 Keynote (FULL)")

    def test_point1_ordinary_uploads_return_none_and_rejected_by_publication(self):
        # Point 1: Ordinary uploads return None from parse_video_item and do not enter live projection.
        # From openai-videos.json: item 0 is 'fHEIw5CcN5U' (The dots demo, ordinary video).
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][0]
        # Fields examined: liveStreamingDetails is None, liveBroadcastContent == "none"
        self.assertIsNone(raw_video.get("liveStreamingDetails"))
        self.assertEqual(raw_video.get("snippet", {}).get("liveBroadcastContent"), "none")
        item = youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertIsNone(item)

        # radar/publication.py inspect_projection_row rejects status=None or non-broadcast status
        from radar.publication import inspect_projection_row
        with self.assertRaises(ValueError):
            inspect_projection_row("live", {"title": "Ordinary Video", "url": "https://www.youtube.com/watch?v=123", "status": None})
        with self.assertRaises(ValueError):
            inspect_projection_row("live", {"title": "Ordinary Video", "url": "https://www.youtube.com/watch?v=123", "status": "unknown"})

    def test_nvidia_fixture_parsing(self):
        text = fixture_text("nvidia-videos.json")
        items = youtube.parse_videos_response(text, catalog.NVIDIA_CHANNEL, NOW)
        # All 5 videos in nvidia-videos.json are ordinary uploads without liveStreamingDetails, so 0 broadcasts
        self.assertEqual(len(items), 0)

    def test_live_stream_status_classification(self):
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][2]
        # Mutate to active live broadcast
        raw_video["liveStreamingDetails"] = {
            "actualStartTime": "2026-10-05T11:00:00Z",
            "scheduledStartTime": "2026-10-05T11:00:00Z",
        }
        item = youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertEqual(item["status"], "live")
        self.assertEqual(item["start_at"], "2026-10-05T11:00:00Z")
        self.assertIsNone(item["end_at"])

    def test_upcoming_stream_status_classification(self):
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][2]
        # Mutate to scheduled upcoming broadcast (start_at in future)
        raw_video["liveStreamingDetails"] = {
            "scheduledStartTime": "2026-10-06T15:00:00Z",
        }
        item = youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertEqual(item["status"], "upcoming")
        self.assertEqual(item["start_at"], "2026-10-06T15:00:00Z")
        self.assertIsNone(item["end_at"])

    def test_point2_passed_scheduled_start_without_actual_start_is_indeterminate_not_upcoming(self):
        # Point 2: A video whose scheduledStartTime has passed with no actualStartTime (cancelled/missed stream)
        # must NOT be labelled upcoming.
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][2]
        # Controlled edit: set scheduledStartTime to 2 hours in the past, remove actualStartTime and actualEndTime,
        # set liveBroadcastContent to 'upcoming'.
        raw_video["snippet"]["liveBroadcastContent"] = "upcoming"
        raw_video["liveStreamingDetails"] = {
            "scheduledStartTime": (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        }
        # parse_video_item raises ValueError for indeterminate status instead of labelling upcoming
        with self.assertRaises(ValueError) as ctx:
            youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertIn("Broadcast status indeterminate", str(ctx.exception))

        # parse_videos_response drops it from items and appends diagnostic
        diagnostics = []
        items = youtube.parse_videos_response(json.dumps({"items": [raw_video]}), OPENAI_CHANNEL, NOW, diagnostics=diagnostics)
        self.assertEqual(items, [])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("Broadcast status indeterminate", diagnostics[0])

    def test_point3_indeterminate_broadcast_emits_diagnostic_not_ended_item(self):
        # Point 3: A broadcast without end time and without valid live/upcoming status must NOT be labelled 'ended'
        # without end_at (which would escape 7-day rule). It must be an error/diagnostic, never a published row.
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][2]
        # Controlled edit: remove actualEndTime, actualStartTime, scheduledStartTime, keeping liveStreamingDetails empty
        # and liveBroadcastContent as 'none'.
        raw_video["snippet"]["liveBroadcastContent"] = "none"
        raw_video["liveStreamingDetails"] = {}

        with self.assertRaises(ValueError) as ctx:
            youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertIn("Broadcast status indeterminate", str(ctx.exception))

        # Verified through collect: channel reports diagnostic, item is not published, ok is True
        diagnostics = []
        items = youtube.parse_videos_response(json.dumps({"items": [raw_video]}), OPENAI_CHANNEL, NOW, diagnostics=diagnostics)
        self.assertEqual(items, [])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("Broadcast status indeterminate", diagnostics[0])

    def test_ended_stream_older_than_7_days_is_dropped(self):
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][2]
        # Ended 8 days ago, started 8 days and 1 hour ago
        ended_at = (NOW - timedelta(days=8)).isoformat().replace("+00:00", "Z")
        started_at = (NOW - timedelta(days=8, hours=1)).isoformat().replace("+00:00", "Z")
        raw_video["liveStreamingDetails"]["actualStartTime"] = started_at
        raw_video["liveStreamingDetails"]["actualEndTime"] = ended_at
        item = youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertIsNone(item)

    def test_ended_stream_within_7_days_is_kept(self):
        raw_video = json.loads(fixture_text("openai-videos.json"))["items"][2]
        # Ended 6 days ago, started 6 days and 1 hour ago
        ended_at = (NOW - timedelta(days=6)).isoformat().replace("+00:00", "Z")
        started_at = (NOW - timedelta(days=6, hours=1)).isoformat().replace("+00:00", "Z")
        raw_video["liveStreamingDetails"]["actualStartTime"] = started_at
        raw_video["liveStreamingDetails"]["actualEndTime"] = ended_at
        item = youtube.parse_video_item(raw_video, OPENAI_CHANNEL, NOW)
        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "ended")


class YouTubeCollectionTests(unittest.TestCase):
    """Test collect() execution with mocked Data API responses."""

    def test_collect_with_mocked_fixtures(self):
        playlist_data = fixture_text("openai-playlistitems.json")
        videos_data = fixture_text("openai-videos.json")
        called_urls = []

        def mock_fetch(url):
            called_urls.append(url)
            if "playlistItems" in url:
                return playlist_data
            if "videos" in url:
                return videos_data
            raise AssertionError("Unexpected URL called: " + url)

        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-api-key"}), \
             patch.object(youtube, "CHANNELS", (OPENAI_CHANNEL,)):
            items, sources = youtube.collect(mock_fetch, NOW)

        # 1 broadcast item from openai-videos.json
        self.assertEqual(len(items), 1)
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0]["ok"])
        self.assertEqual(sources[0]["id"], "openai-youtube")
        self.assertEqual(sources[0]["count"], 1)
        self.assertIsNone(sources[0]["error"])

        # Boundary checks: never call disallowed paths or search.list
        for url in called_urls:
            self.assertNotIn("/streams", url)
            self.assertNotIn("/feeds/videos.xml", url)
            self.assertNotIn("/watch?", url)
            self.assertNotIn("search", url)
            self.assertTrue(url.startswith("https://www.googleapis.com/youtube/v3/"))

    def test_missing_api_key_reports_clean_source_error(self):
        def mock_fetch(url):
            raise AssertionError("Fetch should not be called when API key is missing")

        with patch.dict("os.environ", {}, clear=True):
            items, sources = youtube.collect(mock_fetch, NOW)

        self.assertEqual(items, [])
        self.assertEqual(len(sources), len(youtube.CHANNELS))
        for source in sources:
            self.assertFalse(source["ok"])
            self.assertEqual(source["count"], 0)
            self.assertIn("Missing YOUTUBE_API_KEY", source["error"])
            self.assertIn("Không đọc được", source["error_vi"])

    def test_api_error_reports_honest_source_error_without_fallback(self):
        called = []

        def mock_fetch(url):
            called.append(url)
            raise HTTPError(url, 403, "Quota Exceeded", hdrs=None, fp=None)

        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-api-key"}), \
             patch.object(youtube, "CHANNELS", (OPENAI_CHANNEL,)):
            items, sources = youtube.collect(mock_fetch, NOW)

        self.assertEqual(items, [])
        self.assertEqual(len(sources), 1)
        self.assertFalse(sources[0]["ok"])
        self.assertEqual(sources[0]["count"], 0)
        self.assertIn("HTTPError", sources[0]["error"])
        # Verified no scraping fallback called
        self.assertEqual(len(called), 1)
        self.assertNotIn("/streams", called[0])


class YouTubeSecurityTests(unittest.TestCase):
    """Test Boundary 2: API key never appears in URLs, logs, errors, or requests."""

    SECRET_KEY = "AIzaSySecretKeyNeverLeakThis9999"

    def test_read_url_sends_key_in_header_not_in_url(self):
        captured_requests = []

        def dummy_urlopen(req, timeout=None):
            captured_requests.append(req)
            mock_resp = MagicMock()
            mock_resp.status = 200
            headers_mock = MagicMock()
            headers_mock.get.side_effect = lambda k, default=None: "2" if k == "Content-Length" else default
            headers_mock.get_content_charset.return_value = "utf-8"
            mock_resp.headers = headers_mock
            mock_resp.read.return_value = b"{}"
            mock_resp.geturl.return_value = req.full_url
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        api_url = "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId=UU123"
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": self.SECRET_KEY}), \
             patch("radar.transport.urlopen", dummy_urlopen):
            read_url(api_url)

        self.assertEqual(len(captured_requests), 1)
        req = captured_requests[0]
        self.assertEqual(req.headers.get("X-goog-api-key"), self.SECRET_KEY)
        self.assertNotIn(self.SECRET_KEY, req.full_url)

    def test_safe_redirect_handler_strips_google_api_key_on_untrusted_redirect(self):
        handler = SafeRedirectHandler()
        req = Request("https://www.googleapis.com/youtube/v3/videos",
                      headers={"X-Goog-Api-Key": self.SECRET_KEY, "Authorization": "token abc"})

        redirected = handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/steal")
        self.assertNotIn("X-Goog-Api-Key", redirected.headers)
        self.assertNotIn("Authorization", redirected.headers)

    def test_sanitize_secret_redacts_api_key(self):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": self.SECRET_KEY}):
            leaked_msg = f"HTTPError: 403 Forbidden with key {self.SECRET_KEY} on https://api.invalid/?key={self.SECRET_KEY}"
            sanitized = sanitize_secret(leaked_msg)
            self.assertNotIn(self.SECRET_KEY, sanitized)
            self.assertIn("[REDACTED]", sanitized)

    def test_fetcher_evidence_and_errors_do_not_contain_secret(self):
        def failing_transport(url, **kwargs):
            raise ValueError(f"Connection failed for key={self.SECRET_KEY}")

        fetcher = Fetcher(deadline=9999999999, transport=failing_transport)
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": self.SECRET_KEY}):
            with self.assertRaises(ValueError):
                fetcher(f"https://www.googleapis.com/youtube/v3/playlistItems?key={self.SECRET_KEY}", source_id="openai-youtube")

            evidence = fetcher.evidence("openai-youtube")
            self.assertEqual(len(evidence), 1)
            record = evidence[0]
            self.assertNotIn(self.SECRET_KEY, record["url"])
            self.assertNotIn(self.SECRET_KEY, str(record["error"]))
            self.assertIn("[REDACTED]", record["url"])
            self.assertIn("[REDACTED]", record["error"])

    def test_youtube_collect_errors_do_not_contain_secret(self):
        def failing_fetch(url):
            raise RuntimeError(f"API failed with {self.SECRET_KEY}")

        with patch.dict("os.environ", {"YOUTUBE_API_KEY": self.SECRET_KEY}), \
             patch.object(youtube, "CHANNELS", (OPENAI_CHANNEL,)):
            items, sources = youtube.collect(failing_fetch, NOW)

        self.assertEqual(len(sources), 1)
        self.assertNotIn(self.SECRET_KEY, str(sources[0]["error"]))
        self.assertIn("[REDACTED]", str(sources[0]["error"]))

    def test_point4_fetcher_redacts_before_truncating_error_boundary(self):
        # Point 4: Fetcher.__call__ must redact secret before truncating to 300 characters,
        # preventing a key straddling the boundary from leaking partially.
        secret = self.SECRET_KEY
        # "ValueError: " is 12 chars. Prefix of 278 chars makes secret start at index 290,
        # straddling the 300-char boundary (chars 290-300).
        prefix = "E" * 278
        long_error_message = f"{prefix}{secret}suffix_padding_to_exceed_limit"

        def failing_transport(url, **kwargs):
            raise ValueError(long_error_message)

        fetcher = Fetcher(deadline=9999999999, transport=failing_transport)
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": secret}):
            with self.assertRaises(ValueError):
                fetcher("https://www.googleapis.com/youtube/v3/videos", source_id="openai-youtube")

            evidence = fetcher.evidence("openai-youtube")
            self.assertEqual(len(evidence), 1)
            error_text = str(evidence[0]["error"])
            # The secret prefix (first 10 chars) would leak if truncated before redaction
            self.assertNotIn(secret[:10], error_text)
            self.assertIn("[REDACTED]", error_text)
            self.assertLessEqual(len(error_text), 300)

    def test_point4_youtube_collect_redacts_before_truncating_error_boundary(self):
        # Point 4 in radar/youtube.py: error text must be redacted before truncating to 160 chars.
        secret = self.SECRET_KEY
        # "RuntimeError: " is 14 chars. Prefix of 136 chars makes secret start at index 150,
        # straddling the 160-char boundary (chars 150-160).
        prefix = "W" * 136
        long_exc = f"{prefix}{secret}padding"

        def failing_fetch(url):
            raise RuntimeError(long_exc)

        with patch.dict("os.environ", {"YOUTUBE_API_KEY": secret}), \
             patch.object(youtube, "CHANNELS", (OPENAI_CHANNEL,)):
            items, sources = youtube.collect(failing_fetch, NOW)

        self.assertEqual(len(sources), 1)
        err = str(sources[0]["error"])
        self.assertNotIn(secret[:10], err)
        self.assertIn("[REDACTED]", err)
        self.assertLessEqual(len(err), 160)


class YouTubeCatalogContinuityTests(unittest.TestCase):
    """Test Boundary 4: Source IDs, publishers, and groups stay continuous."""

    def test_configured_channel_ids_and_publishers(self):
        expected_ids = {"openai-youtube", "anthropic-youtube", "google-youtube", "deepmind-youtube"}
        actual_ids = {c[0] for c in youtube.CHANNELS}
        self.assertEqual(actual_ids, expected_ids)

        expected_sources = {"openai-youtube", "anthropic-youtube", "google-youtube", "deepmind-youtube"}
        actual_sources = {s["id"] for s in youtube.SOURCES}
        self.assertEqual(actual_sources, expected_sources)

        for channel in youtube.CHANNELS:
            self.assertIn(channel[1], {"openai", "anthropic", "google"})

    def test_nvidia_channel_continuity(self):
        self.assertEqual(catalog.NVIDIA_CHANNEL[0], "nvidia-youtube")
        self.assertEqual(catalog.NVIDIA_CHANNEL[1], "nvidia")
        self.assertEqual(catalog.NVIDIA_CHANNEL[4], "UCHuiy8bXnmK5nisYHUd1J5g")

    def test_dwarkesh_catalog_endpoint_matches_main(self):
        dwarkesh_entry = next(r for r in catalog.RSS if r[0] == "dwarkesh-video")
        self.assertEqual(dwarkesh_entry[0], "dwarkesh-video")
        self.assertEqual(dwarkesh_entry[2], "podcast")
        self.assertEqual(dwarkesh_entry[3], "dwarkesh")
        self.assertEqual(dwarkesh_entry[4], "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId=UUXl4i9dYBrFOabk0xGmbkRA&maxResults=50")


if __name__ == "__main__":
    unittest.main()

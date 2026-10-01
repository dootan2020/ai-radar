"""Channel fallback contracts, including explicit mutations of captured metadata."""

import json
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from radar import youtube
from verify_youtube_runner import verify
import verify_youtube_runner as runner

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
CHANNEL = youtube.CHANNELS[0]
VIDEO = "Fls_onRviPM"
FIXTURES = Path(__file__).parent / "fixtures"
NSF = ("nsf-test", "test-only", "NASASpaceflight", "NASASpaceflight", "UCSUu1lih2RifWkKtDOJdsBA")


def channel_page(renderer, channel_id=CHANNEL[4], selected=True, tab="streams"):
    data = {
        "metadata": {"channelMetadataRenderer": {"externalId": channel_id}},
        "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [{"tabRenderer": {
            "selected": selected, "endpoint": {"commandMetadata": {
                "webCommandMetadata": {"url": f"/@OpenAI/{tab}"}}},
            "content": {"richGridRenderer": {"contents": [{"richItemRenderer": {
                "content": {"videoRenderer": renderer}}}]}}
        }}]}}
    }
    return "var ytInitialData = " + json.dumps(data) + ";"


def ended_renderer(age="Streamed 2 days ago"):
    return {"videoId": VIDEO, "title": {"runs": [{"text": "OpenAI DevDay"}]},
            "publishedTimeText": {"simpleText": age}}


BLOCKED = 'var ytInitialPlayerResponse = {"playabilityStatus":{"status":"LOGIN_REQUIRED","reason":"Sign in to confirm you’re not a bot"}};'


class ChannelFallbackTests(unittest.TestCase):
    def collect(self, body, watch=BLOCKED, rss_error=False, channel=CHANNEL):
        def fetch(url):
            if "/streams" in url:
                return body
            if "/feeds/" in url:
                if rss_error:
                    raise OSError("RSS unavailable")
                return '<feed xmlns="http://www.w3.org/2005/Atom"/>'
            return watch
        with patch.object(youtube, "CHANNELS", (channel,)):
            return youtube.collect(fetch, NOW)

    def test_blocked_watch_and_rss_failure_keep_verified_channel_item(self):
        items, sources = self.collect(channel_page(ended_renderer()), rss_error=True)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "ended")
        self.assertIsNone(items[0]["start_at"])
        self.assertIsNone(items[0]["end_at"])
        self.assertEqual(items[0]["status_source"], "channel_streams")
        self.assertTrue(sources[0]["ok"])
        self.assertIsNone(sources[0]["error"])
        self.assertEqual(sources[0]["count"], 1)
        self.assertIn("LOGIN_REQUIRED", " ".join(sources[0]["diagnostics"]))

    def test_unverified_identity_or_non_streams_tab_cannot_supply_fallback(self):
        for options in ({"channel_id": "wrong"}, {"selected": False}, {"tab": "videos"}):
            with self.subTest(options=options):
                items, sources = self.collect(channel_page(ended_renderer(), **options))
                self.assertEqual(items, [])
                self.assertFalse(sources[0]["ok"])

    def test_relative_age_window_and_ordinary_upload_exclusion(self):
        for age, retained in [("Streamed 6 days ago", True), ("Streamed 7 days ago", False),
                              ("Streamed 1 week ago", False), ("2 days ago", False),
                              ("Premiered 2 days ago", False)]:
            with self.subTest(age=age):
                items, _ = self.collect(channel_page(ended_renderer(age)))
                self.assertEqual(bool(items), retained)

    def test_real_captured_modern_stream_states_survive_blocked_watch(self):
        for status, video_id in (("upcoming", "aqYtiH1UduQ"), ("live", "Jm8wRjD3xVA"),
                                 ("ended", "9gDxG-pm1Zo")):
            with self.subTest(status=status):
                body = (FIXTURES / f"youtube-runner-streams-{status}.html").read_text(encoding="utf-8")
                items, sources = self.collect(body, channel=NSF)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["video_id"], video_id)
                self.assertEqual(items[0]["status"], status)
                self.assertEqual(items[0]["status_source"], "channel_streams")
                self.assertIsNone(items[0]["start_at"])
                self.assertIsNone(items[0]["end_at"])
                self.assertTrue(sources[0]["ok"])
                if status == "upcoming":
                    self.assertIn("Scheduled for", items[0]["time_text"])
                    self.assertEqual(items[0]["time_precision"], "unknown")

    def test_real_upcoming_watch_overrides_ambiguous_channel_schedule(self):
        body = (FIXTURES / "youtube-runner-streams-upcoming.html").read_text(encoding="utf-8")
        watch = (FIXTURES / "youtube-runner-watch-upcoming.html").read_text(encoding="utf-8")
        items, sources = self.collect(body, watch=watch, channel=NSF)
        self.assertEqual(items[0]["status"], "upcoming")
        self.assertEqual(items[0]["start_at"], "2026-10-02T01:53:00Z")
        self.assertNotIn("status_source", items[0])
        self.assertTrue(sources[0]["ok"])

    def test_real_members_blocked_watch_keeps_readable_authoritative_metadata(self):
        body = (FIXTURES / "youtube-runner-watch-members-blocked.html").read_text(encoding="utf-8")
        item = youtube.parse_watch(body, "Heik3wPT4u8", NSF, NOW)
        self.assertEqual(item["status"], "ended")
        self.assertEqual(item["end_at"], "2026-09-28T16:48:00Z")
        self.assertNotIn("status_source", item)

    def test_real_login_required_age_restriction_preserves_ordinary_video_result(self):
        body = (FIXTURES / "youtube-runner-watch-login-required.html").read_text(encoding="utf-8")
        restricted = ("restricted-test", "test-only", "Restricted test", "test", "UCJqyF-E8VW75fQz61ftchzg")
        self.assertIsNone(youtube.parse_watch(body, "Njp5uhTorCo", restricted, NOW))

    def test_verified_ordinary_and_old_watch_veto_channel_status(self):
        base = {"videoDetails": {"videoId": VIDEO, "channelId": CHANNEL[4], "title": "Title", "isLiveContent": False}}
        old = dict(base, microformat={"playerMicroformatRenderer": {"liveBroadcastDetails": {
            "isLiveNow": False, "endTimestamp": "2026-09-01T00:00:00Z"}}})
        for data in (base, old):
            with self.subTest(data=data):
                items, sources = self.collect(channel_page(ended_renderer()),
                                              "var ytInitialPlayerResponse = " + json.dumps(data))
                self.assertEqual(items, [])
                self.assertTrue(sources[0]["ok"])

    def test_blocked_watch_with_identity_but_incomplete_metadata_keeps_fallback(self):
        data = {"videoDetails": {"videoId": VIDEO, "channelId": CHANNEL[4]},
                "playabilityStatus": {"status": "LOGIN_REQUIRED"}}
        items, sources = self.collect(channel_page(ended_renderer()),
                                      "var ytInitialPlayerResponse = " + json.dumps(data))
        self.assertEqual(items[0]["status_source"], "channel_streams")
        self.assertTrue(sources[0]["ok"])
        self.assertIn("Broadcast metadata unavailable", " ".join(sources[0]["diagnostics"]))

    def test_positive_watch_identity_mismatch_vetoes_fallback(self):
        for identity in ({"videoId": "WrongVid1234"}, {"channelId": "wrong-channel"}):
            with self.subTest(identity=identity):
                body = "var ytInitialPlayerResponse = " + json.dumps({"videoDetails": identity})
                items, sources = self.collect(channel_page(ended_renderer()), body)
                self.assertEqual(items, [])
                self.assertTrue(sources[0]["ok"])
                self.assertIn("mismatched", " ".join(sources[0]["diagnostics"]))

    def test_failed_tab_still_allows_identity_verified_rss_watch(self):
        watch = (FIXTURES / "youtube-ended.html").read_text(encoding="utf-8")
        def fetch(url):
            if "/streams" in url:
                return "Consent required"
            if "/feeds/" in url:
                return ('<feed xmlns="http://www.w3.org/2005/Atom" '
                        'xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
                        '<entry><yt:videoId>' + VIDEO + '</yt:videoId></entry></feed>')
            return watch
        with patch.object(youtube, "CHANNELS", (CHANNEL,)):
            items, sources = youtube.collect(fetch, NOW)
        self.assertEqual(len(items), 1)
        self.assertFalse(sources[0]["ok"])
        self.assertIn("streams", sources[0]["error"])

    def test_fallbacks_beyond_watch_budget_are_preserved_and_deduped(self):
        data = youtube._embedded(channel_page(ended_renderer()), "ytInitialData")
        grid = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["richGridRenderer"]
        grid["contents"] = [{"videoRenderer": dict(ended_renderer(), videoId=f"{n:011d}")}
                            for n in range(youtube.MAX_WATCH_PAGES + 5)]
        grid["contents"].append(grid["contents"][0])
        items, sources = self.collect("var ytInitialData = " + json.dumps(data))
        self.assertEqual(len(items), youtube.MAX_WATCH_PAGES + 5)
        self.assertEqual(sources[0]["count"], len(items))

    def test_sidebar_recommendations_and_nested_command_renderers_are_ignored(self):
        data = youtube._embedded(channel_page(ended_renderer()), "ytInitialData")
        data["sidebar"] = {"videoRenderer": dict(ended_renderer(), videoId="NopeVid1234")}
        renderer = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["richGridRenderer"]["contents"][0]["richItemRenderer"]["content"]["videoRenderer"]
        renderer["menu"] = {"videoRenderer": dict(ended_renderer(), videoId="NopeVid5678")}
        items, _ = self.collect("var ytInitialData = " + json.dumps(data))
        self.assertEqual([item["video_id"] for item in items], [VIDEO])

    def test_legacy_upcoming_has_exact_epoch_and_premiere_is_excluded(self):
        renderer = dict(ended_renderer(""), upcomingEventData={"startTime": "1790905980"})
        items, _ = self.collect(channel_page(renderer))
        self.assertEqual(items[0]["start_at"], "2026-10-02T01:53:00Z")
        renderer["publishedTimeText"] = {"simpleText": "Premieres in 1 day"}
        self.assertEqual(self.collect(channel_page(renderer))[0], [])

    def test_legacy_explicit_premiere_badge_vetoes_upcoming_event(self):
        renderer = dict(ended_renderer(""), upcomingEventData={"startTime": "1790905980"},
                        badges=[{"metadataBadgeRenderer": {
                            "style": "BADGE_STYLE_TYPE_SIMPLE", "label": "PREMIERE"}}])
        self.assertEqual(self.collect(channel_page(renderer))[0], [])

    def test_mismatched_renderer_owner_cannot_supply_fallback(self):
        renderer = dict(ended_renderer(), ownerText={"runs": [{"text": "Other channel",
            "navigationEndpoint": {"browseEndpoint": {"browseId": "wrong-channel"}}}]})
        self.assertEqual(self.collect(channel_page(renderer))[0], [])

    def test_captured_catalog_channel_identity(self):
        for handle, index in (("google", 2), ("googledeepmind", 3)):
            body = (FIXTURES / f"youtube-runner-channel-{handle}.html").read_text(encoding="utf-8")
            data = youtube._embedded(body, "ytInitialData")
            self.assertEqual(data["metadata"]["channelMetadataRenderer"]["externalId"], youtube.CHANNELS[index][4])

    def test_runner_probe_requires_actual_failed_watch_not_only_fallback_label(self):
        items, sources = self.collect(channel_page(ended_renderer()))
        with patch.object(youtube, "CHANNELS", (CHANNEL,)):
            self.assertEqual(len(verify(items, sources, True)[1]), 1)
            sources[0].pop("diagnostics")
            with self.assertRaisesRegex(ValueError, "actual watch failure"):
                verify(items, sources, True)
            sources[0]["ok"] = False
            with self.assertRaisesRegex(ValueError, "identity-verified"):
                verify(items, sources)

    def test_capture_preserves_absence_and_records_provenance_without_rewriting_real_restrictions(self):
        age_restricted = (FIXTURES / "youtube-runner-watch-login-required.html").read_text(encoding="utf-8")
        for watch, should_write in ((BLOCKED, True), (age_restricted, False)):
            with self.subTest(should_write=should_write), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "blocked.html"
                def fetch(url):
                    if "/streams" in url:
                        return channel_page(ended_renderer())
                    if "/feeds/" in url:
                        return '<feed xmlns="http://www.w3.org/2005/Atom"/>'
                    return watch
                with patch.object(youtube, "CHANNELS", (CHANNEL,)), patch.object(runner, "read_url", fetch), \
                     patch.object(sys, "argv", ["probe", "--capture-blocked", str(target)]), redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), 0)
                self.assertEqual(target.exists(), should_write)
                if should_write:
                    body = target.read_text(encoding="utf-8")
                    captured = youtube._embedded(body, "ytInitialPlayerResponse")
                    self.assertEqual(set(captured), {"playabilityStatus"})
                    provenance = json.loads(body.split("<!-- ", 1)[1].split(" -->", 1)[0])
                    self.assertEqual(provenance["source_url"], f"https://www.youtube.com/watch?v={VIDEO}")
                    digest = hashlib.sha256(json.dumps(captured, sort_keys=True).encode()).hexdigest()
                    self.assertEqual(provenance["extracted_player_sha256"], digest)


if __name__ == "__main__":
    unittest.main()

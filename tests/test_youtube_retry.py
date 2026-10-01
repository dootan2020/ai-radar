"""Malformed first responses recover without bypassing channel verification."""

import unittest
from unittest.mock import patch

from radar import youtube
from test_youtube_fallback import BLOCKED, CHANNEL, NOW, channel_page, ended_renderer


class StreamRetryTests(unittest.TestCase):
    def collect(self, pages, deadline=None):
        calls = []

        def fetch(url):
            calls.append(url)
            if "/streams" in url:
                return pages.pop(0)
            if "/feeds/" in url:
                return '<feed xmlns="http://www.w3.org/2005/Atom"/>'
            return BLOCKED

        if deadline is not None:
            fetch.deadline = deadline
        with patch.object(youtube, "CHANNELS", (CHANNEL,)):
            result = youtube.collect(fetch, NOW)
        return result, [url for url in calls if "/streams" in url]

    def test_malformed_then_valid_recovers_and_reports_retry(self):
        with patch.object(youtube.time, "sleep") as sleep:
            (items, sources), calls = self.collect(["<html>temporary page</html>", channel_page(ended_renderer())])
        sleep.assert_called_once_with(0.5)
        self.assertEqual(len(calls), 2)
        self.assertTrue(sources[0]["ok"])
        self.assertEqual(len(items), 1)
        self.assertIn("streams attempt 1", " ".join(sources[0]["diagnostics"]))

    def test_repeated_malformed_stops_after_two_attempts(self):
        (items, sources), calls = self.collect(["bad", "bad", channel_page(ended_renderer())])
        self.assertEqual(len(calls), 2)
        self.assertFalse(sources[0]["ok"])
        self.assertEqual(items, [])
        self.assertIn("Missing or malformed ytInitialData", sources[0]["error"])

    def test_valid_identity_failure_is_not_retried(self):
        (items, sources), calls = self.collect([channel_page(ended_renderer(), channel_id="wrong")])
        self.assertEqual(len(calls), 1)
        self.assertFalse(sources[0]["ok"])
        self.assertEqual(items, [])

    def test_retry_response_must_still_pass_identity(self):
        (items, sources), calls = self.collect(["bad", channel_page(ended_renderer(), channel_id="wrong")])
        self.assertEqual(len(calls), 2)
        self.assertFalse(sources[0]["ok"])
        self.assertEqual(items, [])

    def test_expired_deadline_does_not_retry(self):
        with patch.object(youtube.time, "sleep") as sleep:
            (items, sources), calls = self.collect(["bad"], deadline=0)
        sleep.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertFalse(sources[0]["ok"])
        self.assertEqual(items, [])

    def test_insufficient_request_budget_does_not_sleep_or_retry(self):
        with patch.object(youtube.time, "monotonic", return_value=0), \
                patch.object(youtube.time, "sleep") as sleep:
            (_, sources), calls = self.collect(["bad"], deadline=5)
        sleep.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertFalse(sources[0]["ok"])

    def test_deadline_expiring_during_pause_does_not_start_retry(self):
        with patch.object(youtube.time, "monotonic", side_effect=[0, 12]), \
                patch.object(youtube.time, "sleep") as sleep:
            (_, sources), calls = self.collect(["bad"], deadline=11)
        sleep.assert_called_once_with(0.5)
        self.assertEqual(len(calls), 1)
        self.assertFalse(sources[0]["ok"])

    def test_explicit_empty_tab_is_success_without_retry(self):
        import json
        data = youtube._embedded(channel_page(ended_renderer()), "ytInitialData")
        tab = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
        tab["content"] = {"messageRenderer": {"text": {"simpleText": "No streams"}}}
        (items, sources), calls = self.collect(["var ytInitialData = " + json.dumps(data)])
        self.assertEqual(len(calls), 1)
        self.assertTrue(sources[0]["ok"])
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()

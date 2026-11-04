"""The reporter file says what really happened to each story's source.

Measured 2026-11-04: 64 of 71 lost stories carried reason "reporter_invalid" although the model
never saw them, and bot walls were recorded as plain "robots" or "error".
"""

import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from email.message import Message

import phong_bao.newsroom as newsroom
from phong_bao.newsroom import Articles, FixtureArticles, _reporter
from phong_bao.registry import load_registry
from radar import summary_pipeline
from radar.transport import ResponseText


FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"
ARTICLE = "A readable article body about the launch. " * 80


def _story(sid, url):
    return {"id": sid, "title": f"Story {sid}", "url": url, "published_at": "2026-11-02T00:00:00Z"}


class ReporterLabelTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = json.loads((FIXTURES / "discovery.json").read_text(encoding="utf-8"))
        network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.sent = []

    def run_reporter(self, stories, articles, rows=None, intake=None):
        rows = rows or {}

        def fake_desk(desk, payload, *args, **kwargs):
            self.sent.extend(item["id"] for item in payload)
            return {item["id"]: {"id": item["id"], **rows[item["id"]], "provider": "agy", "boat": "gemini"}
                    for item in payload if item["id"] in rows}, []

        intake = intake or {story["id"]: {"pass": True} for story in stories}
        with patch.object(newsroom, "_agent_desk", side_effect=fake_desk), \
                patch.object(newsroom.Articles, "search", return_value=[]):
            output, _ = _reporter(stories, intake, articles, self.tools, self.discovery, None, [])
        return output

    def test_story_never_sent_to_the_model_is_not_an_invalid_reply(self):
        story = _story("lost-bloomberg", "https://www.bloomberg.com/news/articles/2026-11-02/example")
        output = self.run_reporter([story], FixtureArticles({"articles": {}}))
        row = output[story["id"]]
        self.assertEqual(self.sent, [])
        self.assertFalse(row["readable"])
        self.assertFalse(row["invalid_response"])
        self.assertEqual(row["reason"], "no readable same-event candidate")
        self.assertEqual(row["representative_status"], "unavailable")

    def test_intake_hold_is_labelled_as_such(self):
        story = _story("held", "https://example.com/held")
        output = self.run_reporter([story], FixtureArticles({"articles": {}}),
                                   intake={story["id"]: {"pass": False}})
        self.assertEqual(output[story["id"]]["reason"], "intake hold")
        self.assertFalse(output[story["id"]]["invalid_response"])
        self.assertEqual(output[story["id"]]["representative_status"], "not_checked")

    def test_malformed_reply_for_a_sent_story_is_still_invalid(self):
        story = _story("sent", "https://example.com/readable")
        output = self.run_reporter([story], FixtureArticles({"articles": {story["url"]: {"text": ARTICLE}}}),
                                   rows={story["id"]: {"selected_url": ["not a URL"], "same_event": True,
                                                       "reason": "x"}})
        self.assertEqual(self.sent, [story["id"], story["id"]])  # first try and the retry
        self.assertTrue(output[story["id"]]["invalid_response"])
        self.assertEqual(output[story["id"]]["reason"], "reporter_invalid")

    def test_unsent_and_sent_stories_in_one_cycle_keep_separate_labels(self):
        readable = _story("readable", "https://example.com/readable")
        lost = _story("lost", "https://example.com/lost")
        output = self.run_reporter(
            [readable, lost], FixtureArticles({"articles": {readable["url"]: {"text": ARTICLE}}}),
            rows={readable["id"]: {"selected_url": readable["url"], "same_event": True, "reason": "same event"}})
        self.assertEqual(self.sent, [readable["id"]])
        self.assertTrue(output[readable["id"]]["readable"])
        self.assertEqual(output[lost["id"]]["reason"], "no readable same-event candidate")
        self.assertEqual(sum(row["invalid_response"] for row in output.values()), 0)

    def test_representative_status_names_the_http_cause(self):
        def status_error(url, code):
            return HTTPError(url, code, "Forbidden", Message(), None)

        routes = {
            "https://www.cnbc.com/robots.txt": status_error("https://www.cnbc.com/robots.txt", 403),
            "https://openai.com/robots.txt": ResponseText("User-agent: *\nAllow: /", status=200),
            "https://openai.com/index/example": status_error("https://openai.com/index/example", 403),
            "https://x.com/robots.txt": ResponseText("User-agent: *\nDisallow: /", status=200),
        }

        def read_url(url, **kwargs):
            answer = routes[url]
            if isinstance(answer, Exception):
                raise answer
            return answer

        stories = [_story("cnbc", "https://www.cnbc.com/2026/11/02/example.html"),
                   _story("openai", "https://openai.com/index/example"),
                   _story("x", "https://x.com/someone/status/1")]
        with patch.object(summary_pipeline.transport, "read_url", side_effect=read_url):
            output = self.run_reporter(stories, Articles())
        self.assertEqual({sid: row["representative_status"] for sid, row in output.items()},
                         {"cnbc": "robots:unavailable_403", "openai": "error:http_403", "x": "robots:disallow"})
        self.assertTrue(all(row["reason"] == "no readable same-event candidate" for row in output.values()))


if __name__ == "__main__":
    unittest.main()

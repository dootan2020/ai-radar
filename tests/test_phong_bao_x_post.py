"""A story that is an X post the collector already fetched is read from that stored text.

Measured 2026-11-05: x.com refuses the reader (robots.txt), yet the official API had already put the
post's full text in the story's coverage. The story below is the Mistral post from that day's snapshot.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import phong_bao.newsroom as newsroom
from phong_bao.newsroom import Articles, FixtureArticles, _reporter
from phong_bao.paywall import held_for_paywall
from phong_bao.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures"
POST_URL = "https://x.com/MistralAI/status/2117670644506861900"
POST_TEXT = ("Mistral Large 4 joins the model lineup on Open Math OS. 1.05T open weights, 1M context, live today for "
             "approved teams. Open Math OS is a research workspace where mathematicians and AI agents work on shared "
             "projects, built only on open models so the community can inspect and run https://t.co/IEKpgbV9ch")


def story(text=POST_TEXT, source="x-mistralai", url=POST_URL):
    return {"id": "64b4a391505d5648b786", "title": "Mistral Large 4 joins the model lineup on Open Math OS.",
            "url": url, "published_at": "2026-11-03T17:30:00Z",
            "coverage": [{"id": "056e1fcf7413c986de53", "source": source, "publisher": "x:@MistralAI"
                          if source.startswith("x-") else "hacker-news", "url": url, "summary": text,
                          "post_id": "2117670644506861900" if source.startswith("x-") else None,
                          "published_at": "2026-11-03T17:30:00Z"}]}


class XPostTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = json.loads((FIXTURES / "phong-bao" / "discovery.json").read_text(encoding="utf-8"))
        network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.sent = []

    def run_reporter(self, stories, articles):
        def fake_desk(desk, payload, *args, **kwargs):
            self.sent.extend(payload)
            return {item["id"]: {"id": item["id"], "selected_url": item["representative_url"], "same_event": True,
                                 "reason": "own post", "provider": "agy", "boat": "gemini"} for item in payload}, []

        with patch.object(newsroom, "_agent_desk", side_effect=fake_desk), \
                patch.object(newsroom.Articles, "search", return_value=[]):
            output, _ = _reporter(stories, {s["id"]: {"pass": True} for s in stories}, articles,
                                  self.tools, self.discovery, None, [])
        return output

    def test_collected_post_is_the_readable_source_without_fetching_x(self):
        articles = Articles()
        with patch.object(newsroom, "fetch_article_result", side_effect=AssertionError("x.com fetched")):
            row = self.run_reporter([story()], articles)["64b4a391505d5648b786"]
            self.assertEqual(articles.read(POST_URL), (POST_TEXT, None))  # the writer reads the same text
        self.assertTrue(row["readable"])
        self.assertEqual(row["selected_url"], POST_URL)
        self.assertEqual(row["representative_status"], "readable")
        self.assertEqual(self.sent[0]["candidates"][0]["text"], POST_TEXT)

    def test_short_post_stays_unreadable_and_is_not_held(self):
        row = self.run_reporter([story(text="Mistral Large 4 is live.")], FixtureArticles({"articles": {}}))
        row = row["64b4a391505d5648b786"]
        self.assertFalse(row["readable"])
        self.assertEqual(self.sent, [])
        self.assertFalse(held_for_paywall(POST_URL, row["readable"], row["representative_status"]))

    def test_x_link_that_arrived_through_another_source_is_unchanged(self):
        articles = FixtureArticles({"articles": {}})
        row = self.run_reporter([story(source="hn-front")], articles)["64b4a391505d5648b786"]
        self.assertFalse(row["readable"])
        self.assertEqual(articles.remembered, {})


if __name__ == "__main__":
    unittest.main()

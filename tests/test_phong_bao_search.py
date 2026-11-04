"""The reporter looks for the same event at another outlet when a story's own article is unreadable.

Measured 2026-11-05: Bloomberg's own pages are unreadable for every approved story, and the old
full-title Hacker News query found a hit for 1 of the 26 Bloomberg articles. The fixture is the real
Hacker News Algolia answer for the Marvell-Lumentum story, captured that day.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from email.message import Message
from urllib.parse import parse_qs, urlsplit

import phong_bao.newsroom as newsroom
from phong_bao import search
from phong_bao.newsroom import Articles, _reporter
from phong_bao.registry import load_registry
from radar.transport import ResponseText

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURE = json.loads((FIXTURES / "tim-bai" / "hn-algolia-marvell-lumentum.json").read_text(encoding="utf-8"))
STORY = {**CAPTURE["story"], "coverage": []}
TECHCRUNCH = "https://techcrunch.com/2026/11/02/in-one-of-the-largest-deals-in-tech-history-marvell-buys-lumentum-for-115b/"
ARTICLE = "Marvell agreed to buy Lumentum in an all-stock deal valued at about $115 billion. " * 40


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class OfflineArticles(Articles):
    """Real search code over stored HTTP answers; article reads come from a dict."""

    def __init__(self, routes, texts):
        super().__init__()
        self.routes, self.texts, self.requested, self.reads = routes, texts, [], []

    def read(self, url):
        self.reads.append(url)
        return (self.texts[url], None) if url in self.texts else ("", "error")

    def read_url(self, url, **kwargs):
        self.requested.append(url)
        answer = self.routes(url)
        if isinstance(answer, Exception):
            raise answer
        return answer


def hn_routes(url):
    if url == "https://hn.algolia.com/robots.txt":
        return ResponseText("User-agent: *\nAllow: /", status=200, url=url)
    if url.startswith(search.HN_ALGOLIA):
        return ResponseText(json.dumps(CAPTURE["response"]), status=200, url=url)
    raise AssertionError(f"unexpected request {url}")


class QueryAndRankingTests(unittest.TestCase):
    def test_query_keeps_every_title_word_optional_inside_the_event_window(self):
        url = search.hn_algolia_url(STORY)
        self.assertEqual(url, CAPTURE["request_url"])
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["query"], params["optionalWords"])
        self.assertIn("lumentum", params["query"][0].split())
        self.assertNotIn("for", params["query"][0].split())
        self.assertEqual(params["numericFilters"], ["created_at_i>=1793535300,created_at_i<=1793794500"])

    def test_amounts_and_hyphenated_words_match_their_plain_spelling(self):
        bloomberg = "Anthropic Revenue Hits Nearly $17 Billion Before Mega-IPO"
        cnbc = "Anthropic reports $17B in Q3 revenue, commitments of $895B in revised S-1"
        shared = set(search.distinctive_words(bloomberg)) & set(search.distinctive_words(cnbc))
        self.assertEqual(shared, {"anthropic", "revenue", "17"})
        self.assertIn("ipo", search.distinctive_words(bloomberg))

    def test_ranking_reads_only_other_publishers_that_share_the_story_words(self):
        hits = search.parse_hn_algolia(json.dumps(CAPTURE["response"]))
        ranked = search.rank(STORY, hits)
        urls = [hit["url"] for hit in ranked]
        self.assertEqual(len(urls), 3)  # the press release appears twice in the answer, read once
        self.assertIn(TECHCRUNCH, urls)
        self.assertTrue(any("investor.marvell.com" in url for url in urls))
        self.assertTrue(any("reuters.com" in url for url in urls))
        self.assertFalse(any("theverge.com" in url or "newrepublic.com" in url for url in urls))

    def test_ranking_drops_same_publisher_old_coverage_and_caps_reads(self):
        story = {"title": "Canva Announces Layoffs, Job Changes for About 22% of Workforce",
                 "url": "https://www.bloomberg.com/news/articles/2026-11-03/canva", "published_at": "2026-11-03T22:35:00Z"}
        hits = [{"title": "Canva layoffs hit 22% of staff", "url": f"https://outlet{n}.example/canva",
                 "published_at": "2026-11-04T01:00:00Z"} for n in range(6)]
        hits += [{"title": "Canva layoffs explained", "url": "https://www.bloomberg.com/news/other", "published_at": "2026-11-04T01:00:00Z"},
                 {"title": "Canva layoffs last year", "url": "https://old.example/canva", "published_at": "2025-11-04T01:00:00Z"},
                 {"title": "Canva launches a design tool", "url": "https://one-word.example/canva", "published_at": "2026-11-04T01:00:00Z"}]
        ranked = search.rank(story, hits)
        self.assertEqual(len(ranked), search.READS_PER_STORY)
        self.assertTrue(all(hit["url"].startswith("https://outlet") for hit in ranked))


class SearchRequestTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def run_search(self, routes, budget=None, story=STORY):
        articles = OfflineArticles(routes, {})
        budget = budget or search.SearchBudget()
        with patch.object(search.transport, "read_url", side_effect=articles.read_url):
            return articles.search(story, ["hn-algolia"], budget), budget, articles

    def test_search_checks_robots_then_returns_ranked_candidates(self):
        found, budget, articles = self.run_search(hn_routes)
        self.assertEqual(articles.requested[0], "https://hn.algolia.com/robots.txt")
        self.assertIn(TECHCRUNCH, [hit["url"] for hit in found])
        self.assertEqual(budget.events[0]["status"], "200:18")  # two Ask HN hits carry no link

    def test_robots_refusal_and_http_errors_return_nothing(self):
        def disallowed(url):
            return ResponseText("User-agent: *\nDisallow: /", status=200, url=url)

        def failing(url):
            if url.endswith("robots.txt"):
                return hn_routes(url)
            return HTTPError(url, 503, "Unavailable", Message(), None)

        for routes, status in ((disallowed, "robots"), (failing, "HTTPError")):
            with self.subTest(status=status):
                found, budget, _ = self.run_search(routes)
                self.assertEqual(found, [])
                self.assertEqual(budget.events[0]["status"], status)

    def test_query_cap_stops_searching_for_the_rest_of_the_cycle(self):
        budget = search.SearchBudget(queries=1)
        self.run_search(hn_routes, budget)
        found, budget, articles = self.run_search(hn_routes, budget)
        self.assertEqual(found, [])
        self.assertEqual(articles.requested, [])
        self.assertEqual(budget.events[-1]["event"], "budget_exhausted")

    def test_budget_never_takes_more_than_half_the_desk_time_left(self):
        clock = Clock()
        budget = search.SearchBudget(deadline=clock.now + 100, clock=clock)
        self.assertEqual(budget.left(), 50)
        budget = search.SearchBudget(deadline=clock.now + 3600, clock=clock)
        self.assertEqual(budget.left(), search.SEARCH_SECONDS)
        clock.now += search.SEARCH_SECONDS
        self.assertFalse(budget.take_query())


class ReporterSearchTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = json.loads((FIXTURES / "phong-bao" / "discovery.json").read_text(encoding="utf-8"))
        network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.sent = []

    def run_reporter(self, stories, articles, rows, raw_dir=None):
        def fake_desk(desk, payload, *args, **kwargs):
            self.sent.extend(payload)
            return {item["id"]: {"id": item["id"], **rows[item["id"]], "provider": "agy", "boat": "gemini"}
                    for item in payload if item["id"] in rows}, []

        with patch.object(newsroom, "_agent_desk", side_effect=fake_desk), \
                patch.object(search.transport, "read_url", side_effect=articles.read_url):
            output, _ = _reporter(stories, {story["id"]: {"pass": True} for story in stories}, articles,
                                  self.tools, self.discovery, None, [], raw_dir)
        return output

    def test_unreadable_story_gets_an_independent_report_the_model_accepts(self):
        articles = OfflineArticles(hn_routes, {TECHCRUNCH: ARTICLE})
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_reporter([STORY], articles, {STORY["id"]: {
                "selected_url": TECHCRUNCH, "same_event": True, "reason": "same deal"}}, Path(directory))
            events = json.loads((Path(directory) / "tim-kiem.json").read_text(encoding="utf-8"))["searches"]
        row = output[STORY["id"]]
        self.assertTrue(row["readable"])
        self.assertEqual(row["selected_url"], TECHCRUNCH)
        self.assertEqual([c["url"] for c in self.sent[0]["candidates"]], [TECHCRUNCH])
        self.assertEqual(events, [{"runner": "hn-algolia", "id": STORY["id"], "status": "200:18",
                                   "seconds": events[0]["seconds"]}])

    def test_the_model_still_decides_same_event(self):
        articles = OfflineArticles(hn_routes, {TECHCRUNCH: ARTICLE})
        output = self.run_reporter([STORY], articles, {STORY["id"]: {
            "selected_url": None, "same_event": False, "reason": "different deal"}})
        self.assertFalse(output[STORY["id"]]["readable"])
        self.assertEqual(output[STORY["id"]]["reason"], "different deal")

    def test_at_most_three_readable_search_results_reach_the_model(self):
        answer = {"hits": [{"title": f"Marvell buys Lumentum for $115B, report {n}", "url": f"https://outlet{n}.example/marvell",
                            "created_at": "2026-11-02T18:00:00Z"} for n in range(5)]}

        def routes(url):
            if url.endswith("robots.txt"):
                return hn_routes(url)
            return ResponseText(json.dumps(answer), status=200, url=url)

        articles = OfflineArticles(routes, {hit["url"]: ARTICLE for hit in answer["hits"]})
        self.run_reporter([STORY], articles, {STORY["id"]: {"selected_url": None, "same_event": False, "reason": "x"}})
        self.assertEqual(len(self.sent[0]["candidates"]), search.READABLE_PER_STORY)
        self.assertEqual(len(articles.reads), 1 + search.READABLE_PER_STORY)  # own article, then three results

    def test_readable_story_is_never_searched(self):
        readable = {**STORY, "id": "readable", "url": "https://example.com/marvell"}
        articles = OfflineArticles(hn_routes, {readable["url"]: ARTICLE})
        self.run_reporter([readable], articles, {"readable": {
            "selected_url": readable["url"], "same_event": True, "reason": "own article"}})
        self.assertEqual(articles.requested, [])

    def test_search_failure_keeps_the_reporter_running(self):
        articles = OfflineArticles(lambda url: OSError("connection reset"), {})
        output = self.run_reporter([STORY], articles, {})
        self.assertEqual(self.sent, [])
        self.assertEqual(output[STORY["id"]]["reason"], "no readable same-event candidate")
        self.assertFalse(output[STORY["id"]]["invalid_response"])


if __name__ == "__main__":
    unittest.main()

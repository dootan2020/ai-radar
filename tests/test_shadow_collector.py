"""Offline unit tests for radar.shadow_collector.

Verifies all shadow collector functionality strictly offline using fixtures and mock transports:
- Watchlist query generation and URL encoding
- Candidate loading (fixed feeds, queries, signals)
- Google News RSS search parsing (with source url and publisher)
- Wikipedia pageviews REST API signal parsing
- Google Trends VN RSS parsing
- OpenRouter models list parsing
- Bluesky trending topics parsing
- Hacker News Algolia Show HN parsing
- GDELT DOC API parsing
- Reddit .json parsing
- Robots.txt honouring and caching
- GDELT >= 6s spacing
- Snapshot JSON, JSONL stream, and Markdown summary output generation
- Main CLI execution
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

from radar.shadow_collector import (
    GDELT_MIN_INTERVAL,
    PARSER_REGISTRY,
    build_google_news_url,
    build_wikipedia_pageviews_url,
    check_robots,
    collect_all,
    collect_candidate,
    format_iso_utc,
    load_shadow_candidates,
    load_watchlist,
    main,
    parse_bluesky_trending,
    parse_date_safely,
    parse_federal_register,
    parse_gdelt_doc,
    parse_generic_feed,
    parse_google_news_rss,
    parse_google_trends_rss,
    parse_hn_algolia,
    parse_openrouter_models,
    parse_reddit_json,
    parse_wikipedia_pageviews,
    render_markdown_summary,
    write_json_snapshot,
    write_jsonl_records,
)
from radar.transport import ResponseText

SAMPLE_GOOGLE_NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>"Sam Altman" - Google News</title>
    <link>https://news.google.com/search?q=%22Sam+Altman%22&amp;hl=en-US&amp;gl=US&amp;ceid=US%3Aen</link>
    <item>
      <title>OpenAI CEO Sam Altman outlines future AI infrastructure roadmap - TechCrunch</title>
      <link>https://news.google.com/rss/articles/CBMiVWh0dHBzOi8vdGVjaGNydW5jaC5jb20vMjAyNi8xMC8wNC9zYW0tYWx0bWFuLWNvbXB1dGUtbmVlZHMv0gEA?oc=5</link>
      <guid isPermaLink="false">CBMiVWh0dHBzOi8vdGVjaGNydW5jaC5jb20vMjAyNi8xMC8wNC9zYW0tYWx0bWFuLWNvbXB1dGUtbmVlZHMv0gEA</guid>
      <pubDate>Sun, 04 Oct 2026 18:30:00 GMT</pubDate>
      <description>&lt;a href="..."&gt;Sam Altman outlines compute...&lt;/a&gt;</description>
      <source url="https://techcrunch.com">TechCrunch</source>
    </item>
    <item>
      <title>Sam Altman attends White House tech summit - Reuters</title>
      <link>https://news.google.com/rss/articles/CBMiVWh0dHBzOi8vcmV1dGVycy5jb20vYXJ0aWNsZS8xMjM0?oc=5</link>
      <guid isPermaLink="false">guid2</guid>
      <pubDate>Sun, 04 Oct 2026 14:15:00 GMT</pubDate>
      <description>Reuters report on Altman</description>
      <source url="https://www.reuters.com">Reuters</source>
    </item>
    <item>
      <title>Personal portfolio update without source tag - The Verge</title>
      <link>https://news.google.com/rss/articles/CBMiVWh0dHBzOi8vdGhldmVyZ2UuY29tL3Bvc3QvNTY3OA?oc=5</link>
      <guid isPermaLink="false">guid3</guid>
      <pubDate>Sat, 03 Oct 2026 10:00:00 GMT</pubDate>
      <description>No source element present here</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_WIKIPEDIA_PAGEVIEWS = json.dumps({
    "items": [
        {
            "project": "en.wikipedia",
            "article": "Artificial_intelligence",
            "granularity": "daily",
            "timestamp": "2026100200",
            "access": "all-access",
            "agent": "all-agents",
            "views": 12500
        },
        {
            "project": "en.wikipedia",
            "article": "Artificial_intelligence",
            "granularity": "daily",
            "timestamp": "2026100300",
            "access": "all-access",
            "agent": "all-agents",
            "views": 13000
        },
        {
            "project": "en.wikipedia",
            "article": "Artificial_intelligence",
            "granularity": "daily",
            "timestamp": "2026100400",
            "access": "all-access",
            "agent": "all-agents",
            "views": 19500
        }
    ]
})

SAMPLE_GOOGLE_TRENDS_VN = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trends/trendingsearches/daily" version="2.0">
  <channel>
    <title>Daily Search Trends (Vietnam)</title>
    <item>
      <title>Trí tuệ nhân tạo Gemini</title>
      <link>https://trends.google.com/trends/trendingsearches/daily?geo=VN#Tri+tue+nhan+tao+Gemini</link>
      <pubDate>Sun, 04 Oct 2026 23:00:00 +0700</pubDate>
      <ht:approx_traffic>10K+</ht:approx_traffic>
    </item>
    <item>
      <title>Bóng đá Ngoại hạng Anh</title>
      <link>https://trends.google.com/trends/trendingsearches/daily?geo=VN#Bong+da</link>
      <pubDate>Sun, 04 Oct 2026 21:00:00 +0700</pubDate>
      <ht:approx_traffic>100K+</ht:approx_traffic>
    </item>
  </channel>
</rss>
"""

SAMPLE_OPENROUTER_MODELS = json.dumps({
    "data": [
        {
            "id": "anthropic/claude-3.7-sonnet",
            "name": "Anthropic: Claude 3.7 Sonnet",
            "created": 1728000000,
            "description": "State-of-the-art hybrid reasoning model.",
            "context_length": 200000
        },
        {
            "id": "meta-llama/llama-3.3-70b-instruct",
            "name": "Meta: Llama 3.3 70B Instruct",
            "created": 1727900000,
            "description": "High capability open weights model.",
            "context_length": 128000
        }
    ]
})

SAMPLE_BLUESKY_TRENDING = json.dumps({
    "topics": [
        {"topic": "#ArtificialIntelligence", "count": 2500, "displayName": "Artificial Intelligence"},
        {"topic": "Claude", "count": 1200},
        {"topic": "SundayMorning", "count": 4500}
    ]
})

SAMPLE_HN_ALGOLIA = json.dumps({
    "hits": [
        {
            "objectID": "4000001",
            "title": "Show HN: Fast local inference for DeepSeek LLMs",
            "url": "https://github.com/developer/fast-deepseek",
            "author": "aismith",
            "created_at": "2026-10-04T15:20:00.000Z",
            "points": 180
        },
        {
            "objectID": "4000002",
            "title": "Show HN: A minimalist terminal pomodoro timer in C",
            "url": "https://github.com/developer/pomo",
            "author": "ccoder",
            "created_at": "2026-10-04T12:00:00.000Z",
            "points": 45
        }
    ]
})

SAMPLE_GDELT_DOC = json.dumps({
    "articles": [
        {
            "url": "https://example.com/ai-summit-2026",
            "title": "International Summit Sets Frontier AI Guardrails",
            "seendate": "20261004T180000Z",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "United States"
        }
    ]
})

SAMPLE_REDDIT_JSON = json.dumps({
    "data": {
        "children": [
            {
                "data": {
                    "title": "GGUF quants for Qwen-2.5-Coder now available",
                    "url": "https://huggingface.co/models/qwen-coder-gguf",
                    "permalink": "/r/LocalLLaMA/comments/xyz123/gguf_quants_for_qwen/",
                    "author": "local_dev",
                    "subreddit": "LocalLLaMA",
                    "created_utc": 1728040000
                }
            }
        ]
    }
})

SAMPLE_ROBOTS_TXT_ALLOW = "User-agent: *\nAllow: /\n"
SAMPLE_ROBOTS_TXT_DISALLOW = "User-agent: *\nDisallow: /\n"


def make_mock_fetch(mapping):
    """Create offline mock fetch returning ResponseText from a mapping dict."""
    def _fetch(url, timeout=10):
        for pattern, val in mapping.items():
            if pattern in url:
                if isinstance(val, Exception):
                    raise val
                status, text, content_type = val
                res = ResponseText(text, status=status, url=url)
                res.content_type = content_type
                res.error = None if 200 <= status < 400 else f"HTTP {status}"
                return res
        res = ResponseText("", status=404, url=url)
        res.content_type = "text/plain"
        res.error = "HTTP 404"
        return res
    return _fetch


class WatchlistAndCandidateLoadingTests(unittest.TestCase):
    def test_load_watchlist_structure(self):
        wl = load_watchlist()
        self.assertGreater(len(wl), 0)
        # Check expected categories
        categories = {c["category"] for c in wl}
        self.assertIn("watchlist-people", categories)
        self.assertIn("watchlist-topics", categories)
        self.assertIn("watchlist-vietnamese", categories)

        # Check required names from prompt
        names = [c["name"] for c in wl]
        self.assertTrue(any("Elon Musk" in n for n in names))
        self.assertTrue(any("Sam Altman" in n for n in names))
        self.assertTrue(any("Dario Amodei" in n for n in names))
        self.assertTrue(any("Jensen Huang" in n for n in names))
        self.assertTrue(any("Demis Hassabis" in n for n in names))
        self.assertTrue(any("Mark Zuckerberg" in n for n in names))
        self.assertTrue(any("Donald Trump" in n for n in names))
        self.assertTrue(any("Thibault Sottiaux" in n for n in names))
        self.assertTrue(any("Claude usage limit" in n for n in names))
        self.assertTrue(any("Codex rate limit" in n for n in names))
        self.assertTrue(any("ChatGPT usage limit reset" in n for n in names))
        self.assertTrue(any("AI model release" in n for n in names))
        self.assertTrue(any("AI regulation" in n for n in names))
        self.assertTrue(any("Tin tức AI Việt Nam" in n or "Google News VN" in n for n in names))

    def test_build_google_news_url_english(self):
        url = build_google_news_url('"Sam Altman"', edition="en", time_window="1d")
        self.assertTrue(url.startswith("https://news.google.com/rss/search?"))
        self.assertIn("hl=en-US", url)
        self.assertIn("gl=US", url)
        self.assertIn("ceid=US:en", url)
        self.assertIn("when%3A1d", url)

    def test_build_google_news_url_vietnamese(self):
        url = build_google_news_url('"trí tuệ nhân tạo" OR "AI"', edition="vi", time_window="1d")
        self.assertTrue(url.startswith("https://news.google.com/rss/search?"))
        self.assertIn("hl=vi", url)
        self.assertIn("gl=VN", url)
        self.assertIn("ceid=VN:vi", url)
        self.assertIn("when%3A1d", url)

    def test_load_shadow_candidates_has_three_kinds(self):
        candidates = load_shadow_candidates()
        self.assertGreaterEqual(len(candidates), 20)

        kinds = {c.get("kind") for c in candidates}
        self.assertIn("fixed feed", kinds)
        self.assertIn("query", kinds)
        self.assertIn("signal", kinds)

        # Check unique IDs
        ids = [c["id"] for c in candidates]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate candidate IDs found: {ids}")

        # Check required fields
        for c in candidates:
            self.assertIn("id", c)
            self.assertIn("name", c)
            self.assertIn("kind", c)
            self.assertIn("url", c)
            self.assertTrue(c["url"].startswith("http"))


class GoogleNewsRssParserTests(unittest.TestCase):
    def test_parse_google_news_rss_extracts_items_and_publisher(self):
        cand = {"id": "wl-sam-altman", "name": "Sam Altman"}
        items, numbers, error = parse_google_news_rss(SAMPLE_GOOGLE_NEWS_RSS, cand)

        self.assertIsNone(error)
        self.assertEqual(len(items), 3)

        # Item 1 with source url
        it1 = items[0]
        self.assertIn("Sam Altman", it1["title"])
        self.assertEqual(it1["publisher"], "TechCrunch")
        self.assertEqual(it1["url"], "https://techcrunch.com")
        self.assertEqual(it1["source_url"], "https://techcrunch.com")
        self.assertEqual(it1["published_at"], "2026-10-04T18:30:00Z")

        # Item 2 with source url
        it2 = items[1]
        self.assertEqual(it2["publisher"], "Reuters")
        self.assertEqual(it2["url"], "https://www.reuters.com")
        self.assertEqual(it2["published_at"], "2026-10-04T14:15:00Z")

        # Item 3 without <source> tag, fallback title extraction
        it3 = items[2]
        self.assertEqual(it3["publisher"], "The Verge")
        self.assertTrue(it3["url"].startswith("https://news.google.com/rss/articles/"))

        # Numbers
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers["item_count"], 3)
        self.assertGreater(numbers["ai_count"], 0)

    def test_parse_google_news_empty(self):
        cand = {"id": "wl-empty", "name": "Empty"}
        items, numbers, error = parse_google_news_rss("", cand)
        self.assertEqual(items, [])
        self.assertIsNotNone(error)


class SignalParsersTests(unittest.TestCase):
    def test_parse_wikipedia_pageviews(self):
        cand = {"id": "wikipedia-ai-pageviews", "article": "Artificial_intelligence"}
        items, numbers, error = parse_wikipedia_pageviews(SAMPLE_WIKIPEDIA_PAGEVIEWS, cand)

        self.assertIsNone(error)
        self.assertEqual(items, [])
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers["article"], "Artificial_intelligence")
        self.assertEqual(numbers["views_latest"], 19500)
        self.assertEqual(numbers["views_previous_day"], 13000)
        self.assertEqual(numbers["spike_ratio"], 1.5)
        self.assertEqual(len(numbers["daily_series"]), 3)

    def test_parse_google_trends_vn(self):
        cand = {"id": "google-trends-vn"}
        items, numbers, error = parse_google_trends_rss(SAMPLE_GOOGLE_TRENDS_VN, cand)

        self.assertIsNone(error)
        self.assertEqual(len(items), 2)
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers["total_trends"], 2)
        self.assertEqual(numbers["ai_trend_count"], 1)
        self.assertEqual(numbers["topics"][0]["approx_traffic"], "10K+")
        self.assertTrue(numbers["topics"][0]["is_ai"])
        self.assertFalse(numbers["topics"][1]["is_ai"])

    def test_parse_openrouter_models(self):
        cand = {"id": "openrouter-models"}
        items, numbers, error = parse_openrouter_models(SAMPLE_OPENROUTER_MODELS, cand)

        self.assertIsNone(error)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Anthropic: Claude 3.7 Sonnet")
        self.assertEqual(items[0]["url"], "https://openrouter.ai/models/anthropic/claude-3.7-sonnet")
        self.assertEqual(items[0]["publisher"], "anthropic")
        self.assertEqual(items[0]["published_at"], "2024-10-04T00:00:00Z")

        self.assertIsNotNone(numbers)
        self.assertEqual(numbers["total_models"], 2)
        self.assertEqual(numbers["newest_created_timestamp"], 1728000000)
        self.assertEqual(numbers["newest_model_id"], "anthropic/claude-3.7-sonnet")

    def test_parse_bluesky_trending(self):
        cand = {"id": "bluesky-trending"}
        items, numbers, error = parse_bluesky_trending(SAMPLE_BLUESKY_TRENDING, cand)

        self.assertIsNone(error)
        self.assertEqual(items, [])
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers["total_topics"], 3)
        self.assertEqual(numbers["ai_topic_count"], 2)  # #ArtificialIntelligence and Claude

    def test_parse_hn_algolia(self):
        cand = {"id": "hn-show-hn"}
        items, numbers, error = parse_hn_algolia(SAMPLE_HN_ALGOLIA, cand)

        self.assertIsNone(error)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Show HN: Fast local inference for DeepSeek LLMs")
        self.assertEqual(items[0]["url"], "https://github.com/developer/fast-deepseek")
        self.assertEqual(items[0]["publisher"], "HN @aismith")
        self.assertEqual(items[0]["published_at"], "2026-10-04T15:20:00Z")
        self.assertEqual(numbers["total_hits"], 2)
        self.assertEqual(numbers["ai_hits_count"], 1)

    def test_parse_gdelt_doc(self):
        cand = {"id": "gdelt-ai-doc"}
        items, numbers, error = parse_gdelt_doc(SAMPLE_GDELT_DOC, cand)

        self.assertIsNone(error)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "International Summit Sets Frontier AI Guardrails")
        self.assertEqual(items[0]["url"], "https://example.com/ai-summit-2026")
        self.assertEqual(items[0]["publisher"], "example.com")
        self.assertEqual(items[0]["published_at"], "2026-10-04T18:00:00Z")
        self.assertEqual(numbers["article_count"], 1)

    def test_parse_reddit_json(self):
        cand = {"id": "reddit-localllama"}
        items, numbers, error = parse_reddit_json(SAMPLE_REDDIT_JSON, cand)

        self.assertIsNone(error)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "GGUF quants for Qwen-2.5-Coder now available")
        self.assertIn("LocalLLaMA", items[0]["url"])
        self.assertEqual(items[0]["publisher"], "r/LocalLLaMA u/local_dev")
        self.assertIsNotNone(items[0]["published_at"])
        self.assertEqual(numbers["post_count"], 1)


class CollectorPolitenessAndExecutionTests(unittest.TestCase):
    def test_collect_candidate_offline_successful(self):
        candidate = {
            "id": "wl-sam-altman",
            "name": "Sam Altman (Google News)",
            "kind": "query",
            "url": "https://news.google.com/rss/search?q=altman",
            "parser": "google_news_rss",
        }
        mock_fetch = make_mock_fetch({
            "https://news.google.com/robots.txt": (200, SAMPLE_ROBOTS_TXT_ALLOW, "text/plain"),
            "https://news.google.com/rss/search": (200, SAMPLE_GOOGLE_NEWS_RSS, "application/rss+xml"),
        })

        record = collect_candidate(candidate, fetch_fn=mock_fetch)
        self.assertEqual(record["candidate_id"], "wl-sam-altman")
        self.assertEqual(record["name"], "Sam Altman (Google News)")
        self.assertEqual(record["kind"], "query")
        self.assertEqual(record["http_status"], 200)
        self.assertIsNone(record["error"])
        self.assertEqual(record["item_count"], 3)
        self.assertEqual(len(record["items"]), 3)
        self.assertIsNotNone(record["request_time"])
        self.assertIn("item_count", record["numbers"])

    def test_collect_candidate_robots_disallow(self):
        candidate = {
            "id": "blocked-candidate",
            "name": "Blocked Candidate",
            "kind": "fixed feed",
            "url": "https://blocked.example.com/feed.xml",
            "parser": "rss",
        }
        mock_fetch = make_mock_fetch({
            "https://blocked.example.com/robots.txt": (200, SAMPLE_ROBOTS_TXT_DISALLOW, "text/plain"),
            "https://blocked.example.com/feed.xml": (200, "<rss></rss>", "application/rss+xml"),
        })

        record = collect_candidate(candidate, fetch_fn=mock_fetch)
        self.assertEqual(record["http_status"], None)
        self.assertEqual(record["error"], "Blocked by robots.txt")
        self.assertEqual(record["item_count"], 0)
        self.assertEqual(record["items"], [])

    def test_robots_cache_per_origin(self):
        fetch_calls = []

        def mock_fetch(url, timeout=10):
            fetch_calls.append(url)
            if "robots.txt" in url:
                return ResponseText(SAMPLE_ROBOTS_TXT_ALLOW, status=200, url=url)
            return ResponseText(SAMPLE_GOOGLE_NEWS_RSS, status=200, url=url)

        cache = {}
        c1 = {"id": "c1", "name": "C1", "kind": "query", "url": "https://news.google.com/rss/1", "parser": "google_news_rss"}
        c2 = {"id": "c2", "name": "C2", "kind": "query", "url": "https://news.google.com/rss/2", "parser": "google_news_rss"}

        collect_candidate(c1, fetch_fn=mock_fetch, robots_cache=cache)
        collect_candidate(c2, fetch_fn=mock_fetch, robots_cache=cache)

        # robots.txt should only be fetched once for news.google.com
        robots_fetches = [u for u in fetch_calls if "robots.txt" in u]
        self.assertEqual(len(robots_fetches), 1)

    def test_collect_candidate_handles_http_errors_gracefully(self):
        candidate = {
            "id": "err-candidate",
            "name": "Error Candidate",
            "kind": "fixed feed",
            "url": "https://err.example.com/feed.xml",
            "parser": "rss",
        }
        mock_fetch = make_mock_fetch({
            "https://err.example.com/robots.txt": (404, "Not Found", "text/plain"),
            "https://err.example.com/feed.xml": (403, "Forbidden", "text/html"),
        })

        record = collect_candidate(candidate, fetch_fn=mock_fetch)
        self.assertEqual(record["http_status"], 403)
        self.assertEqual(record["error"], "HTTP 403")
        self.assertEqual(record["item_count"], 0)

    def test_collect_all_runs_sequentially_and_aggregates_metadata(self):
        candidates = [
            {
                "id": "openrouter-models",
                "name": "OpenRouter Models",
                "kind": "signal",
                "url": "https://openrouter.ai/api/v1/models",
                "parser": "openrouter_models",
            },
            {
                "id": "wl-sam-altman",
                "name": "Sam Altman",
                "kind": "query",
                "url": "https://news.google.com/rss/search?q=altman",
                "parser": "google_news_rss",
            },
        ]
        mock_fetch = make_mock_fetch({
            "https://openrouter.ai/robots.txt": (404, "Not Found", "text/plain"),
            "https://openrouter.ai/api/v1/models": (200, SAMPLE_OPENROUTER_MODELS, "application/json"),
            "https://news.google.com/robots.txt": (200, SAMPLE_ROBOTS_TXT_ALLOW, "text/plain"),
            "https://news.google.com/rss/search": (200, SAMPLE_GOOGLE_NEWS_RSS, "application/rss+xml"),
        })

        metadata, records = collect_all(candidates, fetch_fn=mock_fetch, delay=0.0)

        self.assertEqual(len(records), 2)
        self.assertEqual(metadata["total_candidates"], 2)
        self.assertEqual(metadata["successful_candidates"], 2)
        self.assertEqual(metadata["failed_candidates"], 0)
        self.assertEqual(metadata["kinds_summary"]["signal"], 1)
        self.assertEqual(metadata["kinds_summary"]["query"], 1)
        self.assertEqual(metadata["total_items_collected"], 5)  # 2 models + 3 news items


class OutputSerializationTests(unittest.TestCase):
    def test_json_and_jsonl_output(self):
        records = [
            {
                "candidate_id": "test-c1",
                "name": "Test Candidate 1",
                "kind": "fixed feed",
                "request_time": "2026-10-05T06:00:00Z",
                "url": "https://example.com/feed",
                "http_status": 200,
                "error": None,
                "item_count": 1,
                "items": [
                    {
                        "title": "Article 1",
                        "url": "https://example.com/art1",
                        "publisher": "Example",
                        "published_at": "2026-10-05T05:00:00Z",
                    }
                ],
                "numbers": None,
            }
        ]
        metadata = {
            "run_id": "shadow-test",
            "started_at": "2026-10-05T06:00:00Z",
            "completed_at": "2026-10-05T06:00:01Z",
            "total_candidates": 1,
            "successful_candidates": 1,
            "failed_candidates": 0,
            "total_items_collected": 1,
            "kinds_summary": {"fixed feed": 1, "query": 0, "signal": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "snapshot.json"
            jsonl_path = Path(tmpdir) / "stream.jsonl"

            write_json_snapshot(records, metadata, json_path)
            write_jsonl_records(records, jsonl_path)

            # Validate snapshot JSON
            snapshot = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["run_id"], "shadow-test")
            self.assertEqual(len(snapshot["records"]), 1)
            self.assertEqual(snapshot["records"][0]["candidate_id"], "test-c1")

            # Validate stream JSONL
            lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            line_data = json.loads(lines[0])
            self.assertEqual(line_data["candidate_id"], "test-c1")

    def test_render_markdown_summary(self):
        records = [
            {
                "candidate_id": "test-c1",
                "name": "Test Candidate 1",
                "kind": "query",
                "request_time": "2026-10-05T06:00:00Z",
                "url": "https://news.google.com/rss",
                "http_status": 200,
                "error": None,
                "item_count": 5,
                "items": [],
                "numbers": {"ai_count": 3},
            }
        ]
        metadata = {
            "run_id": "shadow-test",
            "completed_at": "2026-10-05T06:00:01Z",
            "total_candidates": 1,
            "successful_candidates": 1,
            "failed_candidates": 0,
            "total_items_collected": 5,
            "kinds_summary": {"fixed feed": 0, "query": 1, "signal": 0},
        }

        summary = render_markdown_summary(records, metadata)
        self.assertIn("# Báo cáo Shadow Collector", summary)
        self.assertIn("`test-c1`", summary)
        self.assertIn("ai_count=3", summary)


class MainCliTests(unittest.TestCase):
    def test_main_cli_execution_with_mock_fetch(self):
        mock_fetch = make_mock_fetch({
            "https://openrouter.ai": (200, SAMPLE_OPENROUTER_MODELS, "application/json"),
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "out.json"
            jsonl_file = Path(tmpdir) / "out.jsonl"
            summary_file = Path(tmpdir) / "out.md"

            # Create a tiny candidates file
            cand_file = Path(tmpdir) / "tiny-candidates.json"
            cand_file.write_text(json.dumps({
                "fixed_feeds": [],
                "signals": [
                    {
                        "id": "openrouter-models",
                        "name": "OpenRouter Models",
                        "kind": "signal",
                        "url": "https://openrouter.ai/api/v1/models",
                        "parser": "openrouter_models",
                    }
                ]
            }), encoding="utf-8")

            empty_wl = Path(tmpdir) / "empty-wl.json"
            empty_wl.write_text(json.dumps({"people": [], "topics": [], "vietnamese": []}), encoding="utf-8")

            with patch("radar.shadow_collector.default_fetch", mock_fetch):
                ret = main([
                    "--candidates", str(cand_file),
                    "--watchlist", str(empty_wl),
                    "--output-json", str(json_file),
                    "--output-jsonl", str(jsonl_file),
                    "--output-summary", str(summary_file),
                    "--no-robots",
                    "--delay", "0.0",
                ])

            self.assertEqual(ret, 0)
            self.assertTrue(json_file.is_file())
            self.assertTrue(jsonl_file.is_file())
            self.assertTrue(summary_file.is_file())

            data = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertEqual(data["total_candidates"], 1)
            self.assertEqual(data["records"][0]["candidate_id"], "openrouter-models")

    def test_main_cli_kind_filtering(self):
        mock_fetch = make_mock_fetch({
            "https://openrouter.ai": (200, SAMPLE_OPENROUTER_MODELS, "application/json"),
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "out.json"
            jsonl_file = Path(tmpdir) / "out.jsonl"
            summary_file = Path(tmpdir) / "out.md"
            cand_file = Path(tmpdir) / "candidates.json"
            cand_file.write_text(json.dumps({
                "fixed_feeds": [
                    {"id": "ff1", "name": "FF1", "kind": "fixed feed", "url": "https://ff1.com/feed", "parser": "rss"}
                ],
                "signals": [
                    {"id": "sig1", "name": "Sig1", "kind": "signal", "url": "https://openrouter.ai/models", "parser": "openrouter_models"}
                ]
            }), encoding="utf-8")
            empty_wl = Path(tmpdir) / "empty-wl.json"
            empty_wl.write_text(json.dumps({"people": [], "topics": [], "vietnamese": []}), encoding="utf-8")

            with patch("radar.shadow_collector.default_fetch", mock_fetch):
                ret = main([
                    "--candidates", str(cand_file),
                    "--watchlist", str(empty_wl),
                    "--output-json", str(json_file),
                    "--output-jsonl", str(jsonl_file),
                    "--output-summary", str(summary_file),
                    "--kind", "signal",
                    "--no-robots",
                    "--delay", "0.0",
                ])

            self.assertEqual(ret, 0)
            data = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertEqual(data["total_candidates"], 1)
            self.assertEqual(data["records"][0]["candidate_id"], "sig1")


class ShadowCollectorEdgeCasesTests(unittest.TestCase):
    def test_gdelt_spacing_enforcement(self):
        candidates = [
            {"id": "gdelt-1", "name": "GDELT 1", "kind": "query", "url": "https://api.gdeltproject.org/doc1", "parser": "gdelt_doc"},
            {"id": "gdelt-2", "name": "GDELT 2", "kind": "query", "url": "https://api.gdeltproject.org/doc2", "parser": "gdelt_doc"},
        ]
        mock_fetch = make_mock_fetch({
            "https://api.gdeltproject.org": (200, SAMPLE_GDELT_DOC, "application/json"),
        })

        sleep_calls = []
        def fake_sleep(duration):
            sleep_calls.append(duration)

        with patch("time.sleep", side_effect=fake_sleep):
            metadata, records = collect_all(candidates, fetch_fn=mock_fetch, delay=0.0, check_robots_policy=False)

        self.assertEqual(len(records), 2)
        # Should have slept for GDELT pacing between call 1 and call 2
        gdelt_sleeps = [s for s in sleep_calls if s >= 5.0]
        self.assertGreaterEqual(len(gdelt_sleeps), 1)

    def test_connection_error_handling(self):
        candidate = {
            "id": "reddit-fail",
            "name": "Reddit LocalLLaMA",
            "kind": "query",
            "url": "https://www.reddit.com/r/LocalLLaMA/new.json",
            "parser": "reddit_json",
        }
        import urllib.error
        mock_fetch = make_mock_fetch({
            "https://www.reddit.com": urllib.error.URLError("getaddrinfo failed: connection refused"),
        })

        record = collect_candidate(candidate, fetch_fn=mock_fetch, check_robots_policy=False)
        self.assertEqual(record["candidate_id"], "reddit-fail")
        self.assertIsNone(record["http_status"])
        self.assertIn("URLError", record["error"])
        self.assertEqual(record["item_count"], 0)
        self.assertEqual(record["items"], [])

    def test_malformed_payload_handling(self):
        cand = {"id": "malformed"}
        # Google News malformed XML
        items, num, err = parse_google_news_rss("<bad><unclosed>", cand)
        self.assertEqual(items, [])
        self.assertIn("XML parse error", err)

        # Wikipedia malformed JSON
        items, num, err = parse_wikipedia_pageviews("{broken json", cand)
        self.assertEqual(items, [])
        self.assertIn("JSON parse error", err)

        # Google Trends malformed XML
        items, num, err = parse_google_trends_rss("<notxml", cand)
        self.assertEqual(items, [])
        self.assertIn("XML parse error", err)

        # OpenRouter malformed JSON
        items, num, err = parse_openrouter_models("invalid", cand)
        self.assertEqual(items, [])
        self.assertIn("JSON parse error", err)

    def test_date_parsing_varieties(self):
        # ISO
        self.assertEqual(parse_date_safely("2026-10-04T12:00:00Z"), "2026-10-04T12:00:00Z")
        # RFC 822
        self.assertEqual(parse_date_safely("Sun, 04 Oct 2026 12:00:00 GMT"), "2026-10-04T12:00:00Z")
        # Unix timestamp
        self.assertEqual(parse_date_safely(1728000000), "2024-10-04T00:00:00Z")
        # GDELT compact format
        self.assertEqual(parse_date_safely("20261004T180000Z"), "2026-10-04T18:00:00Z")
        # Invalid
        self.assertIsNone(parse_date_safely("not a date"))
        self.assertIsNone(parse_date_safely(None))

    def test_federal_register_parser(self):
        cand = {"id": "federal-register-ai"}
        sample = json.dumps({
            "results": [
                {
                    "title": "National AI Safety Initiative Notice",
                    "html_url": "https://www.federalregister.gov/documents/2026/10/01/notice-1",
                    "publication_date": "2026-10-01",
                }
            ]
        })
        items, numbers, error = parse_federal_register(sample, cand)
        self.assertIsNone(error)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "National AI Safety Initiative Notice")
        self.assertEqual(items[0]["publisher"], "Federal Register")
        self.assertEqual(items[0]["published_at"], "2026-10-01T00:00:00Z")
        self.assertEqual(numbers["document_count"], 1)

    def test_build_wikipedia_pageviews_url(self):
        fixed_time = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
        url = build_wikipedia_pageviews_url(now=fixed_time)
        self.assertTrue(url.startswith("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"))
        self.assertIn("Artificial_intelligence", url)
        self.assertIn("/daily/20261001/20261004", url)


if __name__ == "__main__":
    unittest.main()

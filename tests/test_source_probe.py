"""Offline tests for candidate sources probe (radar.source_probe).

Validates all probe operations strictly offline using fixtures and injected fetch transport:
- Direct RSS/Atom XML feed parsing
- HTML autodiscovery via <link rel="alternate" ...>
- 404 / HTTP error handling
- robots.txt parsing (allow and disallow)
- Duplicate detection against existing radar sources
- AI relevance classification and share calculation
- Markdown report formatting and candidate data loading
"""

import json
import unittest
from pathlib import Path

from radar.source_probe import (
    check_duplicate,
    check_robots,
    collect_existing_sources,
    extract_items_from_text,
    find_autodiscovered_feeds,
    load_candidates,
    normalize_url,
    parse_json_feed,
    probe_all,
    probe_candidate,
    render_markdown_report,
)
from radar.transport import ResponseText

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AI Lab Updates</title>
    <link>https://example.com/</link>
    <description>Latest AI releases</description>
    <item>
      <title>Announcing DeepSeek-V3: Open-Source Foundation Model</title>
      <link>https://example.com/deepseek-v3</link>
      <pubDate>Fri, 02 Oct 2026 12:00:00 GMT</pubDate>
      <description>We introduce DeepSeek-V3 with advanced reasoning.</description>
    </item>
    <item>
      <title>LLM benchmarks on mathematical problem solving</title>
      <link>https://example.com/benchmarks</link>
      <pubDate>Thu, 01 Oct 2026 10:00:00 GMT</pubDate>
      <description>Evaluation of frontier models on challenging math sets.</description>
    </item>
    <item>
      <title>Company annual holiday schedule and office closures</title>
      <link>https://example.com/holidays</link>
      <pubDate>Wed, 30 Sep 2026 08:00:00 GMT</pubDate>
      <description>Notes regarding administrative office operations.</description>
    </item>
    <item>
      <title>Claude 3.7 Sonnet hybrid reasoning capabilities</title>
      <link>https://example.com/claude-3-7</link>
      <pubDate>Mon, 28 Sep 2026 09:00:00 GMT</pubDate>
      <description>Detailed technical report on hybrid thinking models.</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_HTML_WITH_FEED = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI Researcher Blog</title>
  <link rel="alternate" type="application/rss+xml" title="RSS Feed" href="/feed.xml">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <h1>Welcome to my blog</h1>
</body>
</html>
"""

SAMPLE_HTML_NO_FEED = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Corporate Landing Page</title>
</head>
<body>
  <h1>Corporate News</h1>
</body>
</html>
"""

SAMPLE_FEDERAL_REGISTER_JSON = json.dumps({
    "count": 2,
    "results": [
        {
            "title": "Artificial Intelligence Safety Standards and Risk Assessment",
            "html_url": "https://www.federalregister.gov/documents/2026/10/01/2026-12345/ai-safety",
            "publication_date": "2026-10-01",
            "abstract": "Proposed federal framework for evaluating frontier AI systems.",
        },
        {
            "title": "Public Hearing on Autonomous Maritime Navigation",
            "html_url": "https://www.federalregister.gov/documents/2026/09/25/2026-12346/maritime",
            "publication_date": "2026-09-25",
            "abstract": "Notice of public hearing regarding commercial vessel automated pilots.",
        },
    ]
})


def make_mock_fetch(mapping):
    """Create an offline fetch callable from a dict of {url: (status, body, content_type)}."""
    def _fetch(url, timeout=10):
        if url in mapping:
            status, body, ct = mapping[url]
            res = ResponseText(body, status=status, url=url)
            res.content_type = ct
            res.error = None if status < 400 else f"HTTP {status}"
            return res
        # Default 404 for unmapped URLs
        res = ResponseText("404 Not Found", status=404, url=url)
        res.content_type = "text/plain"
        res.error = "HTTP 404"
        return res
    return _fetch


class SourceProbeDirectFeedTests(unittest.TestCase):
    def test_direct_rss_feed_is_detected_and_parsed(self):
        candidate = {
            "id": "test-ai-lab",
            "name": "Test AI Lab",
            "url": "https://lab.example.com/feed.xml",
            "label": "chinh-thuc",
            "circle_id": "circle-1",
            "circle_name": "Tạo ra AI",
        }
        mock_fetch = make_mock_fetch({
            "https://lab.example.com/robots.txt": (404, "Not Found", "text/plain"),
            "https://lab.example.com/feed.xml": (200, SAMPLE_RSS, "application/rss+xml"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertTrue(result["reachable"])
        self.assertEqual(result["http_status"], 200)
        self.assertTrue(result["feed_found"])
        self.assertEqual(result["feed_type"], "direct")
        self.assertEqual(result["feed_url"], "https://lab.example.com/feed.xml")
        self.assertEqual(result["item_count"], 4)
        self.assertEqual(result["newest_item_date"], "2026-10-02T12:00:00Z")
        self.assertTrue(result["robots_allowed"])
        self.assertFalse(result["robots_disallowed"])

        # 3 out of 4 titles are about AI (DeepSeek, LLM, Claude)
        self.assertEqual(result["ai_count"], 3)
        self.assertAlmostEqual(result["ai_share"], 0.75, places=2)
        self.assertTrue(result["recommendation"].startswith("SẴN SÀNG"))


class SourceProbeAutodiscoveryTests(unittest.TestCase):
    def test_html_autodiscovery_finds_and_fetches_alternate_link(self):
        candidate = {
            "id": "researcher-blog",
            "name": "Researcher Blog",
            "url": "https://blog.example.com/",
            "label": "cong-dong",
            "circle_id": "circle-2",
            "circle_name": "Kiểm chứng AI",
        }
        mock_fetch = make_mock_fetch({
            "https://blog.example.com/robots.txt": (200, "User-agent: *\nAllow: /", "text/plain"),
            "https://blog.example.com/": (200, SAMPLE_HTML_WITH_FEED, "text/html"),
            "https://blog.example.com/feed.xml": (200, SAMPLE_RSS, "application/rss+xml"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertTrue(result["reachable"])
        self.assertTrue(result["feed_found"])
        self.assertEqual(result["feed_type"], "autodiscovered")
        self.assertEqual(result["feed_url"], "https://blog.example.com/feed.xml")
        self.assertEqual(result["item_count"], 4)
        self.assertEqual(result["ai_count"], 3)

    def test_html_without_alternate_feed_reports_no_feed(self):
        candidate = {
            "id": "corp-news",
            "name": "Corporate News",
            "url": "https://corp.example.com/news",
            "label": "chinh-thuc",
            "circle_id": "circle-1",
            "circle_name": "Tạo ra AI",
        }
        mock_fetch = make_mock_fetch({
            "https://corp.example.com/robots.txt": (404, "Not Found", "text/plain"),
            "https://corp.example.com/news": (200, SAMPLE_HTML_NO_FEED, "text/html"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertTrue(result["reachable"])
        self.assertEqual(result["http_status"], 200)
        self.assertFalse(result["feed_found"])
        self.assertIsNone(result["feed_type"])
        self.assertEqual(result["item_count"], 0)
        self.assertIn("CẦN TÌM FEED", result["recommendation"])


class SourceProbeHttpErrorTests(unittest.TestCase):
    def test_404_not_found_is_reported_cleanly(self):
        candidate = {
            "id": "broken-url",
            "name": "Broken URL",
            "url": "https://broken.example.com/wrong-path",
            "label": "chinh-thuc",
        }
        mock_fetch = make_mock_fetch({
            "https://broken.example.com/robots.txt": (404, "Not Found", "text/plain"),
            "https://broken.example.com/wrong-path": (404, "Not Found", "text/html"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertFalse(result["reachable"])
        self.assertEqual(result["http_status"], 404)
        self.assertFalse(result["feed_found"])
        self.assertIn("404", result["recommendation"])

    def test_403_forbidden_reports_blocking_risk(self):
        candidate = {
            "id": "blocked-substack",
            "name": "Blocked Substack",
            "url": "https://substack.example.com/feed",
            "label": "cong-dong",
        }
        mock_fetch = make_mock_fetch({
            "https://substack.example.com/robots.txt": (403, "Forbidden", "text/html"),
            "https://substack.example.com/feed": (403, "Forbidden", "text/html"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertFalse(result["reachable"])
        self.assertEqual(result["http_status"], 403)
        self.assertIn("403", result["recommendation"])


class SourceProbeRobotsTxtTests(unittest.TestCase):
    def test_robots_txt_disallow_flags_candidate(self):
        candidate = {
            "id": "disallowed-site",
            "name": "Disallowed Site",
            "url": "https://private.example.com/news/feed.xml",
            "label": "chinh-thuc",
        }
        mock_fetch = make_mock_fetch({
            "https://private.example.com/robots.txt": (
                200,
                "User-agent: *\nDisallow: /news/\n",
                "text/plain",
            ),
            "https://private.example.com/news/feed.xml": (200, SAMPLE_RSS, "application/rss+xml"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertTrue(result["robots_disallowed"])
        self.assertFalse(result["robots_allowed"])
        self.assertIn("robots.txt", result["notes"])
        self.assertIn("robots.txt cấm", result["recommendation"])

    def test_robots_txt_allow_rules_permit_path(self):
        candidate = {
            "id": "allowed-site",
            "name": "Allowed Site",
            "url": "https://open.example.com/public/feed.xml",
            "label": "chinh-thuc",
        }
        mock_fetch = make_mock_fetch({
            "https://open.example.com/robots.txt": (
                200,
                "User-agent: *\nDisallow: /secret/\nAllow: /public/\n",
                "text/plain",
            ),
            "https://open.example.com/public/feed.xml": (200, SAMPLE_RSS, "application/rss+xml"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertFalse(result["robots_disallowed"])
        self.assertTrue(result["robots_allowed"])


class SourceProbeDeduplicationTests(unittest.TestCase):
    def test_duplicate_url_is_flagged(self):
        existing = [
            {
                "id": "simon-willison",
                "name": "Simon Willison",
                "url": "https://simonwillison.net/atom/everything/",
                "normalized_url": "https://simonwillison.net/atom/everything",
                "module": "radar.catalog",
            }
        ]
        candidate = {
            "id": "simon-willison-cand",
            "name": "Simon Willison",
            "url": "https://simonwillison.net/atom/everything/",
            "label": "cong-dong",
        }

        dup = check_duplicate(candidate, existing)
        self.assertTrue(dup["is_duplicate"])
        self.assertEqual(dup["existing_id"], "simon-willison")
        self.assertEqual(dup["match_type"], "url")

    def test_duplicate_id_is_flagged(self):
        existing = [
            {
                "id": "latent-space",
                "name": "Latent Space Podcast",
                "url": "https://api.substack.com/feed/podcast/1084089.rss",
                "normalized_url": "https://api.substack.com/feed/podcast/1084089.rss",
                "module": "radar.catalog",
            }
        ]
        candidate = {
            "id": "latent-space",
            "name": "Latent Space",
            "url": "https://www.latent.space/feed",
            "label": "cong-dong",
        }

        dup = check_duplicate(candidate, existing)
        self.assertTrue(dup["is_duplicate"])
        self.assertEqual(dup["existing_id"], "latent-space")
        self.assertEqual(dup["match_type"], "id")

    def test_novel_source_is_not_duplicate(self):
        existing = collect_existing_sources()
        candidate = {
            "id": "novel-unseen-source",
            "name": "Novel Unseen AI Lab",
            "url": "https://novel-lab-unseen-12345.org/feed",
            "label": "chinh-thuc",
        }

        dup = check_duplicate(candidate, existing)
        self.assertFalse(dup["is_duplicate"])


class SourceProbeJsonFeedTests(unittest.TestCase):
    def test_federal_register_json_api_parsing(self):
        candidate = {
            "id": "federal-register-ai",
            "name": "Federal Register AI",
            "url": "https://www.federalregister.gov/api/v1/documents.json",
            "label": "chinh-thuc",
        }
        mock_fetch = make_mock_fetch({
            "https://www.federalregister.gov/robots.txt": (200, "User-agent: *\nAllow: /", "text/plain"),
            "https://www.federalregister.gov/api/v1/documents.json": (
                200,
                SAMPLE_FEDERAL_REGISTER_JSON,
                "application/json",
            ),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])

        self.assertTrue(result["reachable"])
        self.assertTrue(result["feed_found"])
        self.assertEqual(result["feed_type"], "direct")
        self.assertEqual(result["item_count"], 2)
        # First item has "Artificial Intelligence" in title
        self.assertEqual(result["ai_count"], 1)
        self.assertAlmostEqual(result["ai_share"], 0.50, places=2)


class SourceProbeCandidateDataTests(unittest.TestCase):
    def test_candidate_sources_json_has_all_35_candidates(self):
        candidates = load_candidates()
        self.assertEqual(len(candidates), 35)

        required_keys = {"id", "name", "url", "label", "circle_id", "circle_name"}
        seen_ids = set()
        for c in candidates:
            self.assertTrue(required_keys.issubset(c.keys()), f"Missing keys in {c.get('id')}")
            self.assertNotIn(c["id"], seen_ids, f"Duplicate candidate id: {c['id']}")
            seen_ids.add(c["id"])
            self.assertTrue(c["url"].startswith("http"), f"Invalid URL: {c['url']}")
            self.assertIn(c["label"], {"chinh-thuc", "bao-chi", "cong-dong", "tin-hieu"})


class SourceProbeReportFormattingTests(unittest.TestCase):
    def test_render_markdown_report_produces_complete_markdown(self):
        results = [
            {
                "id": "mock-source-1",
                "name": "Mock Source 1",
                "circle_id": "circle-1",
                "circle_name": "Tạo ra AI",
                "proposed_label": "chinh-thuc",
                "url": "https://mock1.com",
                "final_url": "https://mock1.com",
                "http_status": 200,
                "reachable": True,
                "robots_allowed": True,
                "robots_disallowed": False,
                "robots_status": 200,
                "feed_found": True,
                "feed_type": "direct",
                "feed_url": "https://mock1.com/feed",
                "item_count": 10,
                "newest_item_date": "2026-10-01T00:00:00Z",
                "ai_share": 0.8,
                "ai_count": 8,
                "kinds": {"model": 4, "research": 4, "product": 0, "other": 2},
                "is_duplicate": False,
                "duplicate_of": None,
                "duplicate_match": None,
                "notes": "Tìm thấy feed direct",
                "recommendation": "SẴN SÀNG: Feed hoạt động tốt",
                "error": None,
            },
            {
                "id": "mock-source-2",
                "name": "Mock Source 2",
                "circle_id": "circle-2",
                "circle_name": "Kiểm chứng AI",
                "proposed_label": "cong-dong",
                "url": "https://mock2.com",
                "final_url": "https://mock2.com",
                "http_status": 404,
                "reachable": False,
                "robots_allowed": True,
                "robots_disallowed": False,
                "robots_status": 404,
                "feed_found": False,
                "feed_type": None,
                "feed_url": None,
                "item_count": 0,
                "newest_item_date": None,
                "ai_share": 0.0,
                "ai_count": 0,
                "kinds": {},
                "is_duplicate": False,
                "duplicate_of": None,
                "duplicate_match": None,
                "notes": "404 Not Found",
                "recommendation": "LỖI: HTTP 404 Not Found",
                "error": "HTTP 404",
            },
        ]

        report = render_markdown_report(results, generated_at="2026-10-05 12:00:00 UTC")

        self.assertIn("# Báo cáo kiểm tra nguồn ứng viên", report)
        self.assertIn("**Tổng số nguồn kiểm tra**: `2`", report)
        self.assertIn("**Khả dụng (Reachable HTTP 200-399)**: `1/2`", report)
        self.assertIn("| `mock-source-1` |", report)
        self.assertIn("| `mock-source-2` |", report)
        self.assertIn("### Tạo ra AI", report)
        self.assertIn("### Kiểm chứng AI", report)


class SourceProbeAdditionalEdgeCasesTests(unittest.TestCase):
    def test_robots_cache_reuses_result_for_same_domain(self):
        robots_fetch_calls = []

        def mock_fetch(url, timeout=10):
            if "robots.txt" in url:
                robots_fetch_calls.append(url)
                res = ResponseText("User-agent: *\nAllow: /", status=200, url=url)
                res.content_type = "text/plain"
                return res
            res = ResponseText(SAMPLE_RSS, status=200, url=url)
            res.content_type = "application/rss+xml"
            return res

        cache = {}
        cand1 = {"id": "c1", "name": "C1", "url": "https://same-domain.com/path1"}
        cand2 = {"id": "c2", "name": "C2", "url": "https://same-domain.com/path2"}

        probe_candidate(cand1, fetch=mock_fetch, robots_cache=cache, existing_sources=[])
        probe_candidate(cand2, fetch=mock_fetch, robots_cache=cache, existing_sources=[])

        # Robots.txt for same-domain.com should only be fetched ONCE
        self.assertEqual(len(robots_fetch_calls), 1)
        self.assertEqual(robots_fetch_calls[0], "https://same-domain.com/robots.txt")

    def test_malformed_xml_feed_is_handled_gracefully(self):
        candidate = {
            "id": "broken-xml",
            "name": "Broken XML",
            "url": "https://broken.example.com/rss",
            "label": "chinh-thuc",
        }
        mock_fetch = make_mock_fetch({
            "https://broken.example.com/robots.txt": (404, "Not Found", "text/plain"),
            "https://broken.example.com/rss": (200, "<rss><channel><title>Unclosed", "application/rss+xml"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])
        self.assertTrue(result["reachable"])
        self.assertFalse(result["feed_found"])
        self.assertEqual(result["item_count"], 0)

    def test_standard_json_feed_parsing(self):
        standard_json_feed = json.dumps({
            "version": "https://jsonfeed.org/version/1.1",
            "title": "My JSON Feed",
            "items": [
                {
                    "id": "1",
                    "title": "Building with LLMs and AI Agents",
                    "url": "https://example.com/post1",
                    "date_published": "2026-10-01T12:00:00Z",
                    "summary": "Guide to building agentic pipelines.",
                }
            ]
        })
        candidate = {
            "id": "json-feed-cand",
            "name": "JSON Feed",
            "url": "https://json.example.com/feed.json",
            "label": "chinh-thuc",
        }
        mock_fetch = make_mock_fetch({
            "https://json.example.com/robots.txt": (404, "Not Found", "text/plain"),
            "https://json.example.com/feed.json": (200, standard_json_feed, "application/json"),
        })

        result = probe_candidate(candidate, fetch=mock_fetch, existing_sources=[])
        self.assertTrue(result["reachable"])
        self.assertTrue(result["feed_found"])
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["ai_count"], 1)
        self.assertEqual(result["ai_share"], 1.0)

    def test_probe_all_runs_sequence(self):
        cands = [
            {"id": "c1", "name": "C1", "url": "https://e1.com/rss", "label": "chinh-thuc"},
            {"id": "c2", "name": "C2", "url": "https://e2.com/rss", "label": "cong-dong"},
        ]
        mock_fetch = make_mock_fetch({
            "https://e1.com/robots.txt": (404, "", "text/plain"),
            "https://e1.com/rss": (200, SAMPLE_RSS, "application/rss+xml"),
            "https://e2.com/robots.txt": (404, "", "text/plain"),
            "https://e2.com/rss": (404, "Not Found", "text/plain"),
        })

        results = probe_all(cands, fetch=mock_fetch, delay=0)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["feed_found"])
        self.assertFalse(results[1]["feed_found"])


if __name__ == "__main__":
    unittest.main()

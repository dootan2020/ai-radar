"""Offline unit tests for Claude.com news collector and article parser.

Tests against real public fixtures saved from claude.com:
- resources-articles.html
- claude-startups-article.html
- claude-sample-sitemap.xml
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from radar import feeds, v2feeds
from radar.claude import (
    is_claude_news_url,
    parse_claude,
    parse_claude_article_page,
    parse_claude_date,
    parse_claude_html,
    parse_claude_sitemap,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
CLAUDE_SOURCE = {
    "id": "anthropic-claude",
    "name": "Anthropic Claude Blog",
    "lab": "anthropic",
    "group": "lab",
    "url": "https://claude.com/resources/articles",
}


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class ClaudeCollectorTests(unittest.TestCase):
    def test_url_filter_accepts_canonical_articles_and_rejects_non_news(self):
        valid = [
            "https://claude.com/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build",
            "/resources/articles/claude-now-works-in-google-docs-sheets-and-slides",
            "https://claude.com/resources/articles/claude-code-mods",
            "/resources/articles/cowork-web-mobile",
        ]
        for url in valid:
            with self.subTest(valid_url=url):
                self.assertTrue(is_claude_news_url(url))

        invalid = [
            # Locales
            "https://claude.com/ja/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build",
            "/de/resources/articles/claude-now-works-in-google-docs-sheets-and-slides",
            "/fr/resources/articles/test",
            # Webinars / guides / videos / marketing
            "https://claude.com/resources/webinars/opus-5-5-for-work",
            "/resources/guides/prompt-engineering",
            "/resources/videos/claude-slides",
            "/resources/best-practices/agent-development",
            "/resources/perspectives/future-of-work",
            "/programs/startups",
            "/programs/campus",
            "/marketplace/slack",
            "/pricing",
            "/legal/privacy",
            "/resources/articles",  # Directory index without slug
            "",
            None,
        ]
        for url in invalid:
            with self.subTest(invalid_url=url):
                self.assertFalse(is_claude_news_url(url))

    def test_parse_claude_date(self):
        self.assertEqual(parse_claude_date("Oct 6, 2026"), "2026-10-06T00:00:00Z")
        self.assertEqual(parse_claude_date("October 6, 2026"), "2026-10-06T00:00:00Z")
        self.assertEqual(parse_claude_date("Sep 30, 2026"), "2026-09-30T00:00:00Z")
        self.assertEqual(parse_claude_date("2026-10-06"), "2026-10-06T00:00:00Z")
        self.assertEqual(parse_claude_date("2026-10-06T15:30:00Z"), "2026-10-06T15:30:00Z")
        self.assertIsNone(parse_claude_date(None))
        self.assertIsNone(parse_claude_date(""))

    def test_parse_articles_listing_includes_startups_program(self):
        html = read_fixture("resources-articles.html")
        items = parse_claude_html(html, CLAUDE_SOURCE, NOW.isoformat())

        self.assertGreaterEqual(len(items), 8)
        startups = next((it for it in items if "were-expanding-the-claude-startups-program" in it["url"]), None)
        self.assertIsNotNone(startups, "Startups announcement must be parsed from resources-articles.html")
        self.assertEqual(startups["title"], "We’re expanding the Claude Startups program to help founders build")
        self.assertEqual(startups["published_at"], "2026-10-06T00:00:00Z")
        self.assertEqual(startups["lab"], "anthropic")
        self.assertEqual(startups["source"], "anthropic-claude")
        self.assertEqual(startups["time_basis"], "published")

        urls = [it["url"] for it in items]
        self.assertIn("https://claude.com/resources/articles/claude-now-works-in-google-docs-sheets-and-slides", urls)
        self.assertIn("https://claude.com/resources/articles/how-comcast-booz-allen-use-claude-mythos-to-secure-their-codebases", urls)
        self.assertIn("https://claude.com/resources/articles/claude-code-mods", urls)
        self.assertIn("https://claude.com/resources/articles/claude-for-government-is-now-generally-available", urls)

    def test_parse_single_article_page_via_json_ld(self):
        html = read_fixture("claude-startups-article.html")
        items = parse_claude_article_page(html, CLAUDE_SOURCE, NOW.isoformat())

        self.assertEqual(len(items), 1)
        art = items[0]
        self.assertEqual(art["url"], "https://claude.com/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build")
        self.assertEqual(art["title"], "We’re expanding the Claude Startups program to help founders build")
        self.assertEqual(art["published_at"], "2026-10-06T00:00:00Z")
        self.assertIn("Claude Team plan", art["summary"])
        self.assertEqual(art["lab"], "anthropic")

    def test_parse_sitemap_xml(self):
        xml_text = read_fixture("claude-sample-sitemap.xml")
        items = parse_claude_sitemap(xml_text, CLAUDE_SOURCE, NOW.isoformat())

        # Expect 4 English articles, 0 webinars, 0 guides, 0 Japanese duplicates
        self.assertEqual(len(items), 4)
        urls = [it["url"] for it in items]
        self.assertIn("https://claude.com/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build", urls)
        self.assertIn("https://claude.com/resources/articles/claude-now-works-in-google-docs-sheets-and-slides", urls)
        self.assertNotIn("https://claude.com/ja/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build", urls)
        self.assertNotIn("https://claude.com/resources/webinars/opus-5-5-for-work", urls)
        self.assertNotIn("https://claude.com/resources/guides/prompt-engineering", urls)

    def test_unified_parse_claude_routing(self):
        html = read_fixture("resources-articles.html")
        self.assertEqual(len(parse_claude(html, CLAUDE_SOURCE, NOW.isoformat())), len(parse_claude_html(html, CLAUDE_SOURCE, NOW.isoformat())))

        single_html = read_fixture("claude-startups-article.html")
        self.assertEqual(len(parse_claude(single_html, CLAUDE_SOURCE, NOW.isoformat())), 1)

        xml = read_fixture("claude-sample-sitemap.xml")
        self.assertEqual(len(parse_claude(xml, CLAUDE_SOURCE, NOW.isoformat())), 4)

    def test_feeds_and_v2feeds_delegation(self):
        html = read_fixture("resources-articles.html")

        # v2 parse_feed delegation
        v2_items = v2feeds.parse_feed(html, CLAUDE_SOURCE, NOW.isoformat())
        self.assertGreaterEqual(len(v2_items), 8)
        self.assertEqual(v2_items[0]["lab"], "anthropic")
        self.assertEqual(v2_items[0]["source"], "anthropic-claude")

        # v1 parse_feed delegation
        v1_items = feeds.parse_feed(html, CLAUDE_SOURCE)
        self.assertGreaterEqual(len(v1_items), 8)
        self.assertEqual(v1_items[0]["lab"], "anthropic")
        self.assertEqual(v1_items[0]["source"], "anthropic-claude")
        self.assertEqual(set(v1_items[0].keys()), {"id", "lab", "source", "title", "url", "published_at", "summary", "kind"})


if __name__ == "__main__":
    unittest.main()

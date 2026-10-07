"""Unit tests for expanded source depth and candidate lab integrations.

Covers:
- Presence of new lab sources in inventories (anthropic-claude, nvidia-newsroom, qwen-blog).
- Feed parsing of real fixtures (nvidia-releases.xml, qwen-blog.xml).
- Transport gzip decompression handling.
"""

from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from email.message import Message

from radar import catalog, feeds, transport, v2feeds

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class SourceDepthTests(unittest.TestCase):
    def test_sources_registered_in_inventories(self):
        feed_sources = {s["id"]: s for s in feeds.SOURCES}
        self.assertIn("anthropic-claude", feed_sources)
        claude_s = feed_sources["anthropic-claude"]
        self.assertEqual(claude_s["lab"], "anthropic")
        self.assertEqual(claude_s["url"], "https://claude.com/resources/articles")

        self.assertIn("openai-platform", feed_sources)
        oai_s = feed_sources["openai-platform"]
        self.assertEqual(oai_s["lab"], "openai")
        self.assertEqual(oai_s["url"], "https://platform.openai.com/docs/changelog.md")

        self.assertIn("google-ai-studio", feed_sources)
        goog_s = feed_sources["google-ai-studio"]
        self.assertEqual(goog_s["lab"], "google")
        self.assertEqual(goog_s["url"], "https://ai.google.dev/gemini-api/docs/changelog")

        self.assertIn("deepseek-news", feed_sources)
        ds_s = feed_sources["deepseek-news"]
        self.assertEqual(ds_s["lab"], "deepseek")
        self.assertEqual(ds_s["url"], "https://api-docs.deepseek.com/updates")

        catalog_sources = {s["id"]: s for s in catalog.sources(NOW)}
        self.assertIn("nvidia-newsroom", catalog_sources)
        nv = catalog_sources["nvidia-newsroom"]
        self.assertEqual(nv["lab"], "nvidia")
        self.assertEqual(nv["url"], "https://nvidianews.nvidia.com/releases.xml")
        self.assertTrue(nv["filter_ai"])

        self.assertIn("qwen-blog", catalog_sources)
        qw = catalog_sources["qwen-blog"]
        self.assertEqual(qw["lab"], "qwen")
        self.assertEqual(qw["url"], "https://qwenlm.github.io/blog/index.xml")
        self.assertFalse(qw["filter_ai"])

    def test_openai_platform_changelog_parsing(self):
        md_text = read_fixture("openai-changelog.md")
        source = {
            "id": "openai-platform",
            "name": "OpenAI Platform",
            "lab": "openai",
            "url": "https://platform.openai.com/docs/changelog.md",
        }
        v2_items = v2feeds.parse_feed(md_text, source, NOW.isoformat())
        self.assertGreaterEqual(len(v2_items), 10)
        self.assertTrue(all(it["source"] == "openai-platform" for it in v2_items))
        self.assertTrue(all(it["lab"] == "openai" for it in v2_items))
        # Newest item check (Oct 6, 2026: Decisions API)
        newest = v2_items[0]
        self.assertTrue(newest["published_at"].startswith("2026-10-06"))
        self.assertIn("Decisions API", newest["title"])

        v1_items = feeds.parse_feed(md_text, source)
        self.assertGreaterEqual(len(v1_items), 10)
        self.assertEqual(v1_items[0]["published_at"], newest["published_at"])

    def test_google_ai_studio_changelog_parsing(self):
        html_text = read_fixture("google-ai-studio-changelog.html")
        source = {
            "id": "google-ai-studio",
            "name": "Google AI Studio",
            "lab": "google",
            "url": "https://ai.google.dev/gemini-api/docs/changelog",
        }
        v2_items = v2feeds.parse_feed(html_text, source, NOW.isoformat())
        self.assertGreaterEqual(len(v2_items), 10)
        self.assertTrue(all(it["source"] == "google-ai-studio" for it in v2_items))
        self.assertTrue(all(it["lab"] == "google" for it in v2_items))
        # Newest item check (Oct 6, 2026: Gemini Nano Banana 2.1)
        newest = v2_items[0]
        self.assertTrue(newest["published_at"].startswith("2026-10-06"))
        self.assertIn("Gemini Nano Banana 2.1", newest["title"])

        v1_items = feeds.parse_feed(html_text, source)
        self.assertGreaterEqual(len(v1_items), 10)
        self.assertEqual(v1_items[0]["published_at"], newest["published_at"])

    def test_deepseek_updates_parsing(self):
        html_text = read_fixture("deepseek-updates.html")
        source = {
            "id": "deepseek-news",
            "name": "DeepSeek News",
            "lab": "deepseek",
            "url": "https://api-docs.deepseek.com/updates",
        }
        v2_items = v2feeds.parse_feed(html_text, source, NOW.isoformat())
        self.assertGreaterEqual(len(v2_items), 5)
        self.assertTrue(all(it["source"] == "deepseek-news" for it in v2_items))
        self.assertTrue(all(it["lab"] == "deepseek" for it in v2_items))
        # Newest item check (Sep 10, 2026: DeepSeek-V4.1-Flash Release)
        newest = v2_items[0]
        self.assertTrue(newest["published_at"].startswith("2026-09-10"))
        self.assertIn("DeepSeek-V4.1-Flash", newest["title"])

        v1_items = feeds.parse_feed(html_text, source)
        self.assertGreaterEqual(len(v1_items), 5)
        self.assertEqual(v1_items[0]["published_at"], newest["published_at"])

    def test_nvidia_newsroom_feed_parsing(self):
        xml_text = read_fixture("nvidia-releases.xml")
        source = {
            "id": "nvidia-newsroom",
            "name": "NVIDIA Newsroom",
            "publisher": "nvidia",
            "lab": "nvidia",
            "group": "lab",
            "kind": "rss",
            "url": "https://nvidianews.nvidia.com/releases.xml",
            "filter_ai": True,
        }
        items = v2feeds.parse_feed(xml_text, source, NOW.isoformat())
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(all(it["source"] == "nvidia-newsroom" for it in items))
        self.assertTrue(all(it["lab"] == "nvidia" for it in items))
        newest = items[0]
        self.assertIn("telecom", newest["title"].lower())
        self.assertTrue(newest["published_at"].startswith("2026-10-06"))

    def test_qwen_blog_feed_parsing(self):
        xml_text = read_fixture("qwen-blog.xml")
        source = {
            "id": "qwen-blog",
            "name": "Qwen Blog",
            "publisher": "qwen",
            "lab": "qwen",
            "group": "lab",
            "kind": "rss",
            "url": "https://qwenlm.github.io/blog/index.xml",
            "filter_ai": False,
        }
        items = v2feeds.parse_feed(xml_text, source, NOW.isoformat())
        self.assertGreaterEqual(len(items), 10)
        self.assertTrue(all(it["source"] == "qwen-blog" for it in items))
        self.assertTrue(all(it["lab"] == "qwen" for it in items))
        newest = items[0]
        self.assertIn("Qwen", newest["title"])
        self.assertIsNotNone(newest["published_at"])

    def test_transport_decompresses_gzipped_content(self):
        plain_xml = b"<rss><channel><title>Gzip Test</title></channel></rss>"
        compressed = gzip.compress(plain_xml)

        class GzipResponse(io.BytesIO):
            status = 200
            def __init__(self, data):
                super().__init__(data)
                self.headers = Message()
                self.headers["Content-Encoding"] = "gzip"
                self.headers["Content-Length"] = str(len(data))
            def geturl(self):
                return "https://example.invalid/feed.xml"

        with patch.object(transport, "urlopen", side_effect=lambda *args, **kwargs: GzipResponse(compressed)):
            res = transport.read_url("https://example.invalid/feed.xml")
            self.assertEqual(res, plain_xml.decode("utf-8"))
            self.assertEqual(res.status, 200)


if __name__ == "__main__":
    unittest.main()

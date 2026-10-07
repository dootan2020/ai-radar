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

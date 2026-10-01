"""Offline parser contracts, using saved public fixtures and explicit edge cases."""

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from radar.common import classify, clean_text, iso_date
from radar.feeds import parse_feed
from radar.github import parse_trending as github_trending
from radar.huggingface import parse_releases, parse_trending as hf_trending

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = {"id": "openai-news", "name": "OpenAI News", "lab": "openai", "kind": "rss", "url": "https://openai.com/news/rss.xml"}


def saved(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class CommonTests(unittest.TestCase):
    def test_plain_source_summary_has_no_markup_and_bounded_length(self):
        value = clean_text("<p>Hello &amp; world</p>" + "<b> long</b>" * 100)
        self.assertIn("Hello & world", value)
        self.assertNotRegex(value, r"<[^>]+>")
        self.assertLessEqual(len(value), 300)

    def test_dates_convert_offsets_rfc_and_unknowns(self):
        for raw in ["2026-10-01T05:00:00+07:00", "Wed, 30 Sep 2026 22:00:00 GMT"]:
            self.assertEqual(iso_date(raw), "2026-09-30T22:00:00Z")
        for raw in [None, "", "date unknown", "2026-99-99", 123, {}, [], {"bad": 1}, [1]]:
            self.assertIsNone(iso_date(raw))

    def test_keyword_classification(self):
        cases = {"Introducing GPT-6": "model", "New research paper": "research", "New API dashboard": "product", "Company office news": "other"}
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify(title), expected)


class FeedTests(unittest.TestCase):
    def test_real_rss_exact_keys_dates_and_stable_ids(self):
        items = parse_feed(saved("openai.xml"), SOURCE)
        self.assertEqual(len(items), 3)
        expected = {"id", "lab", "source", "title", "url", "published_at", "summary", "kind"}
        for item in items:
            self.assertEqual(set(item), expected)
            self.assertEqual(item["lab"], "openai")
            self.assertEqual(item["source"], "openai-news")
            self.assertLessEqual(len(item["summary"]), 300)
        self.assertEqual(items[0]["published_at"], "2026-09-30T10:30:00Z")
        self.assertEqual(items[0]["id"], parse_feed(saved("openai.xml"), SOURCE)[0]["id"])
        self.assertEqual(items[2]["kind"], "model")

    def test_missing_date_is_unknown_and_duplicate_links_dedupe(self):
        body = saved("openai.xml")
        body = re.sub(r"<pubDate>.*?</pubDate>", "", body)
        first = re.search(r"<item>.*?</item>", body, re.S).group()
        body = body.replace("</channel>", first + "</channel>")
        items = parse_feed(body, SOURCE)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(item["published_at"] is None for item in items))
        self.assertEqual(len({item["url"] for item in items}), 3)

    def test_atom_alternate_link_and_offset_date(self):
        body = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Research paper</title>
          <link rel="self" href="https://example.org/api/1"/><link rel="alternate" href="https://example.org/paper"/>
          <updated>2026-10-01T05:00:00+07:00</updated><summary type="html">&lt;b&gt;Useful&lt;/b&gt; &amp;amp; concise</summary>
        </entry></feed>'''
        item = parse_feed(body, SOURCE)[0]
        self.assertEqual(item["url"], "https://example.org/paper")
        self.assertEqual(item["published_at"], "2026-09-30T22:00:00Z")
        self.assertEqual(item["summary"], "Useful & concise")

    def test_invalid_document_is_failure(self):
        with self.assertRaises((ValueError, ET.ParseError)):
            parse_feed("not XML", SOURCE)


class HuggingFaceTests(unittest.TestCase):
    def test_saved_release_values(self):
        items = parse_releases(saved("hf-releases.json"), "deepseek")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], {"id": "deepseek-ai/DeepSeek-V4.1-Flash", "lab": "deepseek", "url": "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash", "created_at": "2026-09-10T02:17:58Z", "likes": 3937, "downloads": 721211, "pipeline_tag": "image-text-to-text"})

    def test_saved_trending_nested_shape(self):
        item = hf_trending(saved("hf-trending.json"))[0]
        self.assertEqual(item, {"id": "Edge0/Audio8-ASR-Infinite", "type": "model", "url": "https://huggingface.co/Edge0/Audio8-ASR-Infinite", "likes": 1819, "downloads": 26749, "pipeline_tag": "automatic-speech-recognition"})

    def test_missing_numbers_and_metadata_remain_null(self):
        row = json.loads(saved("hf-releases.json"))[0]
        for key in ["likes", "downloads", "pipeline_tag", "createdAt"]:
            del row[key]
        item = parse_releases(json.dumps([row]), "deepseek")[0]
        for key in ["likes", "downloads", "pipeline_tag", "created_at"]:
            self.assertIsNone(item[key], key)

    def test_trending_spaces_datasets_and_zero(self):
        rows = [{"repoType": kind, "repoData": {"id": "owner/repo", "likes": 0}} for kind in ["space", "dataset"]]
        items = hf_trending(json.dumps({"recentlyTrending": rows}))
        self.assertEqual({item["type"] for item in items}, {"space", "dataset"})
        for item in items:
            self.assertEqual(item["likes"], 0)
            self.assertIsNone(item["downloads"])
            self.assertIn("/" + item["type"] + "s/", item["url"])


class GithubTests(unittest.TestCase):
    def test_saved_html_extracts_repository_not_sponsor_or_fork(self):
        items = github_trending(saved("github.html"))
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], {"repo": "NVIDIA/OpenShell", "url": "https://github.com/NVIDIA/OpenShell", "description": "OpenShell is the safe, private runtime for autonomous AI agents.", "language": "Rust", "stars": 12459, "stars_today": 1280})

    def test_absent_language_and_counts_are_unknown(self):
        body = '<article class="Box-row"><h2><a href="/owner/repo">owner / repo</a></h2><p>Useful &amp; small</p></article>'
        item = github_trending(body)[0]
        self.assertEqual(item["description"], "Useful & small")
        for key in ["language", "stars", "stars_today"]:
            self.assertIsNone(item[key], key)

    def test_blocked_page_is_not_silent_empty_success(self):
        with self.assertRaises(ValueError):
            github_trending("<html><title>Sign in / challenge required</title></html>")


if __name__ == "__main__":
    unittest.main()

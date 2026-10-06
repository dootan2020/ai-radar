"""Tests for story ID stability and aliases across pipeline runs and page preparation."""

import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from radar.clustering import cluster_items
from radar.common import stable_id
from radar.retention import retain_stories
from radar.story_pages import (
    BASE_URL, CONTENT_SECURITY_POLICY, persist, prepare, render_redirect_page,
    render_site, story_aliases,
)


class RedirectParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas = {}
        self.canonical = None
        self.refresh = None
        self.csp = None
        self.inline_scripts = []
        self.links = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            if attrs.get("http-equiv") == "refresh":
                self.refresh = attrs.get("content")
            if attrs.get("http-equiv") == "Content-Security-Policy":
                self.csp = attrs.get("content")
            name = attrs.get("name") or attrs.get("property")
            if name:
                self.metas[name] = attrs.get("content")
        elif tag == "link":
            if attrs.get("rel") == "canonical":
                self.canonical = attrs.get("href")
            self.links.append(attrs)
        elif tag == "script" and not attrs.get("src") and not attrs.get("type"):
            self._in_script = True
            self.inline_scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.inline_scripts[-1] += data


class StoryIdAliasReproductionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="story-alias-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "stories.git"
        result = subprocess.run(["git", "init", "--bare", "--quiet", str(self.remote)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_source_story_gains_second_source_first_id_resolves(self):
        # Reproduce coordinator's 06/10 example where first run was shown in feed but never archived:
        # Run 1: The Verge OpenAI watermark story
        verge_url = "https://www.theverge.com/ai-artificial-intelligence/1004880/openai-chatgpt-text-watermarks-eu-ai-act"
        verge_item = {
            "id": stable_id("verge-ai|" + verge_url),
            "source": "verge-ai",
            "publisher": "the-verge",
            "title": "OpenAI is adding text watermarking in ChatGPT and Codex",
            "url": verge_url,
            "published_at": "2026-10-05T18:08:39Z",
            "kind": "product",
            "summary": "An invisible watermark is rolling out to ChatGPT.",
            "group": "news",
        }
        stories_run1 = cluster_items([verge_item], "2026-10-05T19:00:00Z")
        self.assertEqual(len(stories_run1), 1)
        story1_id = stories_run1[0]["id"]
        # Expected verge id: 3685b45efb88af11e6c8
        self.assertEqual(story1_id, "3685b45efb88af11e6c8")

        # Run 2: TechCrunch covers the same story
        tc_url = "https://techcrunch.com/2026/10/05/openai-will-start-watermarking-chatgpts-text-in-the-eu/"
        tc_item = {
            "id": stable_id("techcrunch-ai|" + tc_url),
            "source": "techcrunch-ai",
            "publisher": "techcrunch",
            "title": "OpenAI will start watermarking ChatGPT’s text in the EU",
            "url": tc_url,
            "published_at": "2026-10-05T20:36:48Z",
            "kind": "product",
            "summary": "OpenAI will start text watermarking.",
            "group": "news",
        }
        stories_run2 = cluster_items([verge_item, tc_item], "2026-10-05T21:00:00Z")
        self.assertEqual(len(stories_run2), 1)
        current_story = stories_run2[0]
        current_id = current_story["id"]
        # Expected TechCrunch min anchor id: 62770fe3e19fe1d0e42a
        self.assertEqual(current_id, "62770fe3e19fe1d0e42a")

        # Run 2 page preparation (unarchived run 1)
        snapshot2_path = self.root / "snapshot2.json"
        snapshot2_path.write_text(json.dumps({"stories": stories_run2}), encoding="utf-8")
        site2 = self.root / "site2"
        cand2 = self.root / "cand2"
        prepare(str(self.remote), snapshot2_path, site2, cand2)

        # The current story's page must exist
        self.assertTrue((site2 / "tin" / current_id / "index.html").is_file())

        # CRITICAL TEST REQUIREMENT: The first id (3685b45efb88af11e6c8) MUST STILL RESOLVE!
        first_id_page = site2 / "tin" / story1_id / "index.html"
        self.assertTrue(first_id_page.is_file(), f"First story ID {story1_id} must resolve in site output")

        content = first_id_page.read_text(encoding="utf-8")
        parser = RedirectParser()
        parser.feed(content)
        expected_target = f"{BASE_URL}/tin/{current_id}/"
        self.assertIsNotNone(parser.refresh, "Redirect page must have meta refresh")
        self.assertIn(expected_target, parser.refresh)
        self.assertEqual(parser.canonical, expected_target)
        self.assertEqual(parser.metas.get("robots"), "noindex, follow")

        # Sitemap must contain only canonical URL, not alias
        sitemap = (site2 / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn(f"{BASE_URL}/tin/{current_id}/", sitemap)
        self.assertNotIn(f"{BASE_URL}/tin/{story1_id}/", sitemap)

    def test_one_source_story_persisted_then_gains_second_source_first_id_resolves_and_persists(self):
        # Case where Run 1 WAS persisted to radar-story-pages history:
        verge_url = "https://www.theverge.com/ai-artificial-intelligence/1004880/openai-chatgpt-text-watermarks-eu-ai-act"
        verge_item = {
            "id": stable_id("verge-ai|" + verge_url),
            "source": "verge-ai",
            "publisher": "the-verge",
            "title": "OpenAI is adding text watermarking in ChatGPT and Codex",
            "url": verge_url,
            "published_at": "2026-10-05T18:08:39Z",
            "kind": "product",
            "summary": "An invisible watermark is rolling out to ChatGPT.",
            "group": "news",
        }
        stories_run1 = cluster_items([verge_item], "2026-10-05T19:00:00Z")
        story1_id = stories_run1[0]["id"]

        snapshot1_path = self.root / "snapshot1.json"
        snapshot1_path.write_text(json.dumps({"stories": stories_run1}), encoding="utf-8")
        site1 = self.root / "site1"
        cand1 = self.root / "cand1"
        prepare(str(self.remote), snapshot1_path, site1, cand1)
        self.assertTrue(persist(str(self.remote), cand1))

        # Run 2: TechCrunch covers the same story
        tc_url = "https://techcrunch.com/2026/10/05/openai-will-start-watermarking-chatgpts-text-in-the-eu/"
        tc_item = {
            "id": stable_id("techcrunch-ai|" + tc_url),
            "source": "techcrunch-ai",
            "publisher": "techcrunch",
            "title": "OpenAI will start watermarking ChatGPT’s text in the EU",
            "url": tc_url,
            "published_at": "2026-10-05T20:36:48Z",
            "kind": "product",
            "summary": "OpenAI will start text watermarking.",
            "group": "news",
        }
        stories_run2 = cluster_items([verge_item, tc_item], "2026-10-05T21:00:00Z")
        current_id = stories_run2[0]["id"]

        snapshot2_path = self.root / "snapshot2.json"
        snapshot2_path.write_text(json.dumps({"stories": stories_run2}), encoding="utf-8")
        site2 = self.root / "site2"
        cand2 = self.root / "cand2"
        prepare(str(self.remote), snapshot2_path, site2, cand2)

        # First ID still resolves in site output
        first_id_page = site2 / "tin" / story1_id / "index.html"
        self.assertTrue(first_id_page.is_file())
        parser = RedirectParser()
        parser.feed(first_id_page.read_text(encoding="utf-8"))
        self.assertEqual(parser.canonical, f"{BASE_URL}/tin/{current_id}/")

        # Current ID page is canonical story page
        current_page = site2 / "tin" / current_id / "index.html"
        self.assertTrue(current_page.is_file())

        # Persist succeeds without breaking history
        self.assertTrue(persist(str(self.remote), cand2))

    def test_redirect_page_csp_and_escaping_safety(self):
        malicious_title = 'Headline </script><script>alert("xss")</script>'
        target_url = "https://example.com/tin/canonical-1/"
        html_doc = render_redirect_page(target_url, malicious_title)

        # No raw injected script tags
        self.assertNotIn('<script>alert("xss")</script>', html_doc)
        self.assertIn('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;', html_doc)

        parser = RedirectParser()
        parser.feed(html_doc)
        self.assertEqual(parser.csp, CONTENT_SECURITY_POLICY)

        # Inline script hash verification
        self.assertEqual(len(parser.inline_scripts), 1)
        theme_hash = base64.b64encode(hashlib.sha256(parser.inline_scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{theme_hash}'", parser.csp)

    def test_three_source_cluster_resolves_all_aliases(self):
        item_a = {
            "id": "item-a", "source": "src-a", "publisher": "Pub A",
            "title": "OpenAI releases breakthrough voice assistant for developers", "url": "https://a.com/model",
            "published_at": "2026-10-05T10:00:00Z", "group": "press",
        }
        item_b = {
            "id": "item-b", "source": "src-b", "publisher": "Pub B",
            "title": "OpenAI releases breakthrough voice assistant for developers", "url": "https://b.com/model",
            "published_at": "2026-10-05T11:00:00Z", "group": "press",
        }
        item_c = {
            "id": "item-c", "source": "src-c", "publisher": "Pub C",
            "title": "OpenAI releases breakthrough voice assistant for developers", "url": "https://c.com/model",
            "published_at": "2026-10-05T12:00:00Z", "group": "press",
        }
        stories = cluster_items([item_a, item_b, item_c], "2026-10-05T13:00:00Z")
        self.assertEqual(len(stories), 1)
        st = stories[0]
        # Canonical id is min of https://a.com/model, https://b.com/model, https://c.com/model
        id_a = stable_id("https://a.com/model")
        id_b = stable_id("https://b.com/model")
        id_c = stable_id("https://c.com/model")
        self.assertEqual(st["id"], id_a)
        self.assertEqual(sorted(st["aliases"]), sorted([id_b, id_c]))

        with tempfile.TemporaryDirectory(prefix="story-alias-test-") as tmp:
            site = Path(tmp)
            render_site({st["id"]: st}, site)
            self.assertTrue((site / "tin" / id_a / "index.html").is_file())
            self.assertTrue((site / "tin" / id_b / "index.html").is_file())
            self.assertTrue((site / "tin" / id_c / "index.html").is_file())

            parser_b = RedirectParser()
            parser_b.feed((site / "tin" / id_b / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(parser_b.canonical, f"{BASE_URL}/tin/{id_a}/")

            parser_c = RedirectParser()
            parser_c.feed((site / "tin" / id_c / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(parser_c.canonical, f"{BASE_URL}/tin/{id_a}/")


if __name__ == "__main__":
    unittest.main()

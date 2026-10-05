"""Offline rendering and durable-history coverage for per-story Pages."""

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from radar.story_pages import (
    BASE_URL, CONTENT_SECURITY_POLICY, REF, SITE_NAME, persist, prepare,
    render_site, render_story_page,
)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas = {}
        self.links = []
        self.scripts = []
        self.jsonld = []
        self.csp = None
        self.main_text = []
        self.in_main = False
        self.in_data_script = False
        self.in_jsonld = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.metas[attrs.get("property") or attrs.get("name")] = attrs.get("content")
            if attrs.get("http-equiv") == "Content-Security-Policy":
                self.csp = attrs.get("content")
        elif tag == "link":
            self.links.append(attrs)
        elif tag == "script" and attrs.get("id") == "story-data":
            self.in_data_script = True
            self.scripts.append("")
        elif tag == "script" and attrs.get("type") == "application/ld+json":
            self.jsonld.append("")
            self.in_jsonld = True
        elif tag == "main" and attrs.get("id") == "story-root":
            self.in_main = True

    def handle_endtag(self, tag):
        if tag == "script" and (self.in_data_script or self.in_jsonld):
            self.in_data_script = False
            self.in_jsonld = False
        elif tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.in_jsonld:
            self.jsonld[-1] += data
        elif self.in_data_script:
            self.scripts[-1] += data
        if self.in_main:
            self.main_text.append(data)


def story(story_id="story-1", **overrides):
    result = {
        "id": story_id,
        "title": "Original title",
        "title_vi": "Tiêu đề tiếng Việt",
        "summary": "Original summary",
        "summary_vi": "Tóm tắt tiếng Việt",
        "url": "https://publisher.example/story?a=1&b=2",
        "image": {"src": "https://publisher.example/image.jpg?x=1&y=2"},
        "coverage": [{"publisher": "Publisher", "title": "Original title",
                      "url": "https://publisher.example/story?a=1&b=2"}],
        "worth_score": 3.5,
    }
    result.update(overrides)
    return result


class StoryPageRenderingTests(unittest.TestCase):
    def test_metadata_fallback_content_relative_assets_and_json_are_safe(self):
        malicious = story(
            title_vi='Tiêu đề </title><script>alert("x")</script>',
            summary_vi='Tóm tắt <b>& \' " </script>',
            url="https://publisher.example/story?x=1&y=2",
            coverage=[{"publisher": 'P<ublisher "', "title": "Tiêu đề gốc",
                       "url": "https://publisher.example/story?x=1&y=2"}],
        )
        document = render_story_page(malicious)
        parser = PageParser()
        parser.feed(document)
        self.assertEqual(len(parser.scripts), 1)
        self.assertIn("\\u003c/script", parser.scripts[0])
        self.assertNotIn("</script><script>alert", document)
        data = json.loads(parser.scripts[0])
        self.assertEqual(data["title_vi"], malicious["title_vi"])
        self.assertEqual(parser.metas["description"], malicious["summary_vi"])
        self.assertEqual(parser.metas["og:title"], malicious["title_vi"])
        self.assertEqual(parser.metas["og:url"], f"{BASE_URL}/tin/story-1/")
        self.assertEqual(parser.metas["og:image"], malicious["image"]["src"])
        self.assertEqual(parser.metas["robots"], "max-image-preview:large")
        self.assertTrue(any(link.get("rel") == "canonical" for link in parser.links))
        self.assertIn('href="../../tokens.css"', document)
        self.assertIn('href="../../feed.css"', document)
        self.assertIn('href="../../story.css"', document)
        self.assertIn('src="../../story-page.js"', document)
        self.assertIn(malicious["summary_vi"], "".join(parser.main_text))
        self.assertIn(malicious["coverage"][0]["publisher"], "".join(parser.main_text))
        self.assertIn("Tiêu đề gốc", "".join(parser.main_text))

    def test_news_article_uses_only_story_dates_and_jsonld_keeps_existing_csp(self):
        item = story(
            title_vi='Headline </script><script>alert("x")</script>',
            published_at="2026-10-05T18:54:30Z",
        )
        document = render_story_page(item)
        parser = PageParser()
        parser.feed(document)
        self.assertEqual(len(parser.jsonld), 1)
        self.assertNotIn("</script><script>alert", document)
        article = json.loads(parser.jsonld[0])
        self.assertEqual(article["@type"], "NewsArticle")
        self.assertEqual(article["headline"], item["title_vi"])
        self.assertEqual(article["image"], [item["image"]["src"]])
        self.assertEqual(article["datePublished"], item["published_at"])
        self.assertNotIn("dateModified", article)
        self.assertEqual(article["publisher"], {"@type": "Organization", "name": SITE_NAME})
        self.assertEqual(parser.csp, CONTENT_SECURITY_POLICY)
        self.assertNotIn("'unsafe-inline'", parser.csp.split("script-src ", 1)[1].split(";", 1)[0])


    def test_key_points_and_missing_picture_use_site_default(self):
        document = render_story_page(story(
            image=None, key_points=["Điểm một", {"text": "Điểm hai"}, ""],
        ))
        self.assertIn("<li>Điểm một</li>", document)
        self.assertIn("<li>Điểm hai</li>", document)
        self.assertIn(f'{BASE_URL}/og-image.png', document)
        self.assertNotIn("<p>Tóm tắt tiếng Việt</p>", document)

    def test_rejects_unsafe_ids_and_non_http_original_links(self):
        with self.assertRaisesRegex(ValueError, "unsafe id"):
            render_story_page(story("../bad"))
        with self.assertRaisesRegex(ValueError, "safe original URL"):
            render_story_page(story(url="javascript:alert(1)", coverage=[]))

    def test_sitemap_covers_pages_and_stale_generated_pages_are_removed(self):
        with tempfile.TemporaryDirectory(prefix="story-render-") as temporary:
            site = Path(temporary)
            (site / "tin" / "stale").mkdir(parents=True)
            (site / "tin" / "stale" / "index.html").write_text("old", encoding="utf-8")
            (site / "tin" / "_sample").mkdir()
            stories = {"story-1": story(), "story-2": story("story-2")}
            self.assertEqual(render_site(stories, site), 2)
            sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn(f"{BASE_URL}/tin/story-1/", sitemap)
            self.assertIn(f"{BASE_URL}/tin/story-2/", sitemap)
            self.assertFalse((site / "tin" / "stale").exists())
            self.assertTrue((site / "tin" / "_sample").is_dir())


class StoryPageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="story-history-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "stories.git"
        result = subprocess.run(["git", "init", "--bare", "--quiet", str(self.remote)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def write_snapshot(self, path, stories):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stories": stories}, ensure_ascii=False), encoding="utf-8")

    def test_history_survives_snapshot_expiry_and_stale_candidates_cannot_overwrite(self):
        input_one = self.root / "first.json"
        site_one = self.root / "site-one"
        candidate_one = self.root / "candidate-one"
        self.write_snapshot(input_one, [story()])
        prepare(str(self.remote), input_one, site_one, candidate_one)
        self.assertTrue((site_one / "tin/story-1/index.html").is_file())
        self.assertTrue(persist(str(self.remote), candidate_one))
        self.assertFalse(persist(str(self.remote), candidate_one))

        stale_candidate = self.root / "stale-candidate"
        stale_site = self.root / "stale-site"
        prepare(str(self.remote), input_one, stale_site, stale_candidate)

        input_two = self.root / "second.json"
        site_two = self.root / "site-two"
        candidate_two = self.root / "candidate-two"
        self.write_snapshot(input_two, [story("story-2")])
        prepare(str(self.remote), input_two, site_two, candidate_two)
        self.assertTrue((site_two / "tin/story-1/index.html").is_file())
        self.assertTrue((site_two / "tin/story-2/index.html").is_file())
        self.assertTrue(persist(str(self.remote), candidate_two))
        with self.assertRaisesRegex(ValueError, "advanced"):
            persist(str(self.remote), stale_candidate)
        sitemap = (site_two / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("story-1", sitemap)
        self.assertIn("story-2", sitemap)
        self.assertEqual(REF, "refs/heads/radar-story-pages")


class StoryPageWorkflowTests(unittest.TestCase):
    def test_workflow_uses_quoted_environment_remote_and_isolated_history_job(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".github/workflows/update.yml").read_text(encoding="utf-8")
        self.assertIn("STORY_REMOTE: ${{ github.server_url }}/${{ github.repository }}.git", text)
        self.assertIn('python -m radar.story_pages prepare --remote "$STORY_REMOTE"', text)
        self.assertIn('python -m radar.story_pages persist --remote "$STORY_REMOTE"', text)
        self.assertIn("  persist-story-pages:\n", text)
        self.assertIn("contents: write", text)
        self.assertLess(text.index("name: Prepare permanent story pages"),
                        text.index("name: Upload Pages artifact"))


if __name__ == "__main__":
    unittest.main()

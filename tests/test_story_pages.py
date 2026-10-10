"""Offline rendering and durable-history coverage for per-story Pages."""

from html.parser import HTMLParser
import base64
import hashlib
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
        self.inline_scripts = []
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
        elif tag == "script" and not attrs.get("src") and not attrs.get("type"):
            self.inline_scripts.append("")
            self.in_inline_script = True
        elif tag == "main" and attrs.get("id") == "story-root":
            self.in_main = True

    def handle_endtag(self, tag):
        if tag == "script" and (self.in_data_script or self.in_jsonld):
            self.in_data_script = False
            self.in_jsonld = False
        elif tag == "script" and getattr(self, "in_inline_script", False):
            self.in_inline_script = False
        elif tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.in_jsonld:
            self.jsonld[-1] += data
        elif getattr(self, "in_inline_script", False):
            self.inline_scripts[-1] += data
        elif self.in_data_script:
            self.scripts[-1] += data
        if self.in_main:
            self.main_text.append(data)


def story(story_id="story-1", **overrides):
    result = {
        "id": story_id,
        "title": "Original title",
        "title_vi": "Tiêu đề tiếng Việt",
        "summary": "Original summary.",
        "summary_vi": "Tóm tắt tiếng Việt.",
        "url": "https://publisher.example/story?a=1&b=2",
        "image": {"src": "https://publisher.example/image.jpg?x=1&y=2"},
        "coverage": [{"publisher": "Publisher", "title": "Original title",
                      "url": "https://publisher.example/story?a=1&b=2"}],
        "worth_score": 3.5,
    }
    result.update(overrides)
    return result


class StoryPageRenderingTests(unittest.TestCase):
    def test_screened_story_uses_site_metadata_image_and_keeps_full_title(self):
        item = story(image_screened=True, image=None, headline="Short", headline_vi="Ngắn")
        document = render_story_page(item)
        parser = PageParser()
        parser.feed(document)
        self.assertEqual(parser.metas["og:image"], f"{BASE_URL}/og-image.png")
        self.assertEqual(parser.metas["twitter:image"], parser.metas["og:image"])
        self.assertEqual(json.loads(parser.jsonld[0])["image"], [parser.metas["og:image"]])
        self.assertEqual(parser.metas["twitter:card"], "summary_large_image")
        self.assertIn('id="story-modal-title">Tiêu đề tiếng Việt</h1>', document)
        self.assertEqual(json.loads(parser.scripts[0])["headline_vi"], "Ngắn")
        self.assertIsNone(json.loads(parser.scripts[0])["image"])

    def test_screened_approved_image_is_the_metadata_image(self):
        for src, expected in [("assets/ai/story-1.jpg", f"{BASE_URL}/assets/ai/story-1.jpg"),
                              ("https://publisher.example/photo.jpg", "https://publisher.example/photo.jpg")]:
            with self.subTest(src=src):
                item = story(image_screened=True, image={"src": src})
                parser = PageParser()
                parser.feed(render_story_page(item))
                self.assertEqual(parser.metas["og:image"], expected)
                self.assertEqual(parser.metas["twitter:image"], expected)
                self.assertEqual(json.loads(parser.jsonld[0])["image"], [expected])

    def test_screened_missing_or_invalid_image_never_borrows_coverage_media(self):
        for image in [None, {}, {"src": ""}, {"src": "javascript:alert(1)"}]:
            with self.subTest(image=image):
                item = story(image_screened=True, image=image)
                item["coverage"][0]["media"] = [{"type": "image", "url": "https://rejected.example/image.jpg"}]
                parser = PageParser()
                parser.feed(render_story_page(item, base_url="https://radar.example/"))
                expected = "https://radar.example/og-image.png"
                self.assertEqual(parser.metas["og:image"], expected)
                self.assertEqual(parser.metas["twitter:image"], expected)
                self.assertEqual(json.loads(parser.jsonld[0])["image"], [expected])
                self.assertEqual(json.loads(parser.scripts[0])["image"], image)

    def test_metadata_fallback_content_relative_assets_and_json_are_safe(self):
        malicious = story(
            title_vi='Tiêu đề </title><script>alert("x")</script>',
            summary_vi='Tóm tắt <b>& \' " </script>.',
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
        self.assertIn('class="feed-bar"', document)
        self.assertIn('class="story-page-container" id="story-root"', document)
        self.assertIn('class="story-article"', document)
        self.assertIn('class="story-headline"', document)
        self.assertIn('class="story-summary-box"', document)
        self.assertIn('class="story-origin-gateway"', document)
        self.assertIn('class="skip" href="#story-root"', document)
        self.assertIn('id="i-arrow-left"', document)
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
        theme_hash = base64.b64encode(hashlib.sha256(parser.inline_scripts[0].encode()).digest()).decode()
        self.assertIn(f"'sha256-{theme_hash}'", parser.csp)

    def test_story_json_has_only_referenced_source_records(self):
        item = story(coverage=[{"source": "source-a", "publisher": "A",
                                "url": "https://a.example/story"},
                               {"source": "missing", "url": "https://b.example/story"}])
        document = render_story_page(item, sources=[{"id": "source-a", "name": "Source A", "icon": "a.svg"},
                                                     {"id": "unused", "name": "Unused"}])
        parser = PageParser()
        parser.feed(document)
        data = json.loads(parser.scripts[0])
        self.assertEqual(data["source_records"], [{"id": "source-a", "name": "Source A", "icon": "a.svg"}])

    def test_story_text_cannot_expand_template_placeholders(self):
        document = render_story_page(story(title_vi="{{CONTENT}}", summary_vi="{{JSONLD}}."))
        self.assertIn("<title>{{CONTENT}} · ai·radar</title>", document)
        self.assertIn('content="{{JSONLD}}."', document)
        self.assertNotIn('<title><section class="story-keypoints-box"', document)

    def test_trim_complete_sentences_and_honest_labels(self):
        # Captain's example story
        raw_vi = ("Một dấu nước vô hình, có thể đọc được máy tính trong xuất bản văn bản đang được triển khai "
                  "cho ChatGPT và Codex, nhưng chỉ dành cho người dùng trong Liên minh châu Âu lúc đầu. "
                  "OpenAI cho biết đánh dấu nước textGrain của nó \"được phù hợp hoặc vượt qua\" các cách tiếp cận "
                  "khác như SynthID của Google DeepMind cho văn bản, cũng là cơ sở cho nước")
        expected_vi = ("Một dấu nước vô hình, có thể đọc được máy tính trong xuất bản văn bản đang được triển khai "
                       "cho ChatGPT và Codex, nhưng chỉ dành cho người dùng trong Liên minh châu Âu lúc đầu.")
        raw_en = ("An invisible, machine-readable watermark in text output is rolling out to ChatGPT and Codex, "
                  "but only for users in the European Union at first. OpenAI says its textGrain watermarking "
                  "\"matched or exceeded\" other approaches like Google DeepMind's SynthID for text, which is also "
                  "the basis for the water")
        expected_en = ("An invisible, machine-readable watermark in text output is rolling out to ChatGPT and Codex, "
                       "but only for users in the European Union at first.")

        item = story(summary=raw_en, summary_vi=raw_vi)
        document = render_story_page(item)
        parser = PageParser()
        parser.feed(document)

        # Meta description and fallback content must show only the complete sentence
        self.assertEqual(parser.metas["description"], expected_vi)
        self.assertIn(expected_vi, "".join(parser.main_text))
        self.assertNotIn("cũng là cơ sở cho nước", "".join(parser.main_text))
        self.assertNotIn("the basis for the water", "".join(parser.main_text))

        # Honest label: fallback says 'Đoạn trích bài viết', NOT 'Tóm lược bài viết'
        self.assertIn('aria-label="Đoạn trích bài viết"', document)
        self.assertIn('<h2 class="story-section-h2">Đoạn trích bài viết</h2>', document)
        self.assertNotIn('<h2 class="story-section-h2">Tóm lược bài viết</h2>', document)

        # Gateway description for fallback does not claim AI summarization
        self.assertIn('Mở bài gốc để xem trọn vẹn chi tiết và dẫn chứng.', document)
        self.assertNotIn('ai-radar tóm tắt ý chính để bạn nắm nhanh sự kiện.', document)

    def test_key_points_and_missing_picture_use_site_default(self):
        document = render_story_page(story(
            image=None, key_points=["Điểm một", "Điểm hai", "Điểm ba", "Điểm bốn"],
            key_points_prompt_version="summary-vi-5-full",
            summary_sources=[{"name": "Publisher", "role": "outlet", "url": "https://publisher.example/story"}],
        ))
        self.assertIn('class="story-point-text">Điểm một</span>', document)
        self.assertIn('class="story-point-text">Điểm hai</span>', document)
        self.assertIn(f'{BASE_URL}/og-image.png', document)
        self.assertIn('class="story-keypoints-box"', document)
        self.assertNotIn('class="story-summary-box"', document)
        self.assertNotIn('Đọc nhanh', document)
        self.assertNotIn('Đọc đầy đủ', document)
        self.assertNotIn('Ý chính:', document)
        self.assertIn('Tóm tắt bằng AI từ phần nội dung bài gốc đọc được.', document)
        self.assertNotIn('class="story-summary-text">Tóm tắt tiếng Việt.</p>', document)
        # When key points exist, gateway description notes AI summarization
        self.assertIn('ai-radar tóm tắt ý chính để bạn nắm nhanh sự kiện. Mở bài gốc để xem trọn vẹn chi tiết và dẫn chứng.', document)

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
                        text.index("name: Upload Cloudflare Pages site artifact"))

    def test_generated_story_directories_are_ignored_but_sample_is_not(self):
        root = Path(__file__).resolve().parents[1]
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "site/tin/story-1/index.html"],
                                 cwd=root, capture_output=True, text=True)
        sample = subprocess.run(["git", "check-ignore", "--no-index", "site/tin/_sample/index.html"],
                                cwd=root, capture_output=True, text=True)
        self.assertEqual(ignored.returncode, 0)
        self.assertNotEqual(sample.returncode, 0)


if __name__ == "__main__":
    unittest.main()

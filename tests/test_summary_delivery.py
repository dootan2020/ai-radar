"""Offline article extraction and summary delivery regression tests."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from radar import shadow_collector, summary_gemini, summary_pipeline
from radar.transport import ResponseText, USER_AGENT


FIXTURES = Path(__file__).parent / "fixtures" / "summary-articles"


class SummaryDeliveryTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def test_labelled_body_excludes_other_news_and_authors_inside_main(self):
        parser = summary_pipeline.parse_article(
            '<main><div class="entry-content wp-block-post-content"><p>Synthetic article body.</p>'
            '<p><a href="https://anthropic.com/research/synthetic">research report</a></p></div>'
            '<div><p>Author biography and unrelated funding news.</p>'
            '<a href="https://openai.com/index/unrelated">report</a></div></main>',
            "https://publisher.example/story")
        self.assertEqual(parser.parts, ["Synthetic article body.", "research report"])
        self.assertEqual(parser.links, [("https://anthropic.com/research/synthetic", "research report")])

    def test_article_takes_precedence_over_surrounding_main(self):
        parser = summary_pipeline.parse_article(
            '<main><article><header>Report title</header><article><p>Synthetic primary report body.</p></article>'
            '<section><h2>Related content</h2><p>Unrelated company and statistics.</p></section></article></main>',
            "https://anthropic.com/research/synthetic")
        self.assertEqual(parser.parts, ["Synthetic primary report body."])

    def test_synthetic_articles_extract_body_without_navigation(self):
        openings = {
            "01.html": "Synthetic workshop notes describe a checklist",
            "02.html": "Synthetic research notes describe a checklist",
            "03.html": "Synthetic review notes describe a checklist",
            "05.html": "Synthetic loader notes describe a checklist",
            "06.html": "Synthetic rich text notes describe a checklist",
        }
        for item in json.loads((FIXTURES / "index.json").read_text()):
            with self.subTest(file=item["file"]):
                fetched = []
                html = (FIXTURES / item["file"]).read_text(encoding="utf-8")

                def read(url, **kwargs):
                    fetched.append(url)
                    if url.endswith("/robots.txt"):
                        return ResponseText("User-agent: *\nAllow: /", status=200)
                    return ResponseText(html,
                                        status=200, url=url, content_type="text/html")

                # This test covers the labelled-body parser, so trafilatura is switched off.
                with patch.object(summary_pipeline.transport, "read_url", side_effect=read), \
                        patch.object(summary_pipeline, "trafilatura", None):
                    text, reason = summary_pipeline.fetch_article_result({"url": item["url"]})
                self.assertIsNone(reason)
                self.assertIn(openings[item["file"]], text[:500])
                self.assertGreaterEqual(len(text), 300)
                for decoy in ("Navigation decoy", "Recommended post decoy", "Footer decoy"):
                    self.assertIn(decoy, html)
                    self.assertNotIn(decoy, text)
                self.assertTrue(text.endswith("Synthetic body end marker."))
                self.assertIn("\n", text)
                if item["file"] in {"01.html", "03.html"}:
                    for decoy in ("Script decoy", "Style decoy", "Noscript decoy"):
                        self.assertIn(decoy, html)
                        self.assertNotIn(decoy, text)
                if item["file"] == "06.html":
                    for decoy in ("Unlabelled rich text decoy", "Wrong component decoy", "Wrong label decoy"):
                        self.assertIn(decoy, html)
                        self.assertNotIn(decoy, text)
                self.assertEqual(len(fetched), 2)

    def test_shared_robots_rules_are_checked_for_each_path_in_either_order(self):
        for paths in (("/allowed", "/private"), ("/private", "/allowed")):
            with self.subTest(paths=paths):
                fetched, cache = [], {}

                def read(url, **kwargs):
                    fetched.append(url)
                    if url.endswith("/robots.txt"):
                        return ResponseText("User-agent: *\nDisallow: /private", status=200)
                    return ResponseText("<article>" + "Article body with verified evidence. " * 20 + "</article>",
                                        status=200, url=url, content_type="text/html")

                with patch.object(summary_pipeline.transport, "read_url", side_effect=read):
                    results = {p: summary_pipeline.fetch_article_result(
                        {"url": "https://publisher.example" + p}, cache) for p in paths}
                self.assertIsNone(results["/allowed"][1])
                self.assertEqual(results["/private"], ("", "robots"))
                self.assertEqual(fetched.count("https://publisher.example/robots.txt"), 1)
                self.assertNotIn("https://publisher.example/private", fetched)

    def test_robots_uses_reader_identity_and_denies_unavailable_rules(self):
        robots_text = "User-agent: AI-Radar\nDisallow: /private\n\nUser-agent: *\nAllow: /"
        with patch.object(shadow_collector, "default_fetch", return_value=ResponseText(robots_text, status=200)):
            self.assertTrue(shadow_collector.check_robots("https://publisher.example/private")["disallowed"])
        self.assertTrue(USER_AGENT.startswith("AI-Radar/"))
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                with patch.object(summary_pipeline.transport, "read_url",
                                  return_value=ResponseText("", status=status)) as read:
                    self.assertEqual(summary_pipeline.fetch_article_result(
                        {"url": "https://publisher.example/story"}), ("", "robots"))
                self.assertEqual(read.call_count, 1)

    def test_robots_request_uses_transport_user_agent(self):
        from email.message import Message
        from unittest.mock import MagicMock
        from radar import transport

        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.geturl.return_value = "https://publisher.example/robots.txt"
        response.headers = Message()
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        response.read.return_value = b"User-agent: *\nDisallow: /private"
        with patch.object(transport, "build_opener") as opener:
            opener.return_value.open.return_value = response
            text, reason = summary_pipeline.fetch_article_result({"url": "https://publisher.example/private"})
        self.assertEqual((text, reason), ("", "robots"))
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)

    def test_embedded_article_requires_matching_publisher_and_slug(self):
        html = (FIXTURES / "05.html").read_text(encoding="utf-8")
        for url in ("https://pandaily.com/unrelated", "https://other.example/mirros-agentgarten-open-source-code-worlds-neural-renderer-agents-playbooks"):
            self.assertEqual(summary_pipeline._pandaily_article_html(html, url), "")
        for data in ('"not json"', '"[]"', '"[null]"'):
            markup = "window.__remixContext.streamController.enqueue(" + data + ")"
            self.assertEqual(summary_pipeline._pandaily_article_html(markup, "https://pandaily.com/story"), "")

    def test_parse_article_extracts_entry_and_post_containers(self):
        html = '<div class="entry entryPage"><p>' + 'Simon blog post content about new models. ' * 15 + '</p></div>'
        parser = summary_pipeline.parse_article(html, "https://simonwillison.net/2026/Oct/26/gpt-61-terra/")
        self.assertGreaterEqual(len("\n".join(parser.parts)), 300)
        self.assertIn("Simon blog post content about new models.", parser.parts[0])

    def test_parse_article_does_not_skip_substack_newsletter_post(self):
        html = '<article class="typography newsletter-post post"><p>' + 'Substack detailed article about AI industry. ' * 15 + '</p></article>'
        parser = summary_pipeline.parse_article(html, "https://example.substack.com/p/ai-industry")
        self.assertGreaterEqual(len("\n".join(parser.parts)), 300)
        self.assertIn("Substack detailed article about AI industry.", parser.parts[0])

    def test_parse_article_retains_fuller_article_when_prefer_body_extracts_author_bio(self):
        html = ('<article><p>' + 'Major multi-page technical report on frontier models and pricing. ' * 20 + '</p>'
                '<div class="entry-content"><p>Author bio and contact.</p></div></article>')
        parser = summary_pipeline.parse_article(html, "https://example.com/cheap-llms")
        text = "\n".join(parser.parts)
        self.assertGreaterEqual(len(text), 300)
        self.assertIn("Major multi-page technical report", text)

    def test_fetch_story_article_tries_beyond_two_coverage_urls_and_linked_primary(self):
        story = {
            "id": "terra-like-story",
            "url": "https://openai.example/blocked",
            "title": "Introducing GPT-6.1 Terra",
            "coverage": [
                {"publisher": "openai", "url": "https://openai.example/blocked"},
                {"publisher": "simon", "url": "https://short.example/post"},
                {"publisher": "hacker-news", "url": "https://openai.example/blocked"},
                {"publisher": "docs", "url": "https://developers.openai.example/docs"}
            ]
        }
        docs_html = "<article><p>" + "Full developer documentation for GPT-6.1 Terra with 3100 characters. " * 10 + "</p></article>"
        short_html = '<div class="entry"><p>Short note linking to <a href="https://developers.openai.example/docs">official docs</a>.</p></div>'

        def mock_read(url, **kwargs):
            if url.endswith("/robots.txt"):
                return ResponseText("User-agent: *\nAllow: /", status=200)
            if "blocked" in url:
                resp = ResponseText("Forbidden", status=403, url=url)
                return resp
            if "short.example" in url:
                return ResponseText(short_html, status=200, url=url, content_type="text/html")
            if "developers.openai.example" in url:
                return ResponseText(docs_html, status=200, url=url, content_type="text/html")
            return ResponseText("", status=404)

        with patch.object(summary_pipeline.transport, "read_url", side_effect=mock_read):
            details = {}
            text, reason, url = summary_pipeline.fetch_story_article(story, {}, details)
            self.assertGreaterEqual(len(text), 300)
            self.assertIsNone(reason)
            self.assertEqual(url, "https://developers.openai.example/docs")

    def test_fetch_story_article_records_which_extractor_read_the_page(self):
        from unittest.mock import MagicMock
        story = {"id": "tag-story", "url": "https://publisher.example/post"}
        html = "<article><p>" + "Fallback HTML parser text that has sufficient length. " * 10 + "</p></article>"

        def mock_read(url, **kwargs):
            if url.endswith("/robots.txt"):
                return ResponseText("User-agent: *\nAllow: /", status=200)
            return ResponseText(html, status=200, url=url, content_type="text/html")

        traf = MagicMock()
        traf.extract.return_value = "Trafilatura extracted content with high fidelity. " * 10
        with patch.object(summary_pipeline.transport, "read_url", side_effect=mock_read), \
                patch.object(summary_pipeline, "trafilatura", traf):
            details = {}
            text, reason, _ = summary_pipeline.fetch_story_article(story, {}, details)
            self.assertIsNone(reason)
            self.assertIn("Trafilatura extracted content", text)
            self.assertEqual(details["extractor"], "trafilatura")

        short = MagicMock()
        short.extract.return_value = "Short text"
        with patch.object(summary_pipeline.transport, "read_url", side_effect=mock_read), \
                patch.object(summary_pipeline, "trafilatura", short):
            details = {}
            text, reason, _ = summary_pipeline.fetch_story_article(story, {}, details)
            self.assertIsNone(reason)
            self.assertIn("Fallback HTML parser text", text)
            self.assertEqual(details["extractor"], "parser")

        with patch.object(summary_pipeline.transport, "read_url", side_effect=mock_read), \
                patch.object(summary_pipeline, "trafilatura", None):
            details = {}
            summary_pipeline.fetch_story_article(story, {}, details)
            self.assertEqual(details["extractor"], "parser")
    def test_honest_fallback_summary_prevents_empty_box(self):
        from radar.story_pages import trim_complete_sentences
        story_terra = {
            "title": "Introducing GPT-6.1 Terra",
            "title_vi": "Ra mắt GPT-6.1 Terra",
            "summary_vi": "Đưa ra việc sử dụng máy tính nhanh chóng và khả năng cho tất cả mọi người",
            "coverage": [{"publisher": "openai", "url": "https://openai.com/index/introducing-gpt-6-1-terra"}]
        }
        fb1 = summary_pipeline.honest_fallback_summary(story_terra)
        self.assertTrue(fb1.endswith("."))
        self.assertGreater(len(trim_complete_sentences(fb1)), 0)

        story_hn = {
            "title": "Torvalds: AI is fine for competent devs",
            "title_vi": "Torvalds: AI là tốt cho các nhà phát triển có năng lực",
            "summary_vi": None,
            "coverage": [{"publisher": "The Register", "url": "https://theregister.example/torvalds"}]
        }
        fb2 = summary_pipeline.honest_fallback_summary(story_hn)
        self.assertTrue(fb2.endswith("."))
        self.assertIn("The Register", fb2)
        self.assertIn("Torvalds: AI là tốt cho các nhà phát triển có năng lực", fb2)
        self.assertGreater(len(trim_complete_sentences(fb2)), 0)

    def test_highest_importance_stories_summarized_first(self):
        now_iso = "2026-10-27T12:00:00Z"
        low_story = {
            "id": "story-low",
            "title": "Low Priority Story",
            "importance_weight": 0.1,
            "published_at": now_iso,
            "url": "https://example.com/low",
            "coverage": [{"publisher": "blog", "url": "https://example.com/low"}]
        }
        high_story = {
            "id": "story-high",
            "title": "High Priority Story",
            "importance_weight": 0.9,
            "published_at": now_iso,
            "url": "https://example.com/high",
            "coverage": [{"publisher": "news", "url": "https://example.com/high"}]
        }
        mid_story = {
            "id": "story-mid",
            "title": "Mid Priority Story",
            "importance_weight": 0.5,
            "published_at": now_iso,
            "url": "https://example.com/mid",
            "coverage": [{"publisher": "docs", "url": "https://example.com/mid"}]
        }
        payload = {"generated_at": now_iso, "stories": [low_story, high_story, mid_story]}
        tried_titles = []

        def mock_fetch(story, **kwargs):
            tried_titles.append(story["title"])
            return ""

        cfg = summary_gemini.Config(
            api_key="test-key", confirmed=True, max_requests=10, batch_size=5, max_chars=10000, paid=False)
        with patch.object(summary_pipeline.summary_budget, "capacity_error", return_value=None):
            stats, _ = summary_pipeline.summarize_payload(
                payload, {}, config=cfg, article_fetch_fn=mock_fetch, ledger_path=Path("dummy-ledger.json"))
        self.assertEqual(tried_titles, ["High Priority Story", "Mid Priority Story", "Low Priority Story"])

    def test_extractor_order_trafilatura_first_then_fallback(self):
        from unittest.mock import MagicMock
        html = ("<article><p>" + "Fallback HTML parser text that has sufficient length. " * 10 + "</p></article>")

        # 1. Trafilatura returns sufficient text (>= 300 chars) -> used first
        mock_traf = MagicMock()
        mock_traf.extract.return_value = "Trafilatura extracted content with high fidelity. " * 10
        with patch.object(summary_pipeline, "trafilatura", mock_traf):
            parser = summary_pipeline.parse_article(html, "https://example.com/story")
            self.assertEqual(parser.extractor, "trafilatura")
            self.assertIn("Trafilatura extracted content", "\n".join(parser.parts))
            self.assertTrue(mock_traf.extract.called)

        # 2. Trafilatura returns too short text (< 300 chars) -> falls back to existing parser
        mock_traf_short = MagicMock()
        mock_traf_short.extract.return_value = "Short text"
        with patch.object(summary_pipeline, "trafilatura", mock_traf_short):
            parser = summary_pipeline.parse_article(html, "https://example.com/story")
            self.assertEqual(parser.extractor, "parser")
            self.assertIn("Fallback HTML parser text", "\n".join(parser.parts))

        # 3. Trafilatura raises an exception -> gracefully falls back to existing parser
        mock_traf_err = MagicMock()
        mock_traf_err.extract.side_effect = RuntimeError("extractor crashed")
        with patch.object(summary_pipeline, "trafilatura", mock_traf_err):
            parser = summary_pipeline.parse_article(html, "https://example.com/story")
            self.assertEqual(parser.extractor, "parser")
            self.assertIn("Fallback HTML parser text", "\n".join(parser.parts))


if __name__ == "__main__":
    unittest.main()

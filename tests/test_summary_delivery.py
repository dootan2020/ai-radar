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

                with patch.object(summary_pipeline.transport, "read_url", side_effect=read):
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


if __name__ == "__main__":
    unittest.main()

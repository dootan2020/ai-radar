"""Article fetch and extraction on trimmed copies of real pages the newsroom failed to read.

The pages were saved on 2026-11-04 from the stories lost between 02/11 and 04/11; see
tests/fixtures/doc-bai/index.json. No test touches the network.
"""

from email.message import Message
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from radar import summary_pipeline
from radar.transport import ResponseText


FIXTURES = Path(__file__).parent / "fixtures" / "doc-bai"
ALLOW_ALL = "User-agent: *\nAllow: /"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def redirect(url, location, code=302):
    headers = Message()
    headers["Location"] = location
    return HTTPError(url, code, "Found", headers, None)


def status_error(url, code):
    return HTTPError(url, code, "Forbidden", Message(), None)


class Site:
    """A fake publisher: maps a URL to a page, a robots.txt body, or an HTTP error to raise."""

    def __init__(self, routes):
        self.routes, self.fetched = routes, []

    def read_url(self, url, **kwargs):
        self.fetched.append(url)
        answer = self.routes.get(url)
        if answer is None:
            raise AssertionError(f"unexpected fetch: {url}")
        if isinstance(answer, Exception):
            raise answer
        if url.endswith("/robots.txt"):
            return ResponseText(answer, status=200, url=url, content_type="text/plain")
        return ResponseText(answer, status=200, url=url, content_type="text/html; charset=utf-8")

    def fetch(self, url):
        details = {}
        with patch.object(summary_pipeline.transport, "read_url", side_effect=self.read_url):
            text, reason = summary_pipeline.fetch_article_result({"url": url}, {}, details=details)
        return text, reason, details


class FetchRealPagesTests(unittest.TestCase):
    def setUp(self):
        for target in (patch("socket.create_connection", side_effect=AssertionError("network forbidden")),
                       # The runner's Python has no trafilatura, so these tests cover the parser it uses.
                       patch.object(summary_pipeline, "trafilatura", None)):
            target.start()
            self.addCleanup(target.stop)

    def test_fixture_index_lists_every_saved_page(self):
        index = json.loads(fixture("index.json"))
        self.assertEqual(set(index), {path.name for path in FIXTURES.iterdir()} - {"index.json"})

    # robots.txt

    def test_redirected_robots_txt_is_followed_and_cnn_article_is_read(self):
        page = "https://www.cnn.com/2026/10/30/business/ai-stocks-bonds-debt"
        edition = "https://edition.cnn.com/2026/10/30/business/ai-stocks-bonds-debt"
        site = Site({
            "https://www.cnn.com/robots.txt": redirect("https://www.cnn.com/robots.txt",
                                                       "https://edition.cnn.com/robots.txt"),
            "https://edition.cnn.com/robots.txt": fixture("cnn-edition-robots.txt"),
            page: redirect(page, edition),
            edition: fixture("cnn-ai-stocks-bonds-debt.html"),
        })
        text, reason, _ = site.fetch(page)
        self.assertIsNone(reason)
        self.assertGreater(len(text), 7000)
        self.assertIn("A television shows Intel Corp. news", text[:200])

    def test_redirected_robots_txt_that_disallows_still_refuses(self):
        site = Site({
            "https://publisher.example/robots.txt": redirect("https://publisher.example/robots.txt",
                                                             "https://cdn.publisher.example/robots.txt", 301),
            "https://cdn.publisher.example/robots.txt": "User-agent: *\nDisallow: /",
        })
        self.assertEqual(site.fetch("https://publisher.example/story"),
                         ("", "robots", {"cause": "disallow"}))
        self.assertNotIn("https://publisher.example/story", site.fetched)

    def test_robots_txt_redirect_chain_longer_than_five_hops_is_unavailable(self):
        routes = {f"https://publisher.example/r{hop}/robots.txt": redirect(
            f"https://publisher.example/r{hop}/robots.txt", f"https://publisher.example/r{hop + 1}/robots.txt")
            for hop in range(1, 7)}
        routes["https://publisher.example/robots.txt"] = redirect(
            "https://publisher.example/robots.txt", "https://publisher.example/r1/robots.txt")
        site = Site(routes)
        self.assertEqual(site.fetch("https://publisher.example/story"),
                         ("", "robots", {"cause": "unavailable_302"}))
        self.assertEqual(len(site.fetched), 6)

    def test_robots_txt_redirect_loop_is_unavailable(self):
        site = Site({
            "https://publisher.example/robots.txt": redirect("https://publisher.example/robots.txt",
                                                             "https://publisher.example/other/robots.txt"),
            "https://publisher.example/other/robots.txt": redirect("https://publisher.example/other/robots.txt",
                                                                   "https://publisher.example/robots.txt"),
        })
        self.assertEqual(site.fetch("https://publisher.example/story"),
                         ("", "robots", {"cause": "unavailable_302"}))

    def test_real_robots_txt_disallows_are_still_refused(self):
        for robots, page in (("x-robots.txt", "https://x.com/btibor91/status/2116955752267206776"),
                             ("theregister-robots.txt", "https://www.theregister.com/ai-and-ml/2026/11/03/"
                              "british-fintech-revolut-slashes-ai-coding-costs-10x-by-cutting-out-claude-and-"
                              "going-self-hosted/5307345")):
            with self.subTest(robots=robots):
                origin = "/".join(page.split("/")[:3])
                site = Site({f"{origin}/robots.txt": fixture(robots)})
                self.assertEqual(site.fetch(page), ("", "robots", {"cause": "disallow"}))
                self.assertEqual(site.fetched, [f"{origin}/robots.txt"])

    def test_bot_wall_on_robots_txt_is_refused_and_named(self):
        # CNBC answers the runner's user agent with an Akamai 403 on robots.txt itself.
        site = Site({"https://www.cnbc.com/robots.txt": status_error("https://www.cnbc.com/robots.txt", 403)})
        self.assertEqual(site.fetch("https://www.cnbc.com/2026/11/02/south-korea-ai-spending-budget.html"),
                         ("", "robots", {"cause": "unavailable_403"}))
        self.assertEqual(len(site.fetched), 1)

    def test_bot_wall_on_the_page_is_named_by_its_status(self):
        page = "https://openai.com/index/scaling-git-at-openai"
        site = Site({"https://openai.com/robots.txt": ALLOW_ALL, page: status_error(page, 403)})
        self.assertEqual(site.fetch(page), ("", "error", {"cause": "http_403"}))

    def test_transport_failure_is_named_by_its_exception_class(self):
        page = "https://publisher.example/story"
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, page: TimeoutError("timed out")})
        self.assertEqual(site.fetch(page), ("", "error", {"cause": "TimeoutError"}))

    # Extraction

    def test_valueless_class_attribute_does_not_crash_the_parser(self):
        parser = summary_pipeline.parse_article('<main><div class><p id>' + "Body text. " * 40 + "</p></div>"
                                                '<a href>bare link</a></main>', "https://publisher.example/s")
        self.assertIn("Body text.", parser.parts[0])
        page = "https://proton.me/blog/ai-manifesto"
        site = Site({"https://proton.me/robots.txt": ALLOW_ALL, page: fixture("proton-ai-manifesto.html")})
        text, reason, _ = site.fetch(page)
        self.assertIsNone(reason)
        self.assertGreater(len(text), 8000)
        self.assertTrue(text.startswith("For the last couple of decades"))

    def test_parse_failure_is_named_by_its_exception_class(self):
        page = "https://publisher.example/story"
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, page: "<p>x</p>"})
        with patch.object(summary_pipeline, "parse_article", side_effect=AttributeError("boom")):
            self.assertEqual(site.fetch(page), ("", "error", {"cause": "parse_AttributeError"}))

    def test_nested_article_tags_keep_the_abc_article_body(self):
        page = "https://www.abc.net.au/news/2026-10-19/ai-stock-market-concentration-data/107261078"
        site = Site({"https://www.abc.net.au/robots.txt": ALLOW_ALL, page: fixture("abc-ai-stock-market-concentration.html")})
        text, reason, _ = site.fetch(page)
        self.assertIsNone(reason)
        self.assertGreater(len(text), 9000)
        self.assertTrue(text.startswith("Experts warn AI's dominance of the US stock market"))

    def test_side_card_articles_do_not_hide_the_hugging_face_post(self):
        page = "https://huggingface.co/blog/transformers-mic"
        site = Site({"https://huggingface.co/robots.txt": ALLOW_ALL, page: fixture("huggingface-transformers-mic.html")})
        text, reason, _ = site.fetch(page)
        self.assertIsNone(reason)
        self.assertGreater(len(text), 10000)
        self.assertIn("scaled dot-product attention (SDPA) for T5", text)

    def test_teaser_inside_an_article_stays_too_short_beside_long_related_news(self):
        related = "<section><p>" + "Unrelated market story with its own headline. " * 40 + "</p></section>"
        html = f"<main><article><p>A short subscriber teaser.</p></article>{related}</main>"
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, "https://publisher.example/s": html})
        self.assertEqual(site.fetch("https://publisher.example/s")[:2], ("", "too_short"))

    def test_sibling_related_story_does_not_complete_a_nested_teaser(self):
        # The fragment's only ancestor is the teaser; the long <article> beside it is another story.
        related = "<article><h2>Related</h2><p>" + "A different story about chip exports. " * 30 + "</p></article>"
        html = ("<main><article><p>A short subscriber teaser.</p><article><p>Short fragment.</p></article>"
                f"</article>{related}</main>")
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, "https://publisher.example/s": html})
        self.assertEqual(site.fetch("https://publisher.example/s"),
                         ("", "too_short", {"cause": "15 chars"}))  # the fragment, never the sibling
        empty_fragment = html.replace("<p>Short fragment.</p>", "")
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, "https://publisher.example/s": empty_fragment})
        self.assertEqual(site.fetch("https://publisher.example/s"),
                         ("", "too_short", {"cause": "26 chars"}))  # the teaser around the empty fragment

    def test_enclosing_article_completes_its_own_nested_fragment(self):
        body = "<p>" + "The enclosing article carries the reported event in full. " * 10 + "</p>"
        html = (f"<main><article>{body}<article><p>Nested quote card.</p></article></article>"
                "<article><p>Sibling card.</p></article></main>")
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, "https://publisher.example/s": html})
        text, reason, _ = site.fetch("https://publisher.example/s")
        self.assertIsNone(reason)
        self.assertIn("reported event in full", text)
        self.assertIn("Nested quote card.", text)
        self.assertNotIn("Sibling card.", text)

    # Paywalls

    def test_long_teaser_ending_in_a_bare_subscription_plea_is_a_paywall(self):
        teaser = "<p>" + "The opening paragraphs of a reported story about model pricing. " * 25 + "</p>"
        html = f"<article>{teaser}<p>Please subscribe.</p></article>"
        site = Site({"https://publisher.example/robots.txt": ALLOW_ALL, "https://publisher.example/s": html})
        text, reason, details = site.fetch("https://publisher.example/s")
        self.assertEqual((text, reason), ("", "paywall"))
        self.assertTrue(details["cause"].startswith("phrase 'please subscribe'"))
        self.assertLess(len(teaser), summary_pipeline.PAYWALL_PLEA_MAX_CHARS)

    def test_free_newsletter_asking_readers_to_subscribe_is_read(self):
        page = "https://jack-clark.net/2026/11/02/import-ai-479-spacewar-low-latency-tasks-versus-llms-genie-4/"
        site = Site({"https://jack-clark.net/robots.txt": ALLOW_ALL, page: fixture("jack-clark-import-ai-479.html")})
        text, reason, _ = site.fetch(page)
        self.assertIsNone(reason)
        self.assertGreater(len(text), 15000)
        self.assertIn("please subscribe", text[:400])

    def test_real_paywall_pages_are_still_refused(self):
        for name, page, cause in (
                ("businessinsider-paywall.html", "https://www.businessinsider.com/anthropic-claude-internal-ai-use-"
                 "exceeds-employee-pay-tokens-2026-11", "251 chars"),
                ("scmp-plus-paywall.html", "https://www.scmp.com/plus/tech/tech-trends/article/3373080/"
                 "scmp-plus-fireside-chat-about-ai-professor-alan-macfarlane", "0 chars")):
            with self.subTest(page=name):
                origin = "/".join(page.split("/")[:3])
                site = Site({f"{origin}/robots.txt": ALLOW_ALL, page: fixture(name)})
                self.assertEqual(site.fetch(page), ("", "too_short", {"cause": cause}))

    def test_gating_phrases_still_mark_a_paywall_in_long_text(self):
        body = "<p>" + "A long free paragraph about the reported event. " * 60 + "</p>"
        for phrase in ("Please subscribe to continue reading.", "Subscribe to read the full story.",
                       "Sign in to continue.", "This story is subscriber-only.", "Members only content.",
                       "Unlock the full article today."):
            with self.subTest(phrase=phrase):
                site = Site({"https://publisher.example/robots.txt": ALLOW_ALL,
                             "https://publisher.example/s": f"<article><p>{phrase}</p>{body}</article>"})
                text, reason, details = site.fetch("https://publisher.example/s")
                self.assertEqual((text, reason), ("", "paywall"))
                self.assertTrue(details["cause"].startswith("phrase '"))


if __name__ == "__main__":
    unittest.main()

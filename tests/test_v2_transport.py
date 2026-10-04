"""Synthetic HTTP response boundaries retain observed status after headers."""

import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from radar import catalog, pipeline, transport, youtube
if __package__:
    from .test_v2_support import NOW
else:
    from test_v2_support import NOW


class SyntheticResponse(io.BytesIO):
    status = 200

    def __init__(self, content_length):
        super().__init__(b"x" * 11)
        self.headers = Message()
        if content_length:
            self.headers["Content-Length"] = "11"

    def geturl(self):
        return "https://fixture.invalid/oversized"


class ResponseEvidenceTests(unittest.TestCase):
    def test_oversized_header_or_body_retains_received_http_status(self):
        source = {"id": "oversized", "name": "Oversized fixture", "url": "https://fixture.invalid/oversized",
                  "parser": "feed", "kind": "rss", "lab": "", "group": "press", "publisher": "fixture",
                  "first_wave": True}
        for content_length in [True, False]:
            with self.subTest(content_length=content_length), tempfile.TemporaryDirectory() as folder:
                events = Path(folder) / "events.json"
                events.write_bytes(b"[]")
                with patch.object(catalog, "sources", return_value=[source]), \
                     patch.object(youtube, "collect", return_value=([], [])), \
                     patch.object(transport, "MAX_BYTES", 10), \
                     patch.object(transport, "urlopen", side_effect=lambda *args, **kwargs: SyntheticResponse(content_length)):
                    result = pipeline.build_v2(fetch=transport.read_url, now=NOW, events_path=events)
                record = next(row for row in result["sources"] if row["id"] == "oversized")
                self.assertFalse(record["ok"])
                self.assertIn("limit", record["error"])
                self.assertEqual(record["http_status"], 200)
                self.assertEqual(record["http_requests"][0]["http_status"], 200)


class TechnodeAllowanceTests(unittest.TestCase):
    def test_technode_per_source_allowance(self):
        self.assertEqual(transport.SOURCE_MAX_BYTES.get("technode"), 24 * 1024 * 1024)
        self.assertEqual(transport.max_bytes_for("technode"), 24 * 1024 * 1024)
        self.assertEqual(transport.max_bytes_for("vnexpress-so-hoa"), 8 * 1024 * 1024)
        self.assertEqual(transport.max_bytes_for(None), 8 * 1024 * 1024)
        self.assertEqual(transport.max_bytes_for("unknown-id"), 8 * 1024 * 1024)


class TransportContractTests(unittest.TestCase):
    def test_type_error_inside_transport_surfaces_after_exactly_one_call(self):
        import time
        calls = []

        def failing_transport(url, source_id=None):
            calls.append((url, source_id))
            raise TypeError("internal type error inside transport implementation")

        fetcher = transport.Fetcher(time.monotonic() + 10, failing_transport)
        with self.assertRaisesRegex(TypeError, "internal type error inside transport implementation"):
            fetcher("https://technode.com/feed/", source_id="technode")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("https://technode.com/feed/", "technode"))

    def test_explicit_source_id_passed_to_transport(self):
        import time
        received = []

        def recording_transport(url, source_id=None):
            received.append((url, source_id))
            return "<rss></rss>"

        fetcher = transport.Fetcher(time.monotonic() + 10, recording_transport)
        fetcher("https://technode.com/feed/", source_id="technode")
        self.assertEqual(received, [("https://technode.com/feed/", "technode")])

    def test_unspecified_source_id_calls_transport_without_source_id(self):
        import time
        received = []

        def legacy_transport(url):
            received.append(url)
            return "<rss></rss>"

        fetcher = transport.Fetcher(time.monotonic() + 10, legacy_transport)
        fetcher("https://example.com/feed")
        self.assertEqual(received, ["https://example.com/feed"])

    def test_fetcher_respects_technode_24_mib_allowance(self):
        import time
        chunk_12mib = "a" * (12 * 1024 * 1024)
        fetcher = transport.Fetcher(time.monotonic() + 10, lambda url, **kwargs: chunk_12mib)

        # technode succeeds with 12 MiB
        result = fetcher("https://technode.com/feed/", source_id="technode")
        self.assertEqual(len(result), 12 * 1024 * 1024)

        # standard source fails with 12 MiB (8 MiB limit)
        with self.assertRaisesRegex(ValueError, "Source response exceeds 8 MiB limit"):
            fetcher("https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss", source_id="vnexpress-so-hoa")

    def test_fetcher_rejects_technode_exceeding_24_mib(self):
        import time
        chunk_25mib = "a" * (25 * 1024 * 1024)
        fetcher = transport.Fetcher(time.monotonic() + 10, lambda url, **kwargs: chunk_25mib)
        with self.assertRaisesRegex(ValueError, "Source response exceeds 24 MiB limit"):
            fetcher("https://technode.com/feed/", source_id="technode")

    def test_read_url_respects_technode_allowance(self):
        class LargeResponse(io.BytesIO):
            status = 200
            def __init__(self, size):
                super().__init__(b"x" * size)
                self.headers = Message()
                self.headers["Content-Length"] = str(size)
            def geturl(self):
                return "https://technode.com/feed/"

        # 10 MiB for technode succeeds
        with patch.object(transport, "urlopen", side_effect=lambda *args, **kwargs: LargeResponse(10 * 1024 * 1024)):
            res = transport.read_url("https://technode.com/feed/", source_id="technode")
            self.assertEqual(len(res), 10 * 1024 * 1024)

        # 10 MiB for standard source raises ValueError (8 MiB limit)
        with patch.object(transport, "urlopen", side_effect=lambda *args, **kwargs: LargeResponse(10 * 1024 * 1024)):
            with self.assertRaisesRegex(ValueError, "Source response exceeds 8 MiB limit"):
                transport.read_url("https://standard.invalid/feed", source_id="standard")

        # 25 MiB for technode raises ValueError (24 MiB limit)
        with patch.object(transport, "urlopen", side_effect=lambda *args, **kwargs: LargeResponse(25 * 1024 * 1024)):
            with self.assertRaisesRegex(ValueError, "Source response exceeds 24 MiB limit"):
                transport.read_url("https://technode.com/feed/", source_id="technode")


class RedirectHandlingTests(unittest.TestCase):
    def test_safe_redirect_handler_follows_redirect_and_rewrites_location(self):
        from urllib.request import Request
        import urllib.parse

        handler = transport.SafeRedirectHandler()
        req = Request("https://vnexpress.net/rss/so-hoa.rss", headers={"User-Agent": transport.USER_AGENT})
        headers = Message()
        headers["Location"] = "/rss/khoa-hoc-cong-nghe.rss"
        newurl = urllib.parse.urljoin(req.full_url, headers["Location"])
        new_req = handler.redirect_request(req, None, 302, "Found", headers, newurl)
        self.assertIsNotNone(new_req)
        self.assertEqual(new_req.full_url, "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss")
        self.assertEqual(new_req.headers.get("User-agent"), transport.USER_AGENT)

    def test_safe_redirect_handler_strips_auth_on_non_github_redirect(self):
        from urllib.request import Request

        handler = transport.SafeRedirectHandler()
        req = Request("https://api.github.com/data", headers={"Authorization": "token secret", "User-Agent": transport.USER_AGENT})
        req.unredirected_hdrs["Authorization"] = "token secret"
        new_req = handler.redirect_request(req, None, 302, "Found", {}, "https://other.invalid/data")
        self.assertNotIn("Authorization", new_req.headers)
        self.assertNotIn("Authorization", getattr(new_req, "unredirected_hdrs", {}))
        self.assertEqual(new_req.headers.get("User-agent"), transport.USER_AGENT)


class CnbcDecisionTests(unittest.TestCase):
    def test_cnbc_tech_is_disabled_with_github_runner_reason(self):
        sources = {s["id"]: s for s in catalog.sources(NOW)}
        cnbc = sources.get("cnbc-tech")
        self.assertIsNotNone(cnbc)
        self.assertTrue(cnbc.get("disabled"))
        self.assertIn("máy dựng của GitHub", cnbc.get("disabled_reason", ""))
        self.assertIn("403", cnbc.get("disabled_reason", ""))

    def test_build_v2_does_not_fetch_cnbc_and_records_disabled_status(self):
        with tempfile.TemporaryDirectory() as folder:
            events = Path(folder) / "events.json"
            events.write_bytes(b"[]")
            fetched_urls = []

            def tracking_fetch(url, **kwargs):
                fetched_urls.append(url)
                return transport.ResponseText("<rss></rss>", status=200, url=url)

            result = pipeline.build_v2(fetch=tracking_fetch, now=NOW, events_path=events)
            cnbc_record = next((s for s in result["sources"] if s["id"] == "cnbc-tech"), None)
            self.assertIsNotNone(cnbc_record)
            self.assertTrue(cnbc_record["disabled"])
            self.assertFalse(cnbc_record["ok"])
            self.assertEqual(cnbc_record["count"], 0)
            self.assertIn("Disabled:", cnbc_record["error"])
            self.assertNotIn("https://www.cnbc.com/id/19854910/device/rss/rss.html", fetched_urls)

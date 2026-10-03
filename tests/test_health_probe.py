"""Offline health checks exercise real parsing over the public HTTP boundary."""

import io
from http.client import IncompleteRead
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from radar import health_probe

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


class Response(io.BytesIO):
    def __init__(self, content, url, status=200):
        super().__init__(content)
        self.url, self.status = url, status
        self.headers = {}

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url


class HealthProbeTests(unittest.TestCase):
    def setUp(self):
        self.homepage = (ROOT / "site/index.html").read_bytes()
        self.payload = {"schema_version": 2, "generated_at": NOW.isoformat(),
                        "stories": [], "sources": [], "sections": {}}
        self.overrides, self.requests = {}, []

    def http(self, request, timeout):
        self.assertLessEqual(timeout, health_probe.REQUEST_TIMEOUT)
        self.assertGreater(timeout, 0)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertTrue(request.full_url.startswith(health_probe.SITE_URL))
        self.requests.append(request.full_url)
        path = request.full_url.removeprefix(health_probe.SITE_URL)
        content = self.overrides.get(path)
        if isinstance(content, Exception):
            raise content
        if content is None:
            content = (self.homepage if not path else json.dumps(self.payload).encode()
                       if path == "data/radar.json" else (ROOT / "site" / path).read_bytes())
        if isinstance(content, Response):
            return content
        return Response(content, request.full_url)

    def probe(self):
        with patch.object(health_probe, "urlopen", side_effect=self.http), \
                patch.object(health_probe, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            result = health_probe.probe()
        return {check["id"]: check for check in result["checks"]}

    def test_real_homepage_and_all_referenced_main_assets_are_checked(self):
        checks = self.probe()
        self.assertTrue(all(row["ok"] for row in checks.values()), checks)
        html = self.homepage.decode()
        references = set(re.findall(r'(?:src|href)="([^"/:]+\.(?:css|js))"', html))
        for path in (ROOT / "site").glob("*.js"):
            if path.name in health_probe.ASSETS:
                references.update(re.findall(r"from ['\"]\./([^'\"]+)['\"]", path.read_text(encoding="utf-8")))
        self.assertTrue(references.issubset(set(health_probe.ASSETS)), references)
        for asset in references:
            self.assertIn(health_probe.SITE_URL + asset, self.requests)

    def test_http_failure_or_unrelated_successful_html_fails_homepage(self):
        for body in (HTTPError(health_probe.SITE_URL, 503, "private-sentinel", {}, None),
                     b"<html><title>Maintenance</title></html>"):
            with self.subTest(body=type(body).__name__):
                self.overrides[""] = body
                row = self.probe()["homepage"]
                self.assertFalse(row["ok"])
                self.assertNotIn("private-sentinel", row["detail"])

    def test_missing_each_identity_marker_fails_homepage(self):
        original = self.homepage
        for marker in (b'property="og:site_name"', b'id="top"', b'id="board"', b'src="app.js"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, original)
                self.homepage = original.replace(marker, b'data-removed="true"')
                self.assertFalse(self.probe()["homepage"]["ok"])

    def test_main_style_or_imported_module_http_failure_is_visible(self):
        for asset in ("styles.css", "live.js"):
            with self.subTest(asset=asset):
                self.overrides = {asset: HTTPError(health_probe.SITE_URL + asset, 404, "missing", {}, None)}
                self.assertFalse(self.probe()["asset:" + asset]["ok"])

    def test_new_main_reference_is_discovered_and_checked_without_external_font_requests(self):
        self.homepage += b'<link rel="stylesheet" href="new-main.css">'
        self.overrides["new-main.css"] = HTTPError(health_probe.SITE_URL + "new-main.css", 404, "missing", {}, None)
        self.assertFalse(self.probe()["asset:new-main.css"]["ok"])
        self.assertTrue(all(url.startswith(health_probe.SITE_URL) for url in self.requests))

    def test_non_200_success_status_and_foreign_redirect_are_rejected(self):
        for response in (Response(b"", health_probe.SITE_URL + "styles.css", 204),
                         Response(b"body{}", "https://other.example/styles.css")):
            self.overrides["styles.css"] = response
            self.assertFalse(self.probe()["asset:styles.css"]["ok"])

    def test_snapshot_http_parse_and_minimum_consumer_shape(self):
        variants = [URLError("private-sentinel"), b"not JSON", b"[]", b"{}"]
        for changes in ({"schema_version": 1}, {"schema_version": True}, {"sources": {}},
                        {"stories": None}, {"sections": []}):
            variants.append(json.dumps({**self.payload, **changes}).encode())
        for value in variants:
            with self.subTest(value=type(value).__name__):
                self.overrides["data/radar.json"] = value
                row = self.probe()["snapshot"]
                self.assertFalse(row["ok"])
                self.assertNotIn("private-sentinel", row["detail"])

    def test_snapshot_freshness_uses_existing_three_hour_boundary(self):
        for age, valid in ((0, True), (10800, True), (10801, False), (-1, False)):
            with self.subTest(age=age):
                self.payload["generated_at"] = (NOW - timedelta(seconds=age)).isoformat()
                self.payload["freshness"] = {"stale_after_seconds": 999999}
                self.assertEqual(self.probe()["snapshot"]["ok"], valid)

    def test_nonfinite_json_rejected_like_browser_json_parse(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=str(value)):
                self.payload["stories"] = [value]
                self.assertFalse(self.probe()["snapshot"]["ok"])

    def test_incomplete_read_is_sanitized_and_confirms_after_second_probe(self):
        from radar import health_monitor

        class InterruptedResponse(Response):
            def read1(self, size=-1):
                raise IncompleteRead(b"private-sentinel", 500)

        original = self.http

        def interrupted(request, timeout):
            if request.full_url == health_probe.SITE_URL:
                return InterruptedResponse(b"", request.full_url)
            return original(request, timeout)

        self.http = interrupted
        with patch.object(health_monitor, "probe", side_effect=lambda: {
                "checked_at": NOW.isoformat(), "generated_at": NOW.isoformat(),
                "checks": list(self.probe().values())}), patch.object(health_monitor, "sleep"):
            report = health_monitor.collect_report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual([row["id"] for row in report["confirmed_failures"]], ["homepage"])
        self.assertNotIn("private-sentinel", json.dumps(report))

    def test_missing_invalid_or_naive_snapshot_timestamp_is_rejected(self):
        for value in (None, "invalid", "2026-10-03T12:00:00", 42):
            with self.subTest(value=value):
                self.payload["generated_at"] = value
                self.assertFalse(self.probe()["snapshot"]["ok"])
        del self.payload["generated_at"]
        self.assertFalse(self.probe()["snapshot"]["ok"])

    def test_response_limit_timeout_and_probe_deadline_fail_safely(self):
        for body in (b"x" * (health_probe.MAX_BYTES + 1), TimeoutError("private-sentinel")):
            self.overrides["styles.css"] = body
            row = self.probe()["asset:styles.css"]
            self.assertFalse(row["ok"])
            self.assertNotIn("private-sentinel", row["detail"])
        self.overrides = {}
        with patch.object(health_probe, "monotonic", side_effect=[0] + [1000] * 100):
            checks = self.probe()
        self.assertTrue(any(not row["ok"] for row in checks.values()))


if __name__ == "__main__":
    unittest.main()

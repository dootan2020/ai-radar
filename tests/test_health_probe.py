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
from urllib.parse import urljoin

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
                       if path in ("data/radar.json", "data/radar-ui.json")
                       else (ROOT / "site" / path).read_bytes())
        if isinstance(content, Response):
            return content
        return Response(content, request.full_url)

    def probe(self):
        return {check["id"]: check for check in self.report()["checks"]}

    def report(self):
        with patch.object(health_probe, "urlopen", side_effect=self.http), \
                patch.object(health_probe, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            return health_probe.probe()

    def test_real_homepage_and_all_referenced_main_assets_are_checked(self):
        checks = self.probe()
        self.assertTrue(all(row["ok"] for row in checks.values()), checks)
        html = self.homepage.decode()
        references = set(re.findall(r'(?:src|href)="([^"/:]+\.(?:css|js))"', html))
        pending = [path for path in references if path.endswith(".js")]
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            source = (ROOT / "site" / path).read_text(encoding="utf-8")
            for reference in re.findall(r"(?:from\s*|import\s*\(\s*|import\s*)['\"]([^'\"]+)['\"]", source):
                url = urljoin(health_probe.SITE_URL + path, reference)
                if url.startswith(health_probe.SITE_URL):
                    dependency = url.removeprefix(health_probe.SITE_URL)
                    references.add(dependency)
                    pending.append(dependency)
        for asset in references:
            self.assertIn(health_probe.SITE_URL + asset, self.requests)
        self.assertEqual(len(self.requests), len(set(self.requests)))

    def test_reader_projection_is_fetched_and_checked(self):
        checks = self.probe()
        self.assertIn(health_probe.SITE_URL + "data/radar-ui.json", self.requests)
        self.assertTrue(checks["snapshot-ui"]["ok"])

    def test_reader_projection_missing_invalid_or_wrong_shape_fails_independently(self):
        variants = [HTTPError(health_probe.SITE_URL + "data/radar-ui.json", 404,
                              "private-sentinel", {}, None),
                    b"not JSON private-sentinel", b"[]", b"{}"]
        for changes in ({"schema_version": 1}, {"schema_version": True}, {"stories": None},
                        {"sources": {}}, {"sections": []}, {"stories": [float("nan")]},
                        {"generated_at": None}, {"generated_at": "2026-10-03T12:00:00"}):
            variants.append(json.dumps({**self.payload, **changes}).encode())
        for value in variants:
            with self.subTest(value=type(value).__name__):
                self.overrides["data/radar-ui.json"] = value
                checks = self.probe()
                self.assertTrue(checks["snapshot"]["ok"])
                self.assertTrue(any(not row["ok"] for row in checks.values()), checks)
                self.assertFalse(checks["snapshot-ui"]["ok"])
                self.assertNotIn("private-sentinel", json.dumps(checks))

    def test_reader_projection_freshness_uses_existing_three_hour_boundary(self):
        for age, valid in ((0, True), (10800, True), (10801, False), (-1, False)):
            with self.subTest(age=age):
                self.payload["generated_at"] = (NOW - timedelta(seconds=age)).isoformat()
                self.payload["freshness"] = {"stale_after_seconds": 999999}
                checks = self.probe()
                self.assertIn("snapshot-ui", checks)
                self.assertEqual(checks["snapshot-ui"]["ok"], valid)

    def test_reader_projection_from_another_fresh_build_fails(self):
        for stamp in ((NOW - timedelta(seconds=1)).isoformat(), "2026-10-03T12:00:00Z"):
            with self.subTest(stamp=stamp):
                projection = {**self.payload, "generated_at": stamp}
                self.overrides["data/radar-ui.json"] = json.dumps(projection).encode()
                checks = self.probe()
                self.assertTrue(checks["snapshot"]["ok"])
                self.assertTrue(any(not row["ok"] for row in checks.values()), checks)
                self.assertIn("generated_at", checks["snapshot-ui"]["detail"])

    def test_stale_projection_fails_while_full_snapshot_remains_fresh(self):
        projection = {**self.payload, "generated_at": (NOW - timedelta(seconds=10801)).isoformat()}
        self.overrides["data/radar-ui.json"] = json.dumps(projection).encode()
        checks = self.probe()
        self.assertTrue(checks["snapshot"]["ok"])
        self.assertFalse(checks["snapshot-ui"]["ok"])
        self.assertIn("stale", checks["snapshot-ui"]["detail"])

    def test_remote_timestamps_never_escape_into_report_or_cli_output(self):
        from radar import health_monitor

        for path in ("data/radar.json", "data/radar-ui.json"):
            with self.subTest(path=path):
                self.overrides = {path: json.dumps({**self.payload,
                    "generated_at": "2026-10-03T12:00:00Z\nprivate-sentinel"}).encode()}
                output = io.StringIO()
                with patch.object(health_monitor, "probe", side_effect=self.report), \
                        patch.object(health_monitor, "sleep"), \
                        patch("sys.stdout", output), patch("sys.stderr", output):
                    code = health_monitor.main([])
                self.assertEqual(code, 1)
                self.assertNotIn("private-sentinel", output.getvalue())

    def test_reader_projection_failure_is_confirmed_only_after_second_probe(self):
        from radar import health_monitor

        self.overrides["data/radar-ui.json"] = b"invalid projection"
        with patch.object(health_monitor, "probe", side_effect=self.report) as probe, \
                patch.object(health_monitor, "sleep") as sleep:
            report = health_monitor.collect_report()
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(30)
        self.assertEqual(report["status"], "failed")
        self.assertEqual([row["id"] for row in report["confirmed_failures"]], ["snapshot-ui"])

    def test_reader_projection_recovers_on_confirmation_without_an_incident(self):
        from radar import health_monitor

        self.overrides["data/radar-ui.json"] = b"invalid projection"

        def observed():
            report = self.report()
            self.overrides.clear()
            return report

        with patch.object(health_monitor, "probe", side_effect=observed) as probe, \
                patch.object(health_monitor, "sleep") as sleep:
            report = health_monitor.collect_report()
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(30)
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["confirmed_failures"], [])

    def test_nested_imports_reexports_and_cycles_are_checked_once(self):
        self.overrides.update({
            "app.js": b"import { view } from './parts/view.js'; import('./parts/lazy.js');",
            "parts/view.js": b"import '../shared.js'; export { item } from './item.js';",
            "parts/item.js": b"export * from '../shared.js';",
            "parts/lazy.js": b"import '../app.js';",
            "shared.js": b"export const item = 1;",
        })
        checks = self.probe()
        self.assertTrue(all(row["ok"] for row in checks.values()), checks)
        for name in ("parts/view.js", "parts/item.js", "parts/lazy.js", "shared.js"):
            self.assertIn("asset:" + name, checks)
        self.assertEqual(len(self.requests), len(set(self.requests)))

    def test_new_import_failure_is_visible_for_http_empty_and_html_responses(self):
        for response in (HTTPError("https://example.invalid", 404, "private-sentinel", {}, None),
                         b"", b"<!doctype html><title>private-sentinel</title>"):
            with self.subTest(response=type(response).__name__):
                self.overrides = {"app.js": b"import './new-feature.js';", "new-feature.js": response}
                checks = self.probe()
                self.assertFalse(checks["asset:new-feature.js"]["ok"])
                self.assertNotIn("private-sentinel", json.dumps(checks))

    def test_semicolonless_local_export_does_not_hide_next_import(self):
        self.overrides.update({"app.js": b"const item = 1; export { item }\nimport './missing.js';",
                               "missing.js": b""})
        checks = self.probe()
        self.assertFalse(checks["asset:missing.js"]["ok"])

    def test_modulepreload_discovers_dependencies_without_filename_extension(self):
        self.homepage += b'<link rel="modulepreload" href="parts/preloaded">'
        self.overrides.update({"parts/preloaded": b"import './child.mjs';",
                               "parts/child.mjs": b"export const value = 1;"})
        checks = self.probe()
        self.assertTrue(checks["asset:parts/preloaded"]["ok"])
        self.assertTrue(checks["asset:parts/child.mjs"]["ok"])

    def test_new_import_failure_requires_two_observations(self):
        from radar import health_monitor

        self.overrides.update({"app.js": b"import './new-feature.js';",
                               "new-feature.js": b""})
        with patch.object(health_monitor, "probe", side_effect=lambda: {
                "checked_at": NOW.isoformat(), "generated_at": NOW.isoformat(),
                "checks": list(self.probe().values())}) as probe, patch.object(health_monitor, "sleep") as sleep:
            report = health_monitor.collect_report()
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(30)
        self.assertEqual(report["status"], "failed")
        self.assertEqual([row["id"] for row in report["confirmed_failures"]], ["asset:new-feature.js"])

    def test_comments_strings_and_external_imports_do_not_create_local_requests(self):
        self.overrides["app.js"] = b'''// import './comment.js';
            /* export * from './comment-too.js'; */
            const example = "import './string.js';";
            const template = `import './template.js';`;
            import 'https://external.example/private-sentinel.js?token=secret';
        '''
        checks = self.probe()
        self.assertTrue(all(row["ok"] for row in checks.values()), checks)
        self.assertNotIn("private-sentinel", json.dumps(checks))
        self.assertNotIn(health_probe.SITE_URL + "comment.js", self.requests)

    def test_unsafe_references_fail_without_requesting_or_reporting_secrets(self):
        for reference in ("./module.js?token=private-sentinel", "./module.js#private-sentinel",
                          "../private-sentinel.js", "./%2e%2e/private-sentinel.js",
                          "https://private-sentinel@dootan2020.github.io/ai-radar/module.js",
                          "http://dootan2020.github.io/ai-radar/private-sentinel.js"):
            for source in ("homepage", "module"):
                with self.subTest(reference=reference, source=source):
                    self.requests = []
                    self.overrides = ({"": self.homepage + f'<script src="{reference}"></script>'.encode()}
                                      if source == "homepage" else
                                      {"app.js": f"import '{reference}';".encode()})
                    checks = self.probe()
                    self.assertFalse(checks["homepage" if source == "homepage" else "asset:app.js"]["ok"])
                    self.assertNotIn("private-sentinel", json.dumps(checks))
                    self.assertFalse(any("private-sentinel" in url for url in self.requests))

    def test_homepage_and_import_inventory_limits_fail_visibly(self):
        names = [f"extra-{number}.js" for number in range(health_probe.MAX_ASSETS + 1)]
        for source in ("homepage", "module"):
            with self.subTest(source=source):
                self.requests = []
                self.overrides = {name: b"export const value = 1;" for name in names}
                if source == "homepage":
                    self.overrides[""] = self.homepage + "".join(
                        f'<script src="{name}"></script>' for name in names).encode()
                else:
                    self.overrides["app.js"] = "".join(f"import './{name}';" for name in names).encode()
                checks = self.probe()
                row = checks["homepage" if source == "homepage" else "asset:app.js"]
                self.assertFalse(row["ok"])
                self.assertIn("capacity", row["detail"])
                self.assertLessEqual(len(self.requests), health_probe.MAX_ASSETS + 3)

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

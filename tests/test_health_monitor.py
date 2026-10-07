"""Confirmation and CLI contracts for health observations, without live writes."""

import io
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from radar import health_monitor
from radar.site_config import SITE_URL


def sample(failed=(), at="2026-10-03T12:00:00Z"):
    return {"checked_at": at, "generated_at": "2026-10-03T11:00:00Z", "checks": [
        {"id": name, "url": SITE_URL, "ok": name not in failed,
         "detail": "HTTP 503" if name in failed else "OK"}
        for name in ("homepage", "snapshot", "asset:styles.css")]}


class HealthMonitorTests(unittest.TestCase):
    def collect(self, observations):
        with patch.object(health_monitor, "probe", side_effect=observations) as probe, \
                patch.object(health_monitor, "sleep") as sleep:
            report = health_monitor.collect_report()
        return report, probe.call_count, sleep

    def test_healthy_first_sample_does_not_sleep_or_probe_again(self):
        report, calls, sleep = self.collect([sample()])
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["confirmed_failures"], [])
        self.assertEqual(calls, 1)
        sleep.assert_not_called()

    def test_single_blip_followed_by_health_is_not_an_incident(self):
        report, calls, sleep = self.collect([sample(["homepage"]), sample()])
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["confirmed_failures"], [])
        self.assertEqual(calls, 2)
        sleep.assert_called_once_with(30)

    def test_two_samples_confirm_only_shared_failed_check_ids(self):
        report, _, _ = self.collect([sample(["homepage", "snapshot"]),
                                    sample(["homepage", "asset:styles.css"])])
        self.assertEqual(report["status"], "failed")
        self.assertEqual([row["id"] for row in report["confirmed_failures"]], ["homepage"])

    def test_unrelated_failures_remain_inconclusive_not_recovery(self):
        report, _, _ = self.collect([sample(["homepage"]), sample(["snapshot"])])
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["confirmed_failures"], [])

    def run_main(self, observations, argv=(), api_error=None):
        output = io.StringIO()
        env = {"GITHUB_REPOSITORY": "owner/radar", "GITHUB_TOKEN": "private-sentinel",
               "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY_OWNER": "owner"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(health_monitor, "probe", side_effect=observations), \
                patch.object(health_monitor, "sleep"), \
                patch("radar.failure_alert.urlopen", side_effect=api_error or AssertionError("Unexpected API call")), \
                patch("sys.stdout", output), patch("sys.stderr", output):
            code = health_monitor.main(list(argv))
        self.assertNotIn("private-sentinel", output.getvalue())
        return code, output.getvalue()

    def test_read_only_cli_has_no_github_requests_for_healthy_failed_or_inconclusive(self):
        self.assertEqual(self.run_main([sample()])[0], 0)
        self.assertEqual(self.run_main([sample(["homepage"])] * 2)[0], 1)
        self.assertEqual(self.run_main([sample(["homepage"]), sample(["snapshot"])])[0], 1)

    def test_github_failure_returns_nonzero_and_never_logs_token_or_exception_body(self):
        for error in (HTTPError("https://api.github.com", 403, "private-sentinel", {}, None),
                      URLError("private-sentinel")):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(self.run_main([sample()], ["--report"], error)[0], 1)

    def test_missing_report_token_is_safe_and_inconclusive_never_calls_github(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/radar"}, clear=True), \
                patch.object(health_monitor, "probe", return_value=sample()), \
                patch("radar.failure_alert.urlopen") as http, \
                patch("sys.stdout", output), patch("sys.stderr", output):
            self.assertEqual(health_monitor.main(["--report"]), 1)
        http.assert_not_called()
        self.assertIn("Missing GITHUB_TOKEN", output.getvalue())
        self.assertEqual(self.run_main([sample(["homepage"]), sample(["snapshot"])], ["--report"])[0], 1)


if __name__ == "__main__":
    unittest.main()

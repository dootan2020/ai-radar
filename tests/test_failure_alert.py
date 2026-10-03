"""Offline checks of the real alert entry point and GitHub HTTP boundary."""

import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from radar.failure_alert import AlertError, GitHub, main, publish_reason


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.event_path = Path(self.directory.name) / "event.json"
        self.status_path = Path(self.directory.name) / "publish-status.json"
        self.event = {
            "action": "completed",
            "repository": {"full_name": "owner/radar", "owner": {"login": "owner"}},
            "workflow_run": {"id": 42, "run_attempt": 2, "name": "Update AI Radar",
                             "head_branch": "main", "head_sha": "a" * 40,
                             "head_repository": {"full_name": "owner/radar"}, "conclusion": "failure"},
        }
        self.issues, self.writes, self.requests = [], [], []
        self.jobs = [{"name": "update", "conclusion": "failure", "steps": [
            {"name": "Fetch public sources", "conclusion": "failure"}]}]
        self.failure = None

    def http(self, request, timeout):
        self.assertEqual(timeout, 15)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-sentinel")
        self.assertTrue(request.full_url.startswith("https://api.github.com/repos/owner/radar/"))
        self.requests.append((request.method, request.full_url))
        if self.failure:
            raise self.failure
        if request.method == "GET":
            response = {"jobs": self.jobs} if "/jobs?" in request.full_url else self.issues
        else:
            payload = json.loads(request.data)
            self.writes.append((request.method, request.full_url, payload))
            if request.method == "POST":
                self.issues.append({**payload, "number": 17, "user": {"login": "github-actions[bot]"}})
            else:
                self.issues[0].update(payload)
            response = {"number": 17}
        return io.BytesIO(json.dumps(response).encode())

    def run_alert(self):
        self.event_path.write_bytes(json.dumps(self.event).encode())
        environment = {"GITHUB_EVENT_PATH": str(self.event_path), "GITHUB_REPOSITORY": "owner/radar",
                       "GITHUB_TOKEN": "test-sentinel", "RADAR_PUBLISH_STATUS": str(self.status_path)}
        output = io.StringIO()
        with patch.dict(os.environ, environment), patch("radar.failure_alert.urlopen", side_effect=self.http), \
                patch("sys.stdout", output), patch("sys.stderr", output):
            result = main()
        self.assertNotIn("test-sentinel", output.getvalue())
        return result, output.getvalue()

    def test_update_failure_creates_owner_alert_with_reason_logs_and_artifact(self):
        self.status_path.write_bytes(json.dumps({"published": False, "reason": "source quorum failed: 12/42"}).encode())
        self.assertEqual(self.run_alert()[0], 0)
        method, url, payload = self.writes[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/issues"))
        for text in ("source quorum failed: 12/42", "data/publish-status.json", "radar-publish-status-42-2",
                     "https://github.com/owner/radar/actions/runs/42/attempts/2", "Fetch public sources", "@owner"):
            self.assertIn(text, payload["body"])

    def test_repeat_failures_update_one_issue_and_identical_replay_has_no_write(self):
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.run_alert()[1], "Failure alert unchanged.\n")
        self.assertEqual(len(self.writes), 1)
        self.event["workflow_run"]["id"] = 43
        self.assertEqual(self.run_alert()[1], "Failure alert updated.\n")
        self.assertEqual([item[0] for item in self.writes], ["POST", "PATCH"])
        self.assertEqual(len(self.issues), 1)

    def test_deploy_failure_and_cancellation_are_reported_without_diagnostics(self):
        for conclusion in ("failure", "cancelled", "timed_out"):
            with self.subTest(conclusion=conclusion):
                self.event["workflow_run"]["conclusion"] = conclusion
                self.jobs = [{"name": "deploy", "conclusion": conclusion, "steps": []}]
                self.assertEqual(self.run_alert()[0], 0)
                self.assertIn(f"deploy: {conclusion}", self.writes[-1][2]["body"])
                self.assertIn("Publish diagnostics unavailable", self.writes[-1][2]["body"])

    def test_success_skips_every_network_request(self):
        self.event["workflow_run"]["conclusion"] = "success"
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.requests, [])

    def test_foreign_repository_and_unrelated_workflow_are_rejected(self):
        original = copy.deepcopy(self.event)
        for changes in ({"head_repository": {"full_name": "attacker/radar"}}, {"name": "Offline CI"}):
            self.event = copy.deepcopy(original)
            self.event["workflow_run"].update(changes)
            self.assertEqual(self.run_alert()[0], 1)
        self.assertEqual(self.requests, [])

    def test_permission_or_network_errors_fail_loudly_without_creating_duplicates(self):
        for error in (HTTPError("https://api.github.com", 403, "test-sentinel", {}, None),
                      URLError("test-sentinel")):
            self.failure = error
            code, output = self.run_alert()
            self.assertEqual(code, 1)
            self.assertIn("Failure alert failed", output)
            self.assertEqual(self.writes, [])

    def test_job_lookup_failure_still_posts_run_link(self):
        original = self.http

        def failing_jobs(request, timeout):
            if "/jobs?" in request.full_url:
                raise HTTPError(request.full_url, 503, "unavailable", {}, None)
            return original(request, timeout)

        self.http = failing_jobs
        self.assertEqual(self.run_alert()[0], 0)
        self.assertIn("Job details unavailable", self.writes[0][2]["body"])

    def test_post_failure_returns_nonzero_and_does_not_retry_ambiguous_write(self):
        original = self.http

        def failing_post(request, timeout):
            if request.method == "POST":
                self.writes.append(("POST", request.full_url, None))
                raise URLError("test-sentinel")
            return original(request, timeout)

        self.http = failing_post
        self.assertEqual(self.run_alert()[0], 1)
        self.assertEqual(len(self.writes), 1)

    def test_missing_token_is_a_safe_error(self):
        with self.assertRaisesRegex(AlertError, "Missing GITHUB_TOKEN"):
            GitHub("owner/radar", "")

    def test_diagnostic_is_bounded_and_invalid_json_does_not_hide_alert(self):
        for raw in (b"invalid", b"[]", b"x" * 65537):
            self.status_path.write_bytes(raw)
            self.assertIn("unavailable", publish_reason(self.status_path))
        self.status_path.write_bytes(b'{"published":true}')
        self.assertIn("passed the publish gate", publish_reason(self.status_path))

    def test_pagination_finds_later_issues_and_rejects_invalid_api_data(self):
        api = GitHub("owner/radar", "test-sentinel")
        with patch.object(api, "request", side_effect=[[{}] * 100, [{"number": 17}]]) as request:
            self.assertEqual(list(api.pages("/issues?state=open"))[-1], {"number": 17})
            self.assertIn("&per_page=100&page=2", request.call_args.args[1])
        with patch.object(api, "request", return_value={"error": "broken"}):
            with self.assertRaises(AlertError):
                list(api.pages("/issues"))


if __name__ == "__main__":
    unittest.main()

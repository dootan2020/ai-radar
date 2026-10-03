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
            "workflow_run": {"id": 42, "run_number": 10, "run_attempt": 2, "name": "Update AI Radar",
                             "created_at": "2026-10-03T09:00:00Z",
                             "head_branch": "main", "head_sha": "a" * 40,
                             "head_repository": {"full_name": "owner/radar"}, "conclusion": "failure"},
        }
        self.issues, self.writes, self.requests = [], [], []
        self.jobs = [{"name": "update", "conclusion": "failure", "steps": [
            {"name": "Fetch public sources", "conclusion": "failure"}]}]
        self.failure = None
        self.runs = []

    def http(self, request, timeout):
        self.assertEqual(timeout, 15)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-sentinel")
        self.assertTrue(request.full_url.startswith("https://api.github.com/repos/owner/radar/"))
        self.requests.append((request.method, request.full_url))
        if self.failure:
            raise self.failure
        if request.method == "GET":
            if "/jobs?" in request.full_url:
                response = {"jobs": self.jobs}
            elif "/workflows/update.yml/runs?" in request.full_url:
                response = {"workflow_runs": self.runs}
            elif "/actions/runs/" in request.full_url:
                response = next(run for run in self.runs if str(run["id"]) == request.full_url.rsplit("/", 1)[1])
            else:
                response = self.issues
        else:
            payload = json.loads(request.data)
            self.writes.append((request.method, request.full_url, payload))
            if request.method == "POST":
                self.issues.append({**payload, "number": 17 + len(self.issues), "state": "open",
                                    "user": {"login": "github-actions[bot]"}})
            else:
                number = int(request.full_url.rsplit("/", 1)[1])
                next(issue for issue in self.issues if issue["number"] == number).update(payload)
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
        self.event["workflow_run"]["run_number"] = 11
        self.assertEqual(self.run_alert()[1], "Failure alert updated.\n")
        self.assertEqual([item[0] for item in self.writes], ["POST", "PATCH"])
        self.assertEqual(len(self.issues), 1)

    def test_actionable_deploy_failures_are_reported_without_diagnostics(self):
        for conclusion in ("failure", "timed_out", "action_required", "startup_failure"):
            with self.subTest(conclusion=conclusion):
                self.event["workflow_run"]["conclusion"] = conclusion
                self.jobs = [{"name": "deploy", "conclusion": conclusion, "steps": []}]
                self.assertEqual(self.run_alert()[0], 0)
                self.assertIn(f"deploy: {conclusion}", self.writes[-1][2]["body"])
                self.assertIn("Publish diagnostics unavailable", self.writes[-1][2]["body"])

    def test_nonactionable_conclusions_skip_every_network_request(self):
        for conclusion in ("cancelled", "stale", "neutral", "skipped", None):
            self.event["workflow_run"]["conclusion"] = conclusion
            self.assertEqual(self.run_alert()[0], 0)
            self.assertEqual(self.requests, [])

    def test_later_success_closes_issue_and_replay_is_idempotent(self):
        self.assertEqual(self.run_alert()[0], 0)
        self.event["workflow_run"].update(id=43, run_number=11, run_attempt=1, conclusion="success")
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.issues[0]["state"], "closed")
        self.assertIn("/actions/runs/43/attempts/1", self.issues[0]["body"])
        self.assertEqual(self.writes[-1][2]["state_reason"], "completed")
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(len(self.writes), 2)

    def test_success_without_failure_does_not_create_an_issue(self):
        self.event["workflow_run"]["conclusion"] = "success"
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.writes, [])

    def test_older_success_and_failure_cannot_overwrite_newer_failure(self):
        self.assertEqual(self.run_alert()[0], 0)
        original = self.issues[0]["body"]
        for conclusion in ("success", "failure"):
            self.event["workflow_run"].update(id=41, run_number=9, run_attempt=9, conclusion=conclusion)
            self.assertEqual(self.run_alert()[0], 0)
            self.assertEqual(self.issues[0]["body"], original)
            self.assertEqual(self.issues[0]["state"], "open")
        self.assertEqual(len(self.writes), 1)

    def test_delayed_failure_cannot_recreate_issue_after_recovery(self):
        failure = copy.deepcopy(self.event)
        self.assertEqual(self.run_alert()[0], 0)
        self.event["workflow_run"].update(id=43, run_number=11, run_attempt=1, conclusion="success")
        self.assertEqual(self.run_alert()[0], 0)
        self.event = failure
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(len(self.issues), 1)
        self.assertEqual(len(self.writes), 2)
        self.assertEqual(self.issues[0]["state"], "closed")

    def test_next_failure_after_recovery_creates_one_new_issue(self):
        self.run_alert()
        self.event["workflow_run"].update(id=43, run_number=11, run_attempt=1, conclusion="success")
        self.run_alert()
        self.event["workflow_run"].update(id=44, run_number=12, conclusion="failure")
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual([issue["state"] for issue in self.issues], ["closed", "open"])
        self.assertEqual(len(self.writes), 3)

    def test_same_run_later_attempt_recovers_but_old_attempt_cannot_reopen(self):
        failure = copy.deepcopy(self.event)
        self.run_alert()
        self.event["workflow_run"].update(run_attempt=3, conclusion="success")
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.issues[0]["state"], "closed")
        self.event = failure
        self.run_alert()
        self.assertEqual(len(self.writes), 2)

    def test_newer_completed_run_suppresses_stale_events_without_existing_issue(self):
        for conclusion in ("success", "failure"):
            self.runs = [{**self.event["workflow_run"], "id": 43, "run_number": 11,
                          "conclusion": conclusion}]
            self.assertEqual(self.run_alert()[0], 0)
            self.assertEqual(self.writes, [])

    def test_cancelled_newer_run_does_not_hide_unresolved_failure(self):
        self.runs = [{**self.event["workflow_run"], "id": 43, "run_number": 11, "conclusion": "cancelled"}]
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(len(self.writes), 1)

    def test_recovery_is_isolated_to_branch_bot_issues_and_not_pull_requests(self):
        self.run_alert()
        main_issue = copy.deepcopy(self.issues[0])
        self.event["workflow_run"].update(head_branch="feature/test", id=43, run_number=11)
        self.run_alert()
        feature_issue = copy.deepcopy(self.issues[1])
        self.issues.extend([{**main_issue, "number": 19, "user": {"login": "human"}},
                            {**main_issue, "number": 20, "pull_request": {}}])
        self.event["workflow_run"].update(head_branch="main", id=44, run_number=12, conclusion="success")
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.issues[0]["state"], "closed")
        self.assertEqual(self.issues[1], feature_issue)
        self.assertTrue(all(issue["state"] == "open" for issue in self.issues[2:]))

    def test_foreign_or_other_branch_completed_runs_cannot_suppress_alert(self):
        for changes in ({"head_branch": "feature"}, {"name": "Offline CI"},
                        {"head_repository": {"full_name": "other/radar"}}):
            self.runs.append({**self.event["workflow_run"], "id": 99, "run_number": 99, **changes})
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(len(self.writes), 1)

    def test_legacy_issue_can_recover_using_verified_run_metadata(self):
        self.run_alert()
        self.runs = [copy.deepcopy(self.event["workflow_run"])]
        self.issues[0]["body"] = "\n\n".join(part for part in self.issues[0]["body"].split("\n\n")
                                               if not part.startswith("<!-- radar-update-run:"))
        self.event["workflow_run"].update(id=43, run_number=11, run_attempt=1, conclusion="success")
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.issues[0]["state"], "closed")
        self.assertTrue(any(url.endswith("/actions/runs/42") for _, url in self.requests))

    def test_missing_issue_order_fails_closed_without_writes(self):
        self.run_alert()
        self.issues[0]["body"] = self.issues[0]["body"].split("\n", 1)[0]
        self.event["workflow_run"].update(id=43, run_number=11, conclusion="success")
        self.assertEqual(self.run_alert()[0], 1)
        self.assertEqual(len(self.writes), 1)

    def test_retry_completes_partial_recovery_of_duplicate_bot_issues(self):
        self.run_alert()
        self.issues.append({**copy.deepcopy(self.issues[0]), "number": 18})
        self.event["workflow_run"].update(id=43, run_number=11, conclusion="success")
        original = self.http

        def reject_second_close(request, timeout):
            if request.method == "PATCH" and request.full_url.endswith("/issues/18"):
                raise HTTPError(request.full_url, 503, "unavailable", {}, None)
            return original(request, timeout)

        self.http = reject_second_close
        self.assertEqual(self.run_alert()[0], 1)
        self.assertEqual([issue["state"] for issue in self.issues], ["closed", "open"])
        self.http = original
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual([issue["state"] for issue in self.issues], ["closed", "closed"])

    def test_history_request_is_branch_encoded_and_bounded_by_run_creation(self):
        self.event["workflow_run"]["head_branch"] = "feature/a&b"
        self.assertEqual(self.run_alert()[0], 0)
        url = next(url for _, url in self.requests if "/workflows/" in url)
        self.assertIn("branch=feature%2Fa%26b", url)
        self.assertIn("created=%3E%3D2026-10-03T09%3A00%3A00Z", url)

    def test_newer_failure_prevents_older_success_closing_open_issue(self):
        self.run_alert()
        self.event["workflow_run"].update(id=43, run_number=11, conclusion="success")
        self.runs = [{**self.event["workflow_run"], "id": 44, "run_number": 12, "conclusion": "failure"}]
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.issues[0]["state"], "open")
        self.assertEqual(len(self.writes), 1)

    def test_invalid_order_metadata_cannot_mutate_issues(self):
        original = copy.deepcopy(self.event)
        for changes in ({"run_number": None}, {"run_attempt": 0}, {"id": True}, {"created_at": "invalid"}):
            self.event = copy.deepcopy(original)
            self.event["workflow_run"].update(changes)
            self.assertEqual(self.run_alert()[0], 1)
            self.assertEqual(self.writes, [])

    def test_non_completed_event_is_ignored(self):
        self.event["action"] = "requested"
        self.assertEqual(self.run_alert()[0], 0)
        self.assertEqual(self.requests, [])

    def test_foreign_repository_and_unrelated_workflow_are_rejected(self):
        original = copy.deepcopy(self.event)
        for conclusion in ("failure", "success"):
            for changes in ({"head_repository": {"full_name": "attacker/radar"}}, {"name": "Offline CI"}):
                self.event = copy.deepcopy(original)
                self.event["workflow_run"].update(conclusion=conclusion, **changes)
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
        with patch.object(api, "request", return_value=[{}] * 100) as request:
            with self.assertRaisesRegex(AlertError, "pagination limit"):
                list(api.pages("/issues"))
            self.assertEqual(request.call_count, 10)


if __name__ == "__main__":
    unittest.main()

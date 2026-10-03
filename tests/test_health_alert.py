"""Health incident lifecycle exercised through the real GitHub client boundary."""

import copy
import io
import json
import unittest
from unittest.mock import patch

from radar import health_alert
from radar.failure_alert import AlertError, GitHub


class HealthAlertTests(unittest.TestCase):
    def setUp(self):
        self.issues, self.writes, self.requests = [], [], []
        self.api = GitHub("owner/radar", "private-sentinel")
        self.report = {"status": "failed", "checked_at": "2026-10-03T12:00:00Z",
                       "generated_at": "2026-10-03T08:00:00Z", "checks": [],
                       "confirmed_failures": [{"id": "snapshot", "ok": False,
                           "url": "https://dootan2020.github.io/ai-radar/data/radar.json",
                           "detail": "Snapshot stale: age 14400 seconds"}]}
        self.report["checks"] = copy.deepcopy(self.report["confirmed_failures"])

    def http(self, request, timeout):
        self.assertEqual(timeout, 15)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-sentinel")
        self.assertTrue(request.full_url.startswith("https://api.github.com/repos/owner/radar/"))
        self.requests.append((request.method, request.full_url))
        if request.method == "GET":
            self.assertIn("/issues?", request.full_url)
            response = self.issues
        else:
            payload = json.loads(request.data)
            self.assertNotIn("private-sentinel", request.data.decode())
            self.writes.append((request.method, request.full_url, payload))
            if request.method == "POST":
                self.assertTrue(request.full_url.endswith("/issues"))
                self.issues.append({**payload, "number": 17 + len(self.issues), "state": "open",
                                    "user": {"login": "github-actions[bot]"}})
            else:
                self.assertEqual(request.method, "PATCH")
                number = int(request.full_url.rsplit("/", 1)[1])
                next(issue for issue in self.issues if issue["number"] == number).update(payload)
            response = {"number": 17}
        return io.BytesIO(json.dumps(response).encode())

    def reconcile(self):
        with patch("radar.failure_alert.urlopen", side_effect=self.http):
            return health_alert.reconcile_report(self.report, self.api, "owner/radar", 42, 1, "owner")

    def recovery(self, time="2026-10-03T12:30:00Z"):
        self.report.update(status="healthy", checked_at=time, confirmed_failures=[],
                           checks=[{"id": "snapshot", "url": "https://dootan2020.github.io/ai-radar/data/radar.json",
                                    "ok": True, "detail": "OK"}])

    def test_confirmed_failure_creates_actionable_distinct_bot_issue(self):
        self.reconcile()
        self.assertEqual(len(self.writes), 1)
        body = self.issues[0]["body"]
        self.assertIn(health_alert.HEALTH_MARKER, body)
        self.assertNotIn("<!-- radar-update-failure:", body)
        for evidence in ("snapshot", "14400", "https://dootan2020.github.io/ai-radar/",
                         "https://github.com/owner/radar/actions/runs/42/attempts/1", "@owner"):
            self.assertIn(evidence, body)

    def test_replay_is_idempotent_and_later_failure_updates_one_open_issue(self):
        self.reconcile()
        self.reconcile()
        self.assertEqual(len(self.writes), 1)
        self.report["checked_at"] = "2026-10-03T12:30:00Z"
        self.reconcile()
        self.assertEqual(len(self.issues), 1)
        self.assertEqual([row[0] for row in self.writes], ["POST", "PATCH"])

    def test_healthy_recovery_closes_and_replay_or_old_failure_cannot_reopen(self):
        original = copy.deepcopy(self.report)
        self.reconcile()
        self.recovery()
        self.reconcile()
        self.assertEqual(self.issues[0]["state"], "closed")
        self.assertEqual(self.writes[-1][2]["state_reason"], "completed")
        self.reconcile()
        self.report = original
        self.reconcile()
        self.assertEqual(len(self.writes), 2)
        self.assertEqual(len(self.issues), 1)

    def test_recovery_without_incident_and_inconclusive_observation_have_no_writes(self):
        self.recovery()
        self.reconcile()
        self.assertEqual(self.writes, [])
        self.report.update(status="inconclusive", confirmed_failures=[])
        self.reconcile()
        self.assertEqual(self.writes, [])

    def test_inconclusive_or_older_healthy_report_cannot_close_existing_incident(self):
        self.reconcile()
        self.report.update(status="inconclusive", checked_at="2026-10-03T12:30:00Z", confirmed_failures=[])
        self.reconcile()
        self.recovery("2026-10-03T11:30:00Z")
        self.reconcile()
        self.assertEqual(self.issues[0]["state"], "open")
        self.assertEqual(len(self.writes), 1)

    def test_recovery_ignores_update_incidents_human_issues_and_pull_requests(self):
        self.reconcile()
        incident = copy.deepcopy(self.issues[0])
        unrelated = [{**incident, "number": 18, "body": "<!-- radar-update-failure:main -->"},
                     {**incident, "number": 19, "user": {"login": "human"}},
                     {**incident, "number": 20, "pull_request": {}}]
        self.issues.extend(copy.deepcopy(unrelated))
        self.recovery()
        self.reconcile()
        self.assertEqual(self.issues[0]["state"], "closed")
        self.assertEqual(self.issues[1:], unrelated)

    def test_next_confirmed_failure_after_recovery_creates_new_incident(self):
        original = copy.deepcopy(self.report)
        self.reconcile()
        self.recovery()
        self.reconcile()
        self.report = {**original, "checked_at": "2026-10-03T13:00:00Z"}
        self.reconcile()
        self.assertEqual([issue["state"] for issue in self.issues], ["closed", "open"])

    def test_recovery_closes_all_matching_duplicates_and_no_others(self):
        self.reconcile()
        self.issues.append({**copy.deepcopy(self.issues[0]), "number": 18})
        self.recovery()
        self.reconcile()
        self.assertEqual([issue["state"] for issue in self.issues], ["closed", "closed"])

    def test_invalid_existing_observation_metadata_refuses_unsafe_mutation(self):
        self.reconcile()
        self.issues[0]["body"] = health_alert.HEALTH_MARKER
        self.recovery()
        with self.assertRaises(AlertError):
            self.reconcile()
        self.assertEqual(len(self.writes), 1)


if __name__ == "__main__":
    unittest.main()

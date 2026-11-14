"""The quiet-feed alert: how long hco.news has shown no new story, and whether that looks broken or just quiet."""

from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from radar import freshness_watch, health_alert
from radar.failure_alert import GitHub

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(**delta):
    return NOW - timedelta(**delta)


def site(stories=None, generated=None, sources=None, interval=1800):
    return {"generated_at": iso(generated or ago(minutes=10)),
            "freshness": {"expected_interval_seconds": interval},
            "stories": stories if stories is not None else [
                {"id": "old-1", "aliases": [], "title": "Old story"},
                {"id": "last-1", "aliases": [], "title": "Last new story"}],
            "sources": sources if sources is not None else (
                [{"id": f"s{n}", "ok": True} for n in range(9)] + [{"id": "s9", "ok": False},
                                                                     {"id": "off", "ok": False, "disabled": True}])}


def intake(*hours_ago):
    return {"generated_at": iso(ago(minutes=10)),
            "stories": [{"id": f"c{n}", "published_at": iso(ago(hours=h))} for n, h in enumerate(hours_ago)]}


def history(last_new_hours=6, newsroom_hours=(0.5, 2.5, 4.5, 6.5), head=None):
    return {"additions": {"old-1": ago(hours=30), "last-1": ago(hours=last_new_hours)},
            "archived": {"old-1", "last-1", "gone-1"},
            "history_start": ago(days=5), "head_at": head or ago(minutes=8),
            "newsroom": [ago(hours=h) for h in newsroom_hours], "newsroom_complete": False}


class AssessTests(unittest.TestCase):
    def assess(self, ui=None, feed=None, past=None):
        return freshness_watch.assess(NOW, site() if ui is None else ui,
                                      intake(1, 3) if feed is None else feed,
                                      history() if past is None else past)

    def test_quiet_past_threshold_with_healthy_pipeline_is_quiet_news(self):
        report = self.assess()
        self.assertEqual(report["status"], "quiet")
        self.assertEqual(report["quiet_seconds"], 6 * 3600)
        self.assertFalse(report["quiet_at_least"])
        self.assertEqual(report["last_new_story"]["id"], "last-1")
        self.assertEqual(report["diagnosis"], "quiet-news")
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["signals"]["intake"]["stories_in_window"], 2)
        self.assertEqual(report["signals"]["newsroom"]["dispatches_since_last_story"], 3)
        self.assertEqual(report["signals"]["sources"]["failing"], 1)
        self.assertEqual(report["signals"]["sources"]["enabled"], 10)

    def test_new_story_inside_threshold_is_fresh(self):
        report = self.assess(past=history(last_new_hours=1))
        self.assertEqual(report["status"], "fresh")
        self.assertEqual(report["quiet_seconds"], 3600)

    def test_threshold_is_the_measured_five_hours(self):
        self.assertEqual(freshness_watch.QUIET_AFTER_SECONDS, 5 * 3600)
        self.assertEqual(self.assess(past=history(last_new_hours=4.9))["status"], "fresh")
        self.assertEqual(self.assess(past=history(last_new_hours=5))["status"], "quiet")

    def test_stale_build_is_a_pipeline_problem(self):
        report = self.assess(ui=site(generated=ago(hours=2)), past=history(head=ago(hours=2)))
        self.assertEqual(report["status"], "quiet")
        self.assertEqual(report["diagnosis"], "pipeline")
        self.assertTrue(report["signals"]["build"]["late"])
        self.assertTrue(any("build" in problem for problem in report["problems"]))

    def test_stale_newsroom_is_a_pipeline_problem(self):
        report = self.assess(past=history(newsroom_hours=(7, 9)))
        self.assertEqual(report["diagnosis"], "pipeline")
        self.assertTrue(report["signals"]["newsroom"]["late"])
        self.assertEqual(report["signals"]["newsroom"]["dispatches_since_last_story"], 0)
        self.assertTrue(any("newsroom" in problem.lower() for problem in report["problems"]))

    def test_many_failing_sources_is_a_pipeline_problem(self):
        sources = [{"id": f"s{n}", "ok": n < 5} for n in range(10)]
        report = self.assess(ui=site(sources=sources))
        self.assertEqual(report["diagnosis"], "pipeline")
        self.assertEqual(report["signals"]["sources"]["failing"], 5)

    def test_missing_history_is_unknown_not_fresh(self):
        report = freshness_watch.assess(NOW, site(), intake(1), None)
        self.assertEqual(report["status"], "unknown")
        self.assertIsNone(report["quiet_seconds"])
        self.assertTrue(report["unknowns"])

    def test_missing_site_snapshot_or_its_time_is_unknown(self):
        for ui in (None, {"stories": []}, {**site(), "generated_at": "yesterday"}, {**site(), "stories": "x"}):
            with self.subTest(ui=ui):
                report = freshness_watch.assess(NOW, ui, intake(1), history())
                self.assertEqual(report["status"], "unknown")
                self.assertIsNone(report["quiet_seconds"])

    def test_story_history_behind_the_live_build_is_unknown(self):
        report = self.assess(past=history(head=ago(hours=3)))
        self.assertEqual(report["status"], "unknown")
        self.assertIsNone(report["quiet_seconds"])

    def test_missing_diagnosis_inputs_are_unknown_never_quiet_news(self):
        cases = {"intake": (site(), None, history()),
                 "intake-shape": (site(), {"stories": "x"}, history()),
                 "newsroom": (site(), intake(1), {**history(), "newsroom": []}),
                 "interval": (site(interval=None), intake(1), history()),
                 "sources": (site(sources=[{"id": "off", "ok": False, "disabled": True}]), intake(1), history())}
        for name, (ui, feed, past) in cases.items():
            with self.subTest(name):
                report = freshness_watch.assess(NOW, ui, feed, past)
                self.assertEqual(report["status"], "quiet")
                self.assertEqual(report["diagnosis"], "unknown")
                self.assertTrue(report["unknowns"])

    def test_renamed_story_keeps_its_first_appearance(self):
        stories = [{"id": "old-1", "aliases": [], "title": "Old"},
                   {"id": "renamed", "aliases": ["last-1"], "title": "Same story, new id"}]
        past = history()
        past["additions"]["renamed"] = ago(minutes=30)
        past["archived"].add("renamed")
        report = self.assess(ui=site(stories=stories), past=past)
        self.assertEqual(report["quiet_seconds"], 6 * 3600)
        # An alias archived before the fetched history began makes the story older than the history.
        stories[1]["aliases"] = ["gone-1"]
        report = self.assess(ui=site(stories=stories), past=past)
        self.assertEqual(report["last_new_story"]["id"], "old-1")

    def test_story_live_but_not_yet_archived_counts_from_the_build(self):
        stories = site()["stories"] + [{"id": "brand-new", "aliases": [], "title": "Just built"}]
        report = self.assess(ui=site(stories=stories))
        self.assertEqual(report["status"], "fresh")
        self.assertEqual(report["last_new_story"]["id"], "brand-new")
        self.assertEqual(report["quiet_seconds"], 600)

    def test_no_new_story_in_the_whole_history_is_a_lower_bound(self):
        past = history()
        past["additions"] = {}
        report = self.assess(past=past)
        self.assertEqual(report["status"], "quiet")
        self.assertTrue(report["quiet_at_least"])
        self.assertEqual(report["quiet_seconds"], 5 * 86400)
        self.assertIsNone(report["last_new_story"])


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.issues, self.writes = [], []
        self.api = GitHub("owner/radar", "private-sentinel")

    def http(self, request, timeout):
        self.assertEqual(request.get_header("Authorization"), "Bearer private-sentinel")
        if request.method == "GET":
            response = self.issues
        else:
            payload = json.loads(request.data)
            self.writes.append((request.method, request.full_url, payload))
            if request.method == "POST":
                self.issues.append({**payload, "number": 30 + len(self.issues), "state": "open",
                                    "user": {"login": "github-actions[bot]"}})
            else:
                number = int(request.full_url.rsplit("/", 1)[1])
                next(issue for issue in self.issues if issue["number"] == number).update(payload)
            response = {"number": 30}
        return io.BytesIO(json.dumps(response).encode())

    def reconcile(self, report):
        with patch("radar.failure_alert.urlopen", side_effect=self.http):
            return health_alert.reconcile_quiet(report, self.api, "owner/radar", 42, 1, "owner")

    def report(self, hours, at=NOW, **overrides):
        past = history(last_new_hours=hours)
        report = freshness_watch.assess(at, site(), intake(1, 3), past)
        report.update(overrides)
        return report

    def test_quiet_opens_one_issue_with_duration_diagnosis_and_owner(self):
        self.assertEqual(self.reconcile(self.report(6)), "created")
        method, url, payload = self.writes[0]
        self.assertEqual((method, url.rsplit("/", 1)[1]), ("POST", "issues"))
        self.assertEqual(payload["title"], "Halcyon: 6 giờ chưa có tin mới (có vẻ do ít tin)")
        self.assertIn(health_alert.QUIET_MARKER, payload["body"])
        self.assertIn('<!-- radar-quiet-observation:{"checked_at": "2026-11-14T12:00:00Z"} -->', payload["body"])
        self.assertNotIn(health_alert.HEALTH_MARKER, payload["body"])
        self.assertIn("đã **6 giờ** chưa có tin mới", payload["body"])
        self.assertIn("Tin mới gần nhất: Last new story (id last-1), lên trang ở lần build lúc 13:00 ngày 14/11",
                      payload["body"])
        self.assertIn("Chẩn đoán: **có vẻ do ít tin**", payload["body"])
        self.assertIn("Owner: @owner", payload["body"])
        self.assertIn("Lần chạy newsroom gần nhất: 18:30 ngày 14/11, 30 phút trước", payload["body"])
        self.assertIn("Build gần nhất của trang: 18:50 ngày 14/11, 10 phút trước", payload["body"])
        self.assertIn("1 trên 10 nguồn đang bật bị lỗi (s9)", payload["body"])
        self.assertIn("2 tin intake", payload["body"])
        later = self.report(6.5, at=NOW + timedelta(minutes=30))
        self.assertEqual(self.reconcile(later), "updated")
        self.assertEqual(len(self.issues), 1)

    def test_vietnamese_duration_labels_and_lower_bound(self):
        self.assertEqual([health_alert.duration_vi(value) for value in (2700, 10800, 18720)],
                         ["45 phút", "3 giờ", "5 giờ 12 phút"])
        pipeline = freshness_watch.assess(NOW, site(), intake(1), history(newsroom_hours=(7, 9)))
        self.assertEqual(self.reconcile(pipeline), "created")
        payload = self.writes[-1][2]
        self.assertEqual(payload["title"], "Halcyon: 6 giờ chưa có tin mới (có vẻ pipeline lỗi)")
        self.assertIn("- Lỗi: Newsroom chạy lần gần nhất cách đây 7 giờ", payload["body"])
        past = history()
        past["additions"] = {}
        unknown = freshness_watch.assess(NOW + timedelta(minutes=15), site(), None, past)
        self.reconcile(unknown)
        payload = self.writes[-1][2]
        self.assertEqual(payload["title"], "Halcyon: 120 giờ 15 phút trở lên chưa có tin mới (chưa chẩn đoán được)")
        self.assertIn("- Chưa đo được: Không đọc được bản intake", payload["body"])

    def test_new_story_closes_the_issue_and_old_quiet_report_cannot_reopen(self):
        quiet = self.report(6)
        self.reconcile(quiet)
        fresh = self.report(0.2, at=NOW + timedelta(minutes=15))
        self.assertEqual(self.reconcile(fresh), "resolved")
        self.assertEqual(self.issues[0]["state"], "closed")
        self.assertIn("Đã có tin mới lên trang: Last new story", self.issues[0]["body"])
        self.assertEqual(self.reconcile(quiet), "superseded")
        self.assertEqual(self.reconcile(self.report(0.3, at=NOW + timedelta(minutes=30))), "unchanged")

    def test_unknown_never_opens_or_closes(self):
        self.reconcile(self.report(6))
        unknown = freshness_watch.assess(NOW + timedelta(minutes=15), site(), intake(1), None)
        self.assertEqual(self.reconcile(unknown), "unchanged")
        self.assertEqual(self.issues[0]["state"], "open")
        self.assertEqual(len(self.writes), 1)

    def test_quiet_issue_is_separate_from_the_live_health_incident(self):
        self.issues.append({"number": 5, "state": "open", "user": {"login": "github-actions[bot]"},
                            "title": "AI Radar live health check failed",
                            "body": health_alert.HEALTH_MARKER + "\n\n<!-- radar-health-observation:"
                                    + json.dumps({"checked_at": iso(NOW)}) + " -->"})
        self.assertEqual(self.reconcile(self.report(6)), "created")
        self.assertEqual(self.reconcile(self.report(0.2, at=NOW + timedelta(minutes=15))), "resolved")
        self.assertEqual(self.issues[0]["state"], "open")


class HistoryTests(unittest.TestCase):
    """The story archive read through real git: the shallow boundary commit is not a wave of new stories."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        self.root = Path(tempfile.mkdtemp(prefix="quiet-feed-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.source = self.root / "source"
        self.git(None, "init", "-q", "-b", "main", str(self.source))
        self.git(self.source, "config", "uploadpack.allowFilter", "true")
        self.git(self.source, "config", "user.email", "bot@example.invalid")
        self.git(self.source, "config", "user.name", "bot")
        stories = self.source / "stories"
        stories.mkdir()
        for number, (story_id, stamp) in enumerate([("first", "2026-11-14T01:00:00Z"),
                                                     ("second", "2026-11-14T03:00:00Z"),
                                                     ("third", "2026-11-14T05:00:00Z")]):
            (stories / f"{story_id}.json").write_text("{}", encoding="utf-8")
            (self.source / "index.json").write_text(str(number), encoding="utf-8")
            self.git(self.source, "add", "-A")
            self.git(self.source, "commit", "-q", "-m", story_id, env={"GIT_COMMITTER_DATE": stamp,
                                                                     "GIT_AUTHOR_DATE": stamp})
        self.git(self.source, "branch", "-q", freshness_watch.STORY_BRANCH)
        self.git(self.source, "commit", "-q", "--allow-empty", "-m", "decisions",
                 env={"GIT_COMMITTER_DATE": "2026-11-14T06:00:00Z", "GIT_AUTHOR_DATE": "2026-11-14T06:00:00Z"})
        self.git(self.source, "branch", "-q", freshness_watch.DECISIONS_BRANCH)

    def git(self, repo, *args, env=None):
        command = ["git"] + (["-C", str(repo)] if repo else []) + list(args)
        subprocess.run(command, check=True, capture_output=True, env={**os.environ, **(env or {})})

    def test_shallow_history_excludes_the_boundary_and_reads_newsroom_dispatches(self):
        with patch.object(freshness_watch, "HISTORY_DEPTH", 2):
            past = freshness_watch.read_history(self.source.as_uri())
        self.assertEqual(past["additions"], {"third": datetime(2026, 11, 14, 5, tzinfo=timezone.utc)})
        self.assertEqual(past["archived"], {"first", "second", "third"})
        self.assertEqual(past["history_start"], datetime(2026, 11, 14, 3, tzinfo=timezone.utc))
        self.assertEqual(past["head_at"], datetime(2026, 11, 14, 5, tzinfo=timezone.utc))
        self.assertEqual(past["newsroom"][0], datetime(2026, 11, 14, 6, tzinfo=timezone.utc))

    def test_unreachable_remote_raises_instead_of_reporting_history(self):
        with self.assertRaises(freshness_watch.WatchError):
            freshness_watch.read_history((self.root / "missing").as_uri())


class CommandTests(unittest.TestCase):
    def run_main(self, argv, report):
        output = io.StringIO()
        env = {"GITHUB_REPOSITORY": "owner/radar", "GITHUB_TOKEN": "private-sentinel", "GITHUB_RUN_ID": "42",
               "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY_OWNER": "owner"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(freshness_watch, "collect_report", return_value=report), \
                patch("radar.failure_alert.urlopen", side_effect=AssertionError("Unexpected API call")), \
                patch("sys.stdout", output), patch("sys.stderr", output):
            code = freshness_watch.main(argv)
        self.assertNotIn("private-sentinel", output.getvalue())
        return code, output.getvalue()

    def test_read_only_run_prints_quiet_time_and_diagnosis_without_github(self):
        code, output = self.run_main([], freshness_watch.assess(NOW, site(), intake(1), history()))
        self.assertEqual(code, 0)
        self.assertIn("quiet for 6h 00m", output)
        self.assertIn("quiet-news", output)

    def test_unknown_fails_the_check_and_never_calls_github(self):
        unknown = freshness_watch.assess(NOW, site(), intake(1), None)
        self.assertEqual(self.run_main(["--report"], unknown)[0], 1)
        self.assertEqual(self.run_main([], unknown)[0], 1)


if __name__ == "__main__":
    unittest.main()

"""Offline coverage for the capped newsroom Gemini checker fallback."""

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from phong_bao.cycle import _lanes_available, cycle
from phong_bao.gemini_api import NewsroomRunner
from phong_bao.newsroom import FixtureArticles, _agent_desk
from phong_bao.registry import load_registry, providers
from phong_bao.runner import FixtureRunner
from radar import gemini_paid_budget


FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class GeminiNewsroomTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = {**fixture("discovery.json"), "fuel": "codex : còn\ngemini : CẠN"}
        self.profile = next(tool for tool in self.tools if tool["id"] == "gemini-api")

    def test_paid_checker_requires_key_and_prepared_budget(self):
        self.discovery["key_names"] = []
        self.assertFalse(_lanes_available(self.tools, self.discovery))
        self.assertEqual(providers("kiem-chung", self.tools, self.discovery, boat_exclude={"codex"}), [])
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"RADAR_GEMINI_PAID_REMOTE": "https://example.invalid/repo.git"}, clear=False):
                runner = NewsroomRunner(Path(directory) / "ledger.json")
            with patch("phong_bao.gemini_api.gemini_paid_budget.prepare") as prepare:
                self.assertFalse(runner.start(self.discovery, self.tools))
                prepare.assert_not_called()
                self.discovery["key_names"] = ["GEMINI_API_KEY"]
                with patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
                    for code in ("paid_monthly_cap", "paid_budget_ledger_unavailable"):
                        prepare.return_value = code
                        self.assertFalse(runner.start(self.discovery, self.tools))
                self.assertEqual(prepare.call_count, 2)
        self.assertFalse(_lanes_available(self.tools, self.discovery))

    def test_prepared_ledger_without_request_headroom_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "x",
                                             "RADAR_GEMINI_PAID_REMOTE": "https://example.invalid/repo.git"}):
                runner = NewsroomRunner(Path(directory) / "ledger.json")
                with patch("phong_bao.gemini_api.gemini_paid_budget.prepare", return_value=None), \
                        patch("phong_bao.gemini_api.gemini_paid_budget.remaining_tokens", return_value=0), \
                        patch("phong_bao.gemini_api.gemini_paid_budget.finalize", return_value=None) as finalize:
                    self.assertFalse(runner.start(self.discovery, self.tools))
                    finalize.assert_called_once()

    def test_checker_is_gemini_when_agy_dry_and_editor_used_codex(self):
        self.discovery.update(key_names=["GEMINI_API_KEY"], paid_ready=True)
        self.assertTrue(_lanes_available(self.tools, self.discovery))
        self.assertEqual([tool["id"] for tool in providers("kiem-chung", self.tools, self.discovery,
                                                             boat_exclude={"codex"})], ["gemini-api"])
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            status = cycle(snapshot_fetcher=lambda: fixture("snapshot.json"),
                           decisions_path=base / "decisions.json", cycles_dir=base / "cycles",
                           discovery=self.discovery, tools=self.tools,
                           runner=FixtureRunner(fixture("responses.json")),
                           articles=FixtureArticles(fixture("articles.json")), since_hours=200,
                           now=datetime(2026, 10, 27, 7, tzinfo=timezone.utc))
            self.assertEqual(status["state"], "decided")
            job = base / "cycles" / "20261027T070000Z" / "job"
            editor = json.loads((job / "editor.json").read_text(encoding="utf-8"))
            checker = json.loads((job / "checker.json").read_text(encoding="utf-8"))
            checked = [row for row in checker.values() if row["provider"] == "gemini-api"]
            self.assertTrue(checked)
            self.assertTrue(all(editor[row["id"]]["boat"] == "codex" for row in checked))
            decisions = json.loads((base / "decisions.json").read_text(encoding="utf-8"))["decisions"]
            self.assertTrue(any(row["decision"] == "publish" for row in decisions))

    def test_healthy_agy_keeps_subscription_checker(self):
        discovery = {**self.discovery, "fuel": "codex : còn\ngemini : còn",
                     "paid_ready": True, "key_names": ["GEMINI_API_KEY"]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cycle(snapshot_fetcher=lambda: fixture("snapshot.json"),
                  decisions_path=base / "decisions.json", cycles_dir=base / "cycles",
                  discovery=discovery, tools=self.tools, runner=FixtureRunner(fixture("responses.json")),
                  articles=FixtureArticles(fixture("articles.json")), since_hours=200,
                  now=datetime(2026, 10, 27, 7, tzinfo=timezone.utc))
            job = base / "cycles" / "20261027T070000Z" / "job"
            editor = json.loads((job / "editor.json").read_text(encoding="utf-8"))
            checker = json.loads((job / "checker.json").read_text(encoding="utf-8"))
            checked = [row for row in checker.values() if row["provider"]]
            self.assertTrue(checked)
            self.assertTrue(all(editor[row["id"]]["boat"] == "agy" and row["provider"] == "codex"
                                for row in checked))

    def test_missing_or_exhausted_shared_ledger_disables_paid_checker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "budget.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            discovery = {**self.discovery, "key_names": ["GEMINI_API_KEY"]}
            with patch.dict(os.environ, {"GEMINI_API_KEY": "x", "RADAR_GEMINI_PAID_REMOTE": str(remote)}):
                self.assertFalse(NewsroomRunner(root / "missing.json").start(discovery, self.tools))
                now = time.time()
                gemini_paid_budget._push(str(remote), {
                    "version": 1, "month": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m"),
                    "settled_micros": 20_000_000, "pending": {}, "settled_daily": {},
                    "pending_days": {}, "settled_consumers": {}}, now=now)
                self.assertFalse(NewsroomRunner(root / "spent.json").start(discovery, self.tools))
            self.assertFalse(_lanes_available(self.tools, discovery))

    def test_each_api_batch_reserves_and_settles_actual_usage(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
            runner = NewsroomRunner(Path(directory) / "ledger.json")
            runner.ready = True
            def response(body, key, timeout):
                rows = json.loads(body["contents"][0]["parts"][0]["text"])
                return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
                    {"text": json.dumps({"stories": [{"id": row["id"], "verified": True} for row in rows]})}]}}],
                    "usageMetadata": {"totalTokenCount": 100, "promptTokenCount": 70,
                                      "candidatesTokenCount": 30}}
            with patch("phong_bao.gemini_api.gemini_paid_budget.reserve", side_effect=[(None, "a"), (None, "b")]) as reserve, \
                    patch("phong_bao.gemini_api.gemini_paid_budget.settle") as settle, \
                    patch("phong_bao.gemini_api.summary_gemini.transport", side_effect=response):
                for sid in ("first", "second"):
                    result = runner.run("checker", [{"id": sid}], self.profile, "Check evidence")
                    self.assertEqual(result.rows[0]["id"], sid)
                    self.assertEqual(result.usage["source"], "gemini_api")
                self.assertEqual(reserve.call_count, 2)
                self.assertTrue(all(call.kwargs["consumer"] == "summary" for call in reserve.call_args_list))
                self.assertEqual([call.args[1:] for call in settle.call_args_list], [("a", 100), ("b", 100)])

    def test_malformed_api_batch_is_a_provider_failure_without_secret_text(self):
        self.discovery.update(key_names=["GEMINI_API_KEY"], paid_ready=True)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
            runner = NewsroomRunner(Path(directory) / "ledger.json")
            runner.ready = True
            malformed = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
                {"text": '{"stories": []}'}]}}], "usageMetadata": {"totalTokenCount": 45}}
            with patch("phong_bao.gemini_api.gemini_paid_budget.reserve", return_value=(None, "a")), \
                    patch("phong_bao.gemini_api.gemini_paid_budget.settle") as settle, \
                    patch("phong_bao.gemini_api.summary_gemini.transport", return_value=malformed):
                output, events = _agent_desk("checker", [{"id": "one"}], "Check evidence", "kiem-chung",
                                             self.tools, self.discovery, runner, boat_exclude={"codex"},
                                             require_success=False, concurrency=1)
            self.assertTrue(output["one"]["model_failure"])
            self.assertEqual(events[-1]["event"], "failure")
            self.assertNotIn("x", str(events[-1].get("error", "")))
            settle.assert_called_once()

    def test_two_batches_charge_the_shared_durable_monthly_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "budget.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            with patch.dict(os.environ, {"GEMINI_API_KEY": "x", "RADAR_GEMINI_PAID_REMOTE": str(remote)}):
                self.assertIsNone(gemini_paid_budget.prepare(root / "seed.json", paid=False,
                                                              remote=str(remote), run_key="seed", run_number=1))
                runner = NewsroomRunner(root / "cycle-ledger.json")
                discovery = {**self.discovery, "key_names": ["GEMINI_API_KEY"]}
                self.assertTrue(runner.start(discovery, self.tools))
                def response(body, key, timeout):
                    rows = json.loads(body["contents"][0]["parts"][0]["text"])
                    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
                        {"text": json.dumps({"stories": [{"id": row["id"]} for row in rows]})}]}}],
                        "usageMetadata": {"totalTokenCount": 100}}
                with patch("phong_bao.gemini_api.summary_gemini.transport", side_effect=response):
                    runner.run("checker", [{"id": "first"}], self.profile, "Check")
                    runner.run("checker", [{"id": "second"}], self.profile, "Check")
                self.assertIsNone(runner.finish())
            with tempfile.TemporaryDirectory() as restore_dir:
                store = gemini_paid_budget._restore(str(remote), Path(restore_dir) / "repo", time.time())
            self.assertEqual(store["settled_micros"], 2 * gemini_paid_budget._micros(100, time.time()))
            self.assertEqual(store["pending"], {})


if __name__ == "__main__":
    unittest.main()

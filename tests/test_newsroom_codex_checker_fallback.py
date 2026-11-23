"""Offline coverage for the temporary Codex checker exception."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phong_bao.cycle import cycle
from phong_bao.newsroom import FixtureArticles, _checker, _score_prose
from phong_bao.registry import load_registry
from phong_bao.runner import FixtureRunner
from radar.newsroom_decisions import desk_summary
from tests.test_phong_bao_writer import EXAMPLE, PROSE, SID


FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"
MARKER = "same-boat checker: codex (gpt-6-astra)"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class RecordingRunner(FixtureRunner):
    def __init__(self, responses=None):
        super().__init__(responses or fixture("responses.json"))
        self.calls = []

    def run(self, desk, rows, provider, instruction):
        self.calls.append((desk, provider, rows))
        return super().run(desk, rows, provider, instruction)


class CodexCheckerFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.snapshot = fixture("snapshot.json")
        self.discovery = {**fixture("discovery.json"), "key_names": [],
                          "fuel": "codex : còn\ngemini : CẠN"}

    def run_cycle(self, when, discovery=None, responses=None, articles=None):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runner = RecordingRunner(responses)
            status = cycle(snapshot_fetcher=lambda: self.snapshot,
                           decisions_path=base / "decisions.json", cycles_dir=base / "cycles",
                           discovery=discovery or self.discovery, tools=self.tools, runner=runner,
                           articles=articles or FixtureArticles(fixture("articles.json")), since_hours=10000,
                           now=when)
            decisions = (json.loads((base / "decisions.json").read_text(encoding="utf-8"))["decisions"]
                         if (base / "decisions.json").exists() else [])
            cycle_dir = base / "cycles" / when.strftime("%Y%m%dT%H%M%SZ")
            self.assertEqual(json.loads((cycle_dir / "status.json").read_text(encoding="utf-8")), status)
            job = cycle_dir / "job"
            checker = json.loads((job / "checker.json").read_text(encoding="utf-8")) if job.exists() else {}
            if job.exists():
                self.assertEqual(json.loads((job / "quyet-dinh.json").read_text(encoding="utf-8"))["decisions"],
                                 decisions)
                self.assertEqual(json.loads((cycle_dir / "quyet-dinh.json").read_text(encoding="utf-8"))["decisions"],
                                 decisions)
            return status, decisions, checker, runner.calls

    def test_codex_checks_with_other_model_and_marks_every_touched_decision(self):
        status, decisions, checker, calls = self.run_cycle(datetime(2026, 11, 28, 8, 59, 59,
                                                                    tzinfo=timezone.utc))
        self.assertEqual(status["state"], "decided")
        checked = [row for row in checker.values() if row["provider"] == "codex"]
        self.assertTrue(checked)
        self.assertEqual(status["same_boat_checker_count"], len(checked))
        marked = {row["id"] for row in decisions if MARKER in row["degradation_reasons"]}
        self.assertEqual(marked, {row["id"] for row in checked})
        self.assertTrue(any(row["decision"] == "publish" for row in decisions))
        editor_models = {call[1]["argv"][call[1]["argv"].index("--model") + 1]
                         for call in calls if call[0] == "editor" and call[1]["id"] == "codex"}
        checker_models = {call[1]["argv"][call[1]["argv"].index("--model") + 1]
                          for call in calls if call[0] == "checker" and call[1]["id"] == "codex"}
        self.assertEqual(editor_models, {"gpt-6-sol"})
        self.assertEqual(checker_models, {"gpt-6-astra"})
        self.assertTrue(all(set(row) == {"id", "title", "claims", "source_url", "cited_paragraphs"}
                            for desk, _, rows in calls if desk == "checker" for row in rows))

    def test_fixture_cycle_publishes_a_scored_same_boat_summary(self):
        self.snapshot = {"generated_at": "2026-11-24T00:00:00Z", "stories": [{
            "id": SID, "title": EXAMPLE["title"], "url": EXAMPLE["url"],
            "summary": "HelioLab introduced an AI simulation framework.",
            "published_at": "2026-11-23T22:00:00Z",
            "coverage": [{"id": "c1", "url": EXAMPLE["url"], "publisher": EXAMPLE["publisher"]}]}]}
        claims = ["HelioLab introduced CanvasKit, an AI simulation framework for a virtual workshop."]
        responses = {"reporter": {SID: {"id": SID, "selected_url": EXAMPLE["url"], "same_event": True,
                                         "reason": "The article covers CanvasKit."}},
                     "editor": {SID: {"id": SID, "news": True, "content_kind": "event_news",
                                      "reason": "A new AI framework was introduced.", "subject": "CanvasKit",
                                      "event_type": "release", "importance": "standard",
                                      "event_at": "2026-11-23T22:00:00Z", "claims": claims,
                                      "same_event_coverage_ids": ["c1"]}},
                     "checker": {SID: {"id": SID, "verified": True,
                                       "reason": "The article supports the claim.", "supported_claims": claims}},
                     "writer": {SID: deepcopy(PROSE)},
                     "scorer": {SID: {"id": SID, "questions": {
                         name: {"source_answer": "The article supports this point.",
                                "summary_answer": "The summary conveys this point.", "score": 9}
                         for name in ("what", "why", "notable", "meaning")},
                         "hard_errors": [], "findings": []}}}
        articles = FixtureArticles({"articles": {EXAMPLE["url"]: {
            "text": "\n".join(EXAMPLE["paragraphs"]), "reason": None}}})
        status, decisions, _, calls = self.run_cycle(datetime(2026, 11, 24, 1, tzinfo=timezone.utc),
                                                      responses=responses, articles=articles)
        visible = [row for row in decisions if desk_summary(row) is not None]
        self.assertEqual(len(visible), 1)
        self.assertEqual(status["same_boat_checker_count"], 1)
        self.assertEqual(status["same_boat_scorer_count"], len(visible))
        self.assertIn("same-boat checker: codex (gpt-6-astra)", visible[0]["degradation_reasons"])
        self.assertTrue(all("same-boat scorer: codex (gpt-6-astra)" in row["degradation_reasons"]
                            for row in visible))
        self.assertTrue(all(row["score"]["scorer_model"] == "gpt-6-astra" and
                            row["score"]["writer_models"] == ["gpt-6-sol"] for row in visible))
        self.assertEqual([(desk, provider["argv"][provider["argv"].index("--model") + 1])
                          for desk, provider, _ in calls if desk in {"writer", "scorer"}],
                         [("writer", "gpt-6-sol"), ("scorer", "gpt-6-astra")])

    def test_scorer_uses_other_boat_first_and_grants_nothing_after_expiry_or_same_model(self):
        packet = {"id": "story", "headline_vi": "Tựa đề", "paragraphs_vi": ["Một", "Hai", "Ba"]}
        answer = {"id": "story", "questions": {name: {"source_answer": "Source fact.",
                                               "summary_answer": "Summary fact.", "score": 9}
                                                 for name in ("what", "why", "notable", "meaning")},
                  "hard_errors": [], "findings": []}

        def score(discovery, models):
            runner = RecordingRunner({"scorer": {"story": answer}})
            results, _ = _score_prose({"story": packet}, {"story": ["codex"]}, self.tools, discovery, runner,
                                      writer_models={"story": models})
            return results["story"], runner.calls

        agy, calls = score({**self.discovery, "fuel": "codex : CÒN\ngemini : CÒN",
                            "codex_checker_exception": True}, ["gpt-6-sol"])
        self.assertEqual(calls[0][1]["id"], "agy")
        self.assertNotIn("same_boat_exception", agy["score"])
        gemini, calls = score({**self.discovery, "key_names": ["GEMINI_API_KEY"], "paid_ready": True,
                               "codex_checker_exception": True}, ["gpt-6-sol"])
        self.assertEqual(calls[0][1]["id"], "gemini-api")
        self.assertNotIn("same_boat_exception", gemini["score"])
        same_model, calls = score({**self.discovery, "codex_checker_exception": True}, ["gpt-6-astra"])
        self.assertEqual(same_model["state"], "unscored")
        self.assertEqual(calls, [])
        with patch("phong_bao.newsroom.CODEX_CHECKER_EXPIRES_AT",
                   datetime(2026, 11, 23, tzinfo=timezone.utc)):
            expired, calls = score({**self.discovery, "codex_checker_exception": True}, ["gpt-6-sol"])
        self.assertEqual(expired["state"], "unscored")
        self.assertEqual(calls, [])

    def test_expiry_restores_dry_lane(self):
        status, decisions, checker, calls = self.run_cycle(datetime(2026, 11, 28, 9, tzinfo=timezone.utc))
        self.assertEqual(status["state"], "dry_lane")
        self.assertEqual(decisions, [])
        self.assertEqual(checker, {})
        self.assertEqual(calls, [])

    def test_budget_cut_before_call_does_not_claim_a_same_boat_check(self):
        story = {"id": "one", "title": "A source-backed announcement", "url": "https://example.org/one"}
        reporter = {"one": {"readable": True, "selected_url": story["url"],
                            "source_text": "A source-backed announcement with enough detail to verify the claim.",
                            "representative_status": "readable"}}
        editor = {"one": {"news": True, "boat": "codex", "claims": [story["title"]]}}
        runner = RecordingRunner()
        checked, _ = _checker([story], {"one": {"pass": True}}, reporter, editor, self.tools,
                              {**self.discovery, "codex_checker_exception": True}, runner, deadline=0)
        self.assertNotIn("same_boat_checker", checked["one"])
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()

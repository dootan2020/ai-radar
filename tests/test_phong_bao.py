import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phong_bao.discovery import report
from phong_bao.evaluation import evaluate
from phong_bao.newsroom import FixtureArticles, _checker, _chief, _intake, _same_rep_url, run
from phong_bao.registry import load_registry, providers
from phong_bao.runner import FixtureRunner, RunnerError


FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NewsroomTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = fixture("discovery.json")
        self.runner = FixtureRunner(fixture("responses.json"))
        self.articles = FixtureArticles(fixture("articles.json"))

    def test_registry_adds_new_tool_from_one_file_and_reports_unknowns(self):
        found = report(self.discovery, self.tools)
        self.assertIn("capcut", found["found_not_configured"]["mcp_servers"])
        self.assertIn("NEW_VENDOR_API_KEY", found["found_not_configured"]["key_names"])
        self.assertNotIn("capcut", found["selected"]["dung-video"])
        self.assertIn("remotion", found["selected"]["dung-video"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capcut.toml"
            path.write_bytes(b'id = "capcut"\ncapabilities = ["dung-video"]\nkind = "mcp-plugin"\ncost_class = "subscription"\npriority = 10\nmonthly_cap_usd = 0\nrunner = "external"\n[detect]\nmcp_server = "capcut"\n')
            added = load_registry(directory)
            self.assertEqual([tool["id"] for tool in providers("dung-video", added, self.discovery)], ["capcut"])

    def test_fuel_exhaustion_removes_a_boat(self):
        discovery = {**self.discovery, "fuel": "  codex        : CẠN — usage limit\n  gemini       : chưa đo"}
        self.assertEqual([tool["id"] for tool in providers("bien-tap", self.tools, discovery)], ["agy"])
        discovery["fuel"] = "  codex        : còn\n  gemini       : CẠN"
        self.assertEqual([tool["id"] for tool in providers("bien-tap", self.tools, discovery)], ["codex"])

    def test_fixture_pass_records_every_desk_and_separate_checker(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            status = run(FIXTURES / "snapshot.json", job, self.tools, self.discovery, self.runner,
                         articles=self.articles)
            self.assertEqual(set(status["desks"]), {"intake", "reporter", "editor", "checker", "chief"})
            self.assertTrue(all(row["state"] == "done" for row in status["desks"].values()))
            decisions = json.loads((job / "quyet-dinh.json").read_text(encoding="utf-8"))["decisions"]
            self.assertEqual([row["decision"] for row in decisions], ["publish", "hold", "publish"])
            self.assertEqual(decisions[0]["importance_tier"], "standard")
            self.assertEqual(decisions[1]["round"], "editor")
            self.assertIn("artificialwatch.com", decisions[2]["source_url"])
            editor = json.loads((job / "editor.json").read_text(encoding="utf-8"))
            checker = json.loads((job / "checker.json").read_text(encoding="utf-8"))
            first = decisions[0]["id"]
            self.assertNotEqual(editor[first]["boat"], checker[first]["boat"])
            self.assertEqual(status["desks"]["reporter"]["batches"][0]["batch_size"], 3)
            self.assertEqual(status["desks"]["reporter"]["batches"][0]["source"], "character_estimate")
            self.assertEqual(evaluate(job / "quyet-dinh.json", FIXTURES / "labels.json")["junk_leaked"], 0)

    def test_checker_without_second_boat_stops_job(self):
        discovery = {**self.discovery, "commands": ["python", "codex"]}
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            with self.assertRaises(RunnerError):
                run(FIXTURES / "snapshot.json", job, self.tools, discovery, self.runner,
                    articles=self.articles)
            status = json.loads((job / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["desks"]["checker"]["state"], "failed")
            self.assertFalse((job / "quyet-dinh.json").exists())

    def test_failed_subscription_boat_falls_back_for_whole_batch(self):
        class FirstBoatFails(FixtureRunner):
            def run(self, desk, rows, provider, instruction):
                if desk == "reporter" and provider["id"] == "codex":
                    raise RunnerError("CLI temporary failure")
                return super().run(desk, rows, provider, instruction)

        with tempfile.TemporaryDirectory() as directory:
            status = run(FIXTURES / "snapshot.json", Path(directory) / "job", self.tools,
                         self.discovery, FirstBoatFails(fixture("responses.json")),
                         through="reporter", articles=self.articles)
            self.assertEqual(status["desks"]["reporter"]["batches"][0]["provider"], "agy")

    def test_job_resumes_after_intake_and_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            input_path = Path(directory) / "snapshot.json"
            input_path.write_bytes((FIXTURES / "snapshot.json").read_bytes())
            first = run(input_path, job, self.tools, self.discovery, self.runner,
                        through="intake", articles=self.articles)
            self.assertEqual(list(first["desks"]), ["intake"])
            second = run(input_path, job, self.tools, self.discovery, self.runner,
                         articles=self.articles)
            self.assertEqual(len(second["desks"]), 5)
            changed = fixture("snapshot.json")
            changed["stories"][0]["summary"] = "Changed source input"
            input_path.write_bytes(json.dumps(changed).encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "input differs"):
                run(input_path, job, self.tools, self.discovery, self.runner,
                    articles=self.articles)

    def test_intake_holds_stale_original_and_chief_demotes_older_tier(self):
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        story = {"id": "old", "title": "OpenAI launches a new AI model", "url": "https://example.org/news",
                 "published_at": (now - timedelta(days=31)).isoformat(), "summary": "OpenAI model release"}
        self.assertFalse(_intake([story], now)["old"]["pass"])
        story["published_at"] = (now - timedelta(days=10)).isoformat()
        decisions = _chief([story], {"old": {"pass": True, "reason": "pass"}},
                           {"old": {"readable": True, "selected_url": story["url"], "reason": "pass"}},
                           {"old": {"news": True, "reason": "pass", "importance": "top",
                                    "event_at": now.isoformat(), "claims": [],
                                    "same_event_coverage_ids": [], "split_coverage_ids": []}},
                           {"old": {"verified": True, "reason": "pass"}}, now)
        self.assertEqual(decisions[0]["decision"], "publish")
        self.assertEqual(decisions[0]["importance_tier"], "standard")

    def test_changelog_fragments_are_distinct_events(self):
        first = "https://platform.openai.com/docs/changelog#20260826-29"
        second = "https://platform.openai.com/docs/changelog#20260829-28"
        self.assertFalse(_same_rep_url(first, second))

    def test_checker_is_different_from_each_editor_boat_after_fallback(self):
        stories = fixture("snapshot.json")["stories"][:2]
        responses = fixture("responses.json")
        second = stories[1]["id"]
        responses["checker"][second] = {"id": second, "verified": True, "reason": "checked", "supported_claims": []}
        reporter = {s["id"]: {"source_text": self.articles.read(s["url"])[0], "selected_url": s["url"]} for s in stories}
        editor = {s["id"]: {"news": True, "boat": boat, "claims": []} for s, boat in zip(stories, ("codex", "agy"))}
        output, usage = _checker(stories, {}, reporter, editor, self.tools, self.discovery, FixtureRunner(responses))
        self.assertEqual(output[stories[0]["id"]]["boat"], "agy")
        self.assertEqual(output[second]["boat"], "codex")
        self.assertEqual(len(usage), 2)

    def test_evaluation_rejects_missing_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            path.write_bytes(b'{"decisions": []}')
            with self.assertRaises(ValueError):
                evaluate(path, FIXTURES / "labels.json")


if __name__ == "__main__":
    unittest.main()

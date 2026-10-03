"""Synthetic aggregate API fixtures; no network, keys, or live ranking claims."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import re
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from radar.common import iso_date
from radar.field_api import APIError, GitHubAPI, NoRedirect, native_history
from radar.field_config import FIELDS, classify
from radar.field_history import validate
from radar.field_rankings import collect, empty_state, measurement, search_groups
from radar.transport import ResponseText

NOW = datetime(2026, 10, 3, 1, tzinfo=timezone.utc)


def repository(identity=1, **overrides):
    return dict(id=identity, full_name=f"example/tool-{identity}", description="AI coding assistant and AI agent framework",
                topics=["coding-agent", "agent-framework"], stargazers_count=200,
                pushed_at=iso_date(NOW - timedelta(days=1)), archived=False, fork=False,
                license={"spdx_id": "MIT"}) | overrides


class FixtureAPI:
    def __init__(self, repos=(), failures=(), native=None):
        self.repos, self.failures, self.native = list(repos), set(failures), native
        self.requests = []

    def get(self, path, **params):
        self.requests.append(dict(url=path, http_status=200, status="ok"))
        if path.startswith("/search/"):
            topics = re.findall(r"topic:([a-z0-9-]+)", params["q"])
            if set(topics).intersection(self.failures):
                raise APIError("http_refused", 403)
            rows = [r for r in self.repos if set(topics).intersection(r["topics"])]
            return dict(total_count=len(rows), incomplete_results=False, items=deepcopy(rows[:params["per_page"]]))
        if path.endswith("/stargazers/history"):
            if isinstance(self.native, Exception):
                raise self.native
            return deepcopy(self.native if self.native is not None else [])
        identity = int(path.rsplit("/", 1)[1])
        repo = next((r for r in self.repos if r["id"] == identity), None)
        if repo is None:
            raise APIError("http_refused", 404)
        return deepcopy(repo)


class ClassificationTests(unittest.TestCase):
    def test_independent_fields_and_topic_contamination(self):
        repo = repository()
        self.assertEqual(set(classify(repo, NOW)), {"coding", "agents"})
        broad = repository(description="A neural training library", topics=[topic for _, _, topics, _ in FIELDS for topic in topics])
        self.assertEqual(classify(broad, NOW), {})

    def test_all_seventeen_field_task_fixtures(self):
        cases = [("coding", "coding-agent", "AI coding agent"), ("video", "text-to-video", "AI video generation"),
                 ("images", "text-to-image", "AI image generation"), ("audio", "voice-cloning", "Voice cloning toolkit"),
                 ("animation", "motion-generation", "Create motion graphics programmatically"),
                 ("translation", "machine-translation", "Neural machine translation engine"),
                 ("agents", "agent-framework", "An AI agent framework"),
                 ("mcp", "model-context-protocol", "An MCP server for browser tools"),
                 ("rag", "retrieval-augmented-generation", "Retrieval augmented generation pipeline"),
                 ("evaluation", "llm-evaluation", "LLM evaluation toolkit"),
                 ("local-models", "local-llm", "Run local LLM inference"),
                 ("training", "fine-tuning", "LLM fine tuning toolkit"),
                 ("music", "music-generation", "AI music generation"),
                 ("ocr", "document-parsing", "AI document parsing"),
                 ("robotics", "embodied-ai", "Embodied AI robot learning"),
                 ("trading", "algorithmic-trading", "AI algorithmic trading"),
                 ("games", "game-ai", "AI game NPC behavior")]
        self.assertEqual({case[0] for case in cases}, {field[0] for field in FIELDS})
        for field, topic, purpose in cases:
            with self.subTest(field=field):
                self.assertEqual(set(classify(repository(topics=[topic], description=purpose), NOW)), {field})

    def test_generic_gates_and_license_floor(self):
        changes = [dict(archived=True), dict(fork=True), dict(stargazers_count=99), dict(stargazers_count=True),
                   dict(pushed_at=iso_date(NOW - timedelta(days=31))), dict(pushed_at=iso_date(NOW + timedelta(seconds=1))),
                   dict(full_name="example/awesome-agents"), dict(full_name="example/agent-tutorials"),
                   dict(description="A curated list of AI coding assistant tools"), dict(topics=["coding-assistant", "survey"]),
                   dict(license=None), dict(license={"spdx_id": "NOASSERTION"}), dict(license={"spdx_id": "OpenRAIL"}),
                   dict(license={"spdx_id": "CC-BY-NC-4.0"}), dict(description="A course about coding agents")]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(classify(repository(**change), NOW), {})
        self.assertTrue(classify(repository(stargazers_count=100, pushed_at=iso_date(NOW - timedelta(days=30))), NOW))

    def test_short_video_maker_and_workflow_automation_distinction(self):
        video_maker = repository(
            full_name="harry0703/MoneyPrinterTurbo",
            description="利用 AI 大模型和自动化工作流，根据主题或关键词一键生成高清短视频。Generate HD short videos from a topic or keyword with an automated AI workflow.",
            topics=["ai-video-generator", "content-creation", "ffmpeg", "instagram-reels", "llm", "python",
                    "short-video", "subtitles", "text-to-speech", "tiktok", "video-automation", "video-workflow",
                    "workflow-automation", "youtube-shorts"])
        # A short-video generator describing its pipeline as an automated workflow must NOT qualify as agents
        self.assertNotIn("agents", classify(video_maker, NOW))
        # An active workflow automation engine or platform DOES qualify
        workflow_engine = repository(
            full_name="example/flow-engine",
            description="A workflow automation platform to automate workflows across services",
            topics=["workflow-automation"])
        self.assertIn("agents", classify(workflow_engine, NOW))
        agent_orchestrator = repository(
            full_name="example/agent-runner",
            description="Multi-agent orchestration system to build and run agents",
            topics=["ai-agents", "workflow-automation"])
        self.assertIn("agents", classify(agent_orchestrator, NOW))


class RankingTests(unittest.TestCase):
    def test_warmup_without_native_requests_and_empty_fields(self):
        output, state = collect(FixtureAPI([repository()], native=APIError("http_refused", 403)), NOW)
        self.assertEqual(validate(state), state)
        coding = output["fields"][0]
        self.assertEqual(coding["status"], "tracking")
        self.assertEqual(coding["ranked"], [])
        row = coding["tracking"][0]
        self.assertIsNone(row["stars_net_7d"])
        self.assertEqual(row["tracking_since"], iso_date(NOW))
        self.assertEqual(row["native_history"]["status"], "not_requested")
        self.assertFalse(any("stargazers" in request["url"] for request in output["requests"]))
        self.assertEqual(output["fields"][1]["status"], "empty")

    def test_positive_zero_negative_net_and_tie_sorting(self):
        start = NOW - timedelta(days=7)
        _, state = collect(FixtureAPI([repository(i, stargazers_count=200, pushed_at=iso_date(start)) for i in range(1, 5)]), start)
        repos = [repository(1, stargazers_count=250), repository(2, stargazers_count=200),
                 repository(3, stargazers_count=150), repository(4, stargazers_count=250)]
        output, _ = collect(FixtureAPI(repos, native=[dict(week=1, total=1000, days=[1000, 0, 0, 0, 0, 0, 0])]), NOW, state)
        rows = output["fields"][0]["ranked"]
        self.assertEqual([r["repository_id"] for r in rows], [1, 4, 2, 3])
        self.assertEqual([r["stars_net_7d"] for r in rows], [50, 50, 0, -50])
        self.assertTrue(all(r["window_seconds"] == 604800 and not r["approximate"] for r in rows))

    def test_rolling_interval_requires_nearby_observation(self):
        state = empty_state()
        start = NOW - timedelta(days=7, hours=2)
        state["snapshots"][start.date().isoformat()] = {"1": dict(stars=250, observed_at=iso_date(start))}
        row = measurement(1, 200, iso_date(NOW), state)
        self.assertEqual(row["stars_net_7d"], -50)
        self.assertTrue(row["approximate"])
        self.assertEqual(row["window_seconds"], 612000)
        self.assertIsNone(measurement(1, 200, iso_date(NOW + timedelta(hours=2)), state)["stars_net_7d"])

    def test_daily_reuse_preserves_time_and_does_not_fetch(self):
        output, state = collect(FixtureAPI([repository()]), NOW)
        api = FixtureAPI([])
        again, _ = collect(api, NOW + timedelta(hours=1), state)
        self.assertEqual(again, output)
        self.assertEqual(api.requests, [])

    def test_rename_direct_refresh_and_first_seen_beyond_retention(self):
        start = NOW - timedelta(days=50)
        _, state = collect(FixtureAPI([repository(pushed_at=iso_date(start))]), start)
        renamed = repository(full_name="new-owner/renamed")
        api = FixtureAPI([renamed], failures=[t for _, _, topics, _ in FIELDS for t in topics])
        output, state = collect(api, NOW, state)
        row = output["fields"][0]["tracking"][0]
        self.assertEqual(row["full_name"], "new-owner/renamed")
        self.assertEqual(row["tracking_since"], iso_date(start))
        self.assertEqual(len(state["snapshots"]), 1)
        self.assertEqual(output["fields"][0]["status"], "partial")

    def test_failed_fields_retain_stale_evidence_and_retry_after_six_hours(self):
        _, state = collect(FixtureAPI([repository()]), NOW - timedelta(days=1))
        failing = [t for _, _, topics, _ in FIELDS for t in topics]
        output, state = collect(FixtureAPI([], failures=failing), NOW, state)
        field = output["fields"][0]
        self.assertEqual(field["status"], "stale")
        self.assertEqual(field["ranked"], [])
        self.assertEqual(field["tracking"][0]["observed_at"], iso_date(NOW - timedelta(days=1)))
        self.assertFalse(output["complete"])
        api = FixtureAPI([repository()])
        recovered, _ = collect(api, NOW + timedelta(hours=6), state)
        self.assertTrue(api.requests)
        self.assertTrue(recovered["complete"])

    def test_cap_and_license_exclusion_are_visible(self):
        repos = [repository(i) for i in range(1, 32)] + [repository(32, license=None)]
        output, _ = collect(FixtureAPI(repos), NOW)
        field = output["fields"][0]
        self.assertEqual(len(field["tracking"]), 20)
        self.assertTrue(field["truncated"])
        output, _ = collect(FixtureAPI([repository(32, license=None)]), NOW)
        self.assertEqual(sum(d["excluded_license"] for d in output["fields"][0]["diagnostics"]), 1)

    def test_generated_queries_contain_no_logical_or(self):
        cutoff = iso_date(NOW - timedelta(days=30))
        total_queries = 0
        for field, name, topics, _ in FIELDS:
            groups_and_queries = list(search_groups(topics, cutoff))
            self.assertEqual(len(groups_and_queries), len(topics))
            for group, query in groups_and_queries:
                total_queries += 1
                self.assertEqual(len(group), 1)
                self.assertNotIn(" OR ", query)
                self.assertFalse(re.search(r"\bOR\b", query))
                self.assertEqual(len(re.findall(r"topic:", query)), 1)
                self.assertTrue(query.startswith(f"topic:{group[0]} "))
        self.assertEqual(total_queries, 59)


class APIBoundaryTests(unittest.TestCase):
    def test_native_schema_unknown_empty_and_calendar_added(self):
        for value, expected in [([], "empty"), ({"history": []}, "unknown_schema"),
                                ([dict(week=1, total=3, days=[1, 2, 0, 0, 0, 0, 0])], "ok"),
                                ([dict(week=1, total=3, days=[9] * 7)], "unknown_schema")]:
            result = native_history(FixtureAPI(native=value), "example/tool")
            self.assertEqual(result["status"], expected)
            self.assertFalse(result["usable_for_net"])

    def test_bad_json_and_transport_failure_are_sanitized(self):
        api = GitHubAPI(transport=lambda url: "bad json", sleep=lambda delay: None)
        with self.assertRaisesRegex(APIError, "invalid_or_unavailable"):
            api.get("/search/repositories")
        self.assertEqual(api.requests[0]["status"], "invalid_or_unavailable")

    def test_primary_and_secondary_limits_and_permission_refusal(self):
        fixtures = [(403, {"X-RateLimit-Remaining": "0"}, b'{"message":"API rate limit exceeded"}', {"search"}),
                    (403, {"X-RateLimit-Remaining": "42"}, b'{"message":"secondary rate limit"}', {"search", "core"}),
                    (429, {}, b'{}', {"search", "core"}), (403, {}, b'{"message":"Resource not accessible"}', set())]
        for status, headers, body, stopped in fixtures:
            api = GitHubAPI(sleep=lambda delay: None)
            error = HTTPError("https://api.github.com/search/repositories", status, "failure", headers, BytesIO(body))
            with patch.dict("os.environ", {"GITHUB_TOKEN": "fixture-only"}), patch("radar.field_api.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(APIError):
                    api.get("/search/repositories")
            self.assertEqual(api.stopped, stopped)

    def test_injected_clock_and_redirect_refusal(self):
        api = GitHubAPI(transport=lambda url: ResponseText("{}", 200), clock=lambda: 0, sleep=lambda delay: None)
        self.assertEqual(api.get("/repositories/1"), {})
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "http://api.github.com/"))


if __name__ == "__main__":
    unittest.main()

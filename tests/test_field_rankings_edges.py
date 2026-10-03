"""Independent offline edge cases; no requests leave the process."""

from datetime import datetime, timedelta, timezone
import io
import re
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from radar.field_api import API, APIError, GitHubAPI, native_history
from radar.field_config import FIELDS, classify
from radar.field_history import validate
from radar.field_rankings import collect, empty_state, measurement

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


class FieldClassificationEdges(unittest.TestCase):
    def test_educational_description_is_not_a_tool_but_translating_books_is(self):
        repo = dict(id=42, full_name="example/tool", archived=False, fork=False,
                    description="AI coding agent", topics=["coding-agent", "code-generation"],
                    stargazers_count=100, pushed_at=NOW.isoformat(), license={"spdx_id": "MIT"})
        for description in ("A book about AI coding agents", "A survey of AI coding assistants",
                            "A book about AI code generation", "A survey of AI coding assistant systems",
                            "An awesome list of AI code generation tools"):
            with self.subTest(description=description):
                self.assertEqual(classify(repo | {"description": description}, NOW), {})
        translator = repo | {"topics": ["machine-translation"],
                             "description": "Neural machine translation tool to translate books and documents"}
        self.assertEqual(set(classify(translator, NOW)), {"translation"})

    def test_malformed_license_identifier_excludes_row_without_aborting(self):
        repo = dict(id=42, full_name="example/tool", archived=False, fork=False,
                    description="AI coding agent", topics=["coding-agent"],
                    stargazers_count=100, pushed_at=NOW.isoformat(), license={"spdx_id": "MIT"})
        self.assertIn("coding", classify(repo, NOW))
        for identifier in ([], {}, None, True, 17):
            with self.subTest(identifier=identifier):
                self.assertEqual(classify(repo | {"license": {"spdx_id": identifier}}, NOW), {})


class FieldQuotaEdges(unittest.TestCase):
    def test_primary_search_exhaustion_preserves_core_budget(self):
        client = GitHubAPI()
        error = HTTPError(API + "/search/repositories", 403, "Forbidden",
                          {"X-RateLimit-Remaining": "0"},
                          io.BytesIO(b'{"message":"API rate limit exceeded for installation"}'))
        opener = Mock()
        opener.open.side_effect = error
        with patch("radar.field_api.build_opener", return_value=opener), \
                patch.dict("os.environ", {"GITHUB_TOKEN": "synthetic-token"}):
            with self.assertRaises(APIError):
                client._read(API + "/search/repositories")
        self.assertIn("search", client.stopped)
        self.assertNotIn("core", client.stopped)

    def test_injected_clock_and_transport_allow_deterministic_search_pacing(self):
        tick, calls = [0.0], []

        def sleep(seconds):
            tick[0] += seconds

        def transport(url):
            calls.append(url)
            return '{"items":[],"total_count":0,"incomplete_results":false}'

        client = GitHubAPI(transport=transport, clock=lambda: tick[0], sleep=sleep)
        self.assertEqual(client.get("/search/repositories")["items"], [])
        self.assertEqual(client.get("/search/repositories")["items"], [])
        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(tick[0], 2.1)


class FieldMeasurementEdges(unittest.TestCase):
    def state(self, ago, stars=200):
        earlier = NOW - ago
        state = empty_state()
        state["snapshots"][earlier.date().isoformat()] = {
            "42": {"stars": stars, "observed_at": earlier.isoformat()}}
        return state

    def test_negative_and_zero_are_measurements_not_missing(self):
        for current, expected in ((150, -50), (200, 0)):
            with self.subTest(current=current):
                result = measurement(42, current, NOW.isoformat(), self.state(timedelta(days=7)))
                self.assertEqual(result["stars_net_7d"], expected)
                self.assertEqual(result["method"], "snapshot_net")
                self.assertEqual(result["window_seconds"], 604800)
                self.assertFalse(result["approximate"])

    def test_tolerance_exports_actual_endpoints_and_never_extrapolates(self):
        for side in (-1, 1):
            with self.subTest(side=side):
                age = timedelta(days=7, hours=side * 3)
                result = measurement(42, 201, NOW.isoformat(), self.state(age))
                self.assertEqual(result["stars_net_7d"], 1)
                self.assertEqual(result["window_seconds"], int(age.total_seconds()))
                self.assertTrue(result["approximate"])
                rejected = measurement(42, 201, NOW.isoformat(),
                                       self.state(age + timedelta(seconds=side)))
                self.assertIsNone(rejected["stars_net_7d"])
                self.assertIsNone(rejected["method"])

    def test_refused_native_history_does_not_invent_measurement(self):
        api = Mock()
        api.get.side_effect = APIError("http_refused", 403)
        result = native_history(api, "example/tool")
        self.assertEqual(result["status"], "http_refused")
        self.assertEqual(result["http_status"], 403)
        self.assertFalse(result["usable_for_net"])
        self.assertIsNone(measurement(42, 50000, NOW.isoformat(), empty_state())["stars_net_7d"])


class FieldDailySnapshotEdges(unittest.TestCase):
    def test_empty_search_cannot_hide_failed_existing_member_refresh(self):
        repo = dict(id=42, full_name="example/tool", archived=False, fork=False,
                    description="AI coding agent", topics=["coding-agent"],
                    stargazers_count=100, pushed_at=NOW.isoformat(), license={"spdx_id": "MIT"})

        class FixtureAPI:
            def __init__(self, healthy):
                self.healthy, self.requests = healthy, []

            def get(self, path, **params):
                self.requests.append({"url": path})
                if path == "/search/repositories":
                    rows = [repo] if self.healthy else []
                    return {"items": rows, "total_count": len(rows), "incomplete_results": False}
                raise APIError("budget_exhausted")

        _, initial = collect(FixtureAPI(True), NOW)
        output, _ = collect(FixtureAPI(False), NOW + timedelta(days=1), initial)
        coding = next(field for field in output["fields"] if field["id"] == "coding")
        self.assertFalse(output["complete"])
        self.assertNotEqual(coding["status"], "empty")
        self.assertEqual(coding["ranked"], [])
        self.assertTrue(coding["tracking"])
        self.assertTrue(coding["tracking"][0]["stale"])
        self.assertEqual(coding["tracking"][0]["observed_at"], initial["last_output"]["generated_at"])

    def test_partial_retry_preserves_prior_points_when_entire_cohort_changes(self):
        descriptions = {"coding": "AI coding agent", "video": "AI video generation",
                        "images": "AI image generation", "audio": "AI voice cloning",
                        "animation": "AI character animation", "translation": "Neural machine translation",
                        "agents": "AI agent orchestration", "mcp": "MCP server toolkit",
                        "rag": "Retrieval augmented generation pipeline", "evaluation": "LLM evaluation toolkit",
                        "local-models": "Local LLM inference", "training": "LLM fine tuning toolkit",
                        "music": "AI music generation", "ocr": "AI document parsing OCR",
                        "robotics": "Embodied AI robot learning", "trading": "AI algorithmic trading",
                        "games": "AI game NPC behavior"}

        class FixtureAPI:
            def __init__(self, offset, at):
                self.offset, self.at, self.requests = offset, at, []

            def get(self, path, **params):
                self.requests.append({"url": path})
                if path != "/search/repositories":
                    raise APIError("http_refused", 404)
                topic = re.findall(r"topic:([a-z0-9-]+)", params["q"])[0]
                group = next((index, field) for index, field in enumerate(FIELDS) if topic in field[2])
                index, field = group
                rows = [dict(id=self.offset + index * 20 + n + 1,
                             full_name=f"example/tool-{self.offset + index * 20 + n + 1}",
                             archived=False, fork=False, license={"spdx_id": "MIT"},
                             stargazers_count=100 + n, description=descriptions[field[0]],
                             topics=[field[2][0]], pushed_at=self.at.isoformat()) for n in range(20)]
                return {"items": rows, "total_count": 20, "incomplete_results": True}

        _, initial = collect(FixtureAPI(0, NOW), NOW)
        validate(initial)
        first_points = initial["snapshots"][NOW.date().isoformat()].copy()
        self.assertEqual(len(first_points), 20 * len(FIELDS))
        later = NOW + timedelta(hours=6)
        _, retried = collect(FixtureAPI(1000, later), later, initial)
        validate(retried)
        preserved = retried["snapshots"][NOW.date().isoformat()]
        for identity, point in first_points.items():
            self.assertEqual(preserved[identity], point)


if __name__ == "__main__":
    unittest.main()

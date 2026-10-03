"""Deterministic regression evidence; synthetic repositories, no live API proof."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from radar import field_api, field_config, field_history, field_rankings
from radar.common import iso_date
from radar.field_api import APIError, GitHubAPI
from radar.field_history import FILENAME, persist, restore, validate
from radar.field_publish import prepare
from radar.field_rankings import collect
from test_field_rankings import NOW, FixtureAPI, repository


@contextmanager
def configured(fields):
    with ExitStack() as stack:
        for module in (field_config, field_history, field_rankings):
            if hasattr(module, "FIELDS"):
                stack.enter_context(patch.object(module, "FIELDS", fields))
        yield


class FieldConfigurationRegressions(unittest.TestCase):
    def test_historical_field_order_and_removed_fields_remain_valid(self):
        _, state = collect(FixtureAPI([repository()]), NOW)
        original = deepcopy(state)
        for fields in (tuple(reversed(field_config.FIELDS)), field_config.FIELDS[:1]):
            with self.subTest(fields=[f[0] for f in fields]), configured(fields):
                self.assertEqual(validate(state), original)

    def test_changed_field_list_invalidates_same_day_cache_without_resetting_history(self):
        old_fields = field_config.FIELDS[:1]
        with configured(old_fields):
            _, state = collect(FixtureAPI([repository()]), NOW)
        original_points = deepcopy(state["snapshots"])
        original_first_seen = deepcopy(state["first_seen"])
        api = FixtureAPI([repository()])
        output, migrated = collect(api, NOW + timedelta(hours=1), state)
        self.assertTrue(api.requests, "A changed field definition cannot reuse the prior configuration's cache")
        self.assertEqual([f["id"] for f in output["fields"]], [f[0] for f in field_config.FIELDS])
        self.assertEqual(migrated["snapshots"], original_points)
        self.assertEqual(migrated["first_seen"], original_first_seen)

    def test_changed_ai_signal_invalidates_same_day_cache(self):
        _, state = collect(FixtureAPI([repository()]), NOW)
        original_points = deepcopy(state["snapshots"])
        api = FixtureAPI([repository()])
        with patch.object(field_config, "AI_SIGNAL", re.compile(r"\bquantum\b", re.I)):
            output, changed = collect(api, NOW + timedelta(hours=1), state)
        self.assertTrue(api.requests)
        coding = next(field for field in output["fields"] if field["id"] == "coding")
        self.assertEqual(coding["tracking"], [])
        self.assertEqual(changed["snapshots"], original_points)
        self.assertEqual(changed["first_seen"], state["first_seen"])

    def test_legacy_output_without_fingerprint_loads_but_is_not_cache_reused(self):
        _, state = collect(FixtureAPI([repository()]), NOW)
        state["last_output"].pop("config_fingerprint", None)
        validate(state)
        api = FixtureAPI([repository()])
        output, changed = collect(api, NOW + timedelta(hours=1), state)
        self.assertTrue(api.requests)
        self.assertIsInstance(output.get("config_fingerprint"), str)
        self.assertEqual(changed["snapshots"], state["snapshots"])

    def test_historical_configuration_does_not_relax_duplicate_or_unsafe_ids(self):
        _, state = collect(FixtureAPI([repository()]), NOW)
        for identity in (state["last_output"]["fields"][0]["id"], "../unsafe"):
            invalid = deepcopy(state)
            invalid["last_output"]["fields"][1]["id"] = identity
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                validate(invalid)

    def test_configuration_change_roundtrips_through_real_local_git(self):
        with tempfile.TemporaryDirectory(prefix="field-migration-") as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True,
                           capture_output=True, timeout=30)
            prepare(str(remote), root / "before.json", root / "before", NOW, FixtureAPI([repository()]))
            persist(str(remote), root / "before")
            _, before = restore(str(remote), root / "read-before")
            with configured(tuple(reversed(field_config.FIELDS[:2]))):
                output = prepare(str(remote), root / "after.json", root / "after",
                                 NOW + timedelta(hours=1), FixtureAPI([repository()]))
                self.assertTrue(persist(str(remote), root / "after"))
                _, after = restore(str(remote), root / "read-after")
                self.assertEqual([f["id"] for f in output["fields"]], [f[0] for f in field_config.FIELDS])
                self.assertEqual(after["snapshots"], before["snapshots"])
                self.assertEqual(after["first_seen"], before["first_seen"])


class FieldSelectionRegressions(unittest.TestCase):
    def test_broad_topics_do_not_supply_missing_ai_task_evidence(self):
        cases = [("backtesting", "A fast backtesting library for investment portfolios"),
                 ("algorithmic-trading", "Algorithmic trading and technical analysis tools"),
                 ("robotics", "Robotics middleware and hardware drivers"),
                 ("robotics", "Robot control library for serial motors"),
                 ("game-development", "A general purpose game engine"),
                 ("procedural-generation", "Procedural game level generation engine"),
                 ("game-ai", "A general purpose game engine"),
                 ("ai-game", "Procedural game level generation engine")]
        for topic, description in cases:
            with self.subTest(topic=topic, description=description):
                self.assertEqual(field_config.classify(repository(topics=[topic], description=description), NOW), {})

    def test_collections_rejected_without_rejecting_of_course(self):
        for description in ("A collection of AI coding agent skills", "A collection of system prompts for AI coding agents",
                            "A list of coding agent skills", "A collection of AI agent system prompts"):
            with self.subTest(description=description):
                self.assertEqual(field_config.classify(repository(description=description), NOW), {})
        self.assertIn("coding", field_config.classify(repository(description="An AI coding agent that of course edits code"), NOW))

    def test_ready_requires_five_measured_repositories_without_padding(self):
        start = NOW - timedelta(days=7)
        for count in (1, 4, 5):
            with self.subTest(count=count):
                repos = [repository(i, pushed_at=iso_date(start)) for i in range(1, count + 1)]
                _, state = collect(FixtureAPI(repos), start)
                output, _ = collect(FixtureAPI([repository(i) for i in range(1, count + 1)]), NOW, state)
                coding = next(f for f in output["fields"] if f["id"] == "coding")
                self.assertEqual(len(coding["ranked"]), count)
                self.assertEqual(len({r["repository_id"] for r in coding["ranked"]}), count)
                self.assertEqual(coding["status"], "ready" if count == 5 else "partial")
                self.assertEqual(output["limits"]["minimum_ranked"], 5)
                if count < 5:
                    self.assertEqual(coding["status_reason"], "insufficient_ranked_rows")

    def test_newcomer_enters_full_field_and_history_survives_eviction_and_return(self):
        start = NOW - timedelta(days=7)
        original = [repository(i, stargazers_count=400 - i, pushed_at=iso_date(start)) for i in range(1, 22)]
        _, initial = collect(FixtureAPI(original), start)
        self.assertIn("21", initial["snapshots"][iso_date(start)[:10]], "Admitted discovery outside the display cap needs a baseline")
        middle = start + timedelta(days=1)
        changed = [repository(i, stargazers_count=400 - i, pushed_at=iso_date(middle)) for i in range(1, 22)]
        changed[-1]["stargazers_count"] = 1000
        output, state = collect(FixtureAPI(changed), middle, initial)
        coding = next(f for f in output["fields"] if f["id"] == "coding")
        self.assertIn(21, [r["repository_id"] for r in coding["tracking"]])
        final = [repository(i, stargazers_count=400 - i) for i in range(1, 22)]
        final[-1]["stargazers_count"] = 1200
        final[-2]["stargazers_count"] = 1100
        output, state = collect(FixtureAPI(final), NOW, state)
        rows = next(f for f in output["fields"] if f["id"] == "coding")["ranked"]
        returning = next(r for r in rows if r["repository_id"] == 20)
        newcomer = next(r for r in rows if r["repository_id"] == 21)
        self.assertEqual(returning["tracking_since"], iso_date(start))
        self.assertEqual(newcomer["tracking_since"], iso_date(start))
        self.assertEqual(newcomer["stars_net_7d"], 821)

    def test_collection_performs_no_unused_native_probes(self):
        api = FixtureAPI([repository()])
        collect(api, NOW)
        self.assertFalse(any("stargazers" in r["url"] for r in api.requests))


class FieldBudgetRegressions(unittest.TestCase):
    def test_all_seventeen_fields_fit_search_budget_and_query_limits(self):
        tick, calls = [0.0], []

        def transport(url):
            calls.append((tick[0], url))
            return '{"items":[],"total_count":0,"incomplete_results":false}'

        api = GitHubAPI(transport=transport, clock=lambda: tick[0], sleep=lambda delay: tick.__setitem__(0, tick[0] + delay))
        output, _ = collect(api, NOW)
        self.assertEqual(len(output["fields"]), 17)
        self.assertTrue(output["complete"])
        searches = [(at, parse_qs(urlsplit(url).query)) for at, url in calls if "/search/" in url]
        self.assertLessEqual(len(searches), 60)
        self.assertEqual(len(searches), 59)
        covered = set()
        for at, params in searches:
            query = params["q"][0]
            self.assertEqual(params["per_page"], ["100"])
            self.assertEqual(params["page"], ["1"])
            self.assertNotIn(" OR ", query)
            self.assertFalse(re.search(r"\b(?:OR|AND|NOT)\b", query))
            self.assertLessEqual(len(query), 256)
            covered.update(re.findall(r"topic:([a-z0-9-]+)", query))
            self.assertLessEqual(sum(at <= point < at + 60 for point, _ in searches), 24)
        self.assertEqual(covered, {topic for _, _, topics, _ in field_config.FIELDS for topic in topics})
        self.assertLess(tick[0], 210)

    def test_core_limit_and_deadline_stop_transport(self):
        tick, calls = [0.0], []
        api = GitHubAPI(transport=lambda url: calls.append(url) or "{}", clock=lambda: tick[0], sleep=lambda delay: None)
        for identity in range(80):
            api.get(f"/repositories/{identity + 1}")
        with self.assertRaises(APIError):
            api.get("/repositories/81")
        self.assertEqual(len(calls), 80)
        calls.clear()
        api = GitHubAPI(transport=lambda url: calls.append(url) or "{}", clock=lambda: tick[0], sleep=lambda delay: None)
        tick[0] = 211
        with self.assertRaises(APIError):
            api.get("/repositories/1")
        self.assertEqual(calls, [])

    def test_core_reserve_protects_other_collectors(self):
        api = GitHubAPI()
        api._quota({"X-RateLimit-Remaining": "500"}, field_api.API + "/repositories/1")
        self.assertIn("core", api.stopped)
        self.assertNotIn("search", api.stopped)

    def test_search_cap_does_not_spend_core_budget(self):
        tick, calls = [0.0], []
        api = GitHubAPI(transport=lambda url: calls.append(url) or "{}", clock=lambda: tick[0],
                        sleep=lambda delay: tick.__setitem__(0, tick[0] + delay))
        for index in range(60):
            api.get("/search/repositories", q=f"topic:fixture-{index}")
        with self.assertRaises(APIError):
            api.get("/search/repositories", q="topic:overflow")
        api.get("/repositories/1")
        self.assertEqual(len(calls), 61)


if __name__ == "__main__":
    unittest.main()

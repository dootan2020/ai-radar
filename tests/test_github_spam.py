"""Regression cases for coordinated copies in the new GitHub repository source."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from radar.catalog import sources
from radar.discovery import parse_github
from radar import pipeline, youtube


SOURCE = {"id": "github-ai", "name": "New GitHub repositories", "lab": "",
          "kind": "json", "group": "repository", "publisher": "github"}
OBSERVED = "2026-11-14T15:40:00Z"
SAMPLES = Path(__file__).resolve().parents[1] / "plans" / "reports"


def repo(owner, name, description, created, forks=0):
    return {"full_name": f"{owner}/{name}", "html_url": f"https://github.com/{owner}/{name}",
            "description": description, "created_at": created, "stargazers_count": 250,
            "forks_count": forks}


class GithubSpamTests(unittest.TestCase):
    def parse(self, rows, source=SOURCE):
        return parse_github(json.dumps({"items": rows}), source, OBSERVED)

    def test_coordinated_copies_are_dropped_even_with_forks(self):
        copies = [repo(f"owner-{i}", "same-agent", "Identical AI agent project",
                       f"2026-11-13T16:4{i}:00Z", forks=4 if i == 0 else 0)
                  for i in range(5)]
        real = repo("team", "different-agent", "An original AI agent project",
                    "2026-11-09T00:00:00Z", forks=2)
        with self.assertLogs("radar.discovery", level="WARNING") as logs:
            items = self.parse(copies + [real])
        self.assertEqual([item["title"] for item in items], ["team/different-agent"])
        self.assertIn("5", " ".join(logs.output))

    def test_all_filtered_still_returns_successful_empty_result(self):
        copies = [repo(f"owner-{i}", "same-agent", "Identical AI agent project",
                       f"2026-11-13T16:4{i}:00Z") for i in range(5)]
        with self.assertLogs("radar.discovery", level="WARNING"):
            self.assertEqual(self.parse(copies), [])

    def test_filtered_empty_page_is_reported_as_fetched(self):
        copies = [repo(f"owner-{i}", "same-agent", "Identical AI agent project",
                       f"2026-11-13T16:4{i}:00Z") for i in range(5)]
        body = json.dumps({"items": copies})
        source = SOURCE | {"url": "https://api.github.com/search/repositories"}
        job = (source, "coverage", lambda text: parse_github(text, source, OBSERVED))
        with patch.object(pipeline, "_jobs", return_value=[job]), \
             patch.object(youtube, "collect", return_value=([], [])), \
             self.assertLogs("radar.discovery", level="WARNING"):
            snapshot = pipeline.build(fetch=lambda url, **kwargs: body)
        record = snapshot["sources"][0]
        self.assertTrue(record["ok"])
        self.assertEqual(record["count"], 0)
        self.assertIsNone(record["error"])

    def test_common_name_and_separated_creation_survive(self):
        rows = [repo("one", "chatbot", "A local AI assistant", "2026-11-13T16:40:00Z"),
                repo("two", "chatbot", "An AI sales helper", "2026-11-13T16:41:00Z")]
        rows += [repo(f"team-{i}", "shared-tool", "Same AI code description",
                      f"2026-11-{i + 1:02d}T16:40:00Z") for i in range(5)]
        self.assertEqual(len(self.parse(rows)), 7)

    def test_other_github_sources_keep_their_existing_contract(self):
        copies = [repo(f"owner-{i}", "same-agent", "Identical AI agent project",
                       f"2026-11-13T16:4{i}:00Z") for i in range(5)]
        self.assertEqual(len(self.parse(copies, SOURCE | {"id": "other-github"})), 5)

    def test_github_ai_keeps_first_twenty_survivors_in_order(self):
        rows = [repo(f"owner-{i}", f"project-{i}", f"Distinct AI project {i}",
                     "2026-11-13T16:40:00Z") for i in range(30)]
        items = self.parse(rows)
        self.assertEqual([item["title"] for item in items],
                         [f"owner-{i}/project-{i}" for i in range(20)])

    def test_search_fetches_one_full_page(self):
        from datetime import datetime, timezone
        from urllib.parse import parse_qs, urlparse

        source = next(row for row in sources(datetime(2026, 11, 14, tzinfo=timezone.utc))
                      if row["id"] == "github-ai")
        self.assertEqual(parse_qs(urlparse(source["url"]).query)["per_page"], ["100"])

    def test_saved_search_pages_preserve_real_repositories(self):
        expected = {
            "github-ai-search-sample-20261114.json": [
                "agentes-chat/agentes-chat", "Dodaios/ste80-humanizer"],
            "github-ai-search-sample-20261114-p2.json": ["hitkeeen/blender-ai-mcp-addon"],
            "github-ai-search-sample-20261114-p3.json": [
                "thecoderrrer/ai_manus", "thecoderrrer/manus-ai", "huawei-csl/MACaQ"],
        }
        if not all((SAMPLES / name).exists() for name in expected):
            self.skipTest("Coordinator's local GitHub search samples are unavailable")
        for filename, survivors in expected.items():
            with self.subTest(filename=filename):
                with self.assertLogs("radar.discovery", level="WARNING"):
                    items = parse_github((SAMPLES / filename).read_text(encoding="utf-8"), SOURCE, OBSERVED)
                self.assertEqual([item["title"] for item in items], survivors)

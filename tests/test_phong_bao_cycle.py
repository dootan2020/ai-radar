"""Offline scheduled-cycle behavior with the phase 0 fixture runner."""

import json
from io import BytesIO
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from phong_bao.cycle import cycle, cycle_lock, fetch_snapshot
from phong_bao.__main__ import main
from phong_bao.newsroom import FixtureArticles
from phong_bao.registry import load_registry
from phong_bao.runner import FixtureRunner


FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CountingRunner(FixtureRunner):
    def __init__(self):
        super().__init__(fixture("responses.json"))
        self.calls = []

    def run(self, desk, rows, provider, instruction):
        self.calls.append((desk, [row["id"] for row in rows]))
        return super().run(desk, rows, provider, instruction)


class CycleTests(unittest.TestCase):
    def test_snapshot_uses_browser_user_agent_and_falls_back_only_on_intake_404(self):
        seen = []
        def fake_open(request, timeout):
            seen.append((request.full_url, request.get_header("User-agent"), timeout))
            if request.full_url.endswith("radar-intake.json"):
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            return BytesIO(b'{"stories": []}')

        with patch("phong_bao.cycle.urlopen", side_effect=fake_open):
            self.assertEqual(fetch_snapshot("https://example.org/data/radar-intake.json"), {"stories": []})
        self.assertEqual([row[0] for row in seen], ["https://example.org/data/radar-intake.json",
                                                 "https://example.org/data/radar.json"])
        self.assertTrue(all(row[1].startswith("Mozilla/5.0") and row[2] == 60 for row in seen))

        with patch("phong_bao.cycle.urlopen", side_effect=HTTPError("https://example.org/data/radar-intake.json",
                                                                     403, "Forbidden", {}, None)) as opener:
            with self.assertRaises(HTTPError):
                fetch_snapshot("https://example.org/data/radar-intake.json")
            self.assertEqual(opener.call_count, 1)

    def test_snapshot_falls_back_when_intake_returns_html_with_success_status(self):
        class Response(BytesIO):
            def __init__(self, body, content_type):
                super().__init__(body)
                self.headers = {"Content-Type": content_type}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()

        for body, content_type in ((b"<!doctype html><html>Not found</html>", "text/html"),
                                   (b"<!doctype html><html>Not found</html>", "application/json")):
            with self.subTest(content_type=content_type):
                seen = []
                def fake_open(request, timeout):
                    seen.append(request.full_url)
                    if request.full_url.endswith("radar-intake.json"):
                        return Response(body, content_type)
                    return Response(b'{"stories": []}', "application/json")

                with patch("phong_bao.cycle.urlopen", side_effect=fake_open):
                    self.assertEqual(fetch_snapshot("https://example.org/data/radar-intake.json"), {"stories": []})
                self.assertEqual(seen, ["https://example.org/data/radar-intake.json",
                                        "https://example.org/data/radar.json"])

    def test_cli_passes_custom_snapshot_url(self):
        with patch("phong_bao.__main__.cycle", return_value={"state": "no_new_stories"}) as run_cycle:
            self.assertEqual(main(["cycle", "--snapshot-url", "https://example.org/data/radar-intake.json"]), 0)
        run_cycle.assert_called_once_with(snapshot_url="https://example.org/data/radar-intake.json", since_hours=36)

    def test_only_new_stories_are_decided_and_history_keeps_holds(self):
        snapshot = fixture("snapshot.json")
        first = snapshot["stories"][0]["id"]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "decisions.json"
            path.write_bytes(json.dumps({"schema_version": 1, "generated_at": "2026-10-26T00:00:00Z",
                                         "decisions": [{"id": first, "decision": "hold"}]}).encode())
            runner = CountingRunner()
            args = dict(snapshot_fetcher=lambda: snapshot, decisions_path=path, cycles_dir=base / "cycles",
                        discovery=fixture("discovery.json"), tools=load_registry(), runner=runner,
                        articles=FixtureArticles(fixture("articles.json")), since_hours=200)
            start = datetime(2026, 10, 27, 7, tzinfo=timezone.utc)
            status = cycle(**args, now=start)
            self.assertEqual((status["state"], status["new_count"], status["decided_count"]),
                             ("decided", 2, 2))
            self.assertTrue(runner.calls)
            self.assertFalse(any(first in ids for _, ids in runner.calls))
            decisions = json.loads(path.read_bytes())["decisions"]
            self.assertEqual(len(decisions), 3)
            self.assertEqual(decisions[0], {"id": first, "decision": "hold"})
            dated = base / "cycles" / "20261027T070000Z" / "quyet-dinh.json"
            self.assertEqual(len(json.loads(dated.read_bytes())["decisions"]), 2)
            calls = len(runner.calls)
            later = cycle(**args, now=start + timedelta(minutes=1))
            self.assertEqual((later["state"], later["decided_count"]), ("no_new_stories", 0))
            self.assertEqual(len(runner.calls), calls)
            self.assertEqual(len(json.loads(path.read_bytes())["decisions"]), 3)

    def test_cycle_only_considers_stories_inside_recency_window(self):
        snapshot = fixture("snapshot.json")
        snapshot["stories"][0]["published_at"] = "2026-10-20T00:00:00Z"
        snapshot["stories"][0]["latest_coverage_at"] = "2026-10-25T18:00:00Z"
        snapshot["stories"][1]["published_at"] = "2026-10-27T05:00:00Z"
        snapshot["stories"][1]["latest_coverage_at"] = "2026-10-27T05:00:00Z"
        snapshot["stories"][2]["published_at"] = "2026-10-25T00:00:00Z"
        snapshot["stories"][2]["latest_coverage_at"] = "2026-10-25T00:00:00Z"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runner = CountingRunner()
            status = cycle(snapshot_fetcher=lambda: snapshot, decisions_path=base / "decisions.json",
                           cycles_dir=base / "cycles", discovery=fixture("discovery.json"),
                           tools=load_registry(), runner=runner,
                           articles=FixtureArticles(fixture("articles.json")),
                           now=datetime(2026, 10, 27, 7, tzinfo=timezone.utc))
        self.assertEqual((status["considered_count"], status["new_count"]), (1, 1))
        self.assertTrue(all("5912801014b750b394c9" not in ids for _, ids in runner.calls))

    def test_overlap_guard_releases_lock_and_dry_lane_records_no_decision(self):
        snapshot = fixture("snapshot.json")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            lock = base / "cycles" / "cycle.lock"
            args = dict(snapshot_fetcher=lambda: snapshot, decisions_path=base / "decisions.json",
                        cycles_dir=base / "cycles", tools=load_registry(),
                        discovery={**fixture("discovery.json"), "commands": ["python", "codex"]},
                        runner=CountingRunner(), since_hours=200)
            with cycle_lock(lock):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    cycle(**args)
            status = cycle(**args, now=datetime(2026, 10, 27, 8, tzinfo=timezone.utc))
            self.assertEqual((status["state"], status["decided_count"]), ("dry_lane", 0))
            self.assertFalse((base / "decisions.json").exists())
            self.assertEqual(json.loads((base / "cycles" / "20261027T080000Z" / "status.json").read_bytes())["state"],
                             "dry_lane")


if __name__ == "__main__":
    unittest.main()

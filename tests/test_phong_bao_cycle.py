"""Offline scheduled-cycle behavior with the phase 0 fixture runner."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phong_bao.cycle import cycle, cycle_lock
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
                        articles=FixtureArticles(fixture("articles.json")))
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

    def test_overlap_guard_releases_lock_and_dry_lane_records_no_decision(self):
        snapshot = fixture("snapshot.json")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            lock = base / "cycles" / "cycle.lock"
            args = dict(snapshot_fetcher=lambda: snapshot, decisions_path=base / "decisions.json",
                        cycles_dir=base / "cycles", tools=load_registry(),
                        discovery={**fixture("discovery.json"), "commands": ["python", "codex"]},
                        runner=CountingRunner())
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

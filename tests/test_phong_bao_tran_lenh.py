"""A model call that hangs costs its own batch, never the rest of the desk.

These tests run the real CLIRunner subprocess path against a stand-in CLI (tests/fixtures/phong-bao/slow-lane.py)
that sleeps far past the per-call cap; no model, network or real boat CLI is called.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from phong_bao import newsroom
from phong_bao.runner import BatchResult, CLIRunner, RunnerError

STUB = str(Path(__file__).parent / "fixtures" / "phong-bao" / "slow-lane.py")
CAP = 2
BUDGET = 20
# Rows this long go one per batch (MAX_BATCH_CHARS), the way the writer sends a few long stories per call.
TEXT = "x" * 40_000


def lane(boat, *extra):
    profile = {"id": boat, "capabilities": ["bien-tap"], "kind": "subscription-boat", "cost_class": "subscription",
               "priority": 10 if boat == "codex" else 20, "monthly_cap_usd": 0, "boat": boat, "runner": "batch-cli",
               "argv": [sys.executable, STUB, *extra, boat], "prompt_transport": "stdin",
               "detect": {"command": boat}}
    if boat == "agy":
        profile["desk_priority"] = {"writer": 5}
    return profile


AGY = lane("agy")
CODEX = lane("codex", "--codex", "--never-hang")


def desk(rows, tools, budget=BUDGET):
    discovery = {"commands": [tool["id"] for tool in tools], "fuel": None}
    started = time.monotonic()
    with patch.object(newsroom, "DEFAULT_CALL_TIMEOUT_SECONDS", CAP, create=True):
        output, events = newsroom._agent_desk("writer", rows, "Return JSON", "bien-tap", tools, discovery, CLIRunner(),
                                              require_success=False, deadline=started + budget)
    return output, events, time.monotonic() - started


class HungCallTest(unittest.TestCase):
    def test_a_hung_call_loses_only_its_own_batch(self):
        rows = [{"id": "s1", "text": TEXT}, {"id": "hang-2", "text": TEXT}, {"id": "s3", "text": TEXT}]
        output, events, elapsed = desk(rows, [AGY])
        self.assertEqual(output["s1"]["lane"], "agy")
        self.assertEqual(output["s3"]["lane"], "agy")
        self.assertTrue(output["hang-2"]["model_failure"])
        failures = [event for event in events if event.get("event")]
        self.assertEqual([(event["event"], event["ids"]) for event in failures], [("failure", ["hang-2"])])
        self.assertIn("timed out", failures[0]["error"])
        self.assertLess(elapsed, BUDGET / 2)

    def test_a_hung_call_retries_on_the_next_lane(self):
        rows = [{"id": "s1", "text": TEXT}, {"id": "hang-2", "text": TEXT}, {"id": "s3", "text": TEXT}]
        output, events, elapsed = desk(rows, [AGY, CODEX])
        self.assertEqual({sid: row.get("lane") for sid, row in output.items()},
                         {"s1": "agy", "hang-2": "codex", "s3": "agy"})
        self.assertEqual([(event["event"], event["provider"], event["ids"]) for event in events if event.get("event")],
                         [("timeout", "agy", ["hang-2"])])
        self.assertLess(elapsed, BUDGET / 2)

    def test_a_timeout_on_the_last_lane_is_not_split_into_more_calls(self):
        # Splitting helps a batch that is too big to answer; a lane that hangs would only hang twice more.
        rows = [{"id": "hang-1"}, {"id": "s2"}]
        output, events, elapsed = desk(rows, [AGY])
        self.assertTrue(output["hang-1"]["model_failure"] and output["s2"]["model_failure"])
        self.assertEqual([event["event"] for event in events if event.get("event")], ["failure"])
        self.assertLess(elapsed, 2 * CAP + 3)


class TimeoutValueTest(unittest.TestCase):
    class Recording(CLIRunner):
        def __init__(self):
            self.timeouts = []

        def run(self, desk, rows, provider, instruction, *, timeout=600):
            self.timeouts.append(timeout)
            return BatchResult([{"id": row["id"]} for row in rows], {})

    def timeouts(self, budget, **options):
        runner = self.Recording()
        newsroom._agent_desk("writer", [{"id": "s1"}], "Return JSON", "bien-tap", [AGY], {"commands": ["agy"], "fuel": None},
                             runner, require_success=False, deadline=time.monotonic() + budget, **options)
        return runner.timeouts

    def test_each_call_waits_for_the_cap_or_the_desk_deadline_whichever_comes_first(self):
        self.assertEqual(self.timeouts(3600), [newsroom.DEFAULT_CALL_TIMEOUT_SECONDS])
        self.assertEqual(self.timeouts(3600, call_timeout=42), [42])
        [near] = self.timeouts(30)
        self.assertLessEqual(near, 30)
        self.assertGreater(near, 25)

    def test_the_cap_reaches_every_desk_from_run_and_rejects_nonpositive_values(self):
        seen = {}

        def reporter(*args, **options):
            seen.update(options)
            raise RuntimeError("stop after the reporter starts")

        story = {"id": "s1", "title": "A title", "url": "https://example.com/a", "published_at": "2026-11-06T00:00:00Z"}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text(json.dumps({"generated_at": "2026-11-06T01:00:00Z", "stories": [story]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "positive"):
                newsroom.run(path, Path(temp) / "job", [], {}, CLIRunner(), call_timeout_seconds=0)
            with patch.object(newsroom, "_reporter", side_effect=reporter):
                with self.assertRaisesRegex(RuntimeError, "reporter starts"):
                    newsroom.run(path, Path(temp) / "job", [], {}, CLIRunner(), through="reporter",
                                 call_timeout_seconds=7)
        self.assertEqual(seen.get("call_timeout"), 7)


def alive(pid):
    if os.name == "nt":
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True,
                                 text=True, timeout=30).stdout
        return f'"{pid}"' in listing
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class ProcessTreeTest(unittest.TestCase):
    HOLDER = str(Path(__file__).parent / "fixtures" / "phong-bao" / "pipe-holder.py")
    GRANDCHILD_SECONDS = 45

    def test_a_timeout_ends_a_grandchild_that_holds_the_pipes(self):
        # Killing only the direct child leaves the grandchild holding stdout/stderr, and the call would wait
        # GRANDCHILD_SECONDS for it instead of returning at the cap.
        with tempfile.TemporaryDirectory() as temp:
            pid_file = Path(temp) / "pids.txt"
            provider = {**AGY, "argv": [sys.executable, self.HOLDER, str(pid_file), str(self.GRANDCHILD_SECONDS)]}
            started = time.monotonic()
            with self.assertRaises(RunnerError) as caught:
                CLIRunner().run("writer", [{"id": "s1"}], provider, "Return JSON", timeout=CAP)
            elapsed = time.monotonic() - started
            pids = [int(line) for line in pid_file.read_text(encoding="utf-8").split()]
        self.assertIsInstance(caught.exception.__cause__, subprocess.TimeoutExpired)
        self.assertEqual(len(pids), 2)
        self.assertLess(elapsed, CAP + 8)
        self.assertEqual([pid for pid in pids if alive(pid)], [])


if __name__ == "__main__":
    unittest.main()

"""A desk's model calls run side by side and are recorded exactly as if they had run one after another."""

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from phong_bao import newsroom
from phong_bao.newsroom import DEFAULT_DESK_CONCURRENCY, _agent_desk, desk_concurrency
from phong_bao.registry import load_registry
from phong_bao.runner import AdmissionError, BatchResult, CLIRunner, RunnerError

DISCOVERY = {"commands": ["agy", "codex"], "fuel": "fixture: boats available"}


def lane(tool_id, priority, **extra):
    # stdin transport: the batch limit is the row count, so batch_size=1 makes one call per story.
    return {"id": tool_id, "boat": tool_id, "capabilities": ["bien-tap"], "kind": "subscription-boat",
            "priority": priority, "runner": "batch-cli", "prompt_transport": "stdin",
            "detect": {"command": tool_id}, **extra}


AGY, CODEX = lane("agy", 5), lane("codex", 10)
STORIES = [{"id": f"s{index}", "text": f"story {index}"} for index in range(1, 7)]


def reply(row, provider):
    return {"id": row["id"], "summary": f"{row['id']} by {provider['id']}"}


class ScriptedRunner(CLIRunner):
    """A CLI stand-in: each call sleeps its scripted time, or as long as the timeout allows and then times out."""

    def __init__(self, delays=None, fail=(), admission=()):
        self.delays, self.fail, self.admission = delays or {}, set(fail), set(admission)
        self.lock = threading.Lock()
        self.calls, self.open, self.most_open, self.timeouts = [], {}, {}, []

    def run(self, desk, rows, provider, instruction, *, timeout=600):
        ids = tuple(row["id"] for row in rows)
        name = provider["id"]
        with self.lock:
            self.calls.append((name, ids))
            self.timeouts.append(timeout)
            self.open[name] = self.open.get(name, 0) + 1
            self.most_open[name] = max(self.most_open.get(name, 0), self.open[name])
        try:
            if any(sid in self.admission for sid in ids):
                raise AdmissionError(f"{name} admission stopped (sign-in required: sign in to)")
            delay = max((self.delays.get((name, sid), self.delays.get(sid, 0.0)) for sid in ids), default=0.0)
            if delay > timeout:
                # A real timed-out CLI returns after its timeout plus the time to end its process tree.
                time.sleep(timeout + 0.05)
                raise RunnerError(f"{name} CLI unavailable or timed out") from subprocess.TimeoutExpired(name, timeout)
            time.sleep(delay)
            if (name, ids) in self.fail or any((name, sid) in self.fail for sid in ids):
                raise RunnerError(f"{name} CLI exit 1")
            rows_out = [reply(row, provider) for row in rows]
            return BatchResult(rows_out, {"input_tokens": 10 * len(rows), "output_tokens": 5 * len(rows),
                                          "tokens_per_story": 15.0, "source": "cli", "batch_size": len(rows)})
        finally:
            with self.lock:
                self.open[name] -= 1


def desk(runner, *, concurrency, tools=(AGY, CODEX), stories=STORIES, raw_dir=None, deadline=None, batch_size=1,
         record_as=None):
    return _agent_desk("writer", list(stories), "Return JSON", "bien-tap", list(tools), DISCOVERY, runner,
                       raw_dir=raw_dir, require_success=False, deadline=deadline, batch_size=batch_size,
                       concurrency=concurrency, record_as=record_as)


def raw_files(directory):
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path(directory).iterdir())}


class ParallelDeskTest(unittest.TestCase):
    def test_calls_overlap_so_wall_time_follows_the_longest_wave_not_the_sum(self):
        runner = ScriptedRunner(delays={story["id"]: 0.4 for story in STORIES})
        started = time.monotonic()
        output, events = desk(runner, concurrency=3, tools=(AGY,))
        elapsed = time.monotonic() - started
        self.assertEqual(len(runner.calls), 6)
        self.assertEqual(runner.most_open["agy"], 3)
        # Six 0.4 s calls in turn take 2.4 s; three at a time take two waves, about 0.8 s.
        self.assertLess(elapsed, 1.6)
        self.assertEqual(list(output), [story["id"] for story in STORIES])
        self.assertTrue(all(row["provider"] == "agy" for row in output.values()))

    def test_results_files_and_events_match_the_serial_path(self):
        # Later stories finish first, s2 falls back to codex, and a two-story batch fails on both lanes and splits.
        delays = {"s1": 0.3, "s2": 0.25, "s3": 0.2, "s4": 0.15, "s5": 0.1, "s6": 0.05}
        fail = {("agy", "s2"), ("agy", ("s5", "s6")), ("codex", ("s5", "s6"))}
        results = {}
        for workers in (1, 3):
            with tempfile.TemporaryDirectory() as directory:
                raw = Path(directory) / "raw"
                raw.mkdir()
                # An earlier pass of the same desk already wrote two files; numbering continues after them.
                for number in (1, 2):
                    (raw / f"writer-{number}.json").write_text("{}\n", encoding="utf-8")
                runner = ScriptedRunner(delays=delays, fail=fail)
                stories = STORIES[:4] + [{"id": "s5", "text": "five"}, {"id": "s6", "text": "six"}]
                # batch_size=2 groups (s1,s2) (s3,s4) (s5,s6); s2's group fails on agy as a whole.
                output, events = desk(runner, concurrency=workers, raw_dir=raw, batch_size=2, stories=stories)
                results[workers] = (list(output.items()), events, raw_files(raw))
        self.assertEqual(results[1], results[3])
        output, events, files = results[3]
        self.assertEqual([sid for sid, _ in output], ["s1", "s2", "s3", "s4", "s5", "s6"])
        # s1/s2 on codex, s3/s4, the split, then s5 and s6 alone: files 3 to 7 after the earlier pass's two.
        self.assertEqual(list(files), [f"writer-{number}.json" for number in range(1, 8)])
        self.assertEqual(files["writer-3.json"]["provider"], "codex")
        self.assertEqual(files["writer-5.json"]["event"], "split")
        self.assertEqual([row["id"] for row in files["writer-7.json"]["stories"]], ["s6"])

    def test_a_failing_or_slow_batch_costs_only_its_own_stories(self):
        runner = ScriptedRunner(delays={"s1": 0.05, "s2": 30.0, "s3": 0.05, "s4": 0.05},
                                fail={("agy", "s3"), ("codex", "s3")})
        deadline = time.monotonic() + 1.0
        started = time.monotonic()
        output, events = desk(runner, concurrency=3, stories=STORIES[:4], deadline=deadline)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0 + 0.8)
        self.assertEqual(output["s1"]["provider"], "agy")
        self.assertEqual(output["s4"]["provider"], "agy")
        self.assertTrue(output["s2"]["model_failure"])
        self.assertTrue(output["s3"]["model_failure"])
        by_ids = {tuple(event.get("ids", ())): event.get("event") for event in events if "event" in event}
        self.assertEqual(by_ids[("s2",)], "budget_exhausted")
        self.assertEqual(by_ids[("s3",)], "failure")
        # The slow call was given no more than the time left, never the 15-minute cap.
        self.assertTrue(all(timeout <= 1.0 + 0.01 for timeout in runner.timeouts))

    def test_queued_batches_respect_the_deadline(self):
        runner = ScriptedRunner(delays={story["id"]: 0.3 for story in STORIES[:5]})
        deadline = time.monotonic() + 0.45
        started = time.monotonic()
        output, events = desk(runner, concurrency=2, tools=(AGY,), stories=STORIES[:5], deadline=deadline)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.45 + 0.6)
        # Two calls finish, the next two are cut at the deadline, and the fifth is never sent.
        self.assertEqual([sid for sid, row in output.items() if not row.get("model_failure")], ["s1", "s2"])
        self.assertEqual(sorted(ids for _, ids in runner.calls), [("s1",), ("s2",), ("s3",), ("s4",)])
        self.assertEqual([event["event"] for event in events if "event" in event], ["budget_exhausted"] * 3)
        self.assertEqual(list(output), ["s1", "s2", "s3", "s4", "s5"])

    def test_an_admission_stop_keeps_earlier_batches_and_starts_no_later_one(self):
        runner = ScriptedRunner(delays={"s1": 0.3}, admission={"s2"})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AdmissionError):
                desk(runner, concurrency=2, tools=(AGY,), stories=STORIES[:4], raw_dir=directory)
            files = raw_files(directory)
        self.assertEqual(sorted(ids for _, ids in runner.calls), [("s1",), ("s2",)])
        self.assertEqual(list(files), ["writer-1.json"])
        self.assertEqual([row["id"] for row in files["writer-1.json"]["stories"]], ["s1"])

    def test_a_lane_capped_at_one_call_never_runs_two(self):
        runner = ScriptedRunner(delays={story["id"]: 0.1 for story in STORIES})
        output, _ = desk(runner, concurrency=3, tools=(lane("codex", 10, max_concurrent_calls=1),))
        self.assertEqual(runner.most_open["codex"], 1)
        self.assertEqual(len(output), 6)

    def test_the_codex_profile_runs_one_call_at_a_time(self):
        codex = next(tool for tool in load_registry() if tool["id"] == "codex")
        self.assertEqual(codex["max_concurrent_calls"], 1)

    def test_one_worker_runs_every_call_in_turn(self):
        runner = ScriptedRunner(delays={story["id"]: 0.02 for story in STORIES})
        desk(runner, concurrency=1, tools=(AGY,))
        self.assertEqual(runner.most_open["agy"], 1)
        self.assertEqual([ids for _, ids in runner.calls], [(story["id"],) for story in STORIES])

    def test_concurrency_setting(self):
        self.assertEqual(DEFAULT_DESK_CONCURRENCY, 3)
        self.assertEqual(desk_concurrency({}), 3)
        self.assertEqual(desk_concurrency({newsroom.DESK_CONCURRENCY_ENV: "1"}), 1)
        self.assertEqual(desk_concurrency({newsroom.DESK_CONCURRENCY_ENV: " 4 "}), 4)
        for bad in ("0", "-2", "many", ""):
            self.assertEqual(desk_concurrency({newsroom.DESK_CONCURRENCY_ENV: bad}), 3)


class RegistryLaneCapTest(unittest.TestCase):
    def test_invalid_lane_cap_is_rejected(self):
        source = (Path(newsroom.__file__).resolve().parents[1] / "phong-bao" / "cong-cu" / "codex.toml").read_text(
            encoding="utf-8")
        for bad in ("0", "true", '"2"'):
            with tempfile.TemporaryDirectory() as directory:
                text = source.replace("max_concurrent_calls = 1", f"max_concurrent_calls = {bad}")
                (Path(directory) / "codex.toml").write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "max_concurrent_calls"):
                    load_registry(directory)


if __name__ == "__main__":
    unittest.main()

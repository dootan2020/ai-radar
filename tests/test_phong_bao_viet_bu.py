"""A story the writer failed on gets its prose in a later cycle, from the desk outputs its own cycle stored."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import phong_bao.cycle as cycle_module
import phong_bao.newsroom as newsroom
from phong_bao.cycle import cycle
from phong_bao.newsroom import run
from phong_bao.registry import load_registry
from phong_bao.runner import FixtureRunner
from test_phong_bao_writer import DISCOVERY, NOW, PROSE, SID, articles, desks, story

LATER = NOW + timedelta(hours=4)
STORY_DESKS = ("intake", "reporter", "editor", "checker")


def stamp(moment):
    return moment.strftime("%Y%m%dT%H%M%SZ")


def prose(sid):
    return {**deepcopy(PROSE), "id": sid}


class Lane(FixtureRunner):
    """A writer lane on a fake clock: every story it is sent takes 90 seconds."""

    SECONDS_PER_STORY = 90

    def __init__(self, replies, clock=None):
        super().__init__(replies)
        self.clock = clock if clock is not None else [0.0]
        self.calls = []

    def monotonic(self):
        return self.clock[0]

    def run(self, desk, rows, provider, instruction):
        self.calls.append((desk, [row["id"] for row in rows]))
        self.clock[0] += self.SECONDS_PER_STORY * len(rows)
        return super().run(desk, rows, provider, instruction)

    def sent(self, desk="writer"):
        return [sid for name, ids in self.calls if name == desk for sid in ids]


class WriterRetryTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.decisions_path = self.base / "decisions.json"
        self.cycles = self.base / "cycles"
        self.stories = {}
        self.clock = [0.0]
        patcher = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def stored_cycle(self, moment, specs, written=()):
        """Leave the job a real cycle leaves at `moment`: earlier desks done, the writer failing, the chief deciding.

        specs maps story ID to (hours old at `moment`, verified claim count); `written` lists stories whose
        writer call succeeds.
        """
        job = self.cycles / stamp(moment) / "job"
        job.mkdir(parents=True)
        rows = [{**story(), "id": sid, "published_at": (moment - timedelta(hours=hours)).isoformat()}
                for sid, (hours, _) in specs.items()]
        self.stories.update({row["id"]: row for row in rows})
        input_path = self.base / f"input-{stamp(moment)}.json"
        input_path.write_text(json.dumps({"generated_at": moment.isoformat(), "stories": rows}), encoding="utf-8")
        digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
        intake, reporter, editor, checker = desks()
        done = {"intake": intake, "reporter": reporter, "editor": editor, "checker": checker}
        for desk, value in done.items():
            stored = {}
            for sid, (_, claims) in specs.items():
                stored[sid] = {**deepcopy(value[SID]), "id": sid}
                if desk == "checker":
                    stored[sid]["supported_claims"] = stored[sid]["supported_claims"][:claims]
            (job / f"{desk}.json").write_text(json.dumps(stored), encoding="utf-8")
        (job / "status.json").write_text(json.dumps({
            "input": str(input_path.resolve()), "input_sha256": digest, "corpus_sha256": digest,
            "desks": {desk: {"state": "done"} for desk in done}}), encoding="utf-8")
        lane = Lane({"writer": {sid: prose(sid) for sid in written}})
        run(input_path, job, self.tools, DISCOVERY, lane, articles=articles())
        # The cycle's input lives in a temporary directory that is gone by the next cycle.
        input_path.unlink()
        decisions = json.loads((job / "quyet-dinh.json").read_text(encoding="utf-8"))["decisions"]
        old = self.decisions()["decisions"] if self.decisions_path.exists() else []
        self.write_decisions(old + decisions)
        return json.loads((job / "writer.json").read_text(encoding="utf-8"))

    def decisions(self):
        return json.loads(self.decisions_path.read_text(encoding="utf-8"))

    def by_id(self):
        return {row["id"]: row for row in self.decisions()["decisions"]}

    def write_decisions(self, rows):
        self.decisions_path.write_text(json.dumps({"schema_version": 1, "generated_at": NOW.isoformat(),
                                                   "decisions": rows}), encoding="utf-8")

    def next_cycle(self, moment, lane, *, new=(), **options):
        snapshot = {"generated_at": moment.isoformat(), "stories": list(self.stories.values()) + list(new)}
        with patch.object(newsroom, "BATCH_SIZE", 3), patch.object(newsroom.time, "monotonic",
                                                                   side_effect=lane.monotonic):
            return cycle(snapshot_fetcher=lambda: snapshot, decisions_path=self.decisions_path,
                         cycles_dir=self.cycles, discovery=DISCOVERY, tools=self.tools, runner=lane,
                         articles=articles(), since_hours=200, now=moment, **options)

    def test_a_story_the_writer_failed_on_gets_prose_in_the_next_cycle_from_its_stored_desks(self):
        writer = self.stored_cycle(NOW, {"failed": (2, 2)})
        self.assertEqual(writer["failed"]["reason"], "writer_model_failure")
        before = self.by_id()["failed"]
        self.assertEqual((before["decision"], before["summary"]), ("publish", "claims"))

        lane = Lane({"writer": {"failed": prose("failed")}})
        status = self.next_cycle(LATER, lane)

        # Only the writer runs again: no intake, reporter, editor or checker call.
        self.assertEqual([desk for desk, _ in lane.calls], ["writer"])
        self.assertEqual(lane.sent(), ["failed"])
        self.assertEqual(status["state"], "no_new_stories")
        self.assertEqual(status["writer_retry"], {"candidates": 1, "sent": 1, "budget_cut": 0, "written": 1})
        after = self.by_id()["failed"]
        self.assertEqual(after["summary"], "written")
        self.assertEqual(after["written_by"], "nguoi-viet")
        self.assertEqual(len(after["key_points"]), 4)
        self.assertTrue(after["editorial_headline_vi"])
        # The earlier publication decision is kept as it was; only prose fields are added.
        prose_fields = {"summary", "written_by", "key_points", "editorial_headline_vi", "summary_sources",
                        "summary_limitations", "key_points_prompt_version"}
        self.assertEqual({key: value for key, value in after.items() if key not in prose_fields},
                         {key: value for key, value in before.items() if key not in prose_fields})
        record = self.cycles / stamp(LATER) / "viet-bu"
        self.assertEqual(json.loads((record / "status.json").read_text(encoding="utf-8"))["cycles"],
                         {"failed": stamp(NOW)})
        self.assertTrue(json.loads((record / "writer.json").read_text(encoding="utf-8"))["failed"]["written"])

        # A written story is never sent again.
        again = Lane({"writer": {"failed": prose("failed")}})
        self.next_cycle(LATER + timedelta(hours=4), again)
        self.assertEqual(again.calls, [])

    def test_written_held_and_summary_less_stories_are_not_sent_again(self):
        self.stored_cycle(NOW, {"written": (2, 2), "held": (2, 2), "no-summary": (2, 1), "failed": (2, 2)},
                          written=("written",))
        rows = self.by_id()
        self.assertEqual(rows["written"]["summary"], "written")
        self.assertEqual(rows["no-summary"]["summary"], "none")
        # A later step (the paywall hold) turned this publication into a hold.
        self.write_decisions([{**row, "decision": "hold"} if row["id"] == "held" else row for row in rows.values()])
        lane = Lane({"writer": {sid: prose(sid) for sid in rows}})
        status = self.next_cycle(LATER, lane)
        self.assertEqual(lane.sent(), ["failed"])
        self.assertEqual(status["writer_retry"]["written"], 1)
        after = self.by_id()
        self.assertEqual(after["held"], {**rows["held"], "decision": "hold"})
        self.assertEqual(after["no-summary"], rows["no-summary"])

    def test_a_story_past_the_writer_window_is_not_sent_again(self):
        self.stored_cycle(NOW, {"old": (46, 2), "fresh": (2, 2)})
        lane = Lane({"writer": {"old": prose("old"), "fresh": prose("fresh")}})
        # Four hours later "old" is 50 hours old, outside the 48-hour writer window.
        self.next_cycle(LATER, lane)
        self.assertEqual(lane.sent(), ["fresh"])
        self.assertEqual(self.by_id()["old"]["summary"], "claims")

    def test_a_failed_rewrite_counts_as_a_writer_failure(self):
        self.stored_cycle(NOW, {"rewrite": (2, 2)})
        row = json.loads((self.cycles / stamp(NOW) / "job" / "writer.json").read_text(encoding="utf-8"))["rewrite"]
        row.update(reason="paragraph_roles", invalid_response=True,
                   rewrite={"roles": ["development"], "result": "rewrite_model_failure"})
        (self.cycles / stamp(NOW) / "job" / "writer.json").write_text(json.dumps({"rewrite": row}), encoding="utf-8")
        lane = Lane({"writer": {"rewrite": prose("rewrite")}})
        self.next_cycle(LATER, lane)
        self.assertEqual(lane.sent(), ["rewrite"])
        self.assertEqual(self.by_id()["rewrite"]["summary"], "written")

    def test_retries_only_use_the_writer_budget_the_new_stories_left(self):
        failed = [f"failed-{index}" for index in range(6)]
        self.stored_cycle(NOW, {sid: (2, 2) for sid in failed})
        lane = Lane({"writer": {sid: prose(sid) for sid in failed}})
        order = []
        new_story = {**story(), "id": "new-story", "published_at": LATER.isoformat()}

        def new_story_run(input_path, job, *args, **kwargs):
            # The cycle's own stories go first and their writer spends 48 of its 50 minutes.
            order.append("new stories")
            lane.clock[0] += 48 * 60
            Path(job).mkdir(parents=True, exist_ok=True)
            decision = {**self.by_id()[failed[0]], "id": "new-story"}
            (Path(job) / "quyet-dinh.json").write_text(json.dumps({"decisions": [decision]}), encoding="utf-8")
            return {"desks": {"writer": {"state": "done", "seconds": 48 * 60}}}

        with patch.object(cycle_module, "run", side_effect=new_story_run):
            status = self.next_cycle(LATER, lane, new=[new_story])
        self.assertEqual(status["decided_count"], 1)
        self.assertEqual(order, ["new stories"])
        # One call of three fits the two minutes left; the next would start past the writer budget.
        self.assertEqual(status["writer_retry"], {"candidates": 6, "sent": 3, "budget_cut": 3, "written": 3})
        self.assertIn("new-story", self.by_id())

        # A retry cut before its call is not an attempt: the next cycle sends the other three.
        later = Lane({"writer": {sid: prose(sid) for sid in failed}})
        status = self.next_cycle(LATER + timedelta(hours=4), later)
        self.assertEqual(status["writer_retry"]["written"], 3)
        self.assertTrue(all(self.by_id()[sid]["summary"] == "written" for sid in failed))

    def test_a_cycle_whose_new_stories_spent_the_writer_budget_sends_no_retry(self):
        self.stored_cycle(NOW, {"failed": (2, 2)})
        lane = Lane({"writer": {"failed": prose("failed")}})
        new_story = {**story(), "id": "new-story", "published_at": LATER.isoformat()}

        def new_story_run(input_path, job, *args, **kwargs):
            lane.clock[0] += 50 * 60
            Path(job).mkdir(parents=True, exist_ok=True)
            decision = {**self.by_id()["failed"], "id": "new-story"}
            (Path(job) / "quyet-dinh.json").write_text(json.dumps({"decisions": [decision]}), encoding="utf-8")
            return {"desks": {"writer": {"state": "done", "seconds": 50 * 60}}}

        with patch.object(cycle_module, "run", side_effect=new_story_run):
            status = self.next_cycle(LATER, lane, new=[new_story])
        self.assertEqual(lane.calls, [])
        self.assertEqual(status["writer_retry"], {"candidates": 1, "sent": 0, "budget_cut": 1, "written": 0})
        self.assertEqual(self.by_id()["failed"]["summary"], "claims")

    def test_at_most_the_retry_limit_is_sent_per_cycle_newest_first(self):
        limit = cycle_module.WRITER_RETRY_LIMIT
        specs = {f"failed-{index:02d}": (2 + index, 2) for index in range(limit + 2)}
        self.stored_cycle(NOW, specs)
        lane = Lane({"writer": {sid: prose(sid) for sid in specs}})
        status = self.next_cycle(LATER, lane)
        self.assertEqual(status["writer_retry"]["candidates"], limit)
        self.assertEqual(sorted(lane.sent()), sorted(specs)[:limit])

    def test_a_retry_that_raises_keeps_the_cycle_and_its_decisions(self):
        self.stored_cycle(NOW, {"failed": (2, 2)})

        class BrokenLane(Lane):
            def run(self, desk, rows, provider, instruction):
                raise ValueError("lane crashed")

        status = self.next_cycle(LATER, BrokenLane({}))
        self.assertEqual(status["state"], "no_new_stories")
        self.assertIn("lane crashed", status["writer_retry"]["error"])
        self.assertEqual(self.by_id()["failed"]["summary"], "claims")
        self.assertEqual(json.loads((self.cycles / stamp(LATER) / "status.json").read_text(encoding="utf-8")),
                         status)

    def test_a_story_that_keeps_failing_stops_after_two_retries(self):
        self.stored_cycle(NOW, {"stuck": (2, 2)})
        for hours in (4, 8):
            lane = Lane({})
            status = self.next_cycle(NOW + timedelta(hours=hours), lane)
            # A failed call moves to the next writer lane, so the story can reach two lanes in one attempt.
            self.assertEqual(set(lane.sent()), {"stuck"})
            self.assertEqual(status["writer_retry"]["written"], 0)
        lane = Lane({})
        status = self.next_cycle(NOW + timedelta(hours=12), lane)
        self.assertEqual(lane.calls, [])
        self.assertNotIn("writer_retry", status)


if __name__ == "__main__":
    unittest.main()

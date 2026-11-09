"""Offline one-off backfill checks against stored newsroom cycle evidence."""

from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

from phong_bao.bu_cham import bu_cham
from phong_bao.__main__ import main
from phong_bao.cycle import cycle, cycle_lock
from phong_bao.registry import load_registry
from phong_bao.runner import FixtureRunner
from radar.newsroom_decisions import desk_summary
from tests.test_phong_bao_writer import DISCOVERY, EXAMPLE, PROSE, desks, story


WHEN = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def reply(sid, score=9):
    return {"id": sid, "questions": {key: {"source_answer": "Source says this.",
                                        "summary_answer": "Summary says this.", "score": score}
                                       for key in ("what", "why", "notable", "meaning")},
            "hard_errors": [], "findings": []}


class BackfillTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.cycles = self.base / "cycles"
        self.decisions = self.base / "decisions.json"
        self.job = self.cycles / "20261027T120000Z" / "job"
        self.job.mkdir(parents=True)
        self.tools = load_registry()
        self.rows = []
        self.writers = {}
        self.intake, self.reporter, self.editor, _ = desks()
        self.intake.clear()
        self.reporter.clear()
        self.editor.clear()

    def add(self, sid, *, written=False, held=False, summary=None):
        url = EXAMPLE["url"] + "?" + sid
        self.intake[sid] = {"id": sid, "pass": True}
        self.reporter[sid] = {"id": sid, "readable": True, "selected_url": url,
                              "source_text": "\n".join(EXAMPLE["paragraphs"])}
        self.editor[sid] = {"id": sid, "news": True, "subject": EXAMPLE["title"]}
        source = {"id": "outlet", "role": "outlet", "url": url, "publisher": EXAMPLE["publisher"],
                  "body_complete": True, "paragraphs": [{"id": f"outlet:p{i:03d}", "text": p}
                                                         for i, p in enumerate(EXAMPLE["paragraphs"], 1)]}
        if written:
            prose = {"written": True, "writer_sources": [source], "writer_boats": ["agy"],
                     "key_points": ["Một.", "Hai.", "Ba."], "editorial_headline_vi": "Tiêu đề"}
            decision = {"id": sid, "decision": "hold" if held else "publish", "summary": "written",
                        "written_by": "nguoi-viet", "key_points": prose["key_points"],
                        "editorial_headline_vi": prose["editorial_headline_vi"],
                        "summary_sources": [{"url": url}], "summary_limitations": [],
                        "key_points_prompt_version": "summary-vi-7-bullets", "score": None}
        else:
            prose = {"written": False, "writer_sources": [source], "reason": "writer_model_failure"}
            decision = {"id": sid, "decision": "hold" if held else "publish", "summary": summary or "claims"}
        self.writers[sid] = prose
        self.rows.append(decision)

    def save(self):
        for name, rows in (("writer", self.writers), ("intake", self.intake),
                           ("reporter", self.reporter), ("editor", self.editor)):
            (self.job / f"{name}.json").write_bytes((json.dumps(rows) + "\n").encode())
        self.decisions.write_bytes((json.dumps({"schema_version": 1, "decisions": self.rows}) + "\n").encode())

    def run_backfill(self, replies=None, **kwargs):
        return bu_cham(self.decisions, self.cycles, tools=self.tools, discovery=DISCOVERY,
                       runner=FixtureRunner(replies or {}), now=datetime(2026, 11, 9, 8, tzinfo=timezone.utc),
                       **kwargs)

    def current(self, sid):
        return next(row for row in json.loads(self.decisions.read_text())["decisions"] if row["id"] == sid)

    def test_dry_run_counts_and_reasons_without_writing(self):
        self.add("score", written=True)
        self.add("write")
        self.add("held", written=True, held=True)
        self.add("none", summary="none")
        self.save()
        before = self.decisions.read_bytes()
        result = self.run_backfill()
        self.assertEqual(result["candidates"], {"score": 1, "write": 1})
        self.assertEqual((result["newest"], result["oldest"]), ("2026-10-27", "2026-10-27"))
        self.assertEqual(result["excluded"]["held"], 1)
        self.assertEqual(result["excluded"]["summary none"], 1)
        self.assertEqual(self.decisions.read_bytes(), before)
        self.assertEqual(list(self.cycles.glob("*/viet-bu")), [])
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["bu-cham", "--decisions", str(self.decisions), "--cycles", str(self.cycles)]), 0)
        self.assertIn("score            1", output.getvalue())
        self.assertIn("summary none", output.getvalue())

    def test_score_passes_and_failed_score_stays_hidden(self):
        self.add("passes", written=True)
        self.add("fails", written=True)
        self.save()
        result = self.run_backfill({"rescorer": {"passes": reply("passes"),
                                                   "fails": reply("fails", score=5)}}, execute=True)
        self.assertEqual(result["results"][0]["score_candidates"], 2)
        self.assertIsNotNone(desk_summary(self.current("passes")))
        self.assertIsNone(desk_summary(self.current("fails")))
        self.assertEqual(len(list(self.cycles.glob("*/viet-bu/status.json"))), 1)
        again = self.run_backfill()
        self.assertEqual(again["excluded"]["already scored and failed"], 1)
        self.assertEqual(again["selected"], 0)

    def test_score_precedes_write_and_limit_is_across_modes(self):
        self.add("score", written=True)
        self.add("write")
        self.save()
        limited = self.run_backfill(limit=1)
        self.assertEqual((limited["candidates"], limited["selected"]), ({"score": 1, "write": 1}, 1))
        result = self.run_backfill({"rescorer": {"score": reply("score")}}, limit=1, execute=True)
        self.assertEqual([row["mode"] for row in result["results"]], ["score"])
        self.assertEqual(self.current("write")["summary"], "claims")

    def test_unwritten_story_is_written_from_stored_source(self):
        self.add("write")
        self.save()
        new_prose = deepcopy(PROSE)
        new_prose["id"] = "write"
        result = self.run_backfill({"writer": {"write": new_prose},
                                    "scorer": {"write": reply("write")}}, execute=True)
        self.assertEqual(result["results"][0]["written"], 1)
        self.assertIsNotNone(desk_summary(self.current("write")))

    def test_held_story_never_runs_and_lock_refuses_overlap(self):
        self.add("held", written=True, held=True)
        self.add("score", written=True)
        self.save()
        with cycle_lock(self.cycles / "cycle.lock"):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                self.run_backfill(execute=True)
        self.assertEqual(self.current("held")["decision"], "hold")
        result = self.run_backfill({"rescorer": {"score": reply("score")}}, execute=True)
        self.assertEqual(result["selected"], 1)
        self.assertIsNone(desk_summary(self.current("held")))

    def test_regular_cycle_keeps_its_writer_window(self):
        self.add("old", written=True)
        self.save()
        old_story = {**story(), "id": "old", "published_at": WHEN.isoformat()}
        status = cycle(snapshot_fetcher=lambda: {"generated_at": "2026-11-09T08:00:00Z", "stories": [old_story]},
                       decisions_path=self.decisions, cycles_dir=self.cycles, tools=self.tools,
                       discovery=DISCOVERY, runner=FixtureRunner({}),
                       now=datetime(2026, 11, 9, 8, tzinfo=timezone.utc))
        self.assertNotIn("writer_retry", status)


if __name__ == "__main__":
    unittest.main()

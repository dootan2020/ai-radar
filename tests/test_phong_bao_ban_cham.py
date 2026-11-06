"""The scoring desk ("bàn chấm"): no story reaches readers unless a scorer on another boat passed its prose."""

from copy import deepcopy
from datetime import timedelta
import json
import subprocess
import unittest
from unittest.mock import patch

import phong_bao.cycle as cycle_module
from phong_bao.contracts import validate_chief_output, validate_writer_output
from phong_bao.newsroom import WRITER_PROMPT, WRITER_REVIEW_PROMPT, _chief, _writer
from phong_bao.registry import load_registry
from phong_bao.runner import AdmissionError, FixtureRunner, RunnerError
from phong_bao.scoring import SCORER_PROMPT, scorer_packet, verdict
from radar.newsroom_decisions import SCORE_THRESHOLD, apply_decisions, prose_digest, score_passed
import test_phong_bao_viet_bu as viet_bu
from test_phong_bao_viet_bu import LATER, Lane, prose, stamp
from test_phong_bao_writer import DISCOVERY, NOW, PROSE, SID, articles, desks, story

QUESTIONS = ("what", "why", "notable", "meaning")
FINDING = {"question": "notable", "problem": "The example gives the frame rate but not that it is one GPU.",
           "fix": "Say the renderer runs at 30 frames per second in 480p on one GPU (outlet:p002)."}
HARD_ERROR = {"kind": "number", "summary_text": "71 giây",
              "explanation": "outlet:p003 gives 71 seconds for both vehicles together, not for each."}


def reply(sid=SID, scores=(9, 9, 9, 8), hard_errors=(), findings=()):
    """A scorer reply: the four reader questions answered from the source and from the Vietnamese, then scored."""
    return {"id": sid, "questions": {name: {"source_answer": f"The source answers {name}.",
                                            "summary_answer": f"The Vietnamese answers {name}.", "score": score}
                                     for name, score in zip(QUESTIONS, scores)},
            "hard_errors": list(hard_errors), "findings": list(findings)}


class Recording(FixtureRunner):
    def __init__(self, replies, fail=None):
        super().__init__(replies)
        self.calls = []
        self.fail = fail or {}

    def run(self, desk, rows, provider, instruction):
        self.calls.append((desk, provider.get("boat"), deepcopy(rows), instruction))
        for key in (desk, (desk, provider.get("boat"))):
            if key in self.fail:
                raise self.fail[key]
        return super().run(desk, rows, provider, instruction)

    def desks(self):
        return [(desk, boat) for desk, boat, _, _ in self.calls]


class ScoringDeskTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        patcher = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, replies, *, discovery=DISCOVERY, fail=None, reviews=None):
        runner = Recording(replies, fail)
        intake, reporter, editor, checker = desks()
        output, usage = _writer([story()], intake, reporter, editor, articles(), self.tools, discovery, runner, NOW,
                                reviews=reviews)
        row = output[SID]
        self.assertTrue(validate_writer_output(row))
        decision = _chief([story()], intake, reporter, editor, checker, NOW, output)[0]
        self.assertTrue(validate_chief_output(decision))
        return row, decision, runner, usage

    def shown(self, decision):
        """Story IDs a site build shows from this decision row (every reader file derives from these)."""
        payload = {"stories": [story()], "sections": {"today": [SID]}}
        result = apply_decisions(payload, {"decisions": [decision]})
        self.assertEqual(result["sections"]["today"], [row["id"] for row in result["stories"]])
        return [row["id"] for row in result["stories"]]

    def test_a_passing_verdict_from_another_boat_publishes_the_prose(self):
        row, decision, runner, _ = self.write({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply()}})
        self.assertEqual(runner.desks(), [("writer", "agy"), ("scorer", "codex")])
        self.assertEqual(runner.calls[1][3], SCORER_PROMPT)
        packet = runner.calls[1][2][0]
        # The scorer reads the source paragraphs the writer read and exactly the text a reader sees.
        self.assertEqual([p["id"] for p in packet["sources"][0]["paragraphs"]][:2], ["outlet:p001", "outlet:p002"])
        self.assertEqual(packet["headline_vi"], row["editorial_headline_vi"])
        self.assertEqual(packet["paragraphs_vi"], row["key_points"])
        self.assertEqual((row["score_state"], row["writer_boats"]), ("passed", ["agy"]))
        self.assertEqual(decision["score"]["scorer_boat"], "codex")
        self.assertEqual(decision["score"]["value"], round(0.35 * 9 + 0.20 * 9 + 0.30 * 9 + 0.15 * 8, 2))
        self.assertEqual(decision["score"]["prose_sha256"],
                         prose_digest(decision["editorial_headline_vi"], decision["key_points"]))
        self.assertTrue(score_passed(decision))
        self.assertEqual(self.shown(decision), [SID])

    def test_prose_below_the_bar_or_with_one_hard_error_is_hidden(self):
        below = reply(scores=(8, 8, 8, 7))  # 7.85
        perfect_but_wrong = reply(scores=(10, 10, 10, 10), hard_errors=[HARD_ERROR])
        for name, verdict_reply in (("below", below), ("hard error", perfect_but_wrong)):
            with self.subTest(name):
                row, decision, _, _ = self.write({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: verdict_reply}})
                self.assertTrue(row["written"])
                self.assertEqual(row["score_state"], "failed")
                self.assertEqual(row["score_rewrite"]["result"], "writer_model_failure")
                self.assertEqual(decision["summary"], "written")
                self.assertFalse(score_passed(decision))
                self.assertEqual(self.shown(decision), [])
        self.assertLess(0.35 * 8 + 0.2 * 8 + 0.3 * 8 + 0.15 * 7, SCORE_THRESHOLD)

    def test_a_failed_story_is_rewritten_with_the_findings_and_can_pass_on_a_second_reading(self):
        row, decision, runner, _ = self.write({
            "writer": {SID: deepcopy(PROSE)},
            "scorer": {SID: reply(scores=(9, 9, 6, 8), hard_errors=[HARD_ERROR], findings=[FINDING])},
            "review-writer": {SID: deepcopy(PROSE)},
            "rescorer": {SID: reply()}})
        self.assertEqual([desk for desk, _ in runner.desks()], ["writer", "scorer", "review-writer", "rescorer"])
        _, boat, rows, instruction = runner.calls[2]
        self.assertEqual(instruction, WRITER_REVIEW_PROMPT)
        self.assertTrue(instruction.startswith(WRITER_PROMPT))
        review = rows[0]["review"]
        self.assertEqual(review["hard_errors"], [HARD_ERROR])
        self.assertEqual(review["findings"], [FINDING])
        self.assertEqual(review["weak_questions"], ["notable"])
        self.assertEqual(review["previous_paragraphs"], runner.calls[1][2][0]["paragraphs_vi"])
        # The rewrite reads the same sources the first draft did.
        self.assertEqual(rows[0]["sources"], runner.calls[0][2][0]["sources"])
        # The second reading is on a boat that wrote none of the rewrite either.
        self.assertNotEqual(runner.calls[3][1], boat)
        self.assertEqual(row["score_rewrite"]["result"], "written")
        self.assertEqual(row["score_rewrite"]["verdict"], "passed")
        self.assertIn("hard errors: number", row["score_rewrite"]["first_reason"])
        self.assertEqual(row["score_state"], "passed")
        self.assertEqual(self.shown(decision), [SID])

    def test_one_weak_answer_sends_the_story_to_a_rewrite_with_that_finding(self):
        # 06/11 18:00 Cainiao: what 10, why 6, notable 10, meaning 9 is 9.05 overall, but the cause was missing.
        why = {"question": "why", "problem": "The summary never says why Cainiao made the change.",
               "fix": "State the reason the source gives (outlet:p003)."}
        row, decision, runner, _ = self.write({
            "writer": {SID: deepcopy(PROSE)},
            "scorer": {SID: reply(scores=(10, 6, 10, 9), findings=[why])},
            "review-writer": {SID: deepcopy(PROSE)},
            "rescorer": {SID: reply()}})
        self.assertEqual(row["score_rewrite"]["first_reason"], "score 9.05 but why below 8")
        review = runner.calls[2][2][0]["review"]
        self.assertEqual((review["weak_questions"], review["findings"]), (["why"], [why]))
        self.assertEqual(row["score_state"], "passed")
        self.assertEqual(self.shown(decision), [SID])
        # Without a rewrite the story stays hidden.
        row, decision, _, _ = self.write({"writer": {SID: deepcopy(PROSE)},
                                          "scorer": {SID: reply(scores=(10, 6, 10, 9), findings=[why])}})
        self.assertEqual((row["score_state"], self.shown(decision)), ("failed", []))

    def test_scorer_failure_timeout_invalid_reply_or_no_fuel_hides_the_story(self):
        timed_out = RunnerError("codex call timed out")
        timed_out.__cause__ = subprocess.TimeoutExpired("codex", 900)
        dry = {**DISCOVERY, "fuel": "codex: CẠN (weekly)"}
        cases = {
            "model failure": ({"writer": {SID: deepcopy(PROSE)}}, {}, DISCOVERY),
            "timeout": ({"writer": {SID: deepcopy(PROSE)}}, {"scorer": timed_out}, DISCOVERY),
            "admission stop": ({"writer": {SID: deepcopy(PROSE)}},
                               {"scorer": AdmissionError("codex admission stopped (usage limit reached)")}, DISCOVERY),
            "score out of range": ({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply(scores=(11, 9, 9, 9))}},
                                   {}, DISCOVERY),
            "missing question": ({"writer": {SID: deepcopy(PROSE)},
                                  "scorer": {SID: {**reply(), "questions": {name: reply()["questions"][name]
                                                                            for name in QUESTIONS[:3]}}}},
                                 {}, DISCOVERY),
            "unknown hard error": ({"writer": {SID: deepcopy(PROSE)},
                                    "scorer": {SID: reply(hard_errors=[{**HARD_ERROR, "kind": "style"}])}},
                                   {}, DISCOVERY),
            "no fuel": ({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply()}}, {}, dry),
        }
        for name, (replies, fail, discovery) in cases.items():
            with self.subTest(name):
                row, decision, runner, usage = self.write(replies, discovery=discovery, fail=fail)
                self.assertTrue(row["written"])
                self.assertEqual(row["score_state"], "unscored", row["score_reason"])
                self.assertIsNone(decision["score"])
                self.assertEqual(self.shown(decision), [])
                self.assertNotIn(("scorer", "agy"), runner.desks())
        # With codex dry and claude unmeasured, the only fueled boat is the writer's own: no scorer runs at all.
        _, _, runner, usage = self.write({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply()}}, discovery=dry)
        self.assertEqual(runner.desks(), [("writer", "agy")])
        self.assertIn("scorer_unavailable", {row.get("event") for row in usage})

    def test_the_scorer_never_runs_on_a_boat_that_wrote_the_prose(self):
        # agy is dry for the writer, so codex writes; the scorer then must not be codex, and claude is unmeasured.
        dry_agy = {**DISCOVERY, "fuel": "gemini: CẠN"}
        row, decision, runner, _ = self.write({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply()}},
                                              discovery=dry_agy)
        self.assertEqual(runner.desks(), [("writer", "codex")])
        self.assertEqual(row["score_state"], "unscored")
        self.assertEqual(self.shown(decision), [])
        # Measured claude fuel gives the codex draft a scorer on a third boat.
        claude = {**dry_agy, "commands": [*DISCOVERY["commands"], "claude"],
                  "fuel": "gemini: CẠN\nclaude: CÒN 40%"}
        row, decision, runner, _ = self.write({"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply()}},
                                              discovery=claude)
        self.assertEqual(runner.desks(), [("writer", "codex"), ("scorer", "claude")])
        self.assertEqual(self.shown(decision), [SID])
        # A reply claiming to come from a writing boat is refused even if a lane were misconfigured.
        packet = scorer_packet(SID, [], "Tiêu đề", ["Một.", "Hai.", "Ba."])
        self.assertEqual(verdict(packet, {**reply(), "boat": "agy"}, {"agy"})["reason"], "scorer_same_boat")
        self.assertEqual(verdict(packet, {**reply(), "boat": "codex"}, set())["reason"], "writer_boat_unknown")

    def test_a_rewrite_on_another_boat_keeps_every_writing_boat_away_from_the_scorer(self):
        # agy drafts, codex scores it below the bar, agy fails the review rewrite so codex writes it, keeping
        # what the review did not fault: both agy and codex have words in the final text.
        replies = {"writer": {SID: deepcopy(PROSE)}, "scorer": {SID: reply(scores=(9, 9, 5, 8), findings=[FINDING])},
                   "review-writer": {SID: deepcopy(PROSE)}, "rescorer": {SID: reply()}}
        fail = {("review-writer", "agy"): RunnerError("agy call failed")}
        row, decision, runner, _ = self.write(replies, fail=fail)
        self.assertEqual(runner.desks(), [("writer", "agy"), ("scorer", "codex"), ("review-writer", "agy"),
                                          ("review-writer", "codex")])
        # No boat outside agy and codex has fuel here, so no second reading happens and the story stays hidden.
        self.assertEqual((row["score_state"], row["writer_boats"]), ("unscored", ["agy", "codex"]))
        self.assertEqual(self.shown(decision), [])
        # With measured claude fuel, the second reading goes to claude, never to agy or codex.
        claude = {**DISCOVERY, "commands": [*DISCOVERY["commands"], "claude"], "fuel": "claude: CÒN 40%"}
        row, decision, runner, _ = self.write(replies, fail=fail, discovery=claude)
        self.assertEqual(runner.desks()[-1], ("rescorer", "claude"))
        self.assertEqual(decision["score"]["writer_boats"], ["agy", "codex"])
        self.assertEqual(self.shown(decision), [SID])
        # A verdict from agy on that text never passes on the site, whatever it says.
        forged = deepcopy(decision)
        forged["score"]["scorer_boat"] = "agy"
        self.assertFalse(score_passed(forged))
        self.assertEqual(self.shown(forged), [])


class ScoringRetryTests(unittest.TestCase):
    """Prose a scorer has not passed is scored again, or written again with its findings, by a later cycle."""

    setUp = viet_bu.WriterRetryTests.setUp
    stored_cycle = viet_bu.WriterRetryTests.stored_cycle
    decisions = viet_bu.WriterRetryTests.decisions
    by_id = viet_bu.WriterRetryTests.by_id
    write_decisions = viet_bu.WriterRetryTests.write_decisions
    next_cycle = viet_bu.WriterRetryTests.next_cycle

    def test_unscored_prose_is_scored_by_the_next_cycle_without_writing_again(self):
        # The stored cycle's lane has no scorer replies: the prose is written but unscored, and hidden.
        writer = self.stored_cycle(NOW, {"backlog": (2, 2)}, written=("backlog",))
        self.assertEqual(writer["backlog"]["score_state"], "unscored")
        self.assertIsNone(self.by_id()["backlog"]["score"])
        lane = Lane({"rescorer": {"backlog": reply("backlog")}})
        status = self.next_cycle(LATER, lane)
        self.assertEqual(lane.sent(), [])
        self.assertEqual(lane.sent("rescorer"), ["backlog"])
        self.assertEqual(status["writer_retry"], {"candidates": 0, "sent": 0, "budget_cut": 0, "written": 0,
                                                  "score_candidates": 1, "scored": 1, "passed": 1})
        self.assertTrue(score_passed(self.by_id()["backlog"]))

    def test_prose_written_before_the_scoring_desk_is_backfilled_on_another_boat(self):
        self.stored_cycle(NOW, {"live": (2, 2)}, written=("live",))
        # What a cycle from before the desk left: no verdict on the decision, no writer_boats in writer.json.
        rows = self.by_id()
        rows["live"].pop("score")
        self.write_decisions(list(rows.values()))
        path = self.cycles / stamp(NOW) / "job" / "writer.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        for key in ("score", "score_state", "score_reason", "writer_boats"):
            stored["live"].pop(key)
        path.write_text(json.dumps(stored), encoding="utf-8")
        self.assertEqual(apply_decisions({"stories": [self.stories["live"]]}, self.decisions())["stories"], [])

        class Boats(Lane):
            def run(self, desk, rows, provider, instruction):
                self.calls.append((desk + "@" + provider["boat"], [row["id"] for row in rows]))
                return super().run(desk, rows, provider, instruction)

        lane = Boats({"rescorer": {"live": reply("live")}})
        self.next_cycle(LATER, lane)
        self.assertIn(("rescorer@codex", ["live"]), lane.calls)
        self.assertNotIn("rescorer@agy", {desk for desk, _ in lane.calls})
        shown = apply_decisions({"stories": [self.stories["live"]]}, self.decisions())["stories"]
        self.assertEqual([row["id"] for row in shown], ["live"])

    def test_a_failed_verdict_sends_the_story_back_to_the_writer_with_its_findings(self):
        self.stored_cycle(NOW, {"weak": (2, 2)}, written=("weak",))
        rows = self.by_id()
        packet = scorer_packet("weak", [], rows["weak"]["editorial_headline_vi"], rows["weak"]["key_points"])
        failed = verdict(packet, {**reply("weak", scores=(9, 9, 5, 8), findings=[FINDING]), "boat": "codex",
                                  "provider": "codex"}, {"agy"})
        self.assertEqual(failed["state"], "failed")
        rows["weak"]["score"] = failed["score"]
        self.write_decisions(list(rows.values()))

        class Instructions(Lane):
            def run(self, desk, rows, provider, instruction):
                self.instructions = getattr(self, "instructions", []) + [(desk, instruction, deepcopy(rows))]
                return super().run(desk, rows, provider, instruction)

        lane = Instructions({"writer": {"weak": prose("weak")}, "scorer": {"weak": reply("weak")}})
        status = self.next_cycle(LATER, lane)
        desk, instruction, sent = lane.instructions[0]
        self.assertEqual((desk, instruction), ("writer", WRITER_REVIEW_PROMPT))
        self.assertEqual(sent[0]["review"]["findings"], [FINDING])
        self.assertEqual(sent[0]["review"]["previous_paragraphs"], rows["weak"]["key_points"])
        self.assertEqual(status["writer_retry"]["written"], 1)
        self.assertEqual(status["writer_retry"]["passed"], 1)
        self.assertTrue(score_passed(self.by_id()["weak"]))

    def test_a_story_passed_on_its_total_alone_is_rewritten_by_the_next_cycle(self):
        # A verdict stored before the per-question floor: 9.05 overall with why at 6. It no longer passes, so the
        # next cycle writes the story again with the scorer's "why" finding.
        self.stored_cycle(NOW, {"cainiao": (2, 2)}, written=("cainiao",))
        rows = self.by_id()
        packet = scorer_packet("cainiao", [], rows["cainiao"]["editorial_headline_vi"], rows["cainiao"]["key_points"])
        stored = verdict(packet, {**reply("cainiao", scores=(10, 6, 10, 9), findings=[FINDING]), "boat": "codex",
                                  "provider": "codex"}, {"agy"})
        self.assertEqual(stored["state"], "failed")
        rows["cainiao"]["score"] = stored["score"]
        self.write_decisions(list(rows.values()))
        self.assertFalse(score_passed(self.by_id()["cainiao"]))

        class Instructions(Lane):
            def run(self, desk, rows, provider, instruction):
                self.sent_rows = getattr(self, "sent_rows", []) + [(desk, deepcopy(rows))]
                return super().run(desk, rows, provider, instruction)

        lane = Instructions({"writer": {"cainiao": prose("cainiao")}, "scorer": {"cainiao": reply("cainiao")}})
        status = self.next_cycle(LATER, lane)
        desk, sent = lane.sent_rows[0]
        self.assertEqual((desk, sent[0]["review"]["weak_questions"]), ("writer", ["why"]))
        self.assertEqual(status["writer_retry"]["passed"], 1)
        self.assertTrue(score_passed(self.by_id()["cainiao"]))

    def test_a_retry_rewrite_on_another_boat_is_never_scored_by_the_failed_drafts_boat(self):
        self.stored_cycle(NOW, {"weak": (2, 2)}, written=("weak",))
        rows = self.by_id()
        packet = scorer_packet("weak", [], rows["weak"]["editorial_headline_vi"], rows["weak"]["key_points"])
        failed = verdict(packet, {**reply("weak", scores=(9, 9, 5, 8), findings=[FINDING]), "boat": "codex",
                                  "provider": "codex"}, {"agy"})
        rows["weak"]["score"] = failed["score"]
        self.write_decisions(list(rows.values()))

        class AgyDown(Lane):
            """agy fails the writer, so codex rewrites the agy draft; every call is recorded with its boat."""

            def run(self, desk, rows, provider, instruction):
                self.boats = getattr(self, "boats", []) + [(desk, provider["boat"])]
                if desk == "writer" and provider["boat"] == "agy":
                    raise RunnerError("agy call failed")
                return super().run(desk, rows, provider, instruction)

        lane = AgyDown({"writer": {"weak": prose("weak")}, "scorer": {"weak": reply("weak")}})
        self.next_cycle(LATER, lane)
        self.assertIn(("writer", "codex"), lane.boats)
        self.assertNotIn(("scorer", "agy"), lane.boats)
        self.assertNotIn(("scorer", "codex"), lane.boats)
        retry = json.loads((self.cycles / stamp(LATER) / "viet-bu" / "writer.json").read_text(encoding="utf-8"))
        self.assertEqual(retry["weak"]["writer_boats"], ["agy", "codex"])
        self.assertEqual(retry["weak"]["score_state"], "unscored")
        self.assertFalse(score_passed(self.by_id()["weak"]))

    def test_a_story_whose_scorer_keeps_failing_stops_after_two_score_attempts(self):
        self.stored_cycle(NOW, {"stuck": (2, 2)}, written=("stuck",))
        for hours in (4, 8):
            lane = Lane({})
            self.next_cycle(NOW + timedelta(hours=hours), lane)
            self.assertEqual(set(lane.sent("rescorer")), {"stuck"})
        lane = Lane({})
        status = self.next_cycle(NOW + timedelta(hours=12), lane)
        self.assertEqual(lane.calls, [])
        self.assertNotIn("writer_retry", status)
        self.assertIsNone(self.by_id()["stuck"]["score"])

    def test_a_one_off_backfill_can_raise_the_rescore_limit_for_one_run(self):
        self.stored_cycle(NOW, {"one": (2, 2), "two": (3, 2)}, written=("one", "two"))
        lane = Lane({"rescorer": {"one": reply("one"), "two": reply("two")}})
        with patch.dict("os.environ", {cycle_module.RESCORE_LIMIT_ENV: "1"}):
            status = self.next_cycle(LATER, lane)
        # Newest first: "one" is an hour younger.
        self.assertEqual(lane.sent("rescorer"), ["one"])
        self.assertEqual(status["writer_retry"]["score_candidates"], 1)
        self.assertEqual(cycle_module.rescore_limit({}), cycle_module.RESCORE_LIMIT)
        self.assertEqual(cycle_module.rescore_limit({cycle_module.RESCORE_LIMIT_ENV: "120"}), 120)
        self.assertEqual(cycle_module.rescore_limit({cycle_module.RESCORE_LIMIT_ENV: "many"}),
                         cycle_module.RESCORE_LIMIT)


if __name__ == "__main__":
    unittest.main()

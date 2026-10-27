"""Desk-written key points reach the site, and the paid summary step leaves them alone."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import summarize, summary_gemini as gemini, summary_pipeline
from radar.newsroom_decisions import DESK_PROMPT_VERSION, apply_decisions, is_desk_summary

EXAMPLE = json.loads((Path(__file__).parent / "fixtures" / "summary-articles" / "editorial-case.json")
                     .read_text(encoding="utf-8"))
DESK_POINTS = [
    "Bàn người viết tóm tắt ý thứ nhất của bài báo bằng tiếng Việt.",
    "Bàn người viết tóm tắt ý thứ hai của bài báo bằng tiếng Việt.",
    "Bàn người viết tóm tắt ý thứ ba của bài báo bằng tiếng Việt.",
]


def desk_decision(sid, points=DESK_POINTS):
    return {"id": sid, "decision": "publish", "summary": "written", "written_by": "nguoi-viet",
            "key_points": list(points), "editorial_headline_vi": "Tiêu đề do phòng báo viết",
            "summary_sources": [{"id": "outlet", "role": "outlet", "name": "Desk Source",
                                 "url": "https://desk.example/story"}],
            "summary_limitations": [], "key_points_prompt_version": DESK_PROMPT_VERSION}


def api_story():
    return {"id": EXAMPLE["id"], "title": EXAMPLE["title"], "url": EXAMPLE["url"],
            "published_at": "2026-10-10T00:00:00Z", "summary": "Publisher excerpt.",
            "coverage": [{"url": EXAMPLE["url"], "publisher": EXAMPLE["publisher"]}]}


class DeskSummaryProjectionTests(unittest.TestCase):
    def test_fresh_desk_points_are_published_with_provenance(self):
        payload = {"stories": [{"id": "desk", "title": "Desk story"}, {"id": "plain", "title": "Plain"},
                               {"id": "thin", "title": "Thin"}, {"id": "held", "title": "Held"}]}
        decisions = {"decisions": [desk_decision("desk"), {"id": "plain", "decision": "publish"},
                                   desk_decision("thin", DESK_POINTS[:2]),
                                   {**desk_decision("held"), "decision": "hold"}]}
        result = apply_decisions(payload, decisions)
        desk, plain, thin = result["stories"]
        self.assertEqual(desk["key_points"], DESK_POINTS)
        self.assertEqual(desk["key_points_source"], "nguoi-viet")
        self.assertIs(desk["key_points_machine"], True)
        self.assertEqual(desk["editorial_headline_vi"], "Tiêu đề do phòng báo viết")
        self.assertTrue(is_desk_summary(desk))
        self.assertNotIn("key_points", plain)
        self.assertNotIn("key_points", thin)
        self.assertNotIn("key_points", payload["stories"][0])
        self.assertEqual(apply_decisions(result, decisions)["stories"][0], desk)

    def test_summary_step_skips_desk_stories_and_still_summarizes_the_rest(self):
        desk_story = {"id": "desk", "title": "Desk story", "url": "https://desk.example/story",
                      "published_at": "2026-10-10T00:30:00Z", "summary": "Desk excerpt."}
        payload = apply_decisions({"stories": [desk_story, api_story()], "generated_at": "2026-10-10T01:00:00Z"},
                                  {"decisions": [desk_decision("desk")]})
        before = deepcopy(payload["stories"][0])
        sent, fetched = [], []

        def provider(body, _key, _timeout):
            story = json.loads(body["contents"][0]["parts"][0]["text"])["stories"][0]
            sent.append(story["id"])
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{
                "text": json.dumps(EXAMPLE["output"], ensure_ascii=False)}]}}]}

        def fetch(story):
            fetched.append(story["id"])
            return "\n".join(EXAMPLE["paragraphs"])

        with tempfile.TemporaryDirectory() as directory, patch(
                "socket.create_connection", side_effect=AssertionError("network forbidden")):
            stats, _ = summary_pipeline.summarize_payload(
                payload, {}, config=gemini.Config(api_key="offline-sentinel", confirmed=True),
                article_inputs={}, article_fetch_fn=fetch, transport_fn=provider,
                ledger_path=Path(directory) / "ledger.json", now=lambda: 100000.0)
        self.assertEqual(sent, [EXAMPLE["id"]])
        self.assertEqual(fetched, [EXAMPLE["id"]])
        self.assertEqual(stats["desk_written"], 1)
        self.assertEqual(stats["summarized"], 1, stats)
        self.assertEqual(payload["stories"][0], before)
        self.assertEqual(payload["stories"][1]["key_points_source"], "machine")

    def test_summary_cli_sends_no_api_request_without_explicit_opt_in(self):
        desk_story = {"id": "desk", "title": "Desk story", "url": "https://desk.example/story",
                      "published_at": "2026-10-10T00:30:00Z", "summary": "Desk excerpt."}
        payload = apply_decisions({"stories": [desk_story, api_story()], "generated_at": "2026-10-10T01:00:00Z"},
                                  {"decisions": [desk_decision("desk")]})
        env = {"GEMINI_API_KEY": "offline-sentinel", "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
               "RADAR_GEMINI_PAID_ENABLED": "1"}
        with tempfile.TemporaryDirectory() as directory:
            source, cache = Path(directory) / "radar.json", Path(directory) / "summaries.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.dict("os.environ", env, clear=True), \
                    patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
                    patch.object(gemini, "transport", side_effect=AssertionError("API must not run")), \
                    patch.object(summary_pipeline, "fetch_article_text",
                                 side_effect=AssertionError("no article fetch for the API")), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(summarize.main(["--input", str(source), "--cache", str(cache)]), 0)
            written = json.loads(source.read_text(encoding="utf-8"))
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("Summary skipped: writer desk owns summaries"), lines)
        desk, plain = written["stories"]
        self.assertEqual(desk["key_points"], DESK_POINTS)
        self.assertEqual(desk["key_points_source"], "nguoi-viet")
        self.assertNotIn("key_points", plain)
        self.assertEqual(written["summary"]["status"], "skipped")
        self.assertEqual(written["summary"]["requests"], 0)
        self.assertIsNone(written["summary"]["error"])

    def test_desk_points_for_an_old_contract_are_cleared_like_api_points(self):
        story = apply_decisions({"stories": [{"id": "desk", "title": "Desk"}]},
                                {"decisions": [{**desk_decision("desk"), "key_points_prompt_version": gemini.PROMPT_VERSION}]})
        story = story["stories"][0]
        self.assertFalse(is_desk_summary(story))
        payload = {"stories": [story], "generated_at": "2026-10-10T01:00:00Z"}
        summary_pipeline.summarize_payload(payload, {}, config=gemini.Config(), now=lambda: 100000.0)
        self.assertNotIn("key_points", payload["stories"][0])


if __name__ == "__main__":
    unittest.main()

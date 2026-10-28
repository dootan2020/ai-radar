import json
import unittest
from pathlib import Path
from unittest.mock import patch

import phong_bao.newsroom as newsroom
from phong_bao.newsroom import FixtureArticles, REPORTER_PROMPT, _reporter
from phong_bao.registry import load_registry


FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"
ARTICLE = "A readable article body about the launch. " * 80

# Reply rows as the agy lane returned them on 2026-10-28 (prep-attempt-1/reporter-1.json), URLs moved to example.com.
AGY_ROW = {"selected_url": None, "same_event": True,
           "reason": "The representative article is already readable, and the candidate is from the same publisher."}
# Reply rows as the Codex lane returned them for the same stories (prep/reporter-1.json).
CODEX_REASON = "Representative article is readable and matches the story."


def _story(sid, url):
    return {"id": sid, "title": f"Story {sid}", "url": url, "published_at": "2026-10-28T00:00:00Z"}


class ReporterReadableRepresentativeTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = json.loads((FIXTURES / "discovery.json").read_text(encoding="utf-8"))

    def run_reporter(self, stories, rows, articles):
        def fake_desk(desk, payload, *args, **kwargs):
            return {item["id"]: {"id": item["id"], **rows[item["id"]], "provider": "agy", "boat": "gemini"}
                    for item in payload}, []

        intake = {story["id"]: {"pass": True} for story in stories}
        with patch.object(newsroom, "_agent_desk", side_effect=fake_desk):
            output, _ = _reporter(stories, intake, FixtureArticles({"articles": articles}),
                                  self.tools, self.discovery, None, [])
        return output

    def test_agy_null_selection_keeps_readable_representative(self):
        story = _story("c1913c4bc921d7e32c35", "https://example.com/inside-runtime-agents")
        output = self.run_reporter([story], {story["id"]: AGY_ROW},
                                   {story["url"]: {"text": ARTICLE}})
        row = output[story["id"]]
        self.assertTrue(row["readable"])
        self.assertEqual(row["selected_url"], story["url"])
        self.assertEqual(row["source_text"], ARTICLE[:newsroom.ARTICLE_LIMIT])
        self.assertFalse(row["invalid_response"])

    def test_codex_selection_of_representative_is_unchanged(self):
        story = _story("b9d806b8cb7b2cd2beef", "https://example.com/abs/2610.30753")
        output = self.run_reporter([story], {story["id"]: {"selected_url": story["url"], "same_event": True,
                                                            "reason": CODEX_REASON}},
                                   {story["url"]: {"text": ARTICLE}})
        row = output[story["id"]]
        self.assertTrue(row["readable"])
        self.assertEqual(row["selected_url"], story["url"])
        self.assertEqual(row["reason"], CODEX_REASON)

    def test_null_selection_with_wrong_event_stays_unreadable(self):
        story = _story("d58d88b2f16700c85f91", "https://example.com/unrelated-page")
        output = self.run_reporter([story], {story["id"]: {"selected_url": None, "same_event": False,
                                                            "reason": "Article covers a different event."}},
                                   {story["url"]: {"text": ARTICLE}})
        self.assertFalse(output[story["id"]]["readable"])
        self.assertIsNone(output[story["id"]]["selected_url"])

    def test_null_selection_when_representative_unreadable_stays_unreadable(self):
        story = _story("df4815cb1a6e9e4373c7", "https://example.com/paywalled")
        story["coverage"] = [{"id": "other", "url": "https://other.example.org/same-event", "title": story["title"]}]
        output = self.run_reporter([story], {story["id"]: AGY_ROW},
                                   {"https://other.example.org/same-event": {"text": ARTICLE}})
        self.assertFalse(output[story["id"]]["readable"])
        self.assertIsNone(output[story["id"]]["selected_url"])

    def test_prompt_states_what_to_return_for_a_readable_representative(self):
        self.assertIn("If the representative article is readable", REPORTER_PROMPT)
        self.assertIn("representative_url", REPORTER_PROMPT)


if __name__ == "__main__":
    unittest.main()

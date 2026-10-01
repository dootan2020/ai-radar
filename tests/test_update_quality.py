"""Regressions drawn from the captured morning snapshot and upstream feed."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from radar.common import classify
from radar.feeds import parse_feed
import serve

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE = json.loads((FIXTURES / "radar-before-round2.json").read_text(encoding="utf-8"))


class UpdateQualityTests(unittest.TestCase):
    def test_model_mentions_are_not_the_object_of_a_release(self):
        for title in [
            "Introducing Claude Opus 6 safeguards",
            "Introducing GPT-6 Astra in our tax workbook",
            "Introducing a new model evaluation framework",
            "Introducing new safety measures for frontier models",
            "How developers are releasing models with our platform",
            "We are not releasing a model today",
        ]:
            with self.subTest(title=title):
                self.assertNotEqual(classify(title), "model")

    def test_model_release_judgments_on_every_real_snapshot_item(self):
        judgments = json.loads((FIXTURES / "model-release-judgments.json").read_text(encoding="utf-8"))
        self.assertEqual(set(judgments), {item["id"] for item in BASELINE["updates"]})
        for item in BASELINE["updates"]:
            with self.subTest(title=item["title"]):
                self.assertEqual(classify(item["title"], item["summary"]) == "model",
                                 judgments[item["id"]]["model"], judgments[item["id"]]["reason"])

    def test_real_anthropic_title_cleanup(self):
        source = {"id": "anthropic-research", "lab": "anthropic"}
        items = parse_feed((FIXTURES / "anthropic-research.xml").read_text(encoding="utf-8"), source)
        expected = json.loads((FIXTURES / "anthropic-clean-titles.json").read_text(encoding="utf-8"))
        self.assertEqual(len(items), len(expected))
        for item in items:
            with self.subTest(url=item["url"]):
                self.assertEqual(item["title"], expected[item["url"]])
                self.assertEqual(item["kind"], "research")
        assessment = next(item for item in items if "alignment-assessment" in item["url"])
        self.assertTrue(assessment["summary"].startswith("We present an alignment assessment"))

    def test_other_feeds_keep_legitimate_camelcase(self):
        for title in ["DevDay 2026 Recap", "Introducing MentalHealthBench", "DINOv3", "OpenAI"]:
            body = f"<rss><channel><item><title>{title}</title><link>https://example.org/post</link></item></channel></rss>"
            self.assertEqual(parse_feed(body, {"id": "openai-news", "lab": "openai"})[0]["title"], title)

    def test_research_cleanup_requires_recognized_metadata_and_preserves_names(self):
        for raw, expected in [
            ("Sep 30, 2026ScienceMentalHealthBench", "MentalHealthBench"),
            ("ScienceSep 30, 2026DevDay 2026 Recap", "DevDay 2026 Recap"),
            ("Science advances in OpenAI", "Science advances in OpenAI"),
            ("Sep 30, 2026UnknownCategoryTitle", "Sep 30, 2026UnknownCategoryTitle"),
        ]:
            body = f"<rss><channel><item><title>{raw}</title><link>https://example.org/research</link></item></channel></rss>"
            self.assertEqual(parse_feed(body, {"id": "anthropic-research", "lab": "anthropic"})[0]["title"], expected)

    def test_default_server_uses_8790_and_bind_failure_exits(self):
        with patch.object(serve, "LocalServer", side_effect=OSError("address already in use")) as factory:
            with self.assertRaises(SystemExit) as raised:
                serve.main()
        self.assertEqual(factory.call_args.args[0], ("127.0.0.1", 8790))
        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("localhost:8790", str(raised.exception))
        self.assertIn("address already in use", str(raised.exception))
        self.assertEqual(factory.call_count, 1)


if __name__ == "__main__":
    unittest.main()

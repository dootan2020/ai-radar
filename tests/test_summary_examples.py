"""Reproducible editorial examples through the real pipeline, with no model calls.

Expected Vietnamese text is authored for these fixtures, not Gemini output.
The Qwen fixtures contain real article introductions from the captured RSS.
"""

from html import unescape
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from radar import summary_gemini as gemini, summary_pipeline

FIXTURES = Path(__file__).parent / "fixtures"


def load_examples():
    examples = json.loads((FIXTURES / "summary-key-points.json").read_text(encoding="utf-8"))
    for example in examples:
        path = FIXTURES / example["fixture"]
        if path.suffix == ".html":
            parser = summary_pipeline._ArticleTextParser()
            parser.feed(path.read_text(encoding="utf-8"))
            text = " ".join(parser.parts)
        else:
            text = ET.parse(path).getroot().findall(".//item")[example["item"]].findtext("description")
        example["article_text"] = unescape(text)
    return examples


class SummaryExamplesTests(unittest.TestCase):
    def test_real_source_examples_pass_pipeline_with_stubbed_api(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "socket.create_connection", side_effect=AssertionError("network forbidden")
        ):
            for example in load_examples():
                with self.subTest(example=example["id"]):
                    story = {key: example[key] for key in ("id", "title", "url")}
                    story.update(published_at="2026-10-10T00:00:00Z", summary=example["before"])
                    calls = []

                    def stub(body, _key, _timeout):
                        sent = json.loads(body["contents"][0]["parts"][0]["text"])["stories"][0]
                        calls.append(sent)
                        self.assertTrue(example["article_text"].startswith(sent["article_text"]))
                        self.assertGreaterEqual(len(sent["article_text"]), 300)
                        return {
                            "candidates": [{"finishReason": "STOP", "content": {"parts": [{
                                "text": json.dumps({"summaries": [{"id": sent["id"], "key_points": example["key_points"]}]})
                            }]}}],
                            # No fabricated usage: the conservative reservation remains.
                        }

                    payload = {"stories": [story], "generated_at": "2026-10-10T01:00:00Z"}
                    cache = {}
                    stats, alive = summary_pipeline.summarize_payload(
                        payload, cache, config=gemini.Config(api_key="offline-sentinel", confirmed=True),
                        article_fetch_fn=lambda _: example["article_text"], transport_fn=stub,
                        ledger_path=Path(directory) / (example["id"] + ".json"), now=lambda: 100000.0,
                    )
                    self.assertFalse(alive)
                    self.assertEqual(stats["summarized"], 1, stats)
                    self.assertEqual(story["key_points"], example["key_points"])
                    self.assertTrue(story["key_points_machine"])
                    self.assertEqual(story["summary"], example["before"])
                    self.assertEqual(len(calls), 1)
                    self.assertIn(summary_pipeline.content_hash(calls[0]), cache)


if __name__ == "__main__":
    unittest.main()

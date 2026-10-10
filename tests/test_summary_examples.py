"""Synthetic authored example through production selection, generation and projection.

The transport double supplies a declared fixture, never pretends to be live output.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import summary_gemini as gemini, summary_pipeline
from radar.site_payload import page_payload

FIXTURE = Path(__file__).parent / "fixtures" / "summary-articles" / "editorial-case.json"


class SummaryExamplesTests(unittest.TestCase):
    def test_synthetic_example_survives_generation_projection_and_cache_restore(self):
        example = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory, patch(
            "socket.create_connection", side_effect=AssertionError("network forbidden")
        ):
            story = {key: example[key] for key in ("id", "title", "url")}
            story.update(published_at="2026-10-10T00:00:00Z", summary="Publisher excerpt.",
                         coverage=[{"url": example["url"], "publisher": example["publisher"]}])
            calls = []

            def provider(body, _key, _timeout):
                sent = json.loads(body["contents"][0]["parts"][0]["text"])["stories"][0]
                calls.append(sent)
                self.assertEqual([p["text"] for p in sent["sources"][0]["paragraphs"]], example["paragraphs"])
                self.assertEqual(body["generationConfig"]["maxOutputTokens"], 4096)
                return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{
                    "text": json.dumps(example["output"], ensure_ascii=False)
                }]}}]}

            cache, evidence = {}, {}
            config = gemini.Config(api_key="offline-sentinel", confirmed=True)
            payload = {"stories": [story], "generated_at": "2026-10-10T01:00:00Z"}
            ledger = Path(directory) / "ledger.json"
            stats, alive = summary_pipeline.summarize_payload(
                payload, cache, config=config, article_inputs=evidence,
                article_fetch_fn=lambda _: "\n".join(example["paragraphs"]), transport_fn=provider,
                ledger_path=ledger, now=lambda: 100000.0,
            )
            self.assertFalse(alive)
            self.assertEqual(stats["summarized"], 1, stats)
            self.assertEqual(story["key_points"], [p["text"] for p in example["output"]["key_points"]])
            self.assertEqual(story["key_points_prompt_version"], gemini.PROMPT_VERSION)
            self.assertEqual(story["summary_sources"][0]["url"], example["url"])
            public = json.dumps(page_payload(payload), ensure_ascii=False)
            for forbidden in ("short_vi", "takeaway_vi", "evidence_refs", "paragraphs", *example["paragraphs"]):
                self.assertNotIn(forbidden, public)
            self.assertEqual(len(calls), 1)
            self.assertIn(summary_pipeline.content_hash(calls[0]), cache)
            # Missing provider usage retains the exact conservative reservation.
            self.assertEqual(stats["tokens"], 0)
            saved = json.loads(ledger.read_text())
            self.assertEqual(saved["attempts"][0]["tokens"], stats["input_bytes"] + 4096)
            restored = deepcopy(payload)
            with patch.object(summary_pipeline, "fetch_article_result", side_effect=AssertionError("no refetch")):
                stats, _ = summary_pipeline.summarize_payload(
                    restored, cache, article_inputs=evidence, config=gemini.Config(), now=lambda: 100001.0)
            self.assertEqual(stats["cache_hits"], 1)
            self.assertEqual(restored["stories"][0]["key_points"], story["key_points"])

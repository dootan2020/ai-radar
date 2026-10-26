"""Offline quota fitting with real reservation, parsing and grounding checks."""

from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import gemini_paid_budget as paid
from radar import summarize, summary_gemini as gemini, summary_pipeline as pipeline


ARTICLE = (
    "Apple changes Full Disk Access permissions on macOS. "
    "AI agents must ask for confirmation before reading user data. "
    "The article describes effects on applications and security procedures. "
    "The author explains why confirmation affects how agents operate and how the new "
    "permissions process changes access for applications and their users.")
POINTS = [
    "Apple thay đổi cách quản lý quyền Full Disk Access trên macOS.",
    "Các agent AI cần xin xác nhận trước khi đọc dữ liệu người dùng.",
    "Bài viết nêu tác động tới ứng dụng và quy trình bảo mật.",
    "Tác giả phân tích ảnh hưởng của việc cấp quyền đối với các agent.",
]


class SummaryQuotaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "paid.json"
        self.now = datetime(2026, 10, 11, 17, tzinfo=timezone.utc).timestamp()
        self.config = gemini.Config(api_key="offline-sentinel", confirmed=True, paid=True)
        self.calls = []
        self.env = patch.dict(os.environ, {
            "RADAR_GEMINI_PAID_LEDGER": str(self.path), "GITHUB_RUN_NUMBER": "21",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.assertIsNone(paid.prepare(self.path, paid=False, now=self.now, run_number=21))
        # Production headroom: summary $0.050776, shared run $0.098095.
        ledger = json.loads(self.path.read_text())
        ledger.update(run_allowance_micros=98095, consumer_remaining_micros={
            "summary": 50776, "translation": 2319, "video": 45000,
        })
        self.path.write_text(json.dumps(ledger), encoding="utf-8", newline="\n")
        self.assertEqual(paid.remaining_tokens(self.path, "summary", now=self.now), 13540)

    def story(self, sid="first"):
        return dict(id=sid, title="Apple permissions", url=f"https://publisher.example/{sid}",
                    published_at="2026-10-11T12:00:00Z", kind="news", coverage=[])

    def provider(self, body, key, timeout):
        item = json.loads(body["contents"][0]["parts"][0]["text"])["stories"][0]
        self.calls.append(body)
        ledger = json.loads(self.path.read_text())
        self.assertEqual(ledger["reservations"][-1]["consumer"], "summary")
        estimate = len(gemini.encode_request(body)) + gemini.MAX_OUTPUT_TOKENS
        self.assertEqual(ledger["reservations"][-1]["micros"], paid._micros(estimate, self.now))
        claim = lambda text: {"text": text, "evidence_refs": ["outlet:p001"]}
        row = dict(id=item["id"], status="ready",
                   title_vi=claim("Bài viết phân tích thay đổi và tác động tới người dùng"),
                   key_points=[claim(text) for text in POINTS], used_source_ids=["outlet"],
                   limitations=[] if item["sources"][0]["body_complete"] else ["partial_source"])
        return {"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(row, ensure_ascii=False)}]}}],
            "usageMetadata": {"totalTokenCount": 420}}

    def run_summary(self, stories, articles, **kwargs):
        payload = {"stories": stories, "generated_at": "2026-10-11T17:00:00Z"}
        return pipeline.summarize_payload(
            payload, kwargs.pop("cache", {}), config=self.config,
            transport_fn=kwargs.pop("transport_fn", self.provider),
            article_fetch_fn=lambda story, **kw: articles[story["id"]],
            editor_picks=[{"id": story["id"]} for story in stories], now=lambda: self.now,
            **kwargs)[0]

    def production_article(self, story, *, indivisible=False):
        # Synthetic evidence calibrated to the observed 15,502 wire bytes;
        # use the real serializer, including prompt, schema, and UTF-8 escaping.
        text = ARTICLE
        if not indivisible:
            text += "\n" + ("Further article evidence. " * 20 + "\n") * 5
        text = text.rstrip()
        def estimate(value):
            inputs = pipeline.fit_story_inputs(pipeline.collect_inputs(
                story, value, [], {}, fetched_at=datetime.fromtimestamp(
                    self.now, timezone.utc).isoformat()), self.config.max_chars)
            return len(gemini.encode_request(gemini.request_body([inputs]))) + gemini.MAX_OUTPUT_TOKENS
        multibyte, ascii_bytes = divmod(19598 - estimate(text), 3)
        text += "ữ" * multibyte + "x" * ascii_bytes
        self.assertEqual(estimate(text), 19598)
        return text

    def test_snapshot_reports_active_boost_and_charged_usage(self):
        ledger = json.loads(self.path.read_text())
        ledger.update(run_day="2026-10-11", settled_daily_micros=600_000,
                      daily_remaining_micros=370_000)
        self.path.write_text(json.dumps(ledger), encoding="utf-8", newline="\n")
        payload = {"stories": [], "generated_at": "2026-10-11T17:00:00Z"}
        with patch.dict(os.environ, {"RADAR_GEMINI_PAID_BOOST": "2026-10-11:0.40"}):
            stats, _ = pipeline.summarize_payload(payload, {}, config=self.config,
                                                   now=lambda: self.now)
        self.assertEqual(stats["paid_boost"], {"date": "2026-10-11", "limit_micros": 400_000,
                                               "used_micros": 30_000})
        self.assertEqual(payload["summary"], stats)

    def test_production_headroom_trims_first_story_and_preserves_cached_evidence(self):
        story = self.story()
        article = self.production_article(story)
        evidence, cache = {}, {}
        stats = self.run_summary([story], {story["id"]: article}, article_inputs=evidence, cache=cache)
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["reservations_refused"], 1)
        self.assertEqual(stats["candidates_tried"], 1)
        self.assertLessEqual(len(gemini.encode_request(self.calls[0])) + 4096, 13540)
        self.assertEqual(story["key_points"], POINTS)
        self.assertEqual(stats["settled_micros"], 1575)
        self.assertEqual(stats["settled_tokens"], 420)
        again = self.run_summary([deepcopy(story)], {}, article_inputs=evidence, cache=cache)
        self.assertEqual(again["cache_hits"], 1)
        self.assertEqual(again["settled_micros"], 0)
        self.assertEqual(again["settled_tokens"], 0)
        self.assertEqual(len(self.calls), 1)

    def test_indivisible_first_story_advances_to_later_fitting_story(self):
        first, later = self.story(), self.story("later")
        failures = {}
        stats = self.run_summary([first, later], {
            "first": self.production_article(first, indivisible=True), "later": ARTICLE,
        }, article_failures=failures)
        self.assertEqual(stats["summarized"], 1)
        self.assertNotIn("key_points", first)
        self.assertEqual(later["key_points"], POINTS)
        self.assertEqual(stats["candidates_tried"], 2)
        self.assertEqual(stats["reservations_refused"], 1)
        self.assertIsNone(stats["error"])
        self.assertEqual(failures, {})  # Quota-dependent skips must not survive tomorrow's reset.

    def test_nothing_fits_keeps_quota_error_and_sends_no_request(self):
        stories = [self.story(), self.story("later")]
        stats = self.run_summary(stories, {
            story["id"]: self.production_article(story, indivisible=True) for story in stories})
        self.assertEqual(stats["error"], "paid_summary_daily_tokens")
        self.assertEqual(stats["candidates_tried"], 2)
        self.assertEqual(stats["reservations_refused"], 2)
        self.assertEqual(stats["requests"], 0)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads(self.path.read_text())["reservations"], [])

    def test_first_fitting_editor_pick_keeps_priority_without_trimming(self):
        first, later = self.story(), self.story("later")
        first["worth_score"], later["worth_score"] = 1, 100
        stats = self.run_summary([first, later], {"first": ARTICLE})
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(first["key_points"], POINTS)
        self.assertNotIn("key_points", later)
        self.assertEqual(stats["trimmed"], 0)
        self.assertEqual(stats["candidates_tried"], 1)
        self.assertEqual(stats["reservations_refused"], 0)

    def test_trimming_below_article_minimum_skips_without_call(self):
        story = self.story()
        article = "x" * 299 + "\n" + self.production_article(story, indivisible=True)
        stats = self.run_summary([story], {"first": article})
        self.assertEqual(stats["summarized"], 0)
        self.assertEqual(stats["error"], "paid_summary_daily_tokens")
        self.assertEqual(stats["skipped_reasons"]["input_limit"], 1)
        self.assertEqual(self.calls, [])

    def test_trimmed_summary_still_rejects_invented_facts_and_records_cost(self):
        story = self.story()
        def invalid(body, key, timeout):
            response = self.provider(body, key, timeout)
            part = response["candidates"][0]["content"]["parts"][0]
            row = json.loads(part["text"])
            row["key_points"][0]["text"] = "UnknownCorp thay đổi cách quản lý dữ liệu người dùng."
            part["text"] = json.dumps(row, ensure_ascii=False)
            return response
        stats = self.run_summary([story], {"first": self.production_article(story)}, transport_fn=invalid)
        self.assertEqual(stats["summarized"], 0)
        self.assertEqual(stats["rejected"], 1)
        self.assertIn("invented_entity", stats["rejected_reasons"][0]["reason"])
        self.assertEqual(stats["settled_tokens"], 420)
        self.assertEqual(stats["settled_micros"], 1575)
        self.assertNotIn("key_points", story)

    def test_missing_usage_keeps_estimated_charge(self):
        def no_usage(body, key, timeout):
            response = self.provider(body, key, timeout)
            response.pop("usageMetadata")
            return response
        stats = self.run_summary([self.story()], {"first": ARTICLE}, transport_fn=no_usage)
        estimate = len(gemini.encode_request(self.calls[0])) + gemini.MAX_OUTPUT_TOKENS
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(stats["tokens"], 0)
        self.assertEqual(stats["settled_tokens"], estimate)
        self.assertEqual(stats["settled_micros"], paid._micros(estimate, self.now))

    def test_invalid_response_settles_reported_usage_instead_of_full_hold(self):
        def invalid(body, key, timeout):
            response = self.provider(body, key, timeout)
            response["candidates"][0]["finishReason"] = "MAX_TOKENS"
            return response
        story = self.story()
        stats = self.run_summary([story], {"first": ARTICLE}, transport_fn=invalid)
        self.assertEqual(stats["error"], "invalid_response")
        self.assertEqual(stats["summarized"], 0)
        self.assertEqual(stats["tokens"], 420)
        self.assertEqual(stats["settled_micros"], paid._micros(420, self.now))
        self.assertNotIn("key_points", story)

    def test_retry_counts_both_charges_and_excludes_prior_consumer_spend(self):
        ledger = json.loads(self.path.read_text())
        ledger["consumer_remaining_micros"]["summary"] = 375000
        ledger["run_allowance_micros"] = 200000
        self.path.write_text(json.dumps(ledger), encoding="utf-8", newline="\n")
        self.assertIsNone(paid.reserve(self.path, 500, now=self.now, consumer="translation")[0])
        before = paid.total_micros(self.path, now=self.now)
        attempts = []
        def transient(body, key, timeout):
            attempts.append(body)
            if len(attempts) == 1:
                raise gemini.ProviderError("http_503:UNAVAILABLE")
            return self.provider(body, key, timeout)
        with patch.object(pipeline.time, "sleep"):
            stats = self.run_summary([self.story()], {"first": ARTICLE}, transport_fn=transient)
        estimate = len(gemini.encode_request(attempts[0])) + gemini.MAX_OUTPUT_TOKENS
        self.assertEqual(stats["requests"], 2)
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(stats["settled_tokens"], estimate + 420)
        self.assertEqual(stats["settled_micros"], paid._micros(estimate, self.now) + 1575)
        self.assertEqual(stats["settled_micros"], paid.total_micros(self.path, now=self.now) - before)

    def test_refused_retry_sends_only_first_request_and_keeps_first_charge(self):
        attempts = []
        def unavailable(body, key, timeout):
            attempts.append(body)
            raise gemini.ProviderError("http_503:UNAVAILABLE")
        with patch.object(pipeline.time, "sleep"):
            stats = self.run_summary([self.story()], {"first": ARTICLE}, transport_fn=unavailable)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["reservations_refused"], 1)
        self.assertEqual(stats["error"], "paid_summary_daily_tokens")
        self.assertEqual(stats["settled_micros"], paid.total_micros(self.path, now=self.now))

    def test_other_budget_refusals_stop_without_fitting_or_calling(self):
        ledger = json.loads(self.path.read_text())
        ledger["run_allowance_micros"] = 10000
        self.path.write_text(json.dumps(ledger), encoding="utf-8", newline="\n")
        stats = self.run_summary([self.story(), self.story("later")], {"first": ARTICLE})
        self.assertEqual(stats["error"], "paid_run_allowance")
        self.assertEqual(stats["candidates_tried"], 1)
        self.assertEqual(stats["requests"], 0)
        self.assertEqual(self.calls, [])

    def test_failed_settlement_reports_retained_ledger_charge(self):
        lock = self.path.with_suffix(".json.lock")
        self.addCleanup(lambda: lock.unlink(missing_ok=True))
        def locked_ledger(body, key, timeout):
            response = self.provider(body, key, timeout)
            lock.touch()
            return response
        stats = self.run_summary([self.story()], {"first": ARTICLE}, transport_fn=locked_ledger)
        estimate = len(gemini.encode_request(self.calls[0])) + gemini.MAX_OUTPUT_TOKENS
        self.assertEqual(stats["settled_tokens"], estimate)
        self.assertEqual(stats["settled_micros"], paid.total_micros(self.path, now=self.now))
        self.assertEqual(stats["accounting_error"], "paid_settlement_unconfirmed")

    def test_cli_logs_run_counters_and_cost_including_cache_only_run(self):
        source = self.path.parent / "radar.json"
        cache = self.path.parent / "summaries.json"
        source.write_text(json.dumps({"stories": [self.story()], "generated_at": "2026-10-11T17:00:00Z"}),
                          encoding="utf-8", newline="\n")
        with patch.object(gemini, "config_from_env", return_value=self.config), \
                patch.object(gemini, "transport", side_effect=self.provider), \
                patch.object(pipeline, "fetch_article_result", return_value=(ARTICLE, None)), \
                patch.object(pipeline.time, "time", return_value=self.now):
            logs = []
            for _ in range(2):
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(summarize.main(["--input", str(source), "--cache", str(cache)]), 0)
                lines = [line for line in output.getvalue().splitlines() if line.startswith("Summary run: ")]
                self.assertEqual(len(lines), 1)
                logs.append(json.loads(lines[0].removeprefix("Summary run: ")))
        self.assertEqual(logs[0], {
            "candidates_tried": 1, "reservations_refused": 0, "requests_sent": 1,
            "accepted": 1, "rejected": 0, "settled_micros": 1575, "settled_tokens": 420,
            "usage_tokens": 420, "accounting_error": None,
        })
        self.assertEqual(logs[1]["accepted"], 0)
        self.assertEqual(logs[1]["requests_sent"], 0)
        self.assertEqual(logs[1]["settled_micros"], 0)
        self.assertEqual(logs[1]["settled_tokens"], 0)


if __name__ == "__main__":
    unittest.main()

"""Offline provider orchestration checks; all inference is replaced at the boundary."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from radar import translate as nllb
from radar import translation_gemini as gemini
from radar import translation_pipeline as pipeline
from radar import gemini_paid_budget


TITLE = "How Claude is uplifting biomolecular modeling"
VI = "Làm thế nào Claude đang nâng cao mô hình hóa học"
SUMMARY = "Researchers explain how new tools improve scientific work."
SUMMARY_VI = "Các nhà nghiên cứu giải thích cách công cụ mới cải thiện công việc khoa học."


def inputs(body):
    for content in body["contents"]:
        for part in content["parts"]:
            try:
                value = json.loads(part.get("text", ""))
            except ValueError:
                continue
            if isinstance(value, dict) and "items" in value:
                return value["items"]
    raise AssertionError("REST request contains no structured input items")


def reply(rows, *, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"text": json.dumps({"translations": rows}, ensure_ascii=False)}]}}]}


def story(title=TITLE, **extra):
    return {"id": "s1", "title": title, "kind": "research", "groups": ["lab"],
            "coverage": [], **extra}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "attempts.json"
        self.network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.calls = []
        self.cache = {}

    def transport(self, body, key, timeout):
        self.calls.append((body, key, timeout))
        values = {TITLE: VI, SUMMARY: SUMMARY_VI}
        return reply([{"id": item["id"], "text": values[item["text"]]} for item in inputs(body)])

    def run_payload(self, payload, **options):
        defaults = dict(config=gemini.Config(api_key="offline-sentinel", confirmed=True),
                        transport=self.transport, ledger_path=self.ledger, budget=5,
                        factory=lambda: (_ for _ in ()).throw(ModuleNotFoundError("offline NLLB absent")))
        defaults.update(options)
        return pipeline.translate_payload(payload, {}, self.cache, **defaults)

    def test_batch_deduplicates_normalized_whole_strings_across_fields(self):
        title = TITLE.replace(" ", "  ")
        payload = {"stories": [story(title, summary=SUMMARY, coverage=[
            {"title": TITLE, "summary": SUMMARY}])],
            "repos": [{"id": "o/r", "description": TITLE}], "live": [{"title": TITLE}]}
        before = deepcopy(payload)
        stats, alive = self.run_payload(payload)
        self.assertFalse(alive)
        self.assertEqual(len(self.calls), 1)
        body, key, timeout = self.calls[0]
        self.assertEqual(key, "offline-sentinel")
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 5)
        self.assertEqual({item["text"] for item in inputs(body)}, {TITLE, SUMMARY})
        self.assertEqual(len(inputs(body)), 2)
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 8192)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["stories"][0]["title_vi"], VI)
        self.assertEqual(payload["stories"][0]["summary_vi"], SUMMARY_VI)
        self.assertEqual(payload["stories"][0]["coverage"][0]["summary_vi"], SUMMARY_VI)
        self.assertEqual(payload["repos"][0]["description_vi"], VI)
        self.assertEqual(payload["live"][0]["title_vi"], VI)
        for collection in ("stories", "repos", "live"):
            for original, translated in zip(before[collection], payload[collection]):
                for field in ("title", "summary", "description"):
                    if field in original:
                        self.assertEqual(translated[field], original[field])
        self.assertEqual(payload["translation"], stats)
        self.assertNotIn("offline-sentinel", json.dumps(stats))

    def test_api_receives_sentence_context_without_nllb_splitting(self):
        source = "Introducing Claude tools. Researchers explain the new results."
        translated = "Ra mắt công cụ Claude. Các nhà nghiên cứu giải thích kết quả mới."
        def transport(body, key, timeout):
            rows = inputs(body)
            self.assertEqual([row["text"] for row in rows], [source])
            return reply([{"id": rows[0]["id"], "text": translated}])
        payload = {"stories": [story(source)]}
        self.run_payload(payload, transport=transport)
        self.assertEqual(payload["stories"][0]["title_vi"], translated)

    def test_cached_api_strings_avoid_transport_and_nllb_loading(self):
        self.run_payload({"stories": [story()]})
        self.calls.clear()
        payload = {"stories": [story()]}
        def forbidden():
            self.fail("a valid cache hit must not load NLLB")
        self.run_payload(payload, factory=forbidden)
        self.assertEqual(self.calls, [])
        self.assertEqual(payload["stories"][0]["title_vi"], VI)

    def test_missing_key_or_confirmation_uses_nllb_without_api(self):
        for config in (gemini.Config(), gemini.Config(api_key="offline-sentinel"),
                       gemini.Config(confirmed=True)):
            with self.subTest(configured=bool(config.api_key), confirmed=config.confirmed):
                payload = {"stories": [story()]}
                self.run_payload(payload, config=config, factory=lambda: lambda batch: [VI for _ in batch])
                self.assertEqual(payload["stories"][0]["title_vi"], VI)
                self.assertEqual(self.calls, [])
                self.assertFalse(self.ledger.exists())

    def test_paid_switch_prefers_gemini_and_reconciles_provider_usage(self):
        paid_path = Path(self.tmp.name) / "paid-ledger.json"
        now = time.time()
        gemini_paid_budget.prepare(paid_path, paid=False, now=now, run_number=6)
        gemini_paid_budget.prepare(paid_path, paid=True, now=now, run_number=7)

        def paid_transport(body, key, timeout):
            result = self.transport(body, key, timeout)
            result["usageMetadata"] = {"totalTokenCount": 120}
            return result

        config = gemini.Config(api_key="offline-sentinel", paid=True, confirmed=True)
        with patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "7", "RADAR_GEMINI_PAID_LEDGER": str(paid_path)}):
            stats, _ = self.run_payload({"stories": [story()]}, config=config, transport=paid_transport)
        self.assertEqual(stats["provider"], "gemini")
        self.assertEqual(stats["gemini"]["status"], "ok")
        self.assertEqual(stats["gemini"]["tokens"], 120)
        self.assertEqual(gemini_paid_budget.total_micros(paid_path, now=now), 450)

    def test_monthly_cap_refuses_paid_translation_before_transport(self):
        paid_path = Path(self.tmp.name) / "paid-ledger.json"
        now = time.time()
        gemini_paid_budget.prepare(paid_path, paid=False, now=now, run_number=10)
        gemini_paid_budget.prepare(paid_path, paid=True, now=now, run_number=11)
        config = gemini.Config(api_key="offline-sentinel", paid=True, confirmed=True)
        with patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "11", "RADAR_GEMINI_PAID_LEDGER": str(paid_path),
                                     "RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "0.00001"}):
            payload = {"stories": [story()]}
            stats, _ = self.run_payload(payload, config=config,
                                        factory=lambda: lambda batch: [VI for _ in batch])
        self.assertEqual(self.calls, [])
        self.assertEqual(stats["gemini"]["error"], "paid_monthly_cap")
        self.assertEqual(stats["provider"], "nllb")

    def test_transport_errors_fall_back_without_exposing_exception_text(self):
        for error in (TimeoutError("offline-sentinel timeout"), OSError("offline-sentinel error")):
            with self.subTest(error=type(error).__name__):
                def failing(body, key, timeout):
                    raise error
                payload = {"stories": [story()]}
                output = io.StringIO()
                with redirect_stdout(output), redirect_stderr(output):
                    stats, alive = self.run_payload(payload, transport=failing,
                        factory=lambda: lambda batch: [VI for _ in batch])
                self.assertFalse(alive)
                self.assertEqual(payload["stories"][0]["title_vi"], VI)
                self.assertNotIn("offline-sentinel", output.getvalue() + json.dumps(stats))

    def test_http_status_reaches_snapshot_without_message_or_key(self):
        from unittest.mock import Mock
        from urllib.error import HTTPError
        body = json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                     "message": "offline-sentinel echoed text"}}).encode()
        opener = Mock()
        opener.open.side_effect = HTTPError("https://example.test/", 400, "offline-sentinel", {}, io.BytesIO(body))
        payload = {"stories": [story()]}
        with patch.object(gemini.urllib.request, "build_opener", return_value=opener):
            stats, alive = self.run_payload(payload, transport=gemini.transport)
        self.assertFalse(alive)
        self.assertEqual(stats["gemini"]["error"], "http_400:INVALID_ARGUMENT")
        self.assertEqual(opener.open.call_count, 1)
        self.assertNotIn("offline-sentinel", json.dumps(stats) + json.dumps(payload))

    def test_unsafe_provider_error_text_is_replaced_in_snapshot(self):
        for text in ("http_400:invalid offline-sentinel", "http_400:" + "A" * 41, "http_6000"):
            def failing(body, key, timeout, text=text):
                raise gemini.ProviderError(text)
            stats, _ = self.run_payload({"stories": [story()]}, transport=failing)
            self.assertEqual(stats["gemini"]["error"], "provider_error")

    def test_bad_api_outputs_leave_original_when_nllb_unavailable(self):
        bad = [reply([{"id": "0", "text": VI.replace("Claude", "tên bị dịch")}]),
               reply([{"id": "0", "text": VI}], finish="MAX_TOKENS"),
               {"promptFeedback": {"blockReason": "SAFETY"}},
               {"error": {"code": 429, "message": "offline-sentinel quota"}},
               {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not json"}]}}]},
               reply([{"id": "unknown", "text": VI}]),
               reply([{"id": "0", "text": VI}, {"id": "0", "text": VI}])]
        for response in bad:
            with self.subTest(response=response):
                payload = {"stories": [story(title_vi="stale")], "translation": {"status": "old"}}
                stats, alive = self.run_payload(payload, transport=lambda *args: response)
                self.assertFalse(alive)
                self.assertEqual(payload["stories"][0]["title"], TITLE)
                self.assertNotIn("title_vi", payload["stories"][0])
                self.assertNotIn("offline-sentinel", json.dumps(stats))
                self.assertNotEqual(stats["status"], "old")

    def test_invalid_api_cache_is_revalidated_before_display(self):
        self.cache[TITLE] = VI.replace("Claude", "tên bị dịch")
        payload = {"stories": [story(title_vi="stale")]}
        self.run_payload(payload, config=gemini.Config())
        self.assertNotIn("title_vi", payload["stories"][0])
        self.assertEqual(payload["stories"][0]["title"], TITLE)

    def test_nllb_only_rollback_ignores_api_cache_and_credentials(self):
        self.cache[TITLE] = VI
        payload = {"stories": [story()]}
        fallback = "Claude hỗ trợ các nhà nghiên cứu xây dựng mô hình hóa học"
        stats, _ = self.run_payload(payload, provider="nllb", factory=lambda: lambda batch: [fallback for _ in batch])
        self.assertEqual(self.calls, [])
        self.assertEqual(stats["provider"], "nllb")
        self.assertEqual(payload["stories"][0]["title_vi"], fallback)

    def test_stale_fields_are_cleared_when_source_disappears_or_becomes_an_event(self):
        payload = {"stories": [story(None, title_vi="stale", summary=None, summary_vi="stale",
                                    coverage=[{"title_vi": "stale", "summary_vi": "stale"}]),
                               story("Annual research conference", kind="event", title_vi="stale")],
                   "repos": [{"description_vi": "stale"}], "live": [{"title_vi": "stale"}]}
        self.run_payload(payload, config=gemini.Config())
        self.assertNotIn("stale", json.dumps(payload))
        self.assertIsNone(payload["stories"][0]["title"])

    def test_quotation_marks_survive_or_output_is_rejected(self):
        source = 'Mistral calls this work "a major advance" for researchers'
        good = 'Mistral gọi công trình này là "bước tiến lớn" cho các nhà nghiên cứu'
        for text, accepted in ((good, True), (good.replace('"', ''), False)):
            with self.subTest(accepted=accepted):
                self.cache.clear()
                payload = {"stories": [story(source)]}
                self.run_payload(payload, transport=lambda *args: reply([{"id": "0", "text": text}]))
                if accepted:
                    self.assertEqual(payload["stories"][0]["title_vi"], good)
                else:
                    self.assertNotIn("title_vi", payload["stories"][0])

    def test_curly_quotes_normalize_and_apostrophes_do_not_create_quotes(self):
        cases = [('Mistral calls this work “a major advance” for researchers',
                  'Mistral gọi công trình này là “bước tiến lớn” cho các nhà nghiên cứu'),
                 ("Mistral says researchers don't need to wait for results",
                  "Mistral nói các nhà nghiên cứu không cần chờ kết quả")]
        for source, translated in cases:
            with self.subTest(source=source):
                payload = {"stories": [story(source)]}
                self.run_payload(payload, transport=lambda *args: reply([{"id": "0", "text": translated}]))
                self.assertIn("title_vi", payload["stories"][0])

    def test_added_quotes_and_changed_names_within_quotes_are_rejected(self):
        cases = [(TITLE, VI.replace("Claude", '"Claude"')),
                 (TITLE, VI + '"'),
                 ('Researchers describe "Claude" as a useful scientific tool',
                  'Các nhà nghiên cứu mô tả "tên khác" là công cụ khoa học hữu ích')]
        for source, translated in cases:
            with self.subTest(source=source):
                payload = {"stories": [story(source)]}
                self.run_payload(payload, transport=lambda *args: reply([{"id": "0", "text": translated}]))
                self.assertNotIn("title_vi", payload["stories"][0])

    def test_unknown_multiword_product_identity_and_version_are_protected(self):
        source = "Introducing Quantum Leaf 2 for scientific discovery"
        translated = "Ra mắt Quantum Leaf 2 dành cho khám phá khoa học"
        for text, accepted in ((translated, True), (translated.replace("Leaf ", ""), False)):
            with self.subTest(accepted=accepted):
                self.cache.clear()
                payload = {"stories": [story(source)]}
                self.run_payload(payload, transport=lambda *args: reply([{"id": "0", "text": text}]))
                self.assertEqual("title_vi" in payload["stories"][0], accepted)

    def test_one_request_limit_and_lowered_input_budgets_leave_remainder_original(self):
        for config, maximum in ((gemini.Config(api_key="offline-sentinel", confirmed=True), 24),
                                (gemini.Config(api_key="offline-sentinel", confirmed=True,
                                               batch_size=3, max_chars=90), 2)):
            with self.subTest(maximum=maximum):
                self.cache.clear()
                self.calls.clear()
                payload = {"stories": [story(f"Researchers explain useful method number {i}", id=str(i))
                                       for i in range(30)]}
                def transport(body, key, timeout):
                    items = inputs(body)
                    self.calls.append(body)
                    self.assertLessEqual(len(items), config.batch_size)
                    self.assertLessEqual(sum(len(item["text"]) for item in items), config.max_chars)
                    return reply([{"id": item["id"], "text": "Bản dịch tiếng Việt cho " + item["text"]}
                                  for item in items])
                stats, _ = self.run_payload(payload, config=config, transport=transport)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(stats["gemini"]["requests"], 1)
                self.assertEqual(stats["gemini"]["translated"], maximum)
                self.assertEqual(stats["pending"], 30 - maximum)

    def test_failed_attempts_consume_daily_budget_and_next_run_makes_no_request(self):
        def failing(body, key, timeout):
            self.calls.append(body)
            raise TimeoutError("offline-sentinel")
        for attempt in range(13):
            stats, _ = self.run_payload({"stories": [story()]}, transport=failing, now=lambda: 100000.0)
        self.assertEqual(len(self.calls), 12)
        self.assertEqual(stats["gemini"]["requests"], 0)
        self.assertEqual(stats["gemini"]["error"], "daily_limit")

    def test_hung_transport_respects_deadline_and_cannot_later_mutate_snapshot_or_cache(self):
        release = threading.Event()
        finished = threading.Event()
        def hanging(body, key, timeout):
            release.wait(2)
            finished.set()
            return reply([{"id": "0", "text": VI}])
        payload = {"stories": [story()]}
        started = time.monotonic()
        try:
            stats, alive = self.run_payload(payload, transport=hanging, budget=0.05)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(alive)
            self.assertEqual(stats["gemini"]["error"], "timeout")
            self.assertNotIn("title_vi", payload["stories"][0])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
        self.assertEqual(self.cache, {})
        self.assertNotIn("title_vi", payload["stories"][0])

    def test_nllb_cache_never_blocks_gemini_upgrade_or_pollutes_api_cache(self):
        nllb_cache = {TITLE: "Claude hỗ trợ các nhà nghiên cứu xây dựng mô hình hóa học"}
        payload = {"stories": [story()]}
        stats, _ = pipeline.translate_payload(payload, nllb_cache, self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True), transport=self.transport,
            ledger_path=self.ledger, factory=lambda: self.fail("Gemini success needs no NLLB load"), budget=5)
        self.assertEqual(stats["provider"], "gemini")
        self.assertEqual(payload["stories"][0]["title_vi"], VI)
        self.assertEqual(self.cache[TITLE], VI)
        self.assertNotEqual(nllb_cache[TITLE], self.cache[TITLE])

    def test_cli_persists_validated_api_cache_attempt_ledger_and_safe_metadata(self):
        src = Path(self.tmp.name) / "radar.json"
        cache = Path(self.tmp.name) / "nllb.json"
        gh = Path(self.tmp.name) / "github-output.txt"
        src.write_bytes(json.dumps({"stories": [story(summary=SUMMARY)]}).encode())
        output = io.StringIO()
        environment = {"GEMINI_API_KEY": "offline-sentinel", "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
                       "GITHUB_OUTPUT": str(gh)}
        with patch.dict("os.environ", environment, clear=True), \
                patch.object(gemini, "transport", self.transport), \
                patch.object(nllb, "nllb_factory", side_effect=AssertionError("no NLLB needed")), \
                redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(nllb.main(["--input", str(src), "--cache", str(cache), "--budget", "5"]), 0)
        payload = json.loads(src.read_text(encoding="utf-8"))
        self.assertEqual(payload["translation"]["provider"], "gemini")
        self.assertEqual(payload["stories"][0]["summary_vi"], SUMMARY_VI)
        from radar.site_payload import page_path, page_payload
        self.assertEqual(json.loads(page_path(src).read_text(encoding="utf-8")), page_payload(payload))
        self.assertEqual(gemini.load_cache(cache.with_name("translations-gemini-vi.json"))[TITLE], VI)
        self.assertTrue(cache.with_name("translation-gemini-attempts.json").exists())
        self.assertFalse(cache.exists())
        self.assertIn("gemini_cache_written=true", gh.read_text())
        self.assertIn("gemini_ledger_written=true", gh.read_text())
        artifacts = "".join(path.read_text(encoding="utf-8") for path in Path(self.tmp.name).iterdir())
        self.assertNotIn("offline-sentinel", artifacts + output.getvalue())

    def test_cli_no_key_keeps_original_and_reports_fallback_without_network(self):
        src = Path(self.tmp.name) / "radar.json"
        src.write_bytes(json.dumps({"stories": [story(title_vi="stale")]}).encode())
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(gemini, "transport", side_effect=AssertionError("no API allowed")) as transport, \
                patch.object(nllb, "nllb_factory", side_effect=ModuleNotFoundError("offline NLLB absent")), \
                redirect_stdout(io.StringIO()):
            code = nllb.main(["--input", str(src), "--cache", str(Path(self.tmp.name) / "cache.json"),
                              "--budget", "5"])
        self.assertEqual(code, 0)
        transport.assert_not_called()
        payload = json.loads(src.read_text(encoding="utf-8"))
        self.assertEqual(payload["translation"]["provider"], "original")
        self.assertEqual(payload["translation"]["gemini"]["error"], "missing_key")
        from radar.site_payload import page_path, page_payload
        self.assertEqual(json.loads(page_path(src).read_text(encoding="utf-8")), page_payload(payload))
        self.assertEqual(payload["stories"][0]["title"], TITLE)
        self.assertNotIn("title_vi", payload["stories"][0])

    def test_rejected_first_batch_does_not_starve_later_sources_on_next_run(self):
        sources = [f"Researchers explain useful method number {i}" for i in range(25)]
        batches = []
        def transport(body, key, timeout):
            items = inputs(body)
            batches.append([item["text"] for item in items])
            return reply([{"id": item["id"], "text": "" if item["text"] != sources[-1]
                           else "Bản dịch tiếng Việt cho " + item["text"]} for item in items])
        for run in range(2):
            payload = {"stories": [story(source, id=str(i)) for i, source in enumerate(sources)]}
            self.run_payload(payload, transport=transport, now=lambda: 100000.0 + run)
            for row in payload["stories"][:-1]:
                self.assertNotIn("title_vi", row)
        self.assertEqual(len(batches[0]), 24)
        self.assertNotIn(sources[-1], batches[0])
        self.assertIn(sources[-1], batches[1])
        self.assertIn("title_vi", payload["stories"][-1])
        calls = len(batches)
        self.run_payload({"stories": [story(sources[-1])]}, transport=transport, now=lambda: 100002.0)
        self.assertEqual(len(batches), calls, "successful output must still use its cache")

    def test_cli_cache_and_workflow_output_failures_preserve_successful_snapshot(self):
        src = Path(self.tmp.name) / "radar.json"
        cache = Path(self.tmp.name) / "nllb.json"
        src.write_bytes(json.dumps({"stories": [story()]}).encode())
        environment = {"GEMINI_API_KEY": "offline-sentinel", "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
                       "GITHUB_OUTPUT": self.tmp.name}
        output = io.StringIO()
        with patch.dict("os.environ", environment, clear=True), \
                patch.object(gemini, "transport", self.transport), \
                patch.object(gemini, "save_cache", side_effect=OSError("offline-sentinel write failure")), \
                patch.object(nllb, "nllb_factory", side_effect=AssertionError("no NLLB needed")), \
                redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(nllb.main(["--input", str(src), "--cache", str(cache), "--budget", "5"]), 0)
        payload = json.loads(src.read_text(encoding="utf-8"))
        self.assertEqual(payload["stories"][0]["title_vi"], VI)
        self.assertIn("gemini_cache_write_failed", payload["translation"]["persistence_errors"])
        self.assertIn("workflow_output_write_failed", payload["translation"]["persistence_errors"])
        self.assertNotIn("offline-sentinel", json.dumps(payload) + output.getvalue())

    def test_cli_replacement_with_same_cache_size_is_persisted(self):
        src = Path(self.tmp.name) / "radar.json"
        cache = Path(self.tmp.name) / "cache.json"
        api_cache = cache.with_name("translations-gemini-vi.json")
        gh = Path(self.tmp.name) / "github-output.txt"
        src.write_bytes(json.dumps({"stories": [story()]}).encode())
        gemini.save_cache(api_cache, {TITLE: VI.replace("Claude", "tên sai")})
        environment = {"GEMINI_API_KEY": "offline-sentinel", "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
                       "GITHUB_OUTPUT": str(gh)}
        with patch.dict("os.environ", environment, clear=True), \
                patch.object(gemini, "transport", self.transport), \
                patch.object(nllb, "nllb_factory", side_effect=AssertionError("no NLLB needed")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(nllb.main(["--input", str(src), "--cache", str(cache), "--budget", "5"]), 0)
        self.assertEqual(gemini.load_cache(api_cache), {TITLE: VI})
        self.assertIn("gemini_cache_written=true", gh.read_text())

    def test_nllb_fallback_exception_diagnostics_do_not_expose_credentials(self):
        src = Path(self.tmp.name) / "radar.json"
        src.write_bytes(json.dumps({"stories": [story()]}).encode())
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(gemini, "transport", side_effect=AssertionError("no API allowed")) as transport, \
                patch.object(nllb, "nllb_factory", side_effect=RuntimeError("offline-sentinel")), \
                redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(nllb.main(["--input", str(src), "--cache", str(Path(self.tmp.name) / "cache.json"),
                                       "--budget", "5"]), 0)
        transport.assert_not_called()
        self.assertNotIn("offline-sentinel", src.read_text(encoding="utf-8") + output.getvalue())

    def test_provider_fails_fallback_yields_nothing_survives_for_all_existing_stories(self):
        """When Gemini returns 503 and NLLB produces nothing, all previously published
        translations survive for every story that still exists, while new stories stay untranslated."""
        title_2 = "DeepMind announces Gemini 4 breakthrough"
        vi_2 = "DeepMind công bố bước đột phá Gemini 4"
        summary_2 = "New multimodal architecture enables realtime audio and visual processing."
        summary_vi_2 = "Kiến trúc đa phương thức mới cho phép xử lý âm thanh và hình ảnh theo thời gian thực."
        new_title = "Anthropic announces Claude 5 developer tools"
        new_summary = "Developer tools include prompt caching and batch evaluation."

        payload = {
            "stories": [
                {"id": "s1", "title": TITLE, "title_vi": VI, "summary": SUMMARY, "summary_vi": SUMMARY_VI,
                 "kind": "research", "coverage": [{"title": TITLE, "title_vi": VI}]},
                {"id": "s2", "title": title_2, "title_vi": vi_2, "summary": summary_2, "summary_vi": summary_vi_2,
                 "kind": "product", "coverage": []},
                {"id": "s3", "title": new_title, "summary": new_summary, "kind": "product", "coverage": []},
            ],
            "repos": [{"id": "o/r", "description": TITLE, "description_vi": VI}],
            "live": [{"title": title_2, "title_vi": vi_2}],
            "sources": []
        }

        def failing_transport(*args):
            raise gemini.ProviderError("http_503:UNAVAILABLE")

        def failing_factory():
            raise ModuleNotFoundError("offline NLLB absent")

        stats, alive = self.run_payload(
            payload,
            transport=failing_transport,
            factory=failing_factory
        )

        self.assertFalse(alive)
        self.assertEqual(stats["gemini"]["status"], "failed")
        self.assertEqual(stats["gemini"]["error"], "http_503:UNAVAILABLE")
        self.assertEqual(stats["provider"], "kept")
        self.assertEqual(stats["provider_counts"]["kept"], 4)
        self.assertEqual(stats["kept_published"], 4)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["status"], "partial")

        # Every previously translated field on existing stories survives
        self.assertEqual(payload["stories"][0]["title_vi"], VI)
        self.assertEqual(payload["stories"][0]["summary_vi"], SUMMARY_VI)
        self.assertEqual(payload["stories"][0]["coverage"][0]["title_vi"], VI)
        self.assertEqual(payload["stories"][1]["title_vi"], vi_2)
        self.assertEqual(payload["stories"][1]["summary_vi"], summary_vi_2)
        self.assertEqual(payload["repos"][0]["description_vi"], VI)
        self.assertEqual(payload["live"][0]["title_vi"], vi_2)

        # The new story without translation remains untranslated
        self.assertNotIn("title_vi", payload["stories"][2])
        self.assertNotIn("summary_vi", payload["stories"][2])

        # Kept translations must NEVER pollute gemini_cache
        self.assertEqual(self.cache, {})

        # On the next run when the provider recovers, fresh translation replaces the kept one
        def recovered_transport(body, key, timeout):
            fresh_title = "Claude nâng cao mô hình hóa sinh học như thế nào"
            return reply([{"id": item["id"], "text": fresh_title if item["text"] == TITLE else "bản dịch"}
                          for item in inputs(body)])

        next_payload = {
            "stories": [
                {"id": "s1", "title": TITLE, "title_vi": VI, "kind": "research", "coverage": []}
            ],
            "sources": []
        }
        next_stats, _ = self.run_payload(next_payload, transport=recovered_transport)
        self.assertEqual(next_stats["provider"], "gemini")
        self.assertEqual(next_payload["stories"][0]["title_vi"], "Claude nâng cao mô hình hóa sinh học như thế nào")
        self.assertEqual(self.cache[TITLE], "Claude nâng cao mô hình hóa sinh học như thế nào")

    def test_previous_snapshot_threaded_or_passed_restores_translations(self):
        """If current payload has stripped fields (e.g. from build.py), passing previous snapshot restores them."""
        previous_snapshot = {
            "stories": [
                {"id": "s1", "title": TITLE, "title_vi": VI, "summary": SUMMARY, "summary_vi": SUMMARY_VI,
                 "kind": "research", "coverage": []}
            ]
        }
        payload = {
            "stories": [
                {"id": "s1", "title": TITLE, "summary": SUMMARY, "kind": "research", "coverage": []}
            ],
            "sources": []
        }

        def failing_transport(*args):
            raise gemini.ProviderError("http_503:UNAVAILABLE")

        def failing_factory():
            raise ModuleNotFoundError("offline NLLB absent")

        stats, _ = self.run_payload(
            payload,
            transport=failing_transport,
            factory=failing_factory,
            previous=previous_snapshot
        )
        self.assertEqual(stats["provider"], "kept")
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(payload["stories"][0]["title_vi"], VI)
        self.assertEqual(payload["stories"][0]["summary_vi"], SUMMARY_VI)

    def test_cli_previous_option_restores_translations_when_provider_fails(self):
        """CLI --previous argument provides prior translations when provider fails."""
        src = Path(self.tmp.name) / "radar.json"
        prev = Path(self.tmp.name) / "previous-radar.json"
        cache = Path(self.tmp.name) / "cache.json"

        prev.write_bytes(json.dumps({
            "stories": [{"id": "s1", "title": TITLE, "title_vi": VI, "summary": SUMMARY, "summary_vi": SUMMARY_VI,
                         "kind": "research", "coverage": []}]
        }).encode())
        src.write_bytes(json.dumps({
            "stories": [{"id": "s1", "title": TITLE, "summary": SUMMARY, "kind": "research", "coverage": []}]
        }).encode())

        def failing_transport(*args):
            raise gemini.ProviderError("http_503:UNAVAILABLE")

        with patch.dict("os.environ", {"GEMINI_API_KEY": "offline-sentinel", "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1"}, clear=True), \
                patch.object(gemini, "transport", failing_transport), \
                patch.object(nllb, "nllb_factory", side_effect=ModuleNotFoundError("offline NLLB absent")), \
                redirect_stdout(io.StringIO()):
            code = nllb.main(["--input", str(src), "--cache", str(cache), "--previous", str(prev), "--budget", "5"])

        self.assertEqual(code, 0)
        out = json.loads(src.read_text(encoding="utf-8"))
        self.assertEqual(out["translation"]["provider"], "kept")
        self.assertEqual(out["stories"][0]["title_vi"], VI)
        self.assertEqual(out["stories"][0]["summary_vi"], SUMMARY_VI)


if __name__ == "__main__":
    unittest.main()

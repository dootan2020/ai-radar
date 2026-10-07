"""Offline unit and integration tests for story summarization.

Covers:
- Multi-source story summarization
- Thin single-source story (1 point only, padding rejection)
- Budget exhausted (request & token ceiling)
- Ledger missing / invalid / lost (fails closed)
- Cache hit (zero API calls, zero token consumption)
- Invented-fact rejection (ungrounded numbers, ungrounded entities)
- CLI execution and site projection preservation
"""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from radar import summary_budget, summary_gemini as gemini, summary_pipeline
from radar import gemini_paid_budget
from radar.transport import ResponseText
from radar import summarize
from radar.site_payload import page_path, page_payload


def reply_summary(rows, tokens=350, finish="STOP"):
    return {
        "candidates": [{
            "finishReason": finish,
            "content": {"parts": [{"text": json.dumps({"summaries": rows}, ensure_ascii=False)}]}
        }],
        "usageMetadata": {
            "promptTokenCount": 200,
            "candidatesTokenCount": 150,
            "totalTokenCount": tokens
        }
    }


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.ledger_path = self.tmp_path / "summary-ledger.json"
        self.cache_path = self.tmp_path / "summaries-cache.json"
        summary_budget.init_ledger(self.ledger_path)

        # Strictly forbid any real network connections
        self.network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

        self.calls = []
        self.cache = {}

        # Load real fixture for authentic story structure
        fixture_path = Path(__file__).parent / "fixtures" / "edition-real-snapshot.json"
        self.fixture_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        article = ("Apple thay đổi cách quản lý quyền truy cập Full Disk Access trên macOS. "
                   "Các agent AI cần xin xác nhận trước khi đọc dữ liệu người dùng. "
                   "Bài viết mô tả tác động của thay đổi tới ứng dụng và quy trình bảo mật. "
                   "Tác giả giải thích vì sao yêu cầu xác nhận ảnh hưởng tới cách các agent vận hành, "
                   "đồng thời nêu rõ quy trình mới tác động tới các ứng dụng và quyền truy cập.")
        robots = patch.object(summary_pipeline.shadow_collector, "check_robots",
                              return_value={"robots_status": 200, "disallowed": False})
        robots.start()
        self.addCleanup(robots.stop)
        def read_article(url, **kwargs):
            return ResponseText(f"<article><p>{article}</p></article>", status=200,
                                url=url, content_type="text/html; charset=utf-8")
        reader = patch.object(summary_pipeline.transport, "read_url", side_effect=read_article)
        reader.start()
        self.addCleanup(reader.stop)

    def transport_ok(self, body, key, timeout):
        self.calls.append((body, key, timeout))
        # Generate valid Vietnamese key points based on story IDs in request
        stories_in = body["contents"][0]["parts"][0]["text"]
        parsed = json.loads(stories_in)["stories"]
        rows = []
        for s in parsed:
            pts = [
                "Apple thay đổi cách quản lý quyền Full Disk Access trên macOS.",
                "Agent AI cần xin xác nhận trước khi đọc dữ liệu người dùng.",
                "Bài viết nêu tác động tới ứng dụng và quy trình bảo mật."
            ]
            rows.append({"id": s["id"], "key_points": pts})
        return reply_summary(rows, tokens=420)

    def test_multi_source_story_summarization(self):
        """A story with multiple sources receives synthesized key points combining coverage."""
        # Find multi-source story from fixture: b3857f26daabd24cdab2 (Apple macOS)
        multi_story = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        payload = {"stories": [deepcopy(multi_story)]}

        config = gemini.Config(api_key="offline-sentinel", confirmed=True)
        stats, alive = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=config,
            transport_fn=self.transport_ok,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100000.0,
        )

        self.assertFalse(alive)
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(stats["cache_hits"], 0)
        self.assertEqual(stats["tokens"], 420)

        story = payload["stories"][0]
        self.assertIn("key_points", story)
        self.assertEqual(len(story["key_points"]), 3)
        self.assertNotIn("_summary_article_text", story)
        request_stories = json.loads(self.calls[0][0]["contents"][0]["parts"][0]["text"])["stories"]
        self.assertIn("article_text", request_stories[0])
        self.assertIn("Apple thay đổi cách quản lý", request_stories[0]["article_text"])
        self.assertTrue(story["key_points_machine"])
        self.assertEqual(story["key_points_source"], "machine")
        self.assertIn("Apple", story["key_points"][0])

    def test_article_fetch_requires_allowed_robots_and_semantic_html(self):
        url = "https://publisher.example/story"
        story = {"url": url, "coverage": []}
        body = " ".join(["The article opening describes the reported event and its implications."] * 8)
        page = ResponseText(
            f"<html><body><h1>Headline only</h1><article><p>{body}</p><script>hidden</script></article></body></html>",
            status=200, url=url, content_type="text/html; charset=utf-8",
        )
        with patch.object(summary_pipeline.shadow_collector, "check_robots",
                          return_value={"robots_status": 200, "disallowed": False}) as robots, \
                patch.object(summary_pipeline.transport, "read_url", return_value=page) as read:
            text = summary_pipeline.fetch_article_text(story)
        self.assertIn("reported event", text)
        self.assertNotIn("Headline only", text)
        self.assertNotIn("hidden", text)
        robots.assert_called_once()
        read.assert_called_once_with(url, allow_redirects=False)

        with patch.object(summary_pipeline.shadow_collector, "check_robots",
                          return_value={"robots_status": 403, "disallowed": False}), \
                patch.object(summary_pipeline.transport, "read_url") as read:
            self.assertEqual(summary_pipeline.fetch_article_text(story), "")
        read.assert_not_called()

        paywall = ResponseText(
            "<article>Subscribe to continue reading. " + "Please subscribe to read more. " * 15 + "</article>",
            status=200, url=url, content_type="text/html",
        )
        with patch.object(summary_pipeline.shadow_collector, "check_robots",
                          return_value={"robots_status": 404, "disallowed": False}), \
                patch.object(summary_pipeline.transport, "read_url", return_value=paywall):
            self.assertEqual(summary_pipeline.fetch_article_text(story), "")

    def test_article_fetch_skips_redirect_and_non_html(self):
        url = "https://publisher.example/story"
        story = {"url": url, "coverage": []}
        with patch.object(summary_pipeline.shadow_collector, "check_robots",
                          return_value={"robots_status": 404, "disallowed": False}):
            for response in (
                ResponseText("<article>" + "x" * 400 + "</article>", status=200,
                             url="https://other.example/story", content_type="text/html"),
                ResponseText("<article>" + "x" * 400 + "</article>", status=200,
                             url=url, content_type="application/pdf"),
            ):
                with patch.object(summary_pipeline.transport, "read_url", return_value=response):
                    self.assertEqual(summary_pipeline.fetch_article_text(story), "")

    def test_daily_budget_bounds_72_scheduler_runs(self):
        """The request and token ledgers cap 72 scheduled executions to 8 stories/day."""
        workflow_runs = 24 * 60 // 20
        per_run_requests = gemini.Config().max_requests
        possible_requests = min(workflow_runs * per_run_requests,
                                gemini.Config().daily_requests_limit)
        stories_per_day = min(possible_requests,
                              summary_budget.DEFAULT_DAILY_TOKENS // summary_budget.ESTIMATED_TOKENS_PER_REQUEST)
        self.assertEqual(workflow_runs, 72)
        self.assertEqual(possible_requests, 12)
        self.assertEqual(stories_per_day, summary_budget.MAX_STORIES_PER_DAY)
        self.assertEqual(stories_per_day, 8)
        self.assertLessEqual(stories_per_day * summary_budget.ESTIMATED_TOKENS_PER_REQUEST,
                             summary_budget.DEFAULT_DAILY_TOKENS)
        self.assertGreater((stories_per_day + 1) * summary_budget.ESTIMATED_TOKENS_PER_REQUEST,
                           summary_budget.DEFAULT_DAILY_TOKENS)

    def test_paid_mode_summarizes_beyond_free_tier_daily_ledger(self):
        now = 100000.0
        paid_path = self.tmp_path / "paid-ledger.json"
        gemini_paid_budget.prepare(paid_path, paid=False, now=now, run_number=20)
        gemini_paid_budget.prepare(paid_path, paid=True, now=now, run_number=21)
        for index in range(summary_budget.DEFAULT_DAILY_REQUESTS):
            summary_budget.reserve(self.ledger_path, now=now - 3600 + index, estimated_tokens=100)
        story = deepcopy(self.fixture_data["stories"][0])
        config = gemini.Config(api_key="offline-sentinel", confirmed=True, paid=True)
        with patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "21", "RADAR_GEMINI_PAID_LEDGER": str(paid_path)}):
            stats, _ = summary_pipeline.summarize_payload(
                {"stories": [story]}, self.cache, config=config, transport_fn=self.transport_ok,
                ledger_path=self.ledger_path, budget=10.0, now=lambda: now,
            )
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["error"], None)

    def test_no_article_text_clears_old_points_without_calling_model(self):
        story = deepcopy(self.fixture_data["stories"][0])
        story["key_points"] = ["Điểm cũ chỉ nhắc lại tiêu đề của bài viết."]
        story["key_points_machine"] = True
        story["key_points_source"] = "machine"
        payload = {"stories": [story]}
        stats, _ = summary_pipeline.summarize_payload(
            payload, self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            article_fetch_fn=lambda _: "",
            ledger_path=self.ledger_path, budget=10.0, now=lambda: 100000.0,
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["requests"], 0)
        self.assertEqual(self.calls, [])
        self.assertNotIn("key_points", story)
        self.assertNotIn("key_points_machine", story)
        self.assertNotIn("_summary_article_text", story)

    def test_stale_points_are_removed_from_stories_after_lazy_fetch_break(self):
        base = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        first, later = deepcopy(base), deepcopy(base)
        first.update(id="reachable", worth_score=90)
        later.update(id="not-reached", worth_score=10, key_points=["Điểm cũ."],
                     key_points_machine=True, key_points_source="machine",
                     key_points_prompt_version="summary-vi-2")
        payload = {"stories": [first, later]}
        stats, _ = summary_pipeline.summarize_payload(
            payload, self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            article_fetch_fn=lambda _: "Bài báo mô tả thay đổi Apple và tác động đến ứng dụng, quyền truy cập và bảo mật. " * 5,
            ledger_path=self.ledger_path, budget=10.0, now=lambda: 100000.0,
        )
        self.assertEqual(stats["requests"], 1)
        self.assertNotIn("key_points", later)
        self.assertNotIn("key_points_prompt_version", later)

    def test_503_retries_once_and_reserves_both_requests(self):
        attempts = []

        def flaky_transport(body, key, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise gemini.ProviderError("http_503:UNAVAILABLE")
            return self.transport_ok(body, key, timeout)

        story = deepcopy(self.fixture_data["stories"][0])
        payload = {"stories": [story]}
        with patch.object(summary_pipeline.time, "sleep") as sleep:
            stats, _ = summary_pipeline.summarize_payload(
                payload, self.cache,
                config=gemini.Config(api_key="offline-sentinel", confirmed=True),
                transport_fn=flaky_transport,
                ledger_path=self.ledger_path, budget=10.0, now=lambda: 100000.0,
            )
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(stats["requests"], 2)
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(len(ledger["attempts"]), 2)
        sleep.assert_called_once_with(summary_pipeline.SUMMARY_RETRY_DELAY)

    def test_two_503_responses_stop_after_retry(self):
        attempts = []

        def unavailable(*_):
            attempts.append(1)
            raise gemini.ProviderError("http_503:UNAVAILABLE")

        payload = {"stories": [deepcopy(self.fixture_data["stories"][0])]}
        with patch.object(summary_pipeline.time, "sleep"):
            stats, alive = summary_pipeline.summarize_payload(
                payload, self.cache,
                config=gemini.Config(api_key="offline-sentinel", confirmed=True),
                transport_fn=unavailable,
                ledger_path=self.ledger_path, budget=10.0, now=lambda: 100000.0,
            )
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertFalse(alive)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(stats["requests"], 2)
        self.assertEqual(stats["error"], "http_503:UNAVAILABLE")
        self.assertEqual(len(ledger["attempts"]), 2)
        self.assertNotIn("key_points", payload["stories"][0])

    def test_fetch_stops_after_request_batch_is_ready(self):
        base = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        stories = []
        for index, score in enumerate((90, 80, 70)):
            story = deepcopy(base)
            story["id"] = f"lazy-{index}"
            story["worth_score"] = score
            stories.append(story)
        fetches = []

        def fetch(story):
            fetches.append(story["id"])
            return "Bài báo mô tả các thay đổi của Apple và tác động tới ứng dụng, quyền truy cập cùng quy trình bảo mật. " * 5

        payload = {"stories": stories}
        stats, _ = summary_pipeline.summarize_payload(
            payload, self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True, batch_size=1),
            transport_fn=self.transport_ok, article_fetch_fn=fetch,
            ledger_path=self.ledger_path, budget=10.0, now=lambda: 100000.0,
        )
        requested = json.loads(self.calls[0][0]["contents"][0]["parts"][0]["text"])["stories"]
        self.assertEqual(fetches, ["lazy-0"])
        self.assertEqual([row["id"] for row in requested], ["lazy-0"])
        self.assertEqual(stats["requests"], 1)

    def test_remembered_unreadable_page_is_not_fetched_again(self):
        story = deepcopy(self.fixture_data["stories"][0])
        payload = {"stories": [story]}
        failures = {}
        fetches = []

        def unreadable(current):
            fetches.append(current["id"])
            return ""

        for _ in range(2):
            stats, _ = summary_pipeline.summarize_payload(
                payload, self.cache,
                config=gemini.Config(api_key="offline-sentinel", confirmed=True),
                transport_fn=self.transport_ok, article_fetch_fn=unreadable,
                article_failures=failures, ledger_path=self.ledger_path,
                budget=10.0, now=lambda: 100000.0,
            )
            self.assertEqual(stats["skipped_reasons"], {"too_short": 1})
        self.assertEqual(fetches, [story["id"]])
        self.assertEqual(len(failures), 1)
        entry = next(iter(failures.values()))
        self.assertEqual(set(entry), {"reason", "time"})
        self.assertEqual(entry["reason"], "too_short")
        self.assertEqual(entry["time"], 100000.0)

    def test_article_backed_story_requires_three_points_and_rejects_padding(self):
        """Article text makes the input substantive; fewer than 3 points is rejected."""
        thin_story = next(s for s in self.fixture_data["stories"] if s["id"] == "b4f19348ce95610ceeee")
        inputs = summary_pipeline.story_inputs(thin_story)
        self.assertTrue(summary_pipeline.is_thin_story(inputs))

        # 1 valid point on thin story is accepted
        valid_one_point = ["Nghiên cứu phân tích các rủi ro của trí tuệ nhân tạo tiên phong."]
        cleaned, reason = summary_pipeline.validate_key_points(inputs, valid_one_point)
        self.assertIsNone(reason)
        self.assertEqual(cleaned, valid_one_point)

        # 2 or more points on thin story is rejected as padding
        padded_points = [
            "Nghiên cứu phân tích các rủi ro của trí tuệ nhân tạo tiên phong.",
            "Tác giả đưa ra các kịch bản bùng nổ trí tuệ nhân tạo trong tương lai."
        ]
        rejected_pts, reject_reason = summary_pipeline.validate_key_points(inputs, padded_points)
        self.assertIsNone(rejected_pts)
        self.assertIn("padding_rejected", reject_reason)

        # When the model attempts to return padded points for a thin story in the pipeline:
        def transport_padded(body, key, timeout):
            return reply_summary([{
                "id": thin_story["id"],
                "key_points": padded_points
            }])

        payload = {"stories": [deepcopy(thin_story)]}
        stats, _ = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=transport_padded,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100000.0,
        )

        # The padded story must be rejected and left without key points (no stubs)
        self.assertEqual(stats["summarized"], 0)
        self.assertEqual(stats["rejected"], 1)
        self.assertNotIn("key_points", payload["stories"][0])
        self.assertNotIn("key_points_machine", payload["stories"][0])

    def test_budget_exhausted_fails_closed_without_stubs(self):
        """When request or token limit is reached, pipeline stops and leaves stories without key points."""
        story = deepcopy(self.fixture_data["stories"][0])

        # Fill up request ledger with 12 attempts
        now = 100000.0
        for _ in range(12):
            err = summary_budget.reserve(self.ledger_path, request_limit=12, token_limit=25000,
                                         estimated_tokens=500, now=now)
            self.assertIsNone(err)

        # Attempt 13 should fail closed with daily_limit
        payload = {"stories": [story]}
        stats, _ = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: now + 10,
        )

        self.assertEqual(stats["status"], "failed")
        self.assertEqual(stats["error"], "daily_limit")
        self.assertEqual(stats["requests"], 0)
        self.assertEqual(len(self.calls), 0)
        self.assertNotIn("key_points", payload["stories"][0])

        # Test token ceiling exhaustion
        token_ledger = self.tmp_path / "token-ledger.json"
        summary_budget.init_ledger(token_ledger)
        # Reserve up to token ceiling limit
        err = summary_budget.reserve(token_ledger, request_limit=12, token_limit=1000,
                                     estimated_tokens=950, now=now)
        self.assertIsNone(err)
        # Next reservation exceeding token ceiling fails closed with daily_token_limit
        err_tok = summary_budget.reserve(token_ledger, request_limit=12, token_limit=1000,
                                         estimated_tokens=200, now=now + 5)
        self.assertEqual(err_tok, "daily_token_limit")

    def test_corrupt_or_invalid_ledger_refuses(self):
        """Unreadable, corrupted, or future-dated ledger refuses without making API requests."""
        # Test corrupt ledger (invalid JSON)
        corrupt_ledger = self.tmp_path / "corrupt-ledger.json"
        corrupt_ledger.write_text("not json", encoding="utf-8")
        err = summary_budget.reserve(corrupt_ledger, now=100000.0)
        self.assertEqual(err, "ledger_invalid")

        # In pipeline, corrupt ledger fails closed safely without API call
        payload = {"stories": [deepcopy(self.fixture_data["stories"][0])]}
        stats, _ = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            ledger_path=corrupt_ledger,
            budget=10.0,
            now=lambda: 100000.0,
        )
        self.assertEqual(stats["status"], "failed")
        self.assertEqual(stats["error"], "ledger_invalid")
        self.assertEqual(len(self.calls), 0)
        self.assertNotIn("key_points", payload["stories"][0])

        # Future timestamp in ledger
        future_ledger = self.tmp_path / "future-ledger.json"
        future_ledger.write_text(json.dumps({"version": 1, "attempts": [999999.0]}), encoding="utf-8")
        err_future = summary_budget.reserve(future_ledger, now=100000.0)
        self.assertEqual(err_future, "ledger_invalid")

        # Invalid schema (wrong version or non-list attempts)
        bad_version_ledger = self.tmp_path / "bad-version-ledger.json"
        bad_version_ledger.write_text(json.dumps({"version": 99, "attempts": []}), encoding="utf-8")
        self.assertEqual(summary_budget.reserve(bad_version_ledger, now=100000.0), "ledger_invalid")

    def test_first_run_without_ledger_summarises_and_writes_ledger(self):
        """A first run with no ledger file starts a fresh one, summarises stories, and writes the ledger."""
        fresh_ledger = self.tmp_path / "fresh-first-run-ledger.json"
        self.assertFalse(fresh_ledger.exists())

        story = deepcopy(self.fixture_data["stories"][0])
        payload = {"stories": [story]}

        stats, alive = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            ledger_path=fresh_ledger,
            budget=10.0,
            now=lambda: 100000.0,
        )

        self.assertFalse(alive)
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(len(self.calls), 1)

        # Story has key points assigned
        self.assertIn("key_points", payload["stories"][0])
        self.assertTrue(payload["stories"][0]["key_points_machine"])
        self.assertEqual(payload["stories"][0]["key_points_source"], "machine")

        # Ledger file now exists and contains the attempt with recorded tokens
        self.assertTrue(fresh_ledger.exists())
        data = json.loads(fresh_ledger.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["attempts"]), 1)
        self.assertEqual(data["attempts"][0]["time"], 100000.0)
        self.assertEqual(data["attempts"][0]["tokens"], 420)

    def test_cache_hit_bypasses_transport_and_conserves_budget(self):
        """Unchanged story content hits cache: zero API requests, zero tokens consumed."""
        multi_story = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        payload1 = {"stories": [deepcopy(multi_story)]}

        # First run: populates cache via API call
        stats1, _ = summary_pipeline.summarize_payload(
            payload1,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100000.0,
        )
        self.assertEqual(stats1["summarized"], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(stats1["tokens"], 420)

        # Clear calls
        self.calls.clear()

        # Second run: identical story content must hit cache
        payload2 = {"stories": [deepcopy(multi_story)]}
        stats2, _ = summary_pipeline.summarize_payload(
            payload2,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100005.0,
        )

        self.assertEqual(len(self.calls), 0, "A valid cache hit must make 0 API requests")
        self.assertEqual(stats2["cache_hits"], 1)
        self.assertEqual(stats2["summarized"], 0)
        self.assertEqual(stats2["tokens"], 0)
        self.assertEqual(stats2["status"], "cache")
        self.assertEqual(payload2["stories"][0]["key_points"], payload1["stories"][0]["key_points"])
        self.assertTrue(payload2["stories"][0]["key_points_machine"])

    def test_invented_fact_rejection(self):
        """Points adding facts absent from inputs (numbers, entities) are rejected."""
        story = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        inputs = summary_pipeline.story_inputs(story)

        # Case 1: Invented number not in inputs (e.g. 999 triệu USD)
        invented_number_pts = [
            "Apple đã đầu tư 999 triệu USD vào việc nâng cấp bảo mật hệ điều hành macOS.",
            "Thay đổi này tác động lớn đến các agent AI."
        ]
        res, reason = summary_pipeline.validate_key_points(inputs, invented_number_pts)
        self.assertIsNone(res)
        self.assertIn("invented_number", reason)
        self.assertIn("999", reason)

        # Case 2: Invented entity not in inputs (e.g. DeepSeek or Microsoft)
        invented_entity_pts = [
            "Apple bắt tay cùng DeepSeek để ngăn chặn nguy cơ rò rỉ dữ liệu trên macOS.",
            "Người dùng sẽ nhận thông báo cấp quyền khi có truy cập mới."
        ]
        res2, reason2 = summary_pipeline.validate_key_points(inputs, invented_entity_pts)
        self.assertIsNone(res2)
        self.assertIn("invented_entity", reason2)
        self.assertIn("DeepSeek", reason2)

        # Case 3: Pipeline leaves story without key points when rejected
        def transport_hallucinated(body, key, timeout):
            return reply_summary([{
                "id": story["id"],
                "key_points": invented_number_pts
            }])

        payload = {"stories": [deepcopy(story)]}
        stats, _ = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=transport_hallucinated,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100000.0,
        )

        self.assertEqual(stats["summarized"], 0)
        self.assertEqual(stats["rejected"], 1)
        self.assertNotIn("key_points", payload["stories"][0])
        self.assertEqual(self.cache, {})

    def test_cli_persists_summaries_and_page_projection(self):
        """CLI runner updates radar.json, companion radar-ui.json with key_points, and persists cache."""
        src = self.tmp_path / "radar.json"
        cache = self.tmp_path / "summaries.json"
        ledger = self.tmp_path / "ledger.json"
        self.assertFalse(ledger.exists())
        gh = self.tmp_path / "github-output.txt"

        multi_story = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        src_data = {"stories": [deepcopy(multi_story)]}
        src.write_text(json.dumps(src_data, ensure_ascii=False), encoding="utf-8")

        env = {
            "GEMINI_API_KEY": "offline-sentinel",
            "RADAR_GEMINI_FREE_TIER_CONFIRMED": "1",
            "GITHUB_OUTPUT": str(gh),
        }

        with patch.dict("os.environ", env, clear=True), \
                patch.object(gemini, "transport", self.transport_ok):
            code = summarize.main(["--input", str(src), "--cache", str(cache), "--ledger", str(ledger)])

        self.assertEqual(code, 0)
        updated = json.loads(src.read_text(encoding="utf-8"))
        self.assertIn("key_points", updated["stories"][0])
        self.assertTrue(updated["stories"][0]["key_points_machine"])
        self.assertIn("summary", updated)
        self.assertEqual(updated["summary"]["status"], "ok")

        # Verify page projection carries summary and key_points
        ui_path = page_path(src)
        self.assertTrue(ui_path.exists())
        ui_data = json.loads(ui_path.read_text(encoding="utf-8"))
        self.assertIn("key_points", ui_data["stories"][0])
        self.assertTrue(ui_data["stories"][0]["key_points_machine"])
        self.assertIn("summary", ui_data)
        self.assertEqual(ui_data["summary"]["status"], "ok")

        # Verify cache persisted
        self.assertTrue(cache.exists())
        loaded_cache = gemini.load_cache(cache)
        self.assertEqual(len(loaded_cache), 1)

        # Verify GITHUB_OUTPUT
        self.assertTrue(gh.exists())
        gh_text = gh.read_text(encoding="utf-8")
        self.assertIn("summary_cache_written=true", gh_text)
        self.assertIn("summary_ledger_written=true", gh_text)

        # Verify no secret leak
        all_text = src.read_text(encoding="utf-8") + ui_path.read_text(encoding="utf-8") + gh_text
        self.assertNotIn("offline-sentinel", all_text)

    def test_ranking_window_and_worth_order(self):
        """Stories inside ranking window are sent in worth_score order (highest first, newest first on ties).
        Stories outside the ranking window are never sent and not summarised at all.
        """
        gen_time = "2026-10-05T12:00:00Z"

        # Story 1: Out of window (published 5 days ago, older than 72h window). Highest worth_score 95.0.
        story_out_window = {
            "id": "story-out-of-window",
            "title": "Very old story outside the 72 hour ranking window",
            "published_at": "2026-09-30T12:00:00Z",
            "worth_score": 95.0,
            "coverage": [{
                "publisher": "TechCrunch",
                "title": "Very old story outside the 72 hour ranking window",
                "summary": "This story occurred five days before the snapshot generation time.",
                "published_at": "2026-09-30T12:00:00Z",
            }]
        }

        # Story 2: In window, medium worth score (30.0), published 10 hours ago
        story_med_older = {
            "id": "story-med-older",
            "title": "Medium worth story published earlier",
            "published_at": "2026-10-05T02:00:00Z",
            "worth_score": 30.0,
            "coverage": [{
                "publisher": "The Verge",
                "title": "Medium worth story published earlier",
                "summary": "Report on early morning developments across AI infrastructure.",
                "published_at": "2026-10-05T02:00:00Z",
            }]
        }

        # Story 3: In window, high worth score (75.0), published 8 hours ago
        story_high_worth = {
            "id": "story-high-worth",
            "title": "High worth story with major multi source coverage",
            "published_at": "2026-10-05T04:00:00Z",
            "worth_score": 75.0,
            "coverage": [{
                "publisher": "Wired",
                "title": "High worth story with major multi source coverage",
                "summary": "Major breakthrough announced by leading AI research lab.",
                "published_at": "2026-10-05T04:00:00Z",
            }]
        }

        # Story 4: In window, same medium worth score (30.0) as story_med_older, but newer (published 2 hours ago)
        story_med_newer = {
            "id": "story-med-newer",
            "title": "Medium worth story published more recently",
            "published_at": "2026-10-05T10:00:00Z",
            "worth_score": 30.0,
            "coverage": [{
                "publisher": "Ars Technica",
                "title": "Medium worth story published more recently",
                "summary": "Recent developments in machine learning tooling and frameworks.",
                "published_at": "2026-10-05T10:00:00Z",
            }]
        }

        # Misleading order in payload: out-of-window first, low worth next, high worth last
        payload = {
            "generated_at": gen_time,
            "ranking": {"window_hours": 72},
            "stories": [
                deepcopy(story_out_window),
                deepcopy(story_med_older),
                deepcopy(story_med_newer),
                deepcopy(story_high_worth),
            ]
        }

        calls_received = []
        def transport_recorder(body, key, timeout):
            calls_received.append(body)
            stories_in = json.loads(body["contents"][0]["parts"][0]["text"])["stories"]
            rows = []
            for s in stories_in:
                rows.append({
                    "id": s["id"],
                    "key_points": [
                        "Ý thứ nhất xác thực về tin tức công nghệ trí tuệ nhân tạo.",
                        "Ý thứ hai mô tả diễn biến trong bài báo công nghệ trí tuệ nhân tạo.",
                        "Ý thứ ba nêu tác động được đề cập trong bài viết gốc."
                    ]
                })
            return reply_summary(rows, tokens=300)

        # One story per request keeps the token reservation bounded; worth order selects first.
        config = gemini.Config(api_key="offline-sentinel", confirmed=True, batch_size=2)
        stats, _ = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=config,
            transport_fn=transport_recorder,
            article_fetch_fn=lambda story: "Bài báo mô tả diễn biến và tác động được xác thực trong nội dung gốc. " * 8,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100000.0,
        )

        self.assertEqual(len(calls_received), 1)
        req_stories = json.loads(calls_received[0]["contents"][0]["parts"][0]["text"])["stories"]
        req_ids = [s["id"] for s in req_stories]

        # 1. Proves high-worth story sent before low-worth story:
        self.assertEqual(req_ids[0], "story-high-worth")

        # 2. The same worth score is tie-broken by newer publication time.
        self.assertEqual(req_ids, ["story-high-worth"])

        # 3. Proves out-of-window story is NEVER sent:
        self.assertNotIn("story-out-of-window", req_ids)

        # 4. Out-of-window story receives NO key points:
        out_story_in_payload = next(s for s in payload["stories"] if s["id"] == "story-out-of-window")
        self.assertNotIn("key_points", out_story_in_payload)
        self.assertNotIn("key_points_machine", out_story_in_payload)

        # 5. Stats reflect only the 3 window stories:
        self.assertEqual(stats["stories"], 3)
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(stats["pending"], 2)

        # Next run summarizes the next story in worth order.
        calls_received.clear()
        config_full = gemini.Config(api_key="offline-sentinel", confirmed=True, batch_size=10)
        stats2, _ = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=config_full,
            transport_fn=transport_recorder,
            article_fetch_fn=lambda story: "Bài báo mô tả diễn biến và tác động được xác thực trong nội dung gốc. " * 8,
            ledger_path=self.ledger_path,
            budget=10.0,
            now=lambda: 100005.0,
        )
        self.assertEqual(len(calls_received), 1)
        req2_ids = [s["id"] for s in json.loads(calls_received[0]["contents"][0]["parts"][0]["text"])["stories"]]
        # The next request respects the newer story's tie-break priority.
        self.assertEqual(req2_ids, ["story-med-newer"])
        self.assertNotIn("story-out-of-window", req2_ids)
        self.assertEqual(stats2["stories"], 3)
        self.assertEqual(stats2["cache_hits"], 1)
        self.assertEqual(stats2["summarized"], 1)
        self.assertEqual(stats2["pending"], 1)

        calls_received.clear()
        stats3, _ = summary_pipeline.summarize_payload(
            payload, self.cache, config=config_full, transport_fn=transport_recorder,
            article_fetch_fn=lambda story: "Bài báo mô tả diễn biến và tác động được xác thực trong nội dung gốc. " * 8,
            ledger_path=self.ledger_path, budget=10.0, now=lambda: 100010.0,
        )
        req3_ids = [s["id"] for s in json.loads(calls_received[0]["contents"][0]["parts"][0]["text"])["stories"]]
        self.assertEqual(req3_ids, ["story-med-older"])
        self.assertEqual(stats3["cache_hits"], 2)
        self.assertEqual(stats3["summarized"], 1)
        self.assertEqual(stats3["pending"], 0)



    def test_gemini_config_timeout_allows_values_above_legacy_45s(self):
        """Config timeout must accommodate large article-backed prompts beyond legacy 45s."""
        self.assertGreaterEqual(gemini.Config().timeout, 90.0)
        self.assertEqual(gemini.Config(timeout=120.0).timeout, 120.0)
        self.assertEqual(gemini.Config(timeout=300.0).timeout, 180.0)

    def test_pipeline_and_cli_budget_align_with_workflow_five_minute_limit(self):
        """CLI and pipeline budgets must align with the 5-minute GitHub Actions step budget."""
        self.assertGreaterEqual(summarize.DEFAULT_BUDGET, 180.0)
        self.assertGreaterEqual(summary_pipeline.DEFAULT_BUDGET, 180.0)

    def test_summary_pipeline_accommodates_request_with_article_text_over_45s(self):
        """A request carrying article text is provided a timeout exceeding legacy 45s."""
        story = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        payload = {"stories": [deepcopy(story)]}
        timeouts_seen = []

        def recording_transport(body, key, timeout):
            timeouts_seen.append(timeout)
            return self.transport_ok(body, key, timeout)

        stats, alive = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=recording_transport,
            ledger_path=self.ledger_path,
            now=lambda: 100000.0,
        )
        self.assertFalse(alive)
        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["summarized"], 1)
        self.assertEqual(len(timeouts_seen), 1)
        self.assertGreater(timeouts_seen[0], 45.0)

    def test_insufficient_time_refuses_before_ledger_reservation(self):
        """When remaining time before the request is too short, refuse cleanly without burning quota."""
        story = deepcopy(self.fixture_data["stories"][0])
        payload = {"stories": [story]}

        # If budget has very little time remaining (e.g. 2s < MIN_REQUEST_TIMEOUT),
        # the pipeline must NOT reserve quota or invoke transport.
        stats, alive = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True),
            transport_fn=self.transport_ok,
            ledger_path=self.ledger_path,
            budget=2.0,
            now=lambda: 100000.0,
        )
        ledger_data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(stats["error"], "time_budget")
        self.assertEqual(len(ledger_data["attempts"]), 0)
        self.assertEqual(len(self.calls), 0)

    def test_timed_out_request_is_accounted_for_honestly_in_ledger(self):
        """A timed-out request retains its reservation and estimated tokens in the ledger."""
        story = deepcopy(self.fixture_data["stories"][0])
        payload = {"stories": [story]}

        def hanging_transport(body, key, timeout):
            import time as _t
            _t.sleep(timeout + 0.05)
            return reply_summary([])

        stats, alive = summary_pipeline.summarize_payload(
            payload,
            self.cache,
            config=gemini.Config(api_key="offline-sentinel", confirmed=True, timeout=0.1),
            transport_fn=hanging_transport,
            ledger_path=self.ledger_path,
            budget=5.0,
            now=lambda: 100000.0,
        )
        ledger_data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(stats["error"], "timeout")
        self.assertEqual(len(ledger_data["attempts"]), 1)
        self.assertGreater(ledger_data["attempts"][0]["tokens"], 0)
        self.assertEqual(stats["requests"], 1)

    def test_robots_cache_shared_across_story_fetches(self):
        """Multiple candidate stories on same host share robots.txt result without duplicate fetches."""
        base = next(s for s in self.fixture_data["stories"] if s["id"] == "b3857f26daabd24cdab2")
        s1 = deepcopy(base)
        s1["id"] = "s1"
        s1["url"] = "https://publisher.example/story-1"
        s2 = deepcopy(base)
        s2["id"] = "s2"
        s2["url"] = "https://publisher.example/story-2"
        payload = {"stories": [s1, s2]}

        robots_checks = []
        def counting_check_robots(url, **kwargs):
            robots_checks.append(url)
            return {"robots_status": 200, "disallowed": False}

        with patch.object(summary_pipeline.shadow_collector, "check_robots", side_effect=counting_check_robots):
            stats, _ = summary_pipeline.summarize_payload(
                payload,
                self.cache,
                config=gemini.Config(api_key="offline-sentinel", confirmed=True, batch_size=2),
                transport_fn=self.transport_ok,
                ledger_path=self.ledger_path,
                budget=10.0,
                now=lambda: 100000.0,
            )
        self.assertEqual(len(robots_checks), 1)


if __name__ == "__main__":
    unittest.main()

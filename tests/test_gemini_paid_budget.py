"""Offline coverage for the fail-closed paid Gemini budget."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from radar import gemini_paid_budget as budget
from radar import summary_gemini, video_script


class PaidBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "ledger.json"
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True,
                       capture_output=True)
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc).timestamp()

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare(self, paid, run_id, run_number, attempt="1"):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": str(run_id),
                                     "GITHUB_RUN_ATTEMPT": attempt,
                                     "GITHUB_RUN_NUMBER": str(run_number)}):
            return budget.prepare(self.path, paid=paid, now=self.now, run_number=run_number,
                                  remote=str(self.remote), run_key=f"{run_id}-{attempt}")

    def _reserve(self, tokens, run_number):
        with patch.dict(os.environ, {"GITHUB_RUN_NUMBER": str(run_number)}):
            return budget.reserve(self.path, tokens, now=self.now, run_number=run_number)

    def _store(self, now=None):
        with tempfile.TemporaryDirectory() as temp:
            return budget._restore(str(self.remote), Path(temp) / "repo", self.now if now is None else now)

    def test_switch_off_seeds_durable_ledger_without_enabling_paid_calls(self):
        self.assertFalse(budget.enabled({}))
        self.assertIsNone(self._prepare(False, 100, 4))
        self.assertEqual(self._store(), {"version": 1, "month": "2026-10",
                                         "settled_micros": 0, "pending": {},
                                         "settled_daily": {}, "pending_days": {}, "settled_consumers": {}})

    def test_article_summaries_survive_fresh_runs_and_reach_published_pages(self):
        from copy import deepcopy
        import io
        from radar import summarize, summary_pipeline
        from radar.story_pages import render_story_page
        from radar.transport import ResponseText

        self.now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc).timestamp()
        fixtures = Path(__file__).parent / "fixtures" / "summary-articles"
        articles = json.loads((fixtures / "index.json").read_text(encoding="utf-8"))[:3]
        stories = [dict(id=f"{index:020x}", url=item["url"], title=item["title"],
                        published_at="2026-10-09T12:00:00Z", kind="news", coverage=[],
                        worth_score=90 - index) for index, item in enumerate(articles, 1)]
        payload = {"stories": stories, "generated_at": "2026-10-10T12:00:00Z"}
        src, cache = self.root / "radar.json", self.root / "summaries.json"
        published, output = self.root / "published.json", self.root / "github-output.txt"
        requested, fetched = [], []
        points = [
            "Nhóm thực hành ghi lại từng bước trong sổ tay chung để theo dõi công việc.",
            "Người tham gia kiểm tra hướng dẫn trước khi chuyển sang nhiệm vụ tiếp theo.",
            "Người rà soát đối chiếu danh sách đã hoàn thành với sổ tay sau buổi thực hành.",
            "Nhóm giữ riêng những ghi nhận chưa rõ để thảo luận sau buổi thực hành.",
        ]

        def read(url, **kwargs):
            fetched.append(url)
            if url.endswith("/robots.txt"):
                return ResponseText("User-agent: *\nAllow: /", status=200)
            item = next(item for item in articles if item["url"] == url)
            return ResponseText((fixtures / item["file"]).read_text(encoding="utf-8"),
                                status=200, url=url, content_type="text/html")

        def provider(body, key, timeout):
            # Actual transport boundary: do not replace parsing, grounding or ledger checks.
            inputs = json.loads(body["contents"][0]["parts"][0]["text"])["stories"]
            self.assertEqual(len(inputs), 1)
            requested.append(inputs[0]["id"])
            paragraphs = inputs[0]["sources"][0]["paragraphs"]
            self.assertGreater(sum(len(p["text"]) for p in paragraphs), 300)
            self.assertGreater(budget.total_micros(self.path, now=self.now), 0)
            self.assertEqual(json.loads(self.path.read_text())["reservations"][-1]["consumer"], "summary")
            ref = next(p["id"] for p in paragraphs if "shared notebook" in p["text"])
            claim = lambda text: {"text": text, "evidence_refs": [ref]}
            row = {"id": inputs[0]["id"], "status": "ready",
                   "title_vi": claim("Nhóm thực hành ghi chép và kiểm tra công việc bằng sổ tay"),
                   "key_points": [claim(point) for point in points], "used_source_ids": ["outlet"],
                   "limitations": [] if inputs[0]["sources"][0]["body_complete"] else ["partial_source"]}
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(
                row, ensure_ascii=False)}]}}],
                "usageMetadata": {"totalTokenCount": 420}}

        self.assertIsNone(self._prepare(False, 1100, 1100))
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
                patch.object(summary_pipeline.transport, "read_url", side_effect=read), \
                patch.object(summary_gemini, "transport", side_effect=provider), \
                patch("time.time", return_value=self.now):
            for offset in range(5):
                run = 1101 + offset
                self.assertIsNone(self._prepare(True, run, run))
                if offset == 0:
                    self.assertIsNone(budget.reserve(self.path, 40_000, now=self.now,
                                                     run_number=run, consumer="translation")[0])
                # Simulate a newly collected snapshot; all summary state must load from disk.
                src.write_text(json.dumps(deepcopy(payload)), encoding="utf-8", newline="\n")
                published.write_text("{}", encoding="utf-8")
                env = {"GITHUB_RUN_NUMBER": str(run), "GEMINI_API_KEY": "offline-sentinel",
                       "RADAR_GEMINI_PAID_ENABLED": "1", "RADAR_GEMINI_PAID_LEDGER": str(self.path),
                       "RADAR_PUBLISHED_SNAPSHOT": str(published), "GITHUB_OUTPUT": str(output)}
                with patch.dict(os.environ, env, clear=True), patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(summarize.main(["--input", str(src), "--cache", str(cache)]), 0)
                ui = json.loads((self.root / "radar-ui.json").read_text(encoding="utf-8"))
                stats = ui["summary"]
                self.assertEqual(stats["stories"], 3)
                # Translation consumes $0.15 of this run's $0.20 hold: a larger summary waits.
                self.assertEqual(stats["requests"], int(1 <= offset <= 3))
                self.assertEqual(stats["cache_hits"], min(max(offset - 1, 0), 3))
                self.assertEqual(stats["summarized"], int(1 <= offset <= 3))
                self.assertEqual(stats["pending"], max(3 - offset, 0))
                if offset == 0:
                    self.assertEqual(stats["error"], "paid_monthly_cap")
                for story in ui["stories"]:
                    if story.get("key_points"):
                        self.assertEqual(story["key_points"], points)
                        self.assertIn(points[0], render_story_page(story))
                self.assertEqual(json.loads(src.read_text(encoding="utf-8")),
                                 json.loads(published.read_text(encoding="utf-8")))
                self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now, run_key=f"{run}-1"))
        self.assertEqual(len(requested), 3)
        self.assertEqual(len(set(requested)), 3)
        self.assertEqual(sum(not url.endswith("/robots.txt") for url in fetched), 4)
        store = self._store()
        self.assertEqual(store["settled_consumers"]["2026-10-10"]["summary"], budget._micros(1260, self.now))
        self.assertEqual(store["settled_consumers"]["2026-10-10"]["translation"], budget._micros(40_000, self.now))
        self.assertLess(store["settled_daily"]["2026-10-10"], int(budget.DAILY_PACE_USD * 1_000_000))
        self.assertLess(store["settled_micros"], int(budget.MAX_CAP_USD * 1_000_000))
        self.assertIn("summary_cache_written=true", output.read_text())
        self.assertIn("article_inputs_written=true", output.read_text())

    def test_cancelled_attempt_keeps_only_a_bounded_reservation_and_next_run_continues(self):
        self.assertIsNone(self._prepare(False, 100, 10))
        self.assertIsNone(self._prepare(True, 101, 11))
        self.assertEqual(self._reserve(40_000, 11)[0], None)
        first = self._store()
        self.assertEqual(first["pending"], {"101-1": 200_000})

        # A cancelled run retains its smaller hold; its unknown consumer usage stays charged.
        self.assertIsNone(self._prepare(True, 103, 13))
        second = self._store()
        self.assertEqual(second["pending"], {"101-1": 200_000, "103-1": 175_000})
        self.assertIsNone(self._reserve(40_000, 13)[0])

    def test_branch_run_between_paid_runs_does_not_stale_the_durable_budget(self):
        self.assertIsNone(self._prepare(False, 200, 20))
        self.assertIsNone(self._prepare(True, 201, 21))
        before = self._store()
        # A branch run is paid-off and must not mutate the main-only ledger.
        self.assertIsNone(self._prepare(False, 202, 22))
        self.assertEqual(self._store(), before)
        self.assertIsNone(self._prepare(True, 203, 23))
        self.assertIsNone(self._reserve(40_000, 23)[0])

    def test_missing_local_cache_reloads_month_spend_from_durable_branch(self):
        self.assertIsNone(self._prepare(False, 300, 30))
        self.assertIsNone(self._prepare(True, 301, 31))
        error, request_id = self._reserve(40_000, 31)
        self.assertIsNone(error)
        budget.settle(self.path, request_id, 20_000, now=self.now)
        self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now,
                                          run_key="301-1"))
        self.path.unlink()

        self.assertIsNone(self._prepare(True, 302, 32))
        self.assertEqual(self._store()["settled_micros"], budget._micros(20_000, self.now))
        self.assertIsNone(self._reserve(40_000, 32)[0])

    def test_under_reporting_local_snapshot_cannot_override_nearly_spent_durable_ledger(self):
        self.assertIsNone(self._prepare(False, 400, 40))
        store = self._store()
        store["settled_micros"] = 19_950_000
        budget._push(str(self.remote), store)
        # This stale local snapshot claims no spend; durable state remains authoritative.
        self.path.write_text(json.dumps({"version": 1, "month": "2026-10",
                                        "last_run_number": 40, "reservations": []}),
                             encoding="utf-8")
        self.assertIsNone(self._prepare(True, 401, 41))
        self.assertEqual(self._store()["pending"]["401-1"], 50_000)
        self.assertEqual(self._store()["settled_micros"], 19_950_000)

    def test_monthly_cap_sizes_hold_when_only_a_fractional_allowance_remains(self):
        self.assertIsNone(self._prepare(False, 500, 50))
        store = self._store()
        store["settled_micros"] = 19_950_000
        budget._push(str(self.remote), store)
        self.assertIsNone(self._prepare(True, 501, 51))
        self.assertEqual(self._store()["pending"]["501-1"], 50_000)
        self.assertEqual(self._prepare(True, 502, 52), "paid_monthly_cap")
        self.assertEqual(self._store()["settled_micros"], 19_950_000)

    def test_new_month_rolls_over_and_allows_paid_reservations(self):
        self.assertIsNone(self._prepare(False, 600, 60))
        self.assertIsNone(self._prepare(True, 601, 61))
        error, reservation = self._reserve(1000, 61)
        self.assertIsNone(error)
        budget.settle(self.path, reservation, 500, now=self.now)
        next_month = datetime(2026, 11, 1, 0, tzinfo=timezone.utc).timestamp()
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "602", "GITHUB_RUN_ATTEMPT": "1"}):
            self.assertIsNone(budget.prepare(self.path, paid=True, now=next_month,
                                             run_number=62, remote=str(self.remote),
                                             run_key="602-1"))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["month"], "2026-11")
        self.assertEqual(self._store(next_month)["month"], "2026-11")

    def test_daily_cap_limits_and_sizes_the_final_run_hold(self):
        self.assertIsNone(self._prepare(False, 700, 70))
        store = self._store()
        store["settled_micros"] = 500_000
        store["settled_daily"] = {"2026-10-07": 500_000}
        store["settled_consumers"] = {"2026-10-07": {"translation": 150_000, "summary": 350_000}}
        budget._push(str(self.remote), store)
        self.assertIsNone(self._prepare(True, 701, 71))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["run_allowance_micros"], 70_000)
        self.assertEqual(self._prepare(True, 702, 72), "paid_daily_cap")
        self.assertEqual(self._store()["settled_daily"]["2026-10-07"], 500_000)

    def test_consumer_quotas_survive_cache_loss_and_do_not_borrow(self):
        self.assertIsNone(self._prepare(False, 800, 80))
        self.assertIsNone(self._prepare(True, 801, 81))
        error, _ = budget.reserve(self.path, 40_000, now=self.now, run_number=81, consumer="translation")
        self.assertIsNone(error)
        self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now, run_key="801-1"))
        self.path.unlink()
        self.assertIsNone(self._prepare(True, 802, 82))
        self.assertEqual(budget.reserve(self.path, 1, now=self.now, run_number=82,
                                       consumer="translation")[0], "paid_translation_daily_tokens")
        self.assertIsNone(budget.reserve(self.path, 40_000, now=self.now, run_number=82, consumer="summary")[0])
        self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now, run_key="802-1"))
        self.assertEqual(self._store()["settled_consumers"]["2026-10-07"],
                         {"translation": 150_000, "summary": 150_000})

    def test_reprepare_cannot_erase_unsettled_requests(self):
        self._prepare(False, 900, 90)
        self._prepare(True, 901, 91)
        self._reserve(1000, 91)
        before = self.path.read_bytes()
        self.assertEqual(self._prepare(True, 901, 91), "paid_budget_attempt_already_reserved")
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_writer_cannot_erase_another_durable_hold(self):
        from copy import deepcopy
        self._prepare(False, 910, 90)
        before = self._store()
        stale = deepcopy(before)
        self._prepare(True, 911, 91)
        with self.assertRaises(RuntimeError):
            budget._push(str(self.remote), stale, self.now, expected=before)
        self.assertEqual(self._store()["pending"], {"911-1": 200_000})

    def test_video_attempt_identity_survives_output_and_cache_loss(self):
        self._prepare(False, 920, 90)
        self._prepare(True, 921, 91)
        error, request = budget.reserve(self.path, 2000, now=self.now, run_number=91,
                                        consumer="video", idempotency_key="2026-10-07")
        self.assertIsNone(error)
        budget.settle(self.path, request, 100, now=self.now)
        self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now, run_key="921-1"))
        self.path.unlink()
        self._prepare(True, 922, 92)
        self.assertEqual(budget.reserve(self.path, 2000, now=self.now, run_number=92,
                                        consumer="video", idempotency_key="2026-10-07")[0],
                         "paid_video_already_attempted")

    def test_legacy_spend_is_not_reissued_as_new_consumer_quota(self):
        self._prepare(False, 930, 90)
        store = self._store()
        store.pop("settled_consumers")
        store["settled_micros"] = 160_000
        store["settled_daily"] = {"2026-10-07": 160_000}
        budget._push(str(self.remote), store, self.now)
        self.assertIsNone(self._prepare(True, 931, 91))
        self.assertEqual(budget.remaining_tokens(self.path, "translation", now=self.now, run_number=91), 0)
        self.assertGreater(budget.remaining_tokens(self.path, "summary", now=self.now, run_number=91), 0)

    def test_complete_day_cannot_spend_beyond_pace_or_summary_share(self):
        self._prepare(False, 950, 90)
        for offset, (consumer, tokens) in enumerate([
                ("translation", 40_000), ("summary", 50_000),
                ("summary", 50_000), ("video", 12_000)], 1):
            run = 950 + offset
            self.assertIsNone(self._prepare(True, run, run))
            self.assertIsNone(budget.reserve(self.path, tokens, now=self.now, run_number=run, consumer=consumer)[0])
            if offset == 3:
                self.assertEqual(budget.reserve(self.path, 1, now=self.now, run_number=run, consumer="summary")[0],
                                 "paid_summary_daily_tokens")
            self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now, run_key=f"{run}-1"))
        self.assertEqual(self._store()["settled_daily"]["2026-10-07"], 570_000)
        self.assertEqual(self._prepare(True, 960, 960), "paid_daily_cap")
        self.assertEqual(budget.RUN_ALLOWANCE_USD, Decimal("1"))
        self.assertEqual(budget.DAILY_CAP_USD, Decimal("6"))
        self.assertEqual(budget.MAX_CAP_USD, Decimal("20"))
        self.assertEqual(budget.DAILY_PACE_USD * 31, Decimal("17.67"))
        self.assertGreaterEqual(budget.MAX_CAP_USD - budget.DAILY_PACE_USD * 31, Decimal("2"))

    def test_real_daily_video_request_reaches_transport_on_consecutive_days(self):
        fixture = Path(__file__).parent / "fixtures" / "video-picks-2026-10-10.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        stories = payload["stories"]
        self.assertEqual(len(stories), 3)
        body = video_script.build_gemini_request(stories)
        tokens = len(json.dumps(body).encode("utf-8")) + body["generationConfig"]["maxOutputTokens"]
        self.assertEqual(tokens, 8_309)
        calls = []

        def offline_transport(request, key, timeout):
            calls.append(request)
            # Exercise real request admission without purchasing or inventing model output.
            raise TimeoutError("offline transport boundary")

        self.now = datetime(2026, 10, 10, 22, 7, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(self._prepare(False, 980, 980))
        for run in (981, 982):
            with self.subTest(run=run):
                self.assertIsNone(self._prepare(True, run, run))
                with patch.dict(os.environ, {
                    "GEMINI_API_KEY": "test-key",
                    "RADAR_GEMINI_PAID_ENABLED": "1",
                    "RADAR_GEMINI_PAID_LEDGER": str(self.path),
                    "GITHUB_RUN_NUMBER": str(run),
                }):
                    result = video_script.generate_video_script(
                        fixture, self.root / "video-script.json", self.root / "summary-ledger.json",
                        now_val=datetime.fromtimestamp(self.now, timezone.utc),
                        ref="refs/heads/main", transport_fn=offline_transport)
                self.assertEqual(result["status"], "transport_error", result)
                self.assertEqual(calls[-1], body)
                reservations = json.loads(self.path.read_text(encoding="utf-8"))["reservations"]
                self.assertEqual(len(reservations), 1)
                self.assertEqual(reservations[0]["consumer"], "video")
                self.assertEqual(reservations[0]["micros"], budget._micros(tokens, self.now))
                self.assertIsNone(budget.finalize(
                    self.path, str(self.remote), now=self.now, run_key=f"{run}-1"))
                self.now += 24 * 60 * 60
        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(budget.CONSUMER_TOKENS["video"], tokens * Decimal("1.25"))

    def test_corrupt_consumer_snapshot_cannot_authorize_spending(self):
        self._prepare(False, 970, 90)
        self._prepare(True, 971, 91)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["consumer_remaining_micros"]["translation"] = 999_999
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(budget.reserve(self.path, 1000, now=self.now, run_number=91, consumer="translation")[0],
                         budget.MISSING_CODE)

    def test_cap_configuration_can_only_lower_twenty_dollars(self):
        self.assertEqual(budget.cap_usd({}), Decimal("20"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "25"}), Decimal("20"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "7.5"}), Decimal("7.5"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "bad"}), Decimal(0))

    def test_migration_day_unattributed_spend_allows_video_reservation_at_2230_utc(self):
        self._prepare(False, 990, 990)
        store = self._store()
        store.pop("settled_consumers")
        store["settled_micros"] = 406_902
        store["settled_daily"] = {"2026-10-10": 406_902}
        now_utc = datetime(2026, 10, 10, 22, 30, tzinfo=timezone.utc).timestamp()
        budget._push(str(self.remote), store, now_utc)

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "991", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_NUMBER": "991"}):
            prep_err = budget.prepare(self.path, paid=True, now=now_utc, run_number=991,
                                      remote=str(self.remote), run_key="991-1")
            self.assertIsNone(prep_err)
            self.assertEqual(budget.remaining_tokens(self.path, "translation", now=now_utc, run_number=991), 0)
            self.assertEqual(budget.remaining_tokens(self.path, "summary", now=now_utc, run_number=991), 0)
            self.assertGreaterEqual(budget.remaining_tokens(self.path, "video", now=now_utc, run_number=991), 8_309)

            error, req_id = budget.reserve(self.path, 8_309, now=now_utc, run_number=991,
                                           consumer="video", idempotency_key="2026-10-11")
            self.assertIsNone(error)
            self.assertIsNotNone(req_id)

            budget.settle(self.path, req_id, 8_309, now=now_utc)
            self.assertIsNone(budget.finalize(self.path, str(self.remote), now=now_utc, run_key="991-1"))

        final_store = self._store(now_utc)
        self.assertEqual(final_store["settled_daily"]["2026-10-10"], 406_902 + 31_159)
        self.assertEqual(final_store["settled_consumers"]["2026-10-10"], {"video": 31_159})
        self.assertIn("2026-10-11", final_store["video_dates"])

    def test_migration_day_2026_10_10_total_spend_cannot_exceed_daily_pace(self):
        now_utc = datetime(2026, 10, 10, 22, 30, tzinfo=timezone.utc).timestamp()
        self._prepare(False, 995, 995)
        store = self._store()
        store.pop("settled_consumers")
        store["settled_micros"] = 550_000
        store["settled_daily"] = {"2026-10-10": 550_000}
        budget._push(str(self.remote), store, now_utc)

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "996", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_NUMBER": "996"}):
            self.assertIsNone(budget.prepare(self.path, paid=True, now=now_utc, run_number=996,
                                             remote=str(self.remote), run_key="996-1"))
            tokens_left = budget.remaining_tokens(self.path, "video", now=now_utc, run_number=996)
            self.assertLess(tokens_left, 8_309)
            error, _ = budget.reserve(self.path, 8_309, now=now_utc, run_number=996,
                                      consumer="video", idempotency_key="2026-10-11")
            self.assertIsNotNone(error)

        store["settled_daily"]["2026-10-10"] = 570_000
        store["settled_micros"] = 570_000
        budget._push(str(self.remote), store, now_utc)
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "997", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_NUMBER": "997"}):
            self.assertEqual(budget.prepare(self.path, paid=True, now=now_utc, run_number=997,
                                            remote=str(self.remote), run_key="997-1"),
                             "paid_daily_cap")


if __name__ == "__main__":
    unittest.main()


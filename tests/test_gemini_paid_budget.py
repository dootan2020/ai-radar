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
        tokens = len(json.dumps(body).encode("utf-8")) + summary_gemini.MAX_OUTPUT_TOKENS
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


if __name__ == "__main__":
    unittest.main()

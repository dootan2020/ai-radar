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
                                         "settled_micros": 0, "pending": {}})

    def test_cancelled_attempt_keeps_only_a_bounded_reservation_and_next_run_continues(self):
        self.assertIsNone(self._prepare(False, 100, 10))
        self.assertIsNone(self._prepare(True, 101, 11))
        self.assertEqual(self._reserve(100_000, 11)[0], None)
        first = self._store()
        self.assertEqual(first["pending"], {"101-1": 1_000_000})

        # Simulate cancellation before finalization: the $1 hold remains reserved.
        self.assertIsNone(self._prepare(True, 103, 13))
        second = self._store()
        self.assertEqual(second["pending"], {"101-1": 1_000_000, "103-1": 1_000_000})
        self.assertIsNone(self._reserve(100_000, 13)[0])

    def test_branch_run_between_paid_runs_does_not_stale_the_durable_budget(self):
        self.assertIsNone(self._prepare(False, 200, 20))
        self.assertIsNone(self._prepare(True, 201, 21))
        before = self._store()
        # A branch run is paid-off and must not mutate the main-only ledger.
        self.assertIsNone(self._prepare(False, 202, 22))
        self.assertEqual(self._store(), before)
        self.assertIsNone(self._prepare(True, 203, 23))
        self.assertIsNone(self._reserve(100_000, 23)[0])

    def test_missing_local_cache_reloads_month_spend_from_durable_branch(self):
        self.assertIsNone(self._prepare(False, 300, 30))
        self.assertIsNone(self._prepare(True, 301, 31))
        error, request_id = self._reserve(100_000, 31)
        self.assertIsNone(error)
        budget.settle(self.path, request_id, 50_000, now=self.now)
        self.assertIsNone(budget.finalize(self.path, str(self.remote), now=self.now,
                                          run_key="301-1"))
        self.path.unlink()

        self.assertIsNone(self._prepare(True, 302, 32))
        self.assertEqual(self._store()["settled_micros"], budget._micros(50_000, self.now))
        self.assertIsNone(self._reserve(100_000, 32)[0])

    def test_under_reporting_local_snapshot_cannot_override_nearly_spent_durable_ledger(self):
        self.assertIsNone(self._prepare(False, 400, 40))
        store = self._store()
        store["settled_micros"] = 19_500_000
        budget._push(str(self.remote), store)
        # This stale local snapshot claims no spend; durable state remains authoritative.
        self.path.write_text(json.dumps({"version": 1, "month": "2026-10",
                                        "last_run_number": 40, "reservations": []}),
                             encoding="utf-8")
        self.assertEqual(self._prepare(True, 401, 41), "paid_monthly_cap")
        self.assertEqual(self._store()["settled_micros"], 19_500_000)

    def test_monthly_cap_refuses_a_run_when_only_a_fractional_allowance_remains(self):
        self.assertIsNone(self._prepare(False, 500, 50))
        store = self._store()
        store["settled_micros"] = 19_500_000
        budget._push(str(self.remote), store)
        self.assertEqual(self._prepare(True, 501, 51), "paid_monthly_cap")
        self.assertEqual(self._store()["settled_micros"], 19_500_000)

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

    def test_cap_configuration_can_only_lower_twenty_dollars(self):
        self.assertEqual(budget.cap_usd({}), Decimal("20"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "25"}), Decimal("20"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "7.5"}), Decimal("7.5"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "bad"}), Decimal(0))


if __name__ == "__main__":
    unittest.main()

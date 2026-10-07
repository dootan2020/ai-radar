"""Offline coverage for the fail-closed paid Gemini budget."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import gemini_paid_budget as budget


class PaidBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.json"
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc).timestamp()

    def tearDown(self):
        self.tmp.cleanup()

    def test_switch_off_seeds_ledger_without_enabling_paid_calls(self):
        self.assertFalse(budget.enabled({}))
        self.assertIsNone(budget.prepare(self.path, paid=False, now=self.now, run_number=4))
        self.assertEqual(budget.total_micros(self.path, now=self.now), 0)

    def test_monthly_cap_stops_reservation_before_a_provider_call(self):
        self.assertIsNone(budget.prepare(self.path, paid=False, now=self.now, run_number=4))
        env = {"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "0.01"}
        self.assertIsNone(budget.prepare(self.path, paid=True, now=self.now, run_number=5))
        with patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "5", **env}):
            error, first = budget.reserve(self.path, 2600, now=self.now)
            self.assertIsNone(error)
            budget.settle(self.path, first, 2600, now=self.now)
            error, second = budget.reserve(self.path, 1000, now=self.now)
        self.assertEqual(error, "paid_monthly_cap")
        self.assertIsNone(second)

    def test_missing_ledger_fails_closed_when_paid_is_enabled(self):
        self.assertEqual(budget.prepare(self.path, paid=True, now=self.now, run_number=5),
                         budget.MISSING_CODE)
        self.assertFalse(self.path.exists())

    def test_run_gap_detects_a_lost_or_unsaved_cache_snapshot(self):
        self.assertIsNone(budget.prepare(self.path, paid=False, now=self.now, run_number=10))
        error, reservation = budget.reserve(self.path, 100, now=self.now, run_number=10)
        self.assertIsNone(error)
        self.assertIsNotNone(reservation)
        self.assertEqual(budget.prepare(self.path, paid=True, now=self.now, run_number=12),
                         budget.STALE_RUN_CODE)
        self.assertEqual(budget.reserve(self.path, 100, now=self.now, run_number=12)[0],
                         budget.MISSING_CODE)

    def test_new_month_rolls_over_and_allows_paid_reservations(self):
        self.assertIsNone(budget.prepare(self.path, paid=False, now=self.now, run_number=10))
        error, reservation = budget.reserve(self.path, 1000, now=self.now, run_number=10)
        self.assertIsNone(error)
        budget.settle(self.path, reservation, 500, now=self.now)
        next_month = datetime(2026, 11, 1, 0, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(budget.prepare(self.path, paid=True, now=next_month, run_number=11))
        with patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "11"}):
            error, reservation = budget.reserve(self.path, 1000, now=next_month)
        self.assertIsNone(error)
        self.assertIsNotNone(reservation)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["month"], "2026-11")

    def test_cap_configuration_can_only_lower_twenty_dollars(self):
        self.assertEqual(budget.cap_usd({}), Decimal("20"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "25"}), Decimal("20"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "7.5"}), Decimal("7.5"))
        self.assertEqual(budget.cap_usd({"RADAR_GEMINI_PAID_MONTHLY_CAP_USD": "bad"}), Decimal(0))


if __name__ == "__main__":
    unittest.main()

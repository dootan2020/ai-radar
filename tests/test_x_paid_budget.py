"""Offline tests for durable X spend reservations and fail-closed behavior."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from radar import x_paid_budget as budget


class XPaidBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = self.root / "x-ledger.json"
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc).timestamp()

    def tearDown(self):
        self.temp.cleanup()

    def _store(self):
        with tempfile.TemporaryDirectory() as temporary:
            return budget._restore(str(self.remote), Path(temporary) / "repo", self.now)

    def test_missing_store_fails_closed_when_enabled_and_seeds_when_disabled(self):
        self.assertEqual(budget.prepare(self.local, paid=True, remote=str(self.remote), now=self.now,
                                        run_key="100-1"), budget.MISSING_CODE)
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        self.assertEqual(self._store()["settled_micros"], 0)

    def test_reserves_before_calls_and_settles_only_returned_resources(self):
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        self.assertIsNone(budget.prepare(self.local, paid=True, remote=str(self.remote), now=self.now,
                                         run_key="101-1"))
        error, request_id = budget.reserve(self.local, now=self.now, max_results=10)
        self.assertIsNone(error)
        self.assertEqual(json.loads(self.local.read_text(encoding="utf-8"))["reservations"][0]["micros"], 50_000)
        self.assertIsNone(budget.settle(self.local, request_id, 3, now=self.now))
        self.assertIsNone(budget.update_cursor(self.local, "group-0", "12345", None, now=self.now))
        self.assertIsNone(budget.finalize(self.local, str(self.remote), now=self.now, run_key="101-1"))
        store = self._store()
        self.assertEqual(store["settled_micros"], 15_000)
        self.assertEqual(store["settled_daily"], {"2026-10-09": 15_000})
        self.assertEqual(store["cursors"]["group-0"], {"since_id": "12345", "next_token": None})

    def test_run_cannot_reserve_beyond_the_daily_slice(self):
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        self.assertIsNone(budget.prepare(self.local, paid=True, remote=str(self.remote), now=self.now,
                                         run_key="102-1"))
        for _ in range(20):
            error, request_id = budget.reserve(self.local, now=self.now, max_results=10)
            self.assertIsNone(error)
            self.assertIsNone(budget.settle(self.local, request_id, 10, now=self.now))
        self.assertEqual(budget.reserve(self.local, now=self.now, max_results=10)[0], "x_run_cap")

    def test_settled_daily_cap_blocks_subsequent_run(self):
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        store = self._store()
        store["settled_daily"]["2026-10-09"] = budget.DAILY_CAP_MICROS
        budget._push(str(self.remote), store, self.now)
        self.assertEqual(budget.prepare(self.local, paid=True, remote=str(self.remote), now=self.now,
                                        run_key="103-1"), "x_daily_cap")

    def test_malformed_pending_or_daily_ledger_fails_closed(self):
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        store = self._store()
        store["pending"]["unknown-day"] = 5_000
        budget._push(str(self.remote), store, self.now)
        self.assertEqual(budget.prepare(self.local, paid=True, remote=str(self.remote), now=self.now,
                                        run_key="106-1"), budget.MISSING_CODE)

    def test_monthly_cap_blocks_reservation_and_next_month_resets(self):
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        store = self._store()
        store["settled_micros"] = budget.MONTHLY_CAP_MICROS
        budget._push(str(self.remote), store, self.now)
        self.assertEqual(budget.prepare(self.local, paid=True, remote=str(self.remote), now=self.now,
                                        run_key="104-1"), "x_monthly_cap")
        november = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(budget.prepare(self.local, paid=True, remote=str(self.remote), now=november,
                                         run_key="105-1"))

    def test_month_rollover_resets_spend_but_preserves_search_cursors(self):
        self.assertIsNone(budget.prepare(self.local, paid=False, remote=str(self.remote), now=self.now))
        store = self._store()
        store["settled_micros"] = 25_000
        store["settled_daily"]["2026-10-09"] = 25_000
        store["cursors"]["group-0"] = {"since_id": "987654", "next_token": None}
        budget._push(str(self.remote), store, self.now)
        november = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(budget.prepare(self.local, paid=True, remote=str(self.remote), now=november,
                                         run_key="107-1"))
        fresh = self._store_at(november)
        self.assertEqual(fresh["settled_micros"], 0)
        self.assertEqual(fresh["cursors"]["group-0"], {"since_id": "987654", "next_token": None})

    def _store_at(self, now):
        with tempfile.TemporaryDirectory() as temporary:
            return budget._restore(str(self.remote), Path(temporary) / "repo", now)


if __name__ == "__main__":
    unittest.main()

"""Arena contracts: source fixtures are local evidence, network is never needed."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import tempfile
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from radar.arena import main, CATEGORIES, comparison_date, make_payload, parse_parquet, public_payload, rank_history, refresh

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "plans/live-data/arena"
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


class ArenaComparisonTests(unittest.TestCase):
    def test_week_uses_publication_date_and_never_a_newer_or_ancient_baseline(self):
        history = {day: {} for day in ["2026-09-01", "2026-09-30", "2026-10-02", "2026-10-08"]}
        self.assertEqual(comparison_date("2026-10-08", history), "2026-09-30")
        self.assertIsNone(comparison_date("2026-10-08", {"2026-09-01": {}, "2026-10-02": {}}))
        self.assertEqual(comparison_date("2026-10-08", {"2026-10-01": {}}), "2026-10-01")

    def test_rising_falling_unchanged_and_unlisted_are_distinct(self):
        rows = [{"id": name, "maker": "maker", "rank": rank, "score": 1500.123}
                for name, rank in [("rising", 1), ("falling", 2), ("same", 3), ("absent", 4)]]
        categories = {c: rows for c in CATEGORIES}
        history = {"2026-10-01": {c: {"rising": 4, "falling": 1, "same": 3} for c in CATEGORIES}}
        payload = make_payload("2026-10-08", categories, history)
        actual = payload["categories"]["overall"]
        self.assertEqual([r["rank_change"] for r in actual], [3, -1, 0, None])
        self.assertEqual(actual[-1]["change_status"], "unlisted")
        self.assertEqual(actual[0]["score"], 1500.123)
        unavailable = make_payload("2026-10-08", categories, {})["categories"]["overall"]
        self.assertTrue(all(r["change_status"] == "unavailable" for r in unavailable))

    def test_failure_preserves_snapshot_and_throttles_attempts(self):
        snapshot = {"published_at": "2026-09-20", "categories": {}}
        state = {"snapshot": snapshot, "fetched_at": "2026-09-21T00:00:00+00:00"}
        def fail(_):
            raise TimeoutError("network unavailable")
        result = refresh(state, NOW, fail)
        self.assertEqual(result["snapshot"], snapshot)
        self.assertEqual(result["fetched_at"], state["fetched_at"])
        self.assertEqual(result["fetch_status"], "failed")
        self.assertTrue(public_payload(result, NOW)["stale"])
        def forbidden(_):
            self.fail("24-hour attempt throttle did not hold")
        self.assertEqual(refresh(result, NOW + timedelta(hours=23), forbidden), result)
        self.assertNotIn("attempted_at", state)

    def test_first_failure_is_empty_and_staleness_advances_without_fetch(self):
        result = refresh({}, NOW, lambda _: (_ for _ in ()).throw(OSError()))
        self.assertNotIn("published_at", public_payload(result, NOW))
        state = {"snapshot": {"published_at": "2026-10-08"}, "attempted_at": NOW.isoformat()}
        self.assertFalse(public_payload(state, NOW)["stale"])
        self.assertTrue(public_payload(state, NOW + timedelta(days=13))["stale"])

    def test_cli_writes_last_good_before_work_that_may_be_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            output_path = Path(directory) / "arena.json"
            snapshot = {"published_at": "2026-10-08", "categories": {}}
            state_path.write_text(json.dumps({"snapshot": snapshot}), encoding="utf-8")
            with patch("sys.argv", ["arena", "--state", str(state_path), "--output", str(output_path)]), \
                    patch("radar.arena.refresh", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    main()
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["published_at"], "2026-10-08")
            self.assertEqual(result["fetch_status"], "failed")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["snapshot"], snapshot)

    @unittest.skipUnless(shutil.which("node"), "Node required for Arena renderer tests")
    def test_renderer(self):
        result = subprocess.run(["node", "tests/verify-arena.mjs"], cwd=ROOT, capture_output=True,
                                encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(importlib.util.find_spec("pyarrow") and (FIXTURES / "text_style_control-latest.parquet").exists(),
                     "Requires PyArrow and coordinator-provided local Arena fixtures")
class ArenaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.latest_bytes = (FIXTURES / "text_style_control-latest.parquet").read_bytes()
        cls.history_bytes = (FIXTURES / "text_style_control-full-last8.parquet").read_bytes()
        cls.latest = parse_parquet(cls.latest_bytes)
        cls.history = parse_parquet(cls.history_bytes)

    def fetch(self, filename):
        return self.history_bytes if filename.startswith("full") else self.latest_bytes

    def test_real_parser_and_historical_comparison(self):
        current = self.latest["2026-10-08"]
        self.assertEqual(len(current["overall"]), 414)
        self.assertEqual(current["overall"][0]["id"], "gemini-4-argon-high")
        self.assertAlmostEqual(current["overall"][0]["score"], 1525.3956435571818)
        payload = make_payload("2026-10-08", current, rank_history(self.history))
        self.assertEqual(payload["comparison_at"], "2026-09-30")
        self.assertEqual(payload["categories"]["overall"][1]["rank_change"], 2)
        for rows in payload["categories"].values():
            self.assertEqual(len(rows), 10)
        self.assertEqual(len(self.history), 8)

    @unittest.skipUnless(shutil.which("node"), "Node required for Arena renderer tests")
    def test_every_source_model_has_lossless_names_makers_and_integer_scores(self):
        import io
        import pyarrow.parquet as pq
        source = [r for r in pq.read_table(io.BytesIO(self.latest_bytes)).to_pylist()
                  if r["category"] in CATEGORIES]
        self.assertEqual({r["category"] for r in source}, set(CATEGORIES))
        self.assertEqual(len(source), sum(len(rows) for groups in self.latest.values() for rows in groups.values()))
        result = subprocess.run(["node", "tests/verify-arena.mjs", "--source-rows"], cwd=ROOT,
                                input=json.dumps(source), capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PASS all {len(source)} source rows", result.stdout)

    def test_daily_fetch_keeps_compact_history_and_avoids_repeated_full_download(self):
        calls = []
        def fetch(name):
            calls.append(name)
            return self.fetch(name)
        state = refresh({}, NOW, fetch)
        self.assertEqual(state["fetch_status"], "ok")
        self.assertEqual(len(calls), 2)
        old_snapshot = deepcopy(state["snapshot"])
        state = refresh(state, NOW + timedelta(hours=1), fetch)
        self.assertEqual(len(calls), 2)
        state = refresh(state, NOW + timedelta(days=1), fetch)
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[-1].startswith("latest"))
        self.assertEqual(state["snapshot"], old_snapshot)

    def test_failed_history_still_publishes_latest_and_retries_only_weekly(self):
        calls = []
        def fetch(name):
            calls.append(name)
            if name.startswith("full"):
                raise TimeoutError()
            return self.latest_bytes
        state = refresh({}, NOW, fetch)
        self.assertEqual(state["snapshot"]["published_at"], "2026-10-08")
        self.assertIsNone(state["snapshot"]["comparison_at"])
        refresh(state, NOW + timedelta(days=1), fetch)
        self.assertEqual(len([x for x in calls if x.startswith("full")]), 1)
        refresh(state, NOW + timedelta(days=7), fetch)
        self.assertEqual(len([x for x in calls if x.startswith("full")]), 2)

    def test_malformed_partial_duplicate_nonfinite_future_and_regressed_data_retain_good(self):
        import io
        import pyarrow as pa
        import pyarrow.parquet as pq
        rows = pq.read_table(io.BytesIO(self.latest_bytes)).to_pylist()
        good = refresh({}, NOW, self.fetch)
        variants = [b"not parquet"]
        for changed in [rows + [rows[0]], [r for r in rows if r["category"] != "hard_prompts"],
                        [{**r, "rating": float("nan")} if i == 0 else r for i, r in enumerate(rows)]]:
            stream = io.BytesIO()
            pq.write_table(pa.Table.from_pylist(changed), stream)
            variants.append(stream.getvalue())
        for content in variants:
            with self.subTest(size=len(content)):
                result = refresh(good, NOW + timedelta(days=1), lambda _: content)
                self.assertEqual(result["fetch_status"], "failed")
                self.assertEqual(result["snapshot"], good["snapshot"])
        for published in ["2026-09-30", "2026-11-01"]:
            with patch("radar.arena.parse_parquet", return_value={published: self.latest["2026-10-08"]}):
                result = refresh(good, NOW + timedelta(days=1), self.fetch)
            self.assertEqual(result["fetch_status"], "failed")
            self.assertEqual(result["snapshot"], good["snapshot"])


if __name__ == "__main__":
    unittest.main()

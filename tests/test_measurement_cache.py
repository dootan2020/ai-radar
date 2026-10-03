"""Synthetic offline baseline cases; counts never represent live source health."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build
from radar.measurement_cache import load_baseline, promotion_reason

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def snapshot(at=NOW, good=10, observations=10):
    stamp = at.isoformat()
    return dict(schema_version=2, generated_at=stamp,
                sources=[dict(id=f"remote-{i}", ok=i < good, count=observations if i == 0 else 0,
                              url=f"https://example.org/{i}", error=None if i < good else "Failed")
                         for i in range(10)] + [dict(id="curated-events", ok=True, count=2, url=None, error=None)],
                stories=[dict(source_count=1, coverage=[dict(id=f"item-{i}", source="remote-0",
                    metrics={"points": i}, observed_at=stamp)]) for i in range(observations)],
                updates=[], hf_releases=[], live=[], trending=dict(github=[], huggingface=[]),
                sections=dict(hot=[]), events=[])


class BaselineTests(unittest.TestCase):
    def test_good_first_run_can_seed_and_zero_is_real_measurement(self):
        self.assertIsNone(promotion_reason(snapshot(observations=1), None, NOW))

    def test_first_bad_all_failed_and_empty_runs_cannot_seed(self):
        for payload in (snapshot(good=0), snapshot(good=7), snapshot(observations=0)):
            with self.subTest(payload=payload):
                self.assertIsNotNone(promotion_reason(payload, None, NOW))

    def test_quorum_boundary_is_inclusive_and_calendar_does_not_count(self):
        self.assertIsNone(promotion_reason(snapshot(good=8), None, NOW))
        self.assertIsNotNone(promotion_reason(snapshot(good=7), None, NOW))

    def test_disabled_sources_are_excluded_but_failures_are_not(self):
        payload = snapshot(good=7)
        payload["sources"][9]["disabled"] = True
        self.assertIsNotNone(promotion_reason(payload, None, NOW))
        payload["sources"][8]["disabled"] = True
        self.assertIsNone(promotion_reason(payload, None, NOW))

    def test_severe_measurement_loss_preserves_prior_snapshot(self):
        previous = snapshot(NOW - timedelta(hours=1))
        self.assertIsNotNone(promotion_reason(snapshot(observations=4), previous, NOW))
        self.assertIsNone(promotion_reason(snapshot(observations=5), previous, NOW))

    def test_failed_measured_source_cannot_be_hidden_by_healthy_rss_sources(self):
        previous = snapshot(NOW - timedelta(hours=1))
        current = snapshot()
        current["sources"][0]["ok"] = False
        for story in current["stories"]:
            story["coverage"][0]["source"] = "remote-1"
        self.assertIsNotNone(promotion_reason(current, previous, NOW))

    def test_successful_but_empty_measured_source_cannot_hide_behind_another(self):
        previous = snapshot(NOW - timedelta(hours=1))
        previous["stories"][0]["coverage"][0]["source"] = "remote-1"
        self.assertIsNotNone(promotion_reason(snapshot(), previous, NOW))

    def test_counts_measurement_identities_once_across_duplicate_coverage(self):
        previous = snapshot(NOW - timedelta(hours=1))
        payload = snapshot(observations=1)
        payload["stories"] *= 10
        self.assertIsNotNone(promotion_reason(payload, previous, NOW))

    def test_successful_empty_rss_feeds_are_not_failed_sources(self):
        payload = snapshot(observations=1)
        self.assertEqual(sum(source["count"] == 0 for source in payload["sources"]), 9)
        self.assertIsNone(promotion_reason(payload, None, NOW))

    def test_missing_metrics_do_not_become_zeroes(self):
        for value in (None, True, "12", -1, float("nan"), float("inf")):
            payload = snapshot(observations=1)
            payload["stories"][0]["coverage"][0]["metrics"]["points"] = value
            self.assertIsNotNone(promotion_reason(payload, None, NOW))

    def test_missing_corrupt_schema_and_age_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            self.assertIsNone(load_baseline(path, NOW))
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(load_baseline(path, NOW))
            valid = snapshot(NOW - timedelta(hours=1))
            cases = [[], valid | {"schema_version": 1}, valid | {"stories": {}},
                     valid | {"sources": []}, valid | {"generated_at": "2026-10-02"},
                     snapshot(NOW), snapshot(NOW + timedelta(seconds=1)),
                     snapshot(NOW - timedelta(hours=48, seconds=1))]
            for payload in cases:
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertIsNone(load_baseline(path, NOW))
            payload = snapshot(NOW - timedelta(hours=48))
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_baseline(path, NOW), payload)

    def test_malformed_coverage_and_future_observations_are_rejected(self):
        for change in ({"coverage": None}, {"coverage": [None]}, {"coverage": [dict(
                id="x", source="remote-0", metrics={"points": 1}, observed_at=(NOW + timedelta(seconds=1)).isoformat())]}):
            payload = snapshot(observations=1)
            payload["stories"][0].update(change)
            self.assertIsNotNone(promotion_reason(payload, None, NOW))

    def test_malformed_source_status_cannot_pass_quorum(self):
        for change in ({"count": None}, {"count": True}, {"count": -1}, {"ok": "true"}, {"url": None}):
            payload = snapshot()
            payload["sources"][0].update(change)
            self.assertIsNotNone(promotion_reason(payload, None, NOW))


class BuildBaselineTests(unittest.TestCase):
    @staticmethod
    def display_snapshot(at=NOW, good=10, observations=10):
        payload = snapshot(at, good, observations)
        payload["sections"] = {key: [] for key in
                               ("today", "hot", "models", "papers", "listen", "voices", "community", "upcoming")}
        for index, story in enumerate(payload["stories"]):
            story.update(id=f"story-{index}", title="AI update", url=f"https://example.org/{index}")
            for item in story["coverage"]:
                item.update(title=story["title"], url=story["url"])
        return payload

    def test_output_and_baseline_cannot_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "radar.json")
            with patch.dict(os.environ, {"RADAR_OUTPUT": path, "RADAR_BASELINE": path}, clear=True):
                with self.assertRaisesRegex(ValueError, "different files"):
                    build.main()

    def test_existing_display_snapshot_is_not_used_as_measurement_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "radar.json"
            path.write_text(json.dumps(snapshot(NOW - timedelta(hours=1))), encoding="utf-8")
            with patch.dict(os.environ, {"RADAR_OUTPUT": str(path),
                    "RADAR_BASELINE": str(path.parent / "measurement-baseline.json")}, clear=True), \
                    patch.object(build, "build_v2", return_value=snapshot(good=0)) as collect, \
                    redirect_stdout(io.StringIO()):
                build.main()
            self.assertIsNone(collect.call_args.kwargs["previous"])

    def test_good_degraded_good_sequence_keeps_baseline_bytes_and_current_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "radar.json"
            baseline = Path(directory) / "measurement-baseline.json"
            github_output = Path(directory) / "github-output.txt"
            previous = self.display_snapshot(NOW - timedelta(hours=1))
            baseline.write_text(json.dumps(previous), encoding="utf-8")
            original = baseline.read_bytes()
            bad = self.display_snapshot(good=7)
            env = {"RADAR_OUTPUT": str(output), "RADAR_BASELINE": str(baseline), "GITHUB_OUTPUT": str(github_output)}
            with patch.dict(os.environ, env), patch.object(build, "datetime") as clock:
                clock.now.return_value = NOW
                with patch.object(build, "build_v2", return_value=bad) as collect, redirect_stdout(io.StringIO()):
                    build.main()
                self.assertEqual(collect.call_args.kwargs["previous"], previous)
                self.assertEqual(baseline.read_bytes(), original)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8")), bad)
                self.assertIn("baseline_updated=false", github_output.read_text(encoding="utf-8"))
                good = self.display_snapshot(NOW + timedelta(minutes=1))
                clock.now.return_value = NOW + timedelta(minutes=1)
                with patch.object(build, "build_v2", return_value=good), redirect_stdout(io.StringIO()):
                    build.main()
                self.assertEqual(json.loads(baseline.read_text(encoding="utf-8")), good)
                self.assertTrue(github_output.read_text(encoding="utf-8").endswith("baseline_updated=true\n"))

    def test_first_bad_build_writes_diagnostic_without_creating_published_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "radar.json"
            with patch.dict(os.environ, {"RADAR_OUTPUT": str(output),
                    "RADAR_BASELINE": str(output.parent / "measurement-baseline.json")}, clear=True), \
                    patch.object(build, "build_v2", return_value=snapshot(good=0)), redirect_stdout(io.StringIO()):
                self.assertEqual(build.main(), 1)
            self.assertFalse(output.exists())
            diagnostic = json.loads((output.parent / "publish-status.json").read_text(encoding="utf-8"))
            self.assertFalse(diagnostic["published"])
            self.assertFalse((output.parent / "measurement-baseline.json").exists())


if __name__ == "__main__":
    unittest.main()

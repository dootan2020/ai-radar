"""Offline publication regressions; synthetic sources are not live measurements."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build
from radar.publication import SECTIONS, assess_publication, load_published

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def projection_rows():
    return dict(
        updates=dict(id="update", title="AI update", url="https://example.org/update", published_at=None),
        hf_releases=dict(id="org/model", url="https://huggingface.co/org/model", created_at=None),
        live=dict(title="AI video", url="https://youtube.com/watch?v=video", status="ended",
                  start_at=None, end_at=None, time_precision="relative", time_text="Streamed 1d ago"),
        events=dict(id="event", title="AI event", url="https://example.org/event",
                    start_date="2026-10-04", end_date="2026-10-04", time_precision="date",
                    start_at=None, end_at=None),
        repos=dict(id="org/repo", full_name="org/repo", url="https://github.com/org/repo", created_at=None))


def snapshot(at=NOW, good=42):
    stamp = at.isoformat()
    item = dict(id="item", source="remote-0", title="AI update", url="https://example.org/story",
                observed_at=stamp, metrics={"points": 7})
    return dict(schema_version=2, generated_at=stamp,
                sources=[dict(id=f"remote-{i}", ok=i < good, count=1 if i == 0 else 0,
                              url=f"https://example.org/{i}", error=None if i < good else "Failed")
                         for i in range(42)] +
                        [dict(id=f"disabled-{i}", ok=False, disabled=True, count=0, url=None, error="Disabled")
                         for i in range(4)] + [dict(id="curated-events", ok=True, count=1, url=None, error=None)],
                stories=[dict(id="story", title="AI update", url=item["url"], source_count=1, coverage=[item])],
                sections={key: ["story"] if key == "today" else [] for key in SECTIONS},
                updates=[], hf_releases=[], live=[], events=[], trending=dict(github=[], huggingface=[]))


class PublicationPolicyTests(unittest.TestCase):
    def test_healthy_single_failure_and_partial_outage_publish(self):
        for good in (42, 41, 28):
            with self.subTest(good=good):
                result = assess_publication(snapshot(good=good), None, NOW)
                self.assertTrue(result["published"], result)
                self.assertEqual(result["active_remote_sources"], 42)
                self.assertEqual(result["successful_remote_sources"], good)
                self.assertEqual(result["required_successful_sources"], 28)

    def test_below_quorum_majority_and_all_failed_reject(self):
        for good in (27, 21, 1, 0):
            self.assertFalse(assess_publication(snapshot(good=good), None, NOW)["published"])

    def test_curated_only_stories_cannot_mask_empty_remote_collection(self):
        payload = snapshot()
        payload["stories"][0]["coverage"][0]["source"] = "curated-events"
        for row in payload["sources"]:
            if row["id"] != "curated-events":
                row["count"] = 0
        self.assertFalse(assess_publication(payload, None, NOW)["published"])

    def test_one_failed_measured_source_has_no_publication_veto(self):
        payload = snapshot()
        payload["sources"][0]["ok"] = False
        payload["stories"][0]["coverage"][0]["source"] = "remote-1"
        self.assertTrue(assess_publication(payload, snapshot(NOW - timedelta(minutes=30)), NOW)["published"])

    def test_empty_and_malformed_contracts_reject(self):
        cases = [None, [], {}, snapshot() | {"schema_version": 1}, snapshot() | {"stories": []},
                 snapshot() | {"sources": []}, snapshot() | {"generated_at": "2026-10-03"},
                 snapshot() | {"sections": {}}, snapshot() | {"stories": [None]},
                 snapshot() | {"sources": [None]}, snapshot() | {"trending": {}}]
        for key, value in (("id", None), ("title", ""), ("url", "javascript:alert(1)"),
                           ("coverage", []), ("coverage", [None]), ("source_count", True)):
            payload = snapshot()
            payload["stories"][0][key] = value
            cases.append(payload)
        for key, value in (("ok", "true"), ("count", True), ("url", []), ("disabled", "true")):
            payload = snapshot()
            payload["sources"][0][key] = value
            cases.append(payload)
        for key, value in (("source", []), ("metrics", []), ("observed_at", "unknown")):
            payload = snapshot()
            payload["stories"][0]["coverage"][0][key] = value
            cases.append(payload)
        payload = snapshot()
        payload["sections"]["hot"] = ["missing-story"]
        cases.append(payload)
        payload = snapshot()
        payload["stories"] *= 2
        cases.append(payload)
        payload = snapshot()
        payload["sources"] *= 2
        cases.append(payload)
        payload = snapshot()
        payload["stories"][0]["coverage"][0]["metrics"]["points"] = float("nan")
        cases.append(payload)
        for index, payload in enumerate(cases):
            with self.subTest(case=index):
                self.assertFalse(assess_publication(payload, None, NOW)["published"])

    def test_fresh_recovery_exposes_gap_without_reaging_previous_snapshot(self):
        old = snapshot(NOW - timedelta(days=3))
        original = copy.deepcopy(old)
        result = assess_publication(snapshot(), old, NOW)
        self.assertTrue(result["published"])
        self.assertTrue(result["freshness"]["previous_stale"])
        self.assertTrue(result["freshness"]["scheduler_gap"])
        self.assertEqual(result["freshness"]["gap_seconds"], 3 * 86400)
        self.assertEqual(old, original)

    def test_story_and_coverage_sort_timestamps_still_reject_whole_snapshot(self):
        cases = []
        for field in ("published_at", "start_at", "end_at"):
            payload = snapshot()
            payload["stories"][0][field] = {"invalid": "timestamp"}
            cases.append(payload)
            payload = snapshot()
            payload["stories"][0]["coverage"][0][field] = 12
            cases.append(payload)
        for index, payload in enumerate(cases):
            with self.subTest(case=index):
                self.assertFalse(assess_publication(payload, None, NOW)["published"])

    def test_invalid_projection_rows_are_counted_without_vetoing_publication(self):
        for section, valid in projection_rows().items():
            invalid = [None, {}, valid | {"url": "javascript:bad"},
                       valid | {"published_at": "garbage"}, valid | {"extra": float("nan")}]
            name = "id" if section == "hf_releases" else "full_name" if section == "repos" else "title"
            invalid.append(valid | {name: None})
            if section in {"hf_releases", "repos"}:
                invalid.append(valid | {"created_at": "garbage"})
            if section == "live":
                invalid.extend(valid | {"status": value} for value in ("invalid", [], {}))
            if section == "events":
                invalid.extend(valid | {field: value} for field, value in (
                    ("start_date", {}), ("end_date", 12), ("end_date", "2026-10-03"),
                    ("start_date", "2026-02-30"), ("id", None), ("time_precision", "exact"),
                    ("time_precision", []), ("start_at", NOW.isoformat())))
            for row in invalid:
                with self.subTest(section=section, row=row):
                    payload = snapshot() | {section: [valid, row]}
                    result = assess_publication(payload, None, NOW)
                    self.assertTrue(result["published"], result)
                    self.assertEqual(result["dropped_projection_rows"],
                                     {key: int(key == section) for key in projection_rows()})

    def test_invalid_projection_containers_still_reject(self):
        for section in projection_rows():
            for rows in (None, {}, "broken"):
                with self.subTest(section=section, rows=rows):
                    self.assertFalse(assess_publication(snapshot() | {section: rows}, None, NOW)["published"])

    def test_date_only_events_and_relative_live_times_keep_unknown_timestamps(self):
        payload = snapshot()
        payload["events"] = [dict(id="event", title="AI event", url="https://example.org/event",
                                  start_date="2026-10-04", end_date="2026-10-04", time_precision="date",
                                  start_at=None, end_at=None)]
        payload["live"] = [dict(title="AI video", url="https://youtube.com/watch?v=video", status="ended",
                                start_at=None, end_at=None, time_precision="relative", time_text="Streamed 1d ago")]
        self.assertTrue(assess_publication(payload, None, NOW)["published"])

    def test_stale_future_and_nonadvancing_candidates_reject(self):
        for at in (NOW - timedelta(hours=3, seconds=1), NOW + timedelta(seconds=1)):
            self.assertFalse(assess_publication(snapshot(at), None, NOW)["published"])
        self.assertFalse(assess_publication(snapshot(), snapshot(), NOW)["published"])

    def test_previous_cache_accepts_old_evidence_but_ignores_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published.json"
            self.assertIsNone(load_published(path, NOW))
            path.write_bytes(b"not json")
            self.assertIsNone(load_published(path, NOW))
            old = snapshot(NOW - timedelta(days=7))
            path.write_bytes(json.dumps(old).encode())
            self.assertEqual(load_published(path, NOW), old)
            malformed = old | {"live": [None]}
            path.write_bytes(json.dumps(malformed).encode())
            before = path.read_bytes()
            self.assertIsNone(load_published(path, NOW))
            self.assertEqual(path.read_bytes(), before)


class PublicationBuildTests(unittest.TestCase):
    def run_build(self, directory, payload, error=None):
        paths = {key: Path(directory) / name for key, name in (
            ("RADAR_OUTPUT", "radar.json"), ("RADAR_BASELINE", "baseline.json"),
            ("RADAR_PUBLISHED_SNAPSHOT", "published.json"), ("RADAR_PUBLISH_STATUS", "status.json"),
            ("RADAR_SITEMAP", "sitemap.xml"), ("GITHUB_OUTPUT", "outputs.txt"))}
        with patch.dict(os.environ, {key: str(value) for key, value in paths.items()}, clear=True), \
                patch.object(build, "datetime") as clock, \
                patch.object(build, "build_v2", return_value=payload, side_effect=error), redirect_stdout(io.StringIO()):
            clock.now.return_value = NOW
            code = build.main()
        return code, paths

    def test_rejection_preserves_all_prior_published_artifacts_bytes_and_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            old = snapshot(NOW - timedelta(minutes=30))
            files = []
            for name in ("radar.json", "radar-ui.json", "published.json", "baseline.json", "sitemap.xml"):
                path = Path(directory) / name
                path.write_bytes(json.dumps(old).encode() if path.suffix == ".json" else b"<previous-sitemap/>")
                files.append((path, path.read_bytes(), path.stat().st_mtime_ns))
            malformed_projections = {key: [None] for key in projection_rows()}
            invalid = [snapshot(good=0), snapshot() | {"stories": []}, None,
                       snapshot(good=27) | malformed_projections,
                       snapshot(NOW - timedelta(hours=4)) | malformed_projections,
                       snapshot(NOW + timedelta(seconds=1)) | malformed_projections,
                       snapshot(NOW - timedelta(minutes=30)) | malformed_projections,
                       snapshot() | malformed_projections | {"sources": [None]},
                       snapshot() | malformed_projections | {"sections": {"today": ["missing"]}}]
            curated = snapshot() | malformed_projections
            curated["stories"][0]["coverage"][0]["source"] = "curated-events"
            invalid.append(curated)
            for payload in invalid:
                code, paths = self.run_build(directory, payload)
                self.assertEqual(code, 1)
                for path, content, mtime in files:
                    self.assertEqual(path.read_bytes(), content)
                    self.assertEqual(path.stat().st_mtime_ns, mtime)
                status = json.loads(paths["RADAR_PUBLISH_STATUS"].read_text())
                self.assertFalse(status["published"])
                if isinstance(payload, dict) and payload.get("live") == [None]:
                    self.assertEqual(status["dropped_projection_rows"], {key: 1 for key in projection_rows()})
                self.assertEqual(status["freshness"]["previous_generated_at"], "2026-10-03T11:30:00Z")
                self.assertIn("published_snapshot_updated=false", paths["GITHUB_OUTPUT"].read_text())

    def test_build_writes_filtered_rows_and_identical_drop_counts_to_both_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = projection_rows()
            payload = snapshot() | {key: [row, None, row | {"url": "javascript:bad"}]
                                    for key, row in valid.items()}
            original = copy.deepcopy(payload)
            code, paths = self.run_build(directory, payload)
            self.assertEqual(code, 0)
            status = json.loads(paths["RADAR_PUBLISH_STATUS"].read_text())
            output = json.loads(paths["RADAR_OUTPUT"].read_text())
            expected_counts = {key: 2 for key in valid}
            self.assertEqual(status["dropped_projection_rows"], expected_counts)
            self.assertEqual(output["dropped_projection_rows"], expected_counts)
            for key, row in valid.items():
                self.assertEqual(output[key], [row])
            self.assertEqual(payload, original)
            self.assertEqual(output["generated_at"], original["generated_at"])
            self.assertEqual(output, json.loads(paths["RADAR_PUBLISHED_SNAPSHOT"].read_text()))
            self.assertEqual(output, json.loads(paths["RADAR_BASELINE"].read_text()))
            self.assertEqual(load_published(paths["RADAR_PUBLISHED_SNAPSHOT"], NOW), output)
            from radar.site_payload import page_payload, page_path
            self.assertEqual(json.loads(page_path(paths["RADAR_OUTPUT"]).read_text()), page_payload(output))

    def test_cold_start_rejection_writes_only_diagnostic_and_ci_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            code, paths = self.run_build(directory, snapshot(good=0))
            self.assertEqual(code, 1)
            for key in ("RADAR_OUTPUT", "RADAR_BASELINE", "RADAR_PUBLISHED_SNAPSHOT", "RADAR_SITEMAP"):
                self.assertFalse(paths[key].exists())
            self.assertFalse((Path(directory) / "radar-ui.json").exists())
            self.assertIsNone(json.loads(paths["RADAR_PUBLISH_STATUS"].read_text())["freshness"]["previous_generated_at"])

    def test_healthy_cold_start_writes_separate_caches_and_sitemap(self):
        with tempfile.TemporaryDirectory() as directory:
            code, paths = self.run_build(directory, snapshot())
            self.assertEqual(code, 0)
            output = json.loads(paths["RADAR_OUTPUT"].read_text())
            self.assertIn("freshness", output)
            self.assertEqual(output["dropped_projection_rows"], {key: 0 for key in projection_rows()})
            self.assertEqual(output, json.loads(paths["RADAR_PUBLISHED_SNAPSHOT"].read_text()))
            self.assertEqual(output, json.loads(paths["RADAR_BASELINE"].read_text()))
            self.assertIn(b"2026-10-03T12:00:00Z", paths["RADAR_SITEMAP"].read_bytes())

    def test_collection_exception_is_rejected_with_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            code, paths = self.run_build(directory, None, RuntimeError("private detail"))
            self.assertEqual(code, 1)
            status = json.loads(paths["RADAR_PUBLISH_STATUS"].read_text())
            self.assertEqual(status["reason"], "collection failed: RuntimeError")
            self.assertFalse(paths["RADAR_OUTPUT"].exists())

    def test_partial_publication_does_not_promote_measurement_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.json"
            old = json.dumps(snapshot(NOW - timedelta(minutes=30))).encode()
            baseline.write_bytes(old)
            code, paths = self.run_build(directory, snapshot(good=28))
            self.assertEqual(code, 0)
            self.assertEqual(baseline.read_bytes(), old)
            self.assertEqual(json.loads(paths["RADAR_OUTPUT"].read_text())["freshness"]["stale_after_seconds"], 10800)
            self.assertIn("baseline_updated=false", paths["GITHUB_OUTPUT"].read_text())


if __name__ == "__main__":
    unittest.main()

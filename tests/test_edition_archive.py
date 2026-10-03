"""Immutable archive and publication rejection proofs, entirely offline."""

import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from radar.edition_archive import append_archive, load_archive, publication_eligible
from radar.publication import assess_publication
from test_editions import ASTA, NOW, real_snapshot, subset


def accepted(payload, now=NOW):
    result = assess_publication(payload, None, now)
    if not result["published"]:
        raise AssertionError(result)
    return result


def bytes_in(directory):
    return {path.name: path.read_bytes() for path in Path(directory).iterdir()}


def next_day(payload):
    """Controlled clock shift; do not present as a second live capture."""
    result = copy.deepcopy(payload)
    result["generated_at"] = (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    for story in result["stories"]:
        for item in story["coverage"]:
            item["observed_at"] = result["generated_at"]
    return result


class EditionArchiveTests(unittest.TestCase):
    def test_append_next_date_preserves_old_bytes_and_builds_descending_index(self):
        payload = real_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "editions"
            first = append_archive(payload, accepted(payload), root, NOW)
            first_bytes = (root / "2026-10-03.json").read_bytes()
            later = next_day(payload)
            append_archive(later, accepted(later, NOW + timedelta(days=1)), root, NOW + timedelta(days=1))
            self.assertEqual((root / "2026-10-03.json").read_bytes(), first_bytes)
            self.assertEqual([row["date"] for row in load_archive(root)], ["2026-10-04", "2026-10-03"])
            self.assertEqual(load_archive(root)[1], first)
            index = json.loads((root / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["latest"], {"date": "2026-10-04", "path": "2026-10-04.json"})
            self.assertEqual([row["story_count"] for row in index["editions"]], [0, 3])

    def test_same_day_rerun_is_byte_and_mtime_identical_despite_changed_snapshot(self):
        payload = real_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = append_archive(payload, accepted(payload), root, NOW)
            before = bytes_in(root)
            mtimes = {path.name: path.stat().st_mtime_ns for path in root.iterdir()}
            later = NOW + timedelta(minutes=30)
            payload["generated_at"] = later.isoformat().replace("+00:00", "Z")
            payload["stories"][0]["title_vi"] = "Controlled changed translation"
            second = append_archive(payload, accepted(payload, later), root, later)
            self.assertEqual(first, second)
            self.assertEqual(bytes_in(root), before)
            self.assertEqual({path.name: path.stat().st_mtime_ns for path in root.iterdir()}, mtimes)

    def test_empty_first_edition_stays_empty_when_more_stories_arrive(self):
        payload = subset(real_snapshot(), {"b6aee1da4c9da9519c63"})
        with tempfile.TemporaryDirectory() as directory:
            first = append_archive(payload, accepted(payload), directory, NOW)
            before = bytes_in(directory)
            self.assertEqual(first["stories"], [])
            full = real_snapshot()
            second = append_archive(full, accepted(full), directory, NOW)
            self.assertEqual(second["stories"], [])
            self.assertEqual(bytes_in(directory), before)

    def test_rejected_status_does_not_create_archive_or_change_existing_bytes(self):
        payload = real_snapshot()
        status = accepted(payload)
        variants = [None, {}, status | {"published": False}, status | {"published": "true"},
                    status | {"reason": "rejected"}, status | {"attempted_at": "2026-10-02T09:18:01Z"},
                    status | {"attempted_at": "2026-10-04T09:18:01Z"},
                    status | {"freshness": status["freshness"] | {"generated_at": "2026-10-03T09:00:00Z"}}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "history"
            for bad in variants:
                with self.subTest(status=bad):
                    self.assertFalse(publication_eligible(payload, bad, NOW))
                    self.assertIsNone(append_archive(payload, bad, root, NOW))
                    self.assertFalse(root.exists())
            append_archive(payload, status, root, NOW)
            before = bytes_in(root)
            for bad in variants:
                self.assertIsNone(append_archive(payload, bad, root, NOW))
                self.assertEqual(bytes_in(root), before)

    def test_stale_future_or_malformed_snapshot_cannot_use_prior_success(self):
        payload = real_snapshot()
        status = accepted(payload)
        cases = [(payload, status, NOW + timedelta(hours=3, seconds=1))]
        for timestamp in (None, "2026-10-03", "2026-10-04T09:18:01Z"):
            mutated = copy.deepcopy(payload)
            mutated["generated_at"] = timestamp
            matched = status | {"freshness": status["freshness"] | {"generated_at": timestamp}}
            cases.append((mutated, matched, NOW))
        broken = copy.deepcopy(payload)
        for source in broken["sources"]:
            source["ok"] = False
        cases.append((broken, status, NOW))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "editions"
            for candidate, diagnostic, clock in cases:
                self.assertIsNone(append_archive(candidate, diagnostic, root, clock))
                self.assertFalse(root.exists())

    def test_morning_cut_must_be_observed_by_the_snapshot(self):
        payload = real_snapshot()
        clock = NOW.replace(hour=23, minute=1, second=0) - timedelta(days=1)
        payload["generated_at"] = "2026-10-02T22:59:00Z"
        for story in payload["stories"]:
            for item in story["coverage"]:
                item["observed_at"] = payload["generated_at"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "editions"
            self.assertIsNone(append_archive(payload, accepted(payload, clock), root, clock))
            self.assertFalse(root.exists())

    def test_corruption_is_not_silently_replaced_with_a_new_archive(self):
        payload = real_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            append_archive(payload, accepted(payload), root, NOW)
            target = root / "2026-10-03.json"
            target.write_bytes(b"{broken-json")
            before = bytes_in(root)
            with self.assertRaises(ValueError):
                load_archive(root)
            with self.assertRaises(ValueError):
                append_archive(payload, accepted(payload), root, NOW)
            self.assertEqual(bytes_in(root), before)

    def test_missing_file_or_mismatched_index_is_rejected(self):
        payload = real_snapshot()
        for mutation in ("missing", "count", "latest"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                append_archive(payload, accepted(payload), root, NOW)
                if mutation == "missing":
                    (root / "2026-10-03.json").unlink()
                else:
                    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
                    if mutation == "count":
                        index["editions"][0]["story_count"] = 99
                    else:
                        index["latest"]["date"] = "2026-10-02"
                    (root / "index.json").write_bytes(json.dumps(index).encode())
                with self.assertRaises(ValueError):
                    load_archive(root)

    def test_missing_index_after_interrupted_write_repairs_without_editing_daily_file(self):
        payload = real_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = append_archive(payload, accepted(payload), root, NOW)
            before = (root / "2026-10-03.json").read_bytes()
            (root / "index.json").unlink()
            self.assertEqual(load_archive(root), [first])
            self.assertEqual(append_archive(payload, accepted(payload), root, NOW), first)
            self.assertTrue((root / "index.json").is_file())
            self.assertEqual((root / "2026-10-03.json").read_bytes(), before)

    def test_corrupt_selection_reasons_are_rejected_before_archive_append(self):
        payload = real_snapshot()
        variants = [[None], [{}], [{"code": None, "text": "label"}],
                    [{"code": "primary_release", "text": None}],
                    [{"code": "", "text": "label"}],
                    [{"code": "primary_release", "text": ""}]]
        for reasons in variants:
            with self.subTest(reasons=reasons), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                append_archive(payload, accepted(payload), root, NOW)
                target = root / "2026-10-03.json"
                edition = json.loads(target.read_text(encoding="utf-8"))
                edition["stories"][0]["selection"]["reasons"] = reasons
                target.write_bytes(json.dumps(edition, ensure_ascii=False).encode("utf-8"))
                before = bytes_in(root)
                with self.assertRaises(ValueError):
                    load_archive(root)
                with self.assertRaises(ValueError):
                    append_archive(payload, accepted(payload), root, NOW)
                self.assertEqual(bytes_in(root), before)

    def test_corrupt_coverage_times_cannot_survive_archive_restore(self):
        payload = real_snapshot()
        variants = [("published_at", "not-a-date"), ("published_at", None),
                    ("published_at", "2026-10-01T22:59:59Z"),
                    ("published_at", "2026-10-02T23:00:00Z"),
                    ("time_basis", "repository_created"), ("time_basis", None),
                    ("observed_at", "not-a-date"), ("observed_at", None),
                    ("observed_at", "2026-10-03T09:18:02Z")]
        for field, value in variants:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                append_archive(payload, accepted(payload), root, NOW)
                target = root / "2026-10-03.json"
                edition = json.loads(target.read_text(encoding="utf-8"))
                edition["stories"][0]["coverage"][0][field] = value
                target.write_bytes(json.dumps(edition, ensure_ascii=False).encode("utf-8"))
                before = bytes_in(root)
                with self.assertRaises(ValueError):
                    load_archive(root)
                with self.assertRaises(ValueError):
                    append_archive(payload, accepted(payload), root, NOW)
                self.assertEqual(bytes_in(root), before)

    def test_reason_evidence_must_reference_the_archived_observations(self):
        payload = real_snapshot()
        variants = [
            (0, "code", "unsupported_policy"),
            (0, "observation_ids", ["missing-observation"]),
            (0, "observation_ids", []),
            (1, "publishers", ["nonexistent-publisher", "another-publisher"]),
            (2, "percentile", 0.79),
            (2, "percentile", 1.01),
            (2, "measurement", {"source": "hn-ai", "metric": "points", "value": 0}),
            (2, "measurement", {"source": "unknown", "metric": "points", "value": 186,
                                 "observed_at": "2026-10-03T09:18:01Z"}),
            (2, "measurement", {"source": "hn-ai", "metric": "points", "value": 186,
                                 "observed_at": "2026-10-03T09:18:02Z"}),
        ]
        for story_index, field, value in variants:
            with self.subTest(story=story_index, field=field, value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                append_archive(payload, accepted(payload), root, NOW)
                target = root / "2026-10-03.json"
                edition = json.loads(target.read_text(encoding="utf-8"))
                reason = edition["stories"][story_index]["selection"]["reasons"][0]
                reason[field] = value
                target.write_bytes(json.dumps(edition, ensure_ascii=False).encode("utf-8"))
                with self.assertRaises(ValueError):
                    load_archive(root)


if __name__ == "__main__":
    unittest.main()

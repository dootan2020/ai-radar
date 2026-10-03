"""Local failure injection verifies public last-good data survives field failures."""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radar import field_publish
from radar.field_history import FILENAME, load
from radar.field_rankings import collect
from radar.pipeline import write_atomic
from test_field_rankings import FixtureAPI, NOW, repository


class FieldRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="field-recovery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "published.json"
        self.candidate = self.root / "candidate"
        self.fallback = self.root / "last-good.json"
        self.good, self.state = collect(FixtureAPI([repository()]), NOW)
        write_atomic(self.good, self.fallback)

    def assert_retained(self):
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(payload["generated_at"], self.good["generated_at"])
        self.assertEqual([f["id"] for f in payload["fields"]], [f["id"] for f in self.good["fields"]])
        for before, after in zip(self.good["fields"], payload["fields"]):
            original = before["ranked"] + before["tracking"]
            retained = after["ranked"] + after["tracking"]
            self.assertEqual([r["repository_id"] for r in retained], [r["repository_id"] for r in original])
            for prior, current in zip(original, retained):
                for key in ("stars", "observed_at", "tracking_since", "stars_net_7d"):
                    self.assertEqual(current[key], prior[key])
        self.assertFalse(payload["complete"])
        return payload

    def test_collect_exception_publishes_remote_last_good_on_fresh_runner(self):
        with patch.object(field_publish, "restore", return_value=("a" * 40, deepcopy(self.state))), \
                patch.object(field_publish, "collect", side_effect=RuntimeError("synthetic collect failure")):
            with self.assertRaises(RuntimeError):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1), FixtureAPI())
        self.assert_retained()

    def test_cold_cache_is_seeded_before_a_failed_collection(self):
        self.fallback.unlink()
        with patch.object(field_publish, "restore", return_value=("a" * 40, deepcopy(self.state))), \
                patch.object(field_publish, "collect", side_effect=RuntimeError("synthetic collect failure")):
            with self.assertRaises(RuntimeError):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1),
                                      FixtureAPI(), fallback=self.fallback)
        self.assert_retained()
        self.assertEqual(json.loads(self.fallback.read_text(encoding="utf-8")), self.good)

    def test_restore_failure_keeps_separately_cached_last_good(self):
        with patch.object(field_publish, "restore", side_effect=RuntimeError("synthetic restore failure")):
            with self.assertRaises(RuntimeError):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1),
                                      FixtureAPI(), fallback=self.fallback)
        self.assert_retained()
        self.assertEqual(json.loads(self.fallback.read_text(encoding="utf-8")), self.good)

    def test_candidate_write_failure_cannot_replace_last_good(self):
        def write(payload, path):
            if Path(path).parent == self.candidate:
                raise OSError("synthetic candidate write failure")
            return write_atomic(payload, path)

        with patch.object(field_publish, "restore", return_value=("a" * 40, deepcopy(self.state))), \
                patch.object(field_publish, "write_atomic", side_effect=write):
            with self.assertRaises(OSError):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1),
                                      FixtureAPI([repository(stargazers_count=250)]), fallback=self.fallback)
        self.assert_retained()

    def test_invalid_cached_evidence_is_not_published(self):
        invalid = deepcopy(self.good)
        invalid["fields"][0]["tracking"][0]["url"] = "https://invalid.example/forged"
        write_atomic(invalid, self.fallback)
        with patch.object(field_publish, "restore", side_effect=RuntimeError("synthetic restore failure")):
            with self.assertRaises((ValueError, RuntimeError)):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1),
                                      FixtureAPI(), fallback=self.fallback)
        self.assertFalse(self.output.exists())

    def test_newer_cached_output_wins_over_lagging_persisted_branch_on_failure(self):
        earlier = NOW - timedelta(days=1)
        _, lagging = collect(FixtureAPI([repository(stargazers_count=150, pushed_at=earlier.isoformat())]), earlier)
        with patch.object(field_publish, "restore", return_value=("a" * 40, lagging)), \
                patch.object(field_publish, "collect", side_effect=RuntimeError("synthetic collect failure")):
            with self.assertRaises(RuntimeError):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1),
                                      FixtureAPI(), fallback=self.fallback)
        self.assert_retained()

    def test_failed_candidate_readback_restores_previous_public_artifact(self):
        with patch.object(field_publish, "restore", return_value=("a" * 40, deepcopy(self.state))), \
                patch.object(field_publish, "load", side_effect=RuntimeError("synthetic readback failure")):
            with self.assertRaises(RuntimeError):
                field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(days=1),
                                      FixtureAPI([repository(stargazers_count=900)]), fallback=self.fallback)
        self.assert_retained()

    def test_daily_reuse_cannot_regress_newer_same_config_cached_output(self):
        earlier = NOW - timedelta(hours=1)
        _, lagging = collect(FixtureAPI([repository(stargazers_count=150, pushed_at=earlier.isoformat())]), earlier)
        api = FixtureAPI()
        with patch.object(field_publish, "restore", return_value=("a" * 40, lagging)):
            returned = field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(hours=1),
                                             api, fallback=self.fallback)
        self.assertEqual(api.requests, [])
        self.assertEqual(returned, self.good)
        self.assertEqual(json.loads(self.output.read_text()), self.good)
        self.assertEqual(load(self.candidate / FILENAME), lagging,
                         "A newer public cache must never invent newer persisted counters")

    def test_newer_cache_from_another_configuration_cannot_override_current_fields(self):
        earlier = NOW - timedelta(hours=1)
        _, lagging = collect(FixtureAPI([repository(stargazers_count=150, pushed_at=earlier.isoformat())]), earlier)
        cached = deepcopy(self.good)
        cached["config_fingerprint"] = "0" * 64
        cached["fields"] = cached["fields"][:1]
        write_atomic(cached, self.fallback)
        api = FixtureAPI()
        with patch.object(field_publish, "restore", return_value=("a" * 40, lagging)):
            returned = field_publish.prepare("unused", self.output, self.candidate, NOW + timedelta(hours=1),
                                             api, fallback=self.fallback)
        self.assertEqual(api.requests, [])
        self.assertEqual(returned, lagging["last_output"])
        self.assertEqual(len(returned["fields"]), 17)
        self.assertEqual(json.loads(self.output.read_text()), returned)


if __name__ == "__main__":
    unittest.main()

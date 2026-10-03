"""Offline checkpoint and actual workflow-guard simulation, not hosted-cache proof."""

from contextlib import redirect_stdout
from datetime import timedelta
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from radar.field_checkpoint import main, reserve, verify_reservation
from test_field_rankings import NOW


class FieldCheckpointTests(unittest.TestCase):
    def test_six_hour_utc_slots_and_real_cli_output(self):
        with tempfile.TemporaryDirectory(prefix="field-checkpoint-") as temporary:
            root = Path(temporary)
            output = root / "github-output"
            checkpoint = root / "attempt.json"
            with patch.dict("os.environ", {"GITHUB_OUTPUT": str(output)}), redirect_stdout(io.StringIO()):
                result = main(["reserve", "--path", str(checkpoint), "--now", "2026-10-03T12:59:00+07:00"])
            self.assertEqual(result, 0)
            outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
            self.assertEqual(outputs["slot"], "2026-10-03-0")
            self.assertEqual(outputs["claim"], json.loads(checkpoint.read_text())["claim"])
            self.assertEqual(json.loads(checkpoint.read_text())["attempted_at"], "2026-10-03T05:59:00Z")
            self.assertEqual(reserve(checkpoint, "2026-10-03T13:00:00+07:00"), "2026-10-03-1")
            self.assertEqual(reserve(checkpoint, "2026-10-04T00:00:00Z"), "2026-10-04-0")

    def test_restored_old_claim_is_rejected_even_when_exact_slot_exists(self):
        with tempfile.TemporaryDirectory(prefix="field-claim-") as temporary:
            path = Path(temporary) / "attempt.json"
            slot = reserve(path, NOW)
            old_marker = path.read_bytes()
            reserve(path, NOW + timedelta(minutes=30))
            claim = json.loads(path.read_text())["claim"]
            self.assertTrue(verify_reservation(path, claim, slot))
            path.write_bytes(old_marker)
            with self.assertRaisesRegex(ValueError, "another attempt"):
                verify_reservation(path, claim, slot)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["verify", "--path", str(path), "--claim", claim, "--slot", slot]), 1)

    def test_missing_or_inconsistent_restored_marker_cannot_authorize_collection(self):
        with tempfile.TemporaryDirectory(prefix="field-claim-") as temporary:
            path = Path(temporary) / "attempt.json"
            with self.assertRaises(ValueError):
                verify_reservation(path, "a" * 32, "2026-10-03-0")
            slot = reserve(path, NOW)
            marker = json.loads(path.read_text())
            marker["attempted_at"] = (NOW + timedelta(hours=6)).isoformat()
            path.write_text(json.dumps(marker), encoding="utf-8", newline="\n")
            with self.assertRaises(ValueError):
                verify_reservation(path, marker["claim"], slot)

    def test_clear_requires_a_restored_archive_not_the_local_unsaved_claim(self):
        with tempfile.TemporaryDirectory(prefix="field-clear-") as temporary:
            path = Path(temporary) / "attempt.json"
            slot = reserve(path, NOW)
            claim = json.loads(path.read_text())["claim"]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["clear", "--path", str(path)]), 0)
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                verify_reservation(path, claim, slot)


class FieldWorkflowGuardTests(unittest.TestCase):
    def setUp(self):
        text = (Path(__file__).parents[1] / ".github/workflows/update.yml").read_text(encoding="utf-8")
        self.update = text.split("\n  persist:\n", 1)[0]
        self.steps = {}
        for block in re.split(r"\n      - ", self.update):
            if block.startswith("name: Save last good field output\n"):
                self.steps["field-cache-save"] = block
            identity = re.search(r"^        id: (field-[\w-]+)$", block, re.M)
            if identity:
                self.steps[identity[1]] = block

    def allowed(self, step, values):
        match = re.search(r"^        if: (.+)$", self.steps[step], re.M)
        if not match:
            return True
        expression = re.sub(r"steps\.[\w-]+\.(?:outcome|outputs\.[\w-]+)",
                            lambda value: repr(values.get(value[0], "")), match[1])
        expression = expression.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
        # Only trusted repository expressions, substituted with controlled scalar fixtures.
        return eval(expression, {"__builtins__": {}}, {})

    def run_guards(self, seen=False, restore="success", save="success", verified=True,
                   fallback="success", retain="success", slot="success", ownership="success", clear="success"):
        values = {"steps.field-slot.outcome": slot, "steps.field-fallback-cache.outcome": fallback,
                  "steps.field-retain.outcome": retain}
        values["steps.field-attempt-restore.outcome"] = restore if self.allowed("field-attempt-restore", values) else "skipped"
        values["steps.field-attempt-restore.outputs.cache-hit"] = "true" if seen else "false"
        values["steps.field-attempt-save.outcome"] = save if self.allowed("field-attempt-save", values) else "skipped"
        values["steps.field-attempt-clear.outcome"] = clear if self.allowed("field-attempt-clear", values) else "skipped"
        can_verify = self.allowed("field-attempt-verify", values)
        values["steps.field-attempt-verify.outcome"] = "success" if can_verify else "skipped"
        values["steps.field-attempt-verify.outputs.cache-hit"] = "true" if can_verify and verified else "false"
        values["steps.field-attempt-own.outcome"] = ownership if self.allowed("field-attempt-own", values) else "skipped"
        return self.allowed("field-prepare", values)

    def test_guards_fail_closed_and_previous_attempt_is_not_repeated(self):
        self.assertTrue(self.run_guards())
        for failure in (dict(seen=True), dict(restore="failure"), dict(save="failure"),
                        dict(verified=False), dict(fallback="failure"), dict(retain="failure"),
                        dict(slot="failure"), dict(ownership="failure"), dict(clear="failure")):
            with self.subTest(failure=failure):
                self.assertFalse(self.run_guards(**failure))

    def test_false_lookup_miss_and_conflicting_save_cannot_reuse_an_old_claim(self):
        with tempfile.TemporaryDirectory(prefix="field-conflict-") as temporary:
            path = Path(temporary) / "attempt.json"
            slot = reserve(path, NOW)
            old = path.read_bytes()
            reserve(path, NOW + timedelta(minutes=30))
            current_claim = json.loads(path.read_text())["claim"]
            # A warning/miss then a warning/successful save cannot overwrite immutable cache.
            path.write_bytes(old)
            with redirect_stdout(io.StringIO()):
                status = main(["verify", "--path", str(path), "--claim", current_claim, "--slot", slot])
            self.assertFalse(self.run_guards(seen=False, save="success", verified=True,
                                            ownership="success" if status == 0 else "failure"))

    def test_twelve_fresh_runners_with_failed_persistence_collect_once_per_slot(self):
        cached_slots, collections = set(), []
        start = NOW.replace(hour=0)
        with tempfile.TemporaryDirectory(prefix="field-runners-") as temporary:
            for half_hour in range(13):
                runner = Path(temporary) / str(half_hour)
                at = start + timedelta(minutes=30 * half_hour)
                slot = reserve(runner / "attempt.json", at)
                if self.run_guards(seen=slot in cached_slots):
                    cached_slots.add(slot)
                    collections.append(at)
                    # Data-branch persistence deliberately never succeeds in this model.
        self.assertEqual(collections, [start, start + timedelta(hours=6)])

    def test_last_good_cache_saved_after_attempt_failure_including_timeout(self):
        block = self.steps["field-cache-save"]
        self.assertIn("always()", block)
        self.assertIn("actions/cache/save@", block)
        self.assertIn("path: data/field-last-good.json", block)
        for outcome, expected in (("success", True), ("failure", True), ("skipped", False), ("", False)):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.allowed("field-cache-save", {"steps.field-prepare.outcome": outcome}), expected)

    def test_attempt_uses_exact_independent_key_and_is_durable_before_collection(self):
        keys = []
        for step in ("field-attempt-restore", "field-attempt-save", "field-attempt-verify"):
            block = self.steps[step]
            keys.append(re.search(r"^          key: (.+)$", block, re.M)[1])
            self.assertNotIn("restore-keys:", block)
            self.assertNotIn("run_id", keys[-1])
            self.assertNotIn("run_attempt", keys[-1])
            self.assertIn("steps.field-slot.outputs.slot", keys[-1])
        self.assertEqual(len(set(keys)), 1)
        self.assertIn("lookup-only: true", self.steps["field-attempt-restore"])
        self.assertNotIn("lookup-only: true", self.steps["field-attempt-verify"])
        ownership = self.steps["field-attempt-own"]
        self.assertIn("radar.field_checkpoint verify", ownership)
        self.assertIn("steps.field-slot.outputs.claim", ownership)
        self.assertIn("steps.field-slot.outputs.slot", ownership)
        self.assertIn("radar.field_checkpoint clear", self.steps["field-attempt-clear"])
        order = ["field-retain", "field-attempt-save", "field-attempt-clear", "field-attempt-verify", "field-attempt-own", "field-prepare"]
        self.assertEqual([self.update.index("id: " + step) for step in order],
                         sorted(self.update.index("id: " + step) for step in order))
        self.assertNotIn("persist-fields", self.steps["field-attempt-save"])


if __name__ == "__main__":
    unittest.main()

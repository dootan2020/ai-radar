"""Real local bare-Git round trips; never touch a remote account or site output."""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from radar.field_history import FILENAME, REF, load, persist, restore, validate
from radar.field_publish import prepare
from radar.pipeline import write_atomic
from test_field_rankings import FixtureAPI, NOW, repository


class FieldHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="field-history-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote.git"
        self.git("init", "--bare", "--quiet", str(self.remote))

    def git(self, *args):
        result = subprocess.run(["git", *args], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def build(self, name, now=NOW, repos=None):
        root = self.root / name
        candidate, output = root / "candidate", root / "fields.json"
        payload = prepare(str(self.remote), output, candidate, now, FixtureAPI(repos if repos is not None else [repository(pushed_at=now.isoformat())]))
        self.assertEqual(json.loads(output.read_text()), payload)
        return payload, candidate

    def test_cold_start_roundtrip_idempotence_and_isolated_ref(self):
        output, candidate = self.build("first")
        self.assertTrue(persist(str(self.remote), candidate))
        self.assertFalse(persist(str(self.remote), candidate))
        commit, state = restore(str(self.remote), self.root / "restore")
        self.assertTrue(commit)
        self.assertEqual(state["last_output"], output)
        self.assertEqual(self.git("--git-dir", str(self.remote), "for-each-ref", "--format=%(refname)"), REF)

    def test_next_day_net_counters_and_history_survive_new_runner(self):
        _, first = self.build("first", NOW - timedelta(days=7))
        persist(str(self.remote), first)
        payload, candidate = self.build("next", NOW, [repository(stargazers_count=350)])
        self.assertEqual(payload["fields"][0]["ranked"][0]["stars_net_7d"], 150)
        persist(str(self.remote), candidate)
        _, state = restore(str(self.remote), self.root / "verify")
        self.assertEqual(len(state["snapshots"]), 2)

    def test_stale_candidate_and_mutated_snapshot_cannot_replace_remote(self):
        _, initial = self.build("initial", NOW - timedelta(days=1))
        persist(str(self.remote), initial)
        _, older = self.build("older")
        _, newer = self.build("newer", NOW + timedelta(days=1))
        persist(str(self.remote), newer)
        with self.assertRaisesRegex(ValueError, "advanced"):
            persist(str(self.remote), older)
        _, candidate = self.build("mutated", NOW + timedelta(days=2))
        state = load(candidate / FILENAME)
        first_day = min(state["snapshots"])
        state["snapshots"][first_day]["1"]["stars"] += 1
        write_atomic(state, candidate / FILENAME)
        with self.assertRaisesRegex(ValueError, "immutable"):
            persist(str(self.remote), candidate)

    def test_tracking_date_cannot_reset(self):
        _, initial = self.build("initial", NOW - timedelta(days=1))
        persist(str(self.remote), initial)
        _, candidate = self.build("next")
        state = load(candidate / FILENAME)
        state["first_seen"]["1"] = NOW.isoformat()
        write_atomic(state, candidate / FILENAME)
        with self.assertRaisesRegex(ValueError, "tracking date"):
            persist(str(self.remote), candidate)

    def test_remote_failure_is_not_a_cold_start(self):
        with self.assertRaises(RuntimeError):
            prepare(str(self.root / "absent.git"), self.root / "out.json", self.root / "candidate", NOW, FixtureAPI())
        self.assertFalse((self.root / "out.json").exists())
        self.assertFalse((self.root / "candidate").exists())

    def test_unexpected_remote_path_is_rejected(self):
        _, candidate = self.build("first")
        persist(str(self.remote), candidate)
        repo = self.root / "edit"
        restore(str(self.remote), repo)
        (repo / "unexpected.json").write_bytes(b"{}")
        self.git("-C", str(repo), "add", "--", "unexpected.json")
        self.git("-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "fixture: unexpected path")
        self.git("-C", str(repo), "push", "--quiet", str(self.remote), f"HEAD:{REF}")
        with self.assertRaisesRegex(ValueError, "path or type"):
            restore(str(self.remote), self.root / "read-invalid")

    def test_malformed_state_never_loads(self):
        _, candidate = self.build("first")
        state = load(candidate / FILENAME)
        variants = []
        changed = deepcopy(state)
        changed["snapshots"][NOW.date().isoformat()]["1"]["stars"] = True
        variants.append(changed)
        changed = deepcopy(state)
        changed["last_output"]["fields"][0]["tracking"][0]["url"] = "https://example.invalid"
        variants.append(changed)
        changed = deepcopy(state)
        changed["snapshots"][NOW.date().isoformat()]["1"]["observed_at"] = (NOW + timedelta(days=1)).isoformat()
        variants.append(changed)
        for invalid in variants:
            with self.assertRaises(ValueError):
                validate(invalid)


class FieldWorkflowTests(unittest.TestCase):
    def test_optional_steps_and_isolated_main_only_persistence(self):
        text = (Path(__file__).parents[1] / ".github/workflows/update.yml").read_text()
        update = text.split("\n  update:\n", 1)[1].split("\n  finalize-paid-budget:", 1)[0]
        rest = text.split("\n  persist:\n", 1)[1]
        fields, deploy = rest.split("\n  persist-fields:\n")[1].split("\n  deploy:\n")
        self.assertIn("needs: update", fields)
        self.assertIn("github.ref == 'refs/heads/main'", fields)
        self.assertIn("continue-on-error: true", fields)
        self.assertIn("contents: write", fields)
        self.assertNotIn("persist-fields", deploy)
        self.assertNotIn("contents: write", update)
        preparation = update.split("name: Prepare repository field rankings")[1].split("      - ")[0]
        self.assertIn("continue-on-error: true", preparation)
        self.assertIn("timeout-minutes: 6", preparation)
        field_steps = update.split("# Field failures never participate", 1)[1].split("      - name: Upload collected source evidence", 1)[0]
        optional_minutes = sum(int(value) for value in re.findall(r"timeout-minutes: (\d+)", field_steps))
        update_timeout = int(re.search(r"timeout-minutes: (\d+)", update)[1])
        self.assertGreaterEqual(update_timeout, 30 + optional_minutes,
                                "Optional field steps must preserve the existing 30-minute news allowance")
        self.assertLess(update.index("name: Fetch public sources"), update.index("name: Prepare repository field rankings"))


if __name__ == "__main__":
    unittest.main()

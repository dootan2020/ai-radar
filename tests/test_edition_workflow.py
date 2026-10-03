"""Real local-Git runner lifecycle tests; no network or model inference."""

from datetime import timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from radar.edition_archive import load_archive
from radar.edition_history import REF, files, persist, restore
from radar.edition_publish import prepare
from test_edition_archive import accepted, next_day
from test_editions import NOW, real_snapshot

ROOT = Path(__file__).resolve().parents[1]


class EditionHistoryRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="edition-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "history.git"
        self.git("init", "--bare", "--quiet", str(self.remote))

    def git(self, *args):
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def inputs(self, runner, payload=None, now=NOW):
        runner.mkdir(parents=True, exist_ok=True)
        payload = real_snapshot() if payload is None else payload
        source, status = runner / "radar.json", runner / "status.json"
        source.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        status.write_bytes(json.dumps(accepted(payload, now)).encode("utf-8"))
        return source, status

    def prepare_in(self, runner, payload=None, now=NOW):
        source, status = self.inputs(runner, payload, now)
        output, candidate = runner / "public-editions", runner / "candidate"
        result = prepare(str(self.remote), source, status, output, candidate, now)
        return result, output, candidate

    def test_git_history_survives_runner_and_all_caches_disappearing(self):
        with tempfile.TemporaryDirectory(dir=self.root, prefix="runner-one-") as first:
            _, output, candidate = self.prepare_in(Path(first))
            original = files(output)
            self.assertTrue(persist(str(self.remote), candidate))
            head = self.git("--git-dir", str(self.remote), "rev-parse", REF)
            self.assertFalse(persist(str(self.remote), candidate))
            self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", REF), head)
        self.assertFalse(Path(first).exists())
        runner_two = self.root / "runner-two"
        _, output, candidate = self.prepare_in(runner_two)
        self.assertEqual(files(output), original)
        self.assertEqual(files(candidate / "editions"), original)
        self.assertFalse((runner_two / "measurement-baseline.json").exists())
        self.assertFalse((runner_two / "translations-vi.json").exists())
        self.assertFalse((runner_two / "published-snapshot.json").exists())
        restored = self.root / "fresh-checkout"
        self.assertEqual(restore(str(self.remote), restored), head)
        self.assertEqual(files(restored / "editions"), original)
        refs = self.git("--git-dir", str(self.remote), "for-each-ref", "--format=%(refname)")
        self.assertEqual(refs, REF)

    def test_next_runner_appends_date_without_changing_previous_edition(self):
        _, output, candidate = self.prepare_in(self.root / "first")
        first = (output / "2026-10-03.json").read_bytes()
        persist(str(self.remote), candidate)
        _, output, candidate = self.prepare_in(self.root / "next", next_day(real_snapshot()), NOW + timedelta(days=1))
        self.assertEqual((output / "2026-10-03.json").read_bytes(), first)
        self.assertTrue(persist(str(self.remote), candidate))
        restored = self.root / "verified"
        restore(str(self.remote), restored)
        self.assertEqual([row["date"] for row in load_archive(restored / "editions")],
                         ["2026-10-04", "2026-10-03"])
        self.assertEqual((restored / "editions/2026-10-03.json").read_bytes(), first)

    def test_rejected_mismatched_or_stale_gate_leaves_output_candidate_and_remote_unchanged(self):
        _, output, candidate = self.prepare_in(self.root / "runner")
        persist(str(self.remote), candidate)
        baseline = files(output), files(candidate / "editions"), (candidate / "manifest.json").read_bytes()
        head = self.git("--git-dir", str(self.remote), "rev-parse", REF)
        source, status_file = self.inputs(self.root / "runner")
        status = accepted(real_snapshot())
        variants = [(status | {"published": False}, NOW),
                    (status | {"freshness": status["freshness"] | {"generated_at": "2026-10-03T08:00:00Z"}}, NOW),
                    (status | {"attempted_at": "2026-10-02T09:18:01Z"}, NOW),
                    (status, NOW + timedelta(hours=3, seconds=1))]
        for diagnostic, now in variants:
            with self.subTest(diagnostic=diagnostic, now=now):
                status_file.write_bytes(json.dumps(diagnostic).encode())
                # An unusable remote must never be reached when the gate rejects.
                with self.assertRaisesRegex(ValueError, "gate"):
                    prepare(str(self.root / "unreachable.git"), source, status_file, output, candidate, now)
                self.assertEqual((files(output), files(candidate / "editions"),
                                  (candidate / "manifest.json").read_bytes()), baseline)
                self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", REF), head)

    def test_absent_branch_is_cold_start_but_unreadable_remote_is_failure(self):
        self.assertIsNone(restore(str(self.remote), self.root / "cold"))
        with self.assertRaises(RuntimeError):
            restore(str(self.root / "missing.git"), self.root / "bad")
        source, status = self.inputs(self.root / "input")
        output, candidate = self.root / "out", self.root / "candidate"
        with self.assertRaises(RuntimeError):
            prepare(str(self.root / "missing.git"), source, status, output, candidate, NOW)
        self.assertFalse(output.exists())
        self.assertFalse(candidate.exists())

    def test_stale_runner_cannot_erase_newer_remote_history(self):
        _, _, old = self.prepare_in(self.root / "old")
        persist(str(self.remote), old)
        _, _, new = self.prepare_in(self.root / "new", next_day(real_snapshot()), NOW + timedelta(days=1))
        persist(str(self.remote), new)
        head = self.git("--git-dir", str(self.remote), "rev-parse", REF)
        with self.assertRaisesRegex(ValueError, "advanced"):
            persist(str(self.remote), old)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", REF), head)

    def test_candidate_cannot_rewrite_existing_daily_bytes(self):
        _, _, first = self.prepare_in(self.root / "first")
        persist(str(self.remote), first)
        _, _, candidate = self.prepare_in(self.root / "second")
        target = candidate / "editions/2026-10-03.json"
        original = json.loads(target.read_text(encoding="utf-8"))
        original["stories"][0]["title"] = "Controlled attempted historical edit"
        target.write_bytes(json.dumps(original, ensure_ascii=False).encode("utf-8"))
        head = self.git("--git-dir", str(self.remote), "rev-parse", REF)
        with self.assertRaisesRegex(ValueError, "immutable"):
            persist(str(self.remote), candidate)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", REF), head)

    def test_actual_module_cli_roundtrip_ignores_inherited_autocrlf(self):
        runner = self.root / "cli"
        source, status = self.inputs(runner)
        output, candidate = runner / "output", runner / "candidate"
        config = self.root / "test-gitconfig"
        config.write_bytes(b"[core]\n\tautocrlf = true\n")
        env = os.environ.copy()
        env["GIT_CONFIG_GLOBAL"] = str(config)
        command = [sys.executable, "-m", "radar.edition_publish"]
        prepare_args = ["prepare", "--remote", str(self.remote), "--input", str(source),
                        "--status", str(status), "--output", str(output), "--candidate", str(candidate),
                        "--now", NOW.isoformat()]
        persist_args = ["persist", "--remote", str(self.remote), "--candidate", str(candidate)]
        for args in (prepare_args, persist_args, persist_args):
            completed = subprocess.run(command + args, cwd=ROOT, env=env,
                                       capture_output=True, text=True, timeout=45)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        restored = self.root / "cli-restored"
        restore(str(self.remote), restored)
        self.assertEqual(files(restored / "editions"), files(output))
        status.write_bytes(b'{"published":false}')
        completed = subprocess.run(command + prepare_args, cwd=ROOT, env=env,
                                   capture_output=True, text=True, timeout=45)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(files(restored / "editions"), files(output))


class EditionWorkflowPolicyTests(unittest.TestCase):
    def test_translation_precedes_prepare_and_durable_save_precedes_deploy(self):
        text = (ROOT / ".github/workflows/update.yml").read_text(encoding="utf-8")
        update, rest = text.split("\n  persist:\n", 1)
        persistent, deploy = rest.split("\n  deploy:\n", 1)
        self.assertLess(update.index("name: Translate headlines"), update.index("name: Prepare daily editions"))
        preparation = update.split("name: Prepare daily editions", 1)[1].split("      - ", 1)[0]
        self.assertIn("steps.collect.outputs.published == 'true'", preparation)
        self.assertIn("python -m radar.edition_publish prepare", preparation)
        self.assertIn("if: github.ref == 'refs/heads/main'", persistent)
        self.assertIn("contents: write", persistent)
        self.assertNotIn("contents: write", update)
        self.assertIn("needs: [update, persist]", deploy)
        self.assertIn("python -m radar.edition_publish persist", persistent)
        self.assertIn("cancel-in-progress: false", text)
        self.assertNotRegex(text, r"(?m)^  (push|pull_request):$")
        for step in re.split(r"\n      - ", text):
            if "actions/cache" in step:
                self.assertNotIn("editions", step)
        for name in ("Upload edition history candidate", "Download edition history candidate"):
            step = text.split("name: " + name, 1)[1].split("      - ", 1)[0]
            self.assertIn("name: radar-editions-${{ github.run_id }}", step)
            self.assertNotIn("github.run_attempt", step)


if __name__ == "__main__":
    unittest.main()

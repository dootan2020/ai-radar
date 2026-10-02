"""Offline checks for the workflow's baseline isolation and deployment boundary."""

from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/update.yml"


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_cross_branch_restore_is_ordered_and_versioned(self):
        block = self.text.split("restore-keys: |", 1)[1].split("      - ", 1)[0]
        prefixes = [line.strip() for line in block.splitlines() if line.strip()]
        self.assertEqual(prefixes, ["radar-measurements-v2-${{ github.ref_name }}-",
                                    "radar-measurements-v2-main-"])

    def test_only_promoted_baseline_is_cached(self):
        block = self.text.split("- name: Save measurement snapshot", 1)[1].split("      - ", 1)[0]
        self.assertIn("if: steps.collect.outputs.baseline_updated == 'true'", block)
        self.assertIn("path: data/measurement-baseline.json", block)
        self.assertNotIn("path: site/data/radar.json", block)
        restore = self.text.split("- name: Restore previous measurement snapshot", 1)[1].split("      - ", 1)[0]
        self.assertIn("path: data/measurement-baseline.json", restore)
        self.assertIn("id: collect", self.text)

    def test_reruns_have_unique_keys_and_branches_have_independent_concurrency(self):
        keys = re.findall(r"^\s+key: (.+)$", self.text, re.MULTILINE)
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])
        self.assertIn("${{ github.run_attempt }}", keys[0])
        self.assertIn("group: github-pages-${{ github.ref }}", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_main_deployment_guards_and_latest_verified_majors(self):
        self.assertIn("  deploy:\n    if: github.ref == 'refs/heads/main'", self.text)
        self.assertIn("actions/upload-pages-artifact@v5\n        if: github.ref == 'refs/heads/main'", self.text)
        for action in ("cache/restore@v6", "cache/save@v6", "upload-artifact@v7"):
            self.assertIn("actions/" + action, self.text)


if __name__ == "__main__":
    unittest.main()

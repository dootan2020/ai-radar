"""Health automation stays independent of collection and deployment."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HealthWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/health-monitor.yml").read_text(encoding="utf-8")

    def test_quarter_hour_schedule_and_manual_trigger_are_available(self):
        self.assertRegex(self.text, r"(?m)^  workflow_dispatch:")
        cron = re.search(r"cron:\s*['\"]([^'\"]+)['\"]", self.text).group(1)
        minute, *remaining = cron.split()
        self.assertEqual(remaining, ["*"] * 4)
        minutes = [int(value) for value in minute.split(",")]
        self.assertEqual(minutes, [13, 28, 43, 58])
        self.assertEqual([right - left for left, right in
                          zip(minutes, minutes[1:] + [minutes[0] + 60])], [15] * 4)

    def test_hosted_run_is_bounded_and_serialized(self):
        self.assertRegex(self.text, r"runs-on: ubuntu-[0-9.]+")
        self.assertRegex(self.text, r"timeout-minutes: (?:[1-9]|10)\b")
        self.assertIn("cancel-in-progress: false", self.text)
        group = re.search(r"(?m)^  group: (.+)$", self.text).group(1)
        self.assertNotIn("${{", group)
        self.assertNotIn("github-pages", group)

    def test_trusted_checkout_pinned_actions_and_scoped_builtin_token(self):
        self.assertIn("persist-credentials: false", self.text)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", self.text)
        actions = re.findall(r"(?m)^\s+- uses: (.+)$", self.text)
        self.assertEqual(len(actions), 2)
        for action in actions:
            self.assertRegex(action, r"^actions/(?:checkout|setup-python)@[a-f0-9]{40} # v\d+\.\d+\.\d+$")
        self.assertIn("contents: read", self.text)
        self.assertIn("issues: write", self.text)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", self.text)
        self.assertRegex(self.text, r"python -m radar\.health_monitor --report")
        self.assertEqual(self.text.count("secrets."), 1)

    def test_monitor_cannot_publish_collect_translate_or_execute_untrusted_events(self):
        for forbidden in ("pages: write", "id-token: write", "contents: write", "deploy-pages",
                          "build.py", "radar.translate", "pull_request", "workflow_run", "pip install"):
            self.assertNotIn(forbidden, self.text)
        self.assertNotIn("health_monitor", (ROOT / ".github/workflows/update.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

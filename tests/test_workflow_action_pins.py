"""Consistency checks for pinned GitHub Actions in workflow files."""

from collections import defaultdict
from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "update.yml"
PINNED_ACTION = re.compile(
    r"^\s*uses:\s*([\w.-]+/[\w.-]+)@([0-9a-f]{40})\s+#\s*(\S+)",
    re.IGNORECASE,
)


class WorkflowActionPinTests(unittest.TestCase):
    def test_same_action_and_version_comment_use_same_sha(self):
        pins = defaultdict(set)
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
            match = PINNED_ACTION.match(line)
            if match:
                action, sha, version = match.groups()
                pins[(action.lower(), version)].add(sha.lower())

        inconsistent = {
            f"{action} #{version}": sorted(shas)
            for (action, version), shas in pins.items()
            if len(shas) > 1
        }
        self.assertFalse(inconsistent, f"Action pins disagree: {inconsistent}")


if __name__ == "__main__":
    unittest.main()

"""Offline browser behavior, using Node's standard-library VM and a small DOM."""

from pathlib import Path
import shutil
import subprocess
import unittest


class AppStreamTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
    def test_stream_rendering_and_seen_state(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "--test", "tests/test_app_streams.js"], cwd=root,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

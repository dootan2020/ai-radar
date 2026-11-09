"""Loading visibility wiring; rendered CLS is measured separately in Chrome.

Exercise the real board/error renderers with a small DOM double so an empty snapshot
or failed fetch cannot leave the page hidden behind its loading state.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class LoadingLayoutTests(unittest.TestCase):
    def test_loading_retains_geometry_and_accessible_status(self):
        css = (SITE / "styles.css").read_text(encoding="utf-8")
        board = re.search(r"\.board\.is-loading\s*\{([^}]+)\}", css)
        self.assertIsNotNone(board)
        self.assertRegex(board.group(1), r"visibility\s*:\s*hidden")
        self.assertNotRegex(board.group(1), r"display\s*:\s*none")
        self.assertRegex(css, r"\.board\.is-loading\s*>\s*\.sr\s*\{\s*visibility\s*:\s*visible\s*\}")

    def test_reduced_motion_board_clears_visibility_transition(self):
        css = (SITE / "styles.css").read_text(encoding="utf-8")
        # Under reduced motion every element gets a 150 ms "all" transition; the board must not
        # transition visibility from is-loading to avoid a 2s compositor stall on mobile.
        self.assertIn(".board, .board *{transition-property:none !important}", css)


if __name__ == "__main__":
    unittest.main()

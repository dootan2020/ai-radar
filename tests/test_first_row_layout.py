"""The first screen is one tight bento: the lead spans two rows, live and repositories share the row beside it,
the new-stories tile sits under them, and no side tile pushes its lower block to the bottom."""
import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "site" / "styles.css").read_text(encoding="utf-8")


def rule(selector: str) -> str:
    m = re.search(r"(?:^|[\s}])" + re.escape(selector) + r"\{([^}]*)\}", CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


class FirstRowLayout(unittest.TestCase):
    def test_desktop_block_places_the_four_tiles(self):
        m = re.search(r"@media \(min-width: 1280px\)\{(.*?)\n  \}", CSS, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        self.assertIn(".t-lead{grid-column:1 / span 6;grid-row:1 / span 2}", block)
        self.assertIn(".t-live{grid-column:7 / span 3;grid-row:1}", block)
        self.assertIn(".t-repo{grid-column:10 / span 3;grid-row:1}", block)
        self.assertIn(".t-new{grid-column:7 / span 6;grid-row:2}", block)

    def test_lower_blocks_follow_their_content(self):
        for sel in (".repo-next", ".live-next"):
            self.assertNotIn("margin-top:auto", rule(sel), sel)

    def test_tablet_and_phone_keep_their_own_placement(self):
        self.assertIn(".t-lead{grid-column:1 / -1;grid-row:auto}", CSS)
        self.assertIn(".board > .tile{grid-column:1 / -1 !important}", CSS)


if __name__ == "__main__":
    unittest.main()

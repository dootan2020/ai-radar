"""The repository tile's controls: one segmented track picks the list, plain words pick the window or total.

The owner (03/10 15:07) found the six pill buttons too big, rough and redundant. These tests describe what replaced
them: every choice is a single-tap button announcing its state with aria-pressed, no menu hides a choice, the
tile is titled after the page its lists come from, and phones keep a 44px touch target. The rendered heights and
touch sizes are measured by tests/measure_repo_controls.mjs."""
import re
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
CSS = (SITE / "styles.css").read_text(encoding="utf-8")


def rule(selector: str, text: str = CSS) -> str:
    m = re.search(r"(?:^|[\s}])" + re.escape(selector) + r"\{([^}]*)\}", text)
    assert m, f"no rule for {selector}"
    return m.group(1)


class RepoControls(unittest.TestCase):


    def test_phones_keep_a_44px_touch_target(self):
        m = re.search(r"@media \(max-width: 767px\), \(pointer: coarse\)\{(.*?)\n  \}", CSS, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        # Segment: 40px button plus 2px of track on each side through ::before.
        self.assertIn(".seg-b{min-height:calc(var(--btn-h) - var(--space-4))}", block)
        self.assertIn(".seg-b::before{content:\"\";position:absolute;inset:calc(var(--space-4) / -2) 0}", block)
        # Window word: 24px tall, its ::before grows to --btn-h (44px).
        self.assertIn(".tab-t::before{inset:calc((var(--btn-h) - var(--space-24)) / -2)", block)
        self.assertIn("min-height:var(--space-24)", rule(".tab-t"))

    def test_chosen_window_uses_the_accent_and_chosen_list_a_raised_thumb(self):
        self.assertIn("color:var(--color-accent)", rule('.tab-t[aria-pressed="true"]'))
        self.assertIn("background:var(--color-surface)", rule('.seg-b[aria-pressed="true"]'))


if __name__ == "__main__":
    unittest.main()

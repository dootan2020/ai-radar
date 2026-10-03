"""The repository tile's controls: one segmented track picks the list, plain words pick the window or total.

The owner (03/10 15:07) found the six pill buttons too big, rough and redundant. These tests describe what replaced
them: every choice is a single-tap button announcing its state with aria-pressed, no menu hides a choice, the
tile is titled after the page its lists come from, and phones keep a 44px touch target. The rendered heights and
touch sizes are measured by tests/measure_repo_controls.mjs."""
import re
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
APP = (SITE / "app.js").read_text(encoding="utf-8")
CSS = (SITE / "styles.css").read_text(encoding="utf-8")


def function(name: str) -> str:
    start = APP.index(f"function {name}(")
    end = APP.index("\n}\n", start)
    return APP[start:end]


def rule(selector: str, text: str = CSS) -> str:
    m = re.search(r"(?:^|[\s}])" + re.escape(selector) + r"\{([^}]*)\}", text)
    assert m, f"no rule for {selector}"
    return m.group(1)


class RepoControls(unittest.TestCase):
    def test_list_is_one_segmented_group_and_window_is_a_second_group(self):
        sel = function("repoSelectors")
        self.assertEqual(sel.count('role="group"'), 2)
        self.assertIn('class="seg"', sel)
        self.assertIn('class="seg-b" data-repo-view=', sel)
        self.assertIn('class="tab-t" data-repo-${x.kind}=', sel)
        self.assertNotIn("chip", sel, "the list and window are no longer chip pills")

    def test_every_choice_is_a_one_tap_button_with_its_state(self):
        sel = function("repoSelectors")
        self.assertNotIn("<select", sel, "no choice hides behind a menu")
        self.assertEqual(sel.count("<button"), 2)
        self.assertEqual(sel.count("aria-pressed="), 2)

    def test_three_lists_and_their_windows_are_kept(self):
        self.assertEqual(re.findall(r"\{id:'(\w+)', label:'([^']+)'", APP[APP.index("const REPO_VIEWS"):APP.index("const WINDOWS")]),
                         [("trending", "Đang lên"), ("stars", "Nhiều sao"), ("usable", "Dùng ngay")])
        self.assertIn("{id:'day', label:'Hôm nay'", APP)
        self.assertIn("{id:'week', label:'Tuần này'", APP)
        self.assertIn("{id:'month', label:'Tháng này'", APP)
        self.assertIn("{id:'stars', label:'Theo sao'", APP)
        self.assertIn("{id:'forks', label:'Theo phân nhánh'", APP)
        self.assertIn("picks.slice(1, 4)", function("repoTile"), "one large and three small: four repositories")

    def test_tile_is_titled_after_github_trending(self):
        self.assertIn("tileHead('GitHub Trending<span class=\"sr\">, kho mã AI</span>', 'repo-h'", function("repoTile"))

    def test_choices_go_through_one_setter(self):
        self.assertIn("function setRepo(kind, value)", APP)
        self.assertNotIn("data-repo-select", APP)

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

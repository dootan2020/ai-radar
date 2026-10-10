"""Markup contracts for the quiet new-story pill and header-free home."""
from pathlib import Path
import re
import unittest

SITE = Path(__file__).resolve().parents[1] / "site"


class NewItemsNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SITE / "index.html").read_text(encoding="utf-8")
        cls.css = (SITE / "feed.css").read_text(encoding="utf-8")

    def test_one_quiet_notice_with_separate_live_region(self):
        self.assertIn('class="fresh" id="fresh" hidden', self.html)
        self.assertEqual(self.html.count('id="fresh-go"'), 1)
        self.assertIn('type="button" aria-keyshortcuts="U"', self.html)
        self.assertIn('id="fresh-announcement" role="status" aria-live="polite" aria-atomic="true"', self.html)
        for removed in ["feed-h1", "feed-sub", "moi", "new-go", "mark-seen-btn"]:
            self.assertNotIn(f'id="{removed}"', self.html)
        self.assertIn('<h1 class="sr">', self.html)
        self.assertIn('id="filter-context" aria-live="polite" hidden', self.html)

    def test_theme_tokens_focus_and_touch_target(self):
        body = re.search(r"\.fresh-btn\s*\{([^}]+)\}", self.css)[1]
        self.assertIn("min-height: 44px", body)
        self.assertIn("var(--color-surface)", body)
        self.assertIn("var(--color-accent)", body)
        self.assertIn(".fresh-btn:focus-visible", self.css)
        for removed in [".new-items", ".new-go", ".mark-seen-btn", ".skipped-mark", ".feed-head"]:
            self.assertNotIn(removed, self.css)
        self.assertIn(".new-mark", self.css)
        self.assertIn(".seen-mark", self.css)

    def test_sort_and_metadata_locations(self):
        header = self.html.split('<header class="feed-bar"')[1].split("</header>")[0]
        self.assertIn('id="sort-switch"', header)
        mobile = self.css.split("@media (max-width: 767px)", 1)[1]
        self.assertRegex(mobile, r"\.sort-switch\s*\{[^}]*order: 6;")
        source_panel = self.html.split('id="nguon"')[1].split("</section>")[0]
        self.assertIn('id="src-update"', source_panel)
        self.assertLess(self.html.index('id="stale"'), self.html.index('id="picks"'))


if __name__ == "__main__":
    unittest.main()

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
        cls.js = (SITE / "feed.js").read_text(encoding="utf-8")

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
        self.assertNotIn("order: 6", mobile)
        self.assertIn('id="src-update"', self.html)
        nguon_html = (SITE / "nguon.html").read_text(encoding="utf-8")
        self.assertIn('id="src-update"', nguon_html)
        self.assertIn('id="nguon"', nguon_html)

    def test_no_stale_banner_or_announcement(self):
        self.assertNotIn('id="stale"', self.html)
        self.assertNotIn(".stale", self.css)
        self.assertNotIn("renderStale", self.js)
        self.assertNotIn("$('#stale')", self.js)
        self.assertNotIn("freshness.js", self.html + self.js)

    def test_tabs_have_only_names_without_digit_space(self):
        labels = re.findall(r'<button class="filter-chip"[^>]*>([^<]+)</button>', self.html)
        self.assertEqual(labels, ["Tất cả", "Chuyện lớn", "Đang nóng", "Sản phẩm", "Thảo luận", "Mã và mô hình", "Xếp hạng", "Đã lưu"])
        self.assertNotIn(".filter-chip .count", self.css)
        self.assertNotIn("3ch", self.css)

    def test_header_preserves_tab_space_and_utilities(self):
        desktop = self.css.split("@media (min-width: 768px){")[1].split("@media")[0]
        strip = re.search(r"\.feed-filters\s*\{([^}]+)\}", desktop)[1]
        self.assertIn("overflow-x: auto", strip)
        self.assertIn("gap: var(--space-8)", strip)
        self.assertIn("padding: 0 var(--space-8)", desktop)
        tablet = self.css.split("@media (min-width: 768px) and (max-width: 1399px)")[1].split("@media")[0]
        self.assertIn(".feed-navigation { order: 1; flex-basis: 100%; }", tablet)
        self.assertNotIn(".filter-chip", tablet)
        compact = self.css.split("@media (min-width: 1400px) and (max-width: 1599px)")[1].split("@media")[0]
        self.assertIn(".tc-link .tc-label { display: none; }", compact)
        self.assertIn('aria-label="Tra cứu câu chuyện AI"', self.html)

    def test_one_row_header_stacks_when_its_contents_do_not_fit(self):
        # The one-row bar must not rely on width alone: tabs, fonts and the reader's font size change what fits.
        fit = self.js.split("function fitBar()")[1].split("\n}")[0]
        self.assertIn("matchMedia('(min-width: 1400px)')", self.js)
        self.assertIn("classList.toggle('is-stacked'", fit)
        self.assertIn("filters.scrollWidth > filters.clientWidth", fit)
        self.assertIn("sort.hidden = false", fit)   # measured with the sort switch, so changing tabs keeps the shape
        for caller in ["function renderChips()", "function renderSortSwitch()", "window.addEventListener('resize'"]:
            self.assertIn("fitBar();", self.js.split(caller)[1][:600], caller)
        self.assertIn("document.fonts.addEventListener('loadingdone', fitBar)", self.js)
        self.assertIn(".feed-bar.is-stacked .feed-navigation { order: 1; flex-basis: 100%;", self.css)
        self.assertIn(".feed-bar.is-stacked .feed-filters { flex-wrap: wrap; overflow-x: visible; }", self.css)
        mouse = self.css.split("@media (min-width: 768px) and (max-width: 1399px) and (hover: hover) and (pointer: fine)")[1].split("}")[0]
        self.assertIn("flex-wrap: wrap", mouse)
        touch = self.css.split("@media (min-width: 768px) and (max-width: 1399px) and (pointer: coarse)")[1].split("}")[0]
        self.assertIn("mask-image: var(--nav-fade)", touch)


if __name__ == "__main__":
    unittest.main()

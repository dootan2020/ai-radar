from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FeedHeaderLayoutTests(unittest.TestCase):
    def test_feed_header_is_a_single_non_wrapping_row(self):
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        self.assertIn(".feed-bar-in{", css)
        self.assertIn("display:flex;flex-wrap:nowrap;align-items:center", css)
        self.assertIn(".feed-bar.is-stacked .feed-bar-in{height:var(--bar-h);flex-wrap:nowrap", css)
        self.assertIn(".feed-bar.is-stacked .feed-filters{flex-wrap:nowrap;overflow-x:auto}", css)

    def test_tabs_scroll_without_wrapping_or_masking_the_active_pill(self):
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        self.assertIn(".feed-filters{", css)
        self.assertIn("overflow-x:auto;overflow-y:hidden;overscroll-behavior-inline:contain", css)
        self.assertIn("-webkit-mask-image:none;mask-image:none", css)
        self.assertIn(".feed-filters::-webkit-scrollbar{display:none}", css)
        self.assertIn("@media(prefers-reduced-motion:reduce){.feed-filters{scroll-behavior:auto}}", css)

    def test_phone_header_keeps_actions_visible_and_separates_feed_filters(self):
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("@media(max-width:1279px)", css)
        self.assertIn("@media(max-width:767px)", css)
        self.assertIn(".feed-bar-in{height:112px;min-height:112px;display:grid", css)
        self.assertIn(".feed-bar-in .feed-navigation{grid-column:1/-1;grid-row:2", css)
        self.assertIn(".feed-bar-in>.theme-btn{grid-column:2;grid-row:1;display:grid", css)
        self.assertIn(".feed-bar-in>.tool-launcher{grid-column:3;grid-row:1", css)
        self.assertIn('aria-label="Bản tin sáng"', html)
        self.assertIn('aria-label="Đáng đọc nhất"', html)
        self.assertIn('aria-label="Mới nhất"', html)
        self.assertIn('data-sort="toggle"', html)
        self.assertIn('class="sort-current">Đáng đọc</span>', html)
        self.assertIn("b.dataset.sort === 'toggle'", (ROOT / "site" / "feed.js").read_text(encoding="utf-8"))
        self.assertIn("sortMode === 'worth' ? 'Đáng đọc' : 'Mới nhất'", (ROOT / "site" / "feed.js").read_text(encoding="utf-8"))
        self.assertIn("button.className = 'tool-launcher-button'", (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8"))

    def test_phone_has_labeled_primary_destinations_and_current_page(self):
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        script = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:repeat(4,minmax(0,1fr))", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn('.mobile-nav-link[aria-current="page"]', css)
        self.assertIn("min-height:44px", css)
        self.assertIn(".sort-btn:not(.sort-btn-compact){display:none}", css)
        for label in ("Dòng tin", "Bản tin", "Tra cứu", "Nguồn"):
            self.assertIn(f"'{label}'", script)
        self.assertIn("mobileNav.setAttribute('aria-label', 'Điều hướng chính')", script)
        self.assertIn("link.setAttribute('aria-current', 'page')", script)
        self.assertIn("header.after(mobileNav)", script)
        self.assertNotIn("themePlaceholder", script)

    def test_active_filter_is_scrolled_into_view(self):
        script = (ROOT / "site" / "feed.js").read_text(encoding="utf-8")
        self.assertIn("function scrollChipIntoView(container, chip)", script)
        self.assertIn("scrollChipIntoView(filters, activeChip)", script)
        self.assertNotIn("is-stacked", script)

    def test_other_site_header_variants_stay_on_one_row(self):
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        self.assertIn(".bar{\n  height:var(--bar-h);flex-wrap:nowrap", css)
        self.assertIn(".bt-bar{flex-wrap:nowrap", css)
        for page in ("index.html", "nguon.html", "bento.html", "tra-cuu.html", "ban-tin.html", "tin/_sample/index.html"):
            html = (ROOT / "site" / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertIn('menu-cong-cu.css"', html)
                self.assertIn('menu-cong-cu.js"', html)
                self.assertEqual(html.count('<div class="tool-launcher"></div>'), 1)

    def test_story_page_does_not_insert_a_second_launcher(self):
        story = (ROOT / "site" / "story-page.js").read_text(encoding="utf-8")
        launcher = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelector(\'script[src$="menu-cong-cu.js"]\')', story)
        self.assertIn("if (header.querySelector('.tool-launcher-button')) return", launcher)


if __name__ == "__main__":
    unittest.main()

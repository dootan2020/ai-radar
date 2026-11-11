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
        self.assertIn("button.className = 'tool-launcher-button'", (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8"))

    def test_phone_head_shows_both_orders(self):
        # Captain, 11/11: "Trên Mobile chưa có nút mới nhất, nó ẩn sau nút đáng đọc." Both sides of the order are real
        # buttons at every width; no one-button toggle hides the other side (tests/capture-mobile-sap-xep.mjs measures
        # them at 320, 375 and 414 px on a touch phone).
        import re
        for page in (ROOT / "site" / "index.html", ROOT / "extension" / "newtab.html"):
            html = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                switch = html.split('id="sort-switch"', 1)[1].split("</div>", 1)[0]
                self.assertEqual(re.findall(r'data-sort="(\w+)"', switch), ["worth", "new"])
                self.assertIn('Đáng đọc<span class="sort-label-tail">&nbsp;nhất</span></button>', switch)
                self.assertIn('>Mới nhất</button>', switch)
                self.assertNotIn("toggle", switch)
        feed = (ROOT / "site" / "feed.js").read_text(encoding="utf-8")
        self.assertNotIn("sort-btn-compact", feed)
        self.assertNotIn("'toggle'", feed)
        for name in ("menu-cong-cu.css", "trang-msn.css", "feed.css", "trang-nhat.css"):
            css = (ROOT / "site" / name).read_text(encoding="utf-8")
            with self.subTest(css=name):
                self.assertNotIn("sort-btn-compact", css)
                self.assertIsNone(re.search(r"\.sort-btn[^{}]*\{[^}]*display:\s*none", css))
                self.assertIsNone(re.search(r"\.sort-switch \.tab-pill\s*\{[^}]*display:\s*none", css))
        # The phone keeps the wide row's segmented look, shortens the first label and gives the theme to "Tùy chỉnh".
        msn = (ROOT / "site" / "trang-msn.css").read_text(encoding="utf-8")
        phone = msn.split("@media (max-width: 767px) {\n  /* A phone: the weather", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(".msn-head .theme-btn, .msn-head .sort-label-tail { display: none; }", phone)
        self.assertIn(".msn-head .sort-switch { display: grid; grid-template-columns: 1fr 1fr; width: 12em;", phone)

    def test_phone_has_labeled_primary_destinations_and_current_page(self):
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        script = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:repeat(4,minmax(0,1fr))", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn('.mobile-nav-link[aria-current="page"]', css)
        self.assertIn("min-height:44px", css)
        for label in ("Dòng tin", "Bản tin", "Tìm tin", "Sự kiện"):
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
        for page in ("index.html", "nguon.html", "ban-tin.html", "tin/_sample/index.html"):
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

"""Markup contracts for new stories and the header-free home. The "N tin mới" pill is gone: new stories load by
themselves (captain, 13/11 20:1x, tests/test_tu_tai_tin.py); one polite live region reads each batch out."""
from pathlib import Path
import re
import unittest

SITE = Path(__file__).resolve().parents[1] / "site"


class NewItemsNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SITE / "index.html").read_text(encoding="utf-8")
        cls.css = (SITE / "feed.css").read_text(encoding="utf-8")
        cls.header_css = (SITE / "menu-cong-cu.css").read_text(encoding="utf-8")
        cls.js = (SITE / "feed.js").read_text(encoding="utf-8")

    def test_no_pill_one_live_region(self):
        for removed in ('id="fresh"', 'id="fresh-go"', 'id="fresh-text"', 'class="fresh-btn"', 'id="i-up"'):
            self.assertNotIn(removed, self.html)
        self.assertEqual(self.html.count('id="fresh-announcement" role="status" aria-live="polite" aria-atomic="true"'), 1)
        # U still leads to "Vừa đăng" (feed.js, goFirstNew); the shortcuts list says so.
        self.assertIn("<dt><kbd>U</kbd></dt><dd>Tới thẻ Vừa đăng</dd>", self.html)
        for removed in ["feed-h1", "feed-sub", "moi", "new-go", "mark-seen-btn"]:
            self.assertNotIn(f'id="{removed}"', self.html)
        self.assertIn('<h1 class="sr">', self.html)
        self.assertIn('id="filter-context" aria-live="polite" hidden', self.html)

    def test_marks_stay_and_the_pill_styles_are_gone(self):
        self.assertNotRegex(self.css, r"\.fresh\s*\{")
        self.assertNotIn(".fresh-btn", self.css)
        for removed in [".new-items", ".new-go", ".mark-seen-btn", ".skipped-mark", ".feed-head"]:
            self.assertNotIn(removed, self.css)
        self.assertIn(".new-mark", self.css)
        self.assertIn(".seen-mark", self.css)

    def test_sort_and_metadata_locations(self):
        # The line above the grid is gone (captain, 09/11): the sort switch sits in the panel's head row, and the view's
        # name is a heading for screen readers only, with no update time.
        # The order sits on the heading of the list it orders, "Tin mới" (captain, 11/11 12:3x: "dời đi"): parked in
        # #sort-home and moved into the band's slot when the front page is drawn.
        actions = self.html.split('<div class="head-actions">')[1].split('</nav>')[0]
        self.assertNotIn('id="sort-switch"', actions)
        self.assertIn('id="sort-switch"', self.html.split('id="sort-home"', 1)[1])
        self.assertIn("""bandHTML('news', 'Tin mới', '<div class="band-cells" id="news-grid"></div>', '<i data-slot="sort"></i>')""", self.js)
        meta = self.html.split('<div class="front-meta">')[1].split('id="filter-context"')[0]
        self.assertIn('<h2 class="sr" id="front-h">', meta)
        self.assertNotIn('front-updated', self.html)
        self.assertNotIn("Cập nhật lúc", self.js)
        mobile = self.css.split("@media (max-width: 767px)", 1)[1]
        self.assertNotIn("order: 6", mobile)
        self.assertNotIn('<footer', self.html)
        self.assertNotIn('id="keys-open"', self.html)
        nguon_html = (SITE / "nguon.html").read_text(encoding="utf-8")
        self.assertIn('id="src-update"', nguon_html)
        self.assertIn('id="nguon"', nguon_html)

    def test_no_stale_banner_or_announcement(self):
        self.assertNotIn('id="stale"', self.html)
        self.assertNotIn(".stale", self.css)
        self.assertNotIn("renderStale", self.js)
        self.assertNotIn("$('#stale')", self.js)
        self.assertNotIn("freshness.js", self.html + self.js)

    def test_sections_name_their_view_without_counts(self):
        # Mockup B (captain, 07/11) named each section; on 08/11 the captain asked for clean filters with no story
        # count ("Làm sạch bộ lọc, không hiển thị lượng tin"), and no line counting the window's stories. On 09/11 13:16
        # scrolling into older days replaced the section tabs (Chuyện lớn, Đang nóng, Sản phẩm, Nghiên cứu, Thảo luận).
        labels = re.findall(r'<span class="chip-label">([^<]+)</span>', self.html)
        self.assertEqual(labels, ["Trang nhất", "Mã và mô hình", "Xếp hạng", "Đã lưu"])
        self.assertNotIn('class="count', self.html)
        self.assertNotIn("querySelector('.count')", self.js)
        self.assertNotIn('<span class="count num">', self.js)
        self.assertNotIn('id="front-fresh"', self.html)
        self.assertNotIn("tin trong ${winH} giờ qua", self.js)
        self.assertNotIn("3ch", self.css)

    def test_header_preserves_tab_space_and_utilities(self):
        self.assertIn(".feed-bar-in{", self.header_css)
        self.assertIn("flex-wrap:nowrap", self.header_css)
        self.assertIn(".feed-navigation{", self.header_css)
        self.assertIn(".feed-filters{", self.header_css)
        self.assertIn("overflow-x:auto", self.header_css)
        self.assertIn(".tc-link .tc-label{display:none}", self.header_css)
        self.assertIn('aria-label="Tìm trong tin Halcyon"', self.html)

    def test_header_never_stacks_when_its_contents_do_not_fit(self):
        self.assertNotIn("function fitBar()", self.js)
        self.assertNotIn("is-stacked", self.js)
        self.assertIn("flex-wrap:nowrap", self.header_css)
        self.assertIn(".feed-bar.is-stacked .feed-navigation{order:0;flex:1 1 auto;flex-basis:auto", self.header_css)
        self.assertIn(".feed-bar.is-stacked .feed-filters{flex-wrap:nowrap;overflow-x:auto}", self.header_css)


if __name__ == "__main__":
    unittest.main()

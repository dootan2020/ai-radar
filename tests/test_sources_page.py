"""Unit tests for the sources page (nguon.html, nguon.js), the home footer's link to it, and feed.css."""

from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"


class SourcesPageTestCase(unittest.TestCase):
    """Captain, 08/11 ("Làm sạch trang"): the sources page is a reader's directory of outlets, not a status board."""

    def setUp(self):
        self.nguon_html = (SITE / "nguon.html").read_text(encoding="utf-8")
        self.nguon_js = (SITE / "nguon.js").read_text(encoding="utf-8")
        self.feed_js = (SITE / "feed.js").read_text(encoding="utf-8")
        self.feed_css = (SITE / "feed.css").read_text(encoding="utf-8")

    def test_nguon_html_structure(self):
        self.assertIn('id="nguon"', self.nguon_html)
        self.assertIn('<h1 class="tile-title" id="nguon-h">Nguồn tin</h1>', self.nguon_html)
        self.assertIn('id="src-update"', self.nguon_html)
        self.assertIn('id="src-list"', self.nguon_html)
        self.assertIn('id="src-foot"', self.nguon_html)
        for removed in ('id="src-note"', 'id="src-live"', 'id="src-idle"', 'id="src-bad"', "mỗi 90 giây",
                        "Tạm dừng hoặc gặp lỗi", "tình trạng cập nhật", "số tin lấy được"):
            self.assertNotIn(removed, self.nguon_html)

    def test_directory_lists_every_source_by_name_without_counts_or_states(self):
        self.assertIn("localeCompare(nameOf(b), 'vi')", self.nguon_js)
        for removed in ("s.count", "cleanErrorVi", "tin khớp", "nguồn chạy được", "Xếp hạng nóng", "startLive",
                        "Điểm đáng đọc", "Dữ liệu tạo lúc", "Lượt xem"):
            self.assertNotIn(removed, self.nguon_js)

    def test_home_footer_links_the_sources_without_a_count(self):
        self.assertIn("function renderSources()", self.feed_js)
        part = self.feed_js.split("function renderSources()")[1].split("function ")[0]
        self.assertIn('href="nguon.html"', part)
        self.assertNotIn("asArray(D.sources).length", part)
        self.assertNotIn("Cập nhật lúc", part)

    def test_css_rows_are_touch_targets(self):
        match = re.search(r"\.src-list li\s*\{([^}]+)\}", self.feed_css)
        self.assertIsNotNone(match, ".src-list li rule not found in feed.css")
        body = match.group(1)
        self.assertIn("display: grid", body)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr)", body)
        self.assertIn("min-height: var(--btn-h)", body)


if __name__ == "__main__":
    unittest.main()

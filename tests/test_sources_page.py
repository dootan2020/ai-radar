"""Unit tests for sources page (nguon.html, nguon.js, feed.js footer, feed.css)."""

from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"


class SourcesPageTestCase(unittest.TestCase):
    def setUp(self):
        self.nguon_html = (SITE / "nguon.html").read_text(encoding="utf-8")
        self.nguon_js = (SITE / "nguon.js").read_text(encoding="utf-8")
        self.feed_js = (SITE / "feed.js").read_text(encoding="utf-8")
        self.feed_css = (SITE / "feed.css").read_text(encoding="utf-8")

    def test_nguon_html_structure(self):
        """nguon.html must have semantic sections, ids, and accessible markup."""
        self.assertIn('id="nguon"', self.nguon_html)
        self.assertIn('id="src-update"', self.nguon_html)
        self.assertIn('id="src-note"', self.nguon_html)
        self.assertIn('id="src-live"', self.nguon_html)
        self.assertIn('id="src-list"', self.nguon_html)
        self.assertIn('id="src-idle"', self.nguon_html)
        self.assertIn('id="src-bad"', self.nguon_html)
        self.assertIn('id="src-foot"', self.nguon_html)

    def test_machine_codes_mapped_to_plain_vietnamese(self):
        """Machine codes like x_run_cap and X collection not attempted must be translated."""
        self.assertIn("cleanErrorVi", self.nguon_js)
        self.assertIn("x_run_cap", self.nguon_js)
        self.assertIn("Đã đạt hạn mức thu thập trong lượt chạy", self.nguon_js)
        self.assertIn("X collection not attempted", self.nguon_js)
        self.assertIn("Chưa thu thập trong đợt chạy này", self.nguon_js)

    def test_sources_grouped_and_sorted_correctly(self):
        """Active sources with stories must come first, followed by idle, and bad sources last."""
        self.assertIn("srcs.filter(s => s.ok && (s.count || 0) > 0)", self.nguon_js)
        self.assertIn("srcs.filter(s => s.ok && !(s.count || 0))", self.nguon_js)
        self.assertIn("srcs.filter(s => !s.ok)", self.nguon_js)
        # Verify that broken sources do NOT come first (old sort a.ok - b.ok removed)
        self.assertNotIn("a.ok - b.ok", self.nguon_js)

    def test_feed_footer_count_matches_sources_page(self):
        """Home footer must count total sources consistently with the sources page."""
        self.assertIn("function renderSources()", self.feed_js)
        # Check that total sources is used in feed.js renderSources
        part = self.feed_js.split("function renderSources()")[1].split("function ")[0]
        self.assertIn("asArray(D.sources).length", part)
        self.assertIn('href="nguon.html"', part)

    def test_css_grid_prevents_count_dropping_to_next_line(self):
        """.src-list li must use a 3-column grid layout so .src-n never drops under the name."""
        match = re.search(r"\.src-list li\s*\{([^}]+)\}", self.feed_css)
        self.assertIsNotNone(match, ".src-list li rule not found in feed.css")
        body = match.group(1)
        self.assertIn("display: grid", body)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr) auto", body)
        self.assertNotIn("flex-wrap: wrap", body)


if __name__ == "__main__":
    unittest.main()

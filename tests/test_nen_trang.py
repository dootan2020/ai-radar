"""The Halcyon page keeps real margins on wide screens, and the page surface behind the top row stays plain."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"


def read(path):
    return path.read_text(encoding="utf-8")


class PageBackground(unittest.TestCase):
    def test_panel_and_top_row_stop_at_the_same_width(self):
        tokens, css = read(SITE / "tokens.css"), read(SITE / "trang-msn.css")
        self.assertIn("--msn-panel-max: 1680px;", tokens)
        panel = re.search(r"\.feed-main\.front\.msn-panel \{([^}]*)\}", css).group(1)
        self.assertIn("max-width: var(--msn-panel-max)", panel)
        self.assertIn("calc((100% - var(--msn-panel-max)) / 2)", panel)
        top = re.search(r"\.msn-top-in \{([^}]*)\}", css).group(1)
        self.assertIn("max-width: var(--msn-panel-max)", top)
        self.assertIn("margin-inline: auto", top)

    def test_no_ripple_is_drawn_behind_the_top_row(self):
        css, tokens = read(SITE / "trang-msn.css"), read(SITE / "tokens.css")
        self.assertNotIn("msn-ripple", css + tokens)
        self.assertNotIn("nen-song", css)
        self.assertNotIn("::before", css.split(".msn-top .news-search")[0])
        self.assertFalse((SITE / "nen-song.svg").exists())
        self.assertFalse((EXT / "nen-song.svg").exists())

    def test_the_new_tab_ships_the_same_css(self):
        for name in ("tokens.css", "trang-msn.css"):
            self.assertEqual(read(SITE / name).replace("\r\n", "\n"), read(EXT / name).replace("\r\n", "\n"), name)
        self.assertNotIn("nen-song", read(EXT / "sync-site.py"))

    def test_the_site_csp_allows_the_packaged_file_not_data_uris(self):
        html = read(SITE / "index.html")
        img = re.search(r"img-src ([^;]*);", html).group(1)
        self.assertIn("'self'", img)
        self.assertNotIn("data:", img)


if __name__ == "__main__":
    unittest.main()

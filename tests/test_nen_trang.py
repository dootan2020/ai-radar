"""The Halcyon page keeps real margins on wide screens, and a quiet dive ripple sits behind the top row."""
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

    def test_ripple_is_one_small_flat_shape(self):
        svg = (SITE / "nen-song.svg").read_text(encoding="utf-8")
        self.assertLess(len(svg.encode("utf-8")), 1024)
        self.assertNotRegex(svg, r"(?i)gradient|stroke|<image|<script|data:")
        self.assertIn('fill="#F0446E"', svg)
        css = read(SITE / "trang-msn.css")
        self.assertIn('url("nen-song.svg")', css)
        self.assertIn("z-index: -1", re.search(r"\.msn-top-in::before \{([^}]*)\}", css).group(1))

    def test_ripple_is_quieter_on_light_than_on_dark(self):
        tokens = read(SITE / "tokens.css")
        values = [float(v) for v in re.findall(r"--msn-ripple-a: ([0-9.]+);", tokens)]
        self.assertEqual(len(values), 3)  # light, data-theme dark, system dark
        self.assertEqual(values[1], values[2])
        self.assertLess(values[0], values[1])
        self.assertLessEqual(values[1], 0.2)

    def test_the_new_tab_ships_the_same_ripple_and_css(self):
        for name in ("nen-song.svg", "tokens.css", "trang-msn.css"):
            self.assertEqual(read(SITE / name).replace("\r\n", "\n"), read(EXT / name).replace("\r\n", "\n"), name)
        self.assertIn("'nen-song.svg'", read(EXT / "sync-site.py"))

    def test_the_site_csp_allows_the_packaged_file_not_data_uris(self):
        html = read(SITE / "index.html")
        img = re.search(r"img-src ([^;]*);", html).group(1)
        self.assertIn("'self'", img)
        self.assertNotIn("data:", img)


if __name__ == "__main__":
    unittest.main()
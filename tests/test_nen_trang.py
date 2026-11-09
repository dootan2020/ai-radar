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
        before = re.search(r"@media \(min-width: 60rem\) \{\s*\.msn-top-in::before \{([^}]*)\}", css)
        self.assertIsNotNone(before, "the ripple is drawn only from 60rem, where the top-left is empty")
        self.assertIn("z-index: -1", before.group(1))

    def test_ripple_sits_in_empty_page_space_left_of_the_row(self):
        tokens = read(SITE / "tokens.css")
        dive_x = int(re.search(r"--msn-ripple-x: (-\d+)px", tokens).group(1))
        self.assertLess(dive_x, 0)  # the dive point is left of the row's edge, so the viewport crops the rings
        svg = read(SITE / "nen-song.svg")
        radii = [int(r) for r in re.findall(r"a(\d+) \1 0 1 0 \d+ 0", svg)][::2]
        self.assertLessEqual(len(radii), 7)  # a disc and three bands
        cx = int(re.search(r"--msn-ripple-cx: (\d+)px", tokens).group(1))
        self.assertLess(dive_x + max(radii), 40)  # rings stop well short of the search column (measured: it starts 59px in at 960)
        self.assertEqual(cx, 80)

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

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
        self.assertNotRegex(svg, r"(?i)gradient|stroke|<image|<script|data:|<circle")
        self.assertIn('fill="#F0446E"', svg)
        css = read(SITE / "trang-msn.css")
        self.assertIn('url("nen-song.svg")', css)
        before = re.search(r"@media \(min-width: 75rem\) \{\s*\.msn-top::before \{([^}]*)\}", css)
        self.assertIsNotNone(before, "the ripple is drawn only from 75rem, where the top-left is empty")
        self.assertIn("z-index: -1", before.group(1))
        self.assertEqual(len(re.findall(r"::before", css.split(".msn-top .news-search")[0])), 1)  # no phone variant: dropped, not shrunk

    def test_ripple_is_flat_water_ellipses_in_the_corner(self):
        svg = read(SITE / "nen-song.svg")
        arcs = [(int(rx), float(ry)) for rx, ry in re.findall(r"a(\d+) ([\d.]+) 0 1 0 \d+ 0", svg)]
        self.assertEqual(len(arcs), 6)  # three bands, an outer and an inner edge each: no centre disc
        for rx, ry in arcs:
            self.assertAlmostEqual(rx / ry, 3, delta=0.05)  # flattened 3:1, like ripples seen at an angle
        view = [int(v) for v in re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups()]
        cx = re.search(r"M(\d+) 40a", svg)
        self.assertIsNotNone(cx)
        centre = int(cx.group(1)) + arcs[0][0]
        self.assertLessEqual(max(a[0] for a in arcs) + centre, 180)  # stays clear of the search column (it starts 200px in at 1200)
        self.assertLessEqual(40 + max(a[1] for a in arcs), view[1])
        tokens = read(SITE / "tokens.css")
        self.assertIn("--msn-ripple-w: 200px; --msn-ripple-h: 80px;", tokens)

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

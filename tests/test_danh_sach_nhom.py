"""Captain, 10/11 15:19: "yêu cầu tất cả kiểu hover của list nó phải giống nhau" and "gom các thành phần giống nhau vào 1
chỗ ví dụ: Mô hình dẫn đầu, kho mã đáng lấy, mô hình đáng thử vào 1 chỗ". Every list row on the front page takes one shared
class whose hover and keyboard focus are defined once; the models and code tiles render together in one band."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"
CSS = ("feed.css", "trang-msn.css", "trang-nhat.css")
ROWS = (".hot-row", ".repo", ".model", ".fresh-item", ".brief", ".msn-toplist li", ".ev-link", ".arena-go", ".arena-row")


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def function(src, name):
    start = src.index(f"function {name}(")
    return src[start:src.index("\n}\n", start)]


class OneRowHover(unittest.TestCase):
    def test_every_list_row_carries_the_shared_class(self):
        feed = read(SITE / "feed.js")
        for row in ('<a class="hot-row list-row ', '<a class="repo list-row"', '<a class="model list-row"',
                    '<a class="brief fresh-item list-row"', '<a class="ev-link list-row"', '<button class="arena-go list-row"',
                    '<li class="list-row ${statusClass(st)}"'):
            self.assertEqual(feed.count(row), 1, row)
        # "Chuyện lớn" is the list whose rows are <li>: the template right after its heading.
        top = feed[feed.index('id="top-list"'):]
        self.assertIn('<li class="list-row ', top[:top.index("</ol></section>")])

    def test_the_hover_is_defined_once_and_only_for_a_pointer_that_hovers(self):
        css = read(SITE / "trang-msn.css")
        self.assertEqual(css.count(".list-row:hover"), 1)
        self.assertIn("@media (hover: hover) and (pointer: fine) { .list-row:hover::before { background: var(--row-wash); } }", css)
        # The keyboard gets the same wash plus the focus ring, on the row or on the link inside it.
        self.assertIn(".list-row:focus-visible::before, .list-row:has(:focus-visible)::before { background: var(--row-wash); outline: var(--focus-ring);", css)
        self.assertIn("--row-wash: var(--color-fill);", read(SITE / "tokens.css"))

    def test_no_list_keeps_a_hover_of_its_own(self):
        for name in CSS:
            css = read(SITE / name)
            for selector in re.findall(r"([^{}]*:hover[^{}]*)\{", css):
                for row in ROWS:
                    self.assertNotRegex(selector, re.escape(row) + r"(?![\w-])[^,]*:hover", f"{name}: {selector.strip()}")

    def test_the_extension_ships_the_same_rows(self):
        for name in ("trang-msn.css", "tokens.css"):
            self.assertEqual(read(SITE / name), read(EXT / name), name)
        self.assertEqual(read(EXT / "feed.js").count("list-row"), read(SITE / "feed.js").count("list-row"))


class ModelsAndCodeBand(unittest.TestCase):
    def test_the_three_tiles_render_inside_one_band(self):
        feed = read(SITE / "feed.js")
        lab = function(feed, "renderLab")
        self.assertLess(lab.index("renderArenaTile()"), lab.index("renderRepos()"))
        self.assertLess(lab.index("renderRepos()"), lab.index("renderModels()"))
        self.assertIn('<section class="tile-band" id="lab" aria-labelledby="lab-h">', lab)
        self.assertIn('<div class="band-grid">${tiles}</div>', lab)
        self.assertIn("if (it.t === 'lab') return renderLab();", feed)

    def test_the_front_page_places_the_band_once_and_no_tile_of_it_alone(self):
        feed = read(SITE / "feed.js")
        widgets = feed[feed.index("const widgets = ["):feed.index("].filter(Boolean);", feed.index("const widgets = ["))]
        self.assertIn("{ t: 'lab' }", widgets)
        for alone in ("'arena'", "'repos'", "'models'"):
            self.assertNotIn(alone, widgets)
        # News first: the hot list, then the band, both after the first stories of the river.
        self.assertLess(widgets.index("'hot'"), widgets.index("'lab'"))
        self.assertIn("if ((i + 1) % 10 === 8 && widgets.length) out.push(widgets.shift());", feed)

    def test_the_band_spans_the_grid_and_keeps_its_tiles_side_by_side(self):
        css = read(SITE / "trang-msn.css")
        self.assertIn(".msn-grid > .tile-band { grid-column: 1 / -1; min-width: 0; }", css)
        grid = re.search(r"\.band-grid \{([^}]*)\}", css).group(1)
        self.assertIn("repeat(auto-fit, minmax(min(100%, var(--band-tile-min)), 1fr))", grid)
        self.assertIn("grid-column: auto; grid-row: auto;", re.search(r"\.band-grid > \.tile \{([^}]*)\}", css).group(1))


if __name__ == "__main__":
    unittest.main()

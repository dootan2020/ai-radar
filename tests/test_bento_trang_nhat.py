"""The front page as an orderly bento grid (captain, 10/11 17:51: "Duyệt, giao sửa", approving the coordinator's audit
plans/reports/audit-trang-nhat in firstmate-control). Five bands under one heading style, at most five columns; in every
band the cards of a row are one height and every row is full; "Kho mã đáng lấy" shows one filter row until it is opened;
no grey veil closes over the day's picture on scroll; no "Translated" label on the front page's cards and rows."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (ROOT / "site", ROOT / "extension")


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def function(src, name):
    start = src.index(f"function {name}(")
    return src[start:src.index("\n}\n", start)]


def rendered():
    """tests/verify-bento-rows.mjs once: the bands measured in Chrome at 1440, 1024 and 768 px from the fixture."""
    if not hasattr(rendered, "out"):
        run = subprocess.run(["node", "tests/verify-bento-rows.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=180)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        rendered.out = json.loads(run.stdout.strip().splitlines()[-1])
    return rendered.out


def browser_ready():
    if not shutil.which("node"):
        return False
    chrome = [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"), Path("/usr/bin/google-chrome"),
              Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    if not any(p.exists() for p in chrome):
        return False
    probe = subprocess.run(["node", "--input-type=module", "-e", "await import('puppeteer')"], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
    return probe.returncode == 0


class Bands(unittest.TestCase):
    def test_five_bands_in_the_approved_order_under_one_heading_style(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            front = function(feed, "frontHTML")
            titles = re.findall(r"bandHTML\('(\w+)', '([^']+)'", front)
            self.assertEqual(titles, [("today", "Hôm nay"), ("focus", "Điểm nhấn"), ("news", "Tin mới"), ("more", "Tin khác")])
            self.assertLess(front.index("bandHTML('news'"), front.index("renderLab()"))
            self.assertLess(front.index("renderLab()"), front.index("bandHTML('more'"))
            self.assertIn('<h2 class="band-title" id="band-${id}-h">${title}</h2>', feed)
            self.assertIn('<h2 class="band-title" id="lab-h">Mô hình và mã nguồn</h2>', function(feed, "renderLab"))

    def test_at_most_five_columns_and_the_content_stops_near_1600_px(self):
        for folder in FOLDERS:
            css, tokens = read(folder / "trang-msn.css"), read(folder / "tokens.css")
            self.assertIn("--bento-cols: 5;", tokens)
            self.assertIn("--msn-panel-max: 1624px;", tokens)
            for query, cols in (("(min-width: 1024px) and (max-width: 1439px)", 4), ("(min-width: 768px) and (max-width: 1023px)", 3),
                                ("(max-width: 767px)", 1)):
                block = css[css.index(f"@media {query} {{\n  :root {{ --bento-cols"):]
                self.assertIn(f"--bento-cols: {cols};", block[:block.index("\n}\n")])
            self.assertNotRegex(css, r"--msn-cols: [6-9]")
            self.assertIn("grid-template-columns: repeat(var(--bento-cols), minmax(0, 1fr)); grid-auto-rows: var(--band-row);", css)

    def test_story_bands_fill_whole_rows_from_the_live_column_count(self):
        feed = read(ROOT / "site" / "feed.js")
        news = function(feed, "frontNews")
        self.assertIn("const dbl = C(pool.splice(di, 1)[0], 'wide');", news)
        self.assertIn("const row = pool.splice(0, c - 2).map(st => C(st));", news)
        self.assertIn("else if (pool.length >= c) items.push(...pool.splice(0, c).map(st => C(st)));", news)
        count = function(feed, "otherCount")
        self.assertIn("return Math.min(want, Math.floor(all / cols) * cols);", count)
        self.assertIn("for (const q of ['(min-width: 768px)', '(min-width: 1024px)', '(min-width: 1440px)'])", function(feed, "watchBentoCols"))


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered rows")
class RenderedRows(unittest.TestCase):
    def test_every_row_is_level_and_full_at_three_widths(self):
        out = rendered()
        self.assertEqual({w: out[w]["cols"] for w in out}, {"1440": "5", "1024": "4", "768": "3"})
        for width, page in out.items():
            self.assertEqual(page["errors"], [], width)
            self.assertFalse(page["sideways"], width)
            self.assertEqual([b["band"] for b in page["bands"]], ["Hôm nay", "Điểm nhấn", "Tin mới", "Mô hình và mã nguồn", "Tin khác"])
            for band in page["bands"]:
                for key in ("unequal", "ragged", "overflow", "cut"):
                    self.assertEqual(band[key], [], f"{width} {band['band']} {key}")
                self.assertGreaterEqual(band["rows"], 1)

    def test_the_kho_ma_tile_shows_one_filter_row_until_opened(self):
        for width, page in rendered().items():
            self.assertEqual(page["repoFilterRows"], 1, width)
            self.assertGreater(page["repoFilterRowsOpen"], 1, width)

    def test_no_translated_label_on_the_rendered_front_page(self):
        for width, page in rendered().items():
            self.assertEqual(page["translated"], 0, width)


class KhoMaFilters(unittest.TestCase):
    def test_one_filter_row_until_the_list_is_opened(self):
        for folder in FOLDERS:
            css, feed = read(folder / "trang-msn.css"), read(folder / "feed.js")
            self.assertIn(".band-lab:not(.is-open) .tile-repos :is(.seg-quiet, .area-chips, .repo-note, .repo-more) { display: none; }", css)
            self.assertIn(".band-lab .repo-ctl { flex-wrap: nowrap; overflow: hidden; }", css)
            self.assertIn('data-lab-open aria-expanded="${labOpen}" aria-controls="lab">${labOpen ? \'Thu gọn\' : \'Mở rộng\'}</button>', feed)
            self.assertIn("const lx = t.closest('[data-lab-open]'); if (lx) { toggleLab(lx); return; }", feed)


class ScrollVeil(unittest.TestCase):
    def test_the_scroll_veil_is_gone_and_the_scrim_stays(self):
        for folder in FOLDERS:
            css, tokens = read(folder / "trang-msn.css"), read(folder / "tokens.css")
            for gone in (".nen::after", "nen-cover", "animation-timeline", "animation-range"):
                self.assertNotIn(gone, css, f"{folder.name}: {gone}")
            self.assertNotIn("--nen-cover", tokens)
            self.assertIn(".nen::before { content: \"\"; position: absolute; inset: 0; z-index: 1; background: var(--nen-scrim); }", css)
            self.assertIn("--nen-scrim:", tokens)


class TranslatedLabel(unittest.TestCase):
    def test_no_translated_label_on_front_page_cards_and_rows(self):
        for folder in FOLDERS:
            feed = read(folder / "feed.js")
            for name in ("msnCard", "topListHTML", "freshItem", "leadHTML"):
                self.assertNotIn("translationMark(", function(feed, name), f"{folder.name}: {name}")
            meta = feed[feed.index("const metaHTML = "):]
            self.assertNotIn("translationMark(", meta[:meta.index("\n")])
            self.assertNotIn('class="nc-mt"', feed)
        # The label stays in the story page's and the modal's footer.
        self.assertIn("Translated", read(ROOT / "site" / "story.js"))


class ListHoverAndLabels(unittest.TestCase):
    def test_the_list_wash_is_square_like_the_rules_between_rows(self):
        css = read(ROOT / "site" / "trang-msn.css")
        wash = re.search(r"\.list-row::before \{([^}]*)\}", css).group(1)
        self.assertIn("border-radius: 0;", wash)
        self.assertIn(".fresh-list li, .fresh-list .brief, .briefs li + li .brief { border-radius: 0; }", css)

    def test_card_names_are_labels_and_source_names_are_never_cut(self):
        css = read(ROOT / "site" / "trang-msn.css")
        label = css[css.index(".band :is(.tile .tile-title, .msn-toplist h2, .ev-head h2) {"):]
        label = label[:label.index("}")]
        self.assertIn("font-size: var(--text-micro);", label)
        self.assertIn("text-transform: uppercase;", label)
        src = re.search(r"\n\.nc-src \{([^}]*)\}", css).group(1)
        self.assertNotIn("text-overflow: ellipsis", src)
        self.assertNotIn("text-overflow: ellipsis", re.search(r"\n\.top-src \{([^}]*)\}", css).group(1))


if __name__ == "__main__":
    unittest.main()

"""The top row's search under "Một phần" and "Đầu đề", and the pager dots as drawn (captain, 10/11 18:54: "khi chỉnh bố
cục thì nút tìm kiếm nó phải luôn nằm ở giữa mép trên và mép nội dung chứ em / 2 dấu chấm của thẻ thời tiết nó nằm xa nhau
quá / các dấu chấm trên carousel thì có viền, bỏ viền đi"). The search's vertical middle is halfway between the window's
top edge and the panel's; "Toàn trang" keeps the search at 16 px and the panel at 84 px; the corners stay in the top row.
Rendered by tests/verify-top-search.mjs on the website and the unpacked extension at 1440x900 and 1920x1080."""
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


def rendered():
    if not hasattr(rendered, "out"):
        run = subprocess.run(["node", "tests/verify-top-search.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=300)
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


class SearchRule(unittest.TestCase):
    def test_the_lower_layouts_centre_the_search_in_the_space_above_the_panel(self):
        for folder in FOLDERS:
            css = read(folder / "trang-msn.css")
            self.assertIn(':is([data-layout="part"], [data-layout="head"]) .msn-top-in { flex: 1; grid-template-rows: var(--msn-search-h) 1fr; }', css)
            self.assertIn(':is([data-layout="part"], [data-layout="head"]) .msn-top :is(.news-search, .web-search) { grid-row: 1 / -1; align-self: center; }', css)
            # The middle is exact only while the row's top padding equals its bottom margin.
            self.assertIn(".msn-top { position: relative; padding: var(--top-pad) var(--msn-page-pad) 0;", css)
            self.assertIn("gap: var(--space-12); margin-bottom: var(--space-16);", css)
            self.assertIn("--top-pad: var(--space-16);", read(folder / "tokens.css"))


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered top row")
class RenderedTopRow(unittest.TestCase):
    def test_the_search_sits_halfway_between_the_window_top_and_the_panel(self):
        pages = rendered()["pages"]
        self.assertEqual(len(pages), 12)
        for name, m in pages.items():
            target, layout, size = name.split("-")
            self.assertEqual(m["layout"], layout, name)
            self.assertEqual(m["scrollY"], 0, name)
            self.assertFalse(m["sideways"], name)
            if layout == "full":
                self.assertEqual((round(m["searchTop"]), round(m["panelTop"])), (16, 84), name)
            else:
                self.assertGreater(m["panelTop"], 300, name)
                self.assertLessEqual(abs(m["off"]), 1, f"{name}: search middle {m['searchMid']} vs {m['half']}")

    def test_the_corners_stay_in_the_top_row_under_every_layout(self):
        pages = rendered()["pages"]
        for name, m in pages.items():
            target, layout, size = name.split("-")
            full = pages[f"{target}-full-{size}"]
            self.assertEqual(len(m["cornerTops"]), 3, name)
            self.assertEqual(m["cornerTops"], full["cornerTops"], name)
            for mid in m["cornerMids"]:
                self.assertLess(mid, 16 + 52, name)

    def test_no_errors(self):
        self.assertEqual(rendered()["errors"], [])


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered dots")
class RenderedDots(unittest.TestCase):
    def test_the_lead_and_weather_dots_are_drawn_alike_with_no_ring(self):
        dots = rendered()["dots"]
        lead, weather = dots["lead"], dots["weather"]
        self.assertIsNotNone(weather, "the weather card drew no dots")
        self.assertEqual(len(weather["dots"]), 2)
        self.assertGreaterEqual(len(lead["dots"]), 2)
        look = lambda d: (d["w"], d["h"], d["fill"], d["shadow"], d["radius"], d["buttonH"])
        for state in (True, False):
            self.assertEqual({look(d) for d in lead["dots"] + weather["dots"] if d["current"] is state}.__len__(), 1, state)
        for d in lead["dots"] + weather["dots"]:
            self.assertEqual(d["border"], "0px none")
            self.assertEqual(d["outline"], "none")
            self.assertEqual(d["buttonBorder"], "0px none")
            self.assertEqual(d["buttonBg"], "rgba(0, 0, 0, 0)")
            for layer in re.split(r",\s*(?=(?:color|rgba?)\()", d["shadow"]):
                self.assertNotRegex(layer, r"\)\s+0px 0px 0px", f"a ring: {d['shadow']}")

    def test_the_weather_dots_are_spaced_like_the_lead_dots(self):
        dots = rendered()["dots"]
        gaps = set(dots["lead"]["gaps"]) | set(dots["weather"]["gaps"])
        self.assertEqual(gaps, {8})


if __name__ == "__main__":
    unittest.main()

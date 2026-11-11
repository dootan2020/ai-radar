"""Switching between the front page's tabs (captain, 11/11 12:4x: "trên desktop, khi a chuyển từ trang chủ sang mã và
mô hình thì bị giật lag ... a cũng muốn làm cái gạch màu dưới mỗi tab đó di chuyển mượt mà từ tab này sang tab kia.
đồng thời cố định những thành phần giống nhau ở mỗi tab, chỉ tải lại nội dung, không tải lại toàn bộ"). A view short
enough to need no scrollbar used to widen the page by the scrollbar's 15 px and move every centred box 7.5 px; the
panel shrank to its content; the underline blinked from tab to tab. tests/capture-tab-switch.mjs renders the offline
fixture, whose "Mã và mô hình" and "Xếp hạng" are both shorter than a 2000x1200 window, and switches tabs."""
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


def switched():
    if not hasattr(switched, "out"):
        run = subprocess.run(["node", "tests/capture-tab-switch.mjs", "--only", "2000,375"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", timeout=300)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        switched.out = json.loads(run.stdout.strip().splitlines()[-1])
    return switched.out


class Source(unittest.TestCase):
    def test_the_page_keeps_its_scrollbar_gutter_in_both_copies(self):
        for folder in FOLDERS:
            css = read(folder / "feed.css")
            html_rule = re.search(r"^html \{[^}]*\}", css, re.M)[0]
            self.assertIn("scrollbar-gutter: stable", html_rule, folder.name)
        # The site's first paint uses the inlined critical copy (python -m radar.critical_css); the new tab links feed.css.
        self.assertIn("scrollbar-gutter:stable", read(ROOT / "site" / "index.html").replace(": ", ":"))

    def test_the_underline_moves_by_transform_alone(self):
        for folder in FOLDERS:
            css = read(folder / "trang-msn.css")
            self.assertIn(".msn-head .sections .tab-pill.is-active { transition: transform var(--motion-state) var(--ease-flow); }", css)
            self.assertNotIn('.msn-head .filter-chip[aria-pressed="true"]::after', css, folder.name)
            js = read(folder / "feed.js")
            line = js[js.index("function glideLine("):js.index("function landLine(")]
            self.assertNotIn("style.width", line.split("if (!line.dataset.lands)")[1], "in flight only the transform changes")

    def test_each_tab_has_an_address(self):
        js = read(ROOT / "site" / "feed.js")
        self.assertIn("if (f === 'rankings') return '#xep-hang';", js)
        self.assertIn("if (f === 'code') return '#repo';", js)
        self.assertIn("history.pushState(null, '', url);", js)


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed to switch tabs")
class Rendered(unittest.TestCase):
    def test_no_shared_box_moves_when_a_short_tab_opens(self):
        page = switched()["2000"]
        self.assertEqual(page["errors"], [])
        short = [s for s in page["states"] if s["docHeight"] <= 1200]
        self.assertTrue(short, "the fixture has a view shorter than the window, the case that dropped the scrollbar")
        first = page["states"][0]
        for s in page["states"]:
            where = f"{s['tab']} {s['hash']}"
            self.assertEqual(s["gutter"], "stable", where)
            self.assertEqual(s["bodyWidth"], first["bodyWidth"], where)
            for part in ("bar", "tabs", "panel"):
                self.assertEqual((s[part]["x"], s[part]["w"]), (first[part]["x"], first[part]["w"]), f"{where} {part}")
            # The panel reaches the window's foot less its 48 px bottom margin, however short the view.
            self.assertGreaterEqual(s["panel"]["y"] + s["panel"]["h"] + 48, 1200 - 1, f"{where}: the panel fills the window")
        for sw in page["switches"]:
            self.assertFalse(sw["tabsMoved"] or sw["barMoved"] or sw["widthChanged"], sw["to"])
            self.assertEqual(sw["shift"], 0, sw["to"])

    def test_the_shell_stays_and_only_the_view_changes(self):
        for width in ("2000", "375"):
            page = switched()[width]
            for s in page["states"][1:]:
                self.assertTrue(all(v is not False for v in s["kept"].values()), f"{width} {s['tab']}: {s['kept']}")
                self.assertEqual((s["added"], s["removed"]), ([], []), f"{width} {s['tab']}: header nodes were re-created")
            for sw in page["switches"][1:]:
                # The snapshot the page read once is never fetched again on a switch. (The fixture has no arena.json, so
                # "Xếp hạng" asks for it on each visit and gets a 404; with the live files it is fetched once.)
                self.assertFalse([u for u in sw["requests"] if u.startswith("/data/radar")], f"{width} {sw['to']}: data fetched again")

    def test_the_underline_glides_and_lands_under_the_new_tab(self):
        for width in ("2000", "375"):
            page = switched()[width]
            for s in page["states"]:
                line, tab = s["line"], s["activeBox"]
                self.assertIsNotNone(line, f"{width} {s['tab']}")
                self.assertTrue(tab["x"] <= line["x"] and line["x"] + line["w"] <= tab["x"] + tab["w"] + 1, f"{width} {s['tab']}")
                self.assertIsNone(s["after"], "the old per-tab mark is gone")
            for sw in page["switches"]:
                self.assertIn("line:transform", sw["moving"], f"{width} {sw['to']}")
                self.assertGreater(sw["lineSteps"], 5, f"{width} {sw['to']}: the line passes through the tabs between")
                self.assertLessEqual(sw["lineWidthSets"], 2, f"{width} {sw['to']}: its width changes once, when it lands")
            self.assertLessEqual(page["reduced"]["lineSteps"], 2, f"{width}: reduced motion jumps")
            self.assertEqual(page["reduced"]["running"], 0, f"{width}: reduced motion runs nothing")

    def test_back_forward_and_reload_return_to_the_tab(self):
        page = switched()["2000"]
        states = {s["tab"]: s["hash"] for s in page["states"]}
        self.assertEqual(states, {"all": "", "code": "#repo", "rankings": "#xep-hang"})
        steps = [(h["step"], h.get("hash"), h.get("active")) for h in page["history"]]
        self.assertEqual(steps, [("back", "#repo", "code"), ("back", "#xep-hang", "rankings"), ("forward", "#repo", "code"),
                                 ("reload", "#repo", "code"), ("resize", "#repo", "code")])
        for h in page["history"]:
            line, tab = h["line"], h["activeBox"]
            self.assertTrue(tab["x"] <= line["x"] and line["x"] + line["w"] <= tab["x"] + tab["w"] + 1, h["step"])


if __name__ == "__main__":
    unittest.main()

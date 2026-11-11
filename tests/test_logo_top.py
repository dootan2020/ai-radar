"""The "halcyon" logo returns the reader to the very top of the front page (captain, 11/11 14:50: "khi a click vào chữ
halcyon thì nội dung bị kéo lên trên, thanh tìm kiếm sát mép browsers. link truy cập tới là https://hco.news/#top").
It used to be href="#top", which scrolled the panel (below the search bar) to the window's edge. Now it is a plain "/"
for no-script readers and a click opens the front page's tab, scrolls to 0 and leaves the address clean, with no
page load. tests/capture-logo-top.mjs reads Mã và mô hình 1500 px down, clicks the logo at 1440 and 375."""
import json
import re
import subprocess
import unittest
from pathlib import Path

from tests.test_tab_switch import browser_ready

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class Source(unittest.TestCase):
    def test_the_logo_is_the_front_page_and_the_skip_link_keeps_top(self):
        html = read(ROOT / "site" / "index.html")
        self.assertRegex(html, r'<a class="brand feed-brand" id="brand" href="/" ')
        self.assertIn('<a class="skip" href="#top">', html)

    def test_the_new_tab_logo_still_opens_the_live_site(self):
        html = read(ROOT / "extension" / "newtab.html")
        self.assertRegex(html, r'id="brand" href="https://[^"]+/" aria-label="Halcyon, mở trang web"')


@unittest.skipUnless(browser_ready(), "needs node, puppeteer and Chrome")
class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "tests/capture-logo-top.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=300)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    def test_the_logo_returns_to_the_top_of_the_front_page(self):
        for width in ("1440", "375"):
            with self.subTest(width=width):
                r = self.out[width]
                self.assertGreater(r["before"]["scrollY"], 0, "the reader was down the page")
                self.assertEqual(r["before"]["hash"], "#repo")
                after = r["after"]
                self.assertEqual(after["scrollY"], 0)
                self.assertEqual(after["hash"], "")
                self.assertEqual(after["path"], "/")
                self.assertEqual(after["active"], "all")
                self.assertGreaterEqual(after["searchTop"], 0)
                self.assertTrue(after["inView"])
                self.assertTrue(r["sameShell"], "the shell is kept: no page load")
                self.assertEqual(after["entries"] - r["entries0"], 2, "one entry for the tab, one for the front page")


if __name__ == "__main__":
    unittest.main()
"""The Halcyon page keeps real margins on wide screens; from 768 px the day's picture fills the first screen, as on
Edge's new tab (owner, 10/11: "còn về ảnh nền thì em làm như edge"), and a phone keeps the plain page."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"
LIVE = "https://radar-ai-vn.pages.dev/"


def nen_section(css):
    return css[css.index("/* ---------- the day's picture behind the first screen"):css.index("@keyframes nen-cover")]


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


class DayPicture(unittest.TestCase):
    def test_both_pages_carry_the_layer_and_load_the_picker_before_the_feed(self):
        for path in (SITE / "index.html", EXT / "newtab.html"):
            html = read(path)
            self.assertIn('<div class="nen" id="nen" aria-hidden="true"></div>', html, path.name)
            self.assertLess(html.index('<script type="module" src="nen.js"></script>'),
                            html.index('<script type="module" src="feed.js"></script>'), path.name)
        self.assertEqual(read(SITE / "nen.js"), read(EXT / "nen.js"))

    def test_the_picture_is_drawn_only_from_768_px_and_only_by_the_script(self):
        css = read(SITE / "trang-msn.css")
        section = nen_section(css)
        self.assertIn(".nen { display: none; }", section)
        wide = section[section.index("@media (min-width: 768px) {"):]
        self.assertIn(".nen { display: block; position: fixed;", wide)
        # No stylesheet asks for a picture: a phone, where the layer is never drawn, downloads nothing.
        self.assertNotIn("url(", section)
        self.assertIn("export const WIDE = '(min-width: 768px)';", read(SITE / "nen.js"))

    def test_the_first_screen_is_the_picture_and_the_panel_starts_under_the_middle(self):
        tokens = read(SITE / "tokens.css")
        self.assertIn("--nen-fold: clamp(320px, 45vh, 640px);", tokens)
        self.assertRegex(tokens, r"--nen-mat: #[0-9A-F]{6};")
        wide = nen_section(read(SITE / "trang-msn.css"))
        self.assertIn(".msn-top { display: flex; flex-direction: column; min-height: var(--nen-fold); }", wide)
        # The controls on the picture carry their own surface instead of a scrim over the whole picture.
        self.assertIn("background: var(--nen-pill); box-shadow: var(--nen-pill-shadow);", wide)
        self.assertIn(".msn-top .ns-field, .msn-top .tool-launcher-button {", wide)
        self.assertIn(".msn-top .web-field {", read(EXT / "newtab.css"))
        self.assertIn("animation-timeline: scroll(root block)", wide)

    def test_one_packaged_picture_ships_for_the_offline_and_missing_days(self):
        for folder in (SITE, EXT):
            picture = folder / "anh" / "nen-du-phong.webp"
            self.assertTrue(picture.exists(), picture)
            self.assertLessEqual(picture.stat().st_size, 200 * 1024)
            self.assertEqual(picture.read_bytes()[8:12], b"WEBP")
        self.assertIn("export const PACKAGED = 'anh/nen-du-phong.webp';", read(SITE / "nen.js"))

    @unittest.skipUnless(shutil.which("node"), "Node required for the day's picture tests")
    def test_the_day_is_picked_in_bangkok_and_falls_back_in_order(self):
        run = subprocess.run(["node", "tests/verify-nen.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(got["bangkok"], ["2026-11-10", "2026-11-09", "2027-01-01"])
        self.assertEqual(got["pick"], {"today": "2026-11-10.avif", "earlier": "2026-11-09.webp",
                                       "none": None, "malformed": None, "empty": None})
        self.assertEqual(got["site"], {"shown": "nen/2026-11-10.avif", "fetched": ["nen/lich.json"],
                                       "ready": True, "cached": []})
        self.assertEqual(got["siteNoLich"], "anh/nen-du-phong.webp")
        self.assertEqual(got["siteBrokenPicture"], "anh/nen-du-phong.webp")
        today = LIVE + "nen/2026-11-10.avif"
        self.assertEqual(got["extOnline"], {"shown": today, "cached": [today], "remembered": today})
        self.assertEqual(got["extOffline"], "blob:blob-of-" + LIVE + "nen/2026-11-09.webp")
        self.assertEqual(got["extNothingKept"], "anh/nen-du-phong.webp")

    @unittest.skipUnless(shutil.which("node"), "Node required for the day's picture tests")
    def test_a_phone_downloads_nothing_until_the_window_is_widened(self):
        run = subprocess.run(["node", "tests/verify-nen.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        phone = json.loads(run.stdout.strip().splitlines()[-1])["phone"]
        self.assertEqual(phone, {"fetched": [], "shown": [], "query": "(min-width: 768px)",
                                 "afterWiden": "nen/2026-11-10.avif"})


if __name__ == "__main__":
    unittest.main()

"""The Halcyon page keeps real margins on wide screens; from 768 px the day's picture fills the first screen, as on
Edge's new tab (owner, 10/11: "còn về ảnh nền thì em làm như edge"), and a phone keeps the plain page."""
import functools
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"
LIVE = "https://radar-ai-vn.pages.dev/"


def nen_section(css):
    start = css.index("/* ---------- the day's picture behind the page")
    return css[start:css.index("/* ---------- \"Tùy chỉnh\"", start)]


def read(path):
    return path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def verify_nen():
    """tests/verify-nen.mjs once per run: the day's picture with a fake page."""
    run = subprocess.run(["node", "tests/verify-nen.mjs"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    if run.returncode != 0:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout.strip().splitlines()[-1])


class PageBackground(unittest.TestCase):
    def test_panel_and_top_row_stop_at_the_same_width(self):
        tokens, css = read(SITE / "tokens.css"), read(SITE / "trang-msn.css")
        # Content at most 1600 px (captain, 10/11 17:51): the panel's 1624 px less its two 12 px paddings.
        self.assertIn("--msn-panel-max: 1624px;", tokens)
        self.assertIn("--msn-panel-pad: var(--space-12);", tokens)
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

    def test_the_picture_fills_the_window_and_the_panel_sits_high_by_default(self):
        # Captain, 10/11 14:48: the search and the panel high, as on Edge (tests/test_thanh_tren.py); "Một phần" keeps
        # the fold a little under the middle.
        tokens = read(SITE / "tokens.css")
        self.assertIn("--nen-fold: clamp(320px, 52vh, 640px);", tokens)
        self.assertRegex(tokens, r"--nen-mat: #[0-9A-F]{6};")
        wide = nen_section(read(SITE / "trang-msn.css"))
        self.assertIn(".msn-top { display: flex; flex-direction: column; }", wide)
        self.assertIn('[data-layout="part"] .msn-top { min-height: var(--nen-fold); }', wide)
        # The search keeps its frosted pill on the picture; the corners' tiles take the veil's white ink.
        self.assertIn("background: var(--nen-pill); box-shadow: var(--nen-pill-shadow);", wide)
        self.assertIn(".msn-top .web-field {", read(EXT / "newtab.css"))
        # No surface closes over the picture on scroll (captain, 10/11 17:51; tests/test_bento_trang_nhat.py).
        self.assertNotIn("animation-timeline", wide)

    def test_one_packaged_picture_ships_for_the_offline_and_missing_days(self):
        for folder in (SITE, EXT):
            picture = folder / "anh" / "nen-du-phong.webp"
            self.assertTrue(picture.exists(), picture)
            self.assertLessEqual(picture.stat().st_size, 200 * 1024)
            self.assertEqual(picture.read_bytes()[8:12], b"WEBP")
        self.assertIn("export const PACKAGED = 'anh/nen-du-phong.webp';", read(SITE / "nen.js"))

    @unittest.skipUnless(shutil.which("node"), "Node required for the day's picture tests")
    def test_the_day_is_picked_in_bangkok_and_falls_back_in_order(self):
        got = verify_nen()
        self.assertEqual(got["bangkok"], ["2026-11-10", "2026-11-09", "2027-01-01"])
        self.assertEqual(got["pick"], {"today": "2026-11-10.avif", "earlier": "2026-11-09.webp",
                                       "none": None, "malformed": None, "empty": None,
                                       "order": ["2026-11-10.avif", "2026-11-09.webp", "2026-11-08.webp"]})
        self.assertEqual(got["site"], {"shown": "nen/2026-11-10.avif", "fetched": ["nen/lich.json"],
                                       "ready": True, "cached": []})
        self.assertEqual(got["siteNoLich"], "anh/nen-du-phong.webp")
        today = LIVE + "nen/2026-11-10.avif"
        self.assertEqual({k: got["extOnline"][k] for k in ("shown", "cached", "remembered")},
                         {"shown": today, "cached": [today], "remembered": today})
        self.assertEqual(got["extOffline"], "blob:blob-of-" + LIVE + "nen/2026-11-09.webp")
        self.assertEqual(got["extNothingKept"], "anh/nen-du-phong.webp")

    @unittest.skipUnless(shutil.which("node"), "Node required for the day's picture tests")
    def test_a_broken_picture_for_today_shows_the_day_before_it_first(self):
        got = verify_nen()
        self.assertEqual(got["siteBrokenPicture"], "nen/2026-11-09.webp")
        self.assertEqual(got["siteBrokenTried"], ["nen/2026-11-10.avif", "nen/2026-11-09.webp"])
        # The packaged picture only when the day before is broken too, and never a third day.
        self.assertEqual(got["siteBothBroken"], "anh/nen-du-phong.webp")
        self.assertEqual(got["siteBothBrokenTried"],
                         ["nen/2026-11-10.avif", "nen/2026-11-09.webp", "anh/nen-du-phong.webp"])
        self.assertEqual(got["extBrokenPicture"], LIVE + "nen/2026-11-09.webp")

    @unittest.skipUnless(shutil.which("node"), "Node required for the day's picture tests")
    def test_the_new_tab_downloads_the_picture_once(self):
        ext = verify_nen()["extOnline"]
        # The calendar, then the picture once; the <img> and the offline copy both reuse that one download.
        self.assertEqual(ext["fetched"], [LIVE + "nen/lich.json", LIVE + "nen/2026-11-10.avif"])
        self.assertEqual(ext["img"], ["blob:picture-of-" + LIVE + "nen/2026-11-10.avif"])
        self.assertNotIn("cache.add(", read(SITE / "nen.js"))

    @unittest.skipUnless(shutil.which("node"), "Node required for the day's picture tests")
    def test_a_phone_downloads_nothing_until_the_window_is_widened(self):
        phone = verify_nen()["phone"]
        self.assertEqual(phone, {"fetched": [], "shown": [], "query": "(min-width: 768px)",
                                 "afterWiden": "nen/2026-11-10.avif"})


FRESH_HARNESS = r"""
globalThis.window = globalThis;
const getComputedStyle = () => ({ paddingBottom: '16px' });
const HEAD = 56, PAD = 16;
function tileOf({ heights, pinned, grow = false, clientH = 360 }) {
  const visible = () => rows.filter(r => !r.hidden);
  const rows = heights.map((h, i) => ({
    h, hidden: false, pinned: i < pinned,
    hasAttribute(a) { return a === 'data-pinned' && this.pinned; },
    getBoundingClientRect() {
      let top = HEAD;
      for (const r of visible()) { if (r === this) break; top += r.h; }
      return { top, bottom: top + this.h };
    },
  }));
  const ul = { children: rows, getBoundingClientRect: () => ({ top: HEAD }) };
  const tile = {
    hidden: false, clientTop: 0,
    get scrollHeight() { return HEAD + visible().reduce((s, r) => s + r.h, 0) + PAD; },
    get clientHeight() { return grow ? this.scrollHeight : clientH; },
    getBoundingClientRect: () => ({ top: 0 }),
    querySelector: s => (s === '.fresh-list' ? ul : null),
  };
  return { tile, rows, room: clientH - PAD - HEAD - 1 };
}
let current = null;
const $ = s => (s === '#fresh-row' ? current.tile : null);
__FIT__
function look(t) {
  const shown = t.rows.map((r, i) => [r, i]).filter(([r]) => !r.hidden);
  return { shown: shown.map(([, i]) => i), fits: shown.every(([r]) => r.getBoundingClientRect().bottom - HEAD <= t.room) };
}
const out = {};
// Four new rows, the first one three lines tall: the newest whole rows stay, the last is left out.
current = tileOf({ heights: [100, 66, 66, 66], pinned: 4 });
fitFreshTile(); out.batch = look(current);
// Ordinary rows that do not fit are left out the same way.
current = tileOf({ heights: [80, 80, 80, 80], pinned: 0 });
fitFreshTile(); out.plain = look(current);
// Rows that all fit all show.
current = tileOf({ heights: [60, 60, 60, 60], pinned: 0 });
fitFreshTile(); out.roomy = look(current);
// A first row taller than the whole tile still shows: the tile is never empty.
current = tileOf({ heights: [400, 60], pinned: 0 });
fitFreshTile(); out.tall = look(current);
// A tile that grows with its rows (phone, tablet) shows them all.
current = tileOf({ heights: [80, 66, 66, 66], pinned: 4, grow: true });
fitFreshTile(); out.grows = look(current);
process.stdout.write(JSON.stringify(out));
"""


class FreshTileRows(unittest.TestCase):
    """"Vừa đăng" beside the lead shows only whole rows, newest first, and never pages (captain, 12/11 09:23)."""

    def test_the_tile_hides_rows_it_cannot_show_whole_and_has_no_pager(self):
        css = read(SITE / "trang-msn.css")
        self.assertIn(".fresh-list > li[hidden] { display: none; }", css)
        self.assertNotIn("fresh-pager", css)
        feed = read(SITE / "feed.js")
        self.assertIn("fitFreshTile();\n  fitBandLists();\n  scheduleCountdown();", feed)
        for gone in ("fresh-pager", "pageFresh", "freshPage", "data-fresh-page"):
            self.assertNotIn(gone, feed)

    @unittest.skipUnless(shutil.which("node"), "Node required for the fitting test")
    def test_whole_rows_newest_first(self):
        feed = read(SITE / "feed.js")
        fit = feed[feed.index("let freshRO = null;"):feed.index("function goFirstNew()")]
        fit = fit[:fit.index("/* Redraw the tile in place")]
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(FRESH_HARNESS.replace("__FIT__", fit), encoding="utf-8", newline="\n")
            run = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True, text=True,
                                 encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout)
        self.assertEqual((got["batch"]["shown"], got["batch"]["fits"]), ([0, 1, 2], True))
        self.assertEqual((got["plain"]["shown"], got["plain"]["fits"]), ([0, 1, 2], True))
        self.assertEqual((got["roomy"]["shown"], got["roomy"]["fits"]), ([0, 1, 2, 3], True))
        self.assertEqual(got["tall"]["shown"], [0])
        self.assertEqual(got["grows"]["shown"], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()

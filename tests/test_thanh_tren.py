"""The top row after Edge's new tab (captain, 10/11 14:48: "nút 9 dấu chấm kia không nên bo tròn", "đưa nút tìm kiếm và nội
dung cao lên trên", "có nút tùy chỉnh hiển thị như edge", "giữa nền và nội dung để 1 lớp phủ"; 14:55: "chuyển cho anh cụm
nhiệt độ, vị trí, thời tiết và ngày tháng năm, cùng ở góc trên trái"): the weather and the day at the top left, "Tùy chỉnh"
and the square 9 dots at the top right, a veil over the picture, and choices that survive a reload."""
import functools
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"


def read(path):
    return path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def verify():
    """tests/verify-thanh-tren.mjs once per run."""
    run = subprocess.run(["node", "tests/verify-thanh-tren.mjs"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    if run.returncode != 0:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout.strip().splitlines()[-1])


DEFAULTS = {"layout": "full", "picture": True, "weather": True}


class TopRowMarkup(unittest.TestCase):
    def test_both_pages_put_the_weather_left_and_the_tiles_right(self):
        for path in (SITE / "index.html", EXT / "newtab.html"):
            html = read(path)
            head = html[html.index('id="masthead"'):html.index("</header>")]
            self.assertIn('<div class="top-now" id="top-now"></div>', head, path.name)
            # The cluster opens the row, "Tùy chỉnh" sits just before the 9 dots at its end.
            self.assertLess(head.index('id="top-now"'), head.index("search"), path.name)
            self.assertLess(head.index('id="tc-open"'), head.index('class="tool-launcher"'), path.name)
            self.assertIn('aria-label="Tùy chỉnh"', head, path.name)
            self.assertIn('aria-controls="tuy-chinh"', head, path.name)
            self.assertIn('<script type="module" src="thanh-tren.js"></script>', html, path.name)
        self.assertEqual(read(SITE / "thanh-tren.js"), read(EXT / "thanh-tren.js"))

    def test_the_corners_sit_on_the_row_s_outer_columns(self):
        css = read(SITE / "trang-msn.css")
        top = re.search(r"\.msn-top-in \{([^}]*)\}", css).group(1)
        self.assertIn("minmax(var(--top-side), 1fr) minmax(0, var(--msn-search-max)) minmax(var(--top-side), 1fr)", top)
        self.assertRegex(css, r"\.top-now \{\s*grid-column: 1;")
        self.assertIn(".msn-top .masthead-actions { grid-column: 3;", css)
        self.assertIn('[data-wx="off"] .top-wx { display: none; }', css)

    def test_the_9_dots_are_a_square_tile_not_a_circle(self):
        for folder in (SITE, EXT):
            menu = read(folder / "menu-cong-cu.css")
            button = re.search(r"\.tool-launcher-button\{([^}]*)\}", menu).group(1)
            self.assertIn("border-radius:var(--radius-8)", button)
            self.assertNotIn("radius-full", button)
        css = read(SITE / "trang-msn.css")
        tile = re.search(r"\.msn-top \.top-tile, \.msn-top \.tool-launcher-button \{([^}]*)\}", css).group(1)
        self.assertIn("border-radius: var(--radius-8)", tile)
        self.assertIn("width: var(--btn-h); height: var(--btn-h)", tile)

    def test_the_veil_covers_the_whole_picture_and_darkens_the_top(self):
        tokens = read(SITE / "tokens.css")
        scrim = re.search(r"--nen-scrim: ([^;]*);", tokens).group(1)
        self.assertTrue(scrim.startswith("linear-gradient(to bottom,"), scrim)
        alphas = [float(a) for a in re.findall(r"/ (0\.\d+)\)", scrim)]
        self.assertGreaterEqual(len(alphas), 3, scrim)
        self.assertGreater(alphas[0], alphas[-1])        # darker along the top edge, where the corners' white ink sits
        self.assertGreaterEqual(alphas[-1], 0.25)        # and never clear: the whole picture sits under the veil
        self.assertIn("--top-on-nen-ink: var(--brand-white);", tokens)

    def test_the_search_and_panel_sit_high_unless_the_reader_chose_otherwise(self):
        tokens, css = read(SITE / "tokens.css"), read(SITE / "trang-msn.css")
        self.assertIn("--top-pad: var(--space-16);", tokens)
        self.assertIn(".msn-top { position: relative; padding: var(--top-pad) var(--msn-page-pad) 0;", css)
        self.assertIn('[data-layout="part"] .msn-top { min-height: var(--nen-fold); }', css)
        self.assertIn('[data-layout="head"] .msn-top { min-height: calc(100svh - var(--nen-peek)); }', css)
        self.assertNotIn("--nen-lift", css + tokens)

    def test_the_picture_off_draws_no_layer(self):
        css = read(SITE / "trang-msn.css")
        self.assertIn(':root:not([data-nen="off"]) .nen { display: block; position: fixed;', css)
        self.assertIn("export const NEN_ON = 'halcyon:nen-on';", read(SITE / "nen.js"))

    def test_the_layout_and_picture_choices_leave_phones_alone(self):
        css = read(SITE / "trang-msn.css")
        self.assertIn("@media (max-width: 767px) {\n  .tc-wide { display: none; }\n}", css.replace("\r\n", "\n"))
        js = read(SITE / "thanh-tren.js")
        self.assertEqual(js.count('class="tc-group tc-wide"') + js.count('class="tc-row tc-wide"'), 2)


@unittest.skipUnless(shutil.which("node"), "Node required for the top row tests")
class SavedChoices(unittest.TestCase):
    def test_each_choice_survives_a_reload(self):
        reload = verify()["reload"]
        self.assertEqual(len(reload), 6)
        for row in reload:
            self.assertTrue(row["saved"])
            # What was saved is what is read back, and the page's first-paint scripts on the site and the new tab draw
            # the same attributes as the module, so nothing moves when the modules arrive.
            self.assertEqual(row["module"], row["site"])
            self.assertEqual(row["module"], row["ext"])
        got = {(r["read"]["layout"], r["read"]["picture"], r["read"]["weather"]): r["module"] for r in reload}
        self.assertEqual(got[("full", True, True)], {})
        self.assertEqual(got[("part", True, True)], {"layout": "part"})
        self.assertEqual(got[("head", True, True)], {"layout": "head"})
        self.assertEqual(got[("full", False, True)], {"nen": "off"})
        self.assertEqual(got[("full", True, False)], {"wx": "off"})
        self.assertEqual(got[("head", False, False)], {"layout": "head", "nen": "off", "wx": "off"})

    def test_the_theme_choice_survives_a_reload(self):
        for row in verify()["themes"]:
            self.assertEqual({row["read"], row["site"], row["ext"]}, {row["theme"]}, row)

    def test_failing_storage_falls_back_to_the_defaults(self):
        f = verify()["failing"]
        for name in ("readThrows", "missing", "malformed", "wrongTypes", "nullStorage"):
            self.assertEqual(f[name], DEFAULTS, name)
        self.assertEqual(f["partial"], {**DEFAULTS, "weather": False})
        self.assertFalse(f["saveThrows"])
        self.assertEqual(f["themeThrows"], ["system", False])
        self.assertEqual(f["siteBroken"], {})
        self.assertEqual(f["extBroken"], {})
        # A broken "Tùy chỉnh" entry never costs the reader the saved theme.
        self.assertEqual(f["siteMalformed"], {"theme": "dark"})


@unittest.skipUnless(shutil.which("node"), "Node required for the top row tests")
class WeatherCluster(unittest.TestCase):
    def test_the_cluster_is_drawn_from_the_weather_card_s_reading(self):
        c = verify()["cluster"]
        self.assertEqual(c["nowC"], {"city": "Hà Nội", "unit": "C", "temp": 20, "label": "Mưa phùn", "symbol": "rain"})
        self.assertEqual(c["nowF"]["temp"], 67)
        self.assertEqual(c["night"]["symbol"], "moon")
        self.assertIsNone(c["empty"])
        html = c["htmlC"]
        for part in ('<span class="top-city">Hà Nội</span>', '<use href="#wx-sym-rain"/>',
                     '<span class="top-temp num">20°C</span>', '<span class="sr">, mưa phùn</span>',
                     '<time datetime="2026-11-10">Thứ Ba, 10/11/2026</time>'):
            self.assertIn(part, html)
        self.assertLess(html.index("top-city"), html.index("top-temp"))
        self.assertLess(html.index("top-temp"), html.index("top-date"))
        self.assertIn("67°F", c["htmlF"])
        self.assertEqual(c["htmlNone"], '<span class="top-date"><time datetime="2026-11-10">Thứ Ba, 10/11/2026</time></span>')
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", c["escaped"])

    def test_the_day_is_the_bangkok_day(self):
        c = verify()["cluster"]
        self.assertEqual(c["earlyUtc"], {"iso": "2026-11-10", "text": "Thứ Ba, 10/11/2026"})
        self.assertEqual(c["lateUtc"], {"iso": "2026-11-11", "text": "Thứ Tư, 11/11/2026"})

    def test_the_card_publishes_what_it_paints(self):
        wx = read(SITE / "thoi-tiet.js")
        self.assertIn("publish(weatherNow(data, city, unit));", wx)
        self.assertIn("publish(null);", wx)
        self.assertIn("onWeather(w => { weather = w; paintCluster(); });", read(SITE / "thanh-tren.js"))
        self.assertNotIn("fetch(", read(SITE / "thanh-tren.js"))

    def test_the_picture_waits_while_it_is_turned_off(self):
        off = verify()["off"]
        self.assertEqual(off["whileOff"], [])
        self.assertEqual(off["stillOff"], [])
        self.assertEqual(off["after"], ["nen/lich.json", "nen/2026-11-10.webp"])
        self.assertEqual(off["shown"], "nen/2026-11-10.webp")
        self.assertEqual(off["listenersLeft"], 0)


if __name__ == "__main__":
    unittest.main()

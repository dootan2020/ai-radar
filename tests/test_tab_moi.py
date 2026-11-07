"""The new tab's top zone: the lunar date, the weather and the Google services (captain, 07/11 13:15 and 13:54).

The lunar calendar is checked against dates every Vietnamese calendar prints (Tết, a leap month). The weather reads
Open-Meteo without a key, the reader chooses the city, the browser's location is never asked for and the manifest gains
no permission.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def node(script, *args):
    run = subprocess.run(["node", "--input-type=module", "-e", script, *map(str, args)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node required for the extension modules")
class LunarDateTests(unittest.TestCase):
    def test_known_lunar_dates(self):
        script = r"""
import { solarToLunar, lunarText, todayVN } from '%s';
const days = [[17, 2, 2026], [29, 1, 2025], [10, 2, 2024], [22, 3, 2023], [20, 4, 2023], [7, 11, 2026], [23, 11, 2026]];
const out = days.map(([d, m, y]) => lunarText(solarToLunar(d, m, y)));
// 23:30 UTC on 6/11 is already 7/11 in Vietnam.
out.push(todayVN(new Date(Date.UTC(2026, 10, 6, 23, 30))));
process.stdout.write(JSON.stringify(out));
""" % (EXT / "lich-am.js").as_uri()
        out = node(script)
        self.assertEqual(out[:7], [
            "Âm lịch Mùng 1 tháng Giêng, năm Bính Ngọ",   # Tết 2026
            "Âm lịch Mùng 1 tháng Giêng, năm Ất Tỵ",      # Tết 2025
            "Âm lịch Mùng 1 tháng Giêng, năm Giáp Thìn",  # Tết 2024
            "Âm lịch Mùng 1 tháng Hai nhuận, năm Quý Mão",  # 2023's leap second month
            "Âm lịch Mùng 1 tháng Ba, năm Quý Mão",
            "Âm lịch 29 tháng Chín, năm Bính Ngọ",
            "Âm lịch Rằm tháng Mười, năm Bính Ngọ",
        ])
        self.assertEqual(out[7], {"weekday": "Thứ Bảy", "d": 7, "m": 11, "y": 2026})

    def test_calendar_card_facts(self):
        # The calendar card (mockup H, 08/11): can chi of the day, the lunar month and the year with their animals (the
        # Vietnamese twelve: trâu, mèo), the solar term and the one note, all computed from the date.
        script = r"""
import { calendarDay } from '%s';
const days = [[17, 2, 2026], [7, 11, 2026], [8, 11, 2026], [22, 12, 2026], [23, 11, 2026], [1, 3, 2027], [15, 3, 2026]];
process.stdout.write(JSON.stringify(days.map(([d, m, y]) => { const c = calendarDay(d, m, y);
  return [c.weekday, c.lunarDay, c.animals.day.canchi, c.animals.day.file, c.animals.month.canchi, c.animals.month.file,
          c.animals.year.canchi, c.animals.year.name, c.term, c.note]; })));
""" % (EXT / "lich-am.js").as_uri()
        out = node(script)
        # Tết Bính Ngọ: ngày Nhâm Tuất in tháng Canh Dần (the brief's "ngày Canh Dần" is the month's can chi; the day
        # follows from 01/01/2000 = Mậu Ngọ and from 07/11/2026 = Ất Dậu, 263 days apart).
        self.assertEqual(out[0], ["Thứ Ba", "Mùng 1 tháng Giêng", "Nhâm Tuất", "dog", "Canh Dần", "tiger",
                                  "Bính Ngọ", "ngựa", "Lập xuân", "Hôm nay là mùng 1 tháng Giêng"])
        self.assertEqual(out[1], ["Thứ Bảy", "29 tháng Chín", "Ất Dậu", "rooster", "Mậu Tuất", "dog",
                                  "Bính Ngọ", "ngựa", "Lập đông", "Hôm nay vào tiết Lập đông"])
        self.assertEqual(out[2], ["Chủ Nhật", "30 tháng Chín", "Bính Tuất", "dog", "Mậu Tuất", "dog",
                                  "Bính Ngọ", "ngựa", "Lập đông", "Mai là mùng 1 tháng Mười"])
        self.assertEqual(out[3][8:], ["Đông chí", "Hôm nay vào tiết Đông chí"])
        self.assertEqual(out[4][1], "Rằm tháng Mười")
        self.assertEqual(out[4][9], "Hôm nay là rằm tháng Mười")
        self.assertEqual(out[5][6:8], ["Đinh Mùi", "dê"])      # 2027 after Tết: the goat
        self.assertEqual(out[5][9], "Còn 7 ngày tới mùng 1 tháng Hai")
        self.assertEqual(out[6][1], "27 tháng Giêng")
        self.assertEqual(out[6][9], "Còn 4 ngày tới mùng 1 tháng Hai")


@unittest.skipUnless(shutil.which("node"), "Node required for the extension modules")
class WeatherTests(unittest.TestCase):
    def test_forecast_asks_open_meteo_for_now_hours_and_days(self):
        script = r"""
import { CITIES, describe, forecastURL } from '%s';
process.stdout.write(JSON.stringify({ first: CITIES[0], url: forecastURL(21.0285, 105.8542),
  codes: [0, 3, 61, 95, 1234].map(c => describe(c)[0]) }));
""" % (EXT / "thoi-tiet.js").as_uri()
        out = node(script)
        self.assertEqual(out["first"][0], "Hà Nội")  # the default city
        url = out["url"]
        self.assertTrue(url.startswith("https://api.open-meteo.com/v1/forecast?latitude=21.0285&longitude=105.8542"))
        for part in ("current=", "hourly=", "daily=", "timezone=Asia%2FBangkok", "forecast_days=5"):
            self.assertIn(part, url)
        self.assertNotIn("apikey", url.lower())
        self.assertEqual(out["codes"], ["Trời quang", "Nhiều mây", "Mưa nhỏ", "Dông", "Không rõ"])

    def test_city_is_chosen_never_located(self):
        source = (EXT / "thoi-tiet.js").read_text(encoding="utf-8")
        self.assertNotIn("geolocation", source)
        self.assertIn("const KEY_CITY = 'halcyon:city';", source)
        self.assertIn("const CACHE_MS = 30 * 60e3;", source)


class TopZoneTests(unittest.TestCase):
    def test_manifest_gains_no_permission_or_host(self):
        manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        # The same permissions as before the top zone: Open-Meteo answers with CORS and needs no host entry.
        self.assertEqual(manifest.get("permissions", []), ["storage", "alarms"])
        self.assertEqual(manifest.get("host_permissions", []), ["https://radar-ai-vn.pages.dev/*"])
        self.assertNotIn("optional_permissions", manifest)

    def test_services_name_each_google_service(self):
        source = (EXT / "vung-dau.js").read_text(encoding="utf-8")
        for name in ("Gmail", "YouTube", "Drive", "Maps", "Lịch", "Dịch", "Gemini"):
            self.assertIn(f"['{name}', 'https://", source)
        # Row 1 is icons only at every width (captain, 07/11 22:41): no visible label; the name is read from
        # aria-label and shown as the title tooltip.
        self.assertIn('class="svc" href="${url}" title="${name}" aria-label="${name}"', source)
        self.assertNotIn('svc-name', source)

    def test_new_tab_loads_the_top_zone_only_on_the_extension(self):
        html = (EXT / "newtab.html").read_text(encoding="utf-8")
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="vung-dau.js"', html)
        self.assertIn('href="the-lich.css"', html)
        # The weather lives on the calendar card (mockup H, 08/11), which the new tab's own module builds.
        self.assertIn('id="weather"', (EXT / "the-lich.js").read_text(encoding="utf-8"))
        self.assertIn("import { mountCalendarCard } from './the-lich.js';", (EXT / "vung-dau.js").read_text(encoding="utf-8"))
        for part in ('vung-dau.js', 'the-lich', 'id="weather"', 'id="web-search"', 'id="services"'):
            self.assertNotIn(part, site)

    def test_calendar_card_ships_its_pictures_and_fetches_nothing_new(self):
        # The twelve animals ship inside the extension with their licence (Fluent Emoji flat, MIT); the card names them
        # by relative path and calls no host beyond the new tab's existing ones.
        folder = EXT / "con-giap"
        names = ["rat", "water-buffalo", "tiger", "cat", "dragon", "snake", "horse", "goat", "monkey", "rooster", "dog", "pig"]
        self.assertEqual(sorted(p.stem for p in folder.glob("*.svg")), sorted(names))
        self.assertIn("MIT License", (folder / "LICENSE.txt").read_text(encoding="utf-8"))
        lunar = (EXT / "lich-am.js").read_text(encoding="utf-8")
        for name in names:
            self.assertIn(f"'{name}']", lunar)
        source = (EXT / "the-lich.js").read_text(encoding="utf-8") + (EXT / "the-lich.css").read_text(encoding="utf-8")
        self.assertIn("con-giap/${file}.svg", source)
        self.assertNotIn("http", source)        # no address of any host: the pictures are local, the weather is thoi-tiet.js
        self.assertNotIn("geolocation", source)

    def test_new_tab_has_the_captains_three_rows_above_the_news(self):
        # Captain, 07/11 18:03: row 1 the Google services with the 9 dots at the top right, row 2 the Google search with
        # the day line under it, row 3 a compact Halcyon bar (small logo, the sections, the magnifier), then the news.
        # 18:26, mockup D with three fixes: the wordmark alone (no "y" tile), a border and no shadow under the search,
        # and a Google search.
        html = (EXT / "newtab.html").read_text(encoding="utf-8")
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        head = html[html.index('id="masthead"'):html.index('</header>')]
        order = ['id="services"', 'class="tool-launcher"', 'id="web-search"']
        self.assertEqual([head.index(p) for p in order], sorted(head.index(p) for p in order))
        # 08/11 (mockup H): the day line under the search is gone; its date, lunar date and weather are on the card.
        for part in ('id="dateline"', 'id="day-date"', 'id="weather"'):
            self.assertNotIn(part, html)
        self.assertNotIn('class="brand-tag"', html)
        bar = html[html.index('id="bar"'):html.index('</nav>', html.index('id="bar"'))]
        for part in ('id="brand"', 'wordmark.svg', 'wordmark-dark.svg', 'id="feed-filters"', 'id="sort-switch"',
                     'id="ns-open"', 'class="ed-link"', 'id="theme-btn"'):
            self.assertIn(part, bar)
        self.assertNotIn('logo.svg"', bar.replace('wordmark', ''))  # no "y" tile beside the wordmark
        self.assertLess(bar.index('id="brand"'), bar.index('id="feed-filters"'))
        self.assertLess(html.index('</nav>', html.index('id="bar"')), html.index('id="picks"'))
        # The site home keeps its own masthead, tagline, sort line and no Google rows.
        self.assertIn('class="brand-tag"', site)
        self.assertIn('class="bar-tile"', site)
        for part in ('id="dateline"', 'id="services"', 'Tìm trên Google'):
            self.assertNotIn(part, site)
        css = (EXT / "newtab.css").read_text(encoding="utf-8")
        field = css[css.index('.web-field {'):css.index('#web-query {')]
        self.assertIn('box-shadow: none', field.split('}')[0])
        self.assertIn('.web-field:focus-within { border-color: var(--color-hair-strong); box-shadow: none;', field)
        source = (EXT / "vung-dau.js").read_text(encoding="utf-8")
        self.assertNotIn('day-date', source)


if __name__ == "__main__":
    unittest.main()

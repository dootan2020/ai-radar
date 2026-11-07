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
        self.assertEqual(manifest.get("permissions", []), ["storage", "alarms", "search"])
        self.assertEqual(manifest.get("host_permissions", []), ["https://radar-ai-vn.pages.dev/*"])
        self.assertNotIn("optional_permissions", manifest)

    def test_services_name_each_google_service(self):
        source = (EXT / "vung-dau.js").read_text(encoding="utf-8")
        for name in ("Gmail", "YouTube", "Drive", "Maps", "Lịch", "Dịch", "Gemini"):
            self.assertIn(f"['{name}', 'https://", source)
        self.assertIn('<span class="svc-name">${name}</span>', source)

    def test_new_tab_loads_the_top_zone_only_on_the_extension(self):
        html = (EXT / "newtab.html").read_text(encoding="utf-8")
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="vung-dau.js"', html)
        self.assertIn('id="weather"', html)
        for part in ('vung-dau.js', 'id="weather"', 'id="web-search"', 'id="services"'):
            self.assertNotIn(part, site)

    def test_new_tab_puts_the_date_in_the_masthead_and_one_row_under_it(self):
        # Captain, 07/11 17:12: the top zone gives its height back to the news. The date with the lunar date sits in the
        # masthead beside the wordmark; the search, the weather and the services share the row under it.
        html = (EXT / "newtab.html").read_text(encoding="utf-8")
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        masthead = html[html.index('id="masthead"'):html.index('</header>')]
        self.assertIn('id="dateline"', masthead)
        self.assertNotIn('id="dateline"', site)
        self.assertIn('class="brand-tag"', site)
        zone = html[html.index('id="top-zone"'):html.index('</section>', html.index('id="top-zone"'))]
        self.assertLess(zone.index('id="web-search"'), zone.index('id="weather"'))
        self.assertLess(zone.index('id="weather"'), zone.index('id="services"'))
        source = (EXT / "vung-dau.js").read_text(encoding="utf-8")
        self.assertIn('class="d-short" aria-hidden="true"', source)


if __name__ == "__main__":
    unittest.main()

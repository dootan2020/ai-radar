"""The "Sự kiện" view (#sap-toi), "Ba thì" (captain, 11/11 ~01:50: "A duyệt 3 thì"): live now, coming next, missed this
week. Drawn offline by tests/capture-ba-thi.mjs from the window fixture, the real NeurIPS rows (data/events.json) and
four streams shaped like the collector's (radar/youtube.py): one on air, one in 90 minutes, one ended two days ago, one
ended eight days ago."""
import json
import re
import subprocess
import unittest
from pathlib import Path

try:
    from test_bento_trang_nhat import browser_ready
except ImportError:
    from tests.test_bento_trang_nhat import browser_ready

ROOT = Path(__file__).resolve().parent.parent
SITE, EXT = ROOT / "site", ROOT / "extension"


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@unittest.skipUnless(browser_ready(), "Node, puppeteer and Chrome required")
class BaThi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", "tests/capture-ba-thi.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=300)
        cls.result = json.loads(out.stdout.strip().splitlines()[-1])
        cls.runs = cls.result["runs"]

    def test_no_script_error(self):
        errors = [e for e in self.result["errors"] if "Failed to load resource" not in e]
        self.assertEqual(errors, [])
        self.assertEqual(sorted(self.runs), ["song-1440", "song-1440-toi", "song-2000", "song-375", "trong-1440", "trong-375"])

    def test_the_three_tenses_render_from_the_snapshot(self):
        for key in ("song-1440", "song-1440-toi", "song-2000", "song-375"):
            page = self.runs[key]["page"]
            self.assertEqual(sorted(page["cards"]), ["bt-events", "bt-live", "bt-next", "bt-recent"], key)
            self.assertEqual(page["live"], ["AI cục bộ 301: Quantization"], key)
            self.assertEqual(page["next"], ["Stream cap-soon"], key)
            self.assertEqual(page["nextCount"], ["Còn 1 giờ 30 phút"], key)
            self.assertEqual(page["leadName"], ["NeurIPS 2026 — Sydney"], key)
            # The live tile is the page's one coral surface.
            self.assertEqual(page["coralSurfaces"], ["bt-live"], key)
            # Every stream picture shows its whole 16:9 frame inside its screen.
            self.assertTrue(page["screens"] and all(s["inside"] for s in page["screens"]), key)
            self.assertAlmostEqual(page["screens"][0]["w"] / page["screens"][0]["h"], 16 / 9, delta=0.02)

    def test_ended_streams_older_than_seven_days_are_left_out(self):
        for key in ("song-1440", "song-375"):
            self.assertEqual(self.runs[key]["page"]["recent"], ["Tương lai cơ sở hạ tầng AI"], key)

    def test_the_events_share_one_day_axis(self):
        page = self.runs["song-1440"]["page"]
        self.assertEqual(page["lanes"], ["NeurIPS 2026 — Sydney", "NeurIPS 2026 — Paris", "NeurIPS 2026 — Atlanta"])
        # Today is the first tick; Sydney's seven days start 24 days out, the satellites' five days four days later.
        self.assertEqual(page["ticks"], [{"all": 33, "on": 7, "first": 24}, {"all": 33, "on": 5, "first": 28},
                                         {"all": 33, "on": 5, "first": 28}])
        self.assertEqual(page["legend"], ["Hôm nay13.12"])
        # A phone shows the next event's own ruler and the other editions as plain rows, never link-blue.
        phone = self.runs["song-375"]["page"]
        self.assertEqual(phone["lanes"], [])
        self.assertEqual(phone["rows"], ["NeurIPS 2026 — Paris", "NeurIPS 2026 — Atlanta"])
        for key in ("song-1440", "song-375"):
            p = self.runs[key]["page"]
            self.assertTrue(p["rowLinkColors"] and set(p["rowLinkColors"]) == {p["ink"]}, key)

    def test_a_phone_stacks_live_next_events_then_replays(self):
        cards = self.runs["song-375"]["page"]["cards"]
        order = sorted(cards, key=lambda k: cards[k]["y"])
        self.assertEqual(order, ["bt-live", "bt-next", "bt-events", "bt-recent"])
        self.assertTrue(all(c["w"] == cards["bt-live"]["w"] for c in cards.values()))

    def test_a_lone_replay_leaves_no_half_card_empty(self):
        recent = self.runs["song-1440"]["page"]["cards"]["bt-recent"]
        self.assertLess(recent["emptiest"], recent["h"] / 8)

    def test_no_stream_is_one_calm_line(self):
        for key in ("trong-1440", "trong-375"):
            page = self.runs[key]["page"]
            self.assertEqual(page["calm"], [{"text": "Tuần này chưa có buổi phát nào.", "lines": 1}], key)
            self.assertEqual(sorted(page["cards"]), ["bt-events"], key)
            self.assertEqual(page["coralSurfaces"], [], key)

    def test_a_cold_load_of_the_address_fetches_the_complete_snapshot(self):
        for key, run in self.runs.items():
            self.assertIn("/data/radar-ui.json", run["requested"], key)

    def test_system_floors(self):
        for key, run in self.runs.items():
            page = run["page"]
            self.assertFalse(run["sideways"], key)
            self.assertGreaterEqual(page["minText"], 12, key)
            self.assertEqual(page["smallTargets"], [], key)
            # The page lives in the site's shell; the home's weather and calendar cards stay on the home.
            self.assertFalse(page["weather"], key)
            self.assertEqual(page["view"], "Sự kiện", key)


class Source(unittest.TestCase):
    def test_the_extension_carries_the_same_view(self):
        self.assertEqual(read(SITE / "trang-msn.css"), read(EXT / "trang-msn.css"))
        for folder in (SITE, EXT):
            feed = read(folder / "feed.js")
            self.assertIn("return [{ t: 'ba-thi' }, ...river.map(st => C(st))];", feed)
            self.assertNotIn("function renderLive(", feed)
        # The new tab cannot embed YouTube: its streams stay links that open YouTube.
        self.assertIn("const PLAYER_ON = false;", read(EXT / "feed.js"))

    def test_the_view_uses_tokens_not_new_pixel_values(self):
        css = read(SITE / "trang-msn.css")
        start = css.index('/* ---------- "Sự kiện" (#sap-toi): "Ba thì"')
        block = css[start:css.index("/* ---------- the models and code band", start)]
        # Breakpoints are the site's own media queries; a 0px custom property feeds calc().
        rules = re.sub(r"@media[^{]*", "", block)
        self.assertNotRegex(rules, r"(?<![\w-])(?!0px)\d+(\.\d+)?px")
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")


if __name__ == "__main__":
    unittest.main()

"""The front page's "Sắp diễn ra" card, "Hai mươi lăm" (captain, 10/11 ~21:05, choosing the mockup): the days left are
the card's one large thing, a day ruler under them, then the event as a quiet caption and the calendar buttons, the
Google one filled and naming Google. With more events the next two are a short schedule at its foot. The parts stack
the same way on a phone.
The ruler's arithmetic is site/time-text.js, run under Node; the drawn card is tests/capture-su-kien.mjs (offline)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from test_bento_trang_nhat import browser_ready
except ImportError:
    from tests.test_bento_trang_nhat import browser_ready

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (ROOT / "site", ROOT / "extension")
DAY = 86400000
HOUR = 3600000
START = 1796475600000  # 2026-12-05T13:00:00Z: 6 December in Sydney

HARNESS = """
import {{ rulerPlan, eventShort, RULER_MAX }} from {time_text};
const cases = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify({{
  max: RULER_MAX,
  plans: cases.plans.map(([start, end, now]) => rulerPlan(start, end, now, 'Australia/Sydney')),
  zoned: cases.zoned.map(([start, end, now, zone]) => rulerPlan(Date.parse(start), Date.parse(end), Date.parse(now), zone)),
  short: cases.short.map(([a, b]) => eventShort(a, b)),
}}));
"""


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def function(src, name):
    start = src.index(f"function {name}(")
    return src[start:src.index("\n}\n", start)]


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class Ruler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        week = START + 7 * DAY
        cases = {
            "plans": [
                [START, week, START - 25 * DAY - HOUR],          # 0: the mockup: 25 days, seven days long
                [START, week, START - 5 * HOUR],                 # 1: under one day
                [START, START + 4 * DAY, START - 130 * DAY],     # 2: 130 days away: weeks
                [START, START + 3 * DAY, START - 500 * DAY],     # 3: 500 days away: months
                [START, week, START + 2 * DAY + HOUR],           # 4: on its third day
                [START, START + DAY, START + HOUR],              # 5: a one-day event, today
                [START, week, week],                             # 6: over
                [None, week, START],                             # 7: no start
                [START, week, START - 53 * DAY],                 # 8: 53 + 7 = 60 ticks: still days
                [START, week, START - 54 * DAY],                 # 9: 61: weeks
            ],
            # Calendar days are counted in the event's own timezone, never as 24-hour blocks.
            "zoned": [
                # 0: New York springs forward on 8 March: its first day is 23 hours long; the next local midnight is day 2
                ["2026-03-08T05:00:00Z", "2026-03-11T04:00:00Z", "2026-03-09T04:00:00Z", "America/New_York"],
                # 1: New York falls back on 1 November: 24.5 hours in, it is still the first day (23:30 local)
                ["2026-11-01T04:00:00Z", "2026-11-04T05:00:00Z", "2026-11-02T04:30:00Z", "America/New_York"],
                # 2: exact hours, 14:00 on the 10th to 17:00 on the 12th: three calendar days, not 2.1 rounded to two
                ["2026-10-10T07:00:00Z", "2026-10-12T10:00:00Z", "2026-10-01T00:00:00Z", "Asia/Ho_Chi_Minh"],
                # 3: the same event at 09:00 on the 11th: its second day, though under 24 hours have passed
                ["2026-10-10T07:00:00Z", "2026-10-12T10:00:00Z", "2026-10-11T02:00:00Z", "Asia/Ho_Chi_Minh"],
                # 4: the week the clocks change is still seven days
                ["2026-03-06T05:00:00Z", "2026-03-13T04:00:00Z", "2026-03-01T05:00:00Z", "America/New_York"],
            ],
            "short": [["2026-12-06", "2026-12-12"], ["2026-11-30", "2026-12-02"], ["2026-10-16", "2026-10-16"],
                      ["2026-10-16", None], ["", None]],
        }
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(HARNESS.format(time_text=json.dumps((ROOT / "site" / "time-text.js").as_uri())),
                               encoding="utf-8", newline="\n")
            run = subprocess.run(["node", str(harness), json.dumps(cases)], cwd=ROOT, capture_output=True, text=True,
                                 encoding="utf-8", timeout=30)
        if run.returncode != 0:
            raise AssertionError(run.stdout + run.stderr)
        cls.out = json.loads(run.stdout)

    def test_one_tick_per_day_and_their_count_is_the_days_left(self):
        plan = self.out["plans"][0]
        self.assertEqual((plan["state"], plan["unit"], plan["days"], plan["before"], plan["event"]), ("soon", 1, 25, 25, 7))
        last_day = self.out["plans"][1]
        self.assertEqual((last_day["unit"], last_day["before"], last_day["event"]), (1, 1, 7))

    def test_a_long_wait_is_drawn_in_weeks_then_in_months(self):
        self.assertEqual(self.out["max"], 60)
        weeks, months, at_limit, past_limit = (self.out["plans"][i] for i in (2, 3, 8, 9))
        self.assertEqual((weeks["unit"], weeks["days"], weeks["before"], weeks["event"]), (7, 130, 19, 1))
        self.assertEqual((months["unit"], months["before"], months["event"]), (30, 17, 1))
        self.assertEqual((at_limit["unit"], at_limit["before"] + at_limit["event"]), (1, 60))
        self.assertEqual(past_limit["unit"], 7)
        for plan in (weeks, months, past_limit):
            self.assertLessEqual(plan["before"] + plan["event"], 60)

    def test_a_running_event_counts_its_own_days(self):
        on, today = self.out["plans"][4], self.out["plans"][5]
        self.assertEqual((on["state"], on["day"], on["span"], on["done"], on["event"], on["before"]), ("on", 3, 7, 2, 7, 0))
        self.assertEqual((today["state"], today["day"], today["span"], today["done"], today["event"]), ("on", 1, 1, 0, 1))

    def test_days_are_calendar_dates_in_the_events_timezone(self):
        spring, autumn, exact, exact_on, week = self.out["zoned"]
        self.assertEqual((spring["state"], spring["day"], spring["span"], spring["done"]), ("on", 2, 3, 1))
        self.assertEqual((autumn["state"], autumn["day"], autumn["span"], autumn["done"]), ("on", 1, 3, 0))
        self.assertEqual((exact["state"], exact["span"], exact["event"]), ("soon", 3, 3))
        self.assertEqual((exact_on["state"], exact_on["day"], exact_on["span"]), ("on", 2, 3))
        self.assertEqual((week["span"], week["event"], week["days"]), (7, 7, 5))

    def test_no_ruler_without_a_start_or_after_the_end(self):
        self.assertEqual(self.out["plans"][6:8], [None, None])

    def test_the_dates_at_the_rulers_end(self):
        self.assertEqual(self.out["short"], ["6–12.12", "30.11–2.12", "16.10", "16.10", ""])


class Card(unittest.TestCase):
    def test_the_google_button_names_google_in_vietnamese(self):
        for folder in FOLDERS:
            feed, css = read(folder / "feed.js"), read(folder / "trang-msn.css")
            buttons = function(feed, "calButtons")
            self.assertIn("""'<span><span class="calbtn-add">Thêm vào </span>Google Lịch</span>'""", buttons)
            self.assertIn("""aria-label="Thêm vào Google ${card ? 'Lịch' : 'Calendar'}\"""", buttons)
            self.assertIn("data-cal-ev=\"${esc(e.id)}\"`, e.title, true)}", function(feed, "renderNext"))
            self.assertIn(".msn-ev .calbtn-g { flex: 1; min-width: 0; background: var(--color-accent-fill); color: var(--color-on-accent); }", css)
            self.assertIn("@container (min-width: 17rem) { .msn-ev .calbtn-add { display: inline; } }", css)

    def test_the_parts_come_in_the_mockups_order(self):
        for folder in FOLDERS:
            nxt = function(read(folder / "feed.js"), "renderNext")
            order = [nxt.index(part) for part in ('class="ev-count cd', 'class="ev-ruler"', 'class="ev-link list-row"',
                                                  "${calButtons(eventCal(e)", "${evMoreHTML(rows)}")]
            self.assertEqual(order, sorted(order))
            self.assertIn('data-cd-kind="hero"', nxt)
            self.assertIn("const rows = it ? [] : events.slice(1, 1 + EV_ROWS);", nxt)
            self.assertIn("const EV_ROWS = 2;", read(folder / "feed.js"))

    def test_the_number_is_a_token_and_the_card_is_white(self):
        for folder in FOLDERS:
            tokens, css = read(folder / "tokens.css"), read(folder / "trang-msn.css")
            self.assertIn("--num-count: var(--size-112);", tokens)
            self.assertIn("--num-count-dense: var(--size-76);", tokens)
            self.assertIn(".ev-n { font-size: min(var(--num-count), 50cqi);", css)
            card = css[css.index(".band .msn-ev {"):]
            self.assertNotIn("background", card[:card.index("}")])

    def test_one_timer_drives_the_number_the_rows_and_the_ruler(self):
        for folder in FOLDERS:
            tick = function(read(folder / "feed.js"), "tickCountdowns")
            # A stream ("Sự kiện", "Sắp phát") has its own face and state past its hour; the events keep theirs.
            self.assertIn("const face = kind === 'hero' ? heroFace(p, plan) : kind === 'stream' ? streamFace(p) : rowFace(p);", tick)
            self.assertIn("rulerInner(plan, ruler.dataset.range, ruler.dataset.last)", tick)
            # The ruler counts days in the event's own timezone, at the first draw and on every tick.
            self.assertIn("rulerPlan(start, end, now, el.dataset.cdTz || TZ)", tick)
            nxt = function(read(folder / "feed.js"), "renderNext")
            self.assertIn("rulerPlan(start, end, now, zone)", nxt)
            self.assertIn('data-cd-tz="${esc(zone)}"', nxt)


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered card")
class RenderedCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "tests/capture-su-kien.mjs", "--only", "mot,ba,xa-130-ngay", "--widths", "1440,1024,375"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=240)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        out = json.loads(run.stdout.strip().splitlines()[-1])
        if out["errors"]:
            raise AssertionError(out["errors"])
        cls.runs = out["runs"]

    def test_one_event_is_the_mockup(self):
        card = self.runs["mot-1440"]["card"]
        self.assertEqual((card["number"], card["numberPx"], card["sr"]), ("25", 112, "Còn 25 ngày 1 giờ"))
        self.assertEqual((card["ticks"]["all"], card["ticks"]["now"], card["ticks"]["on"]), (32, 1, 7))
        self.assertEqual(card["legend"], "Hôm nay6–12.12")
        self.assertEqual((card["name"], card["meta"], card["note"]),
                         ("NeurIPS 2026 — Sydney", "6–12 tháng 12 · Sydney, Australia", "Chưa rõ giờ khai mạc"))
        self.assertEqual(card["bg"], "rgb(255, 255, 255)")
        self.assertFalse(card["dense"])

    def test_the_google_button_says_google_and_both_buttons_are_touch_sized(self):
        for name, run in self.runs.items():
            card = run["card"]
            self.assertIn("Google Lịch", card["google"]["text"], name)
            self.assertEqual(card["google"]["aria"], "Thêm vào Google Lịch", name)
            self.assertGreaterEqual(card["google"]["h"], 44, name)
            self.assertGreaterEqual(min(card["ics"]["w"], card["ics"]["h"]), 44, name)
        self.assertEqual(self.runs["mot-375"]["card"]["google"]["text"], "Thêm vào Google Lịch")

    def test_three_events_are_the_next_one_and_a_schedule_of_two(self):
        card = self.runs["ba-1440"]["card"]
        self.assertTrue(card["dense"])
        self.assertEqual(card["number"], "25")
        self.assertEqual([(r["t"], r["m"], r["d"]) for r in card["rows"]],
                         [("NeurIPS 2026 — Paris", "9–13 thg 12 · Paris", "28 ngày"),
                          ("NeurIPS 2026 — Atlanta", "9–13 thg 12 · Atlanta", "28 ngày")])
        self.assertEqual(card["order"], [".ev-head", ".ev-count", ".ev-ruler", ".ev-link", ".calbtn", ".ev-more"])
        self.assertIsNone(card["all"])
        for name in ("ba-1440", "ba-1024", "ba-375"):
            self.assertTrue(all(r["h"] >= 44 for r in self.runs[name]["card"]["rows"]), name)

    def test_a_phone_stacks_the_parts_as_the_desktop_does(self):
        for name in ("mot-375", "ba-375"):
            card = self.runs[name]["card"]
            self.assertEqual(card["order"][:5], [".ev-head", ".ev-count", ".ev-ruler", ".ev-link", ".calbtn"], name)
            count, link, buttons = card["lefts"]
            self.assertEqual(link, buttons, name)
            self.assertLessEqual(abs(count - link), 1, name)
            self.assertEqual(card["numberPx"], 112, name)
            self.assertEqual(card["note"], "Chưa rõ giờ khai mạc", name)

    def test_a_far_event_gets_a_weekly_ruler_that_says_so(self):
        for name in ("xa-130-ngay-1440", "xa-130-ngay-1024"):
            card = self.runs[name]["card"]
            self.assertEqual((card["number"], card["ticks"]["all"], card["ticks"]["on"]), ("130", 20, 1), name)
            self.assertTrue(card["legend"].startswith("Mỗi vạch 1 tuần"), name)

    def test_nothing_overflows_and_the_band_stays_level(self):
        for name, run in self.runs.items():
            card = run["card"]
            self.assertFalse(run["sideways"], name)
            self.assertEqual(card["pastY"], 0, name)
            self.assertLessEqual(card["pastX"], 6, name)   # the number's optical inset, inside the card's padding
            self.assertGreaterEqual(card["minText"], 12, name)
            for target in card["targets"]:
                self.assertGreaterEqual(target["h"], 44, f"{name} {target['cls']}")
            if not name.endswith("-375"):
                for row in run["band"]["rows"]:
                    self.assertEqual({cell["h"] for cell in row}, {384}, name)


if __name__ == "__main__":
    unittest.main()

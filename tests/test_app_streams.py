"""Offline checks for how the v2 page words YouTube fallback times.

The page must never turn a relative age or a timezone-free schedule into an exact instant:
- a relative-only ended stream reads "Đã phát N <đơn vị> trước";
- a YouTube schedule without a timezone keeps the printed date and clock and says "chưa rõ múi giờ";
- a date-only event exported to a calendar stays an all-day event, with no invented midnight;
- a malformed date never reaches the calendar file, and URL stays an unescaped URI (RFC 5545 3.3.13).

The wording lives in site/time-text.js and site/calendar.js, pure ES modules that Node runs
without a DOM. The last test checks that site/app.js really renders through those helpers.
"""

from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

HARNESS = """
import {{ streamedAge, scheduleText }} from {time_text};
import {{ canCalendar, buildIcs }} from {calendar};
const input = JSON.parse(process.argv[2]);
const out = {{
  aged: input.aged.map(t => streamedAge(t)),
  scheduled: input.scheduled.map(t => scheduleText(t)),
  canCal: input.canCal.map(e => canCalendar(e)),
  ics: buildIcs(input.ics),
  urlIcs: buildIcs(input.urlIcs),
  badBuild: input.bad.map(e => {{ try {{ buildIcs(e); return 'built'; }} catch (err) {{ return err.name; }} }}),
}};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class StreamTimeWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {
            "aged": [
                "Streamed 1d ago", "Streamed 2 hours ago", "Streamed 23h ago", "Streamed 1 minute ago",
                "Streamed 30s ago", "Streamed recently", "Streamed 99999999999999999h ago", "", None,
            ],
            "scheduled": ["Scheduled for 10/5/26, 9:00 PM", "Scheduled for Oct 6, 7:30 AM", "Premieres soon", None],
            "canCal": [
                {"title": "No date"},
                {"title": "Date only", "startDate": "2026-10-16"},
                {"title": "Exact", "startAt": "2026-10-16T09:00:00Z"},
                {"title": "Bad", "startAt": "not a time"},
                {"title": "Malformed end date", "startDate": "2026-10-16", "endDate": "TBD"},
                {"title": "End date with a clock", "startDate": "2026-10-16", "endDate": "2026-10-16T18:00:00Z"},
                {"title": "Impossible date", "startDate": "2026-02-31"},
                {"title": "End before start", "startDate": "2026-10-16", "endDate": "2026-10-15"},
                {"title": "Malformed end instant", "startAt": "2026-10-16T09:00:00Z", "endAt": "soon"},
                {"title": "Good range", "startDate": "2026-12-06", "endDate": "2026-12-12"},
            ],
            "ics": {"uid": "ev-1", "title": "NeurIPS 2026, Sydney", "url": "https://nips.cc/",
                    "location": "Sydney, Australia", "startDate": "2026-12-06", "endDate": "2026-12-12"},
            "urlIcs": {"uid": "ev-2", "title": "Session", "startDate": "2026-10-16",
                       "url": "https://events.example.com/?session=1,2;lang=vi"},
            "bad": [
                {"uid": "b1", "title": "x", "startDate": "2026-10-16", "endDate": "TBD"},
                {"uid": "b2", "title": "x", "startAt": "2026-10-16T09:00:00Z", "endAt": "soon"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(HARNESS.format(
                time_text=json.dumps((SITE / "time-text.js").as_uri()),
                calendar=json.dumps((SITE / "calendar.js").as_uri()),
            ), encoding="utf-8", newline="\n")
            result = subprocess.run(
                ["node", str(harness), json.dumps(cls.cases)], cwd=ROOT,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout)

    def test_relative_only_time_reads_as_vietnamese_age(self):
        self.assertEqual(self.out["aged"][:5], [
            "Đã phát 1 ngày trước", "Đã phát 2 giờ trước", "Đã phát 23 giờ trước",
            "Đã phát 1 phút trước", "Đã phát 30 giây trước",
        ])

    def test_unparseable_or_unsafe_age_is_not_invented(self):
        self.assertEqual(self.out["aged"][5:], [None, None, None, None])

    def test_timezone_free_schedule_keeps_printed_clock(self):
        self.assertEqual(self.out["scheduled"][0], "Dự kiến: 10/5/26, 9:00 chiều (chưa rõ múi giờ)")
        self.assertEqual(self.out["scheduled"][1], "Dự kiến: Oct 6, 7:30 sáng (chưa rõ múi giờ)")
        self.assertEqual(self.out["scheduled"][2:], ["chưa rõ giờ", "chưa rõ giờ"])

    def test_calendar_needs_a_verified_date(self):
        self.assertEqual(self.out["canCal"], [False, True, True, False, False, False, False, False, False, True])

    def test_malformed_dates_are_refused_before_any_date_maths(self):
        # buildIcs used to throw an unhandled RangeError from Date#toISOString on these.
        self.assertEqual(self.out["badBuild"], ["Error", "Error"])

    def test_url_is_a_uri_value_without_text_escaping(self):
        lines = self.out["urlIcs"].split("\r\n")
        self.assertIn("URL:https://events.example.com/?session=1,2;lang=vi", lines)

    def test_date_only_event_stays_all_day(self):
        ics = self.out["ics"]
        self.assertIn("DTSTART;VALUE=DATE:20261206", ics)
        self.assertIn("DTEND;VALUE=DATE:20261213", ics)
        self.assertNotIn("T000000", ics)
        self.assertIn("SUMMARY:NeurIPS 2026\\, Sydney", ics)
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n")))

    def test_page_renders_through_these_helpers(self):
        app = (SITE / "app.js").read_text(encoding="utf-8")
        self.assertRegex(app, r"import \{ streamedAge, scheduleText[\w, ]*\} from './time-text\.js';")
        self.assertIn("streamedAge(lastEnded.c.time_text)", app)
        self.assertIn("scheduleText(v.time_text)", app)
        # The page must not keep a private copy that could drift from the tested one.
        self.assertNotIn("function streamedAge", app)
        self.assertNotIn("function scheduleText", app)


if __name__ == "__main__":
    unittest.main()

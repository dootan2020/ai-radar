"""A "Tin khác" sheet's dateline names the days it covers (coordinator, 15/11 22:3x: on live the first sheet read
"Hôm nay · 13/11 00:00 – 00:30", the day word of the newest story in front of the oldest story's date, so a reader took
13/11 to be today). Within one day: the day's name and the hours. Across days: each end with its own day. Under an
older day's heading: the hours only. site/time-text.js sheetSpan, run under Node."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HARNESS = """
const t = await import({time_text});
const at = s => Date.parse(s);
const now = at('2026-11-15T15:30:00Z');   // 22:30 on 15/11 in Vietnam
console.log(JSON.stringify({{
  sameDay: t.sheetSpan(at('2026-11-15T01:00:00Z'), at('2026-11-15T05:00:00Z'), 'Hôm nay', now),
  sameDayHoursOnly: t.sheetSpan(at('2026-11-13T02:32:00Z'), at('2026-11-13T11:48:00Z'), '', now),
  oneStory: t.sheetSpan(at('2026-11-15T01:00:00Z'), at('2026-11-15T01:00:00Z'), 'Hôm nay', now),
  crossToToday: t.sheetSpan(at('2026-11-12T17:00:00Z'), at('2026-11-14T17:30:00Z'), 'Hôm nay', now),
  crossYesterday: t.sheetSpan(at('2026-11-13T08:20:00Z'), at('2026-11-13T23:24:00Z'), 'Hôm qua', now),
  crossUnderHeading: t.sheetSpan(at('2026-11-12T16:30:00Z'), at('2026-11-12T17:10:00Z'), '', now),
}}));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class SheetDateline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for folder in ("site", "extension"):
            with tempfile.TemporaryDirectory() as tmp:
                harness = Path(tmp) / "harness.mjs"
                harness.write_text(HARNESS.format(time_text=json.dumps((ROOT / folder / "time-text.js").as_uri())),
                                   encoding="utf-8", newline="\n")
                run = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True, text=True,
                                     encoding="utf-8", timeout=30)
            if run.returncode != 0:
                raise AssertionError(run.stdout + run.stderr)
            cls.out[folder] = json.loads(run.stdout)

    def test_a_sheet_within_one_day_keeps_its_day_and_hours(self):
        for folder, out in self.out.items():
            self.assertEqual(out["sameDay"], "Hôm nay · 08:00 – 12:00", folder)
            self.assertEqual(out["oneStory"], "Hôm nay · 08:00", folder)

    def test_under_an_older_day_heading_only_the_hours_show(self):
        for folder, out in self.out.items():
            self.assertEqual(out["sameDayHoursOnly"], "09:32 – 18:48", folder)

    def test_a_sheet_across_days_names_each_end_with_its_own_day(self):
        for folder, out in self.out.items():
            self.assertEqual(out["crossToToday"], "13/11 00:00 – Hôm nay 00:30", folder)
            self.assertEqual(out["crossYesterday"], "13/11 15:20 – Hôm qua 06:24", folder)
            # A day heading's own stories never cross midnight, but if they did the line still names both days.
            self.assertEqual(out["crossUnderHeading"], "12/11 23:30 – 13/11 00:10", folder)

    def test_the_feed_takes_its_dateline_from_sheet_span(self):
        for folder in ("site", "extension"):
            feed = (ROOT / folder / "feed.js").read_text(encoding="utf-8")
            start = feed.index("function datelineOf(")
            body = feed[start:feed.index("\n}\n", start)]
            self.assertIn("return sheetSpan(lo, hi, s.key ? '' : dayLabel(dayKey(new Date(hi))));", body)


if __name__ == "__main__":
    unittest.main()

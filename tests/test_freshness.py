"""Offline checks for the stale-data line and the event date wording.

site/freshness.js decides when the snapshot is old enough to say so (three hours, six missed 30-minute runs) or when
too many sources failed at build time; site/time-text.js words an event's verified dates. Both are pure ES modules
that Node runs without a DOM.
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
import {{ freshness, freshnessText, STALE_AFTER_H, OUTAGE_SHARE }} from {freshness};
import {{ eventRange }} from {time_text};
const NOW = Date.parse('2026-10-03T10:00:00Z');   // 17:00 in Vietnam
const ok = n => Array.from({{length: n}}, (_, i) => ({{id: 's' + i, ok: true}}));
const bad = n => Array.from({{length: n}}, (_, i) => ({{id: 'b' + i, ok: false}}));
const paused = n => Array.from({{length: n}}, (_, i) => ({{id: 'p' + i, ok: false, disabled: true}}));
const at = h => new Date(NOW - h * 36e5).toISOString();
const run = (gen, sources) => {{ const f = freshness(gen, sources, NOW); return {{f, text: freshnessText(f, gen, NOW)}}; }};
const out = {{
  limits: [STALE_AFTER_H, OUTAGE_SHARE],
  fresh: run(at(1), ok(10)),
  justUnder: run(at(2.9), ok(10)),
  atLimit: run(at(3), ok(10)),
  old: run('2026-10-03T02:00:00Z', ok(10)),
  days: run('2026-10-01T02:00:00Z', ok(10)),
  outage: run(at(1), [...ok(7), ...bad(3)]),
  pausedOnly: run(at(1), [...ok(8), ...bad(1), ...paused(3)]),
  oldAndOutage: run(at(5), [...ok(5), ...bad(5)]),
  unknown: run('', ok(3)),
  garbage: run('not a time', ok(3)),
  noSources: run(at(1), undefined),
  ranges: [
    eventRange('2026-10-16', '2026-10-16'), eventRange('2026-10-16', null), eventRange('2026-12-06', '2026-12-12'),
    eventRange('2026-11-30', '2026-12-02'), eventRange('2026-12-30', '2027-01-02'), eventRange('TBD', null),
    eventRange('', ''), eventRange('2026-10-16', 'soon'),
  ],
}};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class FreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(HARNESS.format(freshness=json.dumps((SITE / "freshness.js").as_uri()),
                                              time_text=json.dumps((SITE / "time-text.js").as_uri())),
                               encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True, text=True,
                                    encoding="utf-8", timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout)

    def test_limits(self):
        self.assertEqual(self.out["limits"], [3, 0.2])

    def test_fresh_snapshot_says_nothing(self):
        for case in ("fresh", "justUnder", "pausedOnly", "noSources"):
            self.assertEqual(self.out[case]["text"], "", case)
        self.assertFalse(self.out["fresh"]["f"]["old"])

    def test_three_hours_is_old(self):
        self.assertTrue(self.out["atLimit"]["f"]["old"])
        self.assertIn("có thể đã cũ", self.out["atLimit"]["text"])

    def test_old_snapshot_names_its_build_time_in_vietnam(self):
        text = self.out["old"]["text"]
        self.assertTrue(text.startswith("Bản tin chưa cập nhật từ 09:00 ngày 3/10 (8 giờ trước)."), text)
        self.assertIn("Trang thường cập nhật mỗi 30 phút", text)
        self.assertIn("ngày 1/10", self.out["days"]["text"])

    def test_outage_counts_only_active_sources(self):
        self.assertTrue(self.out["outage"]["f"]["outage"])
        self.assertIn("3 trên 10 nguồn không đọc được", self.out["outage"]["text"])
        paused = self.out["pausedOnly"]["f"]
        self.assertEqual((paused["failed"], paused["active"], paused["outage"]), (1, 9, False))

    def test_old_and_outage_say_both(self):
        text = self.out["oldAndOutage"]["text"]
        self.assertIn("có thể đã cũ", text)
        self.assertIn("5 trên 10 nguồn", text)

    def test_missing_or_broken_time_is_said_not_guessed(self):
        for case in ("unknown", "garbage"):
            self.assertTrue(self.out[case]["f"]["unknown"], case)
            self.assertEqual(self.out[case]["text"], "Bản tin này không ghi giờ tạo, nên chưa biết số liệu mới hay cũ.")

    def test_event_ranges(self):
        self.assertEqual(self.out["ranges"], [
            "16 tháng 10", "16 tháng 10", "6–12 tháng 12", "30 tháng 11 – 2 tháng 12",
            "30 tháng 12 – 2 tháng 1 năm 2027", "TBD", "chưa rõ ngày", "16 tháng 10",
        ])


if __name__ == "__main__":
    unittest.main()

"""The "Mới" label lasts six hours: unread and published within NEW_MARK_HOURS, whatever the reader's last visit.

The real isNew / storyStatus / markSeen from site/feed.js and extension/feed.js run in Node against small doubles.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = [ROOT / "site", ROOT / "extension"]


def pick(feed, pattern, what):
    match = re.search(pattern, feed, re.M)
    if not match:
        raise AssertionError(f"Missing in feed.js: {what}")
    return match.group()


def harness(feed):
    parts = [
        pick(feed, r"^const NEW_MARK_HOURS = [^\n]*;", "NEW_MARK_HOURS") if "const NEW_MARK_HOURS" in feed else "",
        pick(feed, r"^const isNew = [\s\S]*?;$", "isNew"),
        pick(feed, r"^function storyStatus\([^\n]*\) \{[\s\S]*?^\}", "storyStatus"),
        pick(feed, r"^function markSeen\(\) \{[\s\S]*?^\}", "markSeen"),
    ]
    return r"""
const NOW = Date.parse('2026-11-14T09:00:00Z');
Date.now = () => NOW;
const ms = iso => new Date(iso).getTime() || 0;
const hoursAgo = h => new Date(NOW - h * 36e5).toISOString();
const K = { lastSeen: 'air2:lastSeen', seenAll: 'air2:seenAll' };
const stored = {};
const store = { get: (k, d) => (k in stored ? stored[k] : d), set: (k, v) => { stored[k] = v; } };
let D = { generated_at: hoursAgo(0.5) };
// The reader visited one hour ago (the old rule's "last look"); nothing was marked seen.
let lastSeen = hoursAgo(1), firstVisit = false, seenAll = null;
let read = new Set(), skipped = new Set(), arrived = new Set(), freshIds = [];
const $$ = () => [], paintStatus = () => {}, toast = () => {};
""" + "\n".join(parts) + r"""
const story = (id, h) => ({ id, published_at: hoursAgo(h) });
const out = {};
out.twoHoursAfterVisit = storyStatus('a', story('a', 2));
out.sevenHours = storyStatus('b', story('b', 7));
out.exactlySixHours = storyStatus('c', story('c', 6));
out.futureDated = storyStatus('f', { id: 'f', published_at: new Date(NOW + 36e5).toISOString() });
read.add('d');
out.opened = storyStatus('d', story('d', 2));
arrived.add('e');
out.arrivedOld = storyStatus('e', story('e', 9));
out.noPublishedAt = storyStatus('g', { id: 'g' });
markSeen();
out.afterMarkSeen = storyStatus('a', story('a', 2));
out.afterMarkSeenFresh = storyStatus('h', { id: 'h', published_at: new Date(NOW + 1000).toISOString() });
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required")
class NewMarkWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for folder in FOLDERS:
            feed = (folder / "feed.js").read_text(encoding="utf-8")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "nhan-moi.mjs"
                path.write_text(harness(feed), encoding="utf-8", newline="\n")
                result = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.out[folder.name] = json.loads(result.stdout)

    def test_unread_story_two_hours_old_is_new_even_after_a_visit_one_hour_ago(self):
        for name, out in self.out.items():
            self.assertEqual(out["twoHoursAfterVisit"], "new", name)

    def test_story_past_the_window_is_not_new(self):
        for name, out in self.out.items():
            self.assertEqual(out["sevenHours"], "none", name)
            self.assertEqual(out["exactlySixHours"], "new", name)
            self.assertEqual(out["futureDated"], "none", name)
            self.assertEqual(out["noPublishedAt"], "none", name)

    def test_opened_story_is_seen_not_new_and_arrivals_stay_new(self):
        for name, out in self.out.items():
            self.assertEqual(out["opened"], "seen", name)
            self.assertEqual(out["arrivedOld"], "new", name)

    def test_mark_seen_clears_every_label(self):
        for name, out in self.out.items():
            self.assertEqual(out["afterMarkSeen"], "none", name)

    def test_window_is_one_named_constant(self):
        for folder in FOLDERS:
            feed = (folder / "feed.js").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"^const NEW_MARK_HOURS = 6;", feed, re.M)), 1, folder.name)
            self.assertNotIn("commitLastSeen", feed, folder.name)

    def test_css_shows_the_chip_even_when_every_row_is_new(self):
        for folder in FOLDERS:
            css = (folder / "trang-msn.css").read_text(encoding="utf-8")
            self.assertNotIn(".fresh-list:has(", css, folder.name)
            self.assertIn(".fresh-list > li:is([data-status=\"new\"], [data-pinned]):not(.is-read) .fresh-new {", css, folder.name)


if __name__ == "__main__":
    unittest.main()
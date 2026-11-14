"""The home feed's two-step data load: the window file first, the complete snapshot after it.

The real loading functions from site/feed.js run in Node against small doubles, so a missing window file, an older
complete file or a deep link cannot leave the reader without stories or with a feed drawn twice.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FEED = (ROOT / "site" / "feed.js").read_text(encoding="utf-8")


def declaration(name):
    match = re.search(r"^(?:async )?function " + name + r"\([^\n]*\) \{[\s\S]*?^\}", FEED, re.M)
    if not match:
        raise AssertionError(f"Missing function in site/feed.js: {name}")
    return match.group()


HARNESS = r"""
const calls = [], drawn = [];
let files = {};
let D = null, STORY_ANY = new Map(), filter = 'all';
let complete = false, completeLoad = null;
const WINDOW_URL = 'data/radar-window.json';
const SECTIONS = { 'sap-toi': {} };
const location = { hash: '' };
const console = { warn: () => {} };
async function fetchJSON(url, init = {}) {
  calls.push([url, init.priority || null]);
  if (!(url in files)) throw new Error('HTTP 404');
  return files[url];
}
async function loadData(init = {}) {
  for (const url of ['data/radar-ui.json', 'data/radar.json']) {
    try { return await fetchJSON(url, init); } catch {}
  }
  throw new Error('no data');
}
function ingest(data) { D = data; STORY_ANY = new Map(data.stories.map(s => [s.id, s])); }
function mergeFieldRepos() { drawn.push('repos'); }
const renderAll = () => drawn.push('all'), renderFeed = () => drawn.push('feed'), renderChips = () => drawn.push('chips');
const appendOlder = () => drawn.push('older');
""" + "\n".join(declaration(name) for name in ("loadFirst", "loadComplete", "adoptComplete", "needsComplete")) + r"""
const snap = (at, ids) => ({ schema_version: 2, generated_at: at, stories: ids.map(id => ({ id })) });
function reset(f, hash = '', view = 'all') {
  files = f; calls.length = 0; drawn.length = 0; D = null; STORY_ANY = new Map(); filter = view;
  complete = false; completeLoad = null; location.hash = hash;
}
async function boot() { const data = await loadFirst(); ingest(data); return data; }
const out = {};

reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) });
await boot();
out.windowFirst = { calls: calls.slice(), stories: D.stories.length, complete };
await loadComplete();
out.adoptSame = { calls: calls.slice(), stories: D.stories.length, drawn: drawn.slice(), complete };

reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) }, '', 'sec:sap-toi');
await boot(); await loadComplete();
out.sectionRedrawn = drawn.slice();

reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T2', ['b']) });
await boot(); await loadComplete();
out.newer = { drawn: drawn.slice(), at: D.generated_at };

reset({ 'data/radar-window.json': snap('T2', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) });
await boot(); await loadComplete();
out.older = { stories: D.stories.length, complete, drawn: drawn.slice() };
files['data/radar-ui.json'] = snap('T2', ['a', 'old']);
await loadComplete();
out.olderRetried = { stories: D.stories.length, complete };

reset({ 'data/radar-ui.json': snap('T1', ['a', 'old']) });
await boot();
out.missingWindow = { calls: calls.slice(), stories: D.stories.length, complete };
const before = calls.length;
await loadComplete();
out.missingWindowNoSecondLoad = calls.length - before;

reset({ 'data/radar-window.json': { broken: true }, 'data/radar-ui.json': snap('T1', ['a', 'old']) });
await boot();
out.invalidWindow = { stories: D.stories.length, complete };

for (const hash of ['#sap-toi', '#da-luu', '#tin/old']) {
  reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) }, hash);
  await boot();
  out['deep' + hash] = { calls: calls.map(c => c[0]), complete };
}
reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) }, '#top');
await boot();
out.plainHash = complete;
location.hash = '#tin/old';
out.laterStoryOutside = needsComplete();
location.hash = '#tin/a';
out.laterStoryInside = needsComplete();
location.hash = '#hom-nay';
out.retiredSection = needsComplete();
location.hash = '#%E0%A4%A';
out.badHash = needsComplete();

process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for feed loading tests")
class FeedFirstLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed-first-load.mjs"
            path.write_text(HARNESS, encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def test_window_file_draws_first_and_complete_follows_at_low_priority(self):
        self.assertEqual(self.out["windowFirst"], {"calls": [["data/radar-window.json", None]], "stories": 1,
                                                   "complete": False})
        same = self.out["adoptSame"]
        self.assertEqual(same["calls"][-1], ["data/radar-ui.json", "low"])
        self.assertEqual(same["stories"], 2)
        self.assertTrue(same["complete"])
        # The same snapshot leaves the drawn feed and the reader's "new" baseline as they were; only the older days
        # join the end of the stream.
        self.assertEqual(same["drawn"], ["repos", "chips", "older"])

    def test_views_outside_the_window_and_newer_snapshots_are_redrawn(self):
        self.assertEqual(self.out["sectionRedrawn"], ["repos", "feed"])
        self.assertEqual(self.out["newer"], {"drawn": ["repos", "all"], "at": "T2"})

    def test_older_complete_snapshot_is_dropped_and_retried(self):
        self.assertEqual(self.out["older"], {"stories": 1, "complete": False, "drawn": []})
        self.assertEqual(self.out["olderRetried"], {"stories": 2, "complete": True})

    def test_missing_or_invalid_window_file_falls_back_to_the_complete_snapshot(self):
        missing = self.out["missingWindow"]
        self.assertEqual([c[0] for c in missing["calls"]], ["data/radar-window.json", "data/radar-ui.json"])
        self.assertEqual((missing["stories"], missing["complete"]), (2, True))
        self.assertEqual(self.out["missingWindowNoSecondLoad"], 0)
        self.assertEqual(self.out["invalidWindow"], {"stories": 2, "complete": True})

    def test_deep_links_open_on_the_complete_snapshot(self):
        for hash in ("#sap-toi", "#da-luu", "#tin/old"):
            self.assertEqual(self.out["deep" + hash], {"calls": ["data/radar-ui.json"], "complete": True}, hash)
        self.assertFalse(self.out["plainHash"])
        self.assertTrue(self.out["laterStoryOutside"])
        self.assertFalse(self.out["laterStoryInside"])
        self.assertFalse(self.out["badHash"])
        # A retired section's address (#hom-nay) opens the home feed, which needs no complete snapshot first.
        self.assertFalse(self.out["retiredSection"])

    def test_home_page_preloads_only_the_window_file(self):
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<link rel="preload" href="(data/[^"]+)" as="fetch" crossorigin>', html),
                         ["data/radar-window.json"])
        self.assertIn("const WINDOW_URL = customData ? null : 'data/radar-window.json';", FEED)


OLDER_HARNESS = r"""
const TZ = 'Asia/Ho_Chi_Minh';
const DAY = new Intl.DateTimeFormat('en-CA', { timeZone: TZ });
const dayKey = d => DAY.format(d);
const ms = iso => new Date(iso).getTime() || 0;
const rankTime = st => ms(st.latest_coverage_at || st.published_at);
const asArray = v => Array.isArray(v) ? v : [];
const C = (st, size = '', opts = {}) => ({ t: 'card', st, size, opts });
let complete = false, PLACED = new Set(), D = null;
""" + "\n".join(re.search(r"^const " + name + r" = [^\n]+;", FEED, re.M).group() for name in ("WEEKDAY", "pubTime")) + "\n" + \
    "\n".join(declaration(name) for name in ("dayLabel", "olderItems")) + r"""
const at = days => new Date(Date.now() - days * 864e5).toISOString();
D = { stories: [
  { id: 'ranked', published_at: at(0) },
  { id: 'three', published_at: at(3) }, { id: 'five-b', published_at: at(5) },
  { id: 'five-a', published_at: new Date(Date.now() - 5 * 864e5 + 3600e3).toISOString() }, { id: 'four', published_at: at(4) },
] };
const out = {};
out.beforeComplete = olderItems();
complete = true; PLACED = new Set(['ranked']);
const items = olderItems();
out.items = items.map(x => x.t === 'day' ? 'day:' + x.key : x.st.id + (x.older ? '' : ':ranked'));
out.again = olderItems().length;
out.labels = [dayLabel(dayKey(new Date())), dayLabel(dayKey(new Date(Date.now() - 864e5))), dayLabel('2026-11-07')];
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for feed loading tests")
class OlderDaysTests(unittest.TestCase):
    """Captain, 09/11 13:16: past the ranked window the stream goes on into the older days, newest first, one quiet line
    per day, every story once."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "older-days.mjs"
            path.write_text(OLDER_HARNESS, encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def test_older_days_wait_for_the_complete_snapshot(self):
        self.assertEqual(self.out["beforeComplete"], [])

    def test_every_other_story_once_newest_first_under_its_day(self):
        items = self.out["items"]
        self.assertEqual([x for x in items if not x.startswith("day:")], ["three", "four", "five-a", "five-b"])
        days = [x for x in items if x.startswith("day:")]
        self.assertEqual(len(days), len(set(days)), "one line per day")
        self.assertEqual(len(days), 3)
        self.assertTrue(items[0].startswith("day:"))
        self.assertEqual(self.out["again"], 0, "a story already placed is never added twice")

    def test_day_lines_read_today_yesterday_then_weekday_and_date(self):
        self.assertEqual(self.out["labels"][:2], ["Hôm nay", "Hôm qua"])
        self.assertEqual(self.out["labels"][2], "Thứ Bảy 7/11")

    def test_retired_sections_and_end_card_are_gone(self):
        self.assertIn("const SECTIONS = {\n  'sap-toi':", FEED.replace("\r\n", "\n"))
        for retired in ("'hom-nay'", "'chuyen-gia'", "'cong-dong'", "'nong'"):
            self.assertIn(retired, re.search(r"const RETIRED_VIEWS = new Set\(\[([^\]]+)\]\)", FEED).group(1))
        for gone in ("end-card", "Bạn đã xem hết", "data-to-top", "big: st =>", "forum: st =>"):
            self.assertNotIn(gone, FEED)


if __name__ == "__main__":
    unittest.main()

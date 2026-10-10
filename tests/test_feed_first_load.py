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
let D = null, STORY_ANY = new Map(), filter = 'all', lastSeen = 'mark', firstVisit = false;
let complete = false, completeLoad = null;
const WINDOW_URL = 'data/radar-window.json';
const SECTIONS = { model: {}, 'sap-toi': {} };
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
function ingest(data) { D = data; STORY_ANY = new Map(data.stories.map(s => [s.id, s])); lastSeen = 'reset'; firstVisit = true; }
function mergeFieldRepos() { drawn.push('repos'); }
const renderAll = () => drawn.push('all'), renderFeed = () => drawn.push('feed'), renderChips = () => drawn.push('chips');
""" + "\n".join(declaration(name) for name in ("loadFirst", "loadComplete", "adoptComplete", "needsComplete")) + r"""
const snap = (at, ids) => ({ schema_version: 2, generated_at: at, stories: ids.map(id => ({ id })) });
function reset(f, hash = '', view = 'all') {
  files = f; calls.length = 0; drawn.length = 0; D = null; STORY_ANY = new Map(); filter = view;
  complete = false; completeLoad = null; lastSeen = 'mark'; firstVisit = false; location.hash = hash;
}
async function boot() { const data = await loadFirst(); ingest(data); lastSeen = 'mark'; firstVisit = false; return data; }
const out = {};

reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) });
await boot();
out.windowFirst = { calls: calls.slice(), stories: D.stories.length, complete };
await loadComplete();
out.adoptSame = { calls: calls.slice(), stories: D.stories.length, drawn: drawn.slice(), complete, lastSeen, firstVisit };

reset({ 'data/radar-window.json': snap('T1', ['a']), 'data/radar-ui.json': snap('T1', ['a', 'old']) }, '', 'sec:model');
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

for (const hash of ['#model', '#da-luu', '#tin/old']) {
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
        # The same snapshot leaves the drawn feed and the reader's "new" baseline as they were.
        self.assertEqual(same["drawn"], ["repos", "chips"])
        self.assertEqual((same["lastSeen"], same["firstVisit"]), ("mark", False))

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
        for hash in ("#model", "#da-luu", "#tin/old"):
            self.assertEqual(self.out["deep" + hash], {"calls": ["data/radar-ui.json"], "complete": True}, hash)
        self.assertFalse(self.out["plainHash"])
        self.assertTrue(self.out["laterStoryOutside"])
        self.assertFalse(self.out["laterStoryInside"])
        self.assertFalse(self.out["badHash"])

    def test_home_page_preloads_only_the_window_file(self):
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<link rel="preload" href="(data/[^"]+)" as="fetch" crossorigin>', html),
                         ["data/radar-window.json"])
        self.assertIn("const WINDOW_URL = customData ? null : 'data/radar-window.json';", FEED)


if __name__ == "__main__":
    unittest.main()

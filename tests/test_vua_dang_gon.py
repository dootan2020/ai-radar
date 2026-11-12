"""The "Vừa đăng" tile stays short (captain, 12/11 09:23: "danh sách tin vừa đăng nó dài quá"). After the "N tin mới"
pill it had drawn the whole pinned batch, seven rows each marked "Mới"; a newsroom catching up can land fifty at once.
The tile now holds at most FRESH_TILE_ROWS rows whatever the batch, the same rows the river leaves out, so the rest of
a batch keeps its place below and every story is on the page once."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (ROOT / "site", ROOT / "extension")

HARNESS = """
import {{ readFileSync }} from 'node:fs';
const src = readFileSync({feed}, 'utf8');
const grab = re => {{ const m = src.match(re); if (!m) throw new Error('missing ' + re); return m[0]; }};
const code = [
  grab(/const ms = [^\\n]*/),
  grab(/const rankTime = [^\\n]*/),
  grab(/const byNew = [^\\n]*/),
  grab(/const pubTime = [^\\n]*/),
  grab(/const NEWEST = [^\\n]*/),
  grab(/const FRESH_TILE_ROWS = [^\\n]*/),
  grab(/const byPub = [^\\n]*/),
  grab(/function newestStories\\(\\) \\{{[\\s\\S]*?\\r?\\n\\}}\\r?\\n/),
  grab(/function freshItem\\(st\\) \\{{[\\s\\S]*?\\r?\\n\\}}\\r?\\n/),
  grab(/function freshInnerHTML\\(\\) \\{{[\\s\\S]*?\\r?\\n\\}}\\r?\\n/),
].join('\\n');
const GEN = Date.parse('2026-11-12T02:30:00Z');
const mk = (id, minutesAgo) => ({{ id, published_at: new Date(GEN - minutesAgo * 6e4).toISOString(), latest_coverage_at: null }});
const stubs = {{
  D: {{}}, filter: 'all', GEN, FRONT_IDS: new Set(), read: new Set(),
  titleOf: st => ({{ text: st.id }}), esc: s => String(s), hhmm: d => d.toISOString().slice(11, 16), exact: s => s,
  langAttr: () => '', markHTML: () => '', statusClass: () => '', storyStatus: () => 'new',
}};
const run = (stories, freshIds) => {{
  const env = {{ ...stubs, allStories: stories, freshIds, STORY_ANY: new Map(stories.map(s => [s.id, s])) }};
  const html = new Function(...Object.keys(env), code + '; return freshInnerHTML();')(...Object.values(env));
  return {{ ids: [...html.matchAll(/<li [^>]*data-sid="([^"]+)"/g)].map(m => m[1]),
    pinned: [...html.matchAll(/<li [^>]*data-pinned/g)].length, n: (html.match(/data-n="(\\d+)"/) || [])[1] || null,
    pager: /fresh-pager|data-fresh-page/.test(html) }};
}};
// A newsroom catching up: fifty stories in the last fifty minutes, all announced by the pill and pinned.
const burst = Array.from({{ length: 50 }}, (_, i) => mk('b' + i, i + 1));
// A quiet morning: two stories in the last six hours, so the tile reaches back a day for more.
const quiet = [mk('q0', 30), mk('q1', 200), mk('q2', 600), mk('q3', 900), mk('q4', 1300)];
process.stdout.write(JSON.stringify({{
  burst: run(burst, burst.map(s => s.id)),
  burstUnpinned: run(burst, []),
  quiet: run(quiet, []),
  // A pinned batch of seven, as on the captain's screen at 09:23.
  seven: run(quiet.concat([mk('s0', 10), mk('s1', 20), mk('s2', 40), mk('s3', 70), mk('s4', 90), mk('s5', 120), mk('s6', 150)]),
    ['s0', 's1', 's2', 's3', 's4', 's5', 's6']),
}}));
"""


@unittest.skipUnless(shutil.which("node"), "Node required")
class VuaDangStaysShort(unittest.TestCase):
    def run_harness(self, folder):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harness.mjs"
            path.write_text(HARNESS.format(feed=json.dumps(str(folder / "feed.js"))), encoding="utf-8", newline="\n")
            res = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_a_burst_of_fifty_shows_the_four_newest_and_no_pager(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            for case in ("burst", "burstUnpinned"):
                self.assertEqual(out[case]["ids"], ["b0", "b1", "b2", "b3"], (folder.name, case))
                self.assertEqual(out[case]["n"], "4", (folder.name, case))
                self.assertFalse(out[case]["pager"], (folder.name, case))
            self.assertEqual(out["burst"]["pinned"], 4, folder.name)

    def test_a_pinned_batch_of_seven_no_longer_stretches_the_tile(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            self.assertEqual(out["seven"]["ids"], ["s0", "s1", "s2", "s3"], folder.name)
            self.assertEqual(out["seven"]["pinned"], 4, folder.name)

    def test_a_quiet_morning_still_fills_the_tile_newest_first(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            self.assertEqual(out["quiet"]["ids"], ["q0", "q1", "q2", "q3"], folder.name)

    def test_the_tile_and_the_river_share_one_cut(self):
        for folder in FOLDERS:
            feed = (folder / "feed.js").read_text(encoding="utf-8")
            build = feed[feed.index("function buildFront() {"):]
            build = build[:build.index("\n}\n")]
            self.assertIn("newestStories().list.slice(0, FRESH_TILE_ROWS)", build)
            inner = feed[feed.index("function freshInnerHTML() {"):]
            inner = inner[:inner.index("\n}\n")]
            self.assertIn("const shown = list.slice(0, FRESH_TILE_ROWS);", inner)
            self.assertRegex(feed, re.compile(r"^const FRESH_TILE_ROWS = 4;$", re.M))


if __name__ == "__main__":
    unittest.main()

"""The "Vừa đăng" tile stays bounded and scrolls to the rest (captain, 12/11 09:23: "danh sách tin vừa đăng nó dài
quá"; 13/11: "làm cuộn, xóa pagination"; "trên mobile ... không cuộn xem thêm được"). It now holds up to NEWEST.cap
rows — the pinned "N tin mới" batch leads (its newest FRESH_TILE_ROWS), then the newest of the rest — with no pager:
a newsroom catching up with fifty arrivals leaves the tile the same bounded height, and the list scrolls (CSS) to the
rows past the fold. The tile and the river still share one cut, so every story is on the page once."""
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
    pager: /fresh-pager|data-fresh-page/.test(html),
    cap: (code.match(/cap:\\s*(\\d+)/) || [])[1] || null }};
}};
// A newsroom catching up: fifty stories in the last fifty minutes, all announced by the pill and pinned.
const burst = Array.from({{ length: 50 }}, (_, i) => mk('b' + i, i + 1));
// A quiet morning: five stories, two within six hours so the tile reaches back a day for the rest.
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
class VuaDangStaysBounded(unittest.TestCase):
    def run_harness(self, folder):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harness.mjs"
            path.write_text(HARNESS.format(feed=json.dumps(str(folder / "feed.js"))), encoding="utf-8", newline="\n")
            res = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_a_burst_of_fifty_is_bounded_to_cap_newest_first_no_pager(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            cap = int(out["burst"]["cap"])
            for case in ("burst", "burstUnpinned"):
                self.assertEqual(out[case]["ids"], [f"b{i}" for i in range(cap)], (folder.name, case))
                self.assertEqual(out[case]["n"], str(cap), (folder.name, case))
                self.assertFalse(out[case]["pager"], (folder.name, case))
            # The whole announced batch that is shown keeps its "Mới" mark; an unannounced tile shows none.
            self.assertEqual(out["burst"]["pinned"], cap, folder.name)
            self.assertEqual(out["burstUnpinned"]["pinned"], 0, folder.name)

    def test_a_pinned_batch_of_seven_leads_the_tile_without_stretching_it(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            cap = int(out["seven"]["cap"])
            # The four newest pinned rows lead; the tile is still bounded to the cap, with no pager.
            self.assertEqual(out["seven"]["ids"][:4], ["s0", "s1", "s2", "s3"], folder.name)
            self.assertEqual(len(out["seven"]["ids"]), cap, folder.name)
            self.assertFalse(out["seven"]["pager"], folder.name)

    def test_a_quiet_morning_fills_the_tile_newest_first(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            # Fewer stories than the cap: every one shows, newest first, no pager.
            self.assertEqual(out["quiet"]["ids"], ["q0", "q1", "q2", "q3", "q4"], folder.name)
            self.assertFalse(out["quiet"]["pager"], folder.name)

    def test_the_tile_and_the_river_share_one_cut(self):
        for folder in FOLDERS:
            feed = (folder / "feed.js").read_text(encoding="utf-8")
            build = feed[feed.index("function buildFront() {"):]
            build = build[:build.index("\n}\n")]
            # The river leaves out every row the tile holds (the whole list), not a sliced four.
            self.assertIn("newestStories().list", build)
            self.assertNotIn("newestStories().list.slice(0, FRESH_TILE_ROWS)", build)
            inner = feed[feed.index("function freshInnerHTML() {"):]
            inner = inner[:inner.index("\n}\n")]
            self.assertIn("const shown = list;", inner)
            self.assertNotIn("fresh-pager", inner)
            self.assertRegex(feed, re.compile(r"^const FRESH_TILE_ROWS = 4;$", re.M))


if __name__ == "__main__":
    unittest.main()

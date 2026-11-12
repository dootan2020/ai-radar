"""The "Vừa đăng" tile lists stories newest-published first, because each row prints its published_at (captain, 12/11
08:36). A story with later coverage but an older publication must not be lifted above a newer one (rankTime)."""
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
  grab(/const byPub = [^\\n]*/),
  grab(/function newestStories\\(\\) \\{{[\\s\\S]*?\\r?\\n\\}}\\r?\\n/),
].join('\\n');
const mk = (id, pub, cov) => ({{ id, published_at: pub, latest_coverage_at: cov }});
const GEN = Date.parse('2026-11-11T18:30:00Z');
const run = (stories, freshIds) => new Function('allStories', 'GEN', 'FRONT_IDS', 'freshIds', 'read', 'STORY_ANY',
  code + '; return newestStories().list.map(s => s.id);')(stories, GEN, new Set(), freshIds, new Set(),
  new Map(stories.map(s => [s.id, s])));
// TSMC published 14:30 VN, covered again at 18:16Z: it must not jump above the stories published after it.
const stories = [
  mk('tsmc', '2026-11-11T07:30:21Z', '2026-11-11T18:16:40Z'),
  mk('b', '2026-11-11T14:50:00Z', null),
  mk('c', '2026-11-11T16:00:00Z', '2026-11-11T16:05:00Z'),
  mk('d', '2026-11-11T17:00:00Z', null),
  mk('e', '2026-11-11T12:00:00Z', null),
];
process.stdout.write(JSON.stringify({{ plain: run(stories, []), pinned: run(stories, ['tsmc', 'b', 'd']) }}));
"""


@unittest.skipUnless(shutil.which("node"), "Node required")
class VuaDangOrder(unittest.TestCase):
    def run_harness(self, folder):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harness.mjs"
            path.write_text(HARNESS.format(feed=json.dumps(str(folder / "feed.js"))), encoding="utf-8", newline="\n")
            res = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_rows_read_newest_published_first_despite_later_coverage(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            self.assertEqual(out["plain"], ["d", "c", "b", "e", "tsmc"], folder.name)

    def test_pinned_batch_is_also_ordered_by_publication(self):
        for folder in FOLDERS:
            out = self.run_harness(folder)
            self.assertEqual(out["pinned"], ["d", "b", "tsmc", "c", "e"], folder.name)


if __name__ == "__main__":
    unittest.main()

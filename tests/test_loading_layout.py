"""Loading visibility wiring; rendered CLS is measured separately in Chrome.

Exercise the real board/error renderers with a small DOM double so an empty snapshot
or failed fetch cannot leave the page hidden behind its loading state.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def function_source(name):
    source = (SITE / "app.js").read_text(encoding="utf-8")
    match = re.search(r"^function " + re.escape(name) + r"\([^\n]*\)\{[\s\S]*?^\}", source, re.M)
    if not match:
        raise AssertionError(f"Missing renderer: {name}")
    return match.group()


class LoadingLayoutTests(unittest.TestCase):
    def test_loading_retains_geometry_and_accessible_status(self):
        css = (SITE / "styles.css").read_text(encoding="utf-8")
        board = re.search(r"\.board\.is-loading\s*\{([^}]+)\}", css)
        self.assertIsNotNone(board)
        self.assertRegex(board.group(1), r"visibility\s*:\s*hidden")
        self.assertNotRegex(board.group(1), r"display\s*:\s*none")
        self.assertRegex(css, r"\.board\.is-loading\s*>\s*\.sr\s*\{\s*visibility\s*:\s*visible\s*\}")

    def test_reduced_motion_board_clears_visibility_transition(self):
        css = (SITE / "styles.css").read_text(encoding="utf-8")
        # Under reduced motion every element gets a 150 ms "all" transition; the board must not
        # transition visibility from is-loading to avoid a 2s compositor stall on mobile.
        self.assertIn(".board, .board *{transition-property:none !important}", css)

    @unittest.skipUnless(shutil.which("node"), "Node required for renderer behavior tests")
    def test_success_empty_and_error_reveal_their_content(self):
        harness = r"""
let board, retry, D, arriveIdx, reloads = 0;
const $ = selector => selector === '#board' ? board : retry;
const avatar = () => '', esc = s => String(s), exact = s => s;
const pickLead = () => ({st: D.stories[0]});
const leadTile = () => '<div class="tile t-lead">Story</div>';
const liveTile = () => '<div class="tile t-live">Live</div>';
const repoTile = () => '', hotTile = () => '', newTile = () => '';
const listenTile = () => '', modelTile = () => '', sourcesTile = () => '';
const hydrateVisible = () => {};
const location = {reload: () => reloads++};
function reset(stories){
  D = {stories, generated_at: '2026-10-03T09:18:01Z'};
  const classes = new Set(['board', 'is-loading']);
  const attributes = new Set(['aria-busy']);
  const fallback = '<div class="reader-fallback" role="status">Đang mở bản tin</div>';
  board = {innerHTML: fallback, classList: {remove: c => classes.delete(c)},
    querySelector: () => board.innerHTML.includes(fallback) ? {outerHTML:fallback, remove:()=>{board.innerHTML=board.innerHTML.replace(fallback,'');}} : null,
    removeAttribute: a => attributes.delete(a), classes, attributes};
  retry = {addEventListener: (event, handler) => {retry[event] = handler;}};
}
function state(){
  return {loading: board.classes.has('is-loading'), busy: board.attributes.has('aria-busy'), html: board.innerHTML};
}
""" + function_source("revealBoard") + "\n" + function_source("renderBoard") + "\n" + function_source("showError") + r"""
const out = {};
reset([{id: 'story'}]); renderBoard(); out.success = state();
reset([{id: 'story'}]); out.rest = renderBoard(true); out.split = state();
reset([{id: 'story'}]); renderBoard(false, false); out.pendingFonts = state();
revealBoard(); out.fontsSettled = state();
reset([]); renderBoard(false, false); out.emptyPending = state(); revealBoard(); out.emptySettled = state();
reset([]); renderBoard(); out.empty = state();
reset([]); showError('Request failed'); out.error = state(); retry.click(); out.reloads = reloads;
process.stdout.write(JSON.stringify(out));
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loading-renderers.mjs"
            path.write_text(harness, encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(path)], cwd=ROOT, capture_output=True,
                                    text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        for case in ("success", "split", "empty", "error", "fontsSettled", "emptySettled"):
            self.assertFalse(out[case]["loading"], case)
            self.assertFalse(out[case]["busy"], case)
            self.assertTrue(out[case]["html"], case)
            self.assertNotIn('reader-fallback', out[case]["html"], case)
        self.assertIn('t-live', out['success']['html'])
        self.assertNotIn('t-live', out['split']['html'])
        self.assertIn('t-live', out['rest'])
        for case in ('pendingFonts', 'emptyPending'):
            self.assertTrue(out[case]['loading'])
            self.assertTrue(out[case]['busy'])
            self.assertIn('class="reader-fallback" role="status"', out[case]['html'])
        self.assertIn('t-live', out['pendingFonts']['html'])
        self.assertIn('Bản tin này chưa có tin nào', out['empty']['html'])
        self.assertIn('role="alert"', out['error']['html'])
        self.assertIn('Request failed', out['error']['html'])
        self.assertEqual(out['reloads'], 1)


if __name__ == "__main__":
    unittest.main()

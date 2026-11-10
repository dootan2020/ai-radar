"""The front page paints its first screen without waiting for whole stylesheets or for files the first screen does not
draw (captain, 11/11 01:03: "Sửa ngay đi e"; Lighthouse 13.5 mobile on hco.news after the lead picture shipped with the
page: FCP 2.5-3.3 s under five blocking stylesheets, 1.36-1.43 MB on first load).

Kept in place here: the inline first-screen CSS equals what radar/critical_css.py derives from the stylesheets; no
stylesheet in the front page's head blocks render; the field rankings never gate the first draw; the Hugging Face papers
list (175 KB) waits for the reader and asks at low priority. Card pictures are checked in test_hieu_nang.py."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from radar import critical_css

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class InlineCriticalCss(unittest.TestCase):
    def test_the_inline_block_equals_its_stylesheets(self):
        self.assertTrue(critical_css.update(SITE / "index.html", check=True),
                        "site/index.html's critical css differs from its stylesheets: run python -m radar.critical_css")

    def test_a_changed_stylesheet_makes_the_check_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            for name in ("index.html", *critical_css.SHEETS):
                shutil.copyfile(SITE / name, site / name)
            self.assertTrue(critical_css.update(site / "index.html", check=True))
            with open(site / "trang-msn.css", "a", encoding="utf-8") as f:
                f.write("\n.msn-grid { outline: 1px solid red; }\n")
            self.assertFalse(critical_css.update(site / "index.html", check=True))
            critical_css.update(site / "index.html")
            self.assertTrue(critical_css.update(site / "index.html", check=True))
            self.assertIn(".msn-grid{outline: 1px solid red;}", read(site / "index.html"))

    def test_the_block_holds_the_first_screen_and_leaves_script_drawn_rules_out(self):
        style = re.search(r"<style>\n(.*?)\n</style>", read(SITE / "index.html"), re.S).group(1)
        for needed in (":root{", "@font-face{", ".msn-grid", ".msn-lead", ".slide-media", ".media-img", ".msn-sk",
                       ".newsbar", ".masthead", ".tool-launcher", ".reader-fallback"):
            self.assertIn(needed, style)
        # Drawn by scripts after the complete files apply (stylesReady): not needed before the first paint.
        for later in (".nc-title{", ".wx-days", ".slide-title{"):
            self.assertNotIn(later, style)
        # A dark-mode reader gets the dark tokens before any file arrives.
        self.assertIn('[data-theme="dark"]', style)

    def test_selector_filter(self):
        names = {".a", ".b", "#x"}
        self.assertTrue(critical_css.selector_matches(".a .b:hover", names))
        self.assertTrue(critical_css.selector_matches("html[data-theme=\"dark\"] .a", names))
        self.assertTrue(critical_css.selector_matches(".a:not(.zzz)", names))
        self.assertTrue(critical_css.selector_matches("body", names))
        self.assertFalse(critical_css.selector_matches(".a .zzz", names))
        self.assertFalse(critical_css.selector_matches("#y", names))
        css = "@media (min-width: 768px){.a{color:red}.zzz{color:blue}}.zzz,.b{margin:0}@keyframes k{from{opacity:0}}"
        self.assertEqual(critical_css.filter_css(css, names),
                         "@media (min-width: 768px){.a{color:red}}.b{margin:0}@keyframes k{from{opacity:0}}")


class NoRenderBlockingStylesheet(unittest.TestCase):
    def test_the_front_page_head_links_no_stylesheet(self):
        html = read(SITE / "index.html")
        head = html[:html.index("</head>")]
        self.assertNotIn('rel="stylesheet"', head)
        for sheet in critical_css.SHEETS:
            self.assertEqual(head.count(f'<link rel="preload" href="{sheet}" as="style">'), 1, sheet)
        # The policy is not widened for the inline block: inline styles were already admitted for per-card values.
        csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', head).group(1)
        self.assertIn("style-src 'self' 'unsafe-inline';", csp)
        self.assertNotIn("nonce-", csp)

    def test_drawing_waits_for_the_complete_files(self):
        nap = read(SITE / "nap-kieu.js")
        self.assertIn("link[rel=\"preload\"][as=\"style\"]", nap)
        self.assertIn("link.rel = 'stylesheet';", nap)
        feed = read(SITE / "feed.js")
        self.assertIn("import { stylesReady } from './nap-kieu.js';", feed)
        self.assertIn("await Promise.all([loadImages(), loadFirst(), loadPicks(), stylesReady]);", feed)
        top = read(SITE / "thanh-tren.js")
        self.assertIn("stylesReady.then(startTopRow);", top)

    def test_the_new_tab_keeps_plain_stylesheets_and_no_baked_lead(self):
        tab = read(EXT / "newtab.html")
        self.assertNotIn("critical css", tab)
        self.assertNotIn("<style>", tab)
        self.assertNotIn('as="style"', tab)
        for sheet in critical_css.SHEETS:
            self.assertIn(f'<link rel="stylesheet" href="{sheet}">', tab)
        self.assertNotIn('rel="preload" as="image"', tab)
        self.assertTrue((EXT / "nap-kieu.js").is_file())


class RankingsNeverGateTheFirstPaint(unittest.TestCase):
    def test_the_first_draw_does_not_wait_for_the_field_rankings(self):
        feed = read(SITE / "feed.js")
        init = feed[feed.index("async function init() {"):]
        init = init[:init.index("\n}\n")]
        first = init[:init.index("renderAll();")]
        self.assertNotIn("loadFieldRankings", first)
        self.assertIn("(filter === 'code' ? Promise.resolve() : whenIdle()).then(loadFieldRankings).then(applyFieldRankings);", init)
        self.assertIn("fetchJSON(FIELD_RANKINGS_URL, { priority: 'low' })", feed)
        apply = feed[feed.index("function applyFieldRankings(fieldData) {"):]
        self.assertIn("rerenderRepos();", apply[:apply.index("\n}\n")])

    def test_the_first_screen_s_lists_do_not_come_from_the_field_rankings(self):
        # The trending lists the repositories tile draws are ids in the snapshot's own repos_meta.rankings, looked up in
        # the snapshot's repos; the field rankings only add the work-area pools.
        feed = read(SITE / "feed.js")
        self.assertIn("const rankedList = (rk, view, second) => asArray(view === 'stars' ? rk[second] : (rk[view] || {})[second]).map(id => REPO.get(String(id))).filter(Boolean);", feed)
        self.assertIn("function rankings() { const rk = D.repos_meta && D.repos_meta.rankings;", feed)


LIVE_HARNESS = r"""
const calls = [];
globalThis.document = { hidden: false, addEventListener() {} };
globalThis.setInterval = () => 0; globalThis.clearInterval = () => {};
globalThis.fetch = async (url, init) => { calls.push({ url: String(url), priority: init && init.priority });
  return { ok: true, json: async () => (String(url).includes('daily_papers') ? [{ paper: { id: '2611.00001', upvotes: 9 }, numComments: 2 }] : String(url).includes('algolia') ? { hits: [] } : []) }; };
const { startLive } = await import(process.argv[2]);
let open; const gate = new Promise(r => { open = r; });
const updates = [];
startLive({ getStories: () => [{ coverage: [{ id: 'c1', source: 'hf-papers', url: 'https://huggingface.co/papers/2611.00001', metrics: { upvotes: 1 } },
  { id: 'c2', url: 'https://x.org', discussion_url: 'https://news.ycombinator.com/item?id=1', metrics: { points: 1 } }] }],
  onUpdates: u => updates.push(...u), onStatus: () => {}, later: { 'hf-papers': gate } });
await new Promise(r => setTimeout(r, 30));
const before = calls.map(c => c.url);
open();
await new Promise(r => setTimeout(r, 30));
process.stdout.write(JSON.stringify({ before, after: calls, updates: updates.map(u => [u.cov.id, u.metric, u.value]) }));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for the live layer test")
class HuggingFaceWaits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "live.mjs"
            harness.write_text(LIVE_HARNESS, encoding="utf-8", newline="\n")
            url = (SITE / "live.js").resolve().as_uri()
            run = subprocess.run(["node", str(harness), url], capture_output=True, text=True, encoding="utf-8", timeout=60)
        if run.returncode != 0:
            raise AssertionError(run.stderr)
        cls.got = json.loads(run.stdout)

    def test_the_papers_list_is_not_asked_for_until_its_gate_opens(self):
        self.assertFalse(any("daily_papers" in u for u in self.got["before"]), self.got["before"])
        self.assertTrue(any("hn.algolia.com" in u for u in self.got["before"]))
        self.assertTrue(any("daily_papers" in c["url"] for c in self.got["after"]))
        self.assertIn(["c1", "upvotes", 9], self.got["updates"])

    def test_every_live_request_is_low_priority(self):
        self.assertTrue(self.got["after"])
        self.assertTrue(all(c["priority"] == "low" for c in self.got["after"]), self.got["after"])

    def test_the_site_gates_the_papers_on_the_reader(self):
        feed = read(SITE / "feed.js")
        self.assertIn("later: { 'hf-papers': whenReaderActs() },", feed)


if __name__ == "__main__":
    unittest.main()

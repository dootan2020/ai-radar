"""The news bar's inline search (site/tim-tin.js) and the retired search page's redirect (site/tra-cuu.html).

Captain, 07/11 13:15: "chuyển nút tìm kiếm tin vào ngay tại navbar mà không làm trang riêng nữa. bỏ trang tìm kiếm
riêng." Results appear as the reader types, without accents, from data/radar-search.json; old links to tra-cuu.html
land on the home with the search open and the query filled.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from radar.search_index import normalize_vietnamese
from tests.test_vietnamese_ui import foreign_words, visible_html, js_literals, UI_KEYS, UI_SINKS, VIET_MARKS

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
EXT = ROOT / "extension"
FIXTURE = ROOT / "tests" / "fixtures" / "radar-search.json"


def node(script, *args):
    run = subprocess.run(["node", "--input-type=module", "-e", script, *map(str, args)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node required for the search module")
class InlineSearchTests(unittest.TestCase):
    def test_fold_matches_the_index_normalizer(self):
        samples = ["Trí tuệ nhân tạo", "Định giá IPO của Anthropic", "GPT-6.1 và Đà Nẵng", "Kimi K3.1 Pro", "ĐỒNG HỒ"]
        script = r"""
import { fold } from '%s';
process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map(fold)));
""" % (SITE / "tim-tin.js").as_uri()
        self.assertEqual(node(script, json.dumps(samples)), [normalize_vietnamese(s) for s in samples])

    def test_unaccented_words_find_accented_headlines_in_the_real_index(self):
        script = r"""
import { readFileSync } from 'node:fs';
import { toRow, matchRows, highlight } from '%s';
const j = JSON.parse(readFileSync(process.argv[1], 'utf8'));
const rows = j.stories.map(s => toRow(s));
const out = {};
for (const q of ['tri tue nhan tao', 'Trí tuệ nhân tạo', 'deepseek', 'openai', 'khong co tu nay xyzzy']) {
  const m = matchRows(rows, q);
  out[q] = { total: m.total, strong: m.strong.length, newestFirst: m.strong.every((r, i, a) => !i || a[i - 1].at >= r.at),
             allMatch: [...m.strong, ...m.weak].every(r => m.words.every(w => r.text.includes(w))) };
}
out.empty = matchRows(rows, '   ');
out.mark = highlight('Định giá IPO', ['dinh', 'ipo']);
process.stdout.write(JSON.stringify(out));
""" % (SITE / "tim-tin.js").as_uri()
        out = node(script, FIXTURE)
        # Without accents finds exactly what the accented query finds.
        self.assertEqual(out["tri tue nhan tao"]["total"], out["Trí tuệ nhân tạo"]["total"])
        for q in ("tri tue nhan tao", "deepseek", "openai"):
            with self.subTest(q=q):
                self.assertGreater(out[q]["total"], 0)
                self.assertTrue(out[q]["newestFirst"])
                self.assertTrue(out[q]["allMatch"])
        self.assertEqual(out["khong co tu nay xyzzy"]["total"], 0)
        self.assertIsNone(out["empty"])
        self.assertEqual(out["mark"], "<mark>Định</mark> giá <mark>IPO</mark>")

    def test_results_group_by_day_and_open_the_story_view(self):
        source = (SITE / "tim-tin.js").read_text(encoding="utf-8")
        self.assertIn("if (days === 1) return 'Hôm qua';", source)
        self.assertIn("const SEARCH_URL = 'data/radar-search.json';", source)
        self.assertIn("if (onOpenStory(a.dataset.nsId, a)) { e.preventDefault(); hide(); }", source)
        # Offline (the new tab without network), the stories on the page are searched instead of nothing.
        self.assertIn("rows = getStories().map(", source)
        # The index loads on the first focus, not with the page.
        self.assertIn("input.addEventListener('focus', () => { load();", source)

    def test_closing_the_search_keeps_keyboard_focus(self):
        # Escape on an empty field (or the clear button) collapses the search. Focus goes back to the button that opened
        # it when that button is on screen (phone), otherwise it stays in the field; it never falls to the page body.
        script = r"""
import { createNewsSearch } from '%s';
globalThis.fetch = async () => { throw new Error('offline'); };
const body = { id: 'body' };
const doc = { activeElement: body, getElementById: id => id === 'ns-status' ? status : null, querySelector: () => null, addEventListener() {} };
globalThis.document = doc;
const classes = () => { const s = new Set(); return { add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
  toggle: (c, on) => (on ? s.add(c) : s.delete(c)) }; };
function el(id, shown = true) {
  const e = { id, hidden: false, value: '', attrs: {}, on: {}, classList: classes(),
    addEventListener(type, fn) { (this.on[type] = this.on[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = v; }, focus() { doc.activeElement = this; }, select() {},
    blur() { if (doc.activeElement === this) doc.activeElement = body; },
    getClientRects: () => shown ? [{}] : [], querySelectorAll: () => [], contains: () => false };
  return e;
}
const status = el('ns-status');
const key = (root, k) => { for (const fn of root.on.keydown || []) fn({ key: k, preventDefault() {}, stopPropagation() {} }); };
const out = {};
for (const buttonShown of [true, false]) {
  const parts = { '#ns-q': el('ns-q'), '#ns-results': el('ns-results'), '#ns-open': el('ns-open', buttonShown), '#ns-clear': el('ns-clear') };
  parts['#ns-results'].hidden = true;
  const root = el('news-search');
  root.querySelector = sel => parts[sel];
  const search = createNewsSearch({ root, getStories: () => [] });
  search.open();
  key(root, 'Escape');
  out[`escape-${buttonShown}`] = [doc.activeElement.id, root.classList.contains('open')];
  search.open();
  for (const fn of parts['#ns-clear'].on.click) fn({});
  out[`clear-${buttonShown}`] = [doc.activeElement.id, root.classList.contains('open')];
}
process.stdout.write(JSON.stringify(out));
""" % (SITE / "tim-tin.js").as_uri()
        self.assertEqual(node(script), {
            "escape-true": ["ns-open", False], "clear-true": ["ns-open", False],
            "escape-false": ["ns-q", False], "clear-false": ["ns-q", False],
        })

    def test_search_ui_is_vietnamese(self):
        leftovers = {}
        for literal, before in js_literals((SITE / "tim-tin.js").read_text(encoding="utf-8")):
            if "<" in literal and ">" in literal:
                for t in visible_html(literal):
                    if foreign_words(t):
                        leftovers[t] = foreign_words(t)
            elif VIET_MARKS.search(literal) or UI_KEYS.search(before) or UI_SINKS.search(before):
                if foreign_words(literal):
                    leftovers[literal] = foreign_words(literal)
        self.assertEqual(leftovers, {})


class SearchEntryPointTests(unittest.TestCase):
    def test_home_has_the_inline_search_and_the_shortcut_opens_it(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        feed = (SITE / "feed.js").read_text(encoding="utf-8")
        self.assertIn('role="combobox" aria-expanded="false" aria-controls="ns-results"', html)
        self.assertIn('aria-keyshortcuts="/"', html)
        self.assertIn("else if (k === '/') { e.preventDefault(); if (newsSearch) newsSearch.open(); }", feed)
        # ?q= (from the old page) and #tim (from other pages) open the search with the query, then the address is cleaned.
        self.assertIn("const q = url.searchParams.get('q');", feed)
        self.assertIn("if (location.hash === '#tim') { openSearchFromAddress(); return; }", feed)
        self.assertIn("openSearchFromAddress();\n  arenaView = createArenaView", feed.replace("\r\n", "\n"))

    def test_the_old_search_page_is_gone_everywhere(self):
        self.assertFalse((SITE / "tra-cuu.js").exists())
        self.assertFalse((SITE / "tra-cuu.css").exists())
        hits = []
        for folder in (SITE, EXT, ROOT / "radar"):
            for path in folder.rglob("*"):
                if path.suffix not in {".html", ".js", ".css", ".py"} or path.name == "tra-cuu.html" or "data" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    if "tra-cuu" in line and not line.lstrip().startswith(("/*", "//", "#", "*")):
                        hits.append(f"{path.relative_to(ROOT).as_posix()}: {line.strip()[:80]}")
        self.assertEqual(hits, [])


class RedirectPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SITE / "tra-cuu.html").read_text(encoding="utf-8")

    def test_one_inline_script_allowed_by_its_hash_and_no_index(self):
        scripts = re.findall(r"<script>([\s\S]*?)</script>", self.html)
        self.assertEqual(len(scripts), 1)
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"script-src 'sha256-{digest}'", self.html)
        self.assertIn('<meta name="robots" content="noindex">', self.html)
        self.assertIn('<meta http-equiv="refresh" content="0; url=./#tim">', self.html)
        self.assertNotIn("<script src", self.html)

    @unittest.skipUnless(shutil.which("node"), "Node required to run the redirect")
    def test_old_links_land_on_the_home_with_the_query(self):
        script = re.search(r"<script>([\s\S]*?)</script>", self.html).group(1)
        runner = r"""
const code = process.argv[1], out = [];
for (const search of ['?q=định%20giá%20IPO', '?q=', '', '?q=a%26b&x=1']) {
  const location = { search, replace: u => out.push(u) };
  new Function('location', code)(location);
}
process.stdout.write(JSON.stringify(out));
"""
        self.assertEqual(node(runner, script), ["./?q=%C4%91%E1%BB%8Bnh%20gi%C3%A1%20IPO", "./#tim", "./#tim", "./?q=a%26b"])


if __name__ == "__main__":
    unittest.main()

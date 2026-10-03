"""Real renderer/disclosure regression checks; CSS wiring is not browser geometry proof."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "site/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "site/styles.css").read_text(encoding="utf-8")


def function_source(name):
    match = re.search(r"^function " + name + r"\([^\n]*\)\{[\s\S]*?^\}", APP, re.M)
    if not match:
        raise AssertionError(f"Missing function {name}")
    return match.group()


@unittest.skipUnless(shutil.which("node"), "Node required for offline lead behavior tests")
class LeadPhoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Execute the production module's declarations and real lead renderer. DOM effects
        # use small doubles, matching test_loading_layout; all display helpers stay real.
        prefix = APP[:APP.index('/* "Đang phát và sắp tới"')]
        prefix = re.sub(r"from '\./([^']+)'", lambda m: "from " + json.dumps(
            (ROOT / "site" / m[1]).as_uri()), prefix)
        handler = APP.split("  const ld = t.closest('[data-lead-details]');", 1)[1].split("  const rd =", 1)[0]
        harness = r"""
import fs from 'node:fs';
const location = {search:''};
const matchMedia = () => ({matches:true});
const localStorage = {getItem:()=>null};
const document = {body:{},activeElement:null,querySelector:s=>nodes.get(s),querySelectorAll:()=>[]};
const nodes = new Map();
const CSS = {escape:s=>s};
let hydrations=0;
function hydrateVisible(){hydrations++;}
""" + prefix + "\n" + function_source("keepFocus") + "\n" + r"""
function keyOf(el){return el?.dataset?.sel || null;}
function clickDisclosure(ld){
""" + handler + "\n}\n" + r"""
D = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
S = new Map(D.stories.map(s=>[s.id,s])); SRC = new Map(D.sources.map(s=>[s.id,s]));
const L = pickLead(), st = L.st, result = {};
result.real = {html:leadTile(L),title:viShown(st.title,st.title_vi),original:st.title,
  summary:st.summary,url:st.url,id:st.id,coverage:covOf(st).map(c=>c.discussion_url||c.url),
  others:L.others.slice(0,2).map(o=>o.id)};
const classes = new Set(), label = {textContent:'Xem đầy đủ'};
const button = {expanded:'false', getAttribute(){return this.expanded;},
  setAttribute(name,value){this.expanded=value;}, querySelector(){return label;},
  closest(){return {classList:{toggle(c,on){on ? classes.add(c) : classes.delete(c);}}};}};
clickDisclosure(button);
result.open = {expanded:button.expanded,label:label.textContent,classes:[...classes],html:leadTile(L),hydrations};
clickDisclosure(button);
result.closed = {expanded:button.expanded,label:label.textContent,classes:[...classes],html:leadTile(L),hydrations};
clickDisclosure(button);
result.sameStory = leadTile({...L,st:{...st,title_vi:'Updated translation'}});
result.nextStory = leadTile({...L,st:{...st,id:'different-lead'}});
result.returnedStory = leadTile(L);
result.translations = [undefined,null,'  ',st.title,' '+st.title+' ',42,'Một tiêu đề khác'].map(title_vi=>leadTile({...L,st:{...st,title_vi}}));
const summary = 'A <script>alert("x")</script> & useful detail '.repeat(12);
result.longSummary = {html:leadTile({...L,st:{...st,summary}}),summary:esc(summary)};
result.single = leadTile({mode:'single',others:[],st:{...st,source_count:1}});
result.focus = [];
for (const attr of ['data-save','data-lead-details']) {
  let focused=0;
  const old = {closest:s=>s.startsWith('.t-lead ') ? old : null,hasAttribute:a=>a===attr,getAttribute:()=>st.id};
  const replacement = {getClientRects:()=>[{}],focus:()=>focused++};
  nodes.set(`.t-lead [${attr}="${st.id}"]`,replacement);
  document.activeElement=old;
  keepFocus(()=>{document.activeElement=document.body;});
  const restored=focused;
  document.activeElement=old;
  keepFocus(()=>{document.activeElement={otherControl:true};});
  result.focus.push({attr,restored,noStolenFocus:focused===restored});
}
process.stdout.write(JSON.stringify(result));
"""
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "lead-behavior.mjs"
            script.write_text(harness, encoding="utf-8", newline="\n")
            run = subprocess.run(["node", str(script), str(ROOT / "tests/fixtures/edition-real-snapshot.json")],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if run.returncode:
            raise AssertionError(run.stdout + run.stderr)
        cls.out = json.loads(run.stdout)

    def test_real_lead_retains_title_sources_links_and_other_stories(self):
        from html import unescape
        real = self.out["real"]
        self.assertIn(real["title"], unescape(real["html"]))
        self.assertIn(real["original"], unescape(real["html"]))
        if real.get("summary"):
            self.assertIn(real["summary"], unescape(real["html"]))
        self.assertIn('id="lead-details"', real["html"])
        self.assertIn(f'data-save="{real["id"]}"', real["html"])
        for link in [real["url"], *real["coverage"]]:
            self.assertIn(link, unescape(real["html"]))
        for story_id in real["others"]:
            self.assertIn(f'data-sel="{story_id}"', real["html"])

    def test_disclosure_opens_and_closes_with_matching_accessible_state(self):
        opened, closed = self.out["open"], self.out["closed"]
        self.assertEqual((opened["expanded"], opened["label"]), ("true", "Thu gọn"))
        self.assertIn("is-expanded", opened["classes"])
        self.assertIn('aria-expanded="true"', opened["html"])
        self.assertEqual((closed["expanded"], closed["label"]), ("false", "Xem đầy đủ"))
        self.assertNotIn("is-expanded", closed["classes"])
        self.assertEqual(opened["hydrations"], closed["hydrations"], "closing must not hydrate hidden content")

    def test_open_state_survives_redraw_but_resets_for_different_lead(self):
        self.assertIn('aria-expanded="true"', self.out["sameStory"])
        for key in ("nextStory", "returnedStory"):
            self.assertIn('aria-expanded="false"', self.out[key])

    def test_translation_attribution_requires_a_real_distinct_translation(self):
        for html in self.out["translations"][:-1]:
            compact = html.split('id="lead-details"')[0]
            self.assertNotIn("lead-attribution", compact)
        translated = self.out["translations"][-1]
        self.assertIn("lead-attribution", translated.split('id="lead-details"')[0])
        self.assertIn('class="orig lead-orig"', translated)
        self.assertIn("Bản dịch máy. Tiêu đề gốc trong phần đầy đủ.", translated)

    def test_summary_is_complete_and_escaped_even_when_long(self):
        self.assertIn(self.out["longSummary"]["summary"], self.out["longSummary"]["html"])
        self.assertNotIn('<script>', self.out["longSummary"]["html"])
        self.assertNotIn("lead-sum-more", self.out["longSummary"]["html"])

    def test_single_source_reason_and_actions_are_retained(self):
        self.assertIn("Chưa có chuyện nào được từ 2 nguồn", self.out["single"])
        self.assertIn("Bài gốc", self.out["single"])
        self.assertIn('data-save=', self.out["single"])

    def test_rerender_restores_save_and_disclosure_focus_without_stealing_it(self):
        for case in self.out["focus"]:
            self.assertEqual(case["restored"], 1, case["attr"])
            self.assertTrue(case["noStolenFocus"], case["attr"])


class LeadPhoneLayoutContractTests(unittest.TestCase):
    def test_desktop_contents_and_phone_disclosure_are_separate(self):
        self.assertRegex(CSS, r"\.lead-details\{display:contents\}")
        self.assertRegex(CSS, r"\.lead-disclosure\{display:none\}")
        phone = CSS[CSS.index('/* Phone lead:'):]
        self.assertIn('@media (max-width: 767px)', phone)
        self.assertIn('.t-lead .lead-details{display:none}', phone)
        self.assertIn('.t-lead.is-expanded .lead-details{display:flex', phone)
        self.assertNotRegex(phone, r"lead-(?:title|sum)[^}]*line-clamp")
        self.assertRegex(phone, r"\.lead-toggle\{[^}]*min-height:var\(--btn-h\)")
        tokens = (ROOT / 'site/tokens.css').read_text(encoding='utf-8')
        self.assertIn('--btn-h: 44px', tokens)

    def test_phone_first_paint_does_not_insert_visible_tiles_later(self):
        boot = APP[APP.index('async function boot()'):]
        self.assertIn('renderBoard(false, true)', boot)
        self.assertNotIn("insertAdjacentHTML('beforeend', rest)", boot)


if __name__ == '__main__':
    unittest.main()

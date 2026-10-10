"""First-screen resource contracts; rendered LCP/CLS are measured separately."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'site/app.js').read_text(encoding='utf-8')


def declaration(name):
    match = re.search(r'^(?:async )?function ' + name + r'\([^\n]*\)\{[\s\S]*?^\}', APP, re.M)
    if not match:
        match = re.search(r'^const ' + name + r' = [^\n]+;', APP, re.M)
    if not match:
        raise AssertionError(f'Missing function: {name}')
    return match.group()


@unittest.skipUnless(shutil.which('node'), 'Node required for resource behavior tests')
class InitialPaintTests(unittest.TestCase):
    def run_js(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'initial-paint.mjs'
            path.write_text(source, encoding='utf-8', newline='\n')
            result = subprocess.run(['node', str(path)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_critical_thumbnail_bypasses_deferred_lazy_images(self):
        source = "const esc = s => s, imgSrc = u => `data-src=\"${u}\"`;\n" + declaration('thumbImg')
        result = self.run_js(source + '\nprocess.stdout.write(JSON.stringify([thumbImg("video"),thumbImg("video","",true)]));')
        lazy, critical = result
        self.assertIn('data-src=', lazy)
        self.assertIn('loading="lazy"', lazy)
        self.assertNotIn('data-src=', critical)
        self.assertIn('src="https://i.ytimg.com/vi/video/hqdefault.jpg"', critical)
        self.assertIn('loading="eager"', critical)
        self.assertIn('fetchpriority="high"', critical)
        self.assertIn('width="480" height="270"', critical)
        live = declaration('liveTile')
        self.assertEqual(len(re.findall(r"thumbImg\([^\n]*?, '', true(?:, lastEnded\.s)?\)", live)), 2,
                         'both story-backed and standalone ended streams are critical')

    def test_screened_video_uses_only_the_story_image(self):
        source = "const esc = s => s, imgSrc = u => `data-src=\"${u}\"`;\n" + declaration('thumbImg')
        result = self.run_js(source + '''
const screened = {image_screened:true};
const approved = {...screened, image:{src:'assets/ai/approved.jpg'}};
process.stdout.write(JSON.stringify([
  thumbImg('video', '', true, screened), thumbImg('video', '', false, screened),
  thumbImg('video', '', true, approved), thumbImg('video', '', false, approved)
]));''')
        self.assertEqual(result[:2], ["", ""])
        self.assertIn('src="assets/ai/approved.jpg"', result[2])
        self.assertIn('data-src="assets/ai/approved.jpg"', result[3])
        self.assertNotIn('i.ytimg.com', ''.join(result))

    def test_first_paint_path_sequences_head_projection_before_full_snapshot(self):
        boot = APP[APP.index('async function boot()'):]
        self.assertIn("loadSnapshot(HEAD_URL, null)", boot)
        self.assertIn("renderBoard(false, true)", boot)
        self.assertIn("revealBoard(); startBoard();", boot)
        self.assertLess(boot.index('loadSnapshot(HEAD_URL, null)'), boot.index('loadSnapshot(DATA_URL, FALLBACK_URL)'))
        self.assertLess(boot.index('renderBoard(false, true)'), boot.index('renderChapters(true)'))

    def test_first_paint_falls_back_seamlessly_when_head_fails(self):
        source = r'''
const calls = [];
const rendered = [];
const loadSnapshot = async (url, fallback) => {
  calls.push(url);
  if (url === 'data/radar-head.json') throw new Error('404 Not Found');
  return {schema_version: 2, generated_at: '2026-10-03T00:00:00Z', stories: [], sources: []};
};
const isSnapshotV2 = j => j && j.schema_version === 2;
const nextTask = () => Promise.resolve();
const setDeferImages = () => {};
const renderBoard = (split, reveal) => { rendered.push('board'); };
const renderChrome = () => {};
const revealBoard = () => {};
const startBoard = () => {};
const afterPaint = () => Promise.resolve();
const loadDeferredImages = () => {};
const renderChapters = () => Promise.resolve();
const observeChapters = () => {};
const whenIdle = () => Promise.resolve();
const hydrateVisible = () => {};
const hydrateHF = () => {};
const open = () => {};
const showError = () => {};
let D = null;
const build = () => {};
const HEAD_URL = 'data/radar-head.json';
const DATA_URL = 'data/radar-ui.json';
const FALLBACK_URL = 'data/radar.json';
const location = {hash: '', search: ''};
const setInterval = () => {};
const document = {addEventListener: () => {}};

''' + declaration('boot') + r'''
await boot();
await new Promise(r => setTimeout(r, 10));
process.stdout.write(JSON.stringify({calls, rendered}));
'''
        result = self.run_js(source)
        self.assertEqual(result['calls'], ['data/radar-head.json', 'data/radar-ui.json'])
        self.assertEqual(result['rendered'], ['board'])

    def test_mark_shortcut_waits_for_the_visible_board(self):
        handler = re.search(r"document.addEventListener\('keydown', e => \{[\s\S]*?^\}\);", APP, re.M).group()
        result = self.run_js(r'''
let handler, loading = true, clicks = 0, disabled = false;
class Element {}
const document = {addEventListener:(event,fn)=>{handler=fn;}};
const board = {classList:{contains:()=>loading}};
const mark = {getAttribute:()=>String(disabled),click:()=>clicks++};
const $ = s => s === '#board' ? board : s === '#mark' ? mark : {open:false};
''' + handler + r'''
handler({key:'m'}); const pending = clicks;
loading = false; handler({key:'M'}); const ready = clicks;
disabled = true; handler({key:'m'});
process.stdout.write(JSON.stringify({pending,ready,disabled:clicks}));
''')
        self.assertEqual(result, {'pending': 0, 'ready': 1, 'disabled': 1})

    def test_head_and_thumbnail_are_preloaded_without_font_blocking(self):
        bento_html = (ROOT / 'site/bento.html').read_text(encoding='utf-8')
        self.assertIn('<link rel="preload" href="data/radar-head.json" as="fetch" crossorigin>', bento_html)
        self.assertRegex(bento_html, r'<link rel="preload" as="image" href="https://i\.ytimg\.com/vi/[^/]+/hqdefault\.jpg" fetchpriority="high">')
        # Fonts must not choke initial slow-4G bandwidth
        font_preloads = re.findall(r'<link rel="preload" href="([^"]+)" as="font"', bento_html)
        self.assertEqual(font_preloads, [])

        feed_html = (ROOT / 'site/index.html').read_text(encoding='utf-8')
        self.assertIn('<link rel="preload" href="data/radar-window.json" as="fetch" crossorigin>', feed_html)
        self.assertEqual(re.findall(r'<link rel="preload" href="([^"]+)" as="font"', feed_html), [])


if __name__ == '__main__':
    unittest.main()

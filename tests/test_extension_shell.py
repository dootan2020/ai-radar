"""Contracts for the cached Chrome new-tab homepage."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'extension'
SITE = ROOT / 'site'
FIXTURE = ROOT / 'tests/fixtures/radar-window-sample.json'
LIVE = 'https://radar-ai-vn.pages.dev/'


def node(script, *paths):
    result = subprocess.run(['node', '--input-type=module', '-e', script, *map(str, paths)],
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class ExtensionShellTests(unittest.TestCase):
    def test_manifest_and_local_code(self):
        manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['manifest_version'], 3)
        self.assertEqual(manifest['chrome_url_overrides'], {'newtab': 'newtab.html'})
        self.assertEqual(set(manifest['permissions']), {'storage', 'alarms', 'search'})
        self.assertEqual(manifest['host_permissions'], [LIVE + '*'])
        self.assertEqual(manifest['background']['service_worker'], 'background.js')
        for path in EXT.rglob('*.html'):
            html = path.read_text(encoding='utf-8')
            self.assertNotRegex(html, r'<script\b(?![^>]*\bsrc="(?:\./)?[\w./-]+\.js")[^>]*>', path.name)
            self.assertNotRegex(html, r'\son[a-z]+\s*=', path.name)
            self.assertNotRegex(html, r'<script\b[^>]*src=["\']https?://', path.name)
            self.assertNotRegex(html, r'<link\b[^>]*rel=["\'](?:stylesheet|modulepreload)["\'][^>]*href=["\']https?://', path.name)
            self.assertNotIn('Content-Security-Policy', html)
            self.assertNotIn('cloudflareinsights.com', html)
        for path in EXT.rglob('*.js'):
            source = path.read_text(encoding='utf-8')
            self.assertNotRegex(source, r'\bimport\s*(?:[^;]*?\sfrom\s*)?["\']https?://', path.name)
        self.assertNotIn('topSites', (EXT / 'newtab.js').read_text(encoding='utf-8'))

    def test_site_assets_and_live_links(self):
        payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(payload['schema_version'], 2)
        self.assertGreater(len(payload['stories']), 100)
        for name in ('tokens.css', 'feed.css', 'arena.css', 'story.css', 'faces.js',
                     'time-text.js', 'words.js', 'titles.js', 'calendar.js', 'arena.js',
                     'story.js', 'worth-score.js', 'live.js', 'feed-images.json',
                     'editor-picks.json'):
            self.assertEqual((EXT / name).read_bytes(), (SITE / name).read_bytes(), name)
        self.assertTrue((EXT / 'fonts/be-vietnam-pro-400-vietnamese.woff2').is_file())
        html = (EXT / 'newtab.html').read_text(encoding='utf-8')
        feed = (EXT / 'feed.js').read_text(encoding='utf-8')
        self.assertIn('<form id="web-search"', html)
        self.assertLess(html.index('id="web-search"'), html.index('id="picks"'))
        for link in ('ban-tin.html', 'tra-cuu.html'):
            self.assertIn(f'href="{LIVE}{link}"', html)
        for link in ('tin/', 'nguon.html'):
            self.assertIn(f'href="{LIVE}{link}', feed)
        self.assertIn(f"location.href = '{LIVE}tra-cuu.html'", feed)
        self.assertIn(f"const u = '{LIVE}tin/'", feed)
        self.assertIn('await cachedSnapshot()', feed)
        self.assertIn('whenIdle().then(async () => {', feed)
        for source in EXT.glob('*.js'):
            for imported in re.findall(r"(?:\bfrom\s*|\bimport\s*\()(['\"])(\./[^'\"]+\.js)\1", source.read_text(encoding='utf-8')):
                self.assertTrue((EXT / imported[1][2:]).is_file(), f'{source.name}: {imported[1]}')

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_relative_story_image_uses_live_site_origin(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const payload = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const mod = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
globalThis.chrome = {storage:{local:{get:async () => ({radarWindow:payload})}}};
const fromCache = await mod.cachedSnapshot();
const fromNetwork = mod.normalizeSnapshot(payload);
const image = stories => stories.find(story => story.image?.src?.startsWith('https://radar-ai-vn.pages.dev/assets/ai/'))?.image.src;
process.stdout.write(JSON.stringify({cached:image(fromCache.stories),network:image(fromNetwork.stories)}));
'''
        result = node(script, EXT / 'snapshot.js', FIXTURE)
        expected = LIVE + 'assets/ai/bd21296acc8d4bd90de5.jpg'
        self.assertEqual(result, {'cached': expected, 'network': expected})

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_snapshot_handles_null_and_untitled_items_without_fetch_timestamp(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const mod = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
globalThis.chrome = {storage:{local:{get:async () => ({radarWindow:{schema_version:2,
  stories:[null,{id:'one',title:'',coverage:[null,{source:'one'}]}],
  live:[null,{title:'Live'}], repos:[null,{id:1,full_name:''}], sources:[null], events:[null]}})}}};
const snap = await mod.cachedSnapshot();
process.stdout.write(JSON.stringify({stories:snap.stories.length,title:snap.stories[0].title,
  coverage:snap.stories[0].coverage.length,live:snap.live.length,repos:snap.repos.length,
  repoTitle:snap.repos[0].full_name,sources:snap.sources.length,events:snap.events.length}));
'''
        self.assertEqual(node(script, EXT / 'snapshot.js'), {
            'stories': 1, 'title': 'Bài viết chưa có tiêu đề', 'coverage': 1,
            'live': 1, 'repos': 1, 'repoTitle': '1', 'sources': 0, 'events': 0,
        })

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_worker_preserves_cache_on_network_failure_and_timeout(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const payload = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const listeners = {}, cache = {radarWindow:{stories:[{id:'old'}]},radarFetchedAt:'old'};
let mode = 'ok', calls = [], timeoutMs;
const realTimeout = AbortSignal.timeout;
AbortSignal.timeout = ms => { timeoutMs = ms; return mode === 'timeout' ? AbortSignal.abort() : realTimeout(ms); };
globalThis.chrome = {
  runtime:{onInstalled:{addListener:fn => listeners.install=fn},onStartup:{addListener:fn => listeners.startup=fn}},
  alarms:{create:(name,options) => cache.alarm=[name,options.periodInMinutes],onAlarm:{addListener:fn => listeners.alarm=fn}},
  storage:{local:{set:async value => Object.assign(cache,value)}},
};
globalThis.fetch = async (url, init) => {
  calls.push(url);
  if (mode === 'offline' || init.signal.aborted) throw Error(mode);
  return {ok:true,json:async () => payload};
};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
listeners.install(); await settle();
const saved = cache.radarWindow.stories.length, stamp = cache.radarFetchedAt;
mode='offline'; listeners.alarm({name:'refresh-radar-window'}); await settle();
const afterOffline = cache.radarWindow.stories.length;
mode='timeout'; listeners.startup(); await settle();
process.stdout.write(JSON.stringify({saved,afterOffline,afterTimeout:cache.radarWindow.stories.length,
  stampKept:cache.radarFetchedAt===stamp,alarm:cache.alarm,timeoutMs,calls}));
'''
        result = node(script, EXT / 'background.js', FIXTURE)
        count = len(json.loads(FIXTURE.read_text(encoding='utf-8'))['stories'])
        self.assertEqual(result, {
            'saved': count, 'afterOffline': count, 'afterTimeout': count,
            'stampKept': True, 'alarm': ['refresh-radar-window', 30],
            'timeoutMs': 10000, 'calls': [LIVE + 'data/radar-window.json'] * 3,
        })

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_search_uses_chrome_search(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const handlers = {}, queries = [];
globalThis.document = {querySelector: selector => selector === '#web-search' ?
  {addEventListener:(_,fn) => handlers.submit=fn} : selector === '#web-query' ? {value:'  AI radar  '} : null};
globalThis.chrome = {search:{query:value => queries.push(value)},storage:{local:{get:async () => ({radarWindow:{}})},onChanged:{addListener:fn => handlers.changed=fn}}};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
handlers.submit({preventDefault(){}});
process.stdout.write(JSON.stringify(queries));
'''
        self.assertEqual(node(script, EXT / 'newtab.js'),
                         [{'text': 'AI radar', 'disposition': 'CURRENT_TAB'}])

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_first_cache_arrival_reloads_only_an_empty_tab(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const handlers = {}; let cache, reloads=0;
globalThis.document = {querySelector: selector => selector === '#web-search' ?
  {addEventListener:() => {}} : selector === '#web-query' ? {value:''} : null};
globalThis.location = {reload:() => reloads++};
globalThis.chrome = {search:{query:() => {}},storage:{local:{get:async () => ({radarWindow:cache})},
  onChanged:{addListener:fn => handlers.changed=fn}}};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
await new Promise(resolve => setTimeout(resolve,0));
handlers.changed({radarWindow:{newValue:{}}},'local');
process.stdout.write(JSON.stringify(reloads));
'''
        self.assertEqual(node(script, EXT / 'newtab.js'), 1)


if __name__ == '__main__':
    unittest.main()

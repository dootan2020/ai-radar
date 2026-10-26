"""Contracts for the cached Chrome new-tab homepage."""
import json
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'extension'
SITE = ROOT / 'site'
FIXTURE = ROOT / 'tests/fixtures/radar-window-sample.json'
HEADLINE_FIXTURE = ROOT / 'tests/fixtures/audited-headlines-live.json'
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
        self.assertIn('tìm kiếm', manifest['description'].lower())
        self.assertEqual(manifest['icons'], {str(size): f'icons/{size}.png'
                                             for size in (16, 32, 48, 128)})
        for icon in manifest['icons'].values():
            self.assertTrue((EXT / icon).is_file(), icon)
        small = (ROOT / 'brand/assets/extension-icon-16.svg').read_text(encoding='utf-8')
        full = (ROOT / 'brand/assets/extension-icon-48.svg').read_text(encoding='utf-8')
        self.assertIn('#00B377', small)
        self.assertIn('#00B377', full)
        self.assertIn('Halcyon kingfisher', small)
        self.assertIn('Halcyon kingfisher', full)
        self.assertNotIn('circle cx="491.52"', small)
        self.assertIn('circle cx="491.52"', full)
        self.assertNotEqual(small, full)
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
                     'time-text.js', 'words.js', 'titles.js', 'editorial-headline.js', 'calendar.js',
                     'worth-score.js', 'live.js', 'feed-images.json',
                     'editor-picks.json', 'favicon.ico', 'apple-touch-icon.png', 'logo.svg'):
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
        self.assertIn(LIVE + 'data/arena.json', (EXT / 'arena.js').read_text(encoding='utf-8'))
        story_source = (EXT / 'story.js').read_text(encoding='utf-8')
        self.assertIn(f"new URL(story.image.src, '{LIVE}')", story_source)
        self.assertNotIn('import.meta.url', story_source)
        for name in ('feed-images.json', 'editor-picks.json'):
            self.assertIn(LIVE + name, feed)
            self.assertIn(f"'{name}'", feed)
        module_patterns = (
            r"\bfrom\s*(['\"])(\.[^'\"]+\.js)\1",
            r"\bimport\s*\(\s*(['\"])(\.[^'\"]+\.js)\1",
            r"\bimport\s+(['\"])(\.[^'\"]+\.js)\1",
        )
        for source in EXT.glob('*.js'):
            code = source.read_text(encoding='utf-8')
            for pattern in module_patterns:
                for _, imported in re.findall(pattern, code):
                    target = (source.parent / imported).resolve()
                    self.assertTrue(target.is_relative_to(EXT.resolve()) and target.is_file(),
                                    f'{source.name}: {imported}')

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_extension_s107_headline_matches_site(self):
        script = r'''
import {readFileSync} from 'node:fs';
import {headlineShown as siteHeadline} from './site/editorial-headline.js';
import {headlineShown as extensionHeadline} from './extension/editorial-headline.js';
import {storyTitle} from './extension/story.js';
const story = JSON.parse(readFileSync(process.argv[1], 'utf8')).stories.find(row => row.index === 107);
process.stdout.write(JSON.stringify({site:siteHeadline(story),extension:extensionHeadline(story),detail:storyTitle(story)}));
'''
        shown = node(script, HEADLINE_FIXTURE)
        expected = 'OpenAI cắt kết nối internet khi huấn luyện mô hình AI tiên phong sau loạt sự cố tấn công mạng'
        self.assertEqual(shown, {'site': expected, 'extension': expected, 'detail': expected})

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
  alarms:{get:async () => cache.alarm ? {name:cache.alarm[0]} : null,
    create:(name,options) => cache.alarm=[name,options.periodInMinutes],onAlarm:{addListener:fn => listeners.alarm=fn}},
  storage:{local:{set:async value => Object.assign(cache,value)}},
};
globalThis.fetch = async (url, init) => {
  calls.push(url);
  if (mode === 'offline' || init.signal.aborted) throw Error(mode);
  return {ok:true,json:async () => payload};
};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
await settle();
const alarmAtWorkerStart = cache.alarm;
listeners.install(); await settle();
const saved = cache.radarWindow.stories.length, stamp = cache.radarFetchedAt;
mode='offline'; listeners.alarm({name:'refresh-radar-window'}); await settle();
const afterOffline = cache.radarWindow.stories.length;
mode='timeout'; listeners.startup(); await settle();
process.stdout.write(JSON.stringify({saved,afterOffline,afterTimeout:cache.radarWindow.stories.length,
  stampKept:cache.radarFetchedAt===stamp,alarm:cache.alarm,alarmAtWorkerStart,timeoutMs,calls}));
'''
        result = node(script, EXT / 'background.js', FIXTURE)
        count = len(json.loads(FIXTURE.read_text(encoding='utf-8'))['stories'])
        self.assertEqual(result, {
            'saved': count, 'afterOffline': count, 'afterTimeout': count,
            'stampKept': True, 'alarm': ['refresh-radar-window', 30],
            'alarmAtWorkerStart': ['refresh-radar-window', 30],
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

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_snapshot_arriving_before_storage_get_resolves_reloads(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const handlers = {}; let finishGet, reloads=0;
globalThis.document = {querySelector: selector => selector === '#web-search' ?
  {addEventListener:() => {}} : {value:''}};
globalThis.location = {reload:() => reloads++};
globalThis.chrome = {search:{query:() => {}},storage:{local:{get:() => new Promise(resolve => finishGet=resolve)},
  onChanged:{addListener:fn => handlers.changed=fn}}};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
handlers.changed({radarWindow:{newValue:{stories:[{id:'new'}]}}},'local');
finishGet({radarWindow:{stories:[{id:'new'}]}});
await new Promise(resolve => setTimeout(resolve,0));
process.stdout.write(JSON.stringify(reloads));
'''
        self.assertEqual(node(script, EXT / 'newtab.js'), 1)

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_live_editor_picks_and_images_fall_back_to_packaged_files(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const picksCode = source.split('async function loadPicks() {')[1].split('async function loadFieldRankings()')[0];
const imagesCode = source.split('async function loadImages() {')[1].split('async function loadData(')[0];
const urls = [...source.matchAll(/const (?:IMAGES_URL|PICKS_URL|PACKAGED_IMAGES_URL|PACKAGED_PICKS_URL) = '([^']+)'/g)].map(m => m[1]);
let calls = [], offline = false;
const fetchJSON = async url => {
  calls.push(url);
  if (offline && url.startsWith('https://')) throw Error('offline');
  if (url.endsWith('editor-picks.json')) return {picks:[{id:url.startsWith('https://')?'live':'packaged'}]};
  return {images:{'item':url.startsWith('https://')?'live.jpg':'packaged.jpg'}};
};
const picks = new Function('fetchJSON','PICKS_URL','PACKAGED_PICKS_URL',
  `async function loadPicks() {${picksCode}; return loadPicks;`)(fetchJSON,urls[2],urls[3]);
const IMG = {};
const images = new Function('fetchJSON','IMAGES_URL','PACKAGED_IMAGES_URL','IMG',
  `async function loadImages() {${imagesCode}; return loadImages;`)(fetchJSON,urls[0],urls[1],IMG);
const onlinePicks = await picks(); await images();
const onlineImage = IMG.item.src;
offline = true; calls = [];
const offlinePicks = await picks(); await images();
process.stdout.write(JSON.stringify({onlinePicks,onlineImage,offlinePicks,offlineImage:IMG.item.src,calls}));
'''
        result = node(script, EXT / 'feed.js')
        self.assertEqual(result['onlinePicks'], [{'id': 'live'}])
        self.assertEqual(result['onlineImage'], 'live.jpg')
        self.assertEqual(result['offlinePicks'], [{'id': 'packaged'}])
        self.assertEqual(result['offlineImage'], 'packaged.jpg')
        self.assertEqual(result['calls'], [LIVE + 'editor-picks.json', 'editor-picks.json',
                                           LIVE + 'feed-images.json', 'feed-images.json'])

    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript behavior tests')
    def test_worker_keeps_existing_alarm(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
let created = 0;
globalThis.chrome = {alarms:{get:async () => ({name:'refresh-radar-window'}),
  create:() => created++,onAlarm:{addListener:() => {}}},
  runtime:{onInstalled:{addListener:() => {}},onStartup:{addListener:() => {}}}};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
await new Promise(resolve => setTimeout(resolve,0));
process.stdout.write(JSON.stringify(created));
'''
        self.assertEqual(node(script, EXT / 'background.js'), 0)

    def test_sync_rejects_missing_anchors_and_extra_load_first_code(self):
        spec = importlib.util.spec_from_file_location('extension_sync', EXT / 'sync-site.py')
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        html = (SITE / 'index.html').read_text(encoding='utf-8')
        feed = (SITE / 'feed.js').read_text(encoding='utf-8')
        for missing in ('<script>try { var t = ', '<!-- Cloudflare Web Analytics -->',
                        'href="ban-tin.html"', 'href="tra-cuu.html"'):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                sync.adapt_html(html.replace(missing, 'changed', 1))
        for missing in ('href="tin/', 'href="nguon.html"', "location.replace('nguon.html')",
                        "location.href = 'tra-cuu.html'"):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                sync.adapt_feed(feed.replace(missing, 'changed', 1))
        with self.assertRaises(ValueError):
            sync.adapt_feed(feed.replace('  complete = true;\n  return loadData();',
                                         '  extraHelper();\n  complete = true;\n  return loadData();', 1))
        for unsafe in ('<script>doBadThing()</script>', '<script src="https://example.com/a.js"></script>'):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                sync.validate_html(sync.adapt_html(html) + unsafe)
        for unsafe in ('<a href="tin/example/">', '<a href="other.html">',
                       '<link href="data/example.json">'):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                sync.validate_html(sync.adapt_html(html) + unsafe)
        with self.assertRaises(ValueError):
            sync.validate_urls(sync.adapt_feed(feed) + "fetch('data/example.json')")


if __name__ == '__main__':
    unittest.main()

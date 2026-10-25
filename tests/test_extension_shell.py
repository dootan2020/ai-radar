"""Offline contracts for the Chrome new-tab shell."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'extension'
FIXTURE = ROOT / 'tests/fixtures/radar-head-sample.json'


class ExtensionShellTests(unittest.TestCase):
    def test_manifest_and_local_code(self):
        manifest = json.loads((EXT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['manifest_version'], 3)
        self.assertEqual(manifest['chrome_url_overrides'], {'newtab': 'newtab.html'})
        self.assertEqual(set(manifest['permissions']), {'storage', 'alarms', 'search', 'topSites'})
        self.assertEqual(manifest['host_permissions'], ['https://radar-ai-vn.pages.dev/*'])
        self.assertEqual(manifest['background']['service_worker'], 'background.js')
        for path in EXT.rglob('*.html'):
            html = path.read_text(encoding='utf-8')
            self.assertNotRegex(html, r'<script\b(?![^>]*\bsrc="(?:\./)?[\w./-]+\.js")[^>]*>', path.name)
            self.assertNotRegex(html, r'\son[a-z]+\s*=', path.name)
            for src in re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html):
                self.assertFalse(re.match(r'https?://', src), src)
        for path in EXT.rglob('*.js'):
            source = path.read_text(encoding='utf-8')
            self.assertNotRegex(source, r'\bimport\s*(?:[^;]*?\sfrom\s*)?["\']https?://', path.name)

    def test_fixture_and_required_files(self):
        payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(payload['schema_version'], 2)
        self.assertTrue(payload['stories'])
        for name in ('newtab.html', 'newtab.css', 'tokens.css', 'newtab.js', 'render.js', 'README.md'):
            self.assertTrue((EXT / name).is_file(), name)
        for size in (16, 48, 128):
            self.assertTrue((EXT / f'icons/{size}.png').is_file())

    @unittest.skipUnless(shutil.which('node'), 'Node required for DOM rendering tests')
    def test_rendering_from_fixture_and_empty_payload(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const payload = JSON.parse(readFileSync(process.argv[2], 'utf8'));
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
}
globalThis.document = {createElement: tag => new Node(tag)};
const {renderFeed} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const all = root => [root, ...root.children.flatMap(all)];
const inspect = data => {
  const root = renderFeed(data), nodes = all(root);
  return {
    lead: nodes.filter(n => n.tag === 'article' && n.className === 'card lead').length,
    sections: Object.fromEntries(nodes.filter(n => n.dataset.kind).map(n => [n.dataset.kind, all(n).filter(x => x.tag === 'article').length])),
    text: nodes.map(n => n.textContent).join(' '),
    firstTitle: nodes.find(n => n.tag === 'a')?.textContent,
  };
};
const sample = inspect(payload);
const live = inspect({...payload, live:[{title:'Live stream',url:'https://example.com/live',status:'live'}]});
process.stdout.write(JSON.stringify({sample,live,empty:inspect({})}));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script,
                                 str(EXT / 'render.js'), str(FIXTURE)],
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = json.loads(result.stdout)
        payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(rendered['sample']['lead'], 1)
        self.assertEqual(rendered['sample']['sections']['hot'], len(payload['sections']['hot']) - 1)
        self.assertEqual(rendered['sample']['sections']['repos'], len(payload['repos']))
        self.assertNotIn('live', rendered['sample']['sections'])
        self.assertEqual(rendered['live']['sections']['live'], 1)
        self.assertIn('Chưa có dữ liệu', rendered['empty']['text'])

    @unittest.skipUnless(shutil.which('node'), 'Node required for worker behavior tests')
    def test_refresh_preserves_cache_when_offline(self):
        script = r'''
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8');
const payload = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const listeners = {};
const cache = {};
let fetches = 0, online = true;
globalThis.chrome = {
  runtime: {
    onInstalled: {addListener: fn => listeners.install = fn},
    onStartup: {addListener: fn => listeners.startup = fn},
  },
  alarms: {
    create: (name, options) => { cache.alarm = [name, options.periodInMinutes]; },
    onAlarm: {addListener: fn => listeners.alarm = fn},
  },
  storage: {local: {set: async value => Object.assign(cache, value)}},
};
globalThis.fetch = async () => {
  fetches++;
  if (!online) throw new Error('offline');
  return {ok:true,json:async () => payload};
};
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
listeners.install(); await settle();
const saved = cache.radarHead?.stories?.length;
online = false;
listeners.alarm({name:'refresh-radar-head'}); await settle();
process.stdout.write(JSON.stringify({saved,afterOffline:cache.radarHead?.stories?.length,
  fetchedAt:!!cache.radarFetchedAt,alarm:cache.alarm,fetches}));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script,
                                 str(EXT / 'background.js'), str(FIXTURE)],
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        count = len(json.loads(FIXTURE.read_text(encoding='utf-8'))['stories'])
        self.assertEqual(observed, {'saved': count, 'afterOffline': count, 'fetchedAt': True,
                                    'alarm': ['refresh-radar-head', 30], 'fetches': 2})


if __name__ == '__main__':
    unittest.main()

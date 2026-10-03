/* Offline equivalence proof: execute the actual app's markup functions with
   full and projected data. This is not a browser layout/performance test. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {loadSnapshot} from '../site/snapshot.js';

const [fullPath, pagePath] = process.argv.slice(2);
const full = JSON.parse(await readFile(fullPath, 'utf8'));
const page = JSON.parse(await readFile(pagePath, 'utf8'));
const originalFetch = globalThis.fetch;
const success = data => ({ok: true, json: async () => data});
for (const bad of [() => ({ok: false, status: 404}), () => success({}),
  () => ({ok: true, json: async () => { throw new SyntaxError('broken JSON'); }}),
  () => { throw new TypeError('offline'); }]) {
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({url, options}); return calls.length === 1 ? bad() : success(full); };
  assert.deepEqual(await loadSnapshot('data/radar-ui.json', 'data/radar.json', {cache:'no-cache'}), full);
  assert.deepEqual(calls.map(({url, options}) => ({url, options:{cache:options.cache}})),
    [{url:'data/radar-ui.json', options:{cache:'no-cache'}}, {url:'data/radar.json', options:{cache:'no-cache'}}]);
  assert.ok(calls.every(({options}) => options.signal instanceof AbortSignal && !options.signal.aborted));
}
let requests = 0;
globalThis.fetch = async () => { requests++; return success(page); };
assert.deepEqual(await loadSnapshot('data/radar-ui.json', 'data/radar.json'), page);
assert.equal(requests, 1);
requests = 0;
globalThis.fetch = async () => { requests++; return {ok:false, status:404}; };
await assert.rejects(loadSnapshot('data/custom.json'), error => error.vi === true && error.message === 'Máy chủ trả mã HTTP 404 khi tải data/custom.json');
assert.equal(requests, 1, 'custom fixture must not silently use default data');
globalThis.fetch = async () => success({});
await assert.rejects(loadSnapshot('data/custom.json'), error => error.vi === true && error.message === 'Tệp dữ liệu không đúng định dạng phiên bản 2');
globalThis.fetch = originalFetch;

const appURL = new URL('../site/app.js', import.meta.url);
let source = (await readFile(appURL, 'utf8')).split('const opened = new Set();')[0];
const modules = {};
for (const match of source.matchAll(/^import \{([^}]+)\} from '([^']+)';$/gm)) {
  modules[match[2]] = await import(new URL(match[2], appURL));
}
source = source.replace(/^import \{([^}]+)\} from '([^']+)';$/gm,
  (_, bindings, path) => `const {${bindings.replace(/\s+as\s+/g, ':')}} = modules[${JSON.stringify(path)}];`);
const factory = new Function('modules', 'location', 'matchMedia', 'localStorage', source + `
return data => {
  D = data; build();
  const L = pickLead(), shown = new Set([L.st.id]);
  const board = [leadTile(L), liveTile(shown), repoTile(), hotTile(shown), newTile(shown), listenTile(shown), modelTile(shown), sourcesTile()];
  const stories = D.stories.map(st => ({id:st.id, row:row(st), detail:detailStory(st), calendar:calOf(st)}));
  const repos = (repoList() || []).map(r => ({id:r.id, row:repoRow(r), detail:detailRepo(r)}));
  const chapters = CHAPTERS.map(c => { expanded.add(c.id); return chapterList(c); });
  const lists = [];
  for (const view of REPO_VIEWS) for (const window of WINDOWS) for (const total of TOTALS) {
    repoView = view.id; repoWindow = window.id; repoTotal = total.id;
    for (const area of [null, ...AREAS.map(a => a.id)]) {
      areas.clear(); if (area) areas.add(area);
      lists.push(repoChapter());
    }
  }
  saved = D.stories.map(st => ({key:st.id, title:st.title, url:st.url}));
  return {board, stories, repos, chapters, lists, saved:savedChapter(), counts:navCounts(D),
    translation:translationNote(), freshness:freshnessText(freshness(D.generated_at, D.sources), D.generated_at)};
};`);
const run = data => factory(modules, {search:''}, () => ({matches:true}), {getItem:() => null})(data);
const originalNow = Date.now;
Date.now = () => Date.parse(full.generated_at) + 4 * 3600_000;
try {
  assert.deepEqual(run(page), run(full), 'all board, story/detail, expanded chapters, saved stories, repo filters and freshness markup must match');
} finally { Date.now = originalNow; }
console.log(`Equivalent reader output: ${full.stories.length} stories, ${(full.repos || []).length} repositories; fallback checks passed.`);

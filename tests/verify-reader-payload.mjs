/* Offline proof of the snapshot loader's fallbacks with full and projected data (site/snapshot.js). The markup
   equivalence half ran the retired bento home (site/app.js) and went with it on 09/11. */
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

console.log(`Snapshot loader fallback checks passed (${full.stories.length} stories).`);

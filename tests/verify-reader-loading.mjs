import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {loadSnapshot} from '../site/snapshot.js';

const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;
const pending = () => new Promise(() => {});
const snapshot = {schema_version: 2, generated_at: '2026-10-03T09:00:00Z', stories: [], sections: {}, sources: []};
const response = () => ({ok: true, json: async () => snapshot});
const delays = [], activeTimers = new Set();
globalThis.setTimeout = (fn, ms) => {
  delays.push(ms);
  const id = realSetTimeout(() => { activeTimers.delete(id); fn(); }, 5);
  activeTimers.add(id);
  return id;
};
globalThis.clearTimeout = id => { activeTimers.delete(id); realClearTimeout(id); };

async function settled(promise){
  let guard;
  try {
    return await Promise.race([
      promise.then(value => ({value}), error => ({error})),
      new Promise(resolve => { guard = realSetTimeout(() => resolve({hung: true}), 150); }),
    ]);
  } finally { realClearTimeout(guard); }
}

const failures = [];
async function check(name, run){
  try { await run(); console.log(`PASS ${name}`); }
  catch (error) { failures.push(name); console.error(`FAIL ${name}: ${error.message}`); }
}

await check('hanging compact request aborts and falls back to full data', async () => {
  const calls = [];
  globalThis.fetch = (url, options) => { calls.push({url, options}); return calls.length === 1 ? pending() : Promise.resolve(response()); };
  const result = await settled(loadSnapshot('compact', 'full', {cache: 'no-cache'}));
  assert.equal(result.hung, undefined, 'reader remains pending after the deadline');
  assert.equal(result.value, snapshot);
  assert.deepEqual(calls.map(c => c.url), ['compact', 'full']);
  assert.equal(calls[0].options.signal.aborted, true);
  assert.equal(calls[1].options.signal.aborted, false);
  assert.equal(calls[1].options.cache, 'no-cache');
  assert.equal(activeTimers.size, 0, 'success must clear deadline');
});

for (const stage of ['request', 'body']) {
  await check(`hanging ${stage} in both attempts reaches real error renderer`, async () => {
    const calls = [];
    globalThis.fetch = (url, options) => {
      calls.push({url, options});
      return stage === 'request' ? pending() : Promise.resolve({ok: true, json: pending});
    };
    const result = await settled(loadSnapshot('compact', 'full'));
    assert.equal(result.hung, undefined, 'reader remains pending after the deadline');
    assert.equal(result.error?.vi, true);
    assert.match(result.error.message, /quá lâu/);
    assert.deepEqual(calls.map(c => c.url), ['compact', 'full']);
    assert.ok(calls.every(c => c.options.signal.aborted));
    const app = readFileSync(new URL('../site/app.js', import.meta.url), 'utf8');
    const source = app.match(/^function showError\([^\n]*\)\{[\s\S]*?^\}/m)[0];
    const classes = new Set(['is-loading']);
    const attributes = new Set(['aria-busy']);
    const board = {innerHTML: '', classList: {remove: c => classes.delete(c)}, removeAttribute: a => attributes.delete(a)};
    let retry;
    const $ = selector => selector === '#board' ? board : {addEventListener: (_, handler) => {retry = handler;}};
    let reloads = 0;
    const showError = new Function('$', 'avatar', 'esc', 'location', `${source}; return showError;`)($, () => '', String, {reload: () => reloads++});
    // Use the production rejection callback as well as its renderer.
    const callback = app.match(/\.catch\((err => showError\([^\n]+)\);/)[1];
    const onError = new Function('showError', `return ${callback};`)(showError);
    onError(result.error);
    assert.equal(classes.has('is-loading'), false);
    assert.equal(attributes.has('aria-busy'), false);
    assert.match(board.innerHTML, /role="alert"/);
    assert.match(board.innerHTML, /quá lâu/);
    retry(); assert.equal(reloads, 1);
  });
}

await check('explicit fixture has a deadline but no implicit fallback', async () => {
  const urls = [];
  globalThis.fetch = url => {urls.push(url); return pending();};
  const result = await settled(loadSnapshot('fixture'));
  assert.equal(result.hung, undefined);
  assert.equal(result.error?.vi, true);
  assert.deepEqual(urls, ['fixture']);
});

await check('compact body deadline still permits the full snapshot', async () => {
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1 ? {ok: true, json: pending} : response();
  const result = await settled(loadSnapshot('compact', 'full'));
  assert.equal(result.value, snapshot);
  assert.equal(calls, 2);
  assert.equal(activeTimers.size, 0);
});

for (const alreadyAborted of [false, true]) {
  await check(`caller cancellation (${alreadyAborted ? 'before' : 'during'} request) never starts fallback`, async () => {
    const controller = new AbortController();
    const reason = new Error('Caller stopped reading');
    const calls = [];
    globalThis.fetch = (url, options) => { calls.push({url, options}); return pending(); };
    if (alreadyAborted) controller.abort(reason);
    const loading = loadSnapshot('compact', 'full', {signal: controller.signal});
    if (!alreadyAborted) controller.abort(reason);
    const result = await settled(loading);
    assert.equal(result.error, reason);
    assert.deepEqual(calls.map(c => c.url), ['compact']);
    assert.equal(calls[0].options.signal.aborted, true);
    assert.equal(activeTimers.size, 0);
  });
}

await check('successful and invalid compact snapshots preserve fallback behavior', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return response(); };
  assert.equal(await loadSnapshot('compact', 'full'), snapshot);
  assert.equal(calls, 1);
  assert.equal(activeTimers.size, 0);
  calls = 0;
  globalThis.fetch = async () => ++calls === 1 ? {ok: true, json: async () => ({bad: true})} : response();
  assert.equal(await loadSnapshot('compact', 'full'), snapshot);
  assert.equal(calls, 2);
  assert.equal(activeTimers.size, 0);
});

await check('request deadlines are positive and no longer than ten seconds', async () => {
  assert.ok(delays.length > 0, 'no deadline was installed');
  assert.ok(delays.every(ms => ms > 0 && ms <= 10_000));
});

globalThis.setTimeout = realSetTimeout;
globalThis.clearTimeout = realClearTimeout;
assert.deepEqual(failures, [], 'reader loading regressions');

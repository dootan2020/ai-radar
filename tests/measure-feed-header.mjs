// Render real site/data through a local static server. No npm dependencies.
// python -m http.server 8808 --bind 127.0.0.1 --directory site
// node tests/measure-feed-header.mjs [--observe] [--out <existing directory>]
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (name, fallback) => process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : fallback;
const url = arg('--url', 'http://127.0.0.1:8808/');
const out = arg('--out', null);
const observe = process.argv.includes('--observe');
const executable = [process.env.CHROME_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(p => p && fs.existsSync(p));
assert.ok(executable, 'Chrome must be installed');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'radar-header-'));
const chrome = spawn(executable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true });
let browserErrors = '';
chrome.stderr.on('data', data => { browserErrors = (browserErrors + data).slice(-6000); });
const exited = new Promise(resolve => chrome.once('exit', resolve));
console.error(`Header measurement Chrome PID: ${chrome.pid}; temporary profile: ${profile}`);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws, sequence = 0;
const pending = new Map();
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 15000);
  pending.set(id, { resolve, reject, timeout });
  ws.send(JSON.stringify({ id, method, params, sessionId }));
});

function measure() {
  const rect = e => {
    const b = e.getBoundingClientRect();
    return { x: b.x, y: b.y, width: b.width, height: b.height, right: b.right, bottom: b.bottom };
  };
  const dimensions = selector => {
    const e = document.querySelector(selector);
    return { ...rect(e), scrollWidth: e.scrollWidth, clientWidth: e.clientWidth };
  };
  const strip = document.querySelector('#feed-filters');
  const navigation = document.querySelector('.feed-navigation');
  const viewport = getComputedStyle(strip).overflowX === 'visible' ? navigation : strip;
  const viewportBox = rect(viewport);
  const masked = getComputedStyle(viewport).maskImage !== 'none';
  const visibleRight = viewportBox.right - (masked ? 32 : 0);
  const contained = box => box.x >= viewportBox.x - 0.5 && box.right <= visibleRight + 0.5 &&
    box.y >= viewportBox.y - 0.5 && box.bottom <= viewportBox.bottom + 0.5;
  const controls = [...document.querySelectorAll('#bar a, #bar button')].filter(e => e.getClientRects().length).map(e => {
    const box = rect(e);
    const range = document.createRange(); range.selectNodeContents(e);
    const text = range.getBoundingClientRect();
    const inScroller = viewport.contains(e);
    const fullyVisible = box.x >= 0 && box.right <= innerWidth + 0.5 &&
      (!inScroller || contained(box));
    return { label: e.textContent.trim() || e.getAttribute('aria-label'), filter: e.dataset.filter,
      active: e.getAttribute('aria-pressed') === 'true',
      ...box, fullyVisible,
      visibleLeft: inScroller ? Math.max(box.x, viewportBox.x) : box.x,
      visibleRight: inScroller ? Math.min(box.right, visibleRight) : box.right,
      textFits: text.x >= box.x - 0.5 && text.right <= box.right + 0.5 &&
        text.y >= box.y - 0.5 && text.bottom <= box.bottom + 0.5 && e.scrollWidth <= e.clientWidth + 1 };
  });
  const overlaps = [];
  for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
    const a = controls[i], b = controls[j];
    if (Math.min(a.visibleRight, b.visibleRight) - Math.max(a.visibleLeft, b.visibleLeft) > 0.5 &&
        Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > 0.5) overlaps.push([a.label, b.label]);
  }
  const tabs = controls.filter(c => c.filter);
  const tabGaps = tabs.slice(1).map((tab, i) => tab.x - tabs[i].right);
  const measurePill = container => {
    if (!container.getClientRects().length) return null;
    const pill = rect(container.querySelector('.tab-pill'));
    const active = rect(container.querySelector('[aria-pressed="true"]'));
    const inset = parseFloat(getComputedStyle(container).getPropertyValue('--tab-pill-inset')) || 0;
    const expected = { x: active.x, y: active.y + inset, width: active.width, height: active.height - inset * 2 };
    return { ...pill, inset, fullyVisible: contained(pill),
      matchesActive: ['x', 'y', 'width', 'height'].every(key => Math.abs(pill[key] - expected[key]) <= 1),
      centered: Math.abs(pill.y + pill.height / 2 - active.y - active.height / 2) <= 1 };
  };
  const pill = measurePill(strip);
  const sortPill = measurePill(document.querySelector('#sort-switch'));
  const utilityPills = [...document.querySelectorAll('.ed-link, .tc-link')].map(e => {
    const box = rect(e), paint = getComputedStyle(e, '::before');
    const top = parseFloat(paint.top), bottom = parseFloat(paint.bottom);
    const left = parseFloat(paint.left), right = parseFloat(paint.right);
    return { label: e.textContent.trim(), height: box.height - top - bottom,
      width: box.width - left - right, centered: Math.abs(top - bottom) <= 0.5 && Math.abs(left - right) <= 0.5 };
  });
  const table = document.querySelector('.arena-table');
  let arena = null;
  if (table && table.getClientRects().length && innerWidth >= 768) {
    const labels = [];
    for (const cell of table.querySelectorAll('thead th')) {
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode, text = node.textContent;
        if (!text.trim()) continue;
        const range = document.createRange();
        range.setStart(node, text.length - text.trimStart().length);
        range.setEnd(node, text.trimEnd().length);
        const boxes = [...range.getClientRects()].filter(b => b.width > 0);
        const b = range.getBoundingClientRect(), c = cell.getBoundingClientRect();
        labels.push({ text: text.trim(), x: b.x, y: b.y, right: b.right, bottom: b.bottom,
          lines: boxes.length, fits: b.x >= c.x - 0.5 && b.right <= c.right + 0.5 });
      }
    }
    const collisions = [];
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
      const a = labels[i], b = labels[j];
      if (Math.min(a.right, b.right) - Math.max(a.x, b.x) > 0.5 &&
          Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > 0.5) collisions.push([a.text, b.text]);
    }
    const axis = rect(table.querySelector('.arena-axis-ticks'));
    const tracks = [...table.querySelectorAll('.arena-plot-track')].map(rect);
    arena = { labels, collisions, axis, tracks,
      headerBottom: rect(table.querySelector('.arena-axis-header')).bottom,
      modelWidth: rect(table.querySelector('.arena-col-model')).width,
      scrollWidth: table.scrollWidth, clientWidth: table.clientWidth };
  }
  return { header: dimensions('#bar'), row: dimensions('.feed-bar-in'), strip: dimensions('#feed-filters'),
    navigation: dimensions('.feed-navigation'), sort: dimensions('#sort-switch'), masked, controls, overlaps,
    tabGaps, arena, pill, sortPill, utilityPills,
    surface: { header: getComputedStyle(document.querySelector('#bar')).backgroundColor,
      canvas: getComputedStyle(document.body).backgroundColor },
    tabCountElements: document.querySelectorAll('.filter-chip .count').length,
    staleBanner: !!document.querySelector('#stale'),
    document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth } };
}

async function main() {
  const portFile = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await sleep(100);
  const [port, endpoint] = fs.readFileSync(portFile, 'utf8').trim().split('\n');
  ws = new WebSocket(`ws://127.0.0.1:${port}${endpoint.trim()}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const data = JSON.parse(event.data), task = pending.get(data.id);
    if (!task) return;
    clearTimeout(task.timeout); pending.delete(data.id);
    data.error ? task.reject(new Error(data.error.message)) : task.resolve(data.result);
  };
  const results = [];
  for (const width of [768, 1024, 1180, 1440, 1920, 375, 320, 767, 1023, 1179, 1399, 1400, 1599, 1600]) {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    const call = (method, params) => send(method, params, sessionId);
    const evaluate = async expression => {
      const r = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    };
    await call('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 768 });
    await call('Emulation.setTouchEmulationEnabled', { enabled: width < 1180 });
    await call('Page.navigate', { url });
    let ready = false;
    for (let i = 0; i < 100; i++) {
      ready = await evaluate(`document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#sort-switch')?.hidden === false && !!document.querySelector('[data-act="save"]')`);
      if (ready) break;
      await sleep(100);
    }
    assert.ok(ready, 'Real feed must finish loading');
    await evaluate('document.fonts.ready.then(() => true)');
    await sleep(350);
    const capture = async (state, saved) => {
      for (const theme of ['light', 'dark']) {
        await evaluate(`document.documentElement.dataset.theme = '${theme}'`);
        results.push({ width, theme, state, saved, ...await evaluate(`(${measure})()`) });
        if (out && [375, 768, 1024, 1180, 1440, 1920].includes(width)) {
          const shot = await call('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width, height: 250, scale: 1 } });
          fs.writeFileSync(path.join(out, `header-${width}-${theme}-${state}.png`), Buffer.from(shot.data, 'base64'));
        }
      }
    };
    await capture('all', false);
    // Exercise the widest real navigation state through the site's save action.
    await evaluate(`document.querySelector('[data-act="save"][aria-pressed="false"]').click()`);
    await sleep(350);
    await capture('all-saved', true);
    for (const filter of ['saved', 'rankings']) {
      await evaluate(`document.querySelector('[data-filter="${filter}"]').click()`);
      await sleep(700);
      await capture(filter, true);
      if (filter === 'rankings') {
        assert.ok(await evaluate(`!!document.querySelector('.arena-table')`), 'Real Arena data must finish loading');
        for (const category of ['hard_prompts', 'non_english']) {
          await evaluate(`document.querySelector('[data-arena-category="${category}"]').click()`);
          await capture(`rankings-${category}`, true);
        }
        await evaluate(`document.querySelector('[data-arena-category="overall"]').click()`);
      }
    }
    // A selected rightmost tab must stay revealed when the available width changes.
    if (width === 1920) {
      await call('Emulation.setDeviceMetricsOverride', { width: 768, height: 900, deviceScaleFactor: 1, mobile: false });
      await sleep(700);
      results.push({ width: 768, theme: 'dark', state: 'rankings-resized', saved: true, ...await evaluate(`(${measure})()`) });
    }
    await evaluate(`document.querySelector('[data-filter="all"]').click()`);
    await evaluate(`document.querySelector('[data-act="save"][aria-pressed="true"]').click()`);
    await send('Target.closeTarget', { targetId });
  }
  if (out) fs.writeFileSync(path.join(out, 'header-measurements.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
  if (!observe) for (const r of results) {
    if (r.state.startsWith('rankings') && r.width >= 768 && r.width <= 1199) {
      const context = `${r.width}/${r.theme}/${r.state}`;
      assert.ok(r.arena, `${context}: missing Arena measurements`);
      assert.ok(r.arena.labels.every(label => label.lines === 1 && label.fits), `${context}: wrapped or clipped Arena header`);
      assert.deepEqual(r.arena.collisions, [], `${context}: Arena labels or ticks collide`);
      assert.ok(r.arena.headerBottom <= r.arena.axis.y, `${context}: labels intrude on axis ticks`);
      assert.ok(r.arena.scrollWidth <= r.arena.clientWidth + 1, `${context}: Arena table overflow`);
      assert.equal(r.arena.tracks.length, 10, `${context}: expected ten plot tracks`);
      assert.ok(r.arena.tracks.every(track => track.width >= 200), `${context}: CI track narrower than 200px`);
      assert.ok(r.arena.tracks.every(track => Math.abs(track.x - r.arena.axis.x) < 1 &&
        Math.abs(track.width - r.arena.axis.width) < 1), `${context}: ticks and bars are misaligned`);
    }
    assert.equal(r.header.scrollWidth, r.header.clientWidth, `${r.width}: header overflow`);
    assert.equal(r.document.scrollWidth, r.document.clientWidth, `${r.width}: document overflow`);
    assert.deepEqual(r.overlaps, [], `${r.width}: controls overlap`);
    assert.equal(r.tabCountElements, 0, `${r.width}: tab count elements remain`);
    assert.equal(r.staleBanner, false, `${r.width}: stale banner remains`);
    assert.notEqual(r.surface.header, r.surface.canvas, `${r.width}/${r.theme}: header merges into canvas`);
    assert.ok(r.pill.matchesActive && r.pill.centered && r.pill.inset > 0, `${r.width}: tab pill must be centred inside its hit area`);
    assert.ok(Math.abs(r.pill.height - 32) <= 1, `${r.width}: expected compact 32px tab pill`);
    if (r.sortPill) {
      assert.ok(r.sortPill.matchesActive && r.sortPill.centered, `${r.width}: sort pill must be centred inside its hit area`);
      assert.ok(Math.abs(r.sortPill.height - r.pill.height) <= 1, `${r.width}: inconsistent sort pill height`);
    }
    assert.ok(r.utilityPills.every(p => p.centered && Math.abs(p.height - r.pill.height) <= 1), `${r.width}: inconsistent utility pills`);
    assert.ok(r.controls.filter(c => c.filter).every(c => !/\d/.test(c.label)), `${r.width}: tab labels contain counts`);
    if (r.width >= 768) {
      assert.equal(r.controls.filter(c => c.filter).length, r.saved ? 8 : 7, `${r.width}: expected all populated sections including Rankings from real data`);
      assert.ok(!r.masked, `${r.width}: desktop fade`);
      assert.ok(r.controls.every(c => c.textFits), `${r.width}: labels clipped inside controls`);
      assert.ok(r.controls.filter(c => !c.filter || c.active).every(c => c.fullyVisible), `${r.width}: clipped utilities or active tab`);
      assert.ok(r.tabGaps.every(gap => Math.abs(gap - 8) <= 0.5), `${r.width}: uneven or touching tabs: ${r.tabGaps}`);
      assert.ok(r.pill.fullyVisible && r.pill.matchesActive, `${r.width}: clipped or misaligned active pill`);
    }
    if (r.width >= 1400) {
      assert.equal(r.strip.scrollWidth, r.strip.clientWidth, `${r.width}: wide desktop tabs should fit without scrolling`);
      assert.ok(r.controls.every(c => c.fullyVisible), `${r.width}: clipped desktop controls`);
      assert.ok(r.controls.every(c => Math.abs(c.y + c.height / 2 - r.controls[0].y - r.controls[0].height / 2) < 1), `${r.width}: multiple rows`);
    }
    assert.ok(r.controls.every(c => c.height >= 44 && c.width >= 44), `${r.width}: touch targets under 44px`);
  }
}

try { await main(); } catch (error) { console.error(error, browserErrors); process.exitCode = 1; }
finally {
  if (ws?.readyState === WebSocket.OPEN) {
    try { await send('Browser.close'); } catch { /* Browser may close before acknowledging. */ }
    ws.close();
  } else chrome.kill();
  await exited;
  // Only remove the unique profile that this process created under the system temp directory.
  assert.equal(path.dirname(profile), path.resolve(os.tmpdir()));
  assert.ok(path.basename(profile).startsWith('radar-header-') && !fs.lstatSync(profile).isSymbolicLink());
  fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}

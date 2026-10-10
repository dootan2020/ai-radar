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
  const stripBox = rect(strip);
  const masked = getComputedStyle(strip).maskImage !== 'none';
  const visibleRight = stripBox.right - (masked ? 32 : 0);
  const controls = [...document.querySelectorAll('#bar a, #bar button')].filter(e => e.getClientRects().length).map(e => {
    const box = rect(e);
    const range = document.createRange(); range.selectNodeContents(e);
    const text = range.getBoundingClientRect();
    const isTab = e.matches('.filter-chip');
    const fullyVisible = box.x >= 0 && box.right <= innerWidth + 0.5 &&
      (!isTab || (box.x >= stripBox.x - 0.5 && box.right <= visibleRight + 0.5));
    return { label: e.textContent.trim() || e.getAttribute('aria-label'), filter: e.dataset.filter,
      ...box, fullyVisible, textFits: text.width <= box.width + 0.5 && e.scrollWidth <= e.clientWidth + 1 };
  });
  const overlaps = [];
  for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
    const a = controls[i], b = controls[j];
    if (Math.min(a.right, b.right) - Math.max(a.x, b.x) > 0.5 &&
        Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > 0.5) overlaps.push([a.label, b.label]);
  }
  return { header: dimensions('#bar'), row: dimensions('.feed-bar-in'), strip: dimensions('#feed-filters'),
    navigation: dimensions('.feed-navigation'), sort: dimensions('#sort-switch'), masked, controls, overlaps,
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
  for (const width of [1024, 1180, 1280, 1440, 1920, 375, 320, 768, 1023, 1179]) {
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
      ready = await evaluate(`document.querySelector('#top')?.getAttribute('aria-busy') === 'false' && document.querySelector('#sort-switch')?.hidden === false`);
      if (ready) break;
      await sleep(100);
    }
    assert.ok(ready, 'Real feed must finish loading');
    await evaluate('document.fonts.ready.then(() => true)');
    await sleep(350);
    const result = { width, ...await evaluate(`(${measure})()`) };
    if (out && [375, 1024, 1180, 1440].includes(width)) {
      for (const theme of ['light', 'dark']) {
        await evaluate(`document.documentElement.dataset.theme = '${theme}'`);
        const shot = await call('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width, height: 250, scale: 1 } });
        fs.writeFileSync(path.join(out, `header-${width}-${theme}.png`), Buffer.from(shot.data, 'base64'));
      }
    }
    results.push(result);
    // Exercise the widest real navigation state through the site's save action.
    await evaluate(`document.querySelector('[data-act="save"][aria-pressed="false"]').click()`);
    await sleep(350);
    results.push({ width, saved: true, ...await evaluate(`(${measure})()`) });
    await evaluate(`document.querySelector('[data-act="save"][aria-pressed="true"]').click()`);
    await send('Target.closeTarget', { targetId });
  }
  if (out) fs.writeFileSync(path.join(out, 'header-measurements.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
  if (!observe) for (const r of results) {
    assert.equal(r.header.scrollWidth, r.header.clientWidth, `${r.width}: header overflow`);
    assert.equal(r.document.scrollWidth, r.document.clientWidth, `${r.width}: document overflow`);
    assert.deepEqual(r.overlaps, [], `${r.width}: controls overlap`);
    assert.equal(r.tabCountElements, 0, `${r.width}: tab count elements remain`);
    assert.equal(r.staleBanner, false, `${r.width}: stale banner remains`);
    assert.ok(r.controls.filter(c => c.filter).every(c => !/\d/.test(c.label)), `${r.width}: tab labels contain counts`);
    if (r.width >= 1024) {
      assert.equal(r.controls.filter(c => c.filter).length, r.saved ? 7 : 6, `${r.width}: expected all populated sections from real data`);
      assert.ok(!r.masked, `${r.width}: desktop fade`);
      assert.equal(r.strip.scrollWidth, r.strip.clientWidth, `${r.width}: scrolling desktop tabs`);
      assert.ok(r.controls.every(c => c.fullyVisible && c.textFits), `${r.width}: clipped controls`);
      assert.ok(r.controls.every(c => Math.abs(c.y + c.height / 2 - r.controls[0].y - r.controls[0].height / 2) < 1), `${r.width}: multiple rows`);
    }
    if (r.width < 1180) assert.ok(r.controls.every(c => c.height >= 44), `${r.width}: touch targets under 44px`);
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

// Rendered check for the repository tile and the page's language, run by hand (not part of the unittest suite):
//   python -m http.server 8805 --bind 127.0.0.1 --directory site
//   node tests/capture_repo_tile.mjs --out <dir> [--url http://127.0.0.1:8805/] [--profile <dir>]
// Chrome headless on a fresh profile (never an existing browser). Writes to <dir>:
//   - page-1440.png / page-375.png: the first screen at each width, plus full-page captures;
//   - tile-<view>-<window>.png (1440) and tile-<view>-<window>-375.png: the repository tile for each list and window;
//   - rendered.json: per width, document.scrollWidth against innerWidth, the four repositories each tile view
//     shows, and every visible text node and aria-label/title/alt of the rendered page and the token page, so
//     tests/test_vietnamese_ui.py's word rule can be applied to what a reader actually sees.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg('--url', 'http://127.0.0.1:8805/');
const OUT = arg('--out', null);
if (!OUT) { console.error('missing --out <dir>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });
const PROFILE = path.resolve(arg('--profile', path.join(OUT, 'chrome-profile')));
fs.rmSync(PROFILE, { recursive: true, force: true });
fs.mkdirSync(PROFILE, { recursive: true });

const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(p => fs.existsSync(p));
if (!CHROME) { console.error('Chrome not found'); process.exit(2); }
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--user-data-dir=${PROFILE}`, '--remote-debugging-port=0', 'about:blank'], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function devtoolsUrl() {
  const f = path.join(PROFILE, 'DevToolsActivePort');
  for (let i = 0; i < 150; i++) { if (fs.existsSync(f)) { const [port, p] = fs.readFileSync(f, 'utf8').split('\n'); if (p) return `ws://127.0.0.1:${port}${p.trim()}`; } await sleep(100); }
  throw new Error('Chrome did not open a DevTools port');
}
let ws, seq = 0;
const pending = new Map();
const send = (method, params = {}, sessionId) => { const id = ++seq; ws.send(JSON.stringify({ id, method, params, sessionId })); return new Promise((res, rej) => pending.set(id, { res, rej, method })); };

/* Every text a reader can see or hear: visible text nodes outside <code>/<kbd>/<script>/<style>, plus labels. */
const COLLECT = `(() => {
  const out = new Set();
  const skip = el => el.closest('code,kbd,script,style,svg,[hidden],[aria-hidden="true"]:not(.av)');
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) { const t = n.textContent.trim(); if (t && !skip(n.parentElement) && n.parentElement.getClientRects().length) out.add(t); }
  document.querySelectorAll('[aria-label],[title],[alt]').forEach(el => { if (el.closest('script,style,svg')) return;
    for (const a of ['aria-label', 'title', 'alt']) { const v = (el.getAttribute(a) || '').trim(); if (v) out.add(v); } });
  out.add(document.title);
  return [...out];
})()`;

async function main() {
  ws = new WebSocket(await devtoolsUrl());
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = m => { const j = JSON.parse(m.data); const p = pending.get(j.id); if (!p) return; pending.delete(j.id); j.error ? p.rej(new Error(`${p.method}: ${j.error.message}`)) : p.res(j.result); };

  async function openPage(url, width, mobile) {
    const height = mobile ? 812 : 900;
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    const s = (m, p) => send(m, p, sessionId);
    await s('Page.enable');
    await s('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
    await s('Emulation.setScrollbarsHidden', { hidden: true });
    await s('Page.navigate', { url });
    const evaluate = async expr => {
      const r = await s('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(`evaluate: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
      return r.result.value;
    };
    const png = async (file, clip) => {
      const r = await s('Page.captureScreenshot', clip ? { format: 'png', clip: { ...clip, scale: 1 }, captureBeyondViewport: true } : { format: 'png' });
      fs.writeFileSync(path.join(OUT, file), Buffer.from(r.data, 'base64'));
    };
    const full = async file => {
      let h = height;
      for (let i = 0; i < 3; i++) {
        const m = await s('Page.getLayoutMetrics'); const ch = Math.ceil((m.cssContentSize || m.contentSize).height);
        if (ch === h) break; h = ch;
        await s('Emulation.setDeviceMetricsOverride', { width, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile }); await sleep(800);
      }
      await png(file);
      await s('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile }); await sleep(400);
    };
    return { s, evaluate, png, full, targetId };
  }
  const ready = async page => {
    for (let i = 0; i < 150; i++) { if (await page.evaluate(`!!document.querySelector('#board') && !document.querySelector('#board').classList.contains('is-loading') && !!document.querySelector('#chapters .ch')`)) break; await sleep(200); }
    await page.evaluate('document.fonts.ready.then(() => true)'); await sleep(1200);
  };
  const tileRepos = `[...document.querySelectorAll('#board .t-repo [data-repo]')].map(el => el.dataset.repo)`;
  const click = async (page, sel) => { await page.evaluate(`document.querySelector(${JSON.stringify(sel)}).click()`); await sleep(500); };

  const result = { url: URL_, widths: {} };
  for (const [width, mobile] of [[1440, false], [375, true]]) {
    const page = await openPage(URL_, width, mobile);
    await ready(page);
    await page.evaluate(`localStorage.clear(), true`);
    const r = { overflow: await page.evaluate(`({scrollWidth: document.documentElement.scrollWidth, innerWidth})`), tiles: {} };
    await page.png(`page-${width}.png`);
    await page.full(`page-${width}-full.png`);
    for (const view of ['trending', 'stars', 'usable']) {
      await click(page, `#board [data-repo-view="${view}"]`);
      const seconds = view === 'stars' ? ['stars', 'forks'] : ['day', 'week', 'month'];
      for (const second of seconds) {
        await click(page, `#board ${view === 'stars' ? `[data-repo-total="${second}"]` : `[data-repo-window="${second}"]`}`);
        r.tiles[`${view}-${second}`] = await page.evaluate(tileRepos);
        {
          const box = await page.evaluate(`(() => { const b = document.querySelector('#board .t-repo').getBoundingClientRect(); return {x: b.x + scrollX, y: b.y + scrollY, width: b.width, height: b.height}; })()`);
          await page.png(`tile-${view}-${second}${width === 1440 ? "" : "-375"}.png`, box);
        }
      }
    }
    await click(page, `#board [data-repo-view="trending"]`);
    await click(page, `#board [data-repo-window="day"]`);
    r.overflowAfter = await page.evaluate(`({scrollWidth: document.documentElement.scrollWidth, innerWidth})`);
    // Open one repository sheet so its labels are part of the language scan.
    await page.evaluate(`document.querySelector('#board .repo-hero').click(), true`); await sleep(600);
    await page.png(`sheet-${width}.png`);
    r.texts = await page.evaluate(COLLECT);
    result.widths[width] = r;
    await send('Target.closeTarget', { targetId: page.targetId });
  }
  const tk = await openPage(new URL('tokens.html', URL_).href, 1440, false);
  for (let i = 0; i < 100; i++) { if (await tk.evaluate(`!!document.querySelector('#comp .tile')`)) break; await sleep(200); }
  await sleep(1200);
  result.tokensTexts = await tk.evaluate(COLLECT);
  await tk.full('tokens-1440.png');
  fs.writeFileSync(path.join(OUT, 'rendered.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ overflow: Object.fromEntries(Object.entries(result.widths).map(([w, r]) => [w, r.overflow])), tiles1440: result.widths[1440].tiles }, null, 1));
}

main().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => { try { ws && ws.close(); } catch { /* closing */ } chrome.kill(); });

// First-rows measurement of the Bento board, run by hand (not part of the unittest suite):
//   python -m http.server 8807 --bind 127.0.0.1 --directory site
//   node tests/measure_first_rows.mjs --out <dir> [--url http://127.0.0.1:8807/] [--widths 1440,1100,768]
// For each width it starts Chrome headless on a fresh throwaway profile, opens the page, writes
// <dir>/page-<width>.png and prints, for every tile of the first two board rows, its box and the largest
// vertical gap between consecutive direct children (the "hole" a reader sees inside a tile).
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg('--url', 'http://127.0.0.1:8807/');
const OUT = arg('--out', null);
const WIDTHS = arg('--widths', '1440,1100,768').split(',').map(Number);
if (!OUT) { console.error('missing --out <dir>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome'].find(p => fs.existsSync(p));
if (!CHROME) { console.error('Chrome not found'); process.exit(2); }

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function measureAt(width) {
  const profile = fs.mkdtempSync(path.join(process.env.PROFILE_DIR || OUT, 'profile-'));
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: 'ignore' });
  try {
    const f = path.join(profile, 'DevToolsActivePort');
    let wsUrl = null;
    for (let i = 0; i < 100 && !wsUrl; i++) {
      if (fs.existsSync(f)) { const [port, p] = fs.readFileSync(f, 'utf8').split('\n'); if (p) wsUrl = `ws://127.0.0.1:${port}${p.trim()}`; }
      if (!wsUrl) await sleep(100);
    }
    if (!wsUrl) throw new Error('Chrome did not open a DevTools port');
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let seq = 0; const pending = new Map();
    ws.onmessage = m => { const j = JSON.parse(m.data); const p = pending.get(j.id); if (!p) return; pending.delete(j.id); j.error ? p.rej(new Error(`${p.method}: ${j.error.message}`)) : p.res(j.result); };
    const send = (method, params = {}, sessionId) => { const id = ++seq; ws.send(JSON.stringify({ id, method, params, sessionId })); return new Promise((res, rej) => pending.set(id, { res, rej, method })); };
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    const s = (m, p) => send(m, p, sessionId);
    await s('Page.enable');
    await s('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await s('Emulation.setScrollbarsHidden', { hidden: true });
    await s('Page.navigate', { url: URL_ });
    const evaluate = async expr => {
      const r = await s('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(`evaluate: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
      return r.result.value;
    };
    let ready = false;
    for (let i = 0; i < 100 && !ready; i++) { ready = await evaluate(`!!document.querySelector('#board') && !document.querySelector('#board').classList.contains('is-loading')`); if (!ready) await sleep(200); }
    if (!ready) throw new Error('board never finished loading');
    await evaluate('document.fonts.ready.then(() => true)');
    await sleep(1500);   // tile-in animation (300ms + 60ms per tile)

    const tiles = await evaluate(`(() => {
      const board = document.querySelector('#board');
      const ts = [...board.children].filter(e => e.classList.contains('tile'));
      const top0 = Math.min(...ts.map(t => t.getBoundingClientRect().top));
      // first two visual rows: tiles whose top lies within the lead's height before the 3rd row begins
      const rows = [...new Set(ts.map(t => Math.round(t.getBoundingClientRect().top)))].sort((a, b) => a - b);
      const rowLimit = rows[2] === undefined ? Infinity : rows[2];
      return ts.filter(t => Math.round(t.getBoundingClientRect().top) < rowLimit).map(t => {
        const r = t.getBoundingClientRect();
        const kids = [...t.children].map(c => c.getBoundingClientRect()).filter(k => k.height > 0).sort((a, b) => a.top - b.top);
        let maxGap = 0, at = null;
        for (let i = 1; i < kids.length; i++) { const g = kids[i].top - kids[i - 1].bottom; if (g > maxGap) { maxGap = g; at = i; } }
        const trailing = kids.length ? Math.round(r.bottom - parseFloat(getComputedStyle(t).paddingBottom) - kids[kids.length - 1].bottom) : 0;
        return { tile: t.className.replace(/\\btile\\b|ready/g, '').trim(), x: Math.round(r.left), y: Math.round(r.top - top0), w: Math.round(r.width), h: Math.round(r.height), maxGap: Math.round(maxGap), gapAfterChild: at, trailingEmpty: trailing };
      });
    })()`);
    // Full page: grow the viewport to the content instead of captureBeyondViewport.
    let height = 900;
    for (let i = 0; i < 3; i++) {
      const m = await s('Page.getLayoutMetrics');
      const h = Math.ceil((m.cssContentSize || m.contentSize).height);
      if (h === height) break;
      height = h;
      await s('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await sleep(800);
    }
    const shot = await s('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(OUT, `page-${width}.png`), Buffer.from(shot.data, 'base64'));
    ws.close();
    return tiles;
  } finally {
    chrome.kill();
  }
}

for (const w of WIDTHS) {
  console.log(`--- ${w}px`);
  console.table(await measureAt(w));
}
process.exit(0);

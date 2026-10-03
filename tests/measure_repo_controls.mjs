// Rendered measurement of the repository tile's list and window controls, run by hand (not part of the unittest suite):
//   python -m http.server 8808 --bind 127.0.0.1 --directory site
//   node tests/measure_repo_controls.mjs --out <dir> --tag <name> [--url http://127.0.0.1:8808/] [--profile <dir>] [--dark] [--chapter] [--no-walk]
// Chrome headless on a fresh profile (never an existing browser). For 1440 and 375 it writes <tag>-<width>.png (the
// tile) and prints, as JSON:
//   - controls: the height the controls take inside the tile, measured as the distance from the bottom of the tile
//     heading to the top of the first repository, and the union box of every control element;
//   - targets: width and height of every interactive control, so the 44px phone floor is checked on the render;
//   - lists: for every list and window, the repositories the tile shows (the count must stay 4) and the state the
//     controls announce (aria-pressed / selected value).
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg('--url', 'http://127.0.0.1:8808/');
const OUT = arg('--out', null);
const TAG = arg('--tag', 'tile');
const WALK = !process.argv.includes('--no-walk');
const DARK = process.argv.includes('--dark');        // also capture the tile in the dark theme
const CHAPTER = process.argv.includes('--chapter');  // also capture the top of the repository chapter
if (!OUT) { console.error('missing --out <dir>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });
const PROFILE = path.resolve(arg('--profile', path.join(OUT, `chrome-profile-${TAG}`)));
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

/* Controls are found by role, not by class, so the old chip rows and any new control are measured the same way. */
const MEASURE = `(() => {
  const tile = document.querySelector('#board .t-repo');
  if (!tile) throw new Error('no repository tile');
  const head = tile.querySelector('.tile-h').getBoundingClientRect();
  const hero = tile.querySelector('.repo-hero');
  const ctl = [...tile.querySelectorAll('[data-repo-view],[data-repo-window],[data-repo-total],select')].filter(e => e.getClientRects().length);
  const boxes = ctl.map(e => e.getBoundingClientRect());
  const top = Math.min(...boxes.map(b => b.top)), bottom = Math.max(...boxes.map(b => b.bottom));
  const tb = tile.getBoundingClientRect();
  /* Contrast from the rendered colours: each CSS colour is painted on a 1px canvas and read back as sRGB. */
  const cv = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  const rgb = c => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = '#fff'; cv.fillRect(0, 0, 1, 1); cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); return [...cv.getImageData(0, 0, 1, 1).data].slice(0, 3); };
  const lum = c => { const [r, g, b] = rgb(c).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return Math.round((x + 0.05) / (y + 0.05) * 100) / 100; };
  const bgOf = e => { for (let n = e; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; } return 'white'; };
  const track = tile.querySelector('.seg');
  return {
    contrast: ctl.map(e => ({text: e.textContent.trim(), pressed: e.getAttribute('aria-pressed'), ratio: ratio(getComputedStyle(e).color, bgOf(e))})),
    thumbVsTrack: track && tile.querySelector('.seg [aria-pressed="true"]') ? ratio(getComputedStyle(tile.querySelector('.seg [aria-pressed="true"]')).backgroundColor, getComputedStyle(track).backgroundColor) : null,
    trackVsTile: track ? ratio(getComputedStyle(track).backgroundColor, bgOf(tile)) : null,
    tile: {width: Math.round(tb.width), height: Math.round(tb.height)},
    headToHero: hero ? Math.round(hero.getBoundingClientRect().top - head.bottom) : null,
    controlsBox: Math.round(bottom - top),
    controlCount: ctl.length,
    targets: ctl.map(e => { const b = e.getBoundingClientRect(), cs = getComputedStyle(e, '::before');
      const pad = cs.content !== 'none' && cs.position === 'absolute' ? {t: parseFloat(cs.top) || 0, b: parseFloat(cs.bottom) || 0, l: parseFloat(cs.left) || 0, r: parseFloat(cs.right) || 0} : {t: 0, b: 0, l: 0, r: 0};
      return {text: (e.textContent || e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 24), w: Math.round(b.width), h: Math.round(b.height),
        hitW: Math.round(b.width - pad.l - pad.r), hitH: Math.round(b.height - pad.t - pad.b)}; }),
    heading: tile.querySelector('.tile-h h2').textContent.trim(),
    scroll: {scrollWidth: document.documentElement.scrollWidth, innerWidth},
  };
})()`;
const STATE = `(() => {
  const tile = document.querySelector('#board .t-repo');
  const on = [...tile.querySelectorAll('[aria-pressed="true"][data-repo-view],[aria-pressed="true"][data-repo-window],[aria-pressed="true"][data-repo-total]')].map(e => e.textContent.trim());
  const sel = [...tile.querySelectorAll('select')].map(s => s.options[s.selectedIndex] && s.options[s.selectedIndex].text);
  return {repos: [...tile.querySelectorAll('[data-repo]')].map(e => e.dataset.repo), on, sel, empty: (tile.querySelector('.empty-note') || {}).textContent || ''};
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
      const r = await s('Page.captureScreenshot', { format: 'png', clip: { ...clip, scale: 1 }, captureBeyondViewport: true });
      fs.writeFileSync(path.join(OUT, file), Buffer.from(r.data, 'base64'));
    };
    return { s, evaluate, png, targetId };
  }
  const ready = async page => {
    for (let i = 0; i < 150; i++) { if (await page.evaluate(`!!document.querySelector('#board .t-repo') && !!document.querySelector('#chapters .ch')`)) break; await sleep(200); }
    await page.evaluate('document.fonts.ready.then(() => true)'); await sleep(1500);
  };
  const tileBox = `(() => { const b = document.querySelector('#board .t-repo').getBoundingClientRect(); return {x: b.x + scrollX, y: b.y + scrollY, width: b.width, height: b.height}; })()`;
  /* Choose a list or window the way a reader does: a click on a button, or a change on a menu. */
  const choose = (kind, value) => `(() => {
    const tile = document.querySelector('#board .t-repo');
    const b = tile.querySelector('[data-repo-' + ${JSON.stringify(kind)} + '="' + ${JSON.stringify(value)} + '"]');
    if (b && b.tagName !== 'OPTION') { b.click(); return 'click'; }
    const s = [...tile.querySelectorAll('select')].find(s => [...s.options].some(o => o.value === ${JSON.stringify(value)} && o.dataset.kind === ${JSON.stringify(kind)}));
    if (!s) return 'missing';
    s.value = ${JSON.stringify(value)}; s.dispatchEvent(new Event('change', {bubbles: true})); return 'change';
  })()`;

  const result = { url: URL_, tag: TAG, widths: {} };
  for (const [width, mobile] of [[1440, false], [375, true]]) {
    const page = await openPage(URL_, width, mobile);
    await ready(page);
    await page.evaluate(`localStorage.clear(), location.reload(), true`);
    await sleep(500); await ready(page);
    const r = await page.evaluate(MEASURE);
    // Logos load lazily: bring the tile into view first, or a phone capture shows empty avatar slots.
    const shot = async name => { await page.evaluate(`document.querySelector('#board .t-repo').scrollIntoView({block: 'center'}), true`); await sleep(1500);
      await page.png(name, await page.evaluate(tileBox)); };
    await shot(`${TAG}-${width === 1440 ? '1440' : 'phone'}.png`);
    if (DARK) {
      await page.evaluate(`localStorage.setItem('air2:theme', '"dark"'), location.reload(), true`); await sleep(500); await ready(page);
      await shot(`${TAG}-${width === 1440 ? '1440' : 'phone'}-dark.png`);
      await page.evaluate(`localStorage.removeItem('air2:theme'), location.reload(), true`); await sleep(500); await ready(page);
    }
    if (CHAPTER) {
      await page.evaluate(`document.querySelector('#repo').scrollIntoView(), true`); await sleep(1500);
      const ch = await page.evaluate(`(() => { const b = document.querySelector('#repo').getBoundingClientRect(); return {x: b.x + scrollX, y: Math.max(0, b.y + scrollY - 160), width: b.width, height: Math.min(b.height, 600) + 160}; })()`);
      await page.png(`${TAG}-${width === 1440 ? '1440' : 'phone'}-chapter.png`, ch);
    }
    if (WALK) {
      r.lists = {};
      for (const [view, seconds, kind] of [['trending', ['day', 'week', 'month'], 'window'], ['stars', ['stars', 'forks'], 'total'], ['usable', ['day', 'week', 'month'], 'window']]) {
        const how = await page.evaluate(choose('view', view)); await sleep(400);
        for (const second of seconds) {
          const how2 = await page.evaluate(choose(kind, second)); await sleep(400);
          r.lists[`${view}-${second}`] = { how: `${how}/${how2}`, ...(await page.evaluate(STATE)), controlsBox: (await page.evaluate(MEASURE)).controlsBox };
        }
      }
      await page.evaluate(choose('view', 'trending')); await sleep(300);
      await page.evaluate(choose('window', 'day')); await sleep(300);
      r.scrollAfter = await page.evaluate(`({scrollWidth: document.documentElement.scrollWidth, innerWidth})`);
    }
    result.widths[width] = r;
    await send('Target.closeTarget', { targetId: page.targetId });
  }
  fs.writeFileSync(path.join(OUT, `${TAG}.json`), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 1));
}

main().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => { try { ws && ws.close(); } catch { /* closing */ } chrome.kill(); });

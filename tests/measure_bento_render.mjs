// Rendered-page measurement for the Bento page, run by hand (not part of the unittest suite):
//   python -m http.server 8801 --bind 127.0.0.1 --directory site
//   node tests/measure_bento_render.mjs --out <dir> [--url http://127.0.0.1:8801/]
// It starts Chrome headless on a fresh, throwaway profile (never an existing browser), opens the page at
// 1440x900, and writes <dir>/page-1440.png, <dir>/tokens-1440.png and <dir>/measure.json with:
//   - styles: computed values of the elements whose literals moved into tokens.css (they must not change);
//   - focusAfterSave: S on a focused board row keeps focus on that row, and J then moves to the next row;
//   - expandAfterSave: a list opened with "Xem thêm" stays open after S re-renders the chapters.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg('--url', 'http://127.0.0.1:8801/');
const OUT = arg('--out', null);
if (!OUT) { console.error('missing --out <dir>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const CHROME = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find(p => fs.existsSync(p));
if (!CHROME) { console.error('Chrome not found'); process.exit(2); }

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bento-measure-'));
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function devtoolsPort() {
  const f = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100; i++) { if (fs.existsSync(f)) { const [port, p] = fs.readFileSync(f, 'utf8').split('\n'); if (p) return `ws://127.0.0.1:${port}${p.trim()}`; } await sleep(100); }
  throw new Error('Chrome did not open a DevTools port');
}

let ws, seq = 0;
const pending = new Map();
function send(method, params = {}, sessionId) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params, sessionId }));
  return new Promise((res, rej) => pending.set(id, { res, rej, method }));
}

async function main() {
  ws = new WebSocket(await devtoolsPort());
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = m => { const j = JSON.parse(m.data); const p = pending.get(j.id); if (!p) return; pending.delete(j.id); j.error ? p.rej(new Error(`${p.method}: ${j.error.message}`)) : p.res(j.result); };

  async function openPage(url) {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    const s = (m, p) => send(m, p, sessionId);
    await s('Page.enable');
    await s('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    // No scrollbar: a full-page capture would otherwise drop it mid-shot and change every vw-based size.
    await s('Emulation.setScrollbarsHidden', { hidden: true });
    await s('Page.navigate', { url });
    const evaluate = async expr => {
      const r = await s('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(`evaluate: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
      return r.result.value;
    };
    const key = async k => {
      const code = 'Key' + k.toUpperCase();
      await s('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code, text: k, windowsVirtualKeyCode: k.toUpperCase().charCodeAt(0) });
      await s('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: k.toUpperCase().charCodeAt(0) });
      await sleep(150);
    };
    const shot = async file => {
      await sleep(1500);
      // Grow the viewport to the page instead of captureBeyondViewport, which re-lays the page out mid-capture
      // and gave a different type size from one run to the next.
      let width = 1440, height = 900;
      for (let i = 0; i < 3; i++) {
        const m = await s('Page.getLayoutMetrics');
        const h = Math.ceil((m.cssContentSize || m.contentSize).height);
        if (h === height) break;
        height = h;
        await s('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
        await sleep(800);
      }
      const r = await s('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(OUT, file), Buffer.from(r.data, 'base64'));
      return { width, height };
    };
    return { s, evaluate, key, shot, targetId };
  }

  const out = {};
  const page = await openPage(URL_);
  for (let i = 0; i < 100; i++) { if (await page.evaluate(`!!document.querySelector('#board') && !document.querySelector('#board').classList.contains('is-loading') && !!document.querySelector('#chapters [data-cap]')`)) break; await sleep(200); }
  await page.evaluate('document.fonts.ready.then(() => true)');

  out.styles = await page.evaluate(`(() => {
    const pick = (sel, props) => { const el = document.querySelector(sel); if (!el) return null; const cs = getComputedStyle(el); return Object.fromEntries(props.map(p => [p, cs.getPropertyValue(p)])); };
    const tmp = document.createElement('div'); tmp.innerHTML = '<span class="av av-md is-fallback" data-mono="AB" style="--mono-h:120;transition:none"></span><span class="av av-xs"></span><span class="av av-sm"></span><span class="av av-lg"></span><span class="av av-xl"></span><span class="datebadge"><b>1</b><span>th 1</span></span>';
    document.body.append(tmp);
    const r = {
      avMd: pick('.av.av-md.is-fallback[data-mono="AB"]', ['background-color', 'color', 'font-size']),
      avXs: pick('.av.av-xs', ['font-size']), avSm: pick('.av.av-sm', ['font-size']), avLg: pick('.av.av-lg', ['font-size']), avXl: pick('.av.av-xl', ['font-size']),
      datebadgeMonth: pick('.datebadge span', ['font-size']),
      cmdCode: pick('.cmd code', ['font-family']),
      nav: pick('.nav', ['mask-image']),
      tabsNum: pick('.tabs .num', ['font-size']),
    };
    document.documentElement.dataset.theme = 'dark';
    r.avMdDark = pick('.av.av-md.is-fallback[data-mono="AB"]', ['background-color', 'color']);
    delete document.documentElement.dataset.theme;
    tmp.remove();
    return r;
  })()`);

  // S on a focused board row, then J.
  out.focusAfterSave = await page.evaluate(`(() => {
    const vis = el => el.getClientRects().length && !el.closest('[hidden]') && !el.closest('#sheet');
    const el = [...document.querySelectorAll('#board button[data-sel]')].find(e => e.dataset.sel && vis(e));
    el.focus();
    window.__k = el.dataset.sel;
    const list = [...document.querySelectorAll('[data-sel],[data-repo]')].filter(e => e.dataset.sel !== '' && vis(e) && getComputedStyle(e).visibility !== 'hidden');
    const i = list.indexOf(el);
    window.__next = list[i + 1] ? (list[i + 1].dataset.sel || 'repo:' + list[i + 1].dataset.repo) : null;
    return {key: window.__k, expectedNext: window.__next};
  })()`);
  await page.key('s');
  Object.assign(out.focusAfterSave, await page.evaluate(`(() => { const a = document.activeElement; return {afterS: a === document.body ? 'BODY' : (a.dataset.sel || a.tagName), savedMark: !!document.querySelector('[data-sel="' + CSS.escape(window.__k) + '"]')}; })()`));
  await page.key('j');
  Object.assign(out.focusAfterSave, await page.evaluate(`(() => { const a = document.activeElement.closest('[data-sel],[data-repo]'); return {afterJ: a ? (a.dataset.sel || 'repo:' + a.dataset.repo) : 'NONE'}; })()`));
  out.focusAfterSave.pass = out.focusAfterSave.afterS === out.focusAfterSave.key && out.focusAfterSave.afterJ === out.focusAfterSave.expectedNext;
  // Undo the save so the screenshot shows the page as a first visit would.
  await page.evaluate(`document.querySelector('[data-sel="' + CSS.escape(window.__k) + '"]').focus()`);
  await page.key('s');

  // "Xem thêm" on the first capped chapter list, then S on a row inside that list.
  out.expandAfterSave = await page.evaluate(`(() => {
    const btn = document.querySelector('#chapters .expand');
    if (!btn) return {skipped: 'no capped list'};
    const list = btn.previousElementSibling, sec = list.closest('section').id;
    btn.click();
    window.__sec = sec;
    const row = [...list.children].reverse().find(k => !k.hidden);
    const target = row.matches('[data-sel],[data-repo]') ? row : row.querySelector('[data-sel],[data-repo]');
    target.focus();
    return {section: sec, rows: list.children.length, hiddenAfterClick: [...list.children].filter(k => k.hidden).length};
  })()`);
  if (!out.expandAfterSave.skipped) {
    await page.key('s');
    Object.assign(out.expandAfterSave, await page.evaluate(`(() => { const list = document.querySelector('#' + window.__sec + ' [data-cap]'); return {hiddenAfterSave: [...list.children].filter(k => k.hidden).length, expandButtonBack: !!document.querySelector('#' + window.__sec + ' .expand')}; })()`));
    out.expandAfterSave.pass = out.expandAfterSave.hiddenAfterSave === 0 && !out.expandAfterSave.expandButtonBack;
    await page.key('s');
  }

  // The checks above may leave a saved story behind (the old page lost focus after S, so the undo missed);
  // clear this throwaway profile's storage so the screenshot is a first visit either way.
  await page.evaluate('localStorage.clear(), true');
  // A fresh profile, reloaded so the screenshot carries no expanded list or focus ring from the checks above.
  // Reduced motion, so the screenshot never lands mid-animation and two runs can be compared.
  const fresh = await openPage('about:blank');
  await fresh.s('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await fresh.s('Page.navigate', { url: URL_ });
  for (let i = 0; i < 100; i++) { if (await fresh.evaluate(`!!document.querySelector('#board') && !document.querySelector('#board').classList.contains('is-loading')`)) break; await sleep(200); }
  await fresh.evaluate('document.fonts.ready.then(() => true)');
  await sleep(3000);
  // Layout: every tile, heading, row and logo as (selector, box, text), to compare two builds without pixel noise
  // from relative times and late-loading images.
  out.layout = await fresh.evaluate(`[...document.querySelectorAll('.tile, h1, h2, h3, .row, .ev-row, .av, .num, .btn, .chip')].map(el => {
    const r = el.getBoundingClientRect();
    return [el.tagName + '.' + [...el.classList].join('.'), Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height), el.matches('.av') ? (el.dataset.mono || '') + (el.querySelector('img') ? ':img' : '') : ''];
  })`);
  out.pageShot = await fresh.shot('page-1440.png');
  const tk = await openPage(new URL('tokens.html', URL_).href);
  await sleep(1500);
  out.tokensShot = await tk.shot('tokens-1440.png');

  fs.writeFileSync(path.join(OUT, 'measure.json'), JSON.stringify(out, null, 2));
  console.log(JSON.stringify(out, null, 2));
}

main().catch(e => { console.error(e.stack || String(e)); process.exitCode = 1; }).finally(async () => {
  // Browser.close ends every Chrome process of this profile; killing only the parent left its children running.
  try { if (ws && ws.readyState === 1) await Promise.race([send('Browser.close'), sleep(3000)]); } catch { /* already closing */ }
  try { ws && ws.close(); } catch { /* closing */ }
  chrome.kill();
  await sleep(1000);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still hold a file; the OS temp cleaner takes it */ }
});

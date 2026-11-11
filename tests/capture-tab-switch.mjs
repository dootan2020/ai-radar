// Switching between the front page's tabs (Trang nhất, Mã và mô hình, Xếp hạng), rendered in headless Chrome from
// site/ and measured: what stays put, what is re-created, what is fetched, and how the frames run during a switch.
//   node tests/capture-tab-switch.mjs [--data <dir>] [--site <dir>] [--out <dir>] [--only <width>[,<width>]]
// <dir> holds a downloaded radar-window.json, radar-ui.json and field-rankings.json (the live snapshot). Without --data
// the page reads tests/fixtures/radar-window-sample.json offline; this is how tests/test_tab_switch.py runs it.
// Widths: 1440x900, 2000x1200, 2560x1440 and a 375x812 touch phone. With --out, one screenshot per tab at 2000x1200.
// One JSON line on stdout: per width, per tab the page's client width, the header's, tab row's and panel's boxes, the
// panel's height, the document's height, the URL hash and the underline's box; the shell nodes that were replaced or
// moved; the requests each switch made; the frames during each switch; Back, Forward and reload.
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const only = String(arg('--only', '')).split(',').filter(Boolean).map(Number);   // e.g. --only 2000,375
const dataDir = arg('--data', '');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const siteDir = path.resolve(arg('--site', path.join(root, 'site')));
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    let file;
    if (!dataDir && /^\/data\/radar(-window)?\.json$/.test(p)) file = path.join(root, 'tests/fixtures/radar-window-sample.json');
    else if (!dataDir && p.startsWith('/data/')) { res.writeHead(404); return res.end(); }
    else if (p.startsWith('/data/')) file = path.join(dataDir, path.basename(p));
    else if (p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    else {
      file = path.join(siteDir, p.endsWith('/') ? p + 'index.html' : p);
      if (!file.startsWith(siteDir)) throw new Error('outside');
    }
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const stand = await fs.readFile(path.join(root, 'site/og-image.png'));

// Every layout shift, input or not: a click is input, and a tab switch must not shift the shell either way.
const EARLY = () => {
  window.__shifts = [];
  new PerformanceObserver(list => { for (const e of list.getEntries()) window.__shifts.push(e.value); })
    .observe({ type: 'layout-shift', buffered: true });
};

// The shell's nodes, kept by reference before the first switch; every later state compares against them.
const KEEP = () => {
  const q = s => document.querySelector(s);
  window.__shell = { panel: q('#top'), bar: q('#bar'), brand: q('#brand'), tabs: q('#feed-filters'),
    chips: [...document.querySelectorAll('#feed-filters .filter-chip')], edition: q('.ed-link'),
    sort: q('#sort-switch'), sortBtns: [...document.querySelectorAll('#sort-switch .sort-btn')], dock: q('.mobile-nav'),
    line: q('#feed-filters > .tab-pill'), cards: [...document.querySelectorAll('#feed-grid .nc')] };
  window.__added = []; window.__removed = [];
  const name = n => n.nodeType === 1 ? (n.id ? '#' + n.id : n.className ? '.' + String(n.className).split(' ')[0] : n.tagName) : '#text';
  const watch = new MutationObserver(list => {
    for (const m of list) {
      for (const n of m.addedNodes) window.__added.push(name(n));
      for (const n of m.removedNodes) window.__removed.push(name(n));
    }
  });
  for (const el of [q('#bar'), q('.mobile-nav')].filter(Boolean)) watch.observe(el, { childList: true, subtree: true });
};

const STATE = () => {
  const r = el => el && el.getBoundingClientRect();
  const box = el => { const b = r(el); return b ? { x: +b.left.toFixed(2), y: +(b.top + scrollY).toFixed(2), w: +b.width.toFixed(2), h: +b.height.toFixed(2) } : null; };
  const q = s => document.querySelector(s);
  const active = q('#feed-filters .filter-chip[aria-pressed="true"]');
  const line = q('#feed-filters > .tab-pill');
  const lineBox = line && getComputedStyle(line).display !== 'none' && getComputedStyle(line).opacity !== '0' ? box(line) : null;
  // The underline, wherever it is drawn: a sliding element, or the pressed tab's ::after.
  let after = null;
  if (active) {
    const s = getComputedStyle(active, '::after');
    if (s.content !== 'none' && s.display !== 'none') {
      const b = r(active);
      after = { x: +(b.left + parseFloat(s.left)).toFixed(2), w: +parseFloat(s.width).toFixed(2) };
    }
  }
  const shell = window.__shell || {};
  const same = (k, sel) => shell[k] ? shell[k] === q(sel) && shell[k].isConnected : null;
  return {
    hash: location.hash, active: active && active.dataset.filter, clientWidth: document.documentElement.clientWidth, bodyWidth: document.body.clientWidth,
    innerWidth, docHeight: document.documentElement.scrollHeight, scrollY: Math.round(scrollY),
    gutter: getComputedStyle(document.documentElement).scrollbarGutter, overflowY: getComputedStyle(document.documentElement).overflowY,
    bar: box(q('#bar')), tabs: box(q('#feed-filters')), panel: box(q('#top')), grid: box(q('#feed-grid')),
    chips: [...document.querySelectorAll('#feed-filters .filter-chip')].map(c => box(c)),
    line: lineBox ? { x: lineBox.x, w: lineBox.w, transform: getComputedStyle(line).transform, width: line.style.width } : null,
    after, activeBox: box(active),
    kept: shell.panel ? { panel: same('panel', '#top'), bar: same('bar', '#bar'), brand: same('brand', '#brand'),
      tabs: same('tabs', '#feed-filters'), edition: same('edition', '.ed-link'),
      sort: same('sort', '#sort-switch'), dock: shell.dock ? same('dock', '.mobile-nav') : null,
      chips: shell.chips.every((c, i) => c === document.querySelectorAll('#feed-filters .filter-chip')[i] && c.isConnected),
      sortBtns: shell.sortBtns.every(b => b.isConnected && b.parentElement === q('#sort-switch')),
      line: shell.line ? shell.line === line && line.isConnected : null } : null,
    // On the front page: are its story cards the very nodes drawn at load (kept, not drawn again)?
    cardsKept: shell.cards && active && active.dataset.filter === 'all' ? shell.cards.length > 0 && shell.cards.every(c => c.isConnected)
      && document.querySelectorAll('#feed-grid .nc').length >= shell.cards.length : null,
    added: window.__added ? [...window.__added] : null, removed: window.__removed ? [...window.__removed] : null,
  };
};

// Frames during a switch: from just before the click until 900 ms after it, every rAF's gap, the tab row's and the
// header's left edge (they must not move), and the underline's box (it should glide).
const ARM = () => {
  window.__frames = []; window.__shifts = [];
  const q = s => document.querySelector(s);
  let last = performance.now();
  const until = last + 900;
  const step = t => {
    const line = q('#feed-filters > .tab-pill');
    const lb = line ? line.getBoundingClientRect() : null;
    window.__frames.push({ dt: +(t - last).toFixed(2), tabsX: +q('#feed-filters').getBoundingClientRect().left.toFixed(2),
      barX: +q('#bar').getBoundingClientRect().left.toFixed(2), cw: document.body.clientWidth, lineCss: line ? line.style.width : null,
      lineX: lb ? +lb.left.toFixed(2) : null, lineW: lb ? +lb.width.toFixed(2) : null });
    last = t;
    if (t < until) requestAnimationFrame(step);
  };
  requestAnimationFrame(t => { last = t; requestAnimationFrame(step); });
};
const FRAMES = () => {
  const f = window.__frames.slice(1);
  const dts = f.map(x => x.dt);
  const xs = new Set(f.map(x => x.tabsX)), bars = new Set(f.map(x => x.barX)), cws = new Set(f.map(x => x.cw));
  const lineXs = f.map(x => x.lineX).filter(x => x !== null);
  return { frames: f.length, longest: Math.max(...dts), over16: dts.filter(d => d > 16.7).length, over33: dts.filter(d => d > 33.4).length,
    tabsMoved: xs.size > 1, barMoved: bars.size > 1, widthChanged: cws.size > 1,
    lineSteps: new Set(lineXs).size, lineWidthSets: new Set(f.map(x => x.lineCss)).size, lineFrom: lineXs[0] ?? null, lineTo: lineXs[lineXs.length - 1] ?? null,
    shift: +window.__shifts.reduce((a, b) => a + b, 0).toFixed(4) };
};

// Classic scrollbars, as Chrome on Windows draws them: a page's scrollbar takes 15 px from its width (puppeteer hides
// scrollbars by default, which would hide the very jump this measures).
const browser = await puppeteer.launch({ headless: true, executablePath, ignoreDefaultArgs: ['--hide-scrollbars'] });
const sizes = [
  { w: 1440, h: 900 }, { w: 2000, h: 1200 }, { w: 2560, h: 1440 },
  { w: 375, h: 812, phone: true },
].filter(s => !only.length || only.includes(s.w));
const TABS = ['all', 'code', 'rankings', 'all', 'rankings', 'code', 'all'];
const NAMES = { all: 'trang-nhat', code: 'ma-va-mo-hinh', rankings: 'xep-hang' };
const result = {};
try {
  for (const size of sizes) {
    const page = await browser.newPage();
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);
    await page.setViewport({ width: size.w, height: size.h, deviceScaleFactor: 1, isMobile: !!size.phone, hasTouch: !!size.phone });
    await page.setRequestInterception(true);
    await page.setCacheEnabled(true);   // a reader's browser keeps what it fetched; interception alone turns the cache off
    let requests = [];
    page.on('request', req => {
      const u = req.url();
      if (!u.startsWith(site) && !u.startsWith('data:')) { requests.push(u); return req.respond({ status: 200, contentType: 'image/png', body: stand }); }
      if (!u.startsWith('data:')) requests.push(u.slice(site.length - 1));
      req.continue();
    });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e.message).slice(0, 200)));
    await page.evaluateOnNewDocument(EARLY);
    await page.goto(site, { waitUntil: 'networkidle0' });
    await wait(1200);
    const first = await page.evaluate(STATE);
    await page.evaluate(KEEP);
    const states = [], switches = [];
    for (const [i, tab] of TABS.entries()) {
      if (i === 0) { states.push({ tab, ...(await page.evaluate(STATE)) }); continue; }
      requests = [];
      await page.evaluate(ARM);
      await page.click(`#feed-filters .filter-chip[data-filter="${tab}"]`);
      // What is moving right after the click: the underline's glide (a transform transition) and the view's fade.
      const moving = await page.evaluate(() => document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.target
        && a.effect.target.matches('#feed-filters > .tab-pill, #arena, #feed-grid'))
        .map(a => `${a.effect.target.id || 'line'}:${a.transitionProperty || a.animationName}`));
      await wait(1100);
      const frames = { ...(await page.evaluate(FRAMES)), moving };
      const state = await page.evaluate(STATE);
      states.push({ tab, ...state });
      switches.push({ to: tab, requests: requests.filter(u => !u.startsWith('/data/') || true), ...frames });
      if (out && size.w === 2000 && i <= 3) {
        await page.evaluate(() => scrollTo(0, 0));
        await wait(300);
        await page.screenshot({ path: path.join(out, `tab-${NAMES[tab]}-2000.png`) });
      }
    }
    // Back and Forward walk the tabs the reader opened; a reload keeps the tab in the URL.
    const history = [];
    for (const step of ['back', 'back', 'forward']) {
      const moved = await (step === 'back' ? page.goBack({ timeout: 3000 }) : page.goForward({ timeout: 3000 })).then(() => true, e => String(e.message).slice(0, 60));
      await wait(900);
      if (moved !== true) { history.push({ step, failed: moved }); continue; }
      const s = await page.evaluate(STATE);
      history.push({ step, hash: s.hash, active: s.active, line: s.line, activeBox: s.activeBox });
    }
    await page.reload({ waitUntil: 'networkidle0' });
    await wait(1200);
    const reload = await page.evaluate(STATE);
    history.push({ step: 'reload', hash: reload.hash, active: reload.active, line: reload.line, activeBox: reload.activeBox });
    // Resizing keeps the underline under its tab.
    await page.setViewport({ width: size.w - 120, height: size.h, deviceScaleFactor: 1, isMobile: !!size.phone, hasTouch: !!size.phone });
    await wait(700);
    const resized = await page.evaluate(STATE);
    history.push({ step: 'resize', hash: resized.hash, active: resized.active, line: resized.line, activeBox: resized.activeBox });
    // A reader deep in the front page who opens another tab starts it at the panel's top.
    await page.setViewport({ width: size.w, height: size.h, deviceScaleFactor: 1, isMobile: !!size.phone, hasTouch: !!size.phone });
    await page.click('#feed-filters .filter-chip[data-filter="all"]');
    await wait(700);
    await page.evaluate(() => scrollTo({ top: 2400, behavior: 'instant' }));
    await wait(300);
    const deepFrom = await page.evaluate(() => Math.round(scrollY));
    await page.click('#feed-filters .filter-chip[data-filter="code"]');
    await wait(700);
    const deep = { from: deepFrom, ...(await page.evaluate(() => ({ scrollY: Math.round(scrollY), panelTop: Math.round(document.querySelector('#top').getBoundingClientRect().top) }))) };
    // Under reduced motion the underline jumps and the view does not fade.
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.evaluate(ARM);
    await page.click('#feed-filters .filter-chip[data-filter="rankings"]');
    const running = await page.evaluate(() => document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.target
      && (a.effect.target.matches('#feed-filters > .tab-pill, #arena, #feed-grid'))).length);
    await wait(1100);
    const reduced = { ...(await page.evaluate(FRAMES)), running };
    result[size.w] = { first: { hash: first.hash, line: first.line, activeBox: first.activeBox }, states, switches, history, deep, reduced, errors };
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
process.stdout.write(JSON.stringify(result) + '\n');

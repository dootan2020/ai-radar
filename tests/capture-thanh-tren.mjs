// The top row after Edge (captain, 10/11 14:48 and 14:55), in Chrome against this worktree: the site at 375/1440/2000/2560
// in light and dark, "Tùy chỉnh" open at 1440 and 375, each content amount at 1440, the picture turned off (and nothing
// downloaded), the unpacked extension at 1440; the search's and the panel's top at 1440x900 and 2000x1100; the contrast of
// the corners' white ink against the picture behind them, on today's picture and other days of nen/lich.json.
// node tests/capture-thanh-tren.mjs --out thanh-tren-anh
// Same server as tests/capture-nen-edge.mjs: site/ from disk, every data/*.json is tests/fixtures/radar-window-sample.json,
// nen/* from the live site (else the packaged picture). Nothing under site/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = path.resolve(root, arg('--out', 'thanh-tren-anh'));
const only = arg('--only', 'site,tc,layout,off,contrast,ext').split(',');
const LIVE = 'https://radar-ai-vn.pages.dev/';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
await fs.mkdir(out, { recursive: true });

const full = JSON.parse(await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8'));
const packaged = await fs.readFile(path.join(root, 'site/anh/nen-du-phong.webp'));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
let lichLive = null;
try { lichLive = await (await fetch(LIVE + 'nen/lich.json', { signal: AbortSignal.timeout(10000) })).json(); } catch { lichLive = null; }
const nenLog = [];
let lichOverride = null;   // one day's file, served as today's entry (the contrast pass)
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p.startsWith('/nen/')) {
      nenLog.push(p);
      if (p.endsWith('lich.json') && lichOverride) {
        const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' }).format(new Date());
        res.writeHead(200, { 'content-type': TYPES['.json'], 'cache-control': 'no-store' });
        return res.end(JSON.stringify({ days: [{ date: today, file: lichOverride }] }));
      }
      try {
        const live = await fetch(LIVE + p.slice(1), { signal: AbortSignal.timeout(10000) });
        if (!live.ok) throw new Error(String(live.status));
        res.writeHead(200, { 'content-type': live.headers.get('content-type') || TYPES[path.extname(p)], 'cache-control': p.endsWith('.json') ? 'no-store' : 'max-age=3600' });
        return res.end(Buffer.from(await live.arrayBuffer()));
      } catch {
        if (p.endsWith('lich.json')) { res.writeHead(404); return res.end(); }
        res.writeHead(200, { 'content-type': 'image/webp' }); return res.end(packaged);
      }
    }
    if (/^\/data\/[\w.-]+\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(full)); }
    const file = path.join(root, 'site', p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const summary = [], problems = [], contrast = [];
console.log(`server ${url}; snapshot ${full.generated_at}; out ${out}; lich days ${lichLive?.days?.length ?? 'none'}`);

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'thanh-tren-'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, pipe: true, enableExtensions: true,
  userDataDir: profile, args: ['--disable-gpu'], timeout: 20000 });
console.log(`Chrome PID ${browser.process().pid}`);

async function open(width, height, theme, settings = null) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const touch = width < 768;
  await page.setViewport({ width, height, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument((t, seen, s) => {
    localStorage.setItem('air2:theme', JSON.stringify(t));
    localStorage.setItem('air2:lastSeen', JSON.stringify(seen));
    if (s) localStorage.setItem('halcyon:tuy-chinh', JSON.stringify(s)); else localStorage.removeItem('halcyon:tuy-chinh');
  }, theme, full.generated_at, settings);
  page.on('pageerror', e => problems.push(`page error at ${width}px: ${e.message}`));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready') || innerWidth < 768 || document.documentElement.dataset.nen === 'off', { timeout: 15000 }).catch(() => {});
  await page.waitForSelector('.top-wx', { timeout: 10000 }).catch(() => problems.push(`${width}px: the weather never reached the top row`));
  await wait(600);
  return { page, ctx };
}

const measure = page => page.evaluate(() => {
  const r = s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return { l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right), b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height) }; };
  return { search: r('.msn-top .ns-field') ?? r('.msn-top .web-field'), panel: r('.feed-main.front.msn-panel'), now: r('#top-now'),
    tune: r('#tc-open'), launcher: r('.tool-launcher-button'), wx: document.querySelector('#top-now')?.textContent.trim() ?? '',
    radius: getComputedStyle(document.querySelector('.tool-launcher-button')).borderRadius,
    overflow: document.documentElement.scrollWidth > innerWidth,
    smallText: [...document.querySelectorAll('#top-now *, .tc-sheet:not([hidden]) *')].filter(e => e.childNodes.length && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(e).fontSize) < 12 && !e.closest('.sr')).length };
});

// The white ink's worst case: the brightest pixel of the picture (under the veil) behind each piece of text or icon.
async function inkContrast(page, scratch) {
  const boxes = await page.evaluate(() => {
    const boxes = [];
    const add = (name, el) => { if (!el) return; const b = el.getBoundingClientRect(); if (b.width) boxes.push({ name, x: b.left, y: b.top, w: b.width, h: b.height }); };
    add('city', document.querySelector('.top-city')); add('temp', document.querySelector('.top-temp'));
    add('date', document.querySelector('.top-date time')); add('launcher dots', document.querySelector('.tool-launcher-dots'));
    add('tune icon', document.querySelector('#tc-open .i'));
    const ink = getComputedStyle(document.querySelector('.top-date')).color;
    const st = document.createElement('style'); st.id = 'hide-ink';
    st.textContent = '#top-now, #top-now * { color: transparent !important; text-shadow: none !important; } #top-now svg, .tool-launcher-dots, #tc-open .i { visibility: hidden !important; }';
    document.head.append(st);
    return { boxes, ink };
  });
  await wait(100);
  const result = [];
  for (const b of boxes.boxes) {
    const clip = { x: Math.max(0, Math.floor(b.x)), y: Math.max(0, Math.floor(b.y)), width: Math.ceil(b.w), height: Math.ceil(b.h) };
    const png = await page.screenshot({ clip, encoding: 'base64' });
    const stats = await scratch.evaluate(async (data, ink) => {
      const img = new Image(); img.src = 'data:image/png;base64,' + data; await img.decode();
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const g = c.getContext('2d'); g.drawImage(img, 0, 0);
      const px = g.getImageData(0, 0, c.width, c.height).data;
      const lin = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
      const lum = (r, gg, b) => 0.2126 * lin(r) + 0.7152 * lin(gg) + 0.0722 * lin(b);
      const [ir, ig, ib] = ink.match(/\d+/g).map(Number); const L1 = lum(ir, ig, ib);
      const ls = []; for (let i = 0; i < px.length; i += 4) ls.push(lum(px[i], px[i + 1], px[i + 2]));
      ls.sort((a, b) => a - b);
      const ratio = L => { const [hi, lo] = L1 > L ? [L1, L] : [L, L1]; return (hi + 0.05) / (lo + 0.05); };
      return { worst: ratio(ls[ls.length - 1]), p95: ratio(ls[Math.floor(ls.length * 0.95)]), median: ratio(ls[Math.floor(ls.length / 2)]) };
    }, png, boxes.ink);
    result.push({ part: b.name, worst: +stats.worst.toFixed(2), p95: +stats.p95.toFixed(2), median: +stats.median.toFixed(2) });
  }
  await page.evaluate(() => document.getElementById('hide-ink')?.remove());
  return result;
}

try {
  if (only.includes('site')) {
    for (const width of [375, 1440, 2000, 2560]) for (const theme of ['light', 'dark']) {
      const height = width < 768 ? 812 : width === 1440 ? 900 : width === 2000 ? 1100 : 1440;
      const { page, ctx } = await open(width, height, theme);
      const m = await measure(page);
      await page.screenshot({ path: path.join(out, `site-${width}-${theme}.png`) });
      summary.push({ name: `site-${width}x${height}-${theme}`, searchTop: m.search?.t, panelTop: m.panel?.t, now: m.wx, launcher: JSON.stringify(m.launcher), radius: m.radius, tune: JSON.stringify(m.tune), overflow: m.overflow });
      if (m.overflow) problems.push(`site-${width}-${theme}: page scrolls sideways`);
      if (m.smallText) problems.push(`site-${width}-${theme}: ${m.smallText} text node(s) under 12px in the corner`);
      for (const [n, b] of [['tune', m.tune], ['launcher', m.launcher]]) if (!b || b.w < 44 || b.h < 44) problems.push(`site-${width}-${theme}: ${n} ${b?.w}x${b?.h}`);
      await ctx.close();
    }
  }

  if (only.includes('tc')) {
    for (const [width, height] of [[1440, 900], [375, 812]]) {
      const { page, ctx } = await open(width, height, 'light');
      await page.click('#tc-open');
      await wait(400);
      const m = await measure(page);
      const sheet = await page.evaluate(() => { const s = document.querySelector('#tuy-chinh'); const b = s.getBoundingClientRect();
        return { open: !s.hidden, l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), b: Math.round(b.bottom),
          controls: [...s.querySelectorAll('label, button')].filter(e => e.offsetParent).map(e => { const q = e.getBoundingClientRect(); return [Math.round(q.width), Math.round(q.height), e.textContent.trim() || e.getAttribute('aria-label')]; }) }; });
      await page.screenshot({ path: path.join(out, `tuy-chinh-${width}.png`) });
      summary.push({ name: `tuy-chinh-${width}`, sheet: JSON.stringify({ ...sheet, controls: undefined }), overflow: m.overflow });
      if (!sheet.open) problems.push(`tuy-chinh-${width}: the panel did not open`);
      if (sheet.r > width || sheet.l < 0) problems.push(`tuy-chinh-${width}: the panel leaves the window`);
      for (const [w, h, label] of sheet.controls) if (h < 44) problems.push(`tuy-chinh-${width}: "${label}" is ${w}x${h}`);
      if (m.overflow) problems.push(`tuy-chinh-${width}: page scrolls sideways`);
      // Escape closes it and gives the focus back to its button.
      await page.keyboard.press('Escape'); await wait(300);
      const back = await page.evaluate(() => document.querySelector('#tuy-chinh').hidden && document.activeElement?.id === 'tc-open');
      if (!back) problems.push(`tuy-chinh-${width}: Escape did not close it back to its button`);
      await ctx.close();
    }
  }

  if (only.includes('layout')) {
    for (const layout of ['full', 'part', 'head']) {
      const { page, ctx } = await open(1440, 900, 'light', { layout, picture: true, weather: true });
      const m = await measure(page);
      await page.screenshot({ path: path.join(out, `bo-cuc-${layout}-1440.png`) });
      summary.push({ name: `layout-${layout}-1440x900`, searchTop: m.search?.t, panelTop: m.panel?.t });
      await ctx.close();
    }
  }

  if (only.includes('off')) {
    nenLog.length = 0;
    const { page, ctx } = await open(1440, 900, 'light', { layout: 'full', picture: false, weather: true });
    const m = await measure(page);
    await page.screenshot({ path: path.join(out, `anh-nen-tat-1440.png`) });
    const asked = nenLog.filter(p => !p.endsWith('lich.json'));
    summary.push({ name: 'picture-off-1440x900', searchTop: m.search?.t, panelTop: m.panel?.t, nenRequests: nenLog.join(' ') || 'none' });
    if (asked.length) problems.push(`picture off: the picture was still requested ${asked.join(' ')}`);
    // Turned back on from the panel: the picture arrives without a reload.
    await page.click('#tc-open'); await wait(300);
    await page.click('input[name="tc-picture"]'); await wait(300);
    await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready'), { timeout: 15000 }).catch(() => problems.push('picture turned back on: it never showed'));
    const saved = await page.evaluate(() => localStorage.getItem('halcyon:tuy-chinh'));
    summary.push({ name: 'picture-on-again', saved });
    await ctx.close();
  }

  if (only.includes('contrast')) {
    const scratch = await (await browser.createBrowserContext()).newPage();
    // Today's picture (what nen.js shows today), then the newest days in the calendar.
    const all = (lichLive?.days ?? []).slice().sort((a, b) => (a.date < b.date ? 1 : -1));
    const todayIso = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' }).format(new Date());
    const current = all.find(d => d.date <= todayIso);
    const days = [...(current ? [{ ...current, date: `${current.date} (hôm nay)` }] : []), ...all.filter(d => d !== current).slice(0, 7)];
    for (const day of days.length ? days : [{ date: 'packaged', file: null }]) {
      lichOverride = day.file;
      const { page, ctx } = await open(1440, 900, 'light');
      const shown = await page.evaluate(() => document.querySelector('#nen img')?.currentSrc?.replace(location.origin, '') ?? null);
      const parts = await inkContrast(page, scratch);
      await page.screenshot({ path: path.join(out, `tuong-phan-${day.date}.png`), clip: { x: 0, y: 0, width: 1440, height: 140 } });
      contrast.push({ day: day.date, shown, parts });
      for (const p of parts) if (p.worst < 4.5) problems.push(`contrast ${day.date} ${p.part}: worst ${p.worst}`);
      await ctx.close();
    }
    lichOverride = null;
    await scratch.browserContext().close();
  }

  if (only.includes('ext')) {
    const id = await browser.installExtension(path.join(root, 'extension'));
    const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
    const worker = await sw.worker();
    await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), full);
    for (const [width, theme] of [[1440, 'light'], [1440, 'dark']]) {
      const page = await browser.newPage();
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      page.on('pageerror', e => problems.push(`ext page error: ${e.message}`));
      await page.goto(`chrome-extension://${id}/newtab.html`, { waitUntil: 'domcontentloaded' });
      await page.evaluate(t => { localStorage.setItem('air2:theme', JSON.stringify(t)); localStorage.removeItem('halcyon:tuy-chinh'); }, theme);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready'), { timeout: 20000 }).catch(() => {});
      await page.waitForSelector('.top-wx', { timeout: 10000 }).catch(() => problems.push('ext: the weather never reached the top row'));
      await wait(1500);
      const m = await measure(page);
      await page.screenshot({ path: path.join(out, `ext-${width}-${theme}.png`) });
      summary.push({ name: `ext-${width}x900-${theme}`, searchTop: m.search?.t, panelTop: m.panel?.t, now: m.wx, overflow: m.overflow });
      await page.close();
    }
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
console.table(summary);
for (const c of contrast) { console.log(`contrast ${c.day} (${c.shown})`); console.table(c.parts); }
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ snapshot: full.generated_at, summary, contrast, problems, nenServed: nenLog }, null, 2));
if (problems.length) { console.log('PROBLEMS\n' + problems.join('\n')); process.exitCode = 1; }
else console.log('No problems measured.');

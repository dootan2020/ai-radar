// "Sự kiện" (#sap-toi), the "Ba thì" page, rendered in headless Chrome from site/ and measured; with --out, a picture of
// each run.
//   node tests/capture-ba-thi.mjs                       offline: tests/fixtures/radar-window-sample.json with the real
//                                                       NeurIPS rows (data/events.json) and streams shaped like the
//                                                       collector's (radar/youtube.py); one JSON line per run set
//   node tests/capture-ba-thi.mjs --data <dir> --out <dir>   a downloaded radar-ui.json and radar-window.json, at the
//                                                       real clock (or --now <iso>), thumbnails from i.ytimg.com
//   --only song,trong   --ext (also the unpacked extension's new tab at 1280)
// Run by tests/test_trang_su_kien.py; nothing under site/ or data/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const dataDir = arg('--data', '');
const only = arg('--only', '');
const withExt = process.argv.includes('--ext');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });
const DAY = 864e5, HOUR = 36e5;
const iso = t => new Date(t).toISOString().replace('.000Z', 'Z');

let NOW, full, windowFile;
if (dataDir) {
  NOW = arg('--now', '') ? Date.parse(arg('--now', '')) : Date.now();
  full = JSON.parse(await fs.readFile(path.join(dataDir, 'radar-ui.json'), 'utf8'));
  windowFile = JSON.parse(await fs.readFile(path.join(dataDir, 'radar-window.json'), 'utf8'));
} else {
  // The clock of the approved mockup: 11/11 01:30 in Vietnam, NeurIPS Sydney 24 days away.
  NOW = Date.parse('2026-11-10T18:30:00Z');
  const raw = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8');
  const shift = NOW - Date.parse(JSON.parse(raw).generated_at);
  windowFile = JSON.parse(raw.replace(/"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))"/g,
    (_, t) => JSON.stringify(new Date(Date.parse(t) + shift).toISOString())));
  const curated = JSON.parse(await fs.readFile(path.join(root, 'data/events.json'), 'utf8'));
  windowFile.events = ['neurips-sydney-2026', 'neurips-paris-2026', 'neurips-atlanta-2026'].map(id => curated.find(e => e.id === id)).filter(Boolean);
  const s = (id, status, start, end, extra = {}) => ({ video_id: id, lab: 'test', channel: 'Kênh thử', title: `Stream ${id}`,
    url: `https://www.youtube.com/watch?v=${id}`, thumbnail: '', published_at: iso(start - DAY), status,
    start_at: start ? iso(start) : null, end_at: end ? iso(end) : null, ...extra });
  windowFile.live = [
    s('cap-live', 'live', NOW - HOUR, null, { channel: 'Hugging Face', title: 'Local AI 301: Quantization', title_vi: 'AI cục bộ 301: Quantization' }),
    s('cap-soon', 'upcoming', NOW + 90 * 6e4 + 30e3, null, { channel: 'Google Cloud Tech' }),
    s('cap-ended', 'ended', NOW - 2 * DAY - 2 * HOUR, NOW - 2 * DAY, { title_vi: 'Tương lai cơ sở hạ tầng AI' }),
    s('cap-old', 'ended', NOW - 8 * DAY - HOUR, NOW - 8 * DAY, { title: 'An ended stream eight days old' }),
  ];
  full = { ...windowFile };
}
const live = full.live || [];
const SCENARIOS = {
  song: { live, widths: [[1440, 'light'], [1440, 'dark'], [375, 'light'], [2000, 'light']] },
  trong: { live: [], widths: [[1440, 'light'], [375, 'light']] },
};
if (dataDir) {
  // The approved mockup's moment (11/11 01:30, the mockup's notes): the same snapshot, with the stream that was then on
  // air as the collector recorded it at the time (live, no end yet). Pictures only: the real file of now decides the rest.
  const was = live.find(v => v.video_id === 'il0dgxjpoC0');
  if (was) SCENARIOS['luc-duyet'] = { live: live.map(v => v === was ? { ...v, status: 'live', end_at: null } : v),
    now: Date.parse('2026-11-10T18:29:30Z'), widths: [[1440, 'light'], [375, 'light']] };   // 01:30 less the page's load
}

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
let current = { full, win: windowFile };
const requests = [];
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  requests.push(p);
  try {
    if (p === '/data/radar-ui.json') { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(current.full)); }
    if (p === '/data/radar-window.json') { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(current.win)); }
    if (p.startsWith('/data/') || p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    const file = path.join(root, 'site', p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));

const MEASURE = () => {
  const r = el => el.getBoundingClientRect();
  const shown = el => { const b = r(el); return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const page = document.querySelector('#feed-grid .bt');
  const res = { sideways: document.scrollingElement.scrollWidth > innerWidth, page: null };
  if (!page) return res;
  const b = r(page);
  const text = q => [...page.querySelectorAll(q)].filter(shown).map(el => el.textContent.replace(/\s+/g, ' ').trim());
  const texts = [...page.querySelectorAll('*')].filter(el => shown(el) && !el.closest('.sr') && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
  const coral = getComputedStyle(document.documentElement).getPropertyValue('--brand-signature').trim().toLowerCase();
  const rgb = c => { const x = document.createElement('i'); x.style.color = c; document.body.append(x); const v = getComputedStyle(x).color; x.remove(); return v; };
  const coralRgb = rgb(coral);
  const screens = [...page.querySelectorAll('.bt-screen')].filter(shown).map(s => {
    const f = s.querySelector('.bt-frame'), sb = r(s), fb = r(f);
    return { w: Math.round(fb.width), h: Math.round(fb.height), inside: fb.left >= sb.left - 0.5 && fb.right <= sb.right + 0.5 && fb.top >= sb.top - 0.5 && fb.bottom <= sb.bottom + 0.5 };
  });
  const calm = [...page.querySelectorAll('.bt-calm')].filter(shown).map(el => ({ text: el.textContent.trim(),
    lines: Math.round(r(el).height / parseFloat(getComputedStyle(el).lineHeight) - (parseFloat(getComputedStyle(el).paddingTop) + parseFloat(getComputedStyle(el).paddingBottom)) / parseFloat(getComputedStyle(el).lineHeight)) }));
  const cards = {};
  for (const k of ['bt-live', 'bt-next', 'bt-recent', 'bt-events']) {
    const el = page.querySelector('.' + k);
    if (el && shown(el)) {
      const cb = r(el);
      // The emptiest stretch inside the card: the tallest band of its height that no visible child covers.
      const spans = [...el.querySelectorAll('*')].filter(c => shown(c) && !c.closest('.sr')).map(c => [r(c).top, r(c).bottom]).sort((a, z) => a[0] - z[0]);
      let y = cb.top + parseFloat(getComputedStyle(el).paddingTop), gap = 0;
      for (const [t, bt] of spans) { gap = Math.max(gap, t - y); y = Math.max(y, bt); }
      gap = Math.max(gap, cb.bottom - parseFloat(getComputedStyle(el).paddingBottom) - y);
      cards[k] = { x: Math.round(cb.left - b.left), y: Math.round(cb.top - b.top), w: Math.round(cb.width), h: Math.round(cb.height),
        bg: getComputedStyle(el).backgroundColor, emptiest: Math.round(gap) };
    }
  }
  res.page = {
    box: { x: Math.round(b.left), y: Math.round(b.top + scrollY), w: Math.round(b.width), h: Math.round(b.height) },
    headings: text('.band-title'), cards,
    coralSurfaces: [...page.querySelectorAll('*')].filter(el => shown(el) && getComputedStyle(el).backgroundColor === coralRgb && r(el).width * r(el).height > 20000 && r(el).height > 100).map(el => el.className),
    live: text('.bt-live-t'), next: text('.bt-next .bt-name'), recent: text('.bt-recent .bt-name, .bt-recent .ev-row-t'),
    nextCount: text('.bt-next .ev-count .sr'), nextFace: [...page.querySelectorAll('.bt-next .ev-count .cd-face')].map(el => el.innerHTML), lanes: text('.bt-lane-t'), laneWaits: text('.bt-lane-d'), rows: text('.bt-lead .ev-row-t'),
    leadName: text('.bt-lead .ev-name'), legend: text('.bt-legend'), calm, screens,
    ticks: [...page.querySelectorAll('.bt-lane')].filter(shown).map(l => { const t = [...l.querySelectorAll('.bt-ticks i')]; return { all: t.length, on: t.filter(i => i.classList.contains('is-on')).length, first: t.findIndex(i => i.classList.contains('is-on')) }; }),
    rowLinkColors: [...page.querySelectorAll('.ev-row-t, .bt-lane-t')].filter(shown).map(el => getComputedStyle(el).color),
    ink: getComputedStyle(page.querySelector('.band-title')).color,
    minText: texts.length ? Math.min(...texts.map(el => parseFloat(getComputedStyle(el).fontSize))) : null,
    smallTargets: [...page.querySelectorAll('a, button')].filter(el => shown(el) && el.getAttribute('aria-hidden') !== 'true' && el.tabIndex >= 0)
      .map(el => ({ cls: String(el.className).split(' ')[0], w: Math.round(r(el).width), h: Math.round(r(el).height) })).filter(t => t.w < 44 || t.h < 44),
    weather: !!document.querySelector('#feed-grid .msn-wx'),
    view: document.querySelector('#filter-context .filter-name')?.textContent || null,
  };
  return res;
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'ba-thi-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, enableExtensions: withExt, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { now: new Date(NOW).toISOString(), chrome: browser.process()?.pid ?? null, runs: {}, errors: [] };

async function open(page, url, width, theme, now) {
  await page.setViewport({ width, height: width < 768 ? 812 : 900, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument((t0, t) => {
    const Real = Date, off = t0 - Real.now();
    // eslint-disable-next-line no-global-assign
    Date = class extends Real { constructor(...a) { if (a.length) super(...a); else super(Real.now() + off); } static now() { return Real.now() + off; } };
    try { localStorage.setItem('air2:theme', JSON.stringify(t)); } catch {}
  }, now, theme);
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    if (u.startsWith('https://radar-ai-vn.pages.dev/data/radar-ui.json')) {
      requests.push('ext:/data/radar-ui.json');
      return req.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(current.full) });
    }
    const ok = u.startsWith(site) || u.startsWith('chrome-extension://') || u.startsWith('data:') || (dataDir && u.startsWith('https://i.ytimg.com/'));
    return ok ? req.continue() : req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${url} ${width}: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') result.errors.push(`${url} ${width} console: ${m.text()}`); });
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#feed-grid .bt'), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => Promise.all([...document.querySelectorAll('.bt img')].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 4000); }))));
  await wait(600);
}
async function shot(page, name) {
  if (!out) return;
  const m = await page.evaluate(MEASURE);
  if (!m.page) return;
  const vp = page.viewport(), lowest = m.page.box.y + m.page.box.h;
  if (lowest + 40 > vp.height) { await page.setViewport({ ...vp, height: Math.ceil(lowest + 40) }); await wait(400); }
  await page.screenshot({ path: path.join(out, `${name}.png`), captureBeyondViewport: false });
}

try {
  for (const [name, sc] of Object.entries(SCENARIOS)) {
    if (only && !only.split(',').includes(name)) continue;
    current = { full: { ...full, live: sc.live }, win: { ...windowFile, live: sc.live } };
    for (const [width, theme] of sc.widths) {
      const ctx = await browser.createBrowserContext();
      const page = await ctx.newPage();
      requests.length = 0;
      await open(page, site + '#sap-toi', width, theme, sc.now || NOW);
      const m = await page.evaluate(MEASURE);
      // A cold load of the address: what the page asked the server for before it drew the view.
      m.requested = [...new Set(requests.filter(p => p.startsWith('/data/')))];
      const key = `${name}-${width}${theme === 'dark' ? '-toi' : ''}`;
      result.runs[key] = m;
      await shot(page, key);
      await ctx.close();
    }
  }
  if (withExt) {
    current = { full, win: windowFile };
    const id = await browser.installExtension(path.join(root, 'extension'));
    const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
    const worker = await sw.worker();
    await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), windowFile);
    const page = await browser.newPage();
    requests.length = 0;
    await open(page, `chrome-extension://${id}/newtab.html#sap-toi`, 1280, 'light', NOW);
    const m = await page.evaluate(MEASURE);
    m.requested = [...new Set(requests)];
    m.playLinks = await page.evaluate(() => [...document.querySelectorAll('.bt a[href*="youtube.com"]')].map(a => ({ play: a.hasAttribute('data-play'), target: a.target })));
    result.runs['tien-ich-1280'] = m;
    await shot(page, 'tien-ich-1280');
    await page.close();
  }
} catch (e) {
  result.errors.push(String(e && e.stack || e));
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(result) + '\n');

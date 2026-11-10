// The front page's "Sắp diễn ra" card ("Hai mươi lăm"), rendered in headless Chrome from site/ with
// tests/fixtures/radar-window-sample.json (offline: every other data file answers 404) and reduced motion. The page's
// clock is set so that the fixture's news is today's and NeurIPS Sydney (data/events.json) is 25 days away; each
// scenario swaps only the snapshot's events and streams, in memory.
//   node tests/capture-su-kien.mjs                      one JSON line: the card and its band, measured per scenario
//   node tests/capture-su-kien.mjs --out bento-anh/su-kien   the same, and a picture of each
//   --only mot,ba   --widths 1440,375 (light theme only)   --ext (also the unpacked extension at 1440)
// Run by tests/test_the_su_kien.py; nothing under site/ or data/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const only = arg('--only', '');
const withExt = process.argv.includes('--ext');
const widthsOnly = arg('--widths', '').split(',').filter(Boolean).map(Number);   // light theme only when given
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });

// The page's clock: 25 days and a little before NeurIPS Sydney opens (6 December, Sydney time).
const NOW = Date.parse('2026-11-10T11:21:18Z');
const DAY = 864e5;
const raw = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8');
const shift = NOW - Date.parse(JSON.parse(raw).generated_at);
// Every instant of the fixture moves with the clock, so its stories are as fresh as they were when it was taken.
const base = JSON.parse(raw.replace(/"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))"/g,
  (_, t) => JSON.stringify(new Date(Date.parse(t) + shift).toISOString())));
const curated = JSON.parse(await fs.readFile(path.join(root, 'data/events.json'), 'utf8'));
const byId = id => curated.find(e => e.id === id);
const sydney = byId('neurips-sydney-2026');
const three = [sydney, byId('neurips-atlanta-2026'), byId('neurips-paris-2026')].filter(Boolean);
const vnDay = t => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh' }).format(new Date(t));
// A fixture event: the Sydney row with other dates, read in Vietnam's timezone unless the case says otherwise.
const ev = (id, changes) => ({ ...sydney, id, timezone: 'Asia/Ho_Chi_Minh', ...changes });
const soon = NOW + 5 * 36e5 + 20 * 6e4;
const exactAt = `${vnDay(NOW + 9 * DAY)}T14:00:00+05:30`;
const stream = { status: 'live', video_id: 'capture-live', title: 'Live: building agents with the new Responses API, questions answered',
  url: 'https://www.youtube.com/watch?v=capture-live', channel: 'OpenAI', thumbnail: '', time_text: '' };

const SCENARIOS = {
  'mot': { events: [sydney], widths: [1440, 1920, 1024, 768, 375, 2560], dark: true },
  'ba': { events: three, widths: [1440, 1024, 768, 375] },
  'duoi-1-ngay': { events: [ev('cap-soon', { start_date: vnDay(soon), end_date: vnDay(soon), time_precision: 'exact', start_at: new Date(soon).toISOString() })], widths: [1440] },
  'dang-dien-ra': { events: [ev('cap-on', { start_date: vnDay(NOW - 2 * DAY), end_date: vnDay(NOW + 4 * DAY) })], widths: [1440] },
  'dang-dien-ra-1-ngay': { events: [ev('cap-today', { start_date: vnDay(NOW), end_date: vnDay(NOW) })], widths: [1440] },
  'xa-130-ngay': { events: [ev('cap-far', { start_date: vnDay(NOW + 131 * DAY), end_date: vnDay(NOW + 134 * DAY) })], widths: [1440, 1024] },
  'gio-chinh-xac': { events: [ev('cap-exact', { title: 'OpenAI DevDay Exchange — Bengaluru', location: 'Bengaluru, India', timezone: 'Asia/Kolkata',
    start_date: exactAt.slice(0, 10), end_date: exactAt.slice(0, 10), time_precision: 'exact', start_at: exactAt })], widths: [1440] },
  'video-va-su-kien': { events: three, live: [stream], widths: [1440, 375] },
  'nhieu-hon-ba': { events: [...three, ev('cap-more', { title: 'Sự kiện thử thứ tư', start_date: vnDay(NOW + 60 * DAY), end_date: vnDay(NOW + 61 * DAY) })], widths: [1440] },
  'sap-toi': { events: three, hash: '#sap-toi', widths: [1440, 375] },
};

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
let current = base;
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (/^\/data\/radar(-window)?\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(current)); }
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
  const box = el => { const b = r(el); return { x: Math.round(b.left), y: Math.round(b.top + scrollY), w: Math.round(b.width), h: Math.round(b.height) }; };
  const card = document.querySelector('#su-kien');
  const band = document.querySelector('.band-focus');
  const res = { sideways: document.scrollingElement.scrollWidth > innerWidth, card: null, band: null };
  if (band && shown(band)) {
    const cells = [...band.querySelector('.band-cells').children].filter(shown);
    const rows = new Map();
    for (const k of cells) { const t = Math.round(r(k).top); (rows.get(t) || rows.set(t, []).get(t)).push(k); }
    res.band = { box: box(band), rows: [...rows.values()].map(ks => ks.map(k => ({
      name: (k.querySelector('h2,h3')?.textContent || k.className).trim().replace(/\s+/g, ' ').slice(0, 20), w: Math.round(r(k).width), h: Math.round(r(k).height) }))) };
  }
  if (card && shown(card)) {
    const cb = r(card), cs = getComputedStyle(card);
    const inner = { left: cb.left + parseFloat(cs.paddingLeft), right: cb.right - parseFloat(cs.paddingRight), bottom: cb.bottom };
    // How far anything drawn in the card runs past its edges (its padding box across, its border box down).
    let pastX = 0, pastY = 0;
    for (const el of card.querySelectorAll('*')) {
      if (!shown(el) || el.closest('.sr') || el.classList.contains('sr')) continue;
      const b = r(el);
      pastX = Math.max(pastX, b.right - inner.right, inner.left - b.left);
      pastY = Math.max(pastY, b.bottom - inner.bottom);
    }
    const text = q => { const el = card.querySelector(q); return el && shown(el) ? el.textContent.replace(/\s+/g, ' ').trim() : null; };
    const top = q => { const el = card.querySelector(q); return el && shown(el) ? Math.round(r(el).top - cb.top) : null; };
    const small = [...card.querySelectorAll('*')].filter(el => shown(el) && !el.closest('.sr') && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
      .map(el => parseFloat(getComputedStyle(el).fontSize));
    const g = card.querySelector('.calbtn-g'), ticks = [...card.querySelectorAll('.ev-ticks i')];
    res.card = {
      box: box(card), dense: card.classList.contains('is-dense'), bg: cs.backgroundColor, pastX: Math.round(pastX), pastY: Math.round(pastY),
      head: text('.ev-head h2'), all: text('.ev-all'), number: text('.ev-n'), count: text('.ev-count .cd-face'), sr: card.querySelector('.ev-count .sr')?.textContent || null,
      numberPx: card.querySelector('.ev-n') ? Math.round(parseFloat(getComputedStyle(card.querySelector('.ev-n')).fontSize)) : null,
      ticks: { all: ticks.length, now: ticks.filter(t => t.classList.contains('is-now')).length, on: ticks.filter(t => t.classList.contains('is-on')).length,
        done: ticks.filter(t => t.classList.contains('is-done')).length, w: ticks.length ? Math.round(r(ticks[1] || ticks[0]).width * 10) / 10 : null },
      legend: text('.ev-legend'), name: text('.ev-name'), meta: text('.ev-meta'), note: text('.ev-note'),
      google: g && shown(g) ? { text: g.innerText.replace(/\s+/g, ' ').trim(),
        aria: g.getAttribute('aria-label'), bg: getComputedStyle(g).backgroundColor, ...box(g) } : null,
      ics: card.querySelector('.calbtn-ics') && shown(card.querySelector('.calbtn-ics')) ? box(card.querySelector('.calbtn-ics')) : null,
      stream: text('.ev-stream'),
      rows: [...card.querySelectorAll('.ev-row')].filter(shown).map(a => ({ t: a.querySelector('.ev-row-t').textContent, m: a.querySelector('.ev-row-m').textContent,
        d: a.querySelector('.ev-row-d .cd-face')?.textContent || null, h: Math.round(r(a).height) })),
      // The order of the parts down the card: the stacking the mockup drew.
      order: ['.ev-head', '.ev-stream', '.ev-count', '.ev-ruler', '.ev-link', '.calbtn', '.ev-more'].map(q => [q, top(q)]).filter(([, t]) => t != null).sort((a, b) => a[1] - b[1]).map(([q]) => q),
      lefts: ['.ev-count', '.ev-link', '.calbtn'].map(q => { const el = card.querySelector(q); return el && shown(el) ? Math.round(r(el).left - cb.left) : null; }),
      minText: small.length ? Math.min(...small) : null,
      targets: [...card.querySelectorAll('a, button')].filter(shown).map(el => ({ cls: String(el.className).split(' ')[0], w: Math.round(r(el).width), h: Math.round(r(el).height) })),
    };
  }
  const tile = document.querySelector('#feed-grid .bt');
  if (tile && shown(tile)) res.list = { box: box(tile), head: tile.querySelector('.band-title')?.textContent, events: tile.querySelectorAll('.bt-lane').length,
    google: tile.querySelectorAll('.calbtn-g').length, ics: tile.querySelectorAll('.calbtn-ics').length, countdowns: [...tile.querySelectorAll('.cd .sr')].map(s => s.textContent) };
  return res;
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'su-kien-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, enableExtensions: withExt, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { now: new Date(NOW).toISOString(), chrome: browser.process()?.pid ?? null, runs: {}, errors: [] };

async function open(page, url, width, theme) {
  await page.setViewport({ width, height: width < 768 ? 812 : 900, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.evaluateOnNewDocument((now, t) => {
    const Real = Date, off = now - Real.now();
    // eslint-disable-next-line no-global-assign
    Date = class extends Real { constructor(...a) { if (a.length) super(...a); else super(Real.now() + off); } static now() { return Real.now() + off; } };
    try { localStorage.setItem('air2:theme', JSON.stringify(t)); } catch {}
  }, NOW, theme);
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    return u.startsWith(site) || u.startsWith('chrome-extension://') || u.startsWith('data:') ? req.continue() : req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${url} ${width}: ${e.message}`));
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && (document.querySelector('#band-more') || document.querySelector('#feed-grid .bt')), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  await wait(1000);
}
// A picture of the band (or the "Sắp diễn ra" list) and one of the card, each scrolled into the window first: a
// capture beyond the viewport re-lays the page out and was seen to drop the number.
async function shot(page, name, m) {
  if (!out) return;
  const clip = (file, b, pad) => page.screenshot({ path: path.join(out, file), captureBeyondViewport: false,
    clip: { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: b.w + 2 * pad, height: b.h + 2 * pad } });
  // The window grows until it holds the part pictured, and the part is measured again where it then stands.
  const lowest = Math.max(...[m.list && m.list.box, m.band && m.band.box, m.card && m.card.box].filter(Boolean).map(b => b.y + b.h));
  const vp = page.viewport();
  if (lowest + 40 > vp.height) { await page.setViewport({ ...vp, height: Math.ceil(lowest + 40) }); await wait(500); }
  const again = await page.evaluate(MEASURE);
  const wide = again.list ? again.list.box : again.band ? again.band.box : null;
  if (wide) await clip(`${name}.png`, wide, 16);
  if (again.card) await clip(`${name}-the.png`, again.card.box, 12);
}

try {
  for (const [name, sc] of Object.entries(SCENARIOS)) {
    if (only && !only.split(',').includes(name)) continue;
    current = { ...base, events: sc.events, live: sc.live || [] };
    const runs = widthsOnly.length ? sc.widths.filter(w => widthsOnly.includes(w)).map(w => [w, 'light'])
      : sc.widths.map(w => [w, 'light']).concat(sc.dark ? [[1440, 'dark']] : []);
    for (const [width, theme] of runs) {
      const ctx = await browser.createBrowserContext();
      const page = await ctx.newPage();
      await open(page, site + (sc.hash || ''), width, theme);
      const m = await page.evaluate(MEASURE);
      const key = `${name}-${width}${theme === 'dark' ? '-toi' : ''}`;
      result.runs[key] = m;
      await shot(page, key, m);
      await ctx.close();
    }
  }
  if (withExt) {
    current = { ...base, events: three, live: [] };
    const id = await browser.installExtension(path.join(root, 'extension'));
    const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
    const worker = await sw.worker();
    await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), current);
    const page = await browser.newPage();
    await open(page, `chrome-extension://${id}/newtab.html`, 1440, 'light');
    const m = await page.evaluate(MEASURE);
    result.runs['tien-ich-1440'] = m;
    await shot(page, 'tien-ich-1440', m);
    if (out) await page.screenshot({ path: path.join(out, 'tien-ich-1440-trang.png') });
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

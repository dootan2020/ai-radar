// The top row and the panel's head row at 1024, 1280, 1366 and 1440 px, rendered in headless Chrome offline: the website
// (served from site/ with tests/fixtures/radar-window-sample.json) and the unpacked extension (its storage filled from the
// same fixture). The weather is a made-up Open-Meteo answer, so the corner carries its city and temperature too.
// For each page and width: the corner's drawn right edge against the search's left edge, the corner's overflow, the
// search's centre against the window's, the order buttons shown and whether any is cut, the head row's overflow.
// On the website at 1280 also: whether the complete snapshot was asked for before and after the first scroll.
// Prints one JSON line; tests/test_hieu_nang.py checks it.
// Usage: node tests/verify-top-row-fit.mjs [--out <dir>]   (--out also saves a screenshot per page and width)
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const argv = process.argv.slice(2);
const outIdx = argv.indexOf('--out');
const out = outIdx >= 0 ? path.resolve(argv[outIdx + 1]) : null;
if (out) await fs.mkdir(out, { recursive: true });
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
const fixture = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
/* A forecast in Open-Meteo's shape (as tests/verify-top-search.mjs): ten days from today (Asia/Bangkok). */
function forecast() {
  const pad = n => String(n).padStart(2, '0');
  const local = new Date(Date.now() + 7 * 36e5);
  const day0 = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate());
  const iso = (t, hour) => { const d = new Date(t); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` + (hour === undefined ? '' : `T${pad(hour)}:00`); };
  const hours = Array.from({ length: 240 }, (_, i) => i);
  const codes = [0, 2, 3, 61, 80, 1, 3, 53, 0, 2];
  return {
    current: { time: iso(local.getTime(), local.getUTCHours()), temperature_2m: 16.4, apparent_temperature: 16, relative_humidity_2m: 70,
      weather_code: 3, wind_speed_10m: 9, is_day: 0 },
    hourly: { time: hours.map(i => iso(day0 + Math.floor(i / 24) * 864e5, i % 24)), temperature_2m: hours.map(i => 18 + (i % 24) / 3),
      weather_code: hours.map(i => codes[i % 10]), precipitation_probability: hours.map(i => (i * 7) % 60), is_day: hours.map(i => +(i % 24 >= 6 && i % 24 < 18)) },
    daily: { time: codes.map((_, i) => iso(day0 + i * 864e5)), weather_code: codes, temperature_2m_max: codes.map((_, i) => 24 + i % 4),
      temperature_2m_min: codes.map((_, i) => 16 + i % 3), precipitation_probability_max: codes.map((_, i) => (i * 13) % 80) },
  };
}
const FORECAST = JSON.stringify(forecast());

const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (/^\/data\/radar(-window)?\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(fixture); }
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
  const corner = document.getElementById('top-now');
  let cornerRight = 0;
  corner.querySelectorAll('*').forEach(c => { const b = r(c); if (b.width && !c.closest('.sr')) cornerRight = Math.max(cornerRight, b.right); });
  const search = r(document.querySelector('.msn-top :is(.news-search, .web-search)'));
  const shown = el => getComputedStyle(el).display !== 'none' && r(el).width > 0;
  const orders = [...document.querySelectorAll('.msn-head .sort-btn')].filter(shown);
  const label = b => [...b.querySelectorAll('span')].filter(shown).map(s => s.textContent.trim()).join(' ') || b.textContent.trim();
  const head = document.querySelector('.msn-head');
  return {
    cornerRight: Math.round(cornerRight), searchLeft: Math.round(search.left),
    cornerOverflow: corner.scrollWidth - corner.clientWidth,
    searchCentre: Math.round((search.left + search.right) / 2 - innerWidth / 2),
    date: corner.querySelector('time')?.innerText || '',
    city: !!corner.querySelector('.top-city'),
    fit: corner.dataset.fit,
    orders: orders.map(label),
    ordersCut: orders.filter(b => b.scrollWidth > b.clientWidth + 1 || [...b.querySelectorAll('span')].filter(shown).some(s => s.scrollWidth > s.clientWidth + 1)).map(label),
    headOverflow: head.scrollWidth - head.clientWidth,
    sideways: document.scrollingElement.scrollWidth > innerWidth,
  };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'top-row-fit-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, enableExtensions: true, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { pages: {}, errors: [] };

try {
  const id = await browser.installExtension(path.join(root, 'extension'));
  const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
  const worker = await sw.worker();
  await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), JSON.parse(fixture.toString('utf8')));
  for (const [target, url] of [['site', site], ['ext', `chrome-extension://${id}/newtab.html`]]) {
    for (const w of [1024, 1280, 1366, 1440]) {
      const page = await browser.newPage();
      await page.setViewport({ width: w, height: 800, deviceScaleFactor: 1 });
      await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: 'light' }]);
      await page.setRequestInterception(true);
      const requests = [];
      page.on('request', req => {
        const u = req.url();
        requests.push(u);
        if (u.startsWith('https://api.open-meteo.com/')) return req.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: FORECAST });
        if (u.startsWith(site) || u.startsWith('chrome-extension://') || u.startsWith('data:')) return req.continue();
        return req.abort();
      });
      page.on('pageerror', e => result.errors.push(`${target} ${w}: ${e.message}`));
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#top-now time'), { timeout: 30000 });
      await page.evaluate(() => document.fonts.ready);
      await wait(900);
      result.pages[`${target}-${w}`] = await page.evaluate(MEASURE);
      if (out) await page.screenshot({ path: path.join(out, `hang-tren-${target}-${w}.png`) });
      if (target === 'site' && w === 1280) {
        // The complete snapshot waits for the reader (feed.js whenReaderActs): none asked for while the page sits
        // untouched, asked for after the first scroll. The fixture server answers radar-ui.json with 404, so the
        // feed falls back to data/radar.json; either address counts.
        const asked = () => requests.filter(u => /\/data\/radar(-ui)?\.json$/.test(u)).length;
        await wait(2500);
        result.complete = { untouched: asked() };
        await page.evaluate(() => window.scrollBy(0, 400));
        for (let i = 0; i < 20 && !asked(); i++) await wait(250);
        result.complete.afterScroll = asked();
      }
      await page.close();
    }
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(result) + '\n');

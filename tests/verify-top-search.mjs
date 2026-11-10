// The top row's search under each "Tùy chỉnh" layout, and the pager dots, rendered in headless Chrome offline: the website
// (served from site/ with tests/fixtures/radar-window-sample.json) and the unpacked extension (its storage filled from the
// same fixture). The forecast is a made-up Open-Meteo answer, so the weather card draws its two page dots.
// For each page, layout and window (1440x900, 1920x1080): the search pill's vertical middle against the halfway point
// between the window's top edge and the panel's, the corners' tops, sideways scroll. On the website at 1440: each row of
// dots, its dots' drawn style and the gaps between them. Prints one JSON line; tests/test_tim_kiem_giua.py checks it.
// Usage: node tests/verify-top-search.mjs [--out <dir>]   (--out also saves screenshots; nothing under site/ is written)
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

/* A forecast in Open-Meteo's shape: ten days from today (Asia/Bangkok), hourly and daily. */
function forecast() {
  const pad = n => String(n).padStart(2, '0');
  const local = new Date(Date.now() + 7 * 36e5);
  const day0 = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate());
  const iso = (t, hour) => { const d = new Date(t); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` + (hour === undefined ? '' : `T${pad(hour)}:00`); };
  const hours = Array.from({ length: 240 }, (_, i) => i);
  const codes = [0, 2, 3, 61, 80, 1, 3, 53, 0, 2];
  return {
    current: { time: iso(local.getTime(), local.getUTCHours()), temperature_2m: 21.4, apparent_temperature: 21, relative_humidity_2m: 70,
      weather_code: 2, wind_speed_10m: 9, is_day: 1 },
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
  const r = el => el && el.getBoundingClientRect();
  const pill = [...document.querySelectorAll('.msn-top :is(.ns-field, .web-field)')].find(e => r(e).height > 0);
  const s = r(pill), panel = r(document.querySelector('#top'));
  const corners = ['#top-now', '#tc-open', '.tool-launcher-button'].map(q => r(document.querySelector(q))).filter(b => b && b.height > 0);
  return { layout: document.documentElement.dataset.layout || 'full', scrollY: scrollY,
    searchTop: s.top, searchH: s.height, searchMid: s.top + s.height / 2, panelTop: panel.top, half: panel.top / 2,
    off: s.top + s.height / 2 - panel.top / 2, cornerTops: corners.map(b => Math.round(b.top)),
    cornerMids: corners.map(b => b.top + b.height / 2), sideways: document.scrollingElement.scrollWidth > innerWidth };
};

const DOTS = () => {
  const rows = { lead: '#lead .lead-dots', weather: '.wx-dots' };
  const res = {};
  for (const [name, q] of Object.entries(rows)) {
    const group = document.querySelector(q);
    if (!group) { res[name] = null; continue; }
    const buttons = [...group.querySelectorAll('button')];
    const dots = buttons.map(b => {
      const cs = getComputedStyle(b), pe = getComputedStyle(b, '::before'), box = b.getBoundingClientRect();
      const w = parseFloat(pe.width);
      return { current: b.getAttribute('aria-current') === 'true', w, h: parseFloat(pe.height), left: box.left + (box.width - w) / 2,
        fill: pe.backgroundColor, shadow: pe.boxShadow, radius: pe.borderRadius, border: pe.borderTopWidth + ' ' + pe.borderTopStyle,
        outline: pe.outlineStyle, buttonBorder: cs.borderTopWidth + ' ' + cs.borderTopStyle, buttonBg: cs.backgroundColor,
        buttonH: box.height, cls: group.className };
    });
    const gaps = dots.slice(1).map((d, i) => Math.round((d.left - (dots[i].left + dots[i].w)) * 10) / 10);
    res[name] = { cls: group.className, dots: dots.map(({ left, ...d }) => d), gaps };
  }
  return res;
};

const settings = layout => JSON.stringify({ layout, picture: true, weather: true });
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'top-search-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, enableExtensions: true, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { pages: {}, dots: null, errors: [] };

async function prepare(page, layout, w, h) {
  await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.evaluateOnNewDocument(v => { try { localStorage.setItem('halcyon:tuy-chinh', v); } catch {} }, settings(layout));
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    if (u.startsWith('https://api.open-meteo.com/')) return req.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: FORECAST });
    if (u.startsWith(site) || u.startsWith('chrome-extension://') || u.startsWith('data:')) return req.continue();
    return req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${layout} ${w}: ${e.message}`));
}

try {
  const id = await browser.installExtension(path.join(root, 'extension'));
  const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
  const worker = await sw.worker();
  await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), JSON.parse(fixture.toString('utf8')));
  for (const [target, url] of [['site', site], ['ext', `chrome-extension://${id}/newtab.html`]]) {
    for (const layout of ['full', 'part', 'head']) {
      for (const [w, h] of [[1440, 900], [1920, 1080]]) {
        const ctx = target === 'site' ? await browser.createBrowserContext() : null;
        const page = await (ctx || browser).newPage();
        await prepare(page, layout, w, h);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await page.waitForFunction(() => document.querySelector('#band-more') && document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 30000 });
        await page.evaluate(() => document.fonts.ready);
        await wait(900);
        result.pages[`${target}-${layout}-${w}x${h}`] = await page.evaluate(MEASURE);
        if (out && w === 1440) await page.screenshot({ path: path.join(out, `tim-${target}-${layout}-1440.png`) });
        if (target === 'site' && layout === 'full' && w === 1440) {
          await page.waitForFunction(() => document.querySelector('.wx-dots'), { timeout: 10000 }).catch(() => {});
          result.dots = await page.evaluate(DOTS);
          if (out) {
            // The lead's dots on a bright picture and on a dark one (drawn here, so the check needs no network).
            for (const [name, a, b] of [['sang', '#fbfbf8', '#dfe6ef'], ['toi', '#0b0d12', '#1c2230']]) {
              await page.evaluate((a, b) => {
                // A picture under the dots: a layer over the slide, under the dots (z-index 3).
                const lead = document.querySelector('#lead');
                let pic = lead.querySelector('.probe-pic');
                if (!pic) { pic = document.createElement('div'); pic.className = 'probe-pic'; lead.append(pic); }
                pic.style.cssText = `position:absolute;inset:0;z-index:2;pointer-events:none;background:linear-gradient(135deg, ${a}, ${b})`;
              }, a, b);
              await wait(300);
              const band = await page.evaluateHandle(() => document.querySelector('#lead').closest('.band-cells, .band-grid') || document.querySelector('#lead').parentElement);
              await band.screenshot({ path: path.join(out, `cham-${name}-1440.png`) });
            }
          }
        }
        await page.close();
        if (ctx) await ctx.close();
      }
    }
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(result) + '\n');

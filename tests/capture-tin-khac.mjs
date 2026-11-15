// "Tin khác" on the front page, rendered in headless Chrome from a radar-ui.json snapshot against this worktree's site/:
// the section as it first draws, then after two scroll loads (cropped around the first older day's heading), at each
// width, light and (at --dark widths) dark. Prints one JSON line of measurements per width: stories drawn, sheets, day
// headings, smallest text, smallest story link, horizontal scroll, page errors.
// node tests/capture-tin-khac.mjs --data <radar-ui.json> --out plans/reports/port-tin-khac --tag after
//   [--widths 375,1440,2000] [--dark 375,1440] [--window-hours 48]
// The window file answers 404, so the page reads the complete snapshot at once and its older days follow the window's
// stories; --window-hours shortens the window so two loads reach an older day. Pictures under /assets/ and /nen/ are not
// in a worktree; they are fetched from hco.news for the headless page only. Nothing under site/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const dataFile = arg('--data', '');
const out = arg('--out', 'plans/reports/port-tin-khac');
const tag = arg('--tag', 'after');
const widths = arg('--widths', '375,1440,2000').split(',').map(Number);
const dark = new Set(arg('--dark', '375,1440').split(',').filter(Boolean).map(Number));
const windowHours = Number(arg('--window-hours', 48));
if (!dataFile) throw new Error('--data <radar-ui.json> is required');
await fs.mkdir(out, { recursive: true });

const snap = JSON.parse(await fs.readFile(dataFile, 'utf8'));
snap.ranking = { ...(snap.ranking || {}), window_hours: windowHours };
const data = Buffer.from(JSON.stringify(snap));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const remote = new Map();
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p === '/data/radar-ui.json' || p === '/data/radar.json') { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(data); }
    if (p.startsWith('/data/')) { res.writeHead(404); return res.end(); }
    if (p.startsWith('/assets/') || p.startsWith('/nen/')) {
      if (!remote.has(p)) remote.set(p, fetch(`https://hco.news${p}`, { signal: AbortSignal.timeout(8000) })
        .then(async r => r.ok ? { type: r.headers.get('content-type'), body: Buffer.from(await r.arrayBuffer()) } : null).catch(() => null));
      const got = await remote.get(p);
      if (!got) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'content-type': got.type || 'application/octet-stream' }); return res.end(got.body);
    }
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

const MEASURE = () => {
  const band = document.querySelector('#band-more');
  const box = band && band.querySelector('#more-box');
  const texts = [...band.querySelectorAll('*')].filter(el => el.getClientRects().length && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
  const links = [...band.querySelectorAll('a[href]')].filter(a => a.getClientRects().length);
  const target = a => { const host = a.closest('[data-sid]') || a; return host.getBoundingClientRect(); };
  return {
    stories: box ? box.querySelectorAll('[data-sid]').length : 0,
    sheets: box ? box.querySelectorAll('.tk-sheet').length : 0,
    days: box ? [...box.querySelectorAll('.day-line')].map(h => h.textContent.trim()) : [],
    minText: Math.min(...texts.map(el => parseFloat(getComputedStyle(el).fontSize))),
    minTarget: links.length ? Math.round(Math.min(...links.map(a => target(a).height))) : null,
    sideways: document.scrollingElement.scrollWidth > innerWidth,
    status: document.querySelector('#more-status')?.textContent || '',
  };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'tin-khac-'));
const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
  pipe: true, userDataDir: profile, args: ['--disable-gpu'], timeout: 20000 });
const report = [];
try {
  for (const width of widths) for (const theme of dark.has(width) ? ['light', 'dark'] : ['light']) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: 1000, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.evaluateOnNewDocument(t => { localStorage.setItem('air2:theme', JSON.stringify(t)); }, theme);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(() => document.querySelector('#band-more:not([hidden])') && document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 30000 });
    await page.evaluate(() => document.fonts.ready);
    // The extension's offer card sits in the window's corner over whatever scrolls under it; it is not "Tin khác".
    await page.addStyleTag({ content: '.cai-widget { display: none !important; }' });
    const settle = async () => {
      await page.evaluate(async () => {
        document.querySelectorAll('#band-more img[data-src]').forEach(img => { if (img.dataset.srcset) img.srcset = img.dataset.srcset; img.src = img.dataset.src; });
        const imgs = [...document.querySelectorAll('#band-more img')];
        imgs.forEach(img => { img.loading = 'eager'; });
        // A picture that never answers must not hold the capture: four seconds at most.
        await Promise.race([Promise.all(imgs.map(img => img.decode().catch(() => {}))), new Promise(r => setTimeout(r, 4000))]);
      });
      await wait(500);
    };
    await page.evaluate(() => document.querySelector('#band-more').scrollIntoView({ block: 'start' }));
    await settle();
    const first = await page.evaluate(MEASURE);
    const suffix = theme === 'dark' ? '-dark' : '';
    const el = await page.$('#band-more');
    await el.screenshot({ path: path.join(out, `${tag}-${width}${suffix}.png`) });
    // Two scroll loads: the sentinel under the section into view, each time until more stories arrive.
    const loads = [];
    for (let i = 0; i < 2; i++) {
      const before = await page.$$eval('#more-box [data-sid]', e => e.length);
      await page.evaluate(() => document.querySelector('#feed-sentinel').scrollIntoView({ block: 'end' }));
      await page.waitForFunction(b => document.querySelectorAll('#more-box [data-sid]').length > b, { timeout: 15000 }, before).catch(() => {});
      await wait(600);
      loads.push([before, await page.$$eval('#more-box [data-sid]', e => e.length)]);
    }
    await settle();
    const after = await page.evaluate(MEASURE);
    // Crop around the first older day's heading: the end of the stretch above it and the start of the one below.
    const day = await page.$('#more-box .day-line');
    if (day) {
      await page.evaluate(h => h.scrollIntoView({ block: 'center' }), day);
      await settle();
      // Document coordinates: page.screenshot's clip is measured from the page's top, not the viewport's.
      const clip = await page.evaluate(h => {
        const d = h.getBoundingClientRect(), b = document.querySelector('#band-more').getBoundingClientRect();
        const top = Math.max(b.top, d.top - 400) + scrollY, bottom = b.bottom + scrollY;
        return { x: b.left + scrollX, y: top, width: b.width, height: Math.min(1600, bottom - top) };
      }, day);
      await page.screenshot({ path: path.join(out, `${tag}-${width}${suffix}-hai-lan-tai.png`), captureBeyondViewport: true, clip });
    }
    report.push({ width, theme, first, loads, after, errors });
    console.log(JSON.stringify({ width, theme, first, loads, after, errors }));
    await page.close();
  }
  await fs.writeFile(path.join(out, `${tag}-measure.json`), JSON.stringify(report, null, 2));
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}

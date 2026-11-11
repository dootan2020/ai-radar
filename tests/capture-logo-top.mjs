// Clicking the "halcyon" logo from deep in another tab (captain, 11/11 14:50: the content scrolled up under the
// window's edge, the search bar touched it and the address became /#top). Renders site/ offline in headless Chrome.
//   node tests/capture-logo-top.mjs [--out <dir>] [--only <width>[,<width>]]
// One JSON line on stdout: per width the state after the click (scrollY, hash, pressed tab, search box, history length).
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const only = String(arg('--only', '')).split(',').filter(Boolean).map(Number);
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const siteDir = path.join(root, 'site');
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    let file;
    if (/^\/data\/radar(-window)?\.json$/.test(p)) file = path.join(root, 'tests/fixtures/radar-window-sample.json');
    else if (p.startsWith('/data/') || p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    else file = path.join(siteDir, p.endsWith('/') ? p + 'index.html' : p);
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const stand = await fs.readFile(path.join(root, 'site/og-image.png'));

const browser = await puppeteer.launch({ headless: true, executablePath, ignoreDefaultArgs: ['--hide-scrollbars'] });
const sizes = [{ w: 1440, h: 900 }, { w: 375, h: 812, phone: true }].filter(s => !only.length || only.includes(s.w));
const result = {};
try {
  for (const size of sizes) {
    const page = await browser.newPage();
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);
    await page.setViewport({ width: size.w, height: size.h, deviceScaleFactor: 1, isMobile: !!size.phone, hasTouch: !!size.phone });
    await page.setRequestInterception(true);
    let loads = 0;
    page.on('request', req => {
      const u = req.url();
      if (!u.startsWith(site) && !u.startsWith('data:')) return req.respond({ status: 200, contentType: 'image/png', body: stand });
      req.continue();
    });
    page.on('framenavigated', f => { if (f === page.mainFrame()) loads++; });
    await page.goto(site, { waitUntil: 'networkidle0' });
    await wait(1200);
    const entries0 = await page.evaluate(() => history.length);
    const marker = await page.evaluate(() => { window.__same = document.querySelector('#top'); return true; });
    // Open Mã và mô hình, then read down the page.
    await page.click('#feed-filters .filter-chip[data-filter="code"]');
    await wait(800);
    await page.evaluate(() => window.scrollTo({ top: 1500, behavior: 'instant' }));
    await wait(300);
    const before = await page.evaluate(() => ({ scrollY: Math.round(scrollY), hash: location.hash }));
    loads = 0;
    await page.click('#brand');
    await wait(1500);
    const after = await page.evaluate(() => {
      const s = document.querySelector('#ns-q');
      const b = s ? s.getBoundingClientRect() : null;
      const active = document.querySelector('#feed-filters .filter-chip[aria-pressed="true"]');
      return { scrollY: Math.round(scrollY), hash: location.hash, search: location.search, path: location.pathname,
        active: active && active.dataset.filter, searchTop: b && +b.top.toFixed(1), searchBottom: b && +b.bottom.toFixed(1),
        inView: !!b && b.top >= 0 && b.bottom <= innerHeight, innerHeight, sameShell: window.__same === document.querySelector('#top'),
        entries: history.length };
    });
    result[size.w] = { before, after, entries0, reloads: loads, sameShell: marker && after.sameShell };
    if (out) await page.screenshot({ path: path.join(out, `logo-top-${size.w}.png`) });
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
console.log(JSON.stringify(result));
// The lead picture the build writes into index.html (radar/front_lead.py) against the one feed.js draws, in headless
// Chrome offline. Serves site/ with a built index.html (--index) and a window snapshot (--data, also served as the
// complete one); every publisher picture is answered with site/og-image.png and counted.
// For each width: the story id of the build's slide, the story id of the carousel's first slide once feed.js has drawn,
// whether the drawn slide holds the very element the page arrived with, the picture's top edge before and after the
// draw, the layout shift score, and how many times the lead's picture was asked for.
// Prints one JSON line; tests/test_front_lead.py checks it.
// Usage: node tests/verify-front-lead.mjs --index <built index.html> --data <radar-window.json> [--out <dir>]
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const argv = process.argv.slice(2);
const arg = name => { const i = argv.indexOf(name); return i >= 0 ? path.resolve(argv[i + 1]) : null; };
const indexFile = arg('--index'), dataFile = arg('--data'), out = arg('--out');
if (!indexFile || !dataFile) throw new Error('--index and --data are required');
if (out) await fs.mkdir(out, { recursive: true });
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
const [indexHtml, data, picture] = await Promise.all([fs.readFile(indexFile), fs.readFile(dataFile), fs.readFile(path.join(root, 'site/og-image.png'))]);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };

const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p === '/' || p === '/index.html') { res.writeHead(200, { 'content-type': TYPES['.html'] }); return res.end(indexHtml); }
    if (/^\/data\/radar(-window|-ui)?\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(data); }
    if (p.startsWith('/data/') || p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    const file = path.join(root, 'site', p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;

/* Runs before the page's own scripts: marks the picture the HTML arrives with (a property, not an attribute, so the
   page is unchanged), records its top edge at first sight, and sums layout shifts. */
const EARLY = () => {
  window.__shift = 0;
  new PerformanceObserver(list => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__shift += e.value; })
    .observe({ type: 'layout-shift', buffered: true });
  new MutationObserver(() => {
    const img = document.querySelector('#feed-skeleton .msn-lead img');
    if (img && !img.__early) { img.__early = true; window.__earlyImg = img; }
  }).observe(document, { childList: true, subtree: true });
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'front-lead-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { widths: {}, errors: [] };
try {
  for (const [w, h] of [[375, 812], [1440, 900]]) {
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);
    await page.setRequestInterception(true);
    const asked = {};
    page.on('pageerror', e => result.errors.push(String(e)));
    await page.evaluateOnNewDocument(EARLY);
    // The first paint, before the modules ran: hold feed.js until the page has drawn the build's slide.
    let release;
    const held = new Promise(r => { release = r; });
    page.on('request', async r => {
      const u = r.url();
      if (u === site + 'feed.js') { await held; return r.continue(); }
      if (u.startsWith(site)) return r.continue();
      if (r.resourceType() === 'image') { asked[u] = (asked[u] || 0) + 1; return r.respond({ status: 200, contentType: 'image/png', body: picture }); }
      return r.respond({ status: 404, body: '' });
    });
    const nav = page.goto(site, { waitUntil: 'load' });   // the load waits for feed.js, held below
    // The parsed page with its blocking styles applied and the picture decoded: what a reader sees before feed.js.
    await page.waitForFunction(() => document.readyState !== 'loading' && window.__earlyImg && window.__earlyImg.complete
      && [...document.querySelectorAll('link[rel="stylesheet"]')].every(l => l.sheet), { timeout: 10000 }).catch(() => {});
    const before = await page.evaluate(() => {
      const slide = document.querySelector('#feed-skeleton .msn-lead .slide');
      const img = window.__earlyImg;
      return { id: slide ? slide.dataset.id : null, top: img ? Math.round(img.getBoundingClientRect().top) : null,
        left: img ? Math.round(img.getBoundingClientRect().left) : null, width: img ? Math.round(img.getBoundingClientRect().width) : null };
    });
    if (out) await page.screenshot({ path: path.join(out, `early-${w}.png`) });
    release();
    await nav;
    await page.waitForSelector('#lead .slide.is-active', { timeout: 15000 });
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    const after = await page.evaluate(() => {
      const slide = document.querySelector('#lead .slide.is-active');
      const img = slide && slide.querySelector('img');
      return { id: slide ? slide.dataset.id : null, adopted: !!(img && img.__early),
        top: img ? Math.round(img.getBoundingClientRect().top) : null, left: img ? Math.round(img.getBoundingClientRect().left) : null,
        width: img ? Math.round(img.getBoundingClientRect().width) : null,
        skeleton: !!document.getElementById('feed-skeleton'), shift: Math.round(window.__shift * 1000) / 1000,
        // feed.js names them by the import map's address (index.html built with asset versions), or the plain file.
        lateStyles: ['arena.css', 'story.css'].map(h => [...document.querySelectorAll('link[rel="stylesheet"]')]
          .some(l => new URL(l.href).pathname === `/${h}`)) };
    });
    if (out) await page.screenshot({ path: path.join(out, `drawn-${w}.png`) });
    const leadUrl = await page.evaluate(() => { const i = document.querySelector('#lead .slide.is-active img'); return i ? i.currentSrc : null; });
    result.widths[w] = { before, after, leadRequests: leadUrl ? (asked[leadUrl] || 0) : null };
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
console.log(JSON.stringify(result));

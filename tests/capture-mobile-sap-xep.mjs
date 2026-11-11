// The front page's order control on a phone and the dock's "Sự kiện", rendered in headless Chrome from site/ and measured.
//   node tests/capture-mobile-sap-xep.mjs --data <dir> [--out <dir>] [--tag <prefix>]
// <dir> holds a downloaded radar-window.json, radar-ui.json and field-rankings.json (the live snapshot); the page runs
// at the real clock. Phone widths are emulated as a touch phone (isMobile, hasTouch) and every tap is a touch tap.
// One JSON line on stdout: per width, the order control's boxes, sideways scroll, the first three titles before and
// after tapping "Mới nhất", and the events view reached from the dock. Nothing under site/ or data/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const tag = arg('--tag', '');
const dataDir = arg('--data', '');
if (!dataDir) throw new Error('--data <dir> is required');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
// --site <dir>: serve a built copy of site/ (its index.html stamped with asset versions by radar/front_lead.py).
const siteDir = path.resolve(arg('--site', path.join(root, 'site')));
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const served = new Set();   // every script and stylesheet address the pages asked for, with its query
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (/\.(js|css)$/.test(p)) served.add(req.url);
  try {
    let file;
    if (p.startsWith('/data/')) file = path.join(dataDir, path.basename(p));
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

const MEASURE = () => {
  const r = el => el.getBoundingClientRect();
  const shown = el => { const b = r(el); return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none'; };
  const box = el => { const b = r(el); return { x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }; };
  const sorts = [...document.querySelectorAll('#sort-switch .sort-btn')].filter(shown).map(el => ({
    sort: el.dataset.sort, text: el.textContent.trim(), pressed: el.getAttribute('aria-pressed'), ...box(el),
    inView: r(el).left >= 0 && r(el).right <= innerWidth, font: parseFloat(getComputedStyle(el).fontSize) }));
  const head = document.querySelector('#bar');
  const headControls = head ? [...head.querySelectorAll('a, button')].filter(shown).map(el => ({ cls: String(el.className).split(' ')[0], text: el.textContent.trim().slice(0, 20), ...box(el) })) : [];
  // The stories under the lead carousel ("Tin nổi bật" keeps its own choice in either order), in the page's order.
  const titles = [...document.querySelectorAll('#feed-grid .nc-title')].filter(shown).slice(0, 3).map(el => el.textContent.trim());
  const lead = document.querySelector('#feed-grid .slide.is-active .slide-title')?.textContent.trim() || null;
  return {
    width: innerWidth, sideways: document.scrollingElement.scrollWidth > innerWidth, scrollWidth: document.scrollingElement.scrollWidth,
    sorts, headControls, headRows: [...new Set(headControls.map(c => c.y))].length, lead, titles,
    hash: location.hash, eventsView: !!document.querySelector('#feed-grid .bt'),
    view: document.querySelector('#filter-context .filter-name')?.textContent || null,
  };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'mobile-sap-xep-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { chrome: browser.process()?.pid ?? null, runs: {}, errors: [] };

async function open(ctx, width, theme, hash = '') {
  const page = await ctx.newPage();
  const phone = width < 768;
  await page.setViewport({ width, height: phone ? 812 : 900, deviceScaleFactor: 1, isMobile: phone, hasTouch: phone });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument(t => { try { localStorage.setItem('air2:theme', JSON.stringify(t)); } catch {} }, theme);
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    const ok = u.startsWith(site) || u.startsWith('data:') || (req.resourceType() === 'image' && u.startsWith('https://'));
    return ok ? req.continue() : req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${width}: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error' && !/net::ERR_FAILED|Failed to load resource/.test(m.text())) result.errors.push(`${width} console: ${m.text()}`); });
  await page.goto(site + hash, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#feed-grid > *'), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  await wait(800);
  return page;
}
const shot = async (page, name) => { if (out) await page.screenshot({ path: path.join(out, `${tag}${name}.png`) }); };

try {
  for (const [width, theme] of [[320, 'light'], [375, 'light'], [414, 'light'], [375, 'dark'], [1440, 'light'], [2000, 'light']]) {
    const ctx = await browser.createBrowserContext();
    const page = await open(ctx, width, theme);
    const key = `${width}${theme === 'dark' ? '-toi' : ''}`;
    const m = await page.evaluate(MEASURE);
    result.runs[key] = m;
    await shot(page, `trang-nhat-${key}`);
    if (key === '375') {
      // Tap "Mới nhất" as a finger would, then read the feed's first three titles again.
      const next = await page.$('#sort-switch .sort-btn[data-sort="new"]');
      const visible = next && await next.evaluate(el => el.getBoundingClientRect().width > 0);
      if (visible) await next.tap(); else result.errors.push('375: no visible "Mới nhất" button');
      await wait(900);
      result.runs['375-moi-nhat'] = await page.evaluate(MEASURE);
      await shot(page, 'trang-nhat-375-moi-nhat');
      // Back to the page's default, then the dock's "Sự kiện" by touch.
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#feed-grid > *'), { timeout: 30000 });
      await wait(600);
      const dock = await page.$('.mobile-nav-link[data-dest="events"]');
      if (dock) await dock.tap(); else result.errors.push('375: no dock "Sự kiện" link');
      await page.waitForFunction(() => document.querySelector('#feed-grid .bt'), { timeout: 15000 }).catch(() => result.errors.push('375: events view not drawn after the dock tap'));
      await wait(800);
      result.runs['375-sap-toi'] = await page.evaluate(MEASURE);
      result.runs['375-sap-toi'].dockCurrent = await page.evaluate(() => document.querySelector('.mobile-nav-link[aria-current="page"]')?.textContent.trim() || null);
      await shot(page, 'sap-toi-375');
    }
    await ctx.close();
  }
} catch (e) {
  result.errors.push(String(e && e.stack || e));
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
result.served = [...served].sort();
process.stdout.write(JSON.stringify(result) + '\n');

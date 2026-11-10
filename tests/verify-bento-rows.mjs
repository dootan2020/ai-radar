// The front page's bento bands, rendered in headless Chrome from tests/fixtures/radar-window-sample.json (offline: every
// other data file answers 404), at 1440, 1024 and 768 px with reduced motion. Prints one JSON line per width: each band's
// rows with unequal card heights, rows that are not full, cards whose content runs past their edge, list rows or filters
// cut by their card, the "Translated" labels on the page, and the Kho mã tile's visible filter rows closed and opened.
// Run by tests/test_bento_trang_nhat.py; nothing under site/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
const fixture = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
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
const url = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));

const MEASURE = () => {
  const r = el => el.getBoundingClientRect();
  const shown = el => { const b = r(el); return b.height > 0 && b.width > 0; };
  const name = el => (el.querySelector('h2,h3')?.textContent || el.className).trim().replace(/\s+/g, ' ').slice(0, 24);
  const past = (k, kb) => {
    let worst = 0;
    const walk = el => {
      for (const c of el.children) {
        const cs = getComputedStyle(c);
        if (cs.display === 'none' || cs.position === 'absolute' || cs.position === 'fixed' || c.hidden) continue;
        const b = r(c);
        if (b.height > 0) worst = Math.max(worst, b.bottom - kb.bottom);
        if (cs.overflowY === 'visible' && cs.overflowX === 'visible') walk(c);
      }
    };
    walk(k);
    return worst;
  };
  const bands = [...document.querySelectorAll('#feed-grid .band')].filter(shown).map(band => {
    const grid = band.querySelector(':scope > .band-cells, :scope > .band-grid');
    const g = r(grid), gap = parseFloat(getComputedStyle(grid).columnGap) || 0;
    const kids = [...grid.children].filter(shown);
    const rows = new Map();
    for (const k of kids) { const t = Math.round(r(k).top); (rows.get(t) || rows.set(t, []).get(t)).push(k); }
    const unequal = [], ragged = [], overflow = [], cut = [];
    for (const [t, ks] of rows) {
      const hs = ks.map(k => Math.round(r(k).height));
      if (new Set(hs).size > 1) unequal.push(`${t}:${hs.join('/')}`);
      const used = ks.reduce((a, k) => a + r(k).width, 0) + gap * (ks.length - 1);
      if (Math.abs(used - g.width) > 2) ragged.push(`${t}:${Math.round(used)}/${Math.round(g.width)}`);
    }
    for (const k of kids) {
      const kb = r(k), p = past(k, kb);
      if (p > 1) overflow.push(`${name(k)} +${Math.round(p)}`);
      for (const row of k.querySelectorAll('li, .repo-cell, .model, .brief, .seg, .area-chips, .repo-ctl, .tile-foot, .ev-foot')) {
        if (!shown(row) || row.closest('[hidden]')) continue;
        const b = r(row);
        if (b.bottom > kb.bottom + 1 || b.top < kb.top - 1) cut.push(`${name(k)}: ${String(row.className).split(' ')[0] || row.tagName}`);
      }
    }
    return { band: band.querySelector('.band-title')?.textContent.trim(), rows: rows.size, unequal, ragged, overflow, cut };
  });
  // The Kho mã tile's filter rows: the distinct tops of its visible controls.
  const repoFilterRows = () => {
    const tile = document.querySelector('#lab .tile-repos'); if (!tile) return null;
    const ctl = [...tile.querySelectorAll('.seg, .area-chips')].filter(shown);
    return new Set(ctl.map(c => Math.round(r(c).top))).size;
  };
  return { cols: getComputedStyle(document.documentElement).getPropertyValue('--bento-cols').trim(), bands,
    translated: [...document.querySelectorAll('#feed-grid .mt')].filter(shown).length,
    sideways: document.scrollingElement.scrollWidth > innerWidth, repoFilterRows: repoFilterRows() };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'bento-rows-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, userDataDir: profile, args: ['--disable-gpu'], timeout: 20000 });
const out = {};
try {
  for (const width of [1440, 1024, 768]) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(() => document.querySelector('#band-more') && document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 30000 });
    await page.evaluate(() => document.fonts.ready);
    await wait(1200);
    const m = await page.evaluate(MEASURE);
    const opener = await page.$('[data-lab-open]');
    let opened = null;
    if (opener) { await opener.click(); await wait(400); opened = (await page.evaluate(MEASURE)).repoFilterRows; }
    out[width] = { ...m, repoFilterRowsOpen: opened, errors };
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(out) + '\n');

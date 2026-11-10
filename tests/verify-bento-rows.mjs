// The front page's bento bands, rendered in headless Chrome from tests/fixtures/radar-window-sample.json (offline: every
// other data file answers 404), at 1440, 1024 and 768 px with reduced motion. Prints one JSON line per width: each band's
// rows with unequal card heights, rows that are not full, cards whose content runs past their edge, list rows or filters
// cut by their card, the "Translated" labels on the page, the Kho mã tile's visible filter rows closed and opened, and,
// on a short window (/cuon/), what scrolling to the sentinel appends: card counts per load, "Tin khác" measured after
// it (rows, older day headings) and the live announcement.
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
// Under /cuon/ the page reads a short window (the fixture's first 90 stories) and a complete snapshot that adds twelve
// older stories (copies moved six and seven days back), so a few scrolls reach the older days and their headings.
const win = JSON.parse(fixture.toString('utf8')), gen = Date.parse(win.generated_at);
const shortWin = { ...win, stories: win.stories.slice(0, 90) };
const older = win.stories.slice(0, 12).map((st, i) => ({ ...st, id: `${st.id}-cu-${i}`, url: `${st.url}#cu-${i}`,
  published_at: new Date(gen - (i < 7 ? 6 : 7) * 864e5 - i * 36e5).toISOString() }));
const shortData = Buffer.from(JSON.stringify(shortWin));
const fullData = Buffer.from(JSON.stringify({ ...shortWin, stories: [...shortWin.stories, ...older] }));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const scroll = p.startsWith('/cuon/');
  if (scroll) p = p.slice('/cuon'.length);
  try {
    const json = body => { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(body); };
    if (p === '/data/radar-window.json') return json(scroll ? shortData : fixture);
    if (p === '/data/radar.json') return json(scroll ? fullData : fixture);
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
    // Every grid of the band: one, or in "Tin khác" one per group (the window's rest, then each older day).
    const grids = [...band.querySelectorAll('.band-cells, .band-grid')].filter(g => !g.parentElement.closest('.band-cells, .band-grid'));
    const one = grid => {
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
    return { rows: rows.size, unequal, ragged, overflow, cut };
    };
    const parts = grids.filter(shown).map(one);
    const sum = key => parts.flatMap(p => p[key]);
    return { band: band.querySelector('.band-title')?.textContent.trim(), rows: parts.reduce((a, p) => a + p.rows, 0),
      unequal: sum('unequal'), ragged: sum('ragged'), overflow: sum('overflow'), cut: sum('cut'),
      days: band.querySelectorAll('.day-line').length, cards: band.querySelectorAll('.nc').length };
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
    // The short window: scroll to the end of "Tin khác" until an older day's heading has arrived (at most ten loads).
    // Whole rows arrive by themselves, then the older days under a heading.
    await page.goto(`${url}cuon/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(() => document.querySelector('#band-more') && document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 30000 });
    await wait(800);
    const scrolls = [];
    for (let i = 0; i < 10 && !(await page.$('#more-box .day-line')); i++) {
      const before = await page.$$eval('#more-box .nc', e => e.length);
      await page.evaluate(() => document.querySelector('#feed-sentinel').scrollIntoView({ block: 'end' }));
      await page.waitForFunction(b => document.querySelectorAll('#more-box .nc').length > b, { timeout: 20000 }, before).catch(() => {});
      await wait(800);
      scrolls.push([before, await page.$$eval('#more-box .nc', e => e.length)]);
    }
    const after = await page.evaluate(MEASURE);
    const extra = await page.evaluate(() => ({ status: document.querySelector('#more-status')?.textContent || '',
      buttons: document.querySelectorAll('#band-more button, #more-btn').length,
      moreText: [...document.querySelectorAll('#top button, #top a')].some(b => /Xem thêm tin/.test(b.textContent)) }));
    out[width] = { ...m, repoFilterRowsOpen: opened, errors, scrolls, afterScroll: after.bands.find(b => b.band === 'Tin khác'),
      afterSideways: after.sideways, ...extra };
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(out) + '\n');

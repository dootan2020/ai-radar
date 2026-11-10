// The front page's bento bands in Chrome against this worktree, with the live snapshot (real data; the fixture if the
// live site cannot be reached): every band's rows measured at 375, 768, 1024, 1440, 1920 and 2560 in light, and at
// 1440 and 375 in dark. For each width it reports rows of unequal height, rows that are not full, cards whose content
// overflows, list rows or filters cut by their card, source names cut, "Translated" labels on the front page, controls
// under 44 px, text under 12 px, sideways scroll, and (from 1024) whether the day's picture is still in sight in the
// gutters after scrolling 700 px. Screenshots: the full page at each width, the viewport scrolled 700 px at 1920, each
// band at 1440, the Kho mã tile closed and opened, a list row under the pointer, and the unpacked extension at 1440.
// node tests/capture-bento.mjs --out bento-anh
// Nothing under site/ is written; the server below only reads it.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = path.resolve(root, arg('--out', 'bento-anh'));
const only = arg('--only', 'site,ext').split(',');
const loads = Number(arg('--loads', 0));      // --loads 2: scroll to the end of "Tin khác" twice, then measure (--runs)
const LIVE = 'https://radar-ai-vn.pages.dev/';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
await fs.mkdir(out, { recursive: true });

const fixture = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'));
const packaged = await fs.readFile(path.join(root, 'site/anh/nen-du-phong.webp'));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const liveCache = new Map(), liveUsed = new Set();
async function live(p) {
  if (liveCache.has(p)) return liveCache.get(p);
  let got = null;
  try {
    const r = await fetch(LIVE + p.slice(1), { signal: AbortSignal.timeout(20000) });
    if (r.ok) got = { type: r.headers.get('content-type') || TYPES[path.extname(p)], body: Buffer.from(await r.arrayBuffer()) };
  } catch {}
  liveCache.set(p, got);
  return got;
}
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p.startsWith('/data/') || p.startsWith('/nen/')) {
      const got = await live(p);
      if (got) { liveUsed.add(p); res.writeHead(200, { 'content-type': got.type }); return res.end(got.body); }
      if (/^\/data\/radar(-window)?\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(fixture); }
      if (p.startsWith('/nen/') && !p.endsWith('.json')) { res.writeHead(200, { 'content-type': 'image/webp' }); return res.end(packaged); }
      res.writeHead(404); return res.end();
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
const summary = [], problems = [], details = {};
console.log(`server ${url}; out ${out}`);

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'bento-'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, pipe: true, enableExtensions: true,
  userDataDir: profile, args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
console.log(`Chrome PID ${browser.process().pid}`);

async function open(width, theme, height) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const touch = width < 768;
  await page.setViewport({ width, height, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument(t => { localStorage.setItem('air2:theme', JSON.stringify(t)); }, theme);
  page.on('pageerror', e => problems.push(`page error at ${width}px ${theme}: ${e.message}`));
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#band-more'), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => { document.querySelectorAll('img[loading="lazy"]').forEach(i => { i.loading = 'eager'; }); });
  await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready') || innerWidth < 768, { timeout: 15000 }).catch(() => {});
  await page.waitForFunction(() => !document.querySelector('#arena-tile .arena-tile-empty'), { timeout: 10000 }).catch(() => {});
  await wait(1500);
  return { page, ctx };
}

// Every band's rows: equal heights, full, nothing overflowing or cut.
const MEASURE = () => {
  const r = el => el.getBoundingClientRect();
  const shown = el => { const b = r(el); return b.height > 0 && b.width > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const name = el => (el.querySelector('h2,h3')?.textContent || el.className).trim().replace(/\s+/g, ' ').slice(0, 24);
  const bands = [...document.querySelectorAll('#feed-grid .band')].filter(shown).map(band => {
    // Every grid of the band: one, or in "Tin khác" one per group (the window's rest, then each older day).
    const grids = [...band.querySelectorAll('.band-cells, .band-grid')].filter(g => !g.parentElement.closest('.band-cells, .band-grid'));
    const one = grid => {
    const g = r(grid), cs = getComputedStyle(grid), gap = parseFloat(cs.columnGap) || 0;
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
    // Content past a card's edge: every in-flow element, walking down only through boxes that do not clip (a clamped
    // headline or a picture frame clips its own content on purpose; the calendar's animal is absolutely placed art).
    const past = (k, kb) => {
      let worst = 0, what = '';
      const walk = el => {
        for (const c of el.children) {
          const cs = getComputedStyle(c);
          if (cs.display === 'none' || cs.position === 'absolute' || cs.position === 'fixed' || c.hidden) continue;
          const b = r(c);
          if (b.height > 0 && b.bottom - kb.bottom > worst) { worst = b.bottom - kb.bottom; what = String(c.className || c.tagName).split(' ')[0]; }
          if (cs.overflowY === 'visible' && cs.overflowX === 'visible') walk(c);
        }
      };
      walk(k);
      return worst > 1 ? `${what} +${Math.round(worst)}` : '';
    };
    for (const k of kids) {
      const kb = r(k);
      const p = past(k, kb);
      if (p) overflow.push(`${name(k)}: ${p}`);
      if (kb.bottom > g.bottom + 1) overflow.push(`${name(k)} past band +${Math.round(kb.bottom - g.bottom)}`);
      for (const row of k.querySelectorAll('li, .repo-cell, .model, .brief, .seg, .area-chips, .repo-ctl, .tile-foot, .ev-foot, .cal-note, .cal-canchi, .wx-foot')) {
        if (!shown(row) || row.closest('[hidden]')) continue;
        const b = r(row);
        if (b.bottom > kb.bottom + 1 || b.top < kb.top - 1) cut.push(`${name(k)}: ${String(row.className).split(' ')[0] || row.tagName} ${Math.round(b.bottom - kb.bottom)}`);
      }
    }
    return { rows: rows.size, items: kids.length, heights: [...rows.values()].map(ks => Math.round(r(ks[0]).height)), unequal, ragged, overflow, cut };
    };
    const parts = grids.filter(shown).map(one);
    const sum = key => parts.flatMap(p => p[key]);
    return { band: band.querySelector('.band-title')?.textContent.trim(), rows: parts.reduce((a, p) => a + p.rows, 0),
      items: parts.reduce((a, p) => a + p.items, 0), heights: sum('heights').join('/'),
      unequal: sum('unequal'), ragged: sum('ragged'), overflow: sum('overflow'), cut: sum('cut'),
      days: [...band.querySelectorAll('.day-line')].map(h => h.textContent.trim()) };
  });
  const srcCut = [...document.querySelectorAll('#feed-grid .nc-src, #feed-grid .top-src')].filter(e => shown(e) && e.scrollWidth > e.clientWidth + 1).map(e => e.textContent);
  const translated = [...document.querySelectorAll('#feed-grid .mt')].filter(shown).length;
  const small = [...document.querySelectorAll('#top button, #top a')].filter(e => shown(e) && !e.closest('.story-link, .nc-title, .slide-title') && !e.classList.contains('story-link'))
    .map(e => [e, r(e)]).filter(([, b]) => b.height < 44 - 0.5).map(([e, b]) => `${(e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 18)} ${Math.round(b.width)}x${Math.round(b.height)}`);
  const tiny = new Set();
  for (const el of document.querySelectorAll('#top *')) {
    if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    if (!shown(el) || el.closest('.sr, [hidden]')) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize); if (fs < 12) tiny.add(`${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]} ${fs}px`);
  }
  const panel = r(document.querySelector('.feed-main.front'));
  return { cols: getComputedStyle(document.documentElement).getPropertyValue('--bento-cols').trim(), panelW: Math.round(panel.width),
    contentW: Math.round(r(document.querySelector('#feed-grid')).width), gutter: Math.round(panel.left),
    sideways: document.scrollingElement.scrollWidth > innerWidth, bands, srcCut, translated, small: small.slice(0, 12), tiny: [...tiny].slice(0, 12) };
};

// After scrolling 700 px: the picture layer is drawn, has no veil over it, and shows in the gutters beside the panel.
const BACKGROUND = () => {
  const nen = document.querySelector('#nen'), img = nen?.querySelector('img');
  const after = nen ? getComputedStyle(nen, '::after') : null;
  const panel = document.querySelector('.feed-main.front').getBoundingClientRect();
  return { drawn: !!nen && getComputedStyle(nen).display !== 'none', ready: !!nen?.classList.contains('is-ready'), imgOpacity: img ? getComputedStyle(img).opacity : null,
    veil: after ? (after.content !== 'none' && after.content !== 'normal' ? `content ${after.content} opacity ${after.opacity}` : 'none') : 'none',
    gutter: Math.round(panel.left), scrolled: Math.round(scrollY) };
};

const shotEl = async (page, sel, file) => { const el = await page.$(sel); if (!el) { problems.push(`no ${sel} for ${file}`); return; } await el.screenshot({ path: path.join(out, file) }); };

// Scroll to the end of "Tin khác" `n` times; each time wait until new cards arrive (the sentinel loads whole rows).
async function scrollLoads(page, n) {
  const steps = [];
  for (let i = 0; i < n; i++) {
    const before = await page.$$eval('#more-box .nc', e => e.length);
    await page.evaluate(() => document.querySelector('#feed-sentinel').scrollIntoView({ block: 'end' }));
    await page.waitForFunction(b => document.querySelectorAll('#more-box .nc').length > b, { timeout: 20000 }, before).catch(() => {});
    await wait(1500);
    steps.push(`${before}->${await page.$$eval('#more-box .nc', e => e.length)}`);
  }
  return steps;
}

try {
  if (loads) {
    // After `loads` scrolls to the end: every row of every band level and full, the day headings, no sideways scroll.
    for (const run of arg('--runs', '1440-light,1024-light,375-light').split(',')) {
      const [w, theme] = run.split('-'), width = Number(w);
      const height = width < 768 ? 812 : width >= 1440 ? 900 : 768;
      const { page, ctx } = await open(width, theme, height);
      const steps = await scrollLoads(page, loads);
      const m = await page.evaluate(MEASURE);
      const more = m.bands.find(b => b.band === 'Tin khác');
      const status = await page.$eval('#more-status', e => e.textContent);
      const buttons = await page.$$eval('#band-more button, #more-btn', e => e.length);
      details[run] = { steps, status, buttons, more, bands: m.bands };
      await page.screenshot({ path: path.join(out, `${run}-cuoi.png`) });
      const day = await page.$('#more-box .day-line');
      if (day) { await page.evaluate(el => el.scrollIntoView({ block: 'start' }), day); await wait(500); await page.screenshot({ path: path.join(out, `${run}-ngay.png`) }); }
      m.bands.flatMap(b => [...b.unequal, ...b.ragged, ...b.overflow, ...b.cut].map(x => `${b.band} ${x}`)).forEach(x => problems.push(`${run}: ${x}`));
      if (m.sideways) problems.push(`${run}: page scrolls sideways`);
      if (buttons) problems.push(`${run}: a button is left in "Tin khác"`);
      summary.push({ name: run, loads: steps.join(' '), cols: m.cols, moreRows: more?.rows, moreCards: more?.items, days: more?.days.join(' / '),
        unequal: m.bands.reduce((a, b) => a + b.unequal.length, 0), ragged: m.bands.reduce((a, b) => a + b.ragged.length, 0),
        overflow: m.bands.reduce((a, b) => a + b.overflow.length, 0), cut: m.bands.reduce((a, b) => a + b.cut.length, 0), sideways: m.sideways, status });
      await ctx.close();
    }
  }
  if (!loads && only.includes('site')) {
    const runs = [[375, 'light'], [768, 'light'], [1024, 'light'], [1440, 'light'], [1920, 'light'], [2560, 'light'], [1440, 'dark'], [375, 'dark']];
    for (const [width, theme] of runs) {
      const height = width < 768 ? 812 : width >= 1920 ? 1080 : width >= 1440 ? 900 : 768;
      const name = `${width}-${theme}`;
      const { page, ctx } = await open(width, theme, height);
      const m = await page.evaluate(MEASURE);
      details[name] = m;
      // The whole page as a window that tall would show it (a full-page capture of a short window can catch the tiles
      // mid-refit); then back to the measured window.
      const tall = await page.evaluate(() => document.scrollingElement.scrollHeight);
      await page.setViewport({ width, height: Math.min(tall, 16000), deviceScaleFactor: 1, hasTouch: width < 768, isMobile: width < 768 });
      await wait(900);
      await page.screenshot({ path: path.join(out, `full-${name}.png`) });
      await page.setViewport({ width, height, deviceScaleFactor: 1, hasTouch: width < 768, isMobile: width < 768 });
      await wait(600);
      let bg = null;
      if (width >= 1024) {
        await page.evaluate(() => window.scrollTo(0, 700)); await wait(600);
        bg = await page.evaluate(BACKGROUND);
        details[name].background = bg;
        if (width === 1920 && theme === 'light') await page.screenshot({ path: path.join(out, `scroll700-${name}.png`) });
        if (!bg.drawn || !bg.ready || bg.imgOpacity !== '1' || bg.veil !== 'none' || bg.gutter < 8) problems.push(`${name}: background after 700px ${JSON.stringify(bg)}`);
        await page.evaluate(() => window.scrollTo(0, 0)); await wait(300);
      }
      const bad = m.bands.flatMap(b => [...b.unequal.map(x => `${b.band} unequal ${x}`), ...b.ragged.map(x => `${b.band} ragged ${x}`),
        ...b.overflow.map(x => `${b.band} overflow ${x}`), ...b.cut.map(x => `${b.band} cut ${x}`)]);
      bad.forEach(x => problems.push(`${name}: ${x}`));
      if (m.sideways) problems.push(`${name}: page scrolls sideways`);
      if (m.srcCut.length) problems.push(`${name}: source names cut: ${m.srcCut.join(', ')}`);
      if (m.translated) problems.push(`${name}: ${m.translated} "Translated" labels on the front page`);
      if (m.small.length) problems.push(`${name}: controls under 44px: ${m.small.join('; ')}`);
      if (m.tiny.length) problems.push(`${name}: text under 12px: ${m.tiny.join('; ')}`);
      summary.push({ name, cols: m.cols, contentW: m.contentW, gutter: m.gutter,
        unequal: m.bands.reduce((a, b) => a + b.unequal.length, 0), ragged: m.bands.reduce((a, b) => a + b.ragged.length, 0),
        overflow: m.bands.reduce((a, b) => a + b.overflow.length, 0), cut: m.bands.reduce((a, b) => a + b.cut.length, 0),
        sideways: m.sideways, srcCut: m.srcCut.length, translated: m.translated, bgAfter700: bg ? (bg.veil === 'none' && bg.imgOpacity === '1' && bg.gutter >= 8 ? `yes (${bg.gutter}px)` : 'NO') : 'n/a',
        rows: m.bands.map(b => `${b.band}:${b.heights}`).join(' | ') });

      if (width === 1440 && theme === 'light') {
        for (const id of ['today', 'focus', 'news', 'lab', 'more']) await shotEl(page, id === 'lab' ? '#lab' : `#band-${id}`, `band-${id}-1440.png`);
        await shotEl(page, '.tile-repos', 'kho-ma-dong-1440.png');
        await page.$eval('[data-lab-open]', b => b.click()); await wait(500);
        const opened = await page.evaluate(MEASURE);
        const lab = opened.bands.find(b => b.band === 'Mô hình và mã nguồn');
        details['lab-open-1440'] = lab;
        await shotEl(page, '.tile-repos', 'kho-ma-mo-1440.png');
        await shotEl(page, '#lab', 'band-lab-mo-1440.png');
        if (lab.unequal.length || lab.ragged.length) problems.push(`lab opened: ${JSON.stringify(lab)}`);
        await page.$eval('[data-lab-open]', b => b.click()); await wait(400);
        // The list hover: the second "Chuyện lớn" row under the pointer.
        const row = await page.$('#top-list li:nth-child(2)');
        await row.scrollIntoView(); const box = await row.boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await wait(400);
        await shotEl(page, '#top-list', 'hover-chuyen-lon-1440.png');
        const fr = await page.$('#fresh-row li:nth-child(2) .brief');
        if (fr) { const b2 = await fr.boundingBox(); await page.mouse.move(b2.x + b2.width / 2, b2.y + b2.height / 2); await wait(400); await shotEl(page, '#fresh-row', 'hover-vua-dang-1440.png'); }
      }
      await ctx.close();
    }
  }

  if (!loads && only.includes('ext')) {
    const id = await browser.installExtension(path.join(root, 'extension'));
    const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
    const worker = await sw.worker();
    const snap = JSON.parse(((await live('/data/radar-window.json'))?.body || fixture).toString('utf8'));
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
    // Cards below the fold wait in their entrance offset until scrolled to; reduced motion measures them at rest.
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), snap);
    page.on('pageerror', e => problems.push(`extension page error: ${e.message}`));
    await page.goto(`chrome-extension://${id}/newtab.html`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('#band-more'), { timeout: 20000 }).catch(() => problems.push('extension: bands never drawn'));
    await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready'), { timeout: 15000 }).catch(() => {});
    await wait(2500);
    const m = await page.evaluate(MEASURE).catch(e => ({ error: String(e) }));
    details['ext-1440'] = m;
    await page.screenshot({ path: path.join(out, 'ext-1440-light.png') });
    await page.screenshot({ path: path.join(out, 'ext-1440-light-full.png'), fullPage: true });
    if (m.bands) m.bands.forEach(b => [...b.unequal, ...b.ragged, ...b.overflow, ...b.cut].forEach(x => problems.push(`ext-1440: ${b.band} ${x}`)));
    summary.push({ name: 'ext-1440-light', cols: m.cols, contentW: m.contentW, unequal: m.bands?.reduce((a, b) => a + b.unequal.length, 0), ragged: m.bands?.reduce((a, b) => a + b.ragged.length, 0),
      overflow: m.bands?.reduce((a, b) => a + b.overflow.length, 0), cut: m.bands?.reduce((a, b) => a + b.cut.length, 0), sideways: m.sideways, translated: m.translated,
      rows: m.bands?.map(b => `${b.band}:${b.heights}`).join(' | ') });
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
console.table(summary.map(({ rows, ...s }) => s));
for (const s of summary) console.log(s.name, s.rows);
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ live: [...liveUsed], summary, problems, details }, null, 2));
if (problems.length) { console.log(`PROBLEMS (${problems.length})\n` + problems.slice(0, 80).join('\n')); process.exitCode = 1; }
else console.log('No problems measured.');

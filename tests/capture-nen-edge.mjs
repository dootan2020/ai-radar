// The Edge-style front page, in Chrome against this worktree: the first screen at 375/1440/2000/2560 in light and dark,
// where the 9-dot launcher sits against the news panel, "Vừa đăng" after the "N tin mới" pill with a batch of six
// (every pinned row whole and reachable), and the unpacked extension's requests for the day's picture.
// node tests/capture-nen-edge.mjs --out nen-edge-sau-anh/after
// The site is served from site/ by a small server in this script; every data/*.json is tests/fixtures/
// radar-window-sample.json, and nen/* comes from the live site (the extension reads it there too), else the packaged
// picture. Nothing under site/ is written. Arrival of new stories is simulated inside the headless page only.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = path.resolve(root, arg('--out', 'nen-edge-sau-anh/run'));
const only = arg('--only', 'site,fresh,ext').split(',');
const LIVE = 'https://radar-ai-vn.pages.dev/';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
await fs.mkdir(out, { recursive: true });

const full = JSON.parse(await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8'));
const packaged = await fs.readFile(path.join(root, 'site/anh/nen-du-phong.webp'));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const nenLog = [];
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p.startsWith('/nen/')) {
      nenLog.push(p);
      try {
        const live = await fetch(LIVE + p.slice(1), { signal: AbortSignal.timeout(10000) });
        if (!live.ok) throw new Error(String(live.status));
        res.writeHead(200, { 'content-type': live.headers.get('content-type') || TYPES[path.extname(p)], 'cache-control': 'max-age=3600' });
        return res.end(Buffer.from(await live.arrayBuffer()));
      } catch {
        if (p.endsWith('lich.json')) { res.writeHead(404); return res.end(); }
        res.writeHead(200, { 'content-type': 'image/webp' }); return res.end(packaged);
      }
    }
    if (/^\/data\/[\w.-]+\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(full)); }
    let file = path.join(root, 'site', p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const summary = [], problems = [];
console.log(`server ${url}; snapshot ${full.generated_at}; out ${out}`);

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'nen-edge-'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, pipe: true, enableExtensions: true,
  userDataDir: profile, args: ['--disable-gpu'], timeout: 20000 });
console.log(`Chrome PID ${browser.process().pid}`);

const gen = Date.parse(full.generated_at), winH = Number(full.ranking?.window_hours) || 72;
const newest = n => full.stories.filter(s => { const t = Date.parse(s.published_at); return t >= gen - winH * 36e5 && t <= gen; })
  .sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at)).slice(0, n);

async function open(width, theme, { held = [], height = 900 } = {}) {
  const ids = new Set(held);
  const base = { ...full, stories: full.stories.filter(s => !ids.has(s.id)) };
  const later = { ...full, generated_at: new Date(gen + 3e5).toISOString() };
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.bringToFront();
  const touch = width < 768;
  await page.setViewport({ width, height, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument((t, seen) => {
    localStorage.setItem('air2:theme', JSON.stringify(t));
    localStorage.setItem('air2:lastSeen', JSON.stringify(seen));
  }, theme, full.generated_at);
  const state = { later: false };
  page.on('pageerror', e => problems.push(`page error at ${width}px: ${e.message}`));
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (!/\/data\/[\w.-]+\.json/.test(req.url())) return req.continue();
    req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(state.later ? later : base) });
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#fresh-row'), { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready') || innerWidth < 768, { timeout: 15000 }).catch(() => {});
  await wait(700);
  return { page, ctx, state };
}

async function arrive(page, state) {
  state.later = true;
  for (let i = 0; i < 10 && await page.$('#fresh[hidden]'); i++) {
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await wait(1500);
  }
  await page.waitForSelector('#fresh:not([hidden])', { timeout: 5000 });
  await wait(300);
}

// Each "Vừa đăng" row against the box the tile shows: whole, cut by the tile's edge, or out of sight.
const freshRows = page => page.evaluate(() => {
  const tile = document.querySelector('#fresh-row');
  const cs = getComputedStyle(tile), r = tile.getBoundingClientRect();
  const top = r.top + parseFloat(cs.borderTopWidth), bottom = r.bottom - parseFloat(cs.borderBottomWidth);
  const rows = [...tile.querySelectorAll('.fresh-list > li')].map(li => {
    const b = li.getBoundingClientRect();
    const shown = b.height > 0 && getComputedStyle(li).display !== 'none' && !li.closest('[hidden]');
    const state = !shown ? 'paged' : b.top >= top - 0.5 && b.bottom <= bottom + 0.5 ? 'whole' : b.top < bottom && b.bottom > top ? 'cut' : 'out';
    return { pinned: li.hasAttribute('data-pinned'), chip: getComputedStyle(li.querySelector('.fresh-new')).display !== 'none', state };
  });
  const ctrls = [...tile.querySelectorAll('button')].filter(b => b.offsetParent).map(b => { const q = b.getBoundingClientRect(); return [Math.round(q.width), Math.round(q.height), b.getAttribute('aria-label') || b.textContent.trim()]; });
  return { tileH: Math.round(r.height), scrolls: tile.scrollHeight > tile.clientHeight + 1, rows, ctrls,
    overflow: document.documentElement.scrollWidth > innerWidth };
});

try {
  if (only.includes('site')) {
    for (const width of [375, 1440, 2000, 2560]) for (const theme of ['light', 'dark']) {
      const { page, ctx } = await open(width, theme, { height: width < 768 ? 812 : width >= 2000 ? 1300 : 900 });
      const m = await page.evaluate(() => {
        const rect = el => { if (!el) return null; const r = el.getBoundingClientRect(); return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom) }; };
        const launcher = document.querySelector('.tool-launcher-button'), panel = document.querySelector('.feed-main.front.msn-panel');
        const L = rect(launcher), P = rect(panel);
        return { launcher: L, panel: P, gap: L && P ? P.t - L.b : null, nen: document.querySelector('#nen img')?.currentSrc?.replace(location.origin, '') ?? null,
          overflow: document.documentElement.scrollWidth > innerWidth };
      });
      await page.screenshot({ path: path.join(out, `site-${width}-${theme}.png`) });
      // While the page scrolls: does the launcher ever overlap the panel or sit within 8px of its edge?
      m.scrolled = [];
      for (const y of [150, 300, 450, 600, 900]) {
        m.scrolled.push(await page.evaluate(y => {
          window.scrollTo(0, y);
          const a = document.querySelector('.tool-launcher-button')?.getBoundingClientRect(), b = document.querySelector('.feed-main.front.msn-panel').getBoundingClientRect();
          if (!a || !a.width) return `${y}:hidden`;
          const near = a.right > b.left - 8 && a.left < b.right + 8 && a.bottom > b.top - 8 && a.top < b.bottom + 8;
          return `${y}:${near ? 'NEAR' : 'clear'}(${Math.round(b.top - a.bottom)})`;
        }, y));
      }
      if (m.scrolled.some(s => s.includes('NEAR')) && width >= 768) problems.push(`site-${width}-${theme}: launcher meets the panel while scrolling ${m.scrolled.join(' ')}`);
      m.scrolled = m.scrolled.join(' ');
      await page.evaluate(() => window.scrollTo(0, 0));
      const f = await freshRows(page);         // "Vừa đăng" before any new story: which rows show, and whole?
      m.freshDefault = f.rows.map(r => r.state[0]).join('');
      if (f.rows.some(r => r.state === 'cut')) problems.push(`site-${width}-${theme}: a "Vừa đăng" row is cut`);
      summary.push({ name: `site-${width}-${theme}`, ...m, launcher: JSON.stringify(m.launcher), panel: JSON.stringify(m.panel) });
      if (m.overflow) problems.push(`site-${width}-${theme}: page scrolls sideways`);
      if (m.gap !== null && m.gap < 8 && width >= 768) problems.push(`site-${width}-${theme}: launcher ${m.gap}px from the panel`);
      await ctx.close();
    }
  }

  if (only.includes('fresh')) {
    const held = newest(6).map(s => s.id);
    for (const [width, theme] of [[1440, 'light'], [2000, 'light'], [2560, 'dark'], [1024, 'light'], [375, 'light']]) {
      const name = `fresh6-${width}-${theme}`;
      const { page, ctx, state } = await open(width, theme, { held, height: width < 768 ? 812 : 1000 });
      await page.evaluate(() => window.scrollTo(0, 2200));
      await arrive(page, state);
      const pill = await page.$eval('#fresh-text', el => el.textContent);
      await page.$eval('#fresh-go', b => b.click());
      await wait(450);                      // mid-glow
      const tile = await page.$('#fresh-row');
      await tile.screenshot({ path: path.join(out, `${name}-glow.png`) });
      await wait(1800);
      const m = await freshRows(page);
      await tile.screenshot({ path: path.join(out, `${name}.png`) });
      const pages = [m];
      // A pager, when there is one: walk it to the end and back, so every pinned row is seen once.
      for (let i = 1; i < 4; i++) {
        const next = await page.$('#fresh-row .fresh-pager:not([hidden]) [data-fresh-page="1"]:not([aria-disabled="true"])');
        if (!next) break;
        await next.click(); await wait(400);
        pages.push(await freshRows(page));
        await tile.screenshot({ path: path.join(out, `${name}-page${i + 1}.png`) });
      }
      const seen = new Set();
      pages.forEach((p, i) => p.rows.forEach((row, j) => { if (row.pinned && row.state === 'whole') seen.add(j); }));
      const pinnedN = m.rows.filter(r => r.pinned).length;
      const cut = pages.flatMap(p => p.rows).filter(r => r.state === 'cut').length;
      summary.push({ name, pill, rows: m.rows.length, pinned: pinnedN, wholePinnedSeen: seen.size, cut, scrolls: m.scrolls,
        pages: pages.length, tileH: m.tileH, ctrls: JSON.stringify(m.ctrls), states: m.rows.map(r => r.state[0]).join('') });
      // The tile holds at most four rows (feed.js, FRESH_TILE_ROWS); the batch's other two stay in the river.
      if (pinnedN !== 4) problems.push(`${name}: ${pinnedN} pinned rows, expected 4 (pill "${pill}")`);
      if (cut) problems.push(`${name}: ${cut} row(s) cut by the tile's edge`);
      if (seen.size < pinnedN) problems.push(`${name}: only ${seen.size} of ${pinnedN} new rows can be seen whole`);
      for (const [w, h, label] of m.ctrls) if (w < 44 || h < 44) problems.push(`${name}: control "${label}" ${w}x${h}`);
      if (m.overflow) problems.push(`${name}: page scrolls sideways`);
      await ctx.close();
    }
  }

  if (only.includes('ext')) {
    const id = await browser.installExtension(path.join(root, 'extension'));
    const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
    const worker = await sw.worker();
    const sample = JSON.parse(await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8'));
    for (const [width, theme] of [[1440, 'light'], [2000, 'light'], [1440, 'dark'], [375, 'light']]) {
      const name = `ext-${width}-${theme}`;
      const page = await browser.newPage();
      const cdp = await page.createCDPSession();
      await cdp.send('Network.enable');
      await cdp.send('Network.clearBrowserCache');
      const reqs = [];
      cdp.on('Network.requestWillBeSent', e => { if (/\/nen\/\d{4}-\d{2}-\d{2}\.(avif|webp)/.test(e.request.url)) reqs.push({ id: e.requestId, url: e.request.url, type: e.type }); });
      const cached = new Set();
      cdp.on('Network.requestServedFromCache', e => cached.add(e.requestId));
      cdp.on('Network.responseReceived', e => { if (e.response.fromDiskCache || e.response.fromServiceWorker) cached.add(e.requestId); });
      await page.setViewport({ width, height: width < 768 ? 812 : 1000, deviceScaleFactor: 1, isMobile: width < 768 });
      await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), sample);
      await page.goto(`chrome-extension://${id}/newtab.html`, { waitUntil: 'domcontentloaded' });
      await page.evaluate(async t => { localStorage.setItem('air2:theme', JSON.stringify(t)); localStorage.removeItem('air2:nen'); await caches.delete('halcyon-nen'); }, theme);
      reqs.length = 0; cached.clear();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready') || innerWidth < 768, { timeout: 20000 }).catch(() => {});
      await wait(2500);                     // the copy kept for offline use is written after the picture shows
      const kept = await page.evaluate(async () => (await (await caches.open('halcyon-nen')).keys()).map(r => r.url));
      const network = reqs.filter(r => !cached.has(r.id));
      await page.screenshot({ path: path.join(out, `${name}-requests-${network.length}.png`) });
      summary.push({ name, requests: reqs.length, network: network.length, types: reqs.map(r => r.type).join('+'), url: reqs[0]?.url ?? '', kept: kept.join(' ') });
      if (width >= 768 && network.length !== 1) problems.push(`${name}: the picture was requested ${network.length} times over the network`);
      if (width < 768 && reqs.length) problems.push(`${name}: a phone-width tab requested the picture`);
      await page.close();
    }
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
console.table(summary);
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ snapshot: full.generated_at, summary, problems, nenServed: nenLog }, null, 2));
if (problems.length) { console.log('PROBLEMS\n' + problems.join('\n')); process.exitCode = 1; }
else console.log('No problems measured.');

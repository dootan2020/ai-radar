// The front page's surfaces and pictures in Chrome against this worktree, with the live snapshot (data, pictures, the
// day's background and the drawn covers from the live site): the panel and card fills, the order control's track and
// chosen side, every card picture's fit (no band, no blurred copy; a drawn cover cropped inside its safe area or shown
// whole on its own colour), and the "Sắp diễn ra" card. Screenshots: the first two bands at 1440 light and dark, the
// order control in both states, the events card with the live event and with two more staged beside it (marked
// "(thử)"), and a strip of picture cards at 1440 and 375.
// node tests/capture-be-mat.mjs --out bento-anh/cuon        Nothing under site/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = path.resolve(root, arg('--out', 'bento-anh/cuon'));
await fs.mkdir(out, { recursive: true });
const LIVE = 'https://radar-ai-vn.pages.dev/';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const fixture = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'));
const cache = new Map();
async function live(p) {
  if (cache.has(p)) return cache.get(p);
  let got = null;
  try { const r = await fetch(LIVE + p.slice(1), { signal: AbortSignal.timeout(20000) }); if (r.ok) got = { type: r.headers.get('content-type'), body: Buffer.from(await r.arrayBuffer()) }; } catch {}
  cache.set(p, got);
  return got;
}
/* Two events staged after the live one, for the three-event layout only; their names say so. */
function withThree(body) {
  const d = JSON.parse(body.toString('utf8'));
  const first = (d.events || [])[0];
  if (!first) return body;
  const shift = (s, n) => { const t = new Date(`${s}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };
  const staged = [10, 24].map((n, i) => ({ ...first, id: `${first.id}-thu-${i}`, url: `${first.url}#thu-${i}`,
    title: `(thử) Sự kiện thứ ${i + 2} để xem bố cục`, start_date: shift(first.start_date, n), end_date: shift(first.end_date || first.start_date, n) }));
  return Buffer.from(JSON.stringify({ ...d, events: [...d.events, ...staged] }));
}
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  let p = decodeURIComponent(u.pathname);
  const three = p.startsWith('/ba/');
  if (three) p = p.slice(3);
  try {
    if (/^\/(data|nen|assets\/cover)\//.test(p)) {
      const got = await live(p);
      let body = got?.body, type = got?.type;
      if (!body && /^\/data\/radar(-window)?\.json$/.test(p)) { body = fixture; type = TYPES['.json']; }
      if (!body) { res.writeHead(404); return res.end(); }
      if (three && /^\/data\/radar(-window)?\.json$/.test(p)) body = withThree(body);
      res.writeHead(200, { 'content-type': type }); return res.end(body);
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
  const bg = el => el ? getComputedStyle(el).backgroundColor : null;
  const sw = document.querySelector('#band-news .band-head .sort-switch');
  const pill = sw && sw.querySelector('.tab-pill');
  const pics = [...document.querySelectorAll('#feed-grid :is(.nc-photo, .slide-media, .thumb, .repo-img, .model-img) img')]
    .filter(i => !i.classList.contains('av-img') && i.getBoundingClientRect().width > 0);
  const slotOf = i => i.parentElement;
  const covers = pics.filter(i => i.classList.contains('is-cover')).map(i => {
    const s = slotOf(i).getBoundingClientRect();
    return { ratio: +(s.width / s.height).toFixed(2), file: i.naturalWidth ? +(i.naturalWidth / i.naturalHeight).toFixed(2) : 0,
      fit: getComputedStyle(i).objectFit, whole: i.classList.contains('is-whole'), edge: slotOf(i).style.getPropertyValue('--cover-edge'), slotBg: bg(slotOf(i)) };
  });
  return {
    panel: bg(document.querySelector('#top')), card: bg(document.querySelector('#feed-grid .msn-card.nc')),
    cardShadow: getComputedStyle(document.querySelector('#feed-grid .msn-card.nc')).boxShadow,
    track: bg(sw), pill: pill ? { bg: bg(pill), shadow: getComputedStyle(pill).boxShadow, w: pill.getBoundingClientRect().width,
      opacity: getComputedStyle(pill).opacity } : null,
    pressed: [...document.querySelectorAll('#sort-switch .sort-btn[aria-pressed="true"]')].map(b => b.dataset.sort),
    pictures: pics.length, contain: pics.filter(i => getComputedStyle(i).objectFit === 'contain' && !i.classList.contains('is-whole')).length,
    backdrops: document.querySelectorAll('#feed-grid .media-backdrop').length, covers,
    events: { rows: document.querySelectorAll('#su-kien .ev-more li').length, fill: getComputedStyle(document.querySelector('#su-kien') || document.body).backgroundImage.slice(0, 60) },
    sideways: document.scrollingElement.scrollWidth > innerWidth,
  };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'be-mat-'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, pipe: true, userDataDir: profile, args: ['--disable-gpu', '--hide-scrollbars'] });
const report = {};
async function open(width, theme, base = url, height = 1300) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForFunction(() => document.querySelector('#band-more') && document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 60000 });
  await page.evaluate(async () => {
    document.documentElement.style.scrollBehavior = 'auto';
    for (let y = 0; y < document.body.scrollHeight; y += 700) { scrollTo(0, y); await new Promise(r => setTimeout(r, 100)); }
    scrollTo(0, 0);
  });
  await wait(2500);
  return { page, ctx };
}
const clipOf = (page, sels) => page.evaluate(sels => {
  const rs = sels.map(s => document.querySelector(s)?.getBoundingClientRect()).filter(Boolean);
  const x = Math.min(...rs.map(r => r.left)), y = Math.min(...rs.map(r => r.top)) + scrollY;
  return { x: Math.max(0, x - 8), y: Math.max(0, y - 8), width: Math.max(...rs.map(r => r.right)) - x + 16, height: Math.max(...rs.map(r => r.bottom)) + scrollY - y + 16 };
}, sels);

try {
  for (const theme of ['light', 'dark']) {
    const { page, ctx } = await open(1440, theme);
    report[`1440-${theme}`] = await page.evaluate(MEASURE);
    await page.screenshot({ path: path.join(out, `be-mat-1440-${theme}.png`), clip: await clipOf(page, ['.msn-head', '#band-today', '#band-focus']), captureBeyondViewport: true });
    if (theme === 'light') {
      const head = await page.$('#band-news .band-head');
      await head.screenshot({ path: path.join(out, 'sap-xep-dang-doc.png') });
      await page.click('#sort-switch .sort-btn[data-sort="new"]');
      await wait(900);
      report['1440-light-moi-nhat'] = await page.evaluate(MEASURE);
      await head.screenshot({ path: path.join(out, 'sap-xep-moi-nhat.png') });
      await page.click('#sort-switch .sort-btn[data-sort="worth"]');
      await wait(900);
      const ev = await page.$('#su-kien');
      if (ev) await ev.screenshot({ path: path.join(out, 'su-kien-1.png') });
      await page.screenshot({ path: path.join(out, 'the-anh-1440.png'), clip: await clipOf(page, ['#band-news']), captureBeyondViewport: true });
    }
    await ctx.close();
  }
  {
    const { page, ctx } = await open(1440, 'light', `${url}ba/`);
    report['1440-ba-su-kien'] = await page.evaluate(MEASURE);
    const ev = await page.$('#su-kien');
    if (ev) await ev.screenshot({ path: path.join(out, 'su-kien-3.png') });
    await ctx.close();
  }
  for (const width of [1024, 768]) {
    const { page, ctx } = await open(width, 'light');
    report[`${width}-light`] = await page.evaluate(MEASURE);
    await ctx.close();
  }
  {
    const { page, ctx } = await open(375, 'light', url, 900);
    report['375-light'] = await page.evaluate(MEASURE);
    await page.screenshot({ path: path.join(out, 'the-anh-375.png'), clip: await clipOf(page, ['#band-news']), captureBeyondViewport: true });
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
await fs.writeFile(path.join(out, 'be-mat.json'), JSON.stringify(report, null, 1));
for (const [k, m] of Object.entries(report)) {
  console.log(`${k}: panel=${m.panel} card=${m.card} track=${m.track} pill=${m.pill?.bg}/${m.pill?.opacity} pressed=${m.pressed} pictures=${m.pictures} contain=${m.contain} backdrops=${m.backdrops} covers=${m.covers.length} whole=${m.covers.filter(c => c.whole).length} eventsRows=${m.events.rows} sideways=${m.sideways}`);
  for (const c of m.covers.filter(c => c.whole || c.ratio < 1.45 || c.ratio > 2.12)) console.log(`   cover slot ${c.ratio} file ${c.file} fit ${c.fit} whole ${c.whole} edge ${c.edge}`);
}

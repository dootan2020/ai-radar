// New stories load by themselves (captain, 13/11 20:1x: "tin mới tự tải, animate mượt mà, user không cần click"):
// the front page rendered in headless Chrome from site/, then a poll that brings a newer snapshot (the fixture plus two
// new stories), at 375 and 1440 px.
//   node tests/capture-tu-tai-tin.mjs [--out <dir>] [--only <width>]
// Same server as tests/capture-mobile-the-tin.mjs: site/ from disk, the window file is
// tests/fixtures/radar-window-sample.json, and the complete snapshot (data/radar.json) is that fixture until the script
// switches it to the newer one. The poll is the page's own (pollSnapshot), started by a visibilitychange event.
// Per width:
//   top     the reader at the top: the arrivals lead "Vừa đăng", no pill, no story twice, the live region, scrollY and
//           the tile's place before and after, and the frames while the page moves (rAF deltas, longest frame).
//   middle  the reader 1500 px down: after the poll nothing changes (scrollY, the element in view, the tile's rows);
//           back at the top the snapshot is applied.
//   modal   a story open at the top: the snapshot waits until it closes.
//   reduced prefers-reduced-motion: applied with no animation at all.
// One JSON line on stdout.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const only = arg('--only', '');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const siteDir = path.join(root, 'site');
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });

// The newer snapshot: ten minutes later, two text stories published since the fixture was made.
const fixture = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8');
const older = JSON.parse(fixture);
const newer = JSON.parse(fixture);
const gen = Date.parse(older.generated_at);
newer.generated_at = new Date(gen + 10 * 60e3).toISOString().replace('.000Z', 'Z');
const model = older.stories.find(st => st.id === 'd3eb78da0ef7a68766a5') || older.stories[0];
const ARRIVALS = [['tu-tai-tin-1', 4, 'Tin mới tự tải thứ nhất'], ['tu-tai-tin-2', 7, 'Tin mới tự tải thứ hai']];
for (const [id, minutes, headline] of ARRIVALS) {
  const at = new Date(gen + minutes * 60e3).toISOString().replace('.000Z', 'Z');
  const url = `https://example.com/${id}`;
  newer.stories.unshift({ ...model, id, url, published_at: at, title: headline, headline, headline_vi: headline, title_vi: headline,
    summary: headline, summary_vi: headline, hot_score: null, worth_score: 1, worth_parts: { freshness: 1 }, worth_why: '',
    image_screened: false, image: undefined, aliases: [],
    coverage: [{ ...model.coverage[0], id: `${id}-c`, url, title: headline, headline, headline_vi: headline, title_vi: headline, published_at: at }] });
}
const NEWER = JSON.stringify(newer);
const ARRIVAL_IDS = ARRIVALS.map(a => a[0]);

let complete = fixture, completeAsks = 0;
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p === '/data/radar-window.json') { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(fixture); }
    if (p === '/data/radar.json') { completeAsks++; res.writeHead(200, { 'content-type': TYPES['.json'], 'cache-control': 'no-store' }); return res.end(complete); }
    if (p.startsWith('/data/') || p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    const file = path.join(siteDir, p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(siteDir)) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const stand = await fs.readFile(path.join(root, 'site/og-image.png'));

// Watches the page from its first script: when #feed-grid is drawn again (the snapshot taken in), what the tile holds,
// and every frame's time.
const EARLY = () => {
  window.__frames = [];
  const tick = t => { window.__frames.push(t); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  window.__long = [];
  try { new PerformanceObserver(list => { for (const e of list.getEntries()) window.__long.push({ at: e.startTime, ms: Math.round(e.duration) }); }).observe({ type: 'longtask' }); } catch {}
  window.__shifts = [];
  try { new PerformanceObserver(list => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__shifts.push({ at: e.startTime, value: e.value }); }).observe({ type: 'layout-shift', buffered: true }); } catch {}
  window.__applied = null;
  // The pictures on screen, and how many of them are not drawn yet (no address, not decoded, or still soft): a redraw
  // must not blank the pictures the reader is looking at.
  window.__pictures = () => {
    const on = [...document.querySelectorAll('#feed-grid img.media-img')].filter(img => {
      const r = img.getBoundingClientRect();
      return r.width && r.bottom > 0 && r.top < innerHeight && !img.closest('.slide:not(.is-active)');
    });
    const blank = on.filter(img => !img.complete || !img.naturalWidth || !img.classList.contains('is-loaded'));
    return { shown: on.length, blank: blank.length,
      which: blank.map(img => `${img.closest('[data-sid]')?.dataset.sid || img.closest('[id]')?.id}:${img.complete ? 'complete' : 'loading'}${img.classList.contains('is-loaded') ? '' : ':soft'}${img.getAttribute('src') ? '' : ':no-src'}`) };
  };
  const watch = () => {
    const grid = document.querySelector('#feed-grid');
    if (!grid) return setTimeout(watch, 50);
    new MutationObserver(() => {
      if (!window.__armed || window.__applied) return;
      const rows = [...document.querySelectorAll('#fresh-list > li')].map(li => li.dataset.sid);
      if (!rows.some(id => window.__arrivals.includes(id))) return;
      const scripted = document.getAnimations().filter(a => a.constructor.name === 'Animation');
      window.__applied = {
        at: performance.now(), scrollY, rows,
        tileTop: Math.round(document.querySelector('#fresh-row')?.getBoundingClientRect().top ?? NaN),
        moving: scripted.length,
        glow: document.getAnimations().filter(a => a.animationName === 'fresh-glow').length,
        arriving: document.querySelectorAll('#fresh-list > li.is-arriving').length,
        pictures: window.__pictures(),
      };
    }).observe(grid, { childList: true });
  };
  watch();
};

// The state of the page a check compares before and after.
const STATE = () => {
  const ids = [...document.querySelectorAll('#feed-grid [data-sid]')].filter(el => el.getClientRects().length).map(el => el.dataset.sid);
  const twice = ids.filter((id, i) => ids.indexOf(id) !== i);
  const probe = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
  const held = probe && probe.closest('[data-sid], .band-cells > *');
  return {
    scrollY, rows: [...document.querySelectorAll('#fresh-list > li')].map(li => li.dataset.sid),
    tileTop: Math.round(document.querySelector('#fresh-row')?.getBoundingClientRect().top ?? NaN),
    pill: !!document.querySelector('#fresh, #fresh-go, .fresh-btn'),
    twice: [...new Set(twice)], live: document.querySelector('#fresh-announcement')?.textContent || '',
    held: held ? { key: held.dataset.sid || held.id || held.className, top: Math.round(held.getBoundingClientRect().top) } : null,
    generated: document.querySelector('#feed-grid')?.dataset.generated || '',
    pictures: window.__pictures(),
  };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'tu-tai-tin-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { arrivals: ARRIVAL_IDS, runs: {}, errors: [] };

async function open(ctx, width, motion) {
  complete = fixture;
  const page = await ctx.newPage();
  const phone = width < 768;
  await page.setViewport({ width, height: phone ? 812 : 900, deviceScaleFactor: 1, isMobile: phone, hasTouch: phone });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: motion }, { name: 'prefers-color-scheme', value: 'light' }]);
  await page.evaluateOnNewDocument(EARLY);
  await page.evaluateOnNewDocument(ids => { window.__arrivals = ids; window.__armed = false; }, ARRIVAL_IDS);
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    const picture = req.resourceType() === 'image' && u.startsWith('https://');
    if (picture) return req.respond({ status: 200, contentType: 'image/png', body: stand });
    return u.startsWith(site) || u.startsWith('data:') ? req.continue() : req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${width}: ${e.message}`));
  await page.goto(site, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#fresh-list > li'), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  // The reader acts once, so the page fetches the complete snapshot (still the fixture) before the newer one exists.
  const asked = completeAsks;
  await page.evaluate(() => dispatchEvent(new Event('focusin')));
  for (let i = 0; i < 40 && completeAsks === asked; i++) await wait(100);
  await wait(800);
  return page;
}
// The page's own poll: it runs when the tab becomes visible.
async function poll(page) {
  complete = NEWER;
  await page.evaluate(() => { window.__armed = true; document.dispatchEvent(new Event('visibilitychange')); });
}
// The frames from just before the redraw to the end of the motion: their gaps (16.7 ms at 60 Hz), the longest one, and
// any long task (over 50 ms of script) around the redraw.
const frameStats = async (page, from, span) => {
  const { frames, long, shifts } = await page.evaluate(() => ({ frames: window.__frames, long: window.__long, shifts: window.__shifts }));
  const inside = frames.filter(t => t >= from - 40 && t <= from + span);
  const gaps = inside.slice(1).map((t, i) => Math.round((t - inside[i]) * 10) / 10);
  return { frames: inside.length, longest: gaps.length ? Math.max(...gaps) : null,
    over20: gaps.filter(g => g > 20).length, over50: gaps.filter(g => g > 50).length, gaps,
    longTasks: long.filter(l => l.at >= from - 500 && l.at <= from + span),
    // Layout shift from the redraw on (a slide is a transform, so it does not count; content jumping does).
    shift: Math.round(shifts.filter(s => s.at >= from - 100).reduce((n, s) => n + s.value, 0) * 1000) / 1000 };
};
const focusName = () => { const a = document.activeElement; return a ? `${a.tagName.toLowerCase()}#${a.id}.${String(a.className).split(' ')[0]}[${a.closest('[data-sid]')?.dataset.sid || ''}]` : null; };

try {
  for (const width of [375, 1440].filter(w => !only || String(w) === only)) {
    const run = result.runs[width] = {};
    // (a) At the top.
    {
      const ctx = await browser.createBrowserContext();
      const page = await open(ctx, width, 'no-preference');
      const before = await page.evaluate(STATE);
      await poll(page);
      await page.waitForFunction(() => window.__applied, { timeout: 15000 });
      await wait(900);
      const applied = await page.evaluate(() => window.__applied);
      const motion = await frameStats(page, applied.at, 700);
      if (out) await page.screenshot({ path: path.join(out, `${width}-dau-trang-sau.png`) });
      await wait(1600);
      const after = await page.evaluate(STATE);
      run.top = { before, applied, after, motion };
      await ctx.close();
    }
    // (b) 1500 px down, then back to the top.
    {
      const ctx = await browser.createBrowserContext();
      const page = await open(ctx, width, 'no-preference');
      await page.evaluate(() => scrollTo({ top: 1500, behavior: 'instant' }));
      await wait(1200);
      const before = await page.evaluate(STATE);
      await poll(page);
      await wait(3500);   // the poll's request, then three of the page's one-second looks
      const held = await page.evaluate(STATE);
      const appliedWhileDown = await page.evaluate(() => window.__applied);
      if (out) await page.screenshot({ path: path.join(out, `${width}-giua-trang-giu.png`) });
      await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
      await page.waitForFunction(() => window.__applied, { timeout: 15000 }).catch(() => {});
      await wait(900);
      const applied = await page.evaluate(() => window.__applied);
      const motion = applied ? await frameStats(page, applied.at, 700) : null;
      await wait(1600);
      const back = await page.evaluate(STATE);
      if (out) await page.screenshot({ path: path.join(out, `${width}-ve-dau-trang.png`) });
      run.middle = { before, held, appliedWhileDown, applied, back, motion };
      await ctx.close();
    }
    // (c) A story open at the top, from the keyboard: the snapshot waits while it is open, and is taken in after Escape
    // closes it, with keyboard focus kept on the story's own link.
    {
      const ctx = await browser.createBrowserContext();
      const page = await open(ctx, width, 'no-preference');
      await page.focus('#fresh-list > li a');
      await page.keyboard.press('Enter');
      await page.waitForFunction(() => document.querySelector('dialog[open]'), { timeout: 10000 });
      await wait(600);
      await poll(page);
      await wait(3000);
      const whileOpen = await page.evaluate(() => ({ applied: window.__applied, open: !!document.querySelector('dialog[open]') }));
      await page.keyboard.press('Escape');
      await wait(150);
      const focusBefore = await page.evaluate(focusName);
      await page.waitForFunction(() => window.__applied, { timeout: 15000 }).catch(() => {});
      await wait(400);
      const afterClose = await page.evaluate(() => ({ applied: window.__applied, open: !!document.querySelector('dialog[open]') }));
      const focusAfter = await page.evaluate(focusName);
      run.modal = { whileOpen, afterClose, focusBefore, focusAfter };
      await ctx.close();
    }
    // (e) With --out: one still 120 ms into the motion (every animation held there), to see the rows mid-slide.
    if (out) {
      const ctx = await browser.createBrowserContext();
      const page = await open(ctx, width, 'no-preference');
      await page.evaluate(() => {
        const grid = document.querySelector('#feed-grid');
        new MutationObserver(() => requestAnimationFrame(() => document.getAnimations().forEach(a => { a.pause(); a.currentTime = 120; })))
          .observe(grid, { childList: true });
      });
      await poll(page);
      await page.waitForFunction(() => window.__applied, { timeout: 15000 }).catch(() => {});
      await wait(300);
      await page.screenshot({ path: path.join(out, `${width}-giua-chuyen-dong.png`) });
      await ctx.close();
    }
    // (d) Reduced motion: applied, nothing animates.
    {
      const ctx = await browser.createBrowserContext();
      const page = await open(ctx, width, 'reduce');
      const before = await page.evaluate(STATE);
      await poll(page);
      await page.waitForFunction(() => window.__applied, { timeout: 15000 }).catch(() => {});
      const applied = await page.evaluate(() => window.__applied);
      await wait(400);
      const after = await page.evaluate(STATE);
      run.reduced = { before, applied, after };
      await ctx.close();
    }
  }
} catch (e) {
  result.errors.push(String(e && e.stack || e));
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(result) + '\n');

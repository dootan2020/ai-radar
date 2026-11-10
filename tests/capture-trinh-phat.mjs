// The stream player (site/trinh-phat.js), driven in headless Chrome from site/ with
// tests/fixtures/radar-window-sample.json and one stream in D.live. A reader opens the page, sees "Trực tiếp · OpenAI"
// on the "Sắp diễn ra" card, taps it, and closes the player with Escape; then the same from the "Sắp diễn ra" view
// (#sap-toi), closed with the close button.
//   node tests/capture-trinh-phat.mjs                   offline: every request off the test server is refused and
//                                                       recorded; one JSON line of measurements (tests/test_trinh_phat.py)
//   node tests/capture-trinh-phat.mjs --walk --out DIR  online: YouTube's hosts answer, so the embed really plays;
//                                                       pictures at 375 and 1440, light and dark, and the extension
//   node tests/capture-trinh-phat.mjs --cases          offline: history against the dialog in every order, and where
//                                                       focus lands when the grid is redrawn under the player
//   --id VIDEO_ID (the stream's id)   --refused VIDEO_ID (also open one whose embed is refused)   --widths 1440,375
// Nothing under site/ or data/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const walk = process.argv.includes('--walk');
const out = arg('--out', '');
const VIDEO = arg('--id', 'Fls_onRviPM');
const refused = arg('--refused', '');
const closeAll = arg('--close', '');   // escape | button | back: close every walk this way (the back gesture of a phone)
const widths = arg('--widths', '1440,375').split(',').filter(Boolean).map(Number);
const themes = walk ? ['light', 'dark'] : ['light'];
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });

// The page's clock, as in tests/capture-su-kien.mjs: the fixture's news is today's, NeurIPS Sydney 25 days away.
const NOW = Date.parse('2026-11-10T11:21:18Z');
const raw = await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8');
const shift = NOW - Date.parse(JSON.parse(raw).generated_at);
const base = JSON.parse(raw.replace(/"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))"/g,
  (_, t) => JSON.stringify(new Date(Date.parse(t) + shift).toISOString())));
const curated = JSON.parse(await fs.readFile(path.join(root, 'data/events.json'), 'utf8'));
const three = ['neurips-sydney-2026', 'neurips-atlanta-2026', 'neurips-paris-2026'].map(id => curated.find(e => e.id === id)).filter(Boolean);
const streamOf = id => ({ status: 'live', video_id: id, title: 'OpenAI DevDay 2026 Keynote (FULL)', channel: 'OpenAI',
  url: `https://www.youtube.com/watch?v=${id}`, thumbnail: '', time_text: '' });
let current = { ...base, events: three, live: [streamOf(VIDEO)] };

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (/^\/data\/radar(-window)?\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(current)); }
    if (p.startsWith('/data/') || p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    const file = path.join(root, 'site', p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
// The hosts a YouTube embed uses; in a walk only these answer (no analytics, no live counters).
const YT = /^https:\/\/([\w-]+\.)*(youtube-nocookie\.com|youtube\.com|ytimg\.com|googlevideo\.com|ggpht\.com|gstatic\.com|google\.com|googleapis\.com)\//;
const ytHost = u => { try { return /(^|\.)(youtube-nocookie\.com|youtube\.com|ytimg\.com|googlevideo\.com)$/.test(new URL(u).hostname); } catch { return false; } };

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'trinh-phat-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, enableExtensions: walk, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars', '--autoplay-policy=no-user-gesture-required'], timeout: 20000 });
const result = { now: new Date(NOW).toISOString(), walk, video: VIDEO, chrome: browser.process()?.pid ?? null, runs: {}, errors: [] };

async function open(page, url, width, theme, log) {
  await page.setViewport({ width, height: width < 768 ? 812 : 900, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.evaluateOnNewDocument((now, t) => {
    if (!/^(http:\/\/127\.0\.0\.1|chrome-extension:)/.test(location.href)) return;   // never YouTube's own frames
    const Real = Date, off = now - Real.now();
    // eslint-disable-next-line no-global-assign
    Date = class extends Real { constructor(...a) { if (a.length) super(...a); else super(Real.now() + off); } static now() { return Real.now() + off; } };
    try { localStorage.setItem('air2:theme', JSON.stringify(t)); } catch {}
  }, NOW, theme);
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    if (u.startsWith(site) || u.startsWith('chrome-extension://') || u.startsWith('data:')) return req.continue();
    const ok = walk && YT.test(u);
    log.push({ at: log.phase, url: u.slice(0, 160), ok });
    return ok ? req.continue() : req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${url} ${width}: ${e.message}`));
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true'
    && (document.querySelector('#su-kien') || document.querySelector('#feed-grid .bt')), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  await wait(800);
}

const STATE = () => {
  const d = document.getElementById('player-dialog');
  const f = d && d.querySelector('iframe');
  const a = document.activeElement;
  const yt = d && d.querySelector('.player-yt');
  const r = el => el.getBoundingClientRect();
  const shown = el => { const b = r(el); return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const inDialog = d && d.open ? [...d.querySelectorAll('*')].filter(el => shown(el)) : [];
  return {
    open: !!(d && d.open), iframes: document.querySelectorAll('iframe').length,
    src: f ? f.src : null, allow: f ? f.allow : null, referrer: f ? f.referrerPolicy : null,
    yt: yt ? { text: yt.textContent.trim(), href: yt.href, w: Math.round(r(yt).width), h: Math.round(r(yt).height) } : null,
    focus: a ? (a.dataset.opener || (a.hasAttribute('data-player-close') ? 'close' : a.tagName.toLowerCase() + '.' + a.className)) : null,
    title: d && d.querySelector('.player-title') ? d.querySelector('.player-title').textContent : null,
    kicker: d && d.querySelector('.player-k') ? d.querySelector('.player-k').textContent : null,
    frame: f ? (b => ({ w: Math.round(b.width), h: Math.round(b.height), top: Math.round(b.top) }))(r(f)) : null,
    panel: d && d.open ? (b => ({ x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }))(r(d.querySelector('.player-panel'))) : null,
    minText: inDialog.length ? Math.min(...inDialog.filter(el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
      .map(el => parseFloat(getComputedStyle(el).fontSize))) : null,
    targets: inDialog.filter(el => el.matches('a, button')).map(el => ({ cls: String(el.className).split(' ')[0], w: Math.round(r(el).width), h: Math.round(r(el).height) })),
    sideways: document.scrollingElement.scrollWidth > innerWidth,
    thumbs: [...document.querySelectorAll('img')].filter(i => /ytimg|youtube/.test(i.currentSrc || i.src)).length,
  };
};

// What the embed shows: playing (a video element with time moving), or YouTube's error text.
async function embedState(page) {
  const fr = page.frames().find(f => /youtube-nocookie\.com\/embed\//.test(f.url()));
  if (!fr) return { frame: false };
  try {
    return await fr.evaluate(async () => {
      const v = document.querySelector('video');
      const t0 = v ? v.currentTime : null;
      await new Promise(r => setTimeout(r, 1500));
      const err = document.querySelector('.ytp-error, .ytp-error-content-wrap-reason');
      return { frame: true, video: !!v, t0, t1: v ? v.currentTime : null, paused: v ? v.paused : null,
        error: err && err.offsetParent !== null ? err.textContent.replace(/\s+/g, ' ').trim().slice(0, 200) : null };
    });
  } catch (e) { return { frame: true, unreadable: String(e.message).slice(0, 120) }; }
}

async function snap(page, name) { if (out) await page.screenshot({ path: path.join(out, `${name}.png`) }); }

// One reader's path through one surface: before the tap, the tap, a few seconds of play, the close.
async function play(page, key, selector, closeWith, log) {
  const opener = await page.waitForSelector(selector, { timeout: 15000 });
  await opener.evaluate(el => { el.dataset.opener = 'opener'; el.scrollIntoView({ block: 'center' }); });
  await wait(300);
  const run = { has: await opener.evaluate(el => ({ play: el.dataset.play || null, href: el.href, text: el.textContent.replace(/\s+/g, ' ').trim().slice(0, 80) })) };
  run.before = await page.evaluate(STATE);
  run.beforeRequests = log.filter(x => ytHost(x.url)).map(x => x.url);
  await snap(page, `${key}-1-truoc`);
  log.phase = 'after';
  await opener.click();
  await page.waitForFunction(() => document.getElementById('player-dialog')?.open, { timeout: 5000 }).catch(() => {});
  run.opened = await page.evaluate(STATE);
  if (walk) {
    await wait(5000);
    run.embed = await embedState(page);
    await snap(page, `${key}-2-dang-phat`);
  }
  closeWith = closeAll || closeWith;
  if (closeWith === 'back') await page.evaluate(() => history.back());
  else if (closeWith === 'escape') await page.keyboard.press('Escape');
  else await page.click('#player-dialog [data-player-close]');
  await wait(400);
  run.closed = await page.evaluate(STATE);
  await snap(page, `${key}-3-sau-khi-dong`);
  run.afterRequests = log.filter(x => x.at === 'after' && ytHost(x.url)).map(x => x.url);
  await opener.evaluate(el => { delete el.dataset.opener; });
  log.phase = 'before';
  return run;
}

// History and the dialog agree in every order: open, close (Escape, the button, the backdrop or Back), Forward (the
// player comes back on its own entry), Back, open again, Back. window.__page marks the document: a Back that left
// the page would lose it.
const SNAP = () => {
  const d = document.getElementById('player-dialog');
  return { open: !!(d && d.open), iframes: document.querySelectorAll('iframe').length,
    src: (d && d.querySelector('iframe')?.src) || null, player: !!(history.state && history.state.player),
    len: history.length, same: window.__page === 1, url: location.href };
};
async function historyCase(page, selector, how) {
  const steps = [];
  const step = async name => { await wait(450); steps.push({ step: name, ...(await page.evaluate(SNAP)) }); };
  const tap = async () => {
    const el = await page.waitForSelector(selector, { timeout: 15000 });
    await el.evaluate(x => x.scrollIntoView({ block: 'center' }));
    await el.click();
  };
  await page.evaluate(() => { window.__page = 1; });
  await step('start');
  await tap(); await step('open');
  if (how === 'escape') await page.keyboard.press('Escape');
  else if (how === 'button') await page.click('#player-dialog [data-player-close]');
  else if (how === 'backdrop') await page.mouse.click(8, 8);
  else await page.evaluate(() => history.back());
  await step('close');
  await page.evaluate(() => history.forward()); await step('forward');
  if (walk) { await wait(4000); steps[steps.length - 1].embed = await embedState(page); }   // online: Forward really plays
  await page.evaluate(() => history.back()); await step('back');
  await tap(); await step('open-again');
  await page.evaluate(() => history.back()); await step('back-again');
  return steps;
}
// The control that opened the player is replaced while it plays (renderFeed sets the grid's innerHTML): closing puts
// focus on the same stream's new control, or on the page's main landmark when the stream is gone.
async function focusCase(page, selector, gone) {
  const el = await page.waitForSelector(selector, { timeout: 15000 });
  await el.evaluate(x => { x.__orig = true; x.scrollIntoView({ block: 'center' }); });
  await el.click();
  await wait(300);
  const swapped = await page.evaluate((sel, gone) => {
    const old = document.querySelector(sel), grid = document.getElementById('feed-grid');
    grid.innerHTML = grid.innerHTML;
    if (gone) document.querySelectorAll('[data-play]').forEach(x => x.remove());
    return { replaced: !!old && !old.isConnected };
  }, selector, gone);
  await page.keyboard.press('Escape');
  await wait(400);
  const focus = await page.evaluate(() => {
    const a = document.activeElement;
    return a ? { orig: !!a.__orig, play: a.dataset.play || null, cls: String(a.className).split(' ')[0], id: a.id || null,
      tag: a.tagName.toLowerCase(), connected: a.isConnected } : null;
  });
  return { ...swapped, focus, open: await page.evaluate(() => document.getElementById('player-dialog').open) };
}

try {
  if (process.argv.includes('--cases')) {
    result.history = {}; result.focus = {};
    for (const width of widths) {
      const hows = width >= 768 ? ['escape', 'button', 'backdrop', 'back'] : ['escape', 'button', 'back'];
      for (const how of hows) {
        const ctx = await browser.createBrowserContext(), page = await ctx.newPage(), log = Object.assign([], { phase: 'before' });
        await open(page, site, width, 'light', log);
        result.history[`${how}-${width}`] = await historyCase(page, '#su-kien .ev-stream', how);
        await ctx.close();
      }
      for (const [name, sel, gone] of [['the', '#su-kien .ev-stream', false], ['sap-toi', '#feed-grid .bt-live .bt-live-go', false], ['mat-luong', '#su-kien .ev-stream', true]]) {
        const ctx = await browser.createBrowserContext(), page = await ctx.newPage(), log = Object.assign([], { phase: 'before' });
        await open(page, site + (name === 'sap-toi' ? '#sap-toi' : ''), width, 'light', log);
        result.focus[`${name}-${width}`] = await focusCase(page, sel, gone);
        await ctx.close();
      }
    }
  } else {
    for (const width of widths) for (const theme of themes) {
      const tag = `${width}${theme === 'dark' ? '-toi' : ''}`;
      // The front page's card, closed with Escape.
      let ctx = await browser.createBrowserContext(), page = await ctx.newPage(), log = Object.assign([], { phase: 'before' });
      await open(page, site, width, theme, log);
      result.runs[`the-${tag}`] = await play(page, `the-${tag}`, '#su-kien .ev-stream', 'escape', log);
      await ctx.close();
      // The "Sắp diễn ra" view's picture, closed with the close button.
      ctx = await browser.createBrowserContext(); page = await ctx.newPage(); log = Object.assign([], { phase: 'before' });
      await open(page, site + '#sap-toi', width, theme, log);
      result.runs[`sap-toi-${tag}`] = await play(page, `sap-toi-${tag}`, '#feed-grid .bt-live .bt-live-go', 'button', log);
      await ctx.close();
    }
    if (refused) {
      current = { ...base, events: three, live: [{ ...streamOf(refused), title: 'Một mã video không tồn tại' }] };
      const ctx = await browser.createBrowserContext(), page = await ctx.newPage(), log = Object.assign([], { phase: 'before' });
      await open(page, site, 1440, 'light', log);
      result.runs['tu-choi-1440'] = await play(page, 'tu-choi-1440', '#su-kien .ev-stream', 'escape', log);
      await ctx.close();
      current = { ...base, events: three, live: [streamOf(VIDEO)] };
    }
    if (walk) {
      const id = await browser.installExtension(path.join(root, 'extension'));
      const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().startsWith(`chrome-extension://${id}/`), { timeout: 20000 });
      const worker = await sw.worker();
      await worker.evaluate(data => chrome.storage.local.set({ radarWindow: data, radarFetchedAt: new Date().toISOString() }), current);
      const page = await browser.newPage(), log = Object.assign([], { phase: 'before' });
      await open(page, `chrome-extension://${id}/newtab.html`, 1440, 'light', log);
      // The new tab keeps the stream as a link to YouTube (extension/sync-site.py turns the player off there).
      const a = await page.waitForSelector('#su-kien .ev-stream', { timeout: 15000 });
      await a.evaluate(el => el.scrollIntoView({ block: 'center' }));
      result.runs['tien-ich-1440'] = { has: await a.evaluate(el => ({ play: el.dataset.play || null, href: el.href, target: el.target,
        text: el.textContent.replace(/\s+/g, ' ').trim().slice(0, 80) })), before: await page.evaluate(STATE),
        beforeRequests: log.filter(x => ytHost(x.url)).map(x => x.url) };
      await snap(page, 'tien-ich-1440-1-truoc');
      await page.close();
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

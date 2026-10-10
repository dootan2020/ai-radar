// Render the events' countdown with Chrome against a server for this worktree: screenshots, a two-shot proof that the
// seconds tick without moving anything, one shared timer, a pause while the page is hidden, and the reduced-motion
// face (words to the minute, no seconds).
// node tests/capture-events-countdown.mjs --url http://127.0.0.1:8811 --out plans/reports/ke-su-kien/countdown [--strict]
// Scenarios swap the snapshot's events and live items inside the headless page only; no data file is touched.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
};
const url = arg('--url', 'http://127.0.0.1:8811');
const out = arg('--out', 'plans/reports/ke-su-kien/countdown');
const strict = process.argv.includes('--strict');
await fs.mkdir(out, { recursive: true });
for (const file of ['index.html', 'feed.css', 'feed.js']) {
  const r = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(r.status, 200, file);
  assert.equal(await r.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), `${file} served by ${url} is not this worktree's`);
}

// Dates in Vietnam time, the page's own calendar.
const vnDay = ms => new Date(ms + 7 * 36e5).toISOString().slice(0, 10);
const now = Date.now();
const exact = (id, title, inMs, hours, location) => ({ id, title, url: `https://example.com/${id}`, time_precision: 'exact',
  start_at: new Date(now + inMs).toISOString(), end_at: new Date(now + inMs + hours * 36e5).toISOString(),
  start_date: vnDay(now + inMs), end_date: vnDay(now + inMs + hours * 36e5), location, verified_at: vnDay(now), source_url: `https://example.com/${id}` });
const dated = (id, title, fromDay, toDay, location) => ({ id, title, url: `https://example.com/${id}`, time_precision: 'date', start_at: null, end_at: null,
  start_date: vnDay(now + fromDay * 864e5), end_date: vnDay(now + toDay * 864e5), location, verified_at: vnDay(now), source_url: `https://example.com/${id}` });
const MIX = [
  dated('cd-on', 'Hội nghị AI Đông Nam Á (đang diễn ra)', -1, 1, 'Singapore'),
  exact('cd-30m', 'Buổi ra mắt mô hình mới — phát trực tuyến', 30 * 6e4, 1, 'Trực tuyến'),
  exact('cd-5h', 'OpenAI DevDay Exchange — Bengaluru', 5 * 36e5, 8, 'Bengaluru, India'),
  dated('cd-3d', 'Google I/O Connect — Berlin', 3, 3, 'Berlin, Đức'),
  dated('cd-57d', 'NeurIPS 2026 — Sydney', 57, 63, 'Sydney, Australia'),
];
const stream = { status: 'live', video_id: 'capture-live', title: 'Live: building agents with the new Responses API, questions answered',
  url: 'https://www.youtube.com/watch?v=capture-live', channel: 'OpenAI', thumbnail: '', time_text: '' };
const SCENARIOS = {
  real: d => d,
  mix: d => ({ ...d, events: MIX, live: [] }),
  'mix-stream': d => ({ ...d, events: MIX, live: [stream] }),
  'mix-tab': d => ({ ...d, events: MIX, live: [] }),
};

const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true, args: ['--disable-gpu'],
  userDataDir: await fs.mkdtemp(path.join(path.resolve(out), 'chrome-profile-')), timeout: 15000,
});
console.log(`Chrome PID ${browser.process().pid}; server ${url}`);
const problems = [];
const summary = [];

async function open(sc, width, theme, motion) {
  const page = await browser.newPage();
  const touch = width < 1024;
  await page.setViewport({ width, height: 900, deviceScaleFactor: 1, hasTouch: touch, isMobile: width < 768 });
  if (touch) { const cdp = await page.createCDPSession(); await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 }); }
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: motion }]);
  await page.evaluateOnNewDocument(t => {
    localStorage.setItem('air2:theme', JSON.stringify(t));
    // Count the countdown's pending timers and every interval the page starts.
    const pending = new Set(); window.__cd = { pending, intervals: 0 };
    const st = window.setTimeout, ct = window.clearTimeout, si = window.setInterval;
    window.setTimeout = function (fn, ms, ...a) {
      const mine = /scheduleCountdown/.test(new Error().stack || '');
      const id = st.call(window, (...x) => { pending.delete(id); return typeof fn === 'function' ? fn(...x) : undefined; }, ms, ...a);
      if (mine) pending.add(id);
      return id;
    };
    window.clearTimeout = id => { pending.delete(id); return ct.call(window, id); };
    window.setInterval = function (...a) { if (/countdown/i.test(new Error().stack || '')) window.__cd.intervals++; return si.apply(window, a); };
  }, theme);
  await page.setRequestInterception(true);
  page.on('request', async req => {
    if (!req.url().includes('data/radar-ui.json')) return req.continue();
    const r = await fetch(req.url());
    req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(SCENARIOS[sc](await r.json())) });
  });
  const tab = sc.endsWith('-tab');
  await page.goto(tab ? `${url}/#sap-toi` : url, { waitUntil: 'domcontentloaded' });
  const sel = tab ? '#feed-grid .tile-live' : '#picks-grid .tile-live';
  await page.waitForSelector(sel, { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async s => { document.querySelector(s).scrollIntoView({ block: 'start' }); window.scrollBy(0, -16);
    await Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))); }, sel);
  await new Promise(r => setTimeout(r, 400));
  return { page, sel };
}
// Everything a tick could move: each card, each title, each date leaf, the calendar control.
const layout = (page, sel) => page.evaluate(s => {
  const tile = document.querySelector(s);
  const r = el => { const b = el.getBoundingClientRect(); return [Math.round(b.left * 10) / 10, Math.round(b.top * 10) / 10, Math.round(b.width * 10) / 10, Math.round(b.height * 10) / 10]; };
  return {
    boxes: [...tile.querySelectorAll('.events > li, .event-name, .date-badge, .calbtn, .event-when')].map(r),
    faces: [...tile.querySelectorAll('.cd-face')].map(f => f.textContent.trim()),
    sr: [...tile.querySelectorAll('.cd > .sr')].map(f => f.textContent.trim()),
    wraps: [...tile.querySelectorAll('.cd')].filter(c => c.getBoundingClientRect().height > parseFloat(getComputedStyle(c).lineHeight) * 1.5 + 1).length,
    live: tile.querySelectorAll('[aria-live]:not([aria-live="off"])').length,
    overflow: document.documentElement.scrollWidth > innerWidth,
  };
}, sel);
async function shot(page, sel, name) {
  const b = await page.$eval(sel, t => { const r = t.getBoundingClientRect(); return { x: r.left + scrollX, y: Math.max(r.top, 0) + scrollY, width: r.width, height: Math.min(r.bottom, innerHeight) - Math.max(r.top, 0) }; });
  await page.screenshot({ path: path.join(out, `${name}.png`), clip: b, captureBeyondViewport: false });
}

try {
  const runs = [];
  for (const sc of ['real', 'mix', 'mix-stream']) { for (const w of [375, 768, 1440]) runs.push([sc, w, 'light']); runs.push([sc, 375, 'dark']); }
  runs.push(['mix-tab', 375, 'light'], ['mix-tab', 1440, 'light']);
  for (const [sc, width, theme] of runs) {
    const { page, sel } = await open(sc, width, theme, 'no-preference');
    const name = `${sc}-${width}-${theme}`;
    const a = await layout(page, sel);
    await shot(page, sel, name);
    await new Promise(r => setTimeout(r, 1100));
    const b = await layout(page, sel);
    const pend = await page.evaluate(() => ({ pending: window.__cd.pending.size, intervals: window.__cd.intervals }));
    if (width === 375 && theme === 'light') await shot(page, sel, `${name}-1s-later`);
    const ticked = a.faces.some((f, i) => f !== b.faces[i]);
    const moved = a.boxes.filter((x, i) => JSON.stringify(x) !== JSON.stringify(b.boxes[i])).length;
    summary.push({ name, faces: a.faces.join(' | '), ticked, moved, wraps: a.wraps, timers: pend.pending, intervals: pend.intervals, overflow: a.overflow });
    if (a.faces.some(f => /\d\d:\d\d:\d\d/.test(f)) && !ticked) problems.push(`${name}: the seconds did not change in 1.1 s`);
    if (moved) problems.push(`${name}: ${moved} boxes moved between two ticks`);
    if (a.wraps) problems.push(`${name}: a countdown wraps onto two lines`);
    if (a.live) problems.push(`${name}: a live region announces the countdown`);
    if (a.overflow) problems.push(`${name}: page scrolls sideways`);
    if (pend.pending > 1 || pend.intervals) problems.push(`${name}: ${pend.pending} countdown timers pending, ${pend.intervals} intervals`);
    if (a.sr.some(s => /\d+ giây|:\d\d/.test(s))) problems.push(`${name}: screen-reader text carries seconds`);
    if (sc.startsWith('mix') && !a.faces.some(f => /Đang diễn ra/.test(f))) problems.push(`${name}: no in-progress event`);

    // Hidden page: the timer stops and the face freezes; visible again: it catches up at once.
    if (sc === 'mix' && width === 375 && theme === 'light') {
      await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
      const h1 = await layout(page, sel); const hp = await page.evaluate(() => window.__cd.pending.size);
      await new Promise(r => setTimeout(r, 2100));
      const h2 = await layout(page, sel);
      await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')); });
      const h3 = await layout(page, sel); const vp = await page.evaluate(() => window.__cd.pending.size);
      summary.push({ name: 'hidden-pause', pendingHidden: hp, frozen: h1.faces.join('|') === h2.faces.join('|'), caughtUp: h3.faces.join('|') !== h2.faces.join('|'), pendingVisible: vp });
      if (hp !== 0 || h1.faces.join('|') !== h2.faces.join('|')) problems.push('hidden page: the countdown kept ticking');
      if (vp !== 1 || h3.faces.join('|') === h2.faces.join('|')) problems.push('visible again: the countdown did not resume at once');
    }
    await page.close();
  }

  // Reduced motion: words to the minute, no seconds, and no tick within a few seconds.
  for (const width of [375, 1440]) {
    const { page, sel } = await open('mix', width, 'light', 'reduce');
    const a = await layout(page, sel);
    await shot(page, sel, `mix-${width}-light-reduced-motion`);
    await new Promise(r => setTimeout(r, 2100));
    const b = await layout(page, sel);
    const pend = await page.evaluate(() => window.__cd.pending.size);
    summary.push({ name: `reduce-${width}`, faces: a.faces.join(' | '), sr: a.sr.join(' | '), changedIn2s: a.faces.join('|') !== b.faces.join('|'), timers: pend });
    if (a.faces.some(f => /:\d\d/.test(f))) problems.push(`reduce-${width}: seconds shown under reduced motion`);
    if (pend > 1) problems.push(`reduce-${width}: ${pend} timers`);
    await page.close();
  }
} finally {
  await browser.close();
}
console.table(summary);
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ summary, problems }, null, 2));
if (problems.length) { console.log(problems.join('\n')); if (strict) process.exitCode = 1; }
else console.log('Seconds tick with nothing moving, one timer, paused while hidden, minutes only under reduced motion.');

// The home's "Vừa đăng" row and the "N tin mới" pill, in Chrome against a server for this worktree: the row sits at
// the top, newest first; tapping the pill brings the reader there with the announced stories leading the row (new dot,
// no pill text), focus on its heading; opened stories turn "seen" in place. Hot headlines carry the flame.
// node tests/capture-fresh-row.mjs --url http://127.0.0.1:8814 --out plans/reports/tin-moi [--snapshot file.json] [--strict]
// Arrival is simulated inside the headless page only: the first load serves the snapshot without its N newest stories,
// the next poll serves the whole snapshot five minutes later. No data file is touched. --snapshot replaces the served
// snapshot (e.g. the same one re-scored by radar/worth.py).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
};
const url = arg('--url', 'http://127.0.0.1:8814');
const out = arg('--out', 'plans/reports/tin-moi');
const snapshotFile = arg('--snapshot', '');
const strict = process.argv.includes('--strict');
await fs.mkdir(out, { recursive: true });

for (const file of ['index.html', 'feed.css', 'feed.js']) {
  const r = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(r.status, 200, file);
  assert.equal(await r.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), `${file} served by ${url} is not this worktree's`);
}
const full = snapshotFile ? JSON.parse(await fs.readFile(snapshotFile, 'utf8')) : await (await fetch(`${url}/data/radar-ui.json`)).json();
const gen = Date.parse(full.generated_at), winH = Number(full.ranking && full.ranking.window_hours) || 72;
const newest = n => full.stories.filter(s => { const t = Date.parse(s.published_at); return t >= gen - winH * 36e5 && t <= Math.min(gen, Date.now()); })
  .sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at)).slice(0, n);

const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  // Headless Chrome jumps on a smooth scroll unless asked to animate it; the motion check needs the real behaviour.
  headless: true, args: ['--disable-gpu', '--enable-smooth-scrolling'],
  userDataDir: await fs.mkdtemp(path.join(os.tmpdir(), 'tin-moi-chrome-')), timeout: 15000,
});
console.log(`Chrome PID ${browser.process().pid}; server ${url}; snapshot ${full.generated_at}`);
const problems = [], summary = [];
const wait = ms => new Promise(r => setTimeout(r, ms));

async function open(n, width, theme, { motion = 'no-preference', sort = 'worth' } = {}) {
  const held = new Set(newest(n).map(s => s.id));
  const base = { ...full, stories: full.stories.filter(s => !held.has(s.id)) };
  const later = { ...full, generated_at: new Date(gen + 3e5).toISOString() };
  const page = await browser.newPage();
  await page.bringToFront();                               // a background tab reports document.hidden and skips the poll
  const touch = width < 1200;
  await page.setViewport({ width, height: 900, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch && width < 768 });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: motion }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument((t, seen, s) => {
    localStorage.setItem('air2:theme', JSON.stringify(t));
    localStorage.setItem('air2:lastSeen', JSON.stringify(seen));   // a returning reader who has seen this snapshot
    localStorage.setItem('air2:sort', JSON.stringify(s));
    // One profile serves every run: what an earlier run opened or scrolled past must not hide this run's arrivals.
    localStorage.removeItem('air2:read'); localStorage.removeItem('air2:skipped');
  }, theme, full.generated_at, sort);
  // The preload and the page's own first fetch both get the older snapshot; only polls after arrive() get the newer one.
  const state = { later: false };
  page.on('pageerror', e => problems.push(`page error at ${width}px: ${e.message}`));
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (!req.url().includes('data/radar-ui.json')) return req.continue();
    req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(state.later ? later : base) });
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#picks-grid .feed-card', { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await wait(300);
  page._arrival = state;
  return { page, held: [...held] };
}
// The page polls every three minutes and when it becomes visible again; the second path, now.
async function arrive(page) {
  page._arrival.later = true;
  await page.bringToFront();
  for (let i = 0; i < 10 && await page.$('#fresh[hidden]'); i++) {
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await wait(1500);
  }
  await page.waitForSelector('#fresh:not([hidden])', { timeout: 5000 });
  await wait(400);
}
async function settleImages(page) {
  await page.evaluate(async () => {
    const imgs = [...document.querySelectorAll('#fresh-row img, #picks-grid img')];
    imgs.forEach(img => { img.loading = 'eager'; });
    await Promise.all(imgs.map(img => img.decode().catch(() => {})));
  });
  await wait(200);
}
const measure = page => page.evaluate(vw => {
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const row = document.querySelector('#fresh-row');
  const ul = row && row.querySelector('.fresh-list');
  const picks = document.querySelector('#picks');
  const bar = document.querySelector('#bar').getBoundingClientRect();
  const pill = document.querySelector('#fresh');
  const ctrls = row && !row.hidden ? [...row.querySelectorAll('a, button')].filter(visible).filter(el => {
    if (!ul || !ul.contains(el)) return true; const r = el.getBoundingClientRect(), u = ul.getBoundingClientRect(); return r.right > u.left && r.left < u.right;
  }).map(el => { const r = el.getBoundingClientRect(); return { cls: String(el.className.baseVal ?? el.className), w: r.width, h: r.height }; }) : [];
  // A flame must never sit alone on a line: its box (flame + first word) is one line tall.
  const lone = [...document.querySelectorAll('.flame-lead')].filter(visible).filter(el => el.getClientRects().length > 1).length;
  return {
    // A phone widens its layout viewport to fit stray content, so innerWidth growing past the screen is overflow too.
    overflow: document.documentElement.scrollWidth > innerWidth || innerWidth > vw, scrollWidth: document.documentElement.scrollWidth, scrollY: Math.round(scrollY),
    rowShown: !!row && !row.hidden, rowIds: ul ? [...ul.children].map(li => li.dataset.sid) : [],
    rowNew: ul ? [...ul.children].map(li => !!li.querySelector('.new-mark')) : [],
    rowSeen: ul ? [...ul.children].map(li => !!li.querySelector('.seen-mark')) : [],
    rowAbovePicks: !!row && !row.hidden && row.getBoundingClientRect().bottom <= picks.getBoundingClientRect().top + 0.5,
    rowFirst: !!row && !row.hidden && row.getBoundingClientRect().top - bar.bottom < 64,
    pillText: document.querySelector('#fresh-text').textContent, pillShown: !pill.hidden,
    pillBelowBar: pill.hidden || pill.getBoundingClientRect().top >= bar.bottom - 0.5,
    focus: document.activeElement ? (document.activeElement.id || document.activeElement.className) : null,
    shelfScrolls: !!ul && ul.scrollWidth > ul.clientWidth + 1, navShown: !!row && !!row.querySelector('.shelf-nav') && visible(row.querySelector('.shelf-nav')),
    small: ctrls.filter(c => c.h < 44 - 0.5 || c.w < 44 - 0.5),
    flames: document.querySelectorAll('.flame').length, loneFlames: lone,
    pillTags: [...document.querySelectorAll('.why-tag')].filter(el => /Đang bàn nhiều|Đang được chú ý/.test(el.textContent)).length,
  };
}, page.viewport().width);
const shot = (page, name) => page.screenshot({ path: path.join(out, `${name}.png`) });

function check(name, m, held) {
  if (m.overflow) problems.push(`${name}: page scrolls sideways (${m.scrollWidth}px)`);
  if (m.loneFlames) problems.push(`${name}: ${m.loneFlames} flame(s) wrapped away from their headline`);
  if (m.pillTags) problems.push(`${name}: ${m.pillTags} "Đang bàn nhiều"/"Đang được chú ý" tag(s) still shown`);
  for (const c of m.small) problems.push(`${name}: control under 44px ${c.cls} ${Math.round(c.w)}x${Math.round(c.h)}`);
  if (!m.rowShown) { problems.push(`${name}: no "Vừa đăng" row`); return; }
  if (!m.rowAbovePicks || !m.rowFirst) problems.push(`${name}: "Vừa đăng" is not the first thing under the header`);
  if (!held) return;
  const want = full.stories.filter(s => held.includes(s.id)).sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at)).map(s => s.id);
  if (JSON.stringify(m.rowIds.slice(0, want.length)) !== JSON.stringify(want)) problems.push(`${name}: the ${want.length} arrivals do not lead the row newest first`);
  if (m.rowNew.slice(0, want.length).some(x => !x)) problems.push(`${name}: an arrival in the row has no new dot`);
}

try {
  const runs = [];
  for (const n of [1, 3, 8]) for (const [w, theme] of [[375, 'light'], [768, 'light'], [1440, 'light'], [375, 'dark'], [1440, 'dark']]) runs.push([n, w, theme]);
  for (const [n, width, theme] of runs) {
    const name = `n${n}-${width}-${theme}`;
    const { page, held } = await open(n, width, theme);
    if (n === 3) { await settleImages(page); await shot(page, `${name}-0-open`); check(`${name}-open`, await measure(page)); }
    await page.evaluate(() => window.scrollTo(0, 2200));   // the reader is down the page when the update lands
    await arrive(page);
    const before = await measure(page);
    await shot(page, `${name}-1-pill`);
    if (!before.pillShown || before.pillText !== `${n} tin mới`) problems.push(`${name}: pill shows "${before.pillText}" (${before.pillShown ? 'shown' : 'hidden'})`);
    if (!before.pillBelowBar) problems.push(`${name}: pill overlaps the header`);
    await page.click('#fresh-go');
    await wait(1200);                                      // the smooth scroll to the top
    await settleImages(page);
    const after = await measure(page);
    await shot(page, `${name}-2-after-tap`);
    check(name, after, held);
    if (after.scrollY !== 0) problems.push(`${name}: after the tap the page is at ${after.scrollY}, not the top`);
    if (after.focus !== 'fresh-row-h') problems.push(`${name}: focus is on ${after.focus}, not the row heading`);
    summary.push({ name, pill: before.pillText, row: after.rowIds.length, lead: after.rowNew.filter(Boolean).length, top: after.scrollY, focus: after.focus,
      scrolls: after.shelfScrolls, nav: after.navShown, flames: after.flames, overflow: after.overflow, small: after.small.length });
    await page.close();
  }

  // The "Mới nhất" sort (the switch, not the row) orders only the river, which sits below four blocks, so the pill still leads to the top row.
  for (const width of [375, 1440]) {
    const name = `sort-new-n3-${width}`;
    const { page, held } = await open(3, width, 'light', { sort: 'new' });
    await page.evaluate(() => window.scrollTo(0, 2200));
    await arrive(page);
    await page.click('#fresh-go'); await wait(1200); await settleImages(page);
    const m = await measure(page);
    const river = await page.evaluate(() => { const h = document.querySelector('#sec-dong-tin'); return h ? Math.round(h.getBoundingClientRect().top + scrollY) : null; });
    await shot(page, name);
    check(name, m, held);
    summary.push({ name, row: m.rowIds.length, top: m.scrollY, focus: m.focus, riverAt: river });
    await page.close();
  }

  // Opening an arrival turns its dot into the seen check in place; the row stays (it is the page's top, not a notice).
  for (const width of [375, 1440]) {
    const name = `open-n3-${width}`;
    const { page } = await open(3, width, 'light');
    await arrive(page);
    await page.click('#fresh-go'); await wait(1200); await settleImages(page);
    const ids = await page.evaluate(() => [...document.querySelectorAll('#fresh-row .fresh-list > li')].map(li => li.dataset.sid));
    for (const id of ids.slice(0, 3)) {
      await page.evaluate(i => document.querySelector(`#fresh-row li[data-sid="${CSS.escape(i)}"] .fresh-item`).scrollIntoView({ inline: 'nearest', block: 'nearest' }), id);
      await page.click(`#fresh-row li[data-sid="${id}"] .fresh-item`);
      await page.waitForSelector('#story-dialog[open]', { timeout: 5000 });
      await page.keyboard.press('Escape'); await wait(500);
    }
    await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('#fresh-shelf').scrollLeft = 0; }); await wait(300);
    const m = await measure(page);
    await shot(page, `${name}-opened`);
    if (!m.rowShown) problems.push(`${name}: row left after opening`);
    if (m.rowSeen.slice(0, 3).some(x => !x)) problems.push(`${name}: opened stories do not show the seen check`);
    summary.push({ name, opened: 3, seen: m.rowSeen.filter(Boolean).length, focus: m.focus, overflow: m.overflow });
    await page.close();
  }

  // Motion: no smooth scroll under reduce; a smooth one otherwise.
  for (const motion of ['reduce', 'no-preference']) {
    const { page } = await open(3, 1440, 'light', { motion });
    await page.evaluate(() => window.scrollTo(0, 2200));
    await arrive(page);
    const from = await page.evaluate(() => Math.round(scrollY));
    await page.evaluate(() => { window.__ys = []; const t0 = performance.now(); const tick = () => { window.__ys.push([Math.round(performance.now() - t0), Math.round(scrollY)]); if (performance.now() - t0 < 1500) requestAnimationFrame(tick); }; document.querySelector('#fresh-go').addEventListener('click', () => requestAnimationFrame(tick), { once: true }); });
    await page.click('#fresh-go');
    const at = await page.evaluate(() => Math.round(scrollY));
    await wait(1200);
    const end = await page.evaluate(() => Math.round(scrollY));
    const ys = await page.evaluate(() => window.__ys);
    const frames = ys.filter(([, y]) => y > 0 && y < from).length;
    summary.push({ name: `motion-${motion}`, from, rightAfterTap: at, framesBetween: frames, settled: end });
    if (motion === 'reduce' && at !== 0) problems.push(`motion reduce: still at ${at} right after the tap (animated)`);
    if (motion === 'reduce' && frames > 0) problems.push(`motion reduce: ${frames} frames between start and top (animated)`);
    if (motion === 'no-preference' && frames < 3) problems.push(`motion no-preference: only ${frames} frames between start and top (jumped)`);
    if (end !== 0) problems.push(`motion ${motion}: settled at ${end}, not the top`);
    await page.close();
  }

  // Keyboard: U does what the pill does.
  {
    const { page, held } = await open(3, 1440, 'light', { motion: 'reduce' });
    await page.evaluate(() => window.scrollTo(0, 2200));
    await arrive(page);
    await page.keyboard.press('u'); await wait(300);
    const m = await measure(page);
    check('key-u', m, held);
    if (m.focus !== 'fresh-row-h') problems.push(`key-u: focus is on ${m.focus}`);
    summary.push({ name: 'key-u', row: m.rowIds.length, top: m.scrollY, focus: m.focus });
    await page.close();
  }

  // The flame in the ranked tile ("Đang nóng") and the river, close up.
  for (const theme of ['light', 'dark']) for (const width of [375, 1440]) {
    const { page } = await open(0, width, theme);
    const el = await page.$('.tile-hot');
    if (el) { await el.scrollIntoView(); await wait(300); await shot(page, `flame-hot-tile-${width}-${theme}`); }
    await page.close();
  }
} finally {
  await browser.close();
}
console.table(summary);
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ snapshot: full.generated_at, summary, problems }, null, 2));
if (problems.length) { console.log(problems.join('\n')); if (strict) process.exitCode = 1; }
else console.log('"Vừa đăng" leads the page; the pill brings the reader there with the arrivals first and focused; flames stay with their headlines; no overflow, no small controls.');

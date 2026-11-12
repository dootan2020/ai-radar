// "Vừa đăng" on the front page, in Chrome against this worktree, in two states (captain, 12/11 09:23: "danh sách tin
// vừa đăng nó dài quá"):
//   normal: a returning reader with two stories published since the last look, so the tile mixes new and seen rows;
//   burst:  fifty stories arrive in one poll (a newsroom catching up), the reader taps "50 tin mới";
//   pill7:  seven new stories on return, the reader taps "7 tin mới" (the screen the captain sent).
// node tests/capture-vua-dang.mjs --out <dir> [--port 8797]
// The site is served from site/ by a small server in this script; every data/*.json is tests/fixtures/
// radar-window-sample.json. Arrivals are simulated inside the headless page only. Nothing under site/ is written.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = path.resolve(root, arg('--out', 'vua-dang-run'));
const port = Number(arg('--port', '8797'));
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
await fs.mkdir(out, { recursive: true });

const full = JSON.parse(await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8'));
const gen = Date.parse(full.generated_at);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (/^\/data\/[\w.-]+\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(full)); }
    const file = path.join(root, 'site', p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise((ok, fail) => { server.once('error', fail); server.listen(port, '127.0.0.1', ok); });
const url = `http://127.0.0.1:${port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const summary = [], problems = [];
console.log(`server ${url}; snapshot ${full.generated_at}; out ${out}`);

// Fifty stories published in the hour after the snapshot, each a copy of a real story under a new id.
const sources = full.stories.filter(s => s.published_at && s.title).slice(0, 50);
const burstStories = sources.map((s, i) => ({ ...s, id: `burst-${i}`, published_at: new Date(gen + (59 - i) * 6e4).toISOString(),
  first_seen_at: new Date(gen + 60 * 6e4).toISOString(), latest_coverage_at: null }));
const burstSnap = { ...full, generated_at: new Date(gen + 61 * 6e4).toISOString(), stories: [...burstStories, ...full.stories] };

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'vua-dang-'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, pipe: true, userDataDir: profile,
  args: ['--disable-gpu'], timeout: 20000 });
console.log(`Chrome PID ${browser.process().pid}`);

async function open(width, theme, { lastSeen = full.generated_at, first = full, later = null } = {}) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.bringToFront();
  const touch = width < 768;
  const height = touch ? 812 : width >= 1700 ? 1000 : 900;
  await page.setViewport({ width, height, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument((t, seen) => {
    localStorage.setItem('air2:theme', JSON.stringify(t));
    localStorage.setItem('air2:lastSeen', JSON.stringify(seen));
  }, theme, lastSeen);
  const state = { later: false };
  page.on('pageerror', e => problems.push(`page error at ${width}px: ${e.message}`));
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (!/\/data\/[\w.-]+\.json/.test(req.url())) return req.continue();
    req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(state.later && later ? later : first) });
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#fresh-row'), { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await wait(900);
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

// What the tile shows: rows whole or cut, which carry the chip, and how its height sits against the lead's.
const look = page => page.evaluate(() => {
  const tile = document.querySelector('#fresh-row');
  const r = tile.getBoundingClientRect();
  const lead = document.querySelector('.band-today .msn-lead')?.getBoundingClientRect();
  const rows = [...tile.querySelectorAll('.fresh-list > li')].map(li => {
    const b = li.getBoundingClientRect();
    const shown = !li.hidden && b.height > 0;
    const chip = getComputedStyle(li.querySelector('.fresh-new')).display !== 'none';
    const lines = Math.round(li.querySelector('.brief-h').getBoundingClientRect().height / parseFloat(getComputedStyle(li.querySelector('.brief-h')).lineHeight));
    return { id: li.dataset.sid, shown, whole: b.top >= r.top - 0.5 && b.bottom <= r.bottom + 0.5, chip, status: li.dataset.status,
      pinned: li.hasAttribute('data-pinned'), time: li.querySelector('time').textContent, lines };
  });
  return { tileH: Math.round(r.height), leadH: lead ? Math.round(lead.height) : null, scrolls: tile.scrollHeight > tile.clientHeight + 1,
    rows, river: [...document.querySelectorAll('#feed-grid .nc[data-id]')].map(el => el.dataset.id),
    overflow: document.documentElement.scrollWidth > innerWidth, pager: !!tile.querySelector('.fresh-pager, [data-fresh-page]') };
});

function judge(name, m, { chips }) {
  const shown = m.rows.filter(r => r.shown);
  const row = { name, rows: shown.length, chips: shown.filter(r => r.chip).length, times: shown.map(r => r.time).join(' '),
    lines: shown.map(r => r.lines).join(''), tileH: m.tileH, leadH: m.leadH };
  summary.push(row);
  if (shown.length > 4) problems.push(`${name}: ${shown.length} rows in the tile`);
  if (!shown.length) problems.push(`${name}: the tile is empty`);
  if (shown.some(r => !r.whole)) problems.push(`${name}: a row is cut by the tile's edge`);
  if (m.scrolls) problems.push(`${name}: the tile scrolls`);
  if (m.pager) problems.push(`${name}: the tile has a pager`);
  if (m.overflow) problems.push(`${name}: the page scrolls sideways`);
  if (m.leadH && m.tileH !== m.leadH && name.match(/-(1440|1754|2000)-/)) problems.push(`${name}: tile ${m.tileH}px beside a ${m.leadH}px lead`);
  if (chips !== undefined && row.chips !== chips) problems.push(`${name}: ${row.chips} "Mới" chip(s), expected ${chips}`);
  const twice = shown.filter(r => m.river.includes(r.id));
  if (twice.length) problems.push(`${name}: ${twice.length} tile row(s) also in the river`);
}

const shot = (page, name) => page.screenshot({ path: path.join(out, `${name}.png`) });

try {
  // The tile's four rows for a reader who has seen everything; the second-newest's time becomes the last look, so the
  // newest one or two are new to them (published after it) and the rest are not.
  const probe = await open(1440, 'light');
  const times = await probe.page.$$eval('#fresh-row .fresh-list > li time', ts => ts.map(t => t.getAttribute('datetime')));
  await probe.ctx.close();
  const mixedSeen = times[2];
  console.log(`tile times ${times.join(' ')}; last look for "normal" ${mixedSeen}`);

  // Seven stories new on return, as on the captain's screen: hold the snapshot's seven newest out of the last look.
  const byPubDesc = full.stories.filter(s => s.published_at && Date.parse(s.published_at) <= gen)
    .sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));
  const sevenSeen = new Date(Date.parse(byPubDesc[7].published_at) + 1000).toISOString();

  const widths = [[375, 'light'], [1440, 'light'], [1440, 'dark'], [1754, 'light'], [1754, 'dark'], [2000, 'light'], [2000, 'dark']];
  for (const [width, theme] of widths) {
    {
      const name = `normal-${width}-${theme}`;
      const { page, ctx } = await open(width, theme, { lastSeen: mixedSeen });
      await page.evaluate(() => window.scrollTo(0, 0)); await wait(200);
      await shot(page, name);
      judge(name, await look(page), { chips: undefined });
      await ctx.close();
    }
    {
      const name = `burst-${width}-${theme}`;
      const { page, ctx, state } = await open(width, theme, { later: burstSnap });
      await page.evaluate(() => window.scrollTo(0, 1600));
      await arrive(page, state);
      const pill = await page.$eval('#fresh-text', el => el.textContent);
      await page.$eval('#fresh-go', b => b.click());
      await wait(500);
      await shot(page, `${name}-glow`);
      await wait(2200);
      await page.evaluate(() => window.scrollTo(0, 0)); await wait(300);
      await shot(page, name);
      const m = await look(page);
      judge(name, m, { chips: 0 });
      summary.at(-1).pill = pill;
      if (pill !== '50 tin mới') problems.push(`${name}: pill "${pill}"`);
      const ids = m.rows.filter(r => r.shown).map(r => r.id);
      const want = burstStories.map(s => s.id).slice(0, ids.length);
      if (JSON.stringify(ids) !== JSON.stringify(want)) problems.push(`${name}: rows ${ids.join(',')} are not the newest arrivals`);
      const restInRiver = burstStories.map(s => s.id).filter(id => !ids.includes(id) && m.river.includes(id)).length;
      summary.at(-1).restInRiver = restInRiver;
      await ctx.close();
    }
  }
  for (const [width, theme] of [[1754, 'light'], [1754, 'dark']]) {
    const name = `pill7-${width}-${theme}`;
    const { page, ctx } = await open(width, theme, { lastSeen: sevenSeen });
    const pill = await page.$eval('#fresh-text', el => el.textContent);
    if (await page.$('#fresh:not([hidden])')) { await page.$eval('#fresh-go', b => b.click()); await wait(2600); }
    await page.evaluate(() => window.scrollTo(0, 0)); await wait(300);
    await shot(page, name);
    judge(name, await look(page), {});
    summary.at(-1).pill = pill;
    await ctx.close();
  }
} finally {
  await browser.close();
  await new Promise(r => server.close(r));
}
console.table(summary);
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ snapshot: full.generated_at, summary, problems }, null, 2));
if (problems.length) { console.log(problems.join('\n')); process.exitCode = 1; }
else console.log('"Vừa đăng": at most four whole rows beside the lead at every width, no pager, the chip only where it tells rows apart.');

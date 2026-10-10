// Every number a home card shows (the photo-less cover, the foot metric, the "why" line, the hot list) must measure the
// page that card links to, never another coverage item of the same cluster (another article, a social post).
// Opens the home page and each news tab in Chrome against a server for this worktree, counts cards whose shown number
// belongs to a different item, and saves screenshots of the home page.
// node tests/capture-card-metric.mjs --url http://127.0.0.1:8817 --out plans/reports/o-99 [--strict] [--focus <story id>]
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
};
const url = arg('--url', 'http://127.0.0.1:8817');
const out = arg('--out', 'plans/reports/o-99');
const focus = arg('--focus', '');
const strict = process.argv.includes('--strict');
await fs.mkdir(out, { recursive: true });

for (const file of ['index.html', 'feed.js']) {
  const r = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(r.status, 200, file);
  assert.equal(await r.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), `${file} served by ${url} is not this worktree's`);
}

const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true, args: ['--disable-gpu'],
  userDataDir: await fs.mkdtemp(path.join(os.tmpdir(), 'card-metric-chrome-')), timeout: 15000,
});
const wait = ms => new Promise(r => setTimeout(r, ms));

async function open(width, theme) {
  const page = await browser.newPage();
  const touch = width < 768;
  await page.setViewport({ width, height: 900, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument(t => { localStorage.setItem('air2:theme', JSON.stringify(t)); }, theme);
  await page.goto(`${url}/`, { waitUntil: 'networkidle0', timeout: 30000 });
  await page.waitForSelector('.feed-card', { timeout: 15000 });
  return page;
}

/* In the page: which shown numbers come from a coverage item other than the one the card links to. */
const audit = () => page => page.evaluate(async () => {
  const { fmt } = await import('/faces.js');
  const D = await (await fetch('data/radar-ui.json')).json();
  const byId = new Map(D.stories.map(s => [s.id, s]));
  const okT = (o, v) => typeof v === 'string' && v.trim() && v.trim() !== String(o || '').trim();
  const norm = u => String(u || '').trim().replace(/#.*$/, '').replace(/\/+$/, '');
  const leadOf = st => {
    if (okT(st.title, st.title_vi)) return st.url;
    const c = (st.coverage || []).find(c => okT(c.title, c.title_vi));
    return c ? c.url : st.url;
  };
  const values = st => {
    const lead = norm(leadOf(st)), own = new Set(), other = new Set();
    for (const c of st.coverage || []) for (const v of Object.values(c.metrics || {})) {
      if (typeof v === 'number' && Number.isFinite(v)) (norm(c.url) === lead ? own : other).add(fmt(v));
    }
    const m = st.hot_signals && st.hot_signals.measurement;
    if (m && Number.isFinite(m.value)) {
      const c = (st.coverage || []).find(c => c.source === m.source && c.metrics && m.metric in c.metrics);
      (c && norm(c.url) === lead ? own : other).add(fmt(m.value));
    }
    return { own, other };
  };
  const shown = el => {
    const nums = [];
    const cv = el.querySelector('.cover-num');
    if (cv && !/nguồn cùng đưa/.test(el.querySelector('.cover-word')?.textContent || '')) nums.push(['cover', cv.textContent.trim()]);
    const foot = el.querySelector('.card-foot .metric > span:not(.cov-btn) b.num');
    if (foot) nums.push(['foot', foot.textContent.trim()]);
    for (const b of el.querySelectorAll('.why-line b.num, .hot-why b.num')) {
      if (!/nguồn cùng đưa/.test(b.parentElement.textContent)) nums.push(['why', b.textContent.trim()]);
    }
    return nums;
  };
  const bad = [];
  let cards = 0, covers = 0, withNum = 0;
  for (const el of document.querySelectorAll('article.feed-card[data-id], a.hot-row[data-sid]')) {
    const id = el.dataset.id || el.dataset.sid, st = byId.get(id);
    if (!st) continue;
    cards++;
    if (el.querySelector('.cover')) covers++;
    const nums = shown(el);
    if (nums.length) withNum++;
    const { own, other } = values(st);
    const hits = nums.filter(([, n]) => other.has(n) && !own.has(n));
    if (hits.length) bad.push({ id, where: hits.map(h => `${h[0]}=${h[1]}`).join(' '), cover: el.querySelector('.cover-word')?.textContent || '' });
  }
  return { cards, covers, withNum, bad };
});

const tally = {};
const page = await open(1440, 'light');
const tabs = await page.$$eval('.filter-chip', bs => bs.filter(b => !b.hidden).map(b => b.dataset.filter)
  .filter(f => f !== 'rankings' && f !== 'saved'));
for (const f of tabs) {
  await page.evaluate(f => document.querySelector(`.filter-chip[data-filter="${f}"]`).click(), f);
  await wait(400);
  tally[f] = await audit()(page);
}
await page.evaluate(() => document.querySelector('.filter-chip[data-filter="all"]').click());
await wait(400);

const shots = [];
const shoot = async (p, name) => {
  const file = path.join(out, `${name}.png`);
  await p.screenshot({ path: file });                       // first: scrolling back up leaves the header mid-animation
  shots.push(file);
  if (focus && await p.$(`article.feed-card[data-id="${focus}"]`)) {
    await p.evaluate(id => document.querySelector(`article.feed-card[data-id="${id}"]`).scrollIntoView({ block: 'center' }), focus);
    await wait(400);
    const el = await p.$(`article.feed-card[data-id="${focus}"]`);
    await el.screenshot({ path: path.join(out, `${name}-card.png`) });
    shots.push(path.join(out, `${name}-card.png`));
  }
};
await shoot(page, 'home-1440-light');
await page.close();
for (const [w, theme] of [[375, 'light'], [1440, 'dark']]) {
  const p = await open(w, theme);
  await shoot(p, `home-${w}-${theme}`);
  await p.close();
}
await browser.close();

let total = 0;
for (const [f, r] of Object.entries(tally)) {
  total += r.bad.length;
  console.log(`${f}: ${r.cards} cards (${r.covers} photo-less, ${r.withNum} with a number), ${r.bad.length} showing another item's number`);
  for (const b of r.bad) console.log(`  ${b.id} ${b.where}${b.cover ? ` | cover: ${b.cover}` : ''}`);
}
console.log(`screenshots: ${shots.join(', ')}`);
if (strict) assert.equal(total, 0, 'cards show a number that belongs to another coverage item');

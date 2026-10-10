// Render the home's "Sắp diễn ra" shelf with Chrome against a server for this worktree, screenshot it and measure it.
// node tests/capture-events-shelf.mjs --url http://127.0.0.1:8811 --out plans/reports/ke-su-kien [--strict]
// Scenarios swap the snapshot's events and live items inside the headless page only; no data file is touched.
// Phone and tablet widths run with touch emulation, so the page sees a coarse pointer the way a phone does.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
};
const url = arg('--url', 'http://127.0.0.1:8811');
const out = arg('--out', 'plans/reports/ke-su-kien');
const widths = arg('--widths', '375,768,1024,1440,1920').split(',').map(Number);
const only = arg('--scenarios', '');
const strict = process.argv.includes('--strict');
await fs.mkdir(out, { recursive: true });

for (const file of ['index.html', 'feed.css', 'feed.js']) {
  const r = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(r.status, 200, file);
  assert.equal(await r.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), `${file} served by ${url} is not this worktree's`);
}

const day = n => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);
const extra = [
  ['Google I/O Connect — Berlin', 3, 3, 'Berlin, Đức'],
  ['AI Engineer World’s Fair: Agents, Evals and the Infrastructure Track', 9, 11, 'San Francisco, Mỹ'],
  ['PyTorch Conference', 20, 21, ''],
  ['Hội thảo AI Việt Nam 2026: Mô hình ngôn ngữ cho tiếng Việt và ứng dụng', 25, 26, 'TP. Hồ Chí Minh, Việt Nam'],
  ['ICLR 2027 — hạn nộp bài', 30, 30, 'Trực tuyến'],
  ['Microsoft Ignite', 38, 41, 'Chicago, Mỹ'],
  ['AWS re:Invent', 45, 49, 'Las Vegas, Mỹ'],
].map(([title, a, b, location], i) => ({ id: `cap-ev-${i}`, title, url: `https://example.com/${i}`, start_date: day(a), end_date: day(b), location,
  start_at: null, end_at: null, time_precision: 'date', verified_at: day(-2), source_url: `https://example.com/${i}` }));
const stream = thumb => ({ status: 'live', video_id: 'capture-live', title: 'Live: building agents with the new Responses API, questions answered',
  url: 'https://www.youtube.com/watch?v=capture-live', channel: 'OpenAI', thumbnail: thumb, time_text: '' });
const evs = (d, n) => [...d.events, ...extra].sort((a, b) => a.start_date.localeCompare(b.start_date)).slice(0, n);

const SCENARIOS = {
  real: d => d,
  ev1: d => ({ ...d, events: evs(d, 1), live: [] }),
  ev3: d => ({ ...d, events: evs(d, 3), live: [] }),
  ev5: d => ({ ...d, events: evs(d, 5), live: [] }),
  ev8: d => ({ ...d, events: evs(d, 8), live: [] }),
  stream: d => ({ ...d, events: evs(d, 5), live: [stream(firstImage(d))] }),
  'stream-ev1': d => ({ ...d, events: evs(d, 1), live: [stream(firstImage(d))] }),
};
function firstImage(d) {
  const s = d.stories.find(s => s.image && (s.image.src || s.image.url || typeof s.image === 'string'));
  return s ? (typeof s.image === 'string' ? s.image : s.image.src || s.image.url) : '';
}

const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true, args: ['--disable-gpu'],
  userDataDir: await fs.mkdtemp(path.join(path.resolve(out), 'chrome-profile-')), timeout: 15000,
});
console.log(`Chrome PID ${browser.process().pid}; server ${url}`);
const problems = [];
const summary = [];

async function open(sc, width, theme, motion = 'reduce') {
  const page = await browser.newPage();
  const touch = width < 1200 && width !== 1024;   // 375 and 768 are touch devices; 1024 stands for a small laptop
  await page.setViewport({ width, height: 900, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch && width < 768 });
  if (touch) { const cdp = await page.createCDPSession(); await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 }); }
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: motion }]);
  await page.evaluateOnNewDocument(t => { localStorage.setItem('air2:theme', JSON.stringify(t)); }, theme);
  await page.setRequestInterception(true);
  page.on('request', async req => {
    if (!req.url().includes('data/radar-ui.json')) return req.continue();
    const r = await fetch(req.url());
    req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(SCENARIOS[sc](await r.json())) });
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#picks-grid .tile-live', { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async () => {
    const imgs = [...document.querySelectorAll('#picks-grid img')];
    imgs.forEach(img => { img.loading = 'eager'; });
    await Promise.all(imgs.map(img => img.decode().catch(() => {})));
  });
  await new Promise(r => setTimeout(r, 300));
  return { page, touch };
}

const measure = page => page.evaluate(() => {
  const box = el => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top + scrollY, w: r.width, h: r.height, right: r.right, bottom: r.bottom + scrollY }; };
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const tile = document.querySelector('#picks-grid .tile-live');
  const ul = tile && tile.querySelector('.events');
  const nav = tile && tile.querySelector('.shelf-nav');
  const ur = ul && ul.getBoundingClientRect();
  const cards = ul ? [...ul.children].map(li => { const r = li.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height), left: Math.round(r.left - ur.left), inView: r.left >= ur.left - 1 && r.right <= ur.right + 1 }; }) : [];
  // Controls the reader can hit: inside the shelf's visible box, or anywhere else in the tile.
  const ctrls = tile ? [...tile.querySelectorAll('a, button')].filter(visible).filter(el => {
    if (!ul || !ul.contains(el)) return true; const r = el.getBoundingClientRect(); return r.right > ur.left && r.left < ur.right;
  }).map(el => ({ cls: String(el.className.baseVal ?? el.className), ...box(el) })) : [];
  const region = tile && tile.querySelector('[role="region"]');
  return {
    overflow: document.documentElement.scrollWidth > innerWidth, scrollWidth: document.documentElement.scrollWidth,
    tile: tile ? box(tile) : null, picks: box(document.querySelector('#picks')),
    shelf: ul ? { cls: ul.className, n: ul.children.length, client: ul.clientWidth, scroll: ul.scrollWidth, overflowX: getComputedStyle(ul).overflowX,
      snap: getComputedStyle(ul).scrollSnapType, scrollbar: getComputedStyle(ul).scrollbarWidth } : null,
    cards, navShown: !!nav && visible(nav), navHidden: nav ? nav.hidden : null,
    navNames: nav ? [...nav.querySelectorAll('button')].map(b => b.getAttribute('aria-label')) : [],
    region: region ? region.getAttribute('aria-label') : null,
    pointerCoarse: matchMedia('(pointer: coarse)').matches,
    small: ctrls.filter(c => c.h < 44 - 0.5 || c.w < 44 - 0.5),
  };
});

async function shoot(page, m, name) {
  const top = Math.max(0, (m.picks && m.picks.h ? m.picks : m.tile).y - 8);
  await page.screenshot({ path: path.join(out, `${name}.png`), clip: { x: 0, y: top, width: page.viewport().width, height: Math.min(m.tile.bottom - top + 16, 4000) }, captureBeyondViewport: true });
}
// Only the tile, for a close look at the shelf.
async function shootTile(page, name) {
  const el = await page.$('#picks-grid .tile-live');
  await el.scrollIntoView(); await new Promise(r => setTimeout(r, 150));
  // A clip of the viewport as it stands: an element screenshot resizes the page for a moment, and the shelf
  // re-snaps on that resize, so it would picture a scroll position the reader never sees.
  const b = await el.evaluate(t => { const r = t.getBoundingClientRect(); return { x: r.left + scrollX, y: Math.max(r.top, 0) + scrollY, width: r.width, height: Math.min(r.bottom, innerHeight) - Math.max(r.top, 0) }; });
  await page.screenshot({ path: path.join(out, `${name}.png`), clip: b, captureBeyondViewport: false });
}

try {
  const runs = [];
  for (const sc of Object.keys(SCENARIOS)) {
    if (only && !only.split(',').includes(sc)) continue;
    for (const w of widths) runs.push([sc, w, 'light']);
    if (sc === 'real' || sc === 'ev5' || sc === 'stream') { runs.push([sc, 375, 'dark']); runs.push([sc, 1440, 'dark']); }
  }
  for (const [sc, width, theme] of runs) {
    const { page, touch } = await open(sc, width, theme);
    const m = await measure(page);
    const name = `${sc}-${width}-${theme}`;
    if (m.tile) { await shoot(page, m, name); await shootTile(page, `tile-${name}`); }
    summary.push({ name, touch, coarse: m.pointerCoarse, overflow: m.overflow, n: m.shelf && m.shelf.n, cardW: m.cards[0] && m.cards[0].w,
      cardsInView: m.cards.filter(c => c.inView).length, shelfScrolls: m.shelf && m.shelf.scroll > m.shelf.client + 1, nav: m.navShown, small: m.small.length });
    if (m.overflow) problems.push(`${name}: page scrolls sideways (${m.scrollWidth}px)`);
    for (const c of m.small) problems.push(`${name}: control under 44px ${c.cls} ${Math.round(c.w)}x${Math.round(c.h)}`);
    if (m.shelf && m.shelf.n > 1) {
      const scrolls = m.shelf.scroll > m.shelf.client + 1;
      if (scrolls !== m.navShown && !touch && width >= 768) problems.push(`${name}: arrows ${m.navShown ? 'shown' : 'hidden'} while the shelf ${scrolls ? 'scrolls' : 'fits'}`);
      if ((touch || width < 768) && m.navShown) problems.push(`${name}: arrows shown on a touch screen`);
      if (!m.region) problems.push(`${name}: shelf region has no label`);
      if (m.navNames.some(n => !n)) problems.push(`${name}: an arrow has no name`);
      const hs = new Set(m.cards.map(c => c.h)); if (width < 1200 && hs.size > 1) problems.push(`${name}: cards of unequal height ${[...hs]}`);
      if (width < 1200 && scrolls && m.cards.filter(c => c.inView).length === m.cards.length) problems.push(`${name}: nothing peeks`);
    }
    if (m.shelf && m.shelf.n === 1 && m.navShown) problems.push(`${name}: arrows for a single event`);

    // A swipe on the phone: the shelf mid-scroll, after one card.
    if (theme === 'light' && width === 375 && m.shelf && m.shelf.scroll > m.shelf.client + 1) {
      // Held between two cards (snapping off for the picture), then let go: the row settles on the nearer card.
      const held = await page.evaluate(() => { const ul = document.querySelector('#picks-grid .events.shelf'); ul.style.scrollSnapType = 'none';
        ul.scrollLeft = ul.firstElementChild.getBoundingClientRect().width * 0.4; return ul.scrollLeft; });
      await shootTile(page, `tile-${name}-midscroll`);
      const snapped = await page.evaluate(async () => { const ul = document.querySelector('#picks-grid .events.shelf'); ul.style.scrollSnapType = '';
        await new Promise(r => setTimeout(r, 700)); return ul.scrollLeft; });
      await shootTile(page, `tile-${name}-snapped`);
      summary[summary.length - 1].heldLeft = Math.round(held);
      summary[summary.length - 1].snapLeft = Math.round(snapped);
    }
    await page.close();
  }

  // Keyboard and arrows, on a desktop with eight events.
  for (const motion of ['no-preference', 'reduce']) {
    const { page } = await open('ev8', 1440, 'light', motion);
    const tabbed = [];
    await page.focus('#picks-grid .card-lead .story-link').catch(() => {});
    for (let i = 0; i < 60 && tabbed.length < 30; i++) {
      await page.keyboard.press('Tab');
      if (motion !== 'reduce') await new Promise(r => setTimeout(r, 600));   // the smooth scroll that brings a peeking card in
      const f = await page.evaluate(() => {
        const a = document.activeElement, ul = document.querySelector('#picks-grid .events.shelf');
        if (!ul || !document.querySelector('#picks-grid .tile-live').contains(a)) return null;
        const r = a.getBoundingClientRect(), u = ul.getBoundingClientRect(), cs = getComputedStyle(a);
        return { cls: String(a.className.baseVal ?? a.className), inShelf: ul.contains(a), visibleInShelf: !ul.contains(a) || (r.left >= u.left - 1 && r.right <= u.right + 1),
          outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0, label: a.getAttribute('aria-label') || a.textContent.trim().slice(0, 40) };
      });
      if (f) tabbed.push(f);
      if (f && f.cls.includes('event') && tabbed.filter(t => t.cls.includes('event')).length === 5) await shootTile(page, `tile-ev8-1440-focus-5th-${motion}`);
    }
    const links = tabbed.filter(t => t.cls === 'event');
    // The home shows the six nearest of the eight; the rest are one link away.
    if (links.length !== 6) problems.push(`keyboard ${motion}: reached ${links.length} of 6 event links by Tab`);
    for (const t of tabbed) { if (!t.visibleInShelf) problems.push(`keyboard ${motion}: focused ${t.cls} "${t.label}" is outside the shelf's view`); if (!t.outline) problems.push(`keyboard ${motion}: no visible focus on ${t.cls}`); }
    await page.evaluate(() => { document.querySelector('#picks-grid .events.shelf').scrollLeft = 0; });
    await new Promise(r => setTimeout(r, 200));
    const before = await measure(page);
    await page.click('.shelf-btn[data-shelf="1"]');
    const mid = await page.evaluate(() => document.querySelector('#picks-grid .events.shelf').scrollLeft);
    await new Promise(r => setTimeout(r, 900));
    const st = await page.evaluate(() => { const ul = document.querySelector('#picks-grid .events.shelf'); const [p, n] = document.querySelectorAll('.shelf-btn');
      const u = ul.getBoundingClientRect(); const first = [...ul.children].find(li => li.getBoundingClientRect().left >= u.left - 1);
      return { left: ul.scrollLeft, prev: p.getAttribute('aria-disabled'), next: n.getAttribute('aria-disabled'), firstAligned: first ? Math.round(first.getBoundingClientRect().left - u.left) : null }; });
    await shootTile(page, `tile-ev8-1440-after-next-${motion}`);
    for (let i = 0; i < 6; i++) { await page.click('.shelf-btn[data-shelf="1"]'); await new Promise(r => setTimeout(r, 700)); }
    const end = await page.evaluate(() => { const [p, n] = document.querySelectorAll('.shelf-btn'); return { prev: p.getAttribute('aria-disabled'), next: n.getAttribute('aria-disabled') }; });
    // Hover state of an arrow, for the picture.
    await page.hover('.shelf-btn[data-shelf="-1"]'); await new Promise(r => setTimeout(r, 200));
    await shootTile(page, `tile-ev8-1440-end-${motion}`);
    summary.push({ name: `arrows-${motion}`, firstPrev: before.navShown, immediateLeft: Math.round(mid), afterNext: Math.round(st.left), prev: st.prev, next: st.next, firstAligned: st.firstAligned, endNext: end.next, tabbedEvents: links.length });
    if (!(st.left > 0) || st.prev !== 'false') problems.push(`arrows ${motion}: next did not move the shelf`);
    if (end.next !== 'true') problems.push(`arrows ${motion}: next still enabled at the end`);
    if (motion === 'reduce' && Math.round(mid) !== Math.round(st.left)) problems.push(`arrows reduce: the shelf animated (${mid} then ${st.left})`);
    await page.close();
  }
} finally {
  await browser.close();
}
console.table(summary);
await fs.writeFile(path.join(out, 'measure.json'), JSON.stringify({ summary, problems }, null, 2));
if (problems.length) { console.log(problems.join('\n')); if (strict) process.exitCode = 1; }
else console.log('No page overflow, no control under 44px, arrows only when the shelf overflows on a mouse, keyboard reaches every card.');

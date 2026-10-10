// Render the home's events tile and every card's source row with Chrome, against a server for this worktree.
// node tests/capture-events-tile.mjs --url http://127.0.0.1:8808 --out plans/reports/events-tile --tag after
// Scenarios swap the snapshot's events and live items inside the headless page only; no data file is touched.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
};
const url = arg('--url', 'http://127.0.0.1:8808');
const out = arg('--out', 'plans/reports/events-tile');
const tag = arg('--tag', 'after');
const widths = arg('--widths', '375,768,1024,1440,1920').split(',').map(Number);
const only = arg('--scenarios', '');
const strict = process.argv.includes('--strict');
await fs.mkdir(out, { recursive: true });

for (const file of ['index.html', 'feed.css', 'feed.js']) {
  const r = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(r.status, 200, file);
  assert.equal(await r.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), `${file} served by ${url} is not this worktree's`);
}

const day = n => { const d = new Date(Date.now() + n * 864e5); return d.toISOString().slice(0, 10); };
const extra = [
  { id: 'cap-ev-a', title: 'Google I/O Connect — Berlin', url: 'https://example.com/a', start_date: day(3), end_date: day(3), location: 'Berlin, Đức' },
  { id: 'cap-ev-b', title: 'AI Engineer World’s Fair: Agents, Evals and the Infrastructure Track', url: 'https://example.com/b', start_date: day(9), end_date: day(11), location: 'San Francisco, Mỹ' },
  { id: 'cap-ev-c', title: 'PyTorch Conference', url: 'https://example.com/c', start_date: day(20), end_date: day(21), location: '' },
].map(e => ({ start_at: null, end_at: null, time_precision: 'date', verified_at: day(-2), source_url: e.url, ...e }));
const stream = thumb => ({ status: 'live', video_id: 'capture-live', title: 'Live: building agents with the new Responses API, questions answered',
  url: 'https://www.youtube.com/watch?v=capture-live', channel: 'OpenAI', thumbnail: thumb, time_text: '' });

const SCENARIOS = {
  real: d => d,
  ev1: d => ({ ...d, events: d.events.slice(0, 1), live: [] }),
  ev3: d => ({ ...d, events: [...d.events, extra[0]], live: [] }),
  ev5: d => ({ ...d, events: [...d.events, ...extra], live: [] }),
  stream: d => ({ ...d, live: [stream(firstImage(d))] }),
  'stream-ev1': d => ({ ...d, events: d.events.slice(0, 1), live: [stream(firstImage(d))] }),
  // The "Sắp diễn ra" view, where the tile lists every event.
  'ev5-tab': d => ({ ...d, events: [...d.events, ...extra], live: [] }),
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
try {
  const runs = [];
  for (const sc of Object.keys(SCENARIOS)) {
    if (only && !only.split(',').includes(sc)) continue;
    const ws = sc === 'real' ? widths : widths.filter(w => [375, 1024, 1440].includes(w));
    for (const w of ws) runs.push([sc, w, 'light']);
    if (sc === 'real' || sc === 'stream') runs.push([sc, 1440, 'dark']);
  }
  for (const [sc, width, theme] of runs) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.evaluateOnNewDocument(t => { localStorage.setItem('air2:theme', JSON.stringify(t)); }, theme);
    await page.setRequestInterception(true);
    page.on('request', async req => {
      if (!req.url().includes('data/radar-ui.json')) return req.continue();
      const r = await fetch(req.url());
      const d = SCENARIOS[sc](await r.json());
      req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(d) });
    });
    const tab = sc.endsWith('-tab');
    await page.goto(tab ? `${url}/#sap-toi` : url, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector(tab ? '#feed-grid .tile-live' : '#picks-grid .card-lead .card-title', { timeout: 20000 });
    await page.evaluate(() => document.fonts.ready);
    // Render a few more rows so the wide, debate and ranked variants are in the page.
    for (let i = 0; i < 4; i++) { await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await new Promise(r => setTimeout(r, 250)); }
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(async () => {
      const imgs = [...document.querySelectorAll('#picks-grid img')];
      imgs.forEach(img => { img.loading = 'eager'; });
      await Promise.all(imgs.map(img => img.decode().catch(() => {})));
    });
    await page.evaluate(async () => { await Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))); });
    await new Promise(r => setTimeout(r, 300));
    const m = await page.evaluate(() => {
      const box = el => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top + scrollY, w: r.width, h: r.height, right: r.right, bottom: r.bottom + scrollY }; };
      const visible = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !el.classList.contains('sr'); };
      // Lines of a row: the distinct vertical centres of its visible leaf pieces.
      const lines = row => {
        const parts = [...row.querySelectorAll('.st-mark, .pick-n, .src-av, .src-name, time, .mt, span[aria-hidden="true"]')]
          .filter(el => visible(el) && !el.closest('.sr'));
        const ys = [];
        for (const el of parts) { const r = el.getBoundingClientRect(); const c = r.top + r.height / 2; if (!ys.some(y => Math.abs(y - c) < 6)) ys.push(c); }
        return ys.length;
      };
      const tile = [...document.querySelectorAll('.tile-live')].find(el => el.getClientRects().length && !el.closest('[hidden]'));
      const ctrls = tile ? [...tile.querySelectorAll('a, button')].filter(visible).map(el => ({ cls: el.className, ...box(el) })) : [];
      const rows = [...document.querySelectorAll('.feed-card .src-row')].filter(visible).map(row => {
        const card = row.closest('.feed-card');
        const rr = row.getBoundingClientRect(), cr = (row.parentElement).getBoundingClientRect();
        const sep = [...row.querySelectorAll('[aria-hidden="true"]')].find(el => el.textContent.trim() === '·' && visible(el));
        let orphan = false;
        // The dot drawn before "when": visible only when it lands inside the row, so it must then sit between who and when.
        const when = row.querySelector('.src-when'), who = row.querySelector('.src-who');
        if (when && who) {
          const w = when.getBoundingClientRect(), o = who.getBoundingClientRect();
          const dot = parseFloat(getComputedStyle(when, '::before').width) || 0;
          const dotVisible = getComputedStyle(when, '::before').content !== 'none' && w.left - dot >= rr.left - 0.5;
          const sameLine = Math.abs((w.top + w.height / 2) - (o.top + o.height / 2)) < 6;
          orphan = dotVisible !== sameLine;
          // Picture and name always share a line.
          const av = who.querySelector('.src-av').getBoundingClientRect(), nm = who.querySelector('.src-name').getBoundingClientRect();
          if (Math.abs((av.top + av.height / 2) - (nm.top + nm.height / 2)) >= 6) orphan = true;
        }
        if (sep) {
          const s = sep.getBoundingClientRect();
          const sibs = [...row.querySelectorAll('time, .src-name')].filter(visible).map(e => e.getBoundingClientRect());
          orphan = !sibs.some(b => Math.abs((b.top + b.height / 2) - (s.top + s.height / 2)) < 6 && b.left > s.left)
            || !sibs.some(b => Math.abs((b.top + b.height / 2) - (s.top + s.height / 2)) < 6 && b.right < s.left);
        }
        const name = row.querySelector('.src-name');
        return { id: card.dataset.sid, variant: card.className.match(/card-(lead|std|wide|debate)/g)?.join(' '), photo: card.classList.contains('card-photo'),
          title: card.querySelector('.card-title')?.textContent.trim().slice(0, 60), width: Math.round(cr.width), lines: lines(row),
          orphanSep: orphan, overflow: rr.right > cr.right + 1 || [...row.children].some(c => visible(c) && c.getBoundingClientRect().right > cr.right + 1),
          nameShown: name ? Math.round(name.getBoundingClientRect().width) : null, nameFull: name ? Math.round(name.scrollWidth) : null,
          hasMt: !!row.querySelector('.mt') };
      });
      const ranked = [...document.querySelectorAll('.hot-row .hot-why, .pick-row .hot-why')].filter(visible).map(el => {
        const row = el.getBoundingClientRect();
        const parts = [...el.querySelectorAll('.why-part')];
        // A dot shows only between two facts on one line: visible iff this fact starts right of the row's left edge.
        const orphan = parts.slice(1).some(p => {
          const r = p.getBoundingClientRect(), dot = parseFloat(getComputedStyle(p, '::before').width) || 0;
          const shown = getComputedStyle(p, '::before').content !== 'none' && r.left - dot >= row.left - 0.5;
          const prev = parts[parts.indexOf(p) - 1].getBoundingClientRect();
          return shown !== (Math.abs(prev.bottom - r.bottom) < 6 && prev.right <= r.left);
        });
        return { orphan, text: el.textContent.slice(0, 60) };
      });
      // WCAG contrast of the tile's small text against what is drawn under it (a pill's fill lives on ::before).
      const cv = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
      const rgb = c => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = '#000'; cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); return [...cv.getImageData(0, 0, 1, 1).data]; };
      const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
      const ratio = (a, b) => { const [x, y] = [lum(rgb(a)), lum(rgb(b))].sort((p, q) => q - p); return +((x + 0.05) / (y + 0.05)).toFixed(2); };
      const bgOf = el => { for (let n = el; n; n = n.parentElement) { const b = getComputedStyle(n).backgroundColor; if (rgb(b)[3] > 0) return b; } return 'white'; };
      const pairs = [];
      const pair = (sel, under) => { const el = tile && tile.querySelector(sel); if (!el) return; const bg = under ? getComputedStyle(el.closest(under.el), under.pseudo).backgroundColor : bgOf(el); pairs.push({ sel, ratio: ratio(getComputedStyle(el).color, bg) }); };
      pair('.date-m'); pair('.event-left'); pair('.event-when'); pair('.tile-more');
      pair('.events .calbtn-g span', { el: '.calbtn-g', pseudo: '::before' }); pair('.events .calbtn-ics', { el: '.calbtn-ics', pseudo: '::before' });
      const picks = document.querySelector('#picks');
      return {
        overflow: document.documentElement.scrollWidth > innerWidth, scrollWidth: document.documentElement.scrollWidth,
        tile: tile ? { ...box(tile), events: [...tile.querySelectorAll('.events > li')].filter(visible).map(li => ({ ...box(li), text: li.textContent.replace(/\s+/g, ' ').trim().slice(0, 90) })) } : null,
        ctrls, small: ctrls.filter(c => c.h < 44 || c.w < 44), rows, ranked, contrast: pairs,
        picks: picks ? box(picks) : null,
        mollick: (() => { const c = [...document.querySelectorAll('.feed-card')].find(c => /Mollick/.test(c.querySelector('.src-name')?.textContent || '')); return c ? box(c) : null; })(),
      };
    });
    const name = `${tag}-${sc}-${width}-${theme}`;
    if (m.tile) {
      const top = Math.max(0, (sc.endsWith('-tab') || !m.picks || m.picks.h === 0 ? m.tile : m.picks).y - 8);
      await page.screenshot({ path: path.join(out, `${name}.png`), clip: { x: 0, y: top, width, height: Math.min(m.tile.bottom - top + 16, 4000) }, captureBeyondViewport: true });
    } else {
      await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: false });
    }
    if (sc === 'real') {
      // One of each other variant, for the source row and the ranked rows' Translated marker.
      for (const [label, sel] of [['wide', '.feed-card.card-wide'], ['debate', '.feed-card.card-debate'], ['ranked', '.tile-hot']]) {
        const el = await page.$(sel);
        if (el) { await el.scrollIntoView(); await new Promise(r => setTimeout(r, 150)); await el.screenshot({ path: path.join(out, `${tag}-${label}-${width}-${theme}.png`) }); }
      }
    }
    if (sc === 'real' && m.mollick) {
      await page.screenshot({ path: path.join(out, `${tag}-mollick-${width}-${theme}.png`), clip: { x: Math.max(0, m.mollick.x - 8), y: m.mollick.y - 8, width: Math.min(width, m.mollick.w + 16), height: m.mollick.h + 16 }, captureBeyondViewport: true });
    }
    const bad = m.rows.filter(r => r.orphanSep || r.overflow || r.lines > 2);
    const multi = m.rows.filter(r => r.lines > 1);
    summary.push({ name, overflow: m.overflow, tileH: m.tile && Math.round(m.tile.h), events: m.tile && m.tile.events.length, small: m.small.length,
      rows: m.rows.length, multiLine: multi.length, bad: bad.length, variants: [...new Set(m.rows.map(r => `${r.variant}${r.photo ? '+photo' : ''}`))].join('|'), ranked: m.ranked.length });
    if (m.overflow) problems.push(`${name}: horizontal overflow (${m.scrollWidth}px)`);
    for (const c of m.small) problems.push(`${name}: control under 44px ${c.cls} ${Math.round(c.w)}x${Math.round(c.h)}`);
    // On the phone the tile spans the column; a shrink-wrapped tile squeezes every event into a sliver.
    if (m.tile && width < 768 && m.tile.w < width - 64) problems.push(`${name}: tile is ${Math.round(m.tile.w)}px wide on a ${width}px screen`);
    for (const c of m.contrast) if (c.ratio < 4.5) problems.push(`${name}: contrast ${c.sel} ${c.ratio}:1`);
    if (process.argv.includes('--verbose')) console.log(name, 'contrast', JSON.stringify(m.contrast));
    for (const r of m.ranked.filter(r => r.orphan)) problems.push(`${name}: ranked row dot out of place "${r.text}"`);
    for (const r of bad) problems.push(`${name}: source row ${r.variant} "${r.title}" lines=${r.lines} orphanSep=${r.orphanSep} overflow=${r.overflow} width=${r.width}`);
    if (process.argv.includes('--verbose')) console.log(name, JSON.stringify(m.rows.filter(r => r.lines > 1).slice(0, 6)));
    await page.close();
  }
} finally {
  await browser.close();
}
console.table(summary);
await fs.writeFile(path.join(out, `${tag}-measure.json`), JSON.stringify({ summary, problems }, null, 2));
if (problems.length) { console.log(problems.join('\n')); if (strict) process.exitCode = 1; }
else console.log('No overflow, no control under 44px, no orphan separator, no source row over two lines.');

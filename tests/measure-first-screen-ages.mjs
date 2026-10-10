// How old are the stories a reader sees first? Opens the home, lists every story element in the first screen (and the
// whole top row and "Nhiều nguồn cùng đưa") with its age from the snapshot's generated_at.
// node tests/measure-first-screen-ages.mjs --url http://127.0.0.1:8814 [--snapshot path.json] [--label after] [--out dir]
// --snapshot serves that file in place of data/radar-ui.json inside the headless page only (e.g. the same snapshot
// re-scored by radar/worth.py), so the page under test and the scores can be varied independently.
import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const url = arg('--url', 'http://127.0.0.1:8814');
const snapshot = arg('--snapshot', '');
const label = arg('--label', 'run');
const out = arg('--out', 'plans/reports/tin-moi');
await fs.mkdir(out, { recursive: true });
const body = snapshot ? await fs.readFile(snapshot, 'utf8') : null;

const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--disable-gpu'] });
const result = {};
try {
  for (const [w, h] of [[375, 812], [1440, 900]]) {
    const page = await browser.newPage();
    await page.bringToFront();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.setRequestInterception(true);
    page.on('request', req => {
      if (body && req.url().includes('data/radar-ui.json')) return req.respond({ status: 200, contentType: 'application/json', body });
      req.continue();
    });
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#picks-grid .feed-card', { timeout: 20000 });
    await new Promise(r => setTimeout(r, 500));
    result[w] = await page.evaluate(() => {
      const gen = Date.parse(document.querySelector('#src-update time')?.getAttribute('datetime') || '');
      const age = el => { const t = el.querySelector('time[datetime]'); return t ? Math.round((gen - Date.parse(t.getAttribute('datetime'))) / 36e5 * 10) / 10 : null; };
      const title = el => (el.querySelector('.card-title, .hot-title, .event-name') || el).textContent.trim().replace(/\s+/g, ' ').slice(0, 70);
      const rows = sel => [...document.querySelectorAll(sel)].map(el => ({ id: el.dataset.sid, ageH: age(el), title: title(el) }));
      const firstScreen = [...document.querySelectorAll('#fresh-row li[data-sid], #picks-grid .feed-card[data-sid], #feed-grid .feed-card[data-sid]')]
        .filter(el => { const r = el.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0; })
        .map(el => ({ id: el.dataset.sid, where: el.closest('#fresh-row') ? 'Vừa đăng' : el.closest('#picks') ? 'Nhiều nguồn cùng đưa' : 'grid', ageH: age(el), title: title(el) }));
      return { newestRow: rows('#fresh-row li[data-sid]'), picks: rows('#picks-grid .feed-card[data-sid]'), firstScreen };
    });
    await page.close();
  }
} finally { await browser.close(); }
await fs.writeFile(path.join(out, `first-screen-${label}.json`), JSON.stringify(result, null, 2));
for (const [w, r] of Object.entries(result)) {
  console.log(`\n== ${label} ${w}px: first screen ==`);
  for (const s of r.firstScreen) console.log(`  ${String(s.ageH).padStart(5)} h  ${s.where.padEnd(22)} ${s.title}`);
  if (w === '1440') {
    console.log(`  Vừa đăng row: ${r.newestRow.map(s => s.ageH + 'h').join(', ') || '(none)'}`);
    console.log(`  Nhiều nguồn cùng đưa: ${r.picks.map(s => s.ageH + 'h').join(', ')}`);
  }
}

// Does any event appear twice among the row, the block and the rest of the first screen? Every signal is printed for
// each pair that shows one, so a reader can judge: pipeline identity (id, aliases), a shared article or discussion
// URL, and how many words of one headline appear across the other's coverage headlines.
const snap = body ? JSON.parse(body) : await (await fetch(`${url}/data/radar-ui.json`)).json();
const byId = new Map(snap.stories.map(s => [s.id, s]));
const STOP = new Set(('the and for with from that this its are was has have will into over after about says said than '
  + 'then what when your their they them how why who now new via').split(' '));
const words = t => String(t || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').split(/[^a-z0-9]+/).filter(x => x.length >= 3 && !STOP.has(x));
const covWords = s => new Set([s.title, ...(s.coverage || []).map(c => c.title)].flatMap(words));
const urls = s => new Set([s.url, ...(s.coverage || []).flatMap(c => [c.url, c.discussion_url])].filter(Boolean));
for (const [w, r] of Object.entries(result)) {
  const seen = new Map();
  for (const x of [...r.firstScreen, ...r.newestRow, ...r.picks]) if (!seen.has(x.id)) seen.set(x.id, x);
  const list = [...seen.values()].map(x => ({ ...x, st: byId.get(x.id) })).filter(x => x.st);
  const pairs = [];
  for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
    const a = list[i].st, b = list[j].st;
    const alias = (a.aliases || []).includes(b.id) || (b.aliases || []).includes(a.id);
    const ua = urls(a); const sharedUrl = [...urls(b)].some(u => ua.has(u));
    const A = covWords(a), B = covWords(b); let k = 0; A.forEach(x => { if (B.has(x)) k++; });
    const ratio = Math.round(k / Math.max(1, Math.min(A.size, B.size)) * 100) / 100;
    if (alias || sharedUrl || ratio >= 0.4) pairs.push({ a: `${list[i].where || ''} ${list[i].title}`, b: `${list[j].where || ''} ${list[j].title}`, alias, sharedUrl, words: k, ratio });
  }
  r.sameEventPairs = pairs;
  console.log(`\n== ${label} ${w}px: pairs that may be one event (row, block and first screen) ==`);
  if (!pairs.length) console.log('  none');
  for (const p of pairs) console.log(`  alias=${p.alias} url=${p.sharedUrl} words=${p.words} ratio=${p.ratio}\n    ${p.a}\n    ${p.b}`);
}
await fs.writeFile(path.join(out, `first-screen-${label}.json`), JSON.stringify(result, null, 2));
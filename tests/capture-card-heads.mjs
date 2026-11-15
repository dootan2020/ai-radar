// The front page's card headers ("Vừa đăng", the weather, "Chuyện lớn", "Sắp diễn ra", the calendar band, "Đáng chú ý") in Chrome
// against a server for this worktree: each header's height and its distance from its card's top edge, where its label
// text starts, where the content under it starts, and whether the page scrolls sideways. Screenshots of the "Hôm nay"
// and "Điểm nhấn" bands at each width.
// node tests/capture-card-heads.mjs --url http://127.0.0.1:8836 --out plans/reports/tieu-de-the --tag after [--snapshot file.json]
// --snapshot serves that radar-ui.json instead of the server's (inside the headless page only; no data file is touched).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
};
const url = arg('--url', 'http://127.0.0.1:8836');
const out = arg('--out', 'plans/reports/tieu-de-the');
const tag = arg('--tag', 'after');
const snapshotFile = arg('--snapshot', '');
const widths = arg('--widths', '375,768,1100,1440,1780,2000').split(',').map(Number);
const shots = new Set(arg('--shots', '375,1440,1780').split(',').map(Number));
await fs.mkdir(out, { recursive: true });

for (const file of ['index.html', 'feed.css', 'trang-msn.css', 'tokens.css', 'feed.js']) {
  const r = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(r.status, 200, file);
  assert.equal(await r.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), `${file} served by ${url} is not this worktree's`);
}
const snapshot = snapshotFile ? await fs.readFile(snapshotFile, 'utf8') : '';

const HEADS = [
  ['Vừa đăng', '#fresh-row', '.tile-head', '.tile-title', '.fresh-list'],
  ['Thời tiết', '.msn-wx', '.wx-head', '.wx-city', '.wx-body'],
  ['Chuyện lớn', '#top-list', 'h2', 'h2', 'ol'],
  ['Sắp diễn ra', '#su-kien', '.ev-head', 'h2', '.ev-head + *'],
  ['Lịch', '#the-lich', '.cal-band', '.cal-band span', '.cal-hero'],
  ['Đáng chú ý', '.band-focus .nc-wide', '.nc-kicker', '.nc-kicker', '.nc-meta'],
];

const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true, args: ['--disable-gpu'],
  userDataDir: await fs.mkdtemp(path.join(os.tmpdir(), 'card-heads-')), timeout: 15000,
});
console.log(`Chrome PID ${browser.process().pid}; server ${url}`);
const report = [];
try {
  for (const width of widths) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: 1000, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.evaluateOnNewDocument(() => { localStorage.setItem('air2:theme', JSON.stringify('light')); });
    if (snapshot) {
      await page.setRequestInterception(true);
      page.on('request', req => req.url().includes('data/radar-ui.json')
        ? req.respond({ status: 200, contentType: 'application/json', body: snapshot }) : req.continue());
    }
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#top-list h2', { timeout: 20000 });
    await page.waitForSelector('#the-lich .cal-band', { timeout: 20000 });
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(async () => {
      const imgs = [...document.querySelectorAll('.band img')];
      imgs.forEach(img => { img.loading = 'eager'; });
      await Promise.all(imgs.map(img => img.decode().catch(() => {})));
      await Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})));
    });
    await new Promise(r => setTimeout(r, 400));
    const m = await page.evaluate(HEADS => {
      const row = HEADS.map(([name, card, head, label, next]) => {
        const c = document.querySelector(card);
        const h = c && c.querySelector(head);
        if (!c || !h || !h.getClientRects().length) return { name, missing: true };
        const cr = c.getBoundingClientRect(), hr = h.getBoundingClientRect();
        const l = h.matches(label) ? h : h.querySelector(label);
        const lr = l.getBoundingClientRect();
        // The label's ink: the text box of its first text run (a line box, not the padded element).
        const range = document.createRange();
        const textNode = [...l.childNodes].find(n => n.nodeType === 3 && n.textContent.trim()) || l.querySelector('span')?.firstChild || l.firstChild;
        range.selectNodeContents(textNode);
        const tr = range.getBoundingClientRect();
        const n = c.querySelector(`${head} ~ ${next}`) || c.querySelector(next);
        const nr = n && n.getBoundingClientRect();
        return {
          name, cardTop: Math.round(cr.top + scrollY), cardH: Math.round(cr.height),
          headTop: +(hr.top - cr.top).toFixed(1), headH: +hr.height.toFixed(1),
          textTop: +(tr.top - cr.top).toFixed(1), textLeft: +(tr.left - cr.left).toFixed(1), textH: +tr.height.toFixed(1),
          labelSize: getComputedStyle(l).fontSize,
          contentTop: nr ? +(nr.top - cr.top).toFixed(1) : null,
          gapBelow: nr ? +(nr.top - hr.bottom).toFixed(1) : null,
        };
      });
      return { row, scrollW: document.documentElement.scrollWidth, innerW: innerWidth };
    }, HEADS);
    report.push({ width, ...m });
    console.log(`\n${width}px  scrollWidth ${m.scrollW} / ${m.innerW}${m.scrollW > m.innerW ? '  HORIZONTAL SCROLL' : ''}`);
    for (const r of m.row) {
      console.log(r.missing ? `  ${r.name}: not shown` :
        `  ${r.name.padEnd(12)} card@${r.cardTop} head top ${r.headTop} h ${r.headH} | text top ${r.textTop} left ${r.textLeft} (${r.labelSize}) | content top ${r.contentTop} gap ${r.gapBelow}`);
    }
    if (shots.has(width)) {
      for (const band of ['band-today', 'band-focus']) {
        const el = await page.$(`.${band}`);
        if (el) await el.screenshot({ path: path.join(out, `${tag}-${band}-${width}.png`) });
      }
    }
    await page.close();
  }
  await fs.writeFile(path.join(out, `${tag}-measure.json`), JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}

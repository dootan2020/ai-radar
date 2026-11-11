// The front page's story cards on a phone, rendered in headless Chrome from site/ and measured, plus desktop widths
// to show they are untouched.
//   node tests/capture-mobile-the-tin.mjs [--data <dir>] [--out <dir>] [--tag <prefix>] [--site <dir>] [--only <width>]
// <dir> holds a downloaded radar-window.json, radar-ui.json and field-rankings.json (the live snapshot). Without
// --data the page reads tests/fixtures/radar-window-sample.json offline (every other data file answers 404); this is
// how tests/test_mobile_the_tin.py runs it. Phone widths are emulated as a touch phone (isMobile, hasTouch).
// With --out: 375 light and dark full pages, 320 and 414 first two screens, 1440 and 2000 first screen.
// One JSON line on stdout: per width, sideways scroll, text under 12px, tap targets under 44px, each story card's
// grid boxes (source, headline, picture, time), the "Chuyện lớn" cards, the panel and the page's layout shift.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = arg('--out', '');
const tag = arg('--tag', '');
const dataDir = arg('--data', '');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const siteDir = path.resolve(arg('--site', path.join(root, 'site')));
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
const executablePath = (await Promise.all(CHROME.map(p => fs.access(p).then(() => p, () => null)))).find(Boolean);
if (out) await fs.mkdir(out, { recursive: true });

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    let file;
    if (!dataDir && /^\/data\/radar(-window)?\.json$/.test(p)) file = path.join(root, 'tests/fixtures/radar-window-sample.json');
    else if (!dataDir && p.startsWith('/data/')) { res.writeHead(404); return res.end(); }
    else if (p.startsWith('/data/')) file = path.join(dataDir, path.basename(p));
    else if (p.startsWith('/nen/')) { res.writeHead(404); return res.end(); }
    else {
      file = path.join(siteDir, p.endsWith('/') ? p + 'index.html' : p);
      if (!file.startsWith(siteDir)) throw new Error('outside');
    }
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const site = `http://127.0.0.1:${server.address().port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const stand = await fs.readFile(path.join(root, 'site/og-image.png'));

const EARLY = () => {
  window.__shift = 0;
  new PerformanceObserver(list => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__shift += e.value; })
    .observe({ type: 'layout-shift', buffered: true });
};

const MEASURE = () => {
  const r = el => el.getBoundingClientRect();
  const shown = el => { const b = r(el); const s = getComputedStyle(el); return b.width > 0 && b.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const box = el => { const b = r(el); return { x: Math.round(b.left), y: Math.round(b.top + scrollY), w: Math.round(b.width), h: Math.round(b.height) }; };
  const grid = document.querySelector('#feed-grid');
  const small = [];
  for (const el of document.querySelectorAll('#feed-grid *, #bar *, .mobile-nav *')) {
    if (!shown(el)) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (own && parseFloat(getComputedStyle(el).fontSize) < 12) small.push({ cls: String(el.className).slice(0, 40), text: el.textContent.trim().slice(0, 24), font: getComputedStyle(el).fontSize });
  }
  const targets = [...document.querySelectorAll('#feed-grid a[href], #feed-grid button, .mobile-nav a, #bar a, #bar button')].filter(shown)
    .map(el => ({ el, b: r(el) })).filter(({ b }) => b.width < 44 || b.height < 44)
    .map(({ el, b }) => ({ cls: String(el.className).slice(0, 40), text: (el.getAttribute('aria-label') || el.textContent).trim().slice(0, 24), w: Math.round(b.width), h: Math.round(b.height) }));
  const part = (el, sel) => { const x = el.querySelector(sel); return x && shown(x) ? box(x) : null; };
  const cards = [...document.querySelectorAll('#feed-grid .band .nc')].filter(shown).map(el => {
    const img = el.querySelector('.nc-photo img');
    const s = getComputedStyle(el), photo = el.querySelector('.nc-photo');
    return { cls: String(el.className), ...box(el), display: s.display, radius: s.borderRadius, border: s.borderTopWidth + ' ' + s.borderTopStyle,
      pad: s.paddingLeft, title: el.querySelector('.nc-title')?.textContent.trim().slice(0, 40) || null,
      titleFont: el.querySelector('.nc-title') ? getComputedStyle(el.querySelector('.nc-title')).fontSize : null,
      titleBox: part(el, '.nc-title'), who: part(el, '.nc-who'), when: part(el, '.nc-when'), sum: part(el, '.nc-sum'),
      pic: photo && shown(photo) ? { ...box(photo), radius: getComputedStyle(photo).borderRadius } : null,
      img: img ? { loading: img.loading, src: img.getAttribute('src'), waiting: img.hasAttribute('data-src') || img.hasAttribute('data-srcset') } : null };
  });
  const top = [...document.querySelectorAll('#feed-grid .band .msn-toplist li')].filter(shown).map(li => {
    const s = getComputedStyle(li), num = li.querySelector(':scope > b');
    return { ...box(li), display: s.display, radius: s.borderRadius, bg: s.backgroundColor, num: num ? { ...box(num), font: getComputedStyle(num).fontSize } : null,
      titleBox: part(li, '.top-title'), src: part(li, '.top-src'), time: part(li, 'time') };
  });
  const panel = document.querySelector('.feed-main.front.msn-panel');
  const sections = grid ? [...grid.children].filter(shown).map(el => ({ tag: el.tagName.toLowerCase(), cls: String(el.className).slice(0, 60), id: el.id || null, ...box(el) })) : [];
  return {
    width: innerWidth, sideways: document.scrollingElement.scrollWidth > innerWidth, scrollWidth: document.scrollingElement.scrollWidth,
    height: document.scrollingElement.scrollHeight, canvas: getComputedStyle(document.body).backgroundColor,
    small: small.slice(0, 20), smallCount: small.length, targets: targets.slice(0, 20), targetCount: targets.length,
    sections: sections.slice(0, 30), cards, top, screen: innerHeight,
    panel: panel && { ...box(panel), radius: getComputedStyle(panel).borderRadius, pad: getComputedStyle(panel).paddingLeft },
    countdown: (el => el && { text: el.textContent.trim(), ...box(el), font: getComputedStyle(el).fontSize, color: getComputedStyle(el).color, opacity: getComputedStyle(el).opacity })(document.querySelector('#feed-grid .ev-n')),
    shift: Math.round((window.__shift || 0) * 1000) / 1000,
  };
};

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'mobile-the-tin-'));
const browser = await puppeteer.launch({ executablePath, headless: true, pipe: true, userDataDir: profile,
  args: ['--disable-gpu', '--hide-scrollbars'], timeout: 20000 });
const result = { chrome: browser.process()?.pid ?? null, runs: {}, errors: [] };

async function open(ctx, width, theme, dpr) {
  const page = await ctx.newPage();
  const phone = width < 768;
  await page.setViewport({ width, height: phone ? 812 : 900, deviceScaleFactor: dpr, isMobile: phone, hasTouch: phone });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument(t => { try { localStorage.setItem('air2:theme', JSON.stringify(t)); } catch {} }, theme);
  await page.evaluateOnNewDocument(EARLY);
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = req.url();
    const picture = req.resourceType() === 'image' && u.startsWith('https://');
    // Offline (the fixture), every publisher picture is answered with site/og-image.png, so cards keep their pictures.
    if (picture && !dataDir) return req.respond({ status: 200, contentType: 'image/png', body: stand });
    return u.startsWith(site) || u.startsWith('data:') || picture ? req.continue() : req.abort();
  });
  page.on('pageerror', e => result.errors.push(`${width}: ${e.message}`));
  await page.goto(site, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true' && document.querySelector('#feed-grid > *'), { timeout: 30000 });
  await page.evaluate(() => document.fonts.ready);
  await wait(1200);
  return page;
}

// Scrolls through the page so lazy pictures load before a full-page shot, then returns to the top.
async function wake(page) {
  await page.evaluate(async () => {
    const step = innerHeight * 0.8;
    for (let y = 0; y < document.scrollingElement.scrollHeight; y += step) { scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); }
    scrollTo(0, 0);
  });
  await wait(1500);
}

const only = arg('--only', '');   // e.g. "375": capture that width alone
const plan = [[375, 'light', 'full'], [375, 'dark', 'full'], [320, 'light', 'two'], [414, 'light', 'two'], [1440, 'light', 'one'], [2000, 'light', 'one']];
try {
  for (const [width, theme, kind] of plan.filter(([w]) => !only || String(w) === only)) {
    const ctx = await browser.createBrowserContext();
    // A full phone page is shot at 1x: at 2x it passes Chrome's 16384 px texture limit and big composited layers go missing.
    const page = await open(ctx, width, theme, kind === 'two' ? 2 : 1);
    const key = `${width}${theme === 'dark' ? '-toi' : ''}`;
    result.runs[key] = await page.evaluate(MEASURE);
    if (out) {
      const file = path.join(out, `${tag}${key}.png`);
      if (kind === 'full') {
        // A viewport as tall as the page instead of fullPage: Chrome's full-page capture of an emulated phone measured
        // the cards' container units against the wrong box (pictures drawn at 80 px where the screen shows 99).
        await wake(page);
        const tall = await page.evaluate(() => document.scrollingElement.scrollHeight);
        await page.setViewport({ width, height: tall, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
        await wait(1200);
        result.runs[key].fullPic = await page.evaluate(() => [...document.querySelectorAll('#feed-grid .band .nc:not(.nc-wide) .nc-photo')].slice(0, 3).map(el => Math.round(el.getBoundingClientRect().width)));
        await page.screenshot({ path: file });
      }
      else if (kind === 'two') {
        // The first two screens as a reader sees them, one viewport each.
        await wake(page);
        await page.screenshot({ path: file.replace(/\.png$/, '-1.png') });
        await page.evaluate(() => scrollTo(0, innerHeight));
        await wait(900);
        await page.screenshot({ path: file.replace(/\.png$/, '-2.png') });
      } else await page.screenshot({ path: file });
    }
    await ctx.close();
  }
} catch (e) {
  result.errors.push(String(e && e.stack || e));
} finally {
  await browser.close();
  server.close();
  await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
}
process.stdout.write(JSON.stringify(result) + '\n');

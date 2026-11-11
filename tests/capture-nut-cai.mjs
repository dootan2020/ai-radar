// The extension's invitation (thanh-tren.js startOffer), in Chrome against this worktree: the home at 1440x900 and
// 2000x1100 in light and dark with the tile beside "Tùy chỉnh", "Tùy chỉnh" open with its permanent line, 1280 (the line
// only), 375 on a phone (nothing), a browser without Chromium's userAgentData (nothing), and × hiding the tile for good.
// node tests/capture-nut-cai.mjs --out nut-cai-anh [--port 8794]
// Same server as tests/capture-thanh-tren.mjs: site/ from disk, every data/*.json is tests/fixtures/radar-window-sample.json,
// nen/* from the live site (else the packaged picture). Nothing under site/ is written. Prints one JSON line last.
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
const out = path.resolve(root, arg('--out', 'nut-cai-anh'));
const port = Number(arg('--port', '8794'));
const LIVE = 'https://radar-ai-vn.pages.dev/';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
await fs.mkdir(out, { recursive: true });

const full = JSON.parse(await fs.readFile(path.join(root, 'tests/fixtures/radar-window-sample.json'), 'utf8'));
const packaged = await fs.readFile(path.join(root, 'site/anh/nen-du-phong.webp'));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  try {
    if (p.startsWith('/nen/')) {
      try {
        const live = await fetch(LIVE + p.slice(1), { signal: AbortSignal.timeout(10000) });
        if (!live.ok) throw new Error(String(live.status));
        res.writeHead(200, { 'content-type': live.headers.get('content-type') || TYPES[path.extname(p)] });
        return res.end(Buffer.from(await live.arrayBuffer()));
      } catch {
        if (p.endsWith('lich.json')) { res.writeHead(404); return res.end(); }
        res.writeHead(200, { 'content-type': 'image/webp' }); return res.end(packaged);
      }
    }
    if (/^\/data\/[\w.-]+\.json$/.test(p)) { res.writeHead(200, { 'content-type': TYPES['.json'] }); return res.end(JSON.stringify(full)); }
    const file = path.join(root, 'site', p.endsWith('/') ? p + 'index.html' : p);
    if (!file.startsWith(path.join(root, 'site'))) throw new Error('outside');
    const body = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
const url = `http://127.0.0.1:${port}/`;
const wait = ms => new Promise(r => setTimeout(r, ms));
const results = {}, problems = [];
console.log(`server ${url}; out ${out}`);

const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'nut-cai-'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, pipe: true, userDataDir: profile,
  args: ['--disable-gpu'], timeout: 20000 });
console.log(`Chrome PID ${browser.process().pid}`);
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36';
const PHONE_UA = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36';
const meta = mobile => ({ brands: [{ brand: 'Chromium', version: '142' }, { brand: 'Google Chrome', version: '142' }],
  fullVersion: '142.0.0.0', platform: mobile ? 'Android' : 'Windows', platformVersion: '15.0.0', architecture: mobile ? '' : 'x86',
  model: '', mobile });

// kind: 'chromium' (desktop Chrome), 'phone' (Chrome on Android), 'other' (no userAgentData: Firefox, Safari)
async function open(width, height, theme, kind = 'chromium', hidden = false, settings = null) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.bringToFront();   // a background tab holds its transitions, and the tile fades in
  const touch = kind === 'phone';
  await page.setViewport({ width, height, deviceScaleFactor: 1, hasTouch: touch, isMobile: touch });
  if (kind === 'other') await page.evaluateOnNewDocument(() => Object.defineProperty(Navigator.prototype, 'userAgentData', { get: () => undefined }));
  else await page.setUserAgent({ userAgent: touch ? PHONE_UA : UA, userAgentMetadata: meta(touch) });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }, { name: 'prefers-color-scheme', value: theme }]);
  await page.evaluateOnNewDocument((t, seen, h, s) => {
    localStorage.setItem('air2:theme', JSON.stringify(t));
    localStorage.setItem('air2:lastSeen', JSON.stringify(seen));
    if (s) localStorage.setItem('halcyon:tuy-chinh', JSON.stringify(s)); else localStorage.removeItem('halcyon:tuy-chinh');
    if (h) localStorage.setItem('halcyon:cai-tien-ich', 'an');
  }, theme, full.generated_at, hidden, settings);
  page.on('pageerror', e => problems.push(`page error at ${width}px: ${e.message}`));
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('#top')?.getAttribute('aria-busy') !== 'true', { timeout: 20000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => document.querySelector('#nen')?.classList.contains('is-ready') || innerWidth < 768, { timeout: 15000 }).catch(() => {});
  await page.waitForSelector('#tuy-chinh', { timeout: 10000 }).catch(() => problems.push(`${width}px: "Tùy chỉnh" never drawn`));
  await wait(700);
  return { page, ctx };
}

const measure = page => page.evaluate(() => {
  const r = s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return { l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right), b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height) }; };
  const tile = r('.cai-offer'), search = r('.msn-top .ns-field'), tune = r('#tc-open');
  const go = document.querySelector('.cai-go');
  return { tile, search, tune, x: r('.cai-x'), row: !!document.querySelector('.tc-ext-go'),
    href: go?.getAttribute('href') ?? null, target: go?.getAttribute('target') ?? null,
    gapToSearch: tile && search ? tile.l - search.r : null, sameTop: tile && tune ? tile.t === tune.t && tile.h === tune.h : null,
    text: go ? getComputedStyle(go).fontSize : null, visible: document.visibilityState,
    opacity: document.querySelector('.cai-offer') ? getComputedStyle(document.querySelector('.cai-offer')).opacity : null, overflow: document.documentElement.scrollWidth > innerWidth };
});

async function shot(name, width, height, theme, kind, opts = {}) {
  const { page, ctx } = await open(width, height, theme, kind, opts.hidden, opts.settings);
  if (opts.sheet) { await page.click('#tc-open'); await wait(400); }
  const m = await measure(page);
  results[name] = m;
  // captureBeyondViewport would resize the page for the shot, re-matching the tile's media query and catching its fade-in
  await page.screenshot({ path: path.join(out, `${name}.png`), captureBeyondViewport: false,
    clip: opts.clip ? { x: 0, y: 0, width, height: opts.clip } : undefined });
  await ctx.close();
  return m;
}

await shot('1440-light', 1440, 900, 'light');
await shot('1440-dark', 1440, 900, 'dark');
await shot('2000-light', 2000, 1100, 'light');
await shot('2000-dark', 2000, 1100, 'dark');
await shot('1440-light-top', 1440, 900, 'light', 'chromium', { clip: 140 });
await shot('1440-dark-tuy-chinh', 1440, 900, 'dark', 'chromium', { sheet: true });
await shot('1366-light-top', 1366, 768, 'light', 'chromium', { clip: 140 });
await shot('1440-light-no-picture', 1440, 900, 'light', 'chromium', { settings: { layout: 'full', picture: false, weather: true }, clip: 140 });
await shot('1280-light-tuy-chinh', 1280, 800, 'light', 'chromium', { sheet: true });
await shot('375-light', 375, 812, 'light', 'phone');
await shot('1440-other-browser', 1440, 900, 'light', 'other', { sheet: true });

// × puts the tile away, and a reload keeps it away; the line in "Tùy chỉnh" stays.
{
  const { page, ctx } = await open(1440, 900, 'light');
  await page.click('.cai-x');
  await wait(300);
  const afterClick = await page.evaluate(() => ({ tile: !!document.querySelector('.cai-offer'), saved: localStorage.getItem('halcyon:cai-tien-ich'),
    focus: document.activeElement?.id ?? null }));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#tuy-chinh', { timeout: 10000 });
  await wait(500);
  const afterReload = await page.evaluate(() => ({ tile: !!document.querySelector('.cai-offer'), row: !!document.querySelector('.tc-ext-go') }));
  results.dismiss = { afterClick, afterReload };
  await ctx.close();
}

// /cai-dat/ forwards to the Store after its load event (the request is stopped there, nothing leaves for Google).
{
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setRequestInterception(true);
  let forwarded = null;
  page.on('request', req => {
    if (req.url().startsWith('https://chromewebstore.google.com/')) { forwarded = req.url(); req.abort(); } else req.continue();
  });
  await page.goto(url + 'cai-dat/', { waitUntil: 'load' }).catch(() => {});
  for (let i = 0; i < 20 && !forwarded; i++) await wait(100);
  results.forward = forwarded;
  await ctx.close();
}

await browser.close();
await new Promise(r => server.close(r));
await fs.rm(profile, { recursive: true, force: true }).catch(() => {});
console.log(JSON.stringify({ results, problems }));

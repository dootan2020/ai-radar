#!/usr/bin/env node
// quay-repo: the pages of a public GitHub repo (home, opened folders, opened files) -> one tall desktop still per page and quay.json.
// It reads github.com signed out as a desktop visitor (owner, 20/11/2026: a repo is never used on a phone, and a desktop page fits the phone safe area better). and records what the page lists (rows by address, their rectangles, the
// first code lines) so halcyon_quay.py can compare the picture with GitHub's own listing. No sign-in, no token, no CAPTCHA.
// Usage and refusals: QUAY.md is slice 4; the design is plans/reports/kongming-261120-0830-quay-repo-github.md section 2.
//   node video/halcyon/quay-repo.mjs --cay <cay.json> --ref <name> --out <folder> [--base https://github.com] [--timeout 45] [--gap 0.8]
// cay.json is written by `halcyon_quay.py cay` (repo, branch, commit, the pages to open in order).
// Writes <out>/<ref>/<n>.png and <out>/<ref>/quay.json. Exit 0 = captured, 1 = refused (`quay: <address>: <kind>: <why>`, nothing written), 2 = bad arguments.
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { INK_MARGIN, DECLINE, wallScan, bangkokStamp } from './chup.mjs';

export const VIEW_W = 1280, VIEW_H = 800, SCALE = 2;   // 2560 px wide stills
const INK_X0 = 80, INK_X1 = 2480;                     // the builder's ink definition (chup.mjs), over the middle of a 2560 px still

export const MAX_LOADS = 6;          // page loads per repo, retries included
export const MAX_CSS_H = 5000;       // 10000 device px, under Chrome's 16384 px limit
const RETRY_AFTER_CAP = 30;

class Refusal extends Error {
  constructor(kind, msg, retry = false) { super(msg); this.kind = kind; this.retry = retry; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- pure helpers (also used by the tests)
export function pageAddress(base, repo, branch, page) {
  const enc = (p) => p.split('/').map(encodeURIComponent).join('/');
  if (page.kind === 'home') return `${base}/${repo}`;
  return `${base}/${repo}/${page.kind === 'tree' ? 'tree' : 'blob'}/${enc(branch)}/${enc(page.path)}`;
}
export function luminance(rgb) {      // "rgb(255, 255, 255)" or "rgba(r, g, b, a)" -> 0..1; null when transparent or unreadable
  const m = /rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)(?:[ ,/]+([\d.]+))?/.exec(rgb || '');
  if (!m) return null;
  if (m[4] !== undefined && Number(m[4]) === 0) return null;
  return (0.2126 * Number(m[1]) + 0.7152 * Number(m[2]) + 0.0722 * Number(m[3])) / 255;
}
export function sameRepo(a, b) { return a.toLowerCase() === b.toLowerCase(); }

// ---------------------------------------------------------------- code that runs inside the page
// Only position:fixed is hidden (a loading bar, a pinned banner). Sticky stays: GitHub's own "Files" panel and README tab bar are part of
// the page a visitor sees, and hiding the panel would blank 321 px of every folder and file page.
const hideFixedOnly = () => { for (const e of document.querySelectorAll('*')) if (getComputedStyle(e).position === 'fixed') e.style.visibility = 'hidden'; };

// The builder's ink definition (chup.mjs inkRows) over the 2560 px still: luminance more than INK_MARGIN from the most common one.
async function inkMeasure(ctx, buf) {
  const p = await ctx.newPage();
  try {
    return await p.evaluate(async ([b64, m, x0, x1]) => {
      const bmp = await createImageBitmap(await (await fetch('data:image/png;base64,' + b64)).blob());
      const cv = new OffscreenCanvas(bmp.width, bmp.height); const g = cv.getContext('2d'); g.drawImage(bmp, 0, 0);
      const d = g.getImageData(0, 0, bmp.width, bmp.height).data; const W = bmp.width, H = bmp.height;
      const lum = new Uint8Array(W * H); const hist = new Array(256).fill(0);
      for (let i = 0; i < W * H; i++) { const L = (d[i * 4] * 19595 + d[i * 4 + 1] * 38470 + d[i * 4 + 2] * 7471 + 0x8000) >> 16; lum[i] = L; hist[L]++; }
      let bg = 0; for (let v = 1; v < 256; v++) if (hist[v] > hist[bg]) bg = v;
      let ink = 0; const xe = Math.min(x1, W);
      for (let y = 0; y < H; y++) for (let x = x0; x < xe; x++) if (Math.abs(lum[y * W + x] - bg) > m) ink++;
      return { w: W, h: H, ratio: ink / (H * (xe - x0)) };
    }, [buf.toString('base64'), INK_MARGIN, INK_X0, INK_X1]);
  } finally { await p.close().catch(() => {}); }
}

function pageBackground() {
  for (const e of [document.body, document.documentElement]) {
    const c = getComputedStyle(e).backgroundColor;
    if (c && c !== 'transparent' && !/rgba\([^)]*,\s*0\)$/.test(c)) return c;
  }
  return 'rgb(255, 255, 255)';
}

// The rows of the file listing. A row is an anchor whose address is /<owner>/<repo>/(tree|blob)/<branch>/<path> with <path> directly under
// this folder, and whose own text is that path (a single-child chain shows "a/b" and links to the deepest folder). Anchors inside the
// README (article), the header, the footer and navigation never count; of the tables left, the one holding most such anchors is the listing.
function listingScan({ repo, branch, folder }) {
  const [o, r] = repo.split('/');
  const prefix = `/${o}/${r}/`.toLowerCase();
  const vis = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && (!e.checkVisibility || e.checkVisibility()); };
  const strip = (s) => s.replace(/\s+/g, '');
  const base = folder ? folder + '/' : '';
  const cands = []; const ignored = { article: 0, chrome: 0, hidden: 0, notChild: 0 };
  for (const a of document.querySelectorAll('a[href]')) {
    let u; try { u = new URL(a.getAttribute('href'), location.href); } catch { continue; }
    if (u.origin !== location.origin) continue;
    let p; try { p = decodeURIComponent(u.pathname); } catch { continue; }
    if (!p.toLowerCase().startsWith(prefix)) continue;
    const m = /^(tree|blob)\/(.+)$/.exec(p.slice(prefix.length));
    if (!m || !m[2].startsWith(branch + '/')) continue;
    const rel = m[2].slice(branch.length + 1);
    if (a.closest('article, .markdown-body')) { ignored.article++; continue; }
    if (a.closest('header, nav, footer, [role=navigation]')) { ignored.chrome++; continue; }
    if (!vis(a)) { ignored.hidden++; continue; }
    if (!rel.startsWith(base) || rel === folder) { ignored.notChild++; continue; }
    const below = rel.slice(base.length);
    if (strip(a.textContent) !== strip(below)) { ignored.notChild++; continue; }
    cands.push({ a, rel, kind: m[1], below, table: a.closest('table') });
  }
  const groups = new Map();
  for (const c of cands) { const g = groups.get(c.table) || new Map(); if (!g.has(c.rel)) g.set(c.rel, c); groups.set(c.table, g); }
  let best = null;
  // The listing is a table; the left "Files" tree panel is a list and can show the same names, so it only counts when no table matches.
  for (const [t, g] of groups) if (t && (!best || g.size > best.g.size)) best = { t, g };
  if (!best) for (const [t, g] of groups) if (!best || g.size > best.g.size) best = { t, g };
  const R = (e) => { const b = e.getBoundingClientRect(); return [Math.round(b.left + scrollX), Math.round(b.top + scrollY), Math.round(b.width), Math.round(b.height)]; };
  const rows = best ? [...best.g.values()].map((c) => {
    const el = c.a.closest('tr') || c.a.closest('li, [role=row]') || c.a;
    return { name: c.below, path: c.rel, kind: c.kind, rect: R(el), name_rect: R(c.a), font_px: parseFloat(getComputedStyle(c.a).fontSize) };
  }) : [];
  const other = [...groups.entries()].filter(([t]) => !best || t !== best.t).reduce((n, [, g]) => n + g.size, 0);
  return { rows, ignored: { ...ignored, other_tables: other }, in_table: !!(best && best.t), file_list: best && best.t ? R(best.t) : null };
}

// The boxes a camera can aim at: README body and the About sidebar (home), whichever is visible.
function boxScan() {
  const vis = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && (!e.checkVisibility || e.checkVisibility()); };
  const R = (e) => { const b = e.getBoundingClientRect(); return [Math.round(b.left + scrollX), Math.round(b.top + scrollY), Math.round(b.width), Math.round(b.height)]; };
  const md = [...document.querySelectorAll('article.markdown-body')].find(vis);
  const h2 = [...document.querySelectorAll('h2')].find((h) => /^about$/i.test(h.textContent.trim()) && vis(h));
  const about = h2 ? (h2.closest('div[class*="sidebarSection"]') || h2.parentElement) : null;
  const body = md ? ([...md.querySelectorAll('p, li')].find(vis) || md) : null;      // the size of README text: the first visible paragraph or list item
  return { readme: md ? R(md) : null, about: about && vis(about) ? R(about) : null, readme_font: body ? parseFloat(getComputedStyle(body).fontSize) : null };
}

// A file page: the code lines are drawn from the data-code-text attribute (textContent is empty), and only a window of lines exists.
function fileScan() {
  const lineEls = [...document.querySelectorAll('[id^="LC"]')].filter((e) => /^LC\d+$/.test(e.id));
  // At 1280 px the lines are plain text nodes; a virtualized page (and the 390 px layout) draws them from a data-code-text attribute instead.
  const text = (e) => { const leaf = [...e.querySelectorAll('[data-code-text]')].filter((s) => !s.querySelector('[data-code-text]')); return leaf.length ? leaf.map((s) => s.getAttribute('data-code-text')).join('') : e.textContent; };
  const byNo = new Map(lineEls.map((e) => [Number(e.id.slice(2)), e]));
  const lines = [];
  for (let n = 1; n <= 40 && byNo.has(n); n++) lines.push(text(byNo.get(n)));
  const code = lineEls.length > 0 || !!document.querySelector('[data-code-text], #read-only-cursor-text-area, [data-testid="code-lines-container"]');
  const md = !!document.querySelector('article.markdown-body');
  let box = null;
  if (lines.length) {
    const first = byNo.get(1).getBoundingClientRect(), last = byNo.get(lines.length).getBoundingClientRect();
    box = [Math.round(first.left + scrollX), Math.round(first.top + scrollY), Math.round(Math.min(first.right, innerWidth) - first.left), Math.round(last.bottom - first.top)];
  }
  const code_font = lines.length ? parseFloat(getComputedStyle(byNo.get(1)).fontSize) : null;
  return { kind: code ? 'code' : md ? 'markdown' : 'other', code_lines: lines, rendered_lines: lineEls.length, code_box: box, code_font };
}

async function waitImages(page) {
  await page.evaluate(() => Promise.race([
    Promise.all([...document.images].filter((i) => !i.complete).map((i) => new Promise((r) => { i.addEventListener('load', r, { once: true }); i.addEventListener('error', r, { once: true }); }))),
    new Promise((r) => setTimeout(r, 5000)),
  ]));
}

// ---------------------------------------------------------------- one page
async function capturePage(ctx, page, o, cay, entry, state) {
  const url = pageAddress(o.base, cay.repo, cay.branch, entry);
  const t0 = Date.now();
  const refuse = (kind, msg, retry = false) => { const r = new Refusal(kind, msg, retry); r.address = url; return r; };
  const gap = state.last ? Math.max(0, o.gap * 1000 - (Date.now() - state.last)) : 0;
  if (gap) await sleep(gap);
  if (state.loads >= MAX_LOADS) throw refuse('rate-limit', `this repo has used its ${MAX_LOADS} page loads (retries count); not loading more`);
  state.loads++; state.last = Date.now();
  const resp = await page.goto(url, { waitUntil: 'load', timeout: o.timeout * 1000 - 5000 });
  const status = resp ? resp.status() : null;
  if (status === 429) {
    const ra = Math.min(RETRY_AFTER_CAP, Number((resp.headers()['retry-after'] || '5')) || 5);
    if (state.waited429) throw refuse('rate-limit', 'HTTP 429 again after waiting for Retry-After; stopping');
    state.waited429 = true;
    await sleep(ra * 1000);
    state.last = 0;
    const e = refuse('rate-limit', `HTTP 429; waited ${ra} s, retrying once`, true); e.after429 = true; throw e;
  }
  if (status !== 200) throw refuse('status', `HTTP ${status} (200 needed)`, status === null || status >= 500);
  await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
  await page.waitForTimeout(500);
  const finalUrl = page.url();
  const fu = new URL(finalUrl);
  const [wo, wr] = cay.repo.split('/');
  const seg = fu.pathname.split('/').filter(Boolean);
  if (/^\/(login|session|sessions)(\/|$)/.test(fu.pathname) || fu.pathname === '/signup') throw refuse('wall', `GitHub sent the page to ${fu.pathname}, a sign-in page`);
  if (seg.length < 2 || !sameRepo(seg[0], wo) || !sameRepo(seg[1], wr)) throw refuse('renamed', `the address now reads ${fu.pathname}; the repo ${cay.repo} has moved to ${seg.slice(0, 2).join('/')}`);
  try { await page.locator('button, [role=button], a').filter({ hasText: new RegExp(DECLINE, 'i') }).first().click({ timeout: 2000 }); await page.waitForTimeout(600); } catch {}
  await page.evaluate(async () => { for (let y = 0; y < Math.min(document.body.scrollHeight, 12000); y += 900) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 70)); } scrollTo(0, 0); });
  await waitImages(page);
  await page.waitForTimeout(300);
  const wall = await page.evaluate(wallScan);
  if (wall.hits.length) throw refuse('wall', `the page is a wall, not the repo: ${wall.hits.slice(0, 2).join('; ')}`);
  if (/^sign in\b/i.test(wall.title.trim())) throw refuse('wall', `the title reads "${wall.title.slice(0, 60)}"`);
  const bg = await page.evaluate(pageBackground);
  const lum = luminance(bg);
  if (lum === null || lum < 0.5) throw refuse('theme', `the page background is ${bg} (luminance ${lum === null ? 'unknown' : lum.toFixed(2)}); only the light theme is shown, never converted`);
  let truncated = false, expanded = false, listing = null;
  if (entry.kind !== 'blob') {
    if (entry.kind === 'home') {
      const before = (await page.evaluate(listingScan, { repo: cay.repo, branch: cay.branch, folder: entry.path })).rows.length;
      const btn = page.locator('button', { hasText: /^\s*view all files\s*$/i }).first();
      if (await btn.isVisible().catch(() => false)) {
        truncated = true;
        await btn.scrollIntoViewIfNeeded().catch(() => {});
        await btn.click({ timeout: 4000 }).catch(() => {});
        for (let i = 0; i < 12; i++) {
          await page.waitForTimeout(300);
          const n = (await page.evaluate(listingScan, { repo: cay.repo, branch: cay.branch, folder: entry.path })).rows.length;
          if (n > before) { expanded = true; break; }
        }
        await page.evaluate(() => scrollTo(0, 0));
        await page.waitForTimeout(300);
      }
    }
    listing = await page.evaluate(listingScan, { repo: cay.repo, branch: cay.branch, folder: entry.path });
    if (listing.rows.length && !listing.in_table) throw refuse('listing', 'the rows found do not sit in a table, so they are not the file listing (the side panel, say); not trusting them');
    if (!listing.rows.length) throw refuse('listing', 'no file rows found on the page (no link of the form /tree|blob/<branch>/<path> with its own path as text inside a table)');
  }
  const file = entry.kind === 'blob' ? await page.evaluate(fileScan) : null;
  const boxes = await page.evaluate(boxScan);
  await page.evaluate(hideFixedOnly);
  const meta = await page.evaluate(() => ({ title: document.title, h: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight) }));
  const cssH = Math.min(meta.h, MAX_CSS_H);
  const png = await page.screenshot({ fullPage: true, clip: { x: 0, y: 0, width: VIEW_W, height: cssH } });
  const ink = await inkMeasure(ctx, png);
  const inkRatio = ink.ratio;
  return { png, page: {
    path: entry.path, type: entry.kind, requested: url, final: finalUrl, status, title: meta.title, picture: null,
    css_height: cssH, capped: meta.h > MAX_CSS_H, picture_px: [ink.w, ink.h], ink_ratio: Math.round(inkRatio * 1e5) / 1e5,
    background: bg, luminance: Math.round(lum * 1e3) / 1e3, truncated, expanded,
    entries: listing ? listing.rows.map((r) => ({ name: r.name, path: r.path, kind: r.kind })) : [],
    rows: listing ? listing.rows.map((r) => ({ path: r.path, rect: r.rect, name_rect: r.name_rect, font_px: r.font_px })) : [],
    row_font_px: listing ? Math.min(...listing.rows.map((r) => r.font_px)) : null,
    listing_ignored: listing ? listing.ignored : null,
    fonts: { ...(boxes.readme_font ? { readme: boxes.readme_font } : {}), ...(file && file.code_font ? { code: file.code_font } : {}) },
    boxes: { file_list: listing ? listing.file_list : null, readme: boxes.readme, about: boxes.about, code: file ? file.code_box : null },
    file: file ? { kind: file.kind, code_lines: file.code_lines, rendered_lines: file.rendered_lines } : null,
    seconds: Math.round((Date.now() - t0) / 100) / 10,
  } };
}

// ---------------------------------------------------------------- one run
async function run(o) {
  const cay = JSON.parse(fs.readFileSync(o.cay, 'utf8'));
  const pages = cay.pages;
  if (pages.length > MAX_LOADS) { const e = new Refusal('rate-limit', `${pages.length} pages are needed and a repo may be loaded ${MAX_LOADS} times at most; open fewer folders`); e.address = `https://github.com/${cay.repo}`; throw e; }
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'quay-profile-'));
  let ctx = null; const out = [];
  const state = { loads: 0, last: 0, waited429: false };
  try {
    const opts = { headless: true, viewport: { width: VIEW_W, height: VIEW_H }, deviceScaleFactor: SCALE, isMobile: false, hasTouch: false, locale: 'en-US', colorScheme: 'light' };
    if (process.env.CHROME_PATH) opts.executablePath = process.env.CHROME_PATH; else opts.channel = 'chrome';
    ctx = await chromium.launchPersistentContext(profile, opts);
    const page = await ctx.newPage();
    for (const entry of pages) {
      let done = null, lastErr = null;
      for (let n = 1; n <= 2 && !done; n++) {
        let timer;
        try {
          done = await Promise.race([capturePage(ctx, page, o, cay, entry, state),
            new Promise((_, rej) => { timer = setTimeout(() => { const e = new Refusal('timeout', `no result in ${o.timeout} s`, true); e.address = pageAddress(o.base, cay.repo, cay.branch, entry); rej(e); }, o.timeout * 1000); })]);
        } catch (e) {
          lastErr = e instanceof Refusal ? e : Object.assign(new Refusal('error', (e.message || String(e)).split('\n')[0], /Timeout|net::/i.test(e.message || '')), { address: pageAddress(o.base, cay.repo, cay.branch, entry) });
          console.error(`quay: ${lastErr.address}: ${lastErr.kind}: ${lastErr.message}${lastErr.retry && n === 1 ? ' (one retry)' : ''}`);
          if (!lastErr.retry) break;
        } finally { clearTimeout(timer); }
      }
      if (!done) { throw lastErr; }
      done.page.picture = `${out.length}.png`;
      out.push(done);
    }
  } finally {
    if (ctx) await Promise.race([ctx.close().catch(() => {}), sleep(8000)]);
    for (let i = 0; i < 5; i++) { try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch { await sleep(400); } }
  }
  const dir = path.join(o.out, o.ref);
  fs.mkdirSync(dir, { recursive: true });
  for (const d of out) fs.writeFileSync(path.join(dir, d.page.picture), d.png);
  const manifest = { version: 1, repo: cay.repo, branch: cay.branch, commit: cay.commit, captured: bangkokStamp(), scale: SCALE, viewport: { width: VIEW_W, height: VIEW_H },
    open: cay.open, loads: state.loads, pages: out.map((d) => d.page) };
  const mf = path.join(dir, 'quay.json');
  fs.writeFileSync(mf, JSON.stringify(manifest, null, 1) + '\n', { encoding: 'utf8' });
  return { manifest: path.resolve(mf), pages: out.length, loads: state.loads };
}

function parseArgs(argv) {
  const o = { base: 'https://github.com', timeout: 45, gap: 0.8 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') { o.help = true; continue; }
    if (!a.startsWith('--')) throw new Error(`unexpected argument ${a}`);
    const k = a.slice(2); const v = argv[++i];
    if (v === undefined) throw new Error(`--${k} needs a value`);
    o[k] = ['timeout', 'gap'].includes(k) ? Number(v) : v;
  }
  return o;
}

export async function main(argv) {
  const o = parseArgs(argv);
  if (o.help) { console.log('quay-repo --cay <cay.json> --ref <name> --out <folder> [--base https://github.com] [--timeout 45] [--gap 0.8]'); return 0; }
  for (const k of ['cay', 'ref', 'out']) if (!o[k]) throw new Error(`--${k} is required`);
  if (!/^[\w.-]+$/.test(o.ref)) throw new Error('--ref may hold letters, digits, dot, dash and underscore only');
  try {
    const r = await run(o);
    console.log(JSON.stringify(r, null, 1));
    return 0;
  } catch (e) {
    if (!(e instanceof Refusal)) throw e;
    console.error(`quay: ${e.address || o.base}: ${e.kind}: ${e.message}; nothing written`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).then((c) => process.exit(c), (e) => { console.error('quay: ' + e.message); process.exit(2); });
}

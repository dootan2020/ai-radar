#!/usr/bin/env node
// chup: a source address + a verbatim sentence from that page -> a phone-width screenshot and the capture-manifest entry
// the spec assembler reads (halcyon_kich_ban.py, KICH-BAN.md section 4). It refuses when the page does not show the sentence.
// Usage and the refusals: CHUP.md. Needs `npm install` in video/ (playwright-core) and Google Chrome on the machine.
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const VIEW_W = 390, VIEW_H = 844, SCALE = 3;                 // the published capture size: 1170 px wide
export const INK_MARGIN = 85, INK_X0 = 60, INK_X1 = 1110;           // ve_halcyon.py: one definition of ink
const PAD_ABOVE = 24, PAD_BELOW = 12;                        // capture px kept above the first and below the last shown line
const MARGIN_CSS = 36;                                       // page kept around the focus in the picture (css px)
export const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
export const DECLINE = '^(decline optional|reject|decline|only necessary|necessary only|refuse|deny|no,? thanks|từ chối)';

class Refusal extends Error {
  constructor(kind, msg, retry = false) { super(msg); this.kind = kind; this.retry = retry; }
}

// ---------------------------------------------------------------- pure helpers (also used by the tests)
export function bandsFromCounts(counts) {   // ve_halcyon.ink_bands: rows with >= 2 ink pixels, a band is >= 10 rows
  const bands = []; let s = null;
  for (let i = 0; i < counts.length; i++) {
    const v = counts[i] >= 2;
    if (v && s === null) s = i;
    if (!v && s !== null) { if (i - s >= 10) bands.push([s, i]); s = null; }
  }
  if (s !== null) bands.push([s, counts.length]);
  return bands;
}

// focus rows and u_rows from the ink rows of the picture and the line boxes of the page (px, relative to the picture)
export function choose(counts, domLines, qa, qb, maxRows) {
  const bands = bandsFromCounts(counts);
  const bandOf = (l) => {
    let best = -1, bestO = 0;
    bands.forEach((b, i) => { const o = Math.min(b[1], l.b) - Math.max(b[0], l.t); if (o > bestO) { bestO = o; best = i; } });
    return best;
  };
  const idx = domLines.map(bandOf);
  for (let i = qa; i <= qb; i++) {
    if (idx[i] < 0) throw new Refusal('no-ink', `line ${i + 1} of the paragraph has no ink the builder would see (text too close to the page colour, or hidden); nothing to show`);
    if (i > qa && idx[i] === idx[i - 1]) throw new Refusal('lines-touch', 'two lines of the quote touch (no blank row between them), so the builder could not cut between them');
  }
  let s = 0;
  for (let i = 0; i <= qa; i++) if (idx[i] < 0 || (i > 0 && idx[i] === idx[i - 1])) { s = qa; break; }
  if (s === 0 && bands[idx[qb]][1] - bands[idx[0]][0] > maxRows) s = qa;
  if (bands[idx[qb]][1] - bands[idx[s]][0] > maxRows) throw new Refusal('too-tall', `the quote spans ${bands[idx[qb]][1] - bands[idx[s]][0]} capture px, over the ${maxRows} px a picture can show; pick a shorter sentence or raise --max-rows`);
  let e = qb;
  while (e + 1 < domLines.length && idx[e + 1] >= 0 && idx[e + 1] === idx[e] + 1 && bands[idx[e + 1]][1] - bands[idx[s]][0] <= maxRows) e++;
  const clear = (r) => r >= 0 && r < counts.length && counts[r] === 0;
  // u_rows: a row inside the gap above the first shown line and one inside the gap below the last, each with two blank rows beside it
  // (the builder's check_shown refuses any ink in the two rows next to a cut). A line the page sets too tight to cut beside is given up, never forced.
  const cutAbove = (i) => {
    const top = bands[idx[i]][0], low = idx[i] > 0 ? bands[idx[i] - 1][1] : 0;
    const t = idx[i] > 0 ? Math.max(Math.floor((low + top) / 2), top - PAD_ABOVE) : Math.max(0, top - PAD_ABOVE);
    for (let r = t; r >= low; r--) if (r + 2 <= top && clear(r) && clear(r + 1)) return r;
    return null;
  };
  const cutBelow = (i) => {
    const bot = bands[idx[i]][1], next = idx[i] + 1 < bands.length, high = next ? bands[idx[i] + 1][0] : counts.length;
    const t = next ? Math.min(bot + PAD_BELOW, Math.max(Math.floor((bot + high) / 2), bot + 2)) : Math.min(counts.length, bot + PAD_BELOW);
    for (let r = t; r >= bot + 2; r--) if (r <= high && clear(r - 1) && clear(r - 2)) return r;
    return null;
  };
  let ua = cutAbove(s);
  while (ua === null && s < qa) { s++; ua = cutAbove(s); }
  let ub = cutBelow(e);
  while (ub === null && e > qb) { e--; ub = cutBelow(e); }
  if (ua === null) throw new Refusal('no-gap', 'no blank row above the first line of the quote to cut the picture at; the page puts something right against it');
  if (ub === null) throw new Refusal('no-gap', 'no blank row below the last line of the quote to cut the picture at; the page puts something right against it');
  const rows = [bands[idx[s]][0], bands[idx[e]][1]];
  return { rows, uRows: [ua, ub], lines: [s, e], bandCount: bands.length, bandIdx: idx };
}

export function bangkokStamp(d = new Date()) {
  return d.toLocaleString('sv-SE', { timeZone: 'Asia/Bangkok' }).replace(' ', 'T') + '+07:00';
}
const bangkokDate = (d = new Date()) => d.toLocaleDateString('en-GB', { timeZone: 'Asia/Bangkok' });

// ---------------------------------------------------------------- code that runs inside the page
export function wallScan() {
  const WALL = [
    ['bot check', /verify you are (a )?human|just a moment|captcha|access denied|unusual traffic|are you a robot|attention required|request blocked|checking your browser/i],
    ['sign-in or paywall', /sign in to (continue|read|view|see)|log ?in to (continue|read|view|see)|subscribe to (continue|read|unlock)|create (a free )?account to (continue|read)|log ?in or sign ?up|đăng nhập để (tiếp tục|xem|đọc)|đăng ký để (đọc|xem)/i],
    ['consent wall', /we value your privacy|accept (all )?cookies|cookie (settings|preferences|consent)|manage (your )?(cookie|consent)|consent (preferences|options)|before you continue to|chấp nhận (tất cả )?cookie/i],
  ];
  const ERR = /^\s*(404|403|500|502|503)\b|page not found|not found|something went wrong|không tìm thấy trang|access forbidden/i;
  const vw = innerWidth, vh = innerHeight;
  const hits = [];
  const test = (where, text) => {
    text = (text || '').replace(/\s+/g, ' ').trim(); if (!text) return;
    for (const [name, re] of WALL) if (re.test(text)) hits.push(`${name} in ${where}: "${text.slice(0, 90)}"`);
  };
  const h1 = document.querySelector('h1');
  if (ERR.test(document.title) || (h1 && ERR.test(h1.innerText))) hits.push(`error page: "${(document.title || (h1 && h1.innerText) || '').slice(0, 90)}"`);
  test('the title', document.title);
  for (const e of document.querySelectorAll('*')) {
    const cs = getComputedStyle(e);
    const modal = e.tagName === 'DIALOG' || /^(alert)?dialog$/.test(e.getAttribute('role') || '') || e.getAttribute('aria-modal') === 'true';
    const pinned = cs.position === 'fixed' || cs.position === 'sticky';
    if (!modal && !pinned) continue;
    if (e.checkVisibility && !e.checkVisibility()) continue;
    const r = e.getBoundingClientRect();
    const area = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0)) / (vw * vh);
    if (modal ? area > 0.05 : area >= 0.25) test(`an overlay covering ${Math.round(area * 100)}% of the screen`, e.innerText);
  }
  const body = (document.body.innerText || '').replace(/\s+/g, ' ').trim();
  if (body.length < 400) test('a page with only ' + body.length + ' characters of text', body);
  return { hits, textLength: body.length, title: document.title };
}

function measure(a) {
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);
  const Q = { '‘': "'", '’': "'", 'ʼ': "'", '‛': "'", '“': '"', '”': '"', '„': '"', '–': '-', '—': '-', '‑': '-', '−': '-' };
  const ZW = new Set(['​', '‌', '‍', '﻿', '­']);
  const nch = (c) => (ZW.has(c) ? null : /\s/.test(c) ? ' ' : (Q[c] || c));
  const normText = (t) => { let o = ''; for (const c of t) { const x = nch(c); if (x === null) continue; if (x === ' ' && (o === '' || o.endsWith(' '))) continue; o += x; } return o.trim(); };
  const blockOf = (nd) => { let e = nd.nodeType === 3 ? nd.parentElement : nd; while (e && getComputedStyle(e).display.startsWith('inline')) e = e.parentElement; return e; };
  const overlay = (el) => { for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
    const p = getComputedStyle(e).position; if (p === 'fixed' || p === 'sticky') return true;
    if (e.tagName === 'DIALOG' || /^(alert)?dialog$/.test(e.getAttribute('role') || '') || e.getAttribute('aria-modal') === 'true') return true; } return false; };
  // visible text with a map from each normalised character back to its text node
  const chars = []; let prevBlock = null; const nodes = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  let n;
  const push = (c, node, off, orig) => { if (c === ' ' && (!chars.length || chars[chars.length - 1].c === ' ')) return; chars.push({ c, node, off, orig }); };
  while ((n = w.nextNode())) {
    if (n.nodeType === 1) { if (n.tagName === 'BR') push(' ', null, 0, ' '); continue; }
    const pe = n.parentElement; if (!pe || SKIP.has(pe.tagName)) continue;
    if (pe.checkVisibility && !pe.checkVisibility({ visibilityProperty: true })) continue;
    const ov = overlay(pe);
    const blk = blockOf(n);
    if (blk !== prevBlock) { push(' ', null, 0, ' '); prevBlock = blk; }
    for (let i = 0; i < n.data.length; i++) { const c = nch(n.data[i]); if (c === null) continue; push(c, ov ? null : n, i, n.data[i]); }
    nodes.add(n);
  }
  let N = chars.map((x) => x.c).join('');
  const need = normText(a.quote);
  if (!need) return { err: 'empty', detail: 'the sentence is empty' };
  // occurrences, ignoring characters that sit in overlays (fixed, sticky, dialog)
  const hits = []; let from = 0, i;
  while ((i = N.indexOf(need, from)) >= 0) { hits.push(i); from = i + need.length; }
  const usable = hits.filter((h) => chars.slice(h, h + need.length).every((x) => x.node || x.c === ' '));
  if (!hits.length) return { err: 'not-found', detail: 'the sentence is not in the visible text of the page' };
  if (!usable.length) return { err: 'overlay', detail: 'the sentence appears only inside a pop-up, banner or pinned bar, not in the page itself' };
  let pick;
  if (a.occurrence === 'last') pick = usable[usable.length - 1];
  else if (a.occurrence) { pick = usable[a.occurrence - 1]; if (pick === undefined) return { err: 'not-found', detail: `occurrence ${a.occurrence} asked, the page has ${usable.length}` }; }
  else if (usable.length > 1) return { err: 'ambiguous', detail: `the sentence appears ${usable.length} times on the page; say which with --occurrence N (1 = first, "last")`, count: usable.length };
  else pick = usable[0];
  const span = chars.slice(pick, pick + need.length);
  const real = span.filter((x) => x.node);
  const startNode = real[0].node, endNode = real[real.length - 1].node;
  const bs = blockOf(startNode), be = blockOf(endNode);
  if (bs !== be) return { err: 'multi-block', detail: `the sentence runs across two blocks of the page (<${bs.tagName.toLowerCase()}> and <${be.tagName.toLowerCase()}>); capture a sentence that lies in one paragraph` };
  const rectsOfRange = (sn, so, en, eo) => { const r = document.createRange(); r.setStart(sn, so); r.setEnd(en, eo);
    return [...r.getClientRects()].filter((q) => q.width > 0.5 && q.height > 0.5); };
  const group = (rs) => { rs = rs.slice().sort((x, y) => (x.top + x.bottom) - (y.top + y.bottom)); const L = [];
    for (const q of rs) { const c = (q.top + q.bottom) / 2, l = L[L.length - 1];
      if (l && c < l.b && c > l.t) { l.t = Math.min(l.t, q.top); l.b = Math.max(l.b, q.bottom); l.l = Math.min(l.l, q.left); l.r = Math.max(l.r, q.right); }
      else L.push({ t: q.top, b: q.bottom, l: q.left, r: q.right }); }
    return L; };
  // lines of the paragraph (the block holding the sentence)
  const pw = document.createTreeWalker(bs, NodeFilter.SHOW_TEXT); const prs = []; let pn;
  while ((pn = pw.nextNode())) { const pe = pn.parentElement; if (!pe || SKIP.has(pe.tagName) || (pe.checkVisibility && !pe.checkVisibility({ visibilityProperty: true }))) continue;
    if (!pn.data.trim()) continue; prs.push(...rectsOfRange(pn, 0, pn, pn.data.length)); }
  const para = group(prs).map((l) => ({ t: l.t + scrollY, b: l.b + scrollY, l: l.l, r: l.r }));
  const nrects = []; {
    for (const x of real) { const key = x.node; if (!nrects.length || nrects[nrects.length - 1].node !== key) nrects.push({ node: key, a: x.off, z: x.off + 1 }); else nrects[nrects.length - 1].z = x.off + 1; } }
  const needleLines = group(nrects.flatMap((q) => rectsOfRange(q.node, q.a, q.node, q.z))).map((l) => ({ t: l.t + scrollY, b: l.b + scrollY, l: l.l, r: l.r }));
  if (!needleLines.length || !para.length) return { err: 'not-rendered', detail: 'the sentence is in the page text but takes no room on screen (collapsed, clipped or off-screen); open it first with --open "<text of the heading to expand>"' };
  const lineAt = (nl) => para.findIndex((p) => Math.min(p.b, nl.b) - Math.max(p.t, nl.t) > 0.5 * Math.min(p.b - p.t, nl.b - nl.t));
  const qa = lineAt(needleLines[0]), qb = lineAt(needleLines[needleLines.length - 1]);
  if (qa < 0 || qb < 0) return { err: 'not-rendered', detail: 'could not place the sentence on a line of its paragraph' };
  // the phrases to mark: one rect per wrapped line, with the words on that line (original characters)
  const bands = [];
  for (const ph of a.phrases) {
    const pt = normText(ph);
    const at = []; let f = 0, k; const inQuote = N.slice(pick, pick + need.length);
    while ((k = inQuote.indexOf(pt, f)) >= 0) { at.push(k); f = k + pt.length; }
    if (!pt || !at.length) return { err: 'band-not-in-quote', detail: `the phrase to mark "${ph}" is not inside the sentence` };
    if (at.length > 1) return { err: 'band-ambiguous', detail: `the phrase to mark "${ph}" occurs ${at.length} times inside the sentence; use a longer phrase` };
    const pa = pick + at[0], pz = pa + pt.length; const words = []; let ws = null;
    for (let j = pa; j <= pz; j++) { const sp = j === pz || chars[j].c === ' '; if (!sp && ws === null) ws = j; if (sp && ws !== null) { words.push([ws, j]); ws = null; } }
    const byLine = [];
    for (const [x, y] of words) {
      const cs = chars.slice(x, y).filter((c) => c.node); if (!cs.length) continue;
      const rs = []; let cur = null;
      for (const c of cs) { if (!cur || cur.node !== c.node) { cur = { node: c.node, a: c.off, z: c.off + 1 }; rs.push(cur); } else cur.z = c.off + 1; }
      const qs = rs.flatMap((q) => rectsOfRange(q.node, q.a, q.node, q.z));
      for (const q of qs) { const c = (q.top + q.bottom) / 2; let L = byLine.find((l) => c < l.b && c > l.t);
        const word = chars.slice(x, y).map((c) => c.orig).join('');
        if (!L) { L = { t: q.top, b: q.bottom, l: q.left, r: q.right, words: [] }; byLine.push(L); }
        L.t = Math.min(L.t, q.top); L.b = Math.max(L.b, q.bottom); L.l = Math.min(L.l, q.left); L.r = Math.max(L.r, q.right);
        if (!L.words.includes(word + '@' + x)) L.words.push(word + '@' + x); }
    }
    byLine.sort((p, q) => p.t - q.t);
    for (const L of byLine) bands.push({ text: L.words.map((x) => x.replace(/@\d+$/, '')).join(' '), l: L.l, t: L.t + scrollY, w: L.r - L.l, h: L.b - L.t });
  }
  // lines to consider below the quote: the same paragraph, as far as a picture could reach
  const maxCss = a.maxRows / a.scale + 40;
  const s0 = (para[qb].b - para[0].t) * a.scale > a.maxRows ? qa : 0; const top0 = para[s0].t;
  let cand = para;
  if (a.follow) {   // opt-in: the lines that come after the paragraph, wherever they sit on the page
    const rs = []; const aw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let an;
    while ((an = aw.nextNode())) { const pe = an.parentElement; if (!pe || SKIP.has(pe.tagName) || !an.data.trim() || (pe.checkVisibility && !pe.checkVisibility({ visibilityProperty: true })) || overlay(pe)) continue; rs.push(...rectsOfRange(an, 0, an, an.data.length)); }
    const lastB = para[para.length - 1].b;
    cand = para.concat(group(rs).map((l) => ({ t: l.t + scrollY, b: l.b + scrollY, l: l.l, r: l.r })).filter((l) => l.t >= lastB - 1));
  }
  let e = qb; while (e + 1 < cand.length && cand[e + 1].b - top0 <= maxCss) e++;
  const matched = real.map((x) => x.orig).join('');
  const covered = [];
  if (a.cover) for (let i = qa; i <= qb; i++) { const cy = (para[i].t + para[i].b) / 2 - scrollY, cx = Math.min(Math.max((para[i].l + para[i].r) / 2, 1), innerWidth - 1);
    if (cy < 0 || cy > innerHeight) { covered.push('off-screen'); continue; }
    const el = document.elementFromPoint(cx, cy); if (!el || !(bs.contains(el) || el.contains(bs))) covered.push(el ? el.tagName.toLowerCase() : 'nothing'); }
  return { ok: true, count: usable.length, matched, tag: bs.tagName.toLowerCase(), lines: cand.slice(0, e + 1), qa, qb, needleLines, bands,
    scrollY, covered, ctx: N.slice(Math.max(0, pick - 60), pick + need.length + 60) };
}

export const hideFixed = () => { for (const e of document.querySelectorAll('*')) { const p = getComputedStyle(e).position; if (p === 'fixed' || p === 'sticky') e.style.visibility = 'hidden'; } };

// ---------------------------------------------------------------- one attempt on one address
export async function inkRows(ctx, buf) {
  const p = await ctx.newPage();
  try {
    return await p.evaluate(async ([b64, m, x0, x1]) => {
      const bmp = await createImageBitmap(await (await fetch('data:image/png;base64,' + b64)).blob());
      const cv = new OffscreenCanvas(bmp.width, bmp.height); const g = cv.getContext('2d'); g.drawImage(bmp, 0, 0);
      const d = g.getImageData(0, 0, bmp.width, bmp.height).data; const W = bmp.width, H = bmp.height;
      const lum = new Uint8Array(W * H); const hist = new Array(256).fill(0);
      for (let i = 0; i < W * H; i++) { const L = (d[i * 4] * 19595 + d[i * 4 + 1] * 38470 + d[i * 4 + 2] * 7471 + 0x8000) >> 16; lum[i] = L; hist[L]++; }
      let bg = 0; for (let v = 1; v < 256; v++) if (hist[v] > hist[bg]) bg = v;
      const counts = new Array(H).fill(0);
      for (let y = 0; y < H; y++) { let c = 0; for (let x = x0; x < Math.min(x1, W); x++) if (Math.abs(lum[y * W + x] - bg) > m) c++; counts[y] = c; }
      return { counts, w: W, h: H, bg };
    }, [buf.toString('base64'), INK_MARGIN, INK_X0, INK_X1]);
  } finally { await p.close().catch(() => {}); }
}

async function attempt(job, url, deadlineMs) {
  const t0 = Date.now();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'chup-profile-'));
  let ctx = null;
  const timer = { t: null };
  const run = async () => {
    const opts = { headless: true, viewport: { width: VIEW_W, height: VIEW_H }, deviceScaleFactor: SCALE, isMobile: true, hasTouch: true, locale: job.locale };
    if (job.ua) opts.userAgent = job.ua === 'iphone' ? IPHONE_UA : job.ua;
    if (process.env.CHROME_PATH) opts.executablePath = process.env.CHROME_PATH; else opts.channel = 'chrome';
    ctx = await chromium.launchPersistentContext(profile, opts);
    const page = await ctx.newPage();
    const resp = await page.goto(url, { waitUntil: 'load', timeout: deadlineMs - 5000 });
    const status = resp ? resp.status() : (url.startsWith('file:') ? 200 : null);
    if (status !== 200) throw new Refusal('status', `HTTP ${status} (200 needed)`, status === null || status >= 500);
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(500);
    try { await page.locator('button, [role=button], a').filter({ hasText: new RegExp(DECLINE, 'i') }).first().click({ timeout: 2000 }); await page.waitForTimeout(600); } catch {}
    await page.evaluate(async () => { for (let y = 0; y < Math.min(document.body.scrollHeight, 12000); y += 900) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 70)); } scrollTo(0, 0); });
    await page.waitForTimeout(300);
    if (job.open) {
      const ok = await page.evaluate((q) => { const els = [...document.querySelectorAll('[aria-expanded],summary,button,[role=button],h2,h3,h4')].filter((e) => e.textContent.includes(q));
        const t = els.find((e) => e.getAttribute('aria-expanded') === 'false') || els[0]; if (!t) return false; t.scrollIntoView({ block: 'center' }); t.click(); return true; }, job.open);
      if (!ok) throw new Refusal('open', `--open "${job.open}": no heading or button on the page contains that text`);
      await page.waitForTimeout(1200);
    }
    const wall = await page.evaluate(wallScan);
    if (wall.hits.length) throw new Refusal('wall', `the page is a wall, not the article: ${wall.hits.slice(0, 2).join('; ')}`);
    const args = { quote: job.quote, occurrence: job.occurrence, phrases: job.bands, maxRows: job.maxRows, scale: SCALE, follow: !!job.follow };
    const m1 = await page.evaluate(measure, args);
    if (m1.err) throw new Refusal(m1.err, m1.detail, m1.err === 'not-found');
    await page.evaluate(hideFixed);
    const y0 = Math.floor(m1.lines[0].t - MARGIN_CSS), y1 = Math.ceil(m1.lines[m1.lines.length - 1].b + MARGIN_CSS);
    if (y1 - y0 > VIEW_H) throw new Refusal('too-tall', `the picture would be ${(y1 - y0) * SCALE} px tall, over one screen; lower --max-rows`);
    await page.evaluate((y) => scrollTo(0, Math.max(0, y - 100)), y0); await page.waitForTimeout(600);
    const m2 = await page.evaluate(measure, { ...args, cover: true });
    if (m2.err) throw new Refusal(m2.err, m2.detail, true);
    if (m2.covered.length) throw new Refusal('covered', `something else is drawn over the sentence (${m2.covered[0]}); not capturing it`);
    const sy = m2.scrollY, clip = { x: 0, y: y0 - sy, width: VIEW_W, height: y1 - y0 };
    const png = await page.screenshot({ clip });
    const m3 = await page.evaluate(measure, args);
    if (m3.err || m3.lines.length !== m2.lines.length || Math.abs(m3.lines[0].t - m2.lines[0].t) > 0.5 || Math.abs(m3.lines[m3.qb].t - m2.lines[m2.qb].t) > 0.5)
      throw new Refusal('moving', 'the page moved while it was being captured (late-loading content); not trusting the picture', true);
    const ink = await inkRows(ctx, png);
    if (ink.w !== VIEW_W * SCALE || ink.h !== (y1 - y0) * SCALE) throw new Refusal('size', `the picture is ${ink.w}x${ink.h}, expected ${VIEW_W * SCALE}x${(y1 - y0) * SCALE}`);
    const rel = (css) => (css + 0) * SCALE;
    const domLines = m2.lines.map((l) => ({ t: Math.round((l.t - y0) * SCALE), b: Math.round((l.b - y0) * SCALE) }));
    const pick = choose(ink.counts, domLines, m2.qa, m2.qb, job.maxRows);
    const bands = m2.bands.map((b) => ({ rect: [Math.round(b.l * SCALE), Math.round((b.t - y0) * SCALE), Math.round(b.w * SCALE), Math.round(b.h * SCALE)], text: b.text }));
    const meta = await page.evaluate(() => ({ site: (document.querySelector('meta[property="og:site_name"]') || {}).content || '', title: document.title, final: location.href }));
    return { png, entry: { rows: pick.rows, uRows: pick.uRows, bands }, status, matched: m2.matched, count: m2.count, ctx: m2.ctx, meta, bandCount: pick.bandCount,
      focusLines: pick.lines[1] - pick.lines[0] + 1, capturedAt: bangkokStamp(), secs: (Date.now() - t0) / 1000, size: [ink.w, ink.h] };
  };
  try {
    return await Promise.race([run(), new Promise((_, rej) => { timer.t = setTimeout(() => rej(new Refusal('timeout', `no result in ${deadlineMs / 1000} s`, true)), deadlineMs); })]);
  } finally {
    clearTimeout(timer.t);
    if (ctx) await Promise.race([ctx.close().catch(() => {}), new Promise((r) => setTimeout(r, 8000))]);
    for (let i = 0; i < 5; i++) { try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch { await new Promise((r) => setTimeout(r, 400)); } }
  }
}

// ---------------------------------------------------------------- the command
function parseArgs(argv) {
  const o = { url: [], band: [] }; const flags = new Set(['url', 'quote', 'quote-file', 'ref', 'out', 'band', 'occurrence', 'hco', 'source', 'date', 'locale', 'ua', 'open', 'max-rows', 'timeout', 'job']);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '-h' || a === '--help') { o.help = true; continue; }
    if (a === '--follow') { o.follow = true; continue; }
    if (!a.startsWith('--') || !flags.has(a.slice(2))) throw new Error(`unknown argument ${a}`);
    const k = a.slice(2), v = argv[++i];
    if (v === undefined) throw new Error(`${a} needs a value`);
    if (k === 'url' || k === 'band') o[k].push(v); else o[k] = v;
  }
  return o;
}

export async function main(argv) {
  const o = parseArgs(argv);
  if (o.help) { console.log('chup --url <address> [--url <next address> ...] --quote "<verbatim sentence>" --ref <name> --out <folder> [--band "<phrase>" ...] [--hco <hco.news story address>]\n  more: --follow  --occurrence N|last  --open "<heading text>"  --source "<chip label>"  --date dd/mm/yyyy  --locale en-US  --ua iphone  --max-rows 700  --timeout 60  --quote-file f  --job job.json\nSee CHUP.md.'); return 0; }
  let job = {};
  if (o.job) job = JSON.parse(fs.readFileSync(o.job, 'utf8'));
  const pick = (k, d) => (o[k] !== undefined && !(Array.isArray(o[k]) && !o[k].length) ? o[k] : job[k] !== undefined ? job[k] : d);
  const j = { urls: pick('url', job.urls || []), quote: o['quote-file'] ? fs.readFileSync(o['quote-file'], 'utf8').trim() : pick('quote'), ref: pick('ref'), out: pick('out'),
    bands: pick('band', job.bands || []), occurrence: pick('occurrence'), hco: pick('hco'), source: pick('source'), date: pick('date'), locale: pick('locale', 'en-US'),
    ua: pick('ua'), open: pick('open'), follow: o.follow || job.follow || false, maxRows: Number(pick('max-rows', job.maxRows || 700)), timeout: Number(pick('timeout', 60)) };
  if (typeof j.urls === 'string') j.urls = [j.urls];
  for (const k of ['quote', 'ref', 'out']) if (!j[k]) throw new Error(`--${k} is required`);
  if (!j.urls.length) throw new Error('--url is required (give several to name fallbacks, in order)');
  if (!/^[\w.-]+$/.test(j.ref)) throw new Error('--ref may hold letters, digits, dot, dash and underscore only (it names the picture file)');
  if (j.occurrence !== undefined && j.occurrence !== 'last') j.occurrence = parseInt(j.occurrence, 10);
  const order = [...j.urls, ...(j.hco ? [j.hco] : [])];
  const trail = []; let done = null;
  for (const url of order) {
    for (let n = 1; n <= 2 && !done; n++) {
      try { done = { url, ...(await attempt(j, url, j.timeout * 1000)) }; trail.push({ url, try: n, ok: true, secs: done.secs }); }
      catch (e) {
        const kind = e instanceof Refusal ? e.kind : 'error'; const msg = e instanceof Refusal ? e.message : (e.message || String(e)).split('\n')[0];
        trail.push({ url, try: n, ok: false, kind, why: msg });
        console.error(`chup: ${url}: ${kind}: ${msg}${e instanceof Refusal && e.retry && n === 1 ? ' (one retry)' : ''}`);
        if (!(e instanceof Refusal ? e.retry : true)) break;
      }
    }
    if (done) break;
  }
  if (!done) { console.error(`chup: the sentence could not be shown from any of ${order.length} address(es); nothing written. Never a different sentence: fix the address or the sentence.`); return 1; }
  fs.mkdirSync(j.out, { recursive: true });
  const file = `${j.ref}.png`;
  fs.writeFileSync(path.join(j.out, file), done.png);
  const entry = { file, focus: { rows: done.entry.rows }, u_rows: done.entry.uRows,
    source: j.source || done.meta.site || (done.url.startsWith('file:') ? 'local page' : new URL(done.url).hostname.replace(/^www\./, '')),
    date: j.date || bangkokDate(), captured: done.capturedAt, bands: done.entry.bands };
  const mf = path.join(j.out, 'captures.json');
  let man = { captures: {} };
  if (fs.existsSync(mf)) man = JSON.parse(fs.readFileSync(mf, 'utf8'));
  man.captures[j.ref] = entry;
  fs.writeFileSync(mf, JSON.stringify(man, null, 1) + '\n', { encoding: 'utf8' });
  const info = { ref: j.ref, url: done.url, final_url: done.meta.final, http: done.status, picture: path.resolve(j.out, file), picture_px: done.size, matched: done.matched, context: done.ctx,
    focus_lines: done.focusLines, seconds: Math.round(done.secs * 10) / 10, manifest: path.resolve(mf), trail };
  fs.writeFileSync(path.join(j.out, `${j.ref}.capture.json`), JSON.stringify({ ...info, entry }, null, 1) + '\n', { encoding: 'utf8' });
  console.log(JSON.stringify({ ...info, entry }, null, 1));
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).then((c) => process.exit(c), (e) => { console.error('chup: ' + e.message); process.exit(2); });
}

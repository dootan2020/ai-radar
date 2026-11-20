#!/usr/bin/env node
// quay-demo: record, by script, a public agent demo page (the AG-UI Dojo "shared state" demo) as a 390x844 phone video, and read the AG-UI events of that very run.
// The script: open the page, wait for the chat, type one sentence with real key delays, send it, let the answer stream, close the chat, scroll to the
// "Agent Scratch pad". Headless Chrome, a throwaway profile deleted afterwards, no sign-in, no cookies kept, no CAPTCHA, navigation only to the job's hosts.
//   node video/halcyon/demo/quay-demo.mjs --job <job.json> --out <folder>
// The job (halcyon_demo.py writes it): {page, say, hosts: [...], deadline: seconds}. Writes <out>/demo.webm and <out>/rec.json (what the page did: moments in seconds
// of the video, the stream's event counts, the notes, rectangles); on a refusal writes <out>/refusal.json {kind, why, retry} and exits 1. 2 = bad arguments.
// halcyon_demo.py owns every gate that judges the result (events, effect, size, age); this file only drives the page and reports what happened.
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { wallScan } from '../chup.mjs';

export const VIEW_W = 390, VIEW_H = 844;
const SEL = {
  textarea: '[data-testid=copilot-chat-textarea]',
  send: '[data-testid=copilot-send-button]',
  close: '[data-testid=copilot-close-button]',
  userMsg: '[data-testid=copilot-user-message]',
  assistantMsg: '[data-testid=copilot-assistant-message]',
  cursor: '[data-testid=copilot-loading-cursor]',
  toolbar: '[data-testid=copilot-assistant-toolbar]',
  chips: '[data-testid=copilot-suggestions]',
  input: '[data-testid=copilot-chat-input]',
  notesCard: '[data-testid=notes-card]',
  notesEmpty: '[data-testid=notes-empty]',
  noteItem: '[data-testid=note-item]',
};
// pace of the footage (ms): long enough that a viewer reads each stage on a phone
const PACE = { intro: 1600, keyDelay: 60, afterType: 500, holdAnswer: 2200, afterClose: 700, scroll: 1300, holdNotes: 3200 };
const KEY_FIELD = /api[ _-]?key|secret|token|password|passcode|mật khẩu|e-?mail/i;

class Refusal extends Error {
  constructor(kind, msg, retry = false) { super(msg); this.kind = kind; this.retry = retry; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- pure helpers (also used by the tests)
export function countEvents(sse) {   // the AG-UI events of a text/event-stream body: {total, by_type, order}
  const by_type = {}, order = [];
  let total = 0;
  for (const block of String(sse).split(/\r?\n\r?\n/)) {
    const data = block.split(/\r?\n/).filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trimStart()).join('\n');
    if (!data) continue;
    let ev; try { ev = JSON.parse(data); } catch { continue; }
    if (!ev || typeof ev.type !== 'string') continue;
    total += 1; by_type[ev.type] = (by_type[ev.type] || 0) + 1;
    if (!order.includes(ev.type)) order.push(ev.type);   // first-seen order of the types
  }
  return { total, by_type, order };
}
export const hostOf = (u) => { try { return new URL(u).host; } catch { return ''; } };

// ---------------------------------------------------------------- one attempt
async function attempt(job, outDir) {
  const hosts = new Set(job.hosts), t0w = Date.now();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'demo-profile-'));
  const vdir = fs.mkdtempSync(path.join(os.tmpdir(), 'demo-video-'));
  let ctx = null, timer = null;
  const cleanup = async () => {
    clearTimeout(timer);
    if (ctx) await ctx.close().catch(() => {});
    fs.rmSync(profile, { recursive: true, force: true });
    fs.rmSync(vdir, { recursive: true, force: true });
  };
  const rec = { page: job.page, say: job.say, moments: {}, blocked: [], streams: [], notes: [], rects: {} };
  const body = async () => {
    const opts = { headless: true, viewport: { width: VIEW_W, height: VIEW_H }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: job.locale || 'en-US',
      acceptDownloads: false, serviceWorkers: 'block', recordVideo: { dir: vdir, size: { width: VIEW_W, height: VIEW_H } } };
    if (process.env.CHROME_PATH) opts.executablePath = process.env.CHROME_PATH; else opts.channel = 'chrome';
    ctx = await chromium.launchPersistentContext(profile, opts);
    await ctx.route('**/*', (route) => {                 // pages of other hosts are never opened; assets of other hosts (fonts, images) are fine
      const rq = route.request();
      if (rq.isNavigationRequest() && !hosts.has(hostOf(rq.url())) && !rq.url().startsWith('about:')) { rec.blocked.push(rq.url().slice(0, 160)); return route.abort('blockedbyclient'); }
      return route.continue();
    });
    const page = await ctx.newPage();
    const t0 = Date.now();
    const T = () => Math.round((Date.now() - t0)) / 1000;   // seconds since the page was created = since the video started
    const mark = (k) => { if (!(k in rec.moments)) rec.moments[k] = T(); };
    let downloaded = null;
    page.on('download', (d) => { downloaded = d.url().slice(0, 120); });
    const bodies = [];
    page.on('response', (r) => {
      if (r.request().method() === 'POST' && /event-stream/.test(r.headers()['content-type'] || '')) {
        mark('stream_first_byte');
        rec.streams.push({ url: r.url().slice(0, 200), status: r.status() });
        bodies.push(r.text().then((t) => { mark('stream_end'); return t; }, () => ''));
      }
    });
    const resp = await page.goto(job.page, { waitUntil: 'load', timeout: 30000 });
    const status = resp ? resp.status() : null;
    if (status !== 200) throw new Refusal('status', `${job.page} answered HTTP ${status} (200 needed)`, status === null || status >= 500);
    if (!hosts.has(hostOf(page.url()))) throw new Refusal('address', `the page ended on ${page.url()}, which is not one of ${[...hosts].join(', ')}`);
    try { await page.waitForSelector(SEL.textarea, { state: 'visible', timeout: 20000 }); }
    catch { throw new Refusal('chat', 'the chat box did not appear within 20 s', true); }
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
    // one cosmetic change, reported in the manifest: the chat panel's 1 px grey left border runs down every row of the 390 px picture and defeats the builder's flat-row test (SPEC.md)
    await page.addStyleTag({ content: '[data-testid=copilot-sidebar]{border-left-width:0 !important}' });
    rec.cosmetic = 'removed the 1 px left border of the chat panel';
    mark('page_ready');
    const scan = await page.evaluate(wallScan);
    if (scan.hits.length) throw new Refusal('wall', scan.hits.slice(0, 3).join('; '));
    const fields = await page.evaluate((src) => { const re = new RegExp(src, 'i');
      return [...document.querySelectorAll('input,textarea')].filter((e) => e.type === 'password' || re.test([e.placeholder, e.name, e.getAttribute('aria-label'), e.autocomplete].join(' '))).map((e) => (e.placeholder || e.name || e.type)).slice(0, 3); }, KEY_FIELD.source);
    if (fields.length) throw new Refusal('wall', `a key, password or e-mail field is on the page: ${fields.join(', ')}`);
    const box = (sel) => page.evaluate((s) => { const r = [...document.querySelectorAll(s)].map((e) => e.getBoundingClientRect()).filter((x) => x.width > 0 && x.height > 0);
      return r.length ? [Math.min(...r.map((x) => x.left)), Math.min(...r.map((x) => x.top)), Math.max(...r.map((x) => x.right)), Math.max(...r.map((x) => x.bottom))].map(Math.round) : null; }, sel);
    rec.rects.input = await box(SEL.input);       // the box the sentence is typed into, before it is used
    rec.notes_before = await page.locator(SEL.noteItem).count();
    rec.notes_empty_before = (await page.locator(SEL.notesEmpty).count()) > 0;
    await page.waitForTimeout(PACE.intro);

    await page.click(SEL.textarea); mark('typed_start');
    await page.keyboard.type(job.say, { delay: PACE.keyDelay }); mark('typed_end');
    rec.typed = await page.inputValue(SEL.textarea);
    if (rec.typed !== job.say) throw new Refusal('typing', `the chat box holds ${JSON.stringify(rec.typed)}, not the sentence ${JSON.stringify(job.say)}`, true);
    await page.waitForTimeout(PACE.afterType);
    await page.click(SEL.send); mark('sent');

    try { await page.waitForFunction((s) => [...document.querySelectorAll(s)].some((e) => e.innerText.trim()), SEL.assistantMsg, { timeout: 45000, polling: 100 }); } catch { throw new Refusal('answer', 'no answer appeared within 45 s of sending', true); }
    mark('answer_start');
    if (bodies.length === 0) { await sleep(1500); }
    const texts = await Promise.race([Promise.all(bodies), sleep(60000).then(() => null)]);
    if (!texts) throw new Refusal('stream', 'the event stream did not end within 60 s', true);
    // the answer is finished when the stream has ended and the loading cursor is gone
    await page.waitForFunction((c) => !document.querySelector(c), SEL.cursor, { timeout: 15000 }).catch(() => {});
    mark('answer_end');
    rec.events = texts.map(countEvents);
    rec.answer = (await page.locator(SEL.assistantMsg).evaluateAll((els) => els.map((e) => e.innerText.trim()).filter(Boolean).join('\n'))).trim();
    // the messages down to the last thing under them (copy button, suggestion chips): what the screen shows between the header and the input box
    const parts = [await box(SEL.userMsg), await box(SEL.assistantMsg), await box(SEL.toolbar), await box(SEL.chips)].filter(Boolean);
    rec.rects.chat = parts.length ? [Math.max(0, Math.min(...parts.map((x) => x[0]))), Math.max(0, Math.min(...parts.map((x) => x[1]))), Math.min(VIEW_W, Math.max(...parts.map((x) => x[2]))), Math.min(VIEW_H, Math.max(...parts.map((x) => x[3])))] : null;
    await page.waitForTimeout(PACE.holdAnswer);

    await page.click(SEL.close); mark('chat_closed');
    await page.waitForTimeout(PACE.afterClose);
    await page.evaluate((c) => document.querySelector(c).scrollIntoView({ behavior: 'smooth', block: 'center' }), SEL.notesCard);
    await page.waitForTimeout(PACE.scroll); mark('notes_in_view');
    rec.notes = await page.locator(SEL.noteItem).evaluateAll((els) => els.map((e) => e.innerText.replace(/\s+/g, ' ').trim()));
    rec.notes_empty_after = (await page.locator(SEL.notesEmpty).count()) > 0;
    rec.rects.notes = await page.evaluate((c) => { const r = document.querySelector(c).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round); }, SEL.notesCard);
    await page.waitForTimeout(PACE.holdNotes); mark('end');
    if (downloaded) throw new Refusal('download', `the page started a download (${downloaded}); nothing is downloaded`);
    rec.seconds_wall = Math.round((Date.now() - t0w) / 100) / 10;
    const video = page.video();
    await ctx.close(); ctx = null;
    const src = await video.path();
    fs.copyFileSync(src, path.join(outDir, 'demo.webm'));
    fs.writeFileSync(path.join(outDir, 'rec.json'), JSON.stringify(rec, null, 2), 'utf8');
  };
  try {
    await Promise.race([body(), new Promise((_, rej) => { timer = setTimeout(() => rej(new Refusal('timeout', `the recording did not finish within ${job.deadline} s`, true)), job.deadline * 1000); })]);
  } finally { await cleanup(); }
}

export async function main(argv) {
  const arg = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null; };
  if (!arg('--job') || !arg('--out')) { console.error('usage: quay-demo.mjs --job <job.json> --out <folder>'); return 2; }
  const job = JSON.parse(fs.readFileSync(arg('--job'), 'utf8'));
  const out = arg('--out');
  fs.mkdirSync(out, { recursive: true });
  try { await attempt({ deadline: 100, ...job }, out); return 0; }
  catch (e) {
    const r = e instanceof Refusal ? e : new Refusal('browser', `${e.name}: ${String(e.message).split('\n')[0].slice(0, 200)}`, true);
    fs.writeFileSync(path.join(out, 'refusal.json'), JSON.stringify({ kind: r.kind, why: r.message, retry: r.retry }), 'utf8');
    console.error(`demo: ${r.kind}: ${r.message}`);
    return 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).then((c) => process.exit(c), (e) => { console.error('demo: ' + e.message); process.exit(2); });
}

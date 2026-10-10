/* Offline Chrome check of the real event renderer/CSS with a fixed clock.
   Run: node tests/verify-event-times-browser.mjs
   Uses the existing local Puppeteer/Chrome installation; starts no HTTP server. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import puppeteer from 'puppeteer';

const events = JSON.parse(await readFile(new URL('../data/events.json', import.meta.url), 'utf8'));
const origin = 'http://event-times.test';
const html = `<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="feed.css">
<main class="feed-main"><section id="picks"><div class="picks-grid" id="picks-grid"></div></section></main>
<script type="module" src="feed.js"></script></html>`;
const browser = await puppeteer.launch({
  executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true, pipe:true,
});
console.log(`Chrome PID ${browser.process().pid}; offline event renderer; worktree ${process.cwd()}`);
try {
  for (const width of [375, 768, 1440]) {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewport({width, height:900});
    await page.emulateTimezone('America/Los_Angeles');
    await page.emulateMediaFeatures([{name:'prefers-reduced-motion', value:'no-preference'}]);
    await page.setRequestInterception(true);
    page.on('request', async request => {
      const url = new URL(request.url());
      if (url.origin !== origin) return request.abort();
      if (url.pathname === '/') return request.respond({status:200, contentType:'text/html', body:html});
      // Serve only real site modules/styles/fonts; never pass a request to the network.
      if (!/^\/[\w/-]+\.(?:js|css|woff2)$/.test(url.pathname)) return request.respond({status:404, body:''});
      try {
        let body = await readFile(new URL(`../site${url.pathname}`, import.meta.url));
        if (url.pathname === '/feed.js') {
          body = body.toString('utf8').split('\ninit();')[0] + `
            let testNow = Date.parse('2026-10-10T12:00:00Z');
            Date.now = () => testNow;
            window.eventTimeTest = {
              render(events) {
                D = {events, live:[], stories:[]};
                document.querySelector('#picks-grid').innerHTML = renderLive();
              },
              tick() { testNow += 1000; tickCountdowns(); }
            };`;
        }
        await request.respond({status:200, contentType:url.pathname.endsWith('.js') ? 'text/javascript'
          : url.pathname.endsWith('.css') ? 'text/css' : 'font/woff2', body});
      } catch { await request.respond({status:404, body:''}); }
    });
    await page.goto(origin, {waitUntil:'networkidle0'});
    await page.waitForFunction(() => window.eventTimeTest);
    await page.evaluate(rows => window.eventTimeTest.render(rows), events);
    await page.evaluate(() => document.fonts.ready);
    const layout = () => page.evaluate(() => ({
      boxes:[...document.querySelectorAll('.events > li, .event-name, .date-badge, .calbtn, .event-when')].map(el => {
        const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
      }),
      text:[...document.querySelectorAll('.event-when')].map(el => el.textContent),
      faces:[...document.querySelectorAll('.cd-face')].map(el => el.textContent),
      wraps:[...document.querySelectorAll('.cd')].filter(el => el.getBoundingClientRect().height > parseFloat(getComputedStyle(el).lineHeight) * 1.5).length,
      overflow:document.documentElement.scrollWidth > innerWidth,
    }));
    const before = await layout();
    await page.evaluate(() => window.eventTimeTest.tick());
    const after = await layout();
    assert.deepEqual(after.boxes, before.boxes, `${width}px: a countdown tick moved event content`);
    assert.notDeepEqual(after.faces, before.faces);
    assert.deepEqual(after.text, ['16 tháng 10 · 14:00 giờ Bengaluru (15:30 giờ Việt Nam)',
      '6–12 tháng 12 · Sydney, Australia · chưa rõ giờ khai mạc']);
    assert.equal(after.wraps, 0);
    assert.equal(after.overflow, false);
    await page.emulateMediaFeatures([{name:'prefers-reduced-motion', value:'reduce'}]);
    await page.evaluate(() => window.eventTimeTest.tick());
    assert.equal(await page.$eval('.cd-face', el => /\d{2}:\d{2}:\d{2}/.test(el.textContent)), false);
    assert.deepEqual(errors, []);
    console.log(`PASS ${width}px: local/Vietnam opening labels, no tick layout shift, no page overflow, reduced motion`);
    await page.close();
  }
} finally {
  await browser.close();
}

/* Offline Chrome check of the "Sự kiện" page's countdowns (renderBaThi, tickCountdowns) with the real CSS and a
   clock the test moves: the events' opening line and faces, a stream ticked across its scheduled start (it reads
   "Sắp bắt đầu", never live), no layout shift on a tick, no page overflow. 375, 768 and 1440 px.
   Run: node tests/verify-event-times-browser.mjs (tests/test_trang_su_kien.py runs it). Starts no HTTP server. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import puppeteer from 'puppeteer';

const events = JSON.parse(await readFile(new URL('../data/events.json', import.meta.url), 'utf8'));
const origin = 'http://event-times.test';
const html = `<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="feed.css"><link rel="stylesheet" href="trang-msn.css">
<main class="msn-main" style="padding:16px"><div class="msn-grid" id="feed-grid"></div></main>
<script type="module" src="feed.js"></script></html>`;
const NOW = Date.parse('2026-10-10T12:00:00Z');
const stream = {video_id:'tick-soon', status:'upcoming', title:'A stream about to start', channel:'OpenAI', thumbnail:'',
  url:'https://www.youtube.com/watch?v=tick-soon', start_at:new Date(NOW + 90e3).toISOString(), end_at:null};
const browser = await puppeteer.launch({
  executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe', headless:true, pipe:true,
});
console.log(`Chrome PID ${browser.process().pid}; offline "Sự kiện" countdowns; worktree ${process.cwd()}`);
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
            let testNow = ${NOW};
            Date.now = () => testNow;
            window.eventTimeTest = {
              render(events, live) {
                D = {events, live, stories:[]};
                document.querySelector('#feed-grid').innerHTML = renderBaThi();
              },
              tick(ms) { testNow += ms; tickCountdowns(); }
            };`;
        }
        await request.respond({status:200, contentType:url.pathname.endsWith('.js') ? 'text/javascript'
          : url.pathname.endsWith('.css') ? 'text/css' : 'font/woff2', body});
      } catch { await request.respond({status:404, body:''}); }
    });
    await page.goto(origin, {waitUntil:'networkidle0'});
    await page.waitForFunction(() => window.eventTimeTest);
    await page.evaluate((rows, live) => window.eventTimeTest.render(rows, live), events, [stream]);
    await page.evaluate(() => document.fonts.ready);
    const state = () => page.evaluate(() => {
      const shown = el => el.getClientRects().length > 0;
      const next = document.querySelector('.bt-next .ev-count');
      return {
        boxes:[...document.querySelectorAll('.bt-lane, .ev-row, .ev-name, .calbtn, .bt-what, .ev-count')].filter(shown).map(el => {
          const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
        }),
        lead:document.querySelector('.bt-lead .ev-name').textContent,
        note:document.querySelector('.bt-lead .ev-note')?.textContent || null,
        stream:next ? {cls:next.className, sr:next.querySelector('.sr').textContent, face:next.querySelector('.cd-face').textContent} : null,
        live:document.querySelectorAll('.bt-live').length,
        clocks:[...document.querySelectorAll('.cd-face')].filter(el => /\d{2}:\d{2}:\d{2}/.test(el.textContent)).length,
        overflow:document.documentElement.scrollWidth > innerWidth,
      };
    });
    const before = await state();
    assert.equal(before.lead, events[0].title, `${width}px: the nearest event leads`);
    assert.equal(before.note, 'Khai mạc 15:30 giờ Việt Nam');
    assert.deepEqual(before.stream, {cls:'ev-count cd is-soon', sr:'Còn 1 phút', face:'1phútnữa'});
    // One second later nothing on the page moves.
    await page.evaluate(() => window.eventTimeTest.tick(1000));
    const second = await state();
    assert.deepEqual(second.boxes, before.boxes, `${width}px: a countdown tick moved content`);
    // Across the scheduled start: the stream has not gone live, and the page says so.
    await page.evaluate(() => window.eventTimeTest.tick(120e3));
    const after = await state();
    assert.deepEqual(after.stream, {cls:'ev-count cd is-due', sr:'Đã tới giờ phát, chưa lên sóng', face:'Sắp bắt đầu'});
    assert.equal(after.live, 0);
    // A fresh draw past the hour reads the same.
    await page.evaluate((rows, live) => window.eventTimeTest.render(rows, live), events, [stream]);
    assert.deepEqual((await state()).stream, after.stream);
    await page.emulateMediaFeatures([{name:'prefers-reduced-motion', value:'reduce'}]);
    await page.evaluate(() => window.eventTimeTest.tick(60e3));
    const reduced = await state();
    assert.equal(reduced.clocks, 0);
    assert.equal(reduced.overflow, false);
    assert.deepEqual(errors, []);
    console.log(`PASS ${width}px: opening line, a stream past its hour reads "Sắp bắt đầu", no tick layout shift, no overflow`);
    await page.close();
  }
} finally {
  await browser.close();
}

// Capture the installed extension with the background worker's live snapshot.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const puppeteer = require('puppeteer');

const root = path.resolve(__dirname, '..');
const extension = path.join(root, 'extension');
const output = path.join(__dirname, 'assets', 'store');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ar-store-'));

async function main() {
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      pipe: true,
      enableExtensions: true,
      userDataDir: profile,
      executablePath: process.env.CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    });
    const id = await browser.installExtension(extension);
    const target = await browser.waitForTarget(item =>
      item.type() === 'service_worker' && item.url().startsWith(`chrome-extension://${id}/`),
    {timeout: 20000});
    const worker = await target.worker();
    const snapshot = await worker.evaluate(async () => {
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        const {radarWindow, radarFetchedAt} = await chrome.storage.local.get(['radarWindow', 'radarFetchedAt']);
        if (radarWindow?.schema_version === 2 && radarWindow.stories?.length && radarFetchedAt) {
          return {generatedAt: radarWindow.generated_at, stories: radarWindow.stories.length};
        }
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      throw new Error('Background worker did not save the live radar-window.json');
    });
    const bangkokDay = value => new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date(value));
    if (!snapshot.generatedAt || bangkokDay(snapshot.generatedAt) !== bangkokDay(Date.now())) {
      throw new Error(`Live radar-window.json is not from today: ${snapshot.generatedAt}`);
    }

    fs.mkdirSync(output, {recursive: true});
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewport({width: 1280, height: 800, deviceScaleFactor: 1});
    const url = `chrome-extension://${id}/newtab.html`;
    await page.goto(url, {waitUntil: 'domcontentloaded'});
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => localStorage.setItem('air2:theme', JSON.stringify(value)), theme);
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => {
        const top = document.querySelector('#top');
        return top?.getAttribute('aria-busy') !== 'true' && document.querySelectorAll('.feed-card').length > 0;
      }, {timeout: 30000});
      await page.evaluate(async () => {
        await document.fonts.ready;
        await Promise.race([
          Promise.all([...document.images].map(image => image.complete ? null :
            new Promise(resolve => { image.addEventListener('load', resolve, {once: true}); image.addEventListener('error', resolve, {once: true}); }))),
          new Promise(resolve => setTimeout(resolve, 10000)),
        ]);
      });
      const details = await page.evaluate(() => ({
        theme: document.documentElement.dataset.theme,
        cards: document.querySelectorAll('.feed-card').length,
        overflow: document.documentElement.scrollWidth > innerWidth,
      }));
      if (details.theme !== theme || details.overflow) throw new Error(`Invalid ${theme} page: ${JSON.stringify(details)}`);
      await page.screenshot({path: path.join(output, `new-tab-${theme}.png`), fullPage: false});
      console.log(`new-tab-${theme}.png: 1280x800, ${details.cards} live cards`);
    }
    if (errors.length) throw new Error(`Page errors: ${JSON.stringify(errors)}`);
    console.log(`Live snapshot: ${snapshot.generatedAt}, ${snapshot.stories} stories`);
    await page.close();
  } finally {
    if (browser) await browser.close();
    if (path.dirname(profile) === os.tmpdir() && path.basename(profile).startsWith('ar-store-')) {
      fs.rmSync(profile, {recursive: true, force: true});
    }
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });

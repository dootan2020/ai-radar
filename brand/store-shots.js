// Capture the Chrome Web Store screenshots from the real extension: install extension/ unpacked in headless Chrome,
// let its own worker save the live radar-window.json, then shoot its new tab at 1280x800 in light and dark.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
let puppeteer;
try { puppeteer = require('puppeteer'); } catch { puppeteer = require('puppeteer-core'); }

const root = path.resolve(__dirname, '..');
const extension = path.join(root, 'extension');
const output = path.join(extension, 'store', 'anh');
const names = {light: 'screenshot-1-sang-1280x800.png', dark: 'screenshot-2-toi-1280x800.png'};
// The site's own freshness limit (radar/publication.py STALE_AFTER_SECONDS): an older snapshot is not "today's".
const STALE_AFTER_MS = 3 * 3600 * 1000;

async function main() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ar-store-'));
  let browser;
  try {
    // Branded Chrome ignores --load-extension; Puppeteer installs the unpacked folder over the CDP pipe instead.
    browser = await puppeteer.launch({headless: true, pipe: true, enableExtensions: true, userDataDir: profile,
      executablePath: process.env.CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'});
    const id = await browser.installExtension(extension);
    fs.mkdirSync(output, {recursive: true});
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewport({width: 1280, height: 800, deviceScaleFactor: 1});
    const url = `chrome-extension://${id}/newtab.html`;
    await page.goto(url, {waitUntil: 'domcontentloaded'});
    // The worker refreshes on install; wait for the snapshot it saves, exactly as a first install does.
    const saved = await page.waitForFunction(async () => {
      const {radarWindow, radarFetchedAt} = await chrome.storage.local.get(['radarWindow', 'radarFetchedAt']);
      return radarWindow && radarFetchedAt ? {generated: radarWindow.generated_at, stories: radarWindow.stories.length} : null;
    }, {timeout: 30000, polling: 500}).then(handle => handle.jsonValue());
    const age = Date.now() - Date.parse(saved.generated);
    if (!(age >= 0 && age <= STALE_AFTER_MS) || !saved.stories) {
      throw new Error(`Stale or empty live snapshot: ${JSON.stringify(saved)}`);
    }
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => localStorage.setItem('air2:theme', JSON.stringify(value)), theme);
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => {
        const top = document.querySelector('#top');
        return top?.getAttribute('aria-busy') !== 'true' && document.querySelectorAll('.tile').length > 0;
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
        cards: document.querySelectorAll('.tile').length,
        overflow: document.documentElement.scrollWidth > innerWidth,
      }));
      if (details.theme !== theme || details.overflow) throw new Error(`Invalid ${theme} page: ${JSON.stringify(details)}`);
      await page.screenshot({path: path.join(output, names[theme]), fullPage: false});
      console.log(`${names[theme]}: 1280x800, ${details.cards} cards`);
    }
    if (errors.length) throw new Error(`Page errors: ${JSON.stringify(errors)}`);
    console.log(`Live snapshot: ${saved.generated}, ${saved.stories} stories, extension ${id}`);
  } finally {
    if (browser) await browser.close();
    if (path.dirname(profile) === os.tmpdir() && path.basename(profile).startsWith('ar-store-')) {
      fs.rmSync(profile, {recursive: true, force: true});
    }
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });

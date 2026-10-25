const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const puppeteer = require('puppeteer');

const root = path.resolve(__dirname, '../..');
const ext = path.join(root, 'extension');
const out = path.join(root, 'plans/reports/port');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'radar-window-sample.json'), 'utf8'));
fs.mkdirSync(out, {recursive: true});

async function main() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ar-'));
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      pipe: true,
      enableExtensions: true,
      userDataDir: profile,
      executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    });
    console.log('Chrome launched');
    const id = await browser.installExtension(ext);
    console.log(`Extension installed: ${id}`);
    const target = await browser.waitForTarget(item => item.type() === 'service_worker' && item.url().startsWith(`chrome-extension://${id}/`), {timeout: 20000});
    const worker = await target.worker();
    const url = `chrome-extension://${id}/newtab.html`;
    const page = await browser.newPage();
    const errors = [];
    let offline = false;
    page.on('pageerror', error => errors.push(error.message));
    await page.setRequestInterception(true);
    page.on('request', request => {
      if (offline && request.url().startsWith('https:')) request.abort('internetdisconnected');
      else request.continue();
    });
    await worker.evaluate(data => chrome.storage.local.set({radarWindow: data, radarFetchedAt: new Date().toISOString()}), fixture);

    async function shot(name, width, height, theme, state = 'cached') {
      await page.setViewport({width, height, deviceScaleFactor: 1, isMobile: width === 375});
      offline = state === 'offline';
      if (state === 'empty') await worker.evaluate(() => chrome.storage.local.clear());
      else await worker.evaluate(data => chrome.storage.local.set({radarWindow: data, radarFetchedAt: new Date().toISOString()}), fixture);
      await page.goto(url, {waitUntil: 'domcontentloaded'});
      await page.evaluate(value => {
        localStorage.setItem('air2:theme', JSON.stringify(value));
        document.documentElement.dataset.theme = value;
      }, theme);
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => {
        const top = document.querySelector('#top');
        return top && top.getAttribute('aria-busy') !== 'true';
      }, {timeout: 20000});
      await page.screenshot({path: path.join(out, `${name}.png`), fullPage: false});
      const info = await page.evaluate(() => ({
        cards: document.querySelectorAll('.feed-card').length,
        heading: document.querySelector('#feed-empty h2')?.textContent,
        search: !!document.querySelector('#web-query'),
        overflow: document.documentElement.scrollWidth > innerWidth,
        localImageUrls: [...document.querySelectorAll('img')].filter(img => img.src.startsWith(location.origin + '/assets/ai/')).length,
      }));
      console.log(`${name}: ${JSON.stringify(info)}`);
      if (!info.search || info.overflow || info.localImageUrls ||
          (state === 'empty' ? info.cards !== 0 || !info.heading : info.cards === 0)) {
        throw new Error(`${name}: unexpected page state ${JSON.stringify(info)}`);
      }
    }

    for (const width of [1280, 1440, 2560, 375]) {
      for (const theme of ['light', 'dark']) await shot(`${width}-${theme}`, width, width === 375 ? 812 : 1000, theme);
    }
    await shot('1440-empty-light', 1440, 1000, 'light', 'empty');
    await shot('1440-offline-light', 1440, 1000, 'light', 'offline');
    console.log(`Page errors: ${JSON.stringify(errors)}`);
    if (errors.length) throw new Error(`Page errors: ${JSON.stringify(errors)}`);
    await page.close();
  } finally {
    if (browser) await browser.close();
    if (path.dirname(profile) === os.tmpdir() && path.basename(profile).startsWith('ar-')) {
      fs.rmSync(profile, {recursive: true, force: true});
    }
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });

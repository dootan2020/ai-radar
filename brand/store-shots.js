// Capture the extension new tab with a local, real site snapshot.
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const puppeteer = require('puppeteer');

const root = path.resolve(__dirname, '..');
const extension = path.join(root, 'extension');
const output = path.join(__dirname, 'assets', 'store');
const snapshotPath = path.join(root, 'site', 'data', 'radar-window.json');
const mime = {'.css': 'text/css', '.html': 'text/html', '.ico': 'image/x-icon',
  '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml'};

function localServer() {
  return http.createServer((request, response) => {
    const file = path.resolve(extension, `.${new URL(request.url, 'http://localhost').pathname}`);
    if (!file.startsWith(extension + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404).end();
      return;
    }
    response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(response);
  });
}

async function main() {
  const snapshot = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
  if (snapshot.schema_version !== 2 || !Array.isArray(snapshot.stories) || !snapshot.stories.length) {
    throw new Error(`${snapshotPath} is not a populated radar-window snapshot`);
  }
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ar-store-'));
  const server = localServer();
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await puppeteer.launch({headless: true, pipe: true, userDataDir: profile,
      executablePath: process.env.CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'});
    fs.mkdirSync(output, {recursive: true});
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewport({width: 1280, height: 800, deviceScaleFactor: 1});
    await page.evaluateOnNewDocument(value => {
      globalThis.chrome = {
        storage: {onChanged: {addListener() {}}, local: {async get() {return {radarWindow: value};}}},
        search: {query() {}},
      };
    }, snapshot);
    await page.setRequestInterception(true);
    page.on('request', request => {
      if (request.url() === 'https://radar-ai-vn.pages.dev/data/radar-ui.json') {
        return request.respond({status: 200, contentType: 'application/json', body: JSON.stringify(snapshot)});
      }
      return request.continue();
    });
    const url = `http://127.0.0.1:${server.address().port}/newtab.html`;
    for (const theme of ['light', 'dark']) {
      await page.goto(url, {waitUntil: 'domcontentloaded'});
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
      console.log(`new-tab-${theme}.png: 1280x800, ${details.cards} local snapshot cards`);
    }
    if (errors.length) throw new Error(`Page errors: ${JSON.stringify(errors)}`);
    console.log(`Local snapshot: ${snapshot.generated_at}, ${snapshot.stories.length} stories`);
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
    if (path.dirname(profile) === os.tmpdir() && path.basename(profile).startsWith('ar-store-')) {
      fs.rmSync(profile, {recursive: true, force: true});
    }
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });

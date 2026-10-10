// Render the local snapshot with Chrome; run against a server for this worktree.
// node tests/verify-original-hints.mjs --url http://127.0.0.1:8808 --out plans/reports/original-hints
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer';

const arg = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : process.argv[index + 1];
};
const url = arg('--url', 'http://127.0.0.1:8808');
const out = arg('--out', 'plans/reports/original-hints');
const widths = arg('--widths', '375,1024,1440,1920').split(',').map(Number);
const themes = arg('--themes', 'light,dark').split(',');
await fs.mkdir(out, { recursive: true });
// Refuse to certify a server serving a different worktree or stale stylesheet.
for (const file of ['index.html', 'feed.css', 'feed.js', 'data/radar-ui.json']) {
  const response = await fetch(`${url}/${file}`, { signal: AbortSignal.timeout(10000) });
  assert.equal(response.status, 200, file);
  assert.equal(await response.text(), await fs.readFile(new URL(`../site/${file}`, import.meta.url), 'utf8'), file);
}
console.log(`Verified server files at ${url}; launching Chrome`);
const browser = await puppeteer.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--disable-gpu'],
  userDataDir: await fs.mkdtemp(path.join(path.resolve(out), 'chrome-profile-')),
  timeout: 15000,
});
console.log(`Chrome PID ${browser.process().pid}; server ${url} reused; worktree ${process.cwd()}`);
const results = [];
const failures = [];
try {
  for (const theme of themes) for (const width of widths) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: width >= 1920 ? 1080 : 900, deviceScaleFactor: 1 });
    await page.evaluateOnNewDocument(theme => {
      localStorage.setItem('air2:theme', JSON.stringify(theme));
    }, theme);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card-lead .card-title');
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => document.querySelectorAll('.card-orig').length > 1);
    // Finish entrances before measuring, without changing the production layout.
    await page.evaluate(async () => {
      await Promise.all(document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity)
        .map(a => a.finished.catch(() => {})));
    });
    const result = await page.evaluate(() => {
      const box = el => {
        const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, height: r.height, left: r.left, right: r.right, width: r.width };
      };
      const lead = document.querySelector('.card-lead');
      return {
        headline: box(lead.querySelector('.card-title')),
        source: box(lead.querySelector('.src-row')),
        lead: box(lead),
        overflow: document.documentElement.scrollWidth > innerWidth,
        footers: [...document.querySelectorAll('.card-foot')].map(footer => {
          const metric = footer.querySelector('.metric');
          const actions = footer.querySelector('.card-actions');
          const items = [...metric.children].map(box);
          const controls = [...footer.querySelectorAll('button')].map(box);
          const metricGap = parseFloat(getComputedStyle(metric).columnGap);
          const footerGap = parseFloat(getComputedStyle(footer).columnGap);
          return {
            ...box(footer),
            cardId: footer.closest('.feed-card').dataset.sid,
            metric: box(metric), actions: box(actions), items, controls,
            requiredWidth: items.reduce((sum, item) => sum + item.width, 0)
              + metricGap * Math.max(0, items.length - 1) + footerGap + box(actions).width,
          };
        }),
        originals: [...document.querySelectorAll('.card-orig')].map(el => ({
          ...box(el),
          lineHeight: parseFloat(getComputedStyle(el).lineHeight),
          clamp: getComputedStyle(el).webkitLineClamp,
          chipBaseline: getComputedStyle(el.querySelector('.mt')).verticalAlign,
          text: el.querySelector('.orig-text').textContent,
          card: el.closest('.feed-card').className,
          cardHeight: el.closest('.feed-card').getBoundingClientRect().height,
        })),
      };
    });
    const session = await page.createCDPSession();
    const { nodes } = await session.send('Accessibility.getFullAXTree');
    const accessibleTexts = nodes.filter(n => !n.ignored && n.role?.value === 'StaticText').map(n => n.name?.value);
    result.fullOriginalsAccessible = result.originals.every(o => accessibleTexts.includes(o.text));
    await page.screenshot({ path: path.join(out, `${theme}-${width}.png`) });
    results.push({ theme, width, ...result });
    const check = (ok, message) => { if (!ok) failures.push(`${theme} ${width}: ${message}`); };
    check(result.originals.length > 0, 'no originals rendered');
    check(!result.overflow, 'horizontal overflow');
    check(result.fullOriginalsAccessible, 'full original absent from accessibility tree');
    for (const footer of result.footers) {
      const label = `footer ${footer.cardId}`;
      if (footer.requiredWidth <= footer.width + 0.5) {
        check(Math.abs(footer.metric.top - footer.actions.top) <= 1
          && footer.items.every(item => item.top >= footer.actions.top - 1 && item.bottom <= footer.actions.bottom + 1),
        `${label} wraps although its contents fit`);
      }
      check(footer.controls.every(control => control.width >= 43.5 && control.height >= 43.5),
        `${label} has a control smaller than 44px`);
      const pieces = [...footer.items, ...footer.controls.slice(1)];
      check(pieces.every(piece => piece.left >= footer.left - 0.5 && piece.right <= footer.right + 0.5
        && piece.top >= footer.top - 0.5 && piece.bottom <= footer.bottom + 0.5), `${label} clips its contents`);
      check(pieces.every((a, index) => pieces.slice(index + 1).every(b =>
        Math.min(a.right, b.right) - Math.max(a.left, b.left) <= 0.5
        || Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) <= 0.5)), `${label} overlaps controls or text`);
    }
    for (const original of result.originals) {
      check(original.clamp === '2' && original.height <= original.lineHeight * 2 + 1,
        `original exceeds two lines (${original.height}px): ${original.text.slice(0, 70)}`);
      check(original.chipBaseline === 'baseline', 'chip lost baseline alignment');
    }
    if (width >= 1024) {
      check(result.headline.top >= 0 && result.headline.bottom <= 760, 'lead headline extends below 760px');
      check(result.source.bottom <= 900, 'lead source outside first screen');
    }
    console.log(JSON.stringify({ theme, width, headlineBottom: result.headline.bottom,
      leadHeight: result.lead.height, originals: result.originals.length,
      fullOriginalsAccessible: result.fullOriginalsAccessible }));
    await page.close();
  }
  await fs.writeFile(path.join(out, 'measurements.json'), JSON.stringify(results, null, 2) + '\n');
  assert.deepEqual(failures, [], failures.join('\n'));
  console.log('PASS two-line originals, accessible full text, baseline alignment, compact reachable footers and lead headlines above 760px');
} finally {
  await browser.close();
}

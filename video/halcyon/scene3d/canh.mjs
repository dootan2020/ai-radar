// Renderer of the giao-thuc scene: installed Chrome, headless, GPU on; the page is served from disk under a made-up origin (Chrome will not
// import ES modules over file://) and every other request is aborted and counted. For each frame f: renderAt(f / fps), measure the labels,
// screenshot the stage at final size, pipe the PNG to ffmpeg (h264_nvenc, BT.601 tv range, the matrix the builder decodes with).
// Writes clip.mp4 and render.json in --out. Started by canh.py; playwright-core and three resolve from --node-dir (the chain's video/ folder).
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : undefined; };
const SCENE = arg('--scene'), DATA = arg('--data'), THREE = arg('--three'), FONTS = (arg('--fonts') || '').split(path.delimiter).filter(Boolean), OUT = arg('--out');
const req = createRequire(path.join(arg('--node-dir'), 'package.json'));
const { chromium } = req('playwright-core');
const data = JSON.parse(fs.readFileSync(DATA, 'utf8'));
const { w: W, h: H, fps: FPS, frames: N } = data;
const SAFE_BOTTOM = 890, COL_Y = 476, COL_X = 800, MIN = 28;
const ORIGIN = 'http://canh.local/';
const errLog = fs.createWriteStream(path.join(OUT, 'render.err'));
const say = (s) => { process.stdout.write(s + '\n'); };

const files = {
  'index.html': [path.join(SCENE, 'scene.html'), 'text/html'],
  'giao-thuc.js': [path.join(SCENE, 'giao-thuc.js'), 'text/javascript'],
  'three.module.js': [path.join(THREE, 'three.module.js'), 'text/javascript'],
  'three.core.js': [path.join(THREE, 'three.core.js'), 'text/javascript'],
  'data.json': [DATA, 'application/json'],
};
for (const n of ['BeVietnamPro-SemiBold.ttf', 'BeVietnamPro-Medium.ttf', 'BarlowCondensed-ExtraBold.ttf', 'JetBrainsMono-Medium.ttf']) {
  const d = FONTS.find((x) => fs.existsSync(path.join(x, n)));
  if (d) files['fonts/' + n] = [path.join(d, n), 'font/ttf'];
}

let served = 0, aborted = 0; const abortedUrls = [];
const opts = { headless: true, args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--disable-features=Translate,MediaRouter', '--force-color-profile=srgb', '--hide-scrollbars'] };
if (process.env.CHROME_PATH) opts.executablePath = process.env.CHROME_PATH; else opts.channel = 'chrome';
const browser = await chromium.launch(opts);
let ff;
try {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, acceptDownloads: false, serviceWorkers: 'block', colorScheme: 'dark', reducedMotion: 'no-preference' });
  await ctx.route('**/*', async (route) => {
    const u = route.request().url();
    if (u.startsWith(ORIGIN)) {
      const f = files[u.slice(ORIGIN.length).split('?')[0] || 'index.html'];
      if (f) { served++; return route.fulfill({ status: 200, contentType: f[1], body: fs.readFileSync(f[0]) }); }
    }
    aborted++; if (abortedUrls.length < 10) abortedUrls.push(u);
    return route.abort();
  });
  const page = await ctx.newPage();
  page.on('console', (m) => errLog.write(`console ${m.type()}: ${m.text()}\n`));
  page.on('pageerror', (e) => errLog.write(`pageerror: ${e.message}\n`));
  await page.goto(ORIGIN + 'index.html');
  await page.waitForFunction(() => window.sceneReady === true, null, { timeout: 60000 });
  const info = await page.evaluate(() => ({ ...window.sceneInfo, fonts: window.sceneFonts }));
  say(`WebGL: ${info.vendor} | ${info.renderer} | three r${info.three}`);
  if (arg('--stills')) {               // look-only mode: PNG stills at the given seconds, no clip
    for (const [i, s] of arg('--stills').split(',').map(Number).entries()) {
      const labs = await page.evaluate((t) => { window.renderAt(t); return window.labels(); }, s);
      await page.screenshot({ path: path.join(OUT, `still-${String(i).padStart(2, '0')}-${s.toFixed(2)}.png`), clip: { x: 0, y: 0, width: W, height: H }, type: 'png' });
      say(`still ${s}: ` + labs.map((l) => `"${l.text.slice(0, 18)}"@${l.x.toFixed(0)},${l.y.toFixed(0)}+${l.w.toFixed(0)}x${l.h.toFixed(0)} ${l.size}px op${l.op.toFixed(2)}`).join(' | '));
    }
    process.exitCode = 0;
  } else {

  ff = spawn('ffmpeg', ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
    '-vf', 'scale=out_color_matrix=bt601:out_range=tv,format=yuv420p', '-c:v', 'h264_nvenc', '-preset', 'p7', '-tune', 'hq', '-rc', 'constqp', '-qp', '14',
    '-profile:v', 'high', '-g', String(FPS), '-bf', '0', '-colorspace', 'smpte170m', '-color_primaries', 'smpte170m', '-color_trc', 'smpte170m', '-color_range', 'tv',
    '-r', String(FPS), '-movflags', '+faststart', path.join(OUT, 'clip.mp4')], { stdio: ['pipe', 'inherit', 'pipe'] });
  let ffErr = ''; ff.stderr.on('data', (d) => { ffErr += d; });
  const ffDone = new Promise((res) => ff.on('close', (c) => res(c)));

  const clip = { x: 0, y: 0, width: W, height: H };
  const hashes = [];
  const viol = []; let minSize = 1e9, checked = 0;
  // warm-up: every material compiled and every texture uploaded before frame 0 is kept (a fresh page's first render measured up to 98 levels off)
  for (const s of [0, 5, 10, 14, 17, 19, 22.2, 25, 0]) { await page.evaluate((t) => window.renderAt(t), s); await page.screenshot({ clip, type: 'png' }); }
  const pick = [Math.floor(N * .17), Math.floor(N * .55), N - 1];
  const t0 = process.hrtime.bigint();
  for (let f = 0; f < N; f++) {
    const labs = await page.evaluate((t) => { window.renderAt(t); return window.labels(); }, f / FPS);
    checked++;
    for (const l of labs) {
      if (l.op < .02 || !l.text.trim()) continue;
      minSize = Math.min(minSize, l.size);
      const where = `f${f} "${l.text.slice(0, 24)}"`;
      if (l.size < MIN) viol.push(`${where} is ${l.size} px`);
      if (l.x < 0 || l.y < 0 || l.x + l.w > W + .5) viol.push(`${where} leaves the canvas (${l.x.toFixed(0)},${l.y.toFixed(0)} ${l.w.toFixed(0)}x${l.h.toFixed(0)})`);
      if (l.y + l.h > SAFE_BOTTOM) viol.push(`${where} reaches y ${(l.y + l.h).toFixed(0)}, under the subtitle (limit ${SAFE_BOTTOM})`);
      if (l.y + l.h > COL_Y && l.x + l.w > COL_X) viol.push(`${where} reaches x ${(l.x + l.w).toFixed(0)} below y ${COL_Y}, under the button column (limit ${COL_X})`);
    }
    const solid = labs.filter((l) => l.op >= .5 && l.text.trim());
    for (let i = 0; i < solid.length; i++) for (let j = i + 1; j < solid.length; j++) {
      const a = solid[i], b = solid[j];
      const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), iy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (ix > 2 && iy > 2) viol.push(`f${f} "${a.text.slice(0, 20)}" overlaps "${b.text.slice(0, 20)}"`);
    }
    const png = await page.screenshot({ clip, type: 'png', animations: 'allow', caret: 'initial', scale: 'css' });
    hashes.push(createHash('sha256').update(png).digest('hex'));
    if (pick.includes(f)) fs.writeFileSync(path.join(OUT, `det-${f}-a.png`), png);
    if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once('drain', r));
    if (f % 150 === 0) say(`frame ${f}/${N}`);
  }
  ff.stdin.end();
  const code = await ffDone;
  const seconds = Number(process.hrtime.bigint() - t0) / 1e9;
  if (code !== 0) throw new Error('h264_nvenc encode failed: ' + ffErr.slice(-800));
  // determinism: three frames rendered again, in reverse order, after everything else; canh.py compares the pixels of each pair (det-<f>-a/b.png)
  const again = [];
  for (const f of [...pick].reverse()) {
    await page.evaluate((t) => window.renderAt(t), f / FPS);
    const png = await page.screenshot({ clip, type: 'png', animations: 'allow', caret: 'initial', scale: 'css' });
    fs.writeFileSync(path.join(OUT, `det-${f}-b.png`), png);
    again.push({ f, first: hashes[f].slice(0, 16), again: createHash('sha256').update(png).digest('hex').slice(0, 16) });
  }
  const equal = again.every((x) => x.first === x.again);
  const rj = { renderer: info.renderer, vendor: info.vendor, three: info.three, fonts: info.fonts, served, aborted, aborted_urls: abortedUrls, frames: hashes.length,
    seconds: Math.round(seconds * 10) / 10, ms_per_frame: Math.round(seconds * 1000 / N), determinism: { equal, frames: again },
    labels: { min_size: minSize === 1e9 ? 0 : minSize, frames: checked, violations: [...new Set(viol)].slice(0, 40) } };
  fs.writeFileSync(path.join(OUT, 'render.json'), JSON.stringify(rj, null, 1));
  say(`rendered ${hashes.length} frames in ${rj.seconds} s (${rj.ms_per_frame} ms/frame); served ${served}, aborted ${aborted}; same bytes twice ${equal} (pixels compared by canh.py); label problems ${rj.labels.violations.length}`);
  }
} finally {
  if (ff && ff.exitCode === null && !ff.stdin.writableEnded) { try { ff.stdin.end(); } catch {} }
  await browser.close();
  errLog.end();
}

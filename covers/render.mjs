// Covers for stories without a picture, drawn from each story's own facts and rendered locally by headless Chrome.
//
//   node covers/render.mjs [--count 8] [--data <radar-window.json url or file>]
//
// Takes the live snapshot, picks the N most recent stories with no image, renders each in every direction under
// covers/templates/ at the feed card's picture frame, 2x, and draws one contact sheet per direction in the real card
// layout (site CSS) at 375 and 1440 px. Everything lands in covers/out/ (git-ignored).
//
// Frame sizes, measured on the live page rendered locally on 2026-11-10 (.nc-photo, site/trang-msn.css):
//   1440 px feed: 260.9 x 148 css px (1.763:1)  ->  cover  522 x 296 px  (<id>.png)
//    375 px feed: 167.5 x 112 css px (1.496:1)  ->  cover  336 x 224 px  (<id>-phone.png)
// The frame keeps its height and follows the column width, so other widths differ (1024 px: 2.10:1, >=1750 px: 1.47:1).
import { mkdirSync, writeFileSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch } from './lib/cdp.mjs';
import { serve } from './lib/serve.mjs';
import { factsOf, hasImage } from './lib/facts.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const OUT = join(HERE, 'out');
const LIVE = 'https://radar-ai-vn.pages.dev/data/radar-window.json';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const FRAMES = [{ suffix: '', w: 261, h: 148 }, { suffix: '-phone', w: 168, h: 112 }];
const SHEETS = [{ w: 375, h: 812, mobile: true }, { w: 1440, h: 900, mobile: false }];

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt; };
const COUNT = Number(arg('count', 8));
const DATA = arg('data', LIVE);

async function loadSnapshot() {
  if (!/^https?:/.test(DATA)) return JSON.parse(readFileSync(DATA, 'utf8'));
  const r = await fetch(DATA, { headers: { 'user-agent': UA, accept: 'application/json' } });
  if (!r.ok) throw new Error(`${DATA}: HTTP ${r.status}`);
  return r.json();
}

const monoHue = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const byNew = (a, b) => String(b.published_at || '').localeCompare(String(a.published_at || ''));
function cardOf(st, f, gen) {
  const title = st.editorial_headline_vi || st.title_vi || st.title;
  const hours = Math.max(0, Math.round((Date.parse(gen) - Date.parse(st.published_at)) / 36e5));
  return { id: st.id, title, translated: title !== st.title, source: f.source, mono: f.face.mono, monoHue: monoHue(f.source),
    faceSrc: f.face.kind === 'gh' ? f.face.src.replace('s=256', 's=40') : null, ago: hours ? `${hours} giờ trước` : 'Vừa xong' };
}

const t0 = Date.now();
const snap = await loadSnapshot();
const sources = new Map((snap.sources || []).map(s => [s.id, s]));
const stories = snap.stories || [];
const bare = stories.filter(s => !hasImage(s)).sort(byNew);
const pick = bare.slice(0, COUNT);
console.log(`snapshot ${snap.generated_at}: ${stories.length} stories, ${bare.length} without an image; covering the ${pick.length} newest`);
mkdirSync(join(OUT, 'data'), { recursive: true });
writeFileSync(join(OUT, 'data', 'radar-window.json'), JSON.stringify(snap));

const facts = pick.map(st => factsOf(st, sources));
writeFileSync(join(OUT, 'facts.json'), JSON.stringify(facts, null, 2));
const photos = stories.filter(s => hasImage(s) && (s.image.kind || 'photo') === 'photo').sort(byNew).slice(0, 2);
writeFileSync(join(OUT, 'sheet-data.json'), JSON.stringify({
  covers: pick.map((st, i) => cardOf(st, facts[i], snap.generated_at)),
  photos: photos.map(st => ({ ...cardOf(st, factsOf(st, sources), snap.generated_at), image: st.image.src })),
}));

const directions = readdirSync(join(HERE, 'templates')).filter(n => n.endsWith('.html')).map(n => n.replace(/\.html$/, ''));
const srv = await serve(ROOT);
const chrome = await launch();
const timings = [];
try {
  for (const dir of directions) {
    mkdirSync(join(OUT, dir), { recursive: true });
    for (const f of facts) {
      for (const fr of FRAMES) {
        const s = Date.now();
        await chrome.viewport(fr.w, fr.h, 2);
        await chrome.goto('about:blank');
        await chrome.goto(`${srv.url}/covers/templates/${dir}.html#${encodeURIComponent(JSON.stringify(f))}`);
        await chrome.waitReady();
        writeFileSync(join(OUT, dir, `${f.id}${fr.suffix}.png`), await chrome.screenshot({ x: 0, y: 0, width: fr.w, height: fr.h }));
        timings.push(Date.now() - s);
      }
    }
    for (const sh of SHEETS) {
      await chrome.viewport(sh.w, sh.h, 1, sh.mobile);
      await chrome.goto(`${srv.url}/covers/contact-sheet.html?dir=${dir}`);
      await chrome.waitReady(30000);
      const height = await chrome.evaluate('Math.ceil(document.documentElement.scrollHeight)');
      writeFileSync(join(OUT, `sheet-${dir}-${sh.w}.png`), await chrome.screenshot({ x: 0, y: 0, width: sh.w, height }));
    }
    console.log(`${dir}: ${facts.length * FRAMES.length} covers, 2 sheets`);
  }
} finally {
  await chrome.close();
  srv.close();
}
const avg = timings.reduce((a, b) => a + b, 0) / Math.max(1, timings.length);
console.log(`rendered ${timings.length} covers, ${Math.round(avg)} ms each on average; total ${((Date.now() - t0) / 1000).toFixed(1)} s -> ${OUT}`);

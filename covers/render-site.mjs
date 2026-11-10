// Render the "Con số" cover of every story in a request, reusing a cover whose facts have not changed.
//
//   node covers/render-site.mjs <request.json> <result.json>
//
// request: {"stories": [...], "sources": [...], "out_dir": "site/assets/cover"}   (radar/covers.py writes it)
// result:  {"covers": {"<id>": {"src": "assets/cover/<id>-<hash>.png", "tall": "...-t.png", "hero": "figure|name|outlet"}},
//           "rendered": n, "reused": n, "failed": {"<id>": "reason"}}
// A cover's file name carries a hash of its facts and of the template, so a cover is drawn once and drawn again only
// when what it shows would change. Two files per story: wide (2.10:1, for cards and the story page) and tall (1:1, for
// the wide card's half, measured 0.60 to 0.65:1, and square thumbnails); the site crops them with object-fit: cover.
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch } from './lib/cdp.mjs';
import { serve } from './lib/serve.mjs';
import { factsOf } from './lib/facts.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
// CSS pixels of each file; screenshots are taken at 2x.
const FRAMES = { wide: { w: 311, h: 148, suffix: '' }, tall: { w: 308, h: 308, suffix: '-t' } };
const TEMPLATE = 'covers/templates/con-so.html';
const DRAWING = ['covers/templates/con-so.html', 'covers/templates/cover.js'].map(p => readFileSync(join(ROOT, p), 'utf8')).join('\n');

const [requestPath, resultPath] = process.argv.slice(2);
if (!requestPath || !resultPath) { console.error('usage: node covers/render-site.mjs <request.json> <result.json>'); process.exit(2); }
const request = JSON.parse(readFileSync(requestPath, 'utf8'));
const outDir = resolve(request.out_dir || join(ROOT, 'site/assets/cover'));
const publicDir = 'assets/cover';
mkdirSync(outDir, { recursive: true });
const sources = new Map((request.sources || []).map(s => [s.id, s]));

const jobs = [];
const result = { covers: {}, rendered: 0, reused: 0, failed: {} };
for (const st of request.stories || []) {
  if (!st || !/^[\w-]+$/.test(String(st.id || ''))) continue;
  let facts;
  try { facts = factsOf(st, sources); } catch (e) { result.failed[st.id] = `facts: ${e.message}`; continue; }
  const hash = createHash('sha256').update(JSON.stringify(facts)).update(DRAWING).digest('hex').slice(0, 10);
  const files = Object.fromEntries(Object.entries(FRAMES).map(([k, fr]) => [k, `${st.id}-${hash}${fr.suffix}.png`]));
  const entry = { src: `${publicDir}/${files.wide}`, tall: `${publicDir}/${files.tall}`, hero: facts.hero.type };
  if (Object.values(files).every(f => existsSync(join(outDir, f)))) { result.covers[st.id] = entry; result.reused++; continue; }
  jobs.push({ facts, files, entry });
}

if (jobs.length) {
  const srv = await serve(ROOT);
  let chrome;
  try {
    chrome = await launch();
    for (const job of jobs) {
      try {
        for (const [frame, fr] of Object.entries(FRAMES)) {
          await chrome.viewport(fr.w, fr.h, 2);
          await chrome.goto('about:blank');
          await chrome.goto(`${srv.url}/${TEMPLATE}?frame=${frame}#${encodeURIComponent(JSON.stringify(job.facts))}`);
          await chrome.waitReady();
          writeFileSync(join(outDir, job.files[frame]), await chrome.screenshot({ x: 0, y: 0, width: fr.w, height: fr.h }));
        }
        result.covers[job.facts.id] = job.entry;
        result.rendered++;
      } catch (e) { result.failed[job.facts.id] = e.message; }
    }
  } catch (e) {
    for (const job of jobs) if (!result.covers[job.facts.id]) result.failed[job.facts.id] = e.message;
  } finally {
    if (chrome) await chrome.close();
    srv.close();
  }
}
writeFileSync(resultPath, JSON.stringify(result));
console.log(`covers: ${result.rendered} rendered, ${result.reused} reused, ${Object.keys(result.failed).length} failed`);

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const siteDir = path.join(repoRoot, 'site');

const server = http.createServer((req, res) => {
  const cleanPath = req.url.split('?')[0];
  let p = path.join(siteDir, cleanPath === '/' ? 'index.html' : cleanPath);
  if (!fs.existsSync(p)) {
    res.writeHead(404);
    return res.end('Not found');
  }
  const ext = path.extname(p).toLowerCase();
  const mimes = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
  };
  res.writeHead(200, { 'Content-Type': mimes[ext] || 'application/octet-stream' });
  res.end(fs.readFileSync(p));
});

await new Promise(r => server.listen(8799, '127.0.0.1', r));

const chromePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const userDataDir = path.join(repoRoot, 'plans/tools/chr-test');
const chrome = spawn(chromePath, [
  '--headless=new',
  '--disable-gpu',
  '--hide-scrollbars',
  '--remote-debugging-port=9336',
  `--user-data-dir=${userDataDir}`,
  'about:blank',
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
await sleep(1500);

let targets;
for (let i = 0; i < 30; i++) {
  try {
    targets = await (await fetch('http://127.0.0.1:9336/json')).json();
    if (targets && targets.length) break;
  } catch {}
  await sleep(200);
}

const page = targets.find(t => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r, { once: true }));

let id = 0;
const pending = new Map();
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m);
    pending.delete(m.id);
  }
});

const send = (method, params = {}) => new Promise(res => {
  const i = ++id;
  pending.set(i, res);
  ws.send(JSON.stringify({ id: i, method, params }));
});

await send('Page.enable');
await send('Runtime.enable');

for (const w of [768, 860, 1024, 1180, 1440]) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 768 });
  await send('Page.navigate', { url: 'http://127.0.0.1:8799/index.html' });
  await sleep(1000);
  const evalRes = await send('Runtime.evaluate', {
    expression: `(() => {
      const tbl = document.querySelector('.arena-table');
      if (!tbl) return { error: 'no table' };
      const thRank = document.querySelector('.arena-th-rank')?.getBoundingClientRect();
      const thModel = document.querySelector('.arena-th-model')?.getBoundingClientRect();
      const thPlot = document.querySelector('.arena-th-plot')?.getBoundingClientRect();
      const thScore = document.querySelector('.arena-th-score')?.getBoundingClientRect();
      const thChange = document.querySelector('.arena-th-change')?.getBoundingClientRect();
      const header = document.querySelector('.arena-axis-header')?.getBoundingClientRect();
      const title = document.querySelector('.arena-axis-title')?.getBoundingClientRect();
      const range = document.querySelector('.arena-axis-range')?.getBoundingClientRect();
      const ticks = document.querySelector('.arena-axis-ticks')?.getBoundingClientRect();
      const firstWhisker = document.querySelector('.arena-whisker')?.getBoundingClientRect();
      const track = document.querySelector('.arena-plot-track')?.getBoundingClientRect();

      // Check all model names in table
      const modelNames = Array.from(document.querySelectorAll('.arena-col-model .arena-model-name')).map(el => {
        const rect = el.getBoundingClientRect();
        return {
          text: el.textContent.trim(),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          lineHeight: parseFloat(window.getComputedStyle(el).lineHeight) || 20
        };
      });

      return {
        viewport: ${w},
        tableWidth: Math.round(tbl.getBoundingClientRect().width),
        colWidths: {
          rank: Math.round(thRank?.width || 0),
          model: Math.round(thModel?.width || 0),
          plot: Math.round(thPlot?.width || 0),
          score: Math.round(thScore?.width || 0),
          change: Math.round(thChange?.width || 0)
        },
        trackWidth: Math.round(track?.width || 0),
        whiskerWidth: Math.round(firstWhisker?.width || 0),
        headerTicksGap: ticks && header ? Math.round(ticks.top - header.bottom) : null,
        titleBox: { width: Math.round(title?.width || 0), height: Math.round(title?.height || 0) },
        rangeBox: { width: Math.round(range?.width || 0), height: Math.round(range?.height || 0) },
        sampleModelLines: Math.round(modelNames[0]?.height / (modelNames[0]?.lineHeight || 20))
      };
    })()`,
    returnByValue: true
  });
  console.log(`Viewport ${w}px:`, JSON.stringify(evalRes.result.value));
}

try { chrome.kill(); } catch {}
try { server.close(); } catch {}
process.exit(0);

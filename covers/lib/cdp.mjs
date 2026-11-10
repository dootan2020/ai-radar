// A minimal Chrome DevTools Protocol driver: one headless Chrome, one tab, no npm dependencies (Node 22 WebSocket).
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Chrome as installed on this machine or on the GitHub runner (ubuntu-26.04 ships Google Chrome); CHROME overrides.
const CANDIDATES = {
  win32: ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'],
  linux: ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser'],
  darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'],
};
export const CHROME = process.env.CHROME || (CANDIDATES[process.platform] || []).find(p => existsSync(p)) || null;
const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function launch() {
  if (!CHROME) throw new Error('Chrome not found (set CHROME to its path)');
  const profile = mkdtempSync(join(tmpdir(), 'covers-chrome-'));
  const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--force-color-profile=srgb',
    '--font-render-hinting=none',
    // A CI runner's Chrome may have no usable sandbox (unprivileged user namespaces); it only opens the repository's
    // own template and the source avatars the site already shows.
    ...(process.env.CI ? ['--no-sandbox'] : []), 'about:blank'], { stdio: 'ignore' });
  const portFile = join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  if (!existsSync(portFile)) { proc.kill(); throw new Error('Chrome did not start: no DevToolsActivePort'); }
  const [port, path] = readFileSync(portFile, 'utf8').split('\n');
  const ws = new WebSocket(`ws://127.0.0.1:${port}${path.trim()}`);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map(), listeners = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(`${m.error.message} ${m.error.data || ''}`)) : res(m.result);
    } else if (m.method) listeners.forEach(l => l(m));
  };
  const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const mid = ++id; pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  const page = (method, params) => send(method, params, sessionId);
  await page('Page.enable'); await page('Runtime.enable');
  const waitEvent = (method, timeout = 30000) => new Promise((res, rej) => {
    const t = setTimeout(() => { listeners.splice(listeners.indexOf(fn), 1); rej(new Error(`timeout waiting for ${method}`)); }, timeout);
    const fn = m => { if (m.method === method && m.sessionId === sessionId) { clearTimeout(t); listeners.splice(listeners.indexOf(fn), 1); res(m.params); } };
    listeners.push(fn);
  });
  const evaluate = async expr => {
    const r = await page('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  return {
    async viewport(width, height, scale = 2, mobile = false) {
      await page('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile });
    },
    async goto(url, timeout = 30000) {
      const loaded = waitEvent('Page.loadEventFired', timeout);
      await page('Page.navigate', { url });
      await loaded;
    },
    evaluate,
    // Wait until the page sets document.documentElement.dataset.ready (templates do it after fonts and images).
    async waitReady(timeout = 15000) {
      const t0 = Date.now();
      while (Date.now() - t0 < timeout) {
        if (await evaluate('document.documentElement.dataset.ready === "1"')) return;
        await sleep(50);
      }
      throw new Error('page never reported ready');
    },
    async screenshot(clip) {
      const r = await page('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
      return Buffer.from(r.data, 'base64');
    },
    async close() {
      try { await send('Browser.close'); } catch { /* already gone */ }
      ws.close();
      await sleep(300);
      if (proc.exitCode === null) proc.kill();
      try { rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still hold a file */ }
    },
  };
}

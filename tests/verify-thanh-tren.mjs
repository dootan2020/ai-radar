// The top row's corners and "Tùy chỉnh" (site/thanh-tren.js), with fake storage and a fake page: the saved choices across
// a reload (thanh-tren.js and both first-paint scripts), storage that fails, the weather cluster from the weather card's
// own data, and the picture that waits while it is turned off. Prints one JSON object; tests/test_thanh_tren.py checks it.
// Usage: node tests/verify-thanh-tren.mjs
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const load = file => import(pathToFileURL(path.join(root, 'site', file)).href);
const tt = await load('thanh-tren.js');
const wx = await load('thoi-tiet.js');
const nen = await load('nen.js');

const memory = (init = {}) => {
  const m = new Map(Object.entries(init));
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), m };
};
const broken = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); }, removeItem() { throw new Error('SecurityError'); } };
const fakeRoot = () => ({ dataset: {} });

/* The first-paint scripts, run as the browser runs them, against a saved storage: what the page looks like on reload. */
const site = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
const inline = site.match(/<script>([\s\S]*?)<\/script>/)[1];
const themeJs = fs.readFileSync(path.join(root, 'extension', 'theme.js'), 'utf8');
function firstPaint(code, storage) {
  const dataset = {};
  vm.runInNewContext(code, { document: { documentElement: { dataset } }, localStorage: storage, JSON });
  return dataset;
}

const options = [
  { layout: 'full', picture: true, weather: true },
  { layout: 'part', picture: true, weather: true },
  { layout: 'head', picture: true, weather: true },
  { layout: 'full', picture: false, weather: true },
  { layout: 'full', picture: true, weather: false },
  { layout: 'head', picture: false, weather: false },
];
const reload = options.map(s => {
  const store = memory();
  const saved = tt.saveSettings(store, s);
  const r = fakeRoot();
  tt.applySettings(r, tt.readSettings(store));
  return { saved, read: tt.readSettings(store), module: r.dataset, site: firstPaint(inline, store), ext: firstPaint(themeJs, store) };
});
const themes = ['light', 'dark', 'system'].map(t => {
  const store = memory();
  tt.saveTheme(store, t);
  return { theme: t, read: tt.readTheme(store), site: firstPaint(inline, store).theme ?? 'system', ext: firstPaint(themeJs, store).theme ?? 'system' };
});

const failing = {
  readThrows: tt.readSettings(broken),
  saveThrows: tt.saveSettings(broken, { layout: 'head', picture: false, weather: false }),
  themeThrows: [tt.readTheme(broken), tt.saveTheme(broken, 'dark')],
  missing: tt.readSettings(memory()),
  malformed: tt.readSettings(memory({ 'halcyon:tuy-chinh': '{not json' })),
  wrongTypes: tt.readSettings(memory({ 'halcyon:tuy-chinh': JSON.stringify({ layout: 'giant', picture: 'no', weather: 0 }) })),
  partial: tt.readSettings(memory({ 'halcyon:tuy-chinh': JSON.stringify({ weather: false }) })),
  nullStorage: tt.readSettings(null),
  siteBroken: firstPaint(inline, broken),
  extBroken: firstPaint(themeJs, broken),
  siteMalformed: firstPaint(inline, memory({ 'halcyon:tuy-chinh': '{not json', 'air2:theme': '"dark"' })),
};

/* The cluster from the weather card's own reading (Open-Meteo's shape, as thoi-tiet.js receives it). */
const reading = { current: { time: '2026-11-10T14:45', temperature_2m: 19.6, weather_code: 53, is_day: 1 } };
const night = { current: { time: '2026-11-10T22:00', temperature_2m: 17.2, weather_code: 0, is_day: 0 } };
const day = tt.today(new Date('2026-11-10T07:48:00Z'));
const nowC = wx.weatherNow(reading, 'Hà Nội', 'C');
const nowF = wx.weatherNow(reading, 'Đà Nẵng', 'F');
const heard = [];
const stop = wx.onWeather(w => heard.push(w));
const cluster = {
  nowC, nowF, night: wx.weatherNow(night, 'Huế', 'C'), empty: wx.weatherNow({}, 'Hà Nội', 'C'),
  htmlC: tt.clusterHTML(nowC, day), htmlF: tt.clusterHTML(nowF, day), htmlNone: tt.clusterHTML(null, day),
  escaped: tt.clusterHTML({ ...nowC, city: '<b>x</b>' }, day),
  day, lateUtc: tt.today(new Date('2026-11-10T17:30:00Z')), earlyUtc: tt.today(new Date('2026-11-10T16:59:00Z')),
  heardBeforePaint: heard.length,
};
stop();

/* nen.js with the picture turned off: nothing is fetched until "Tùy chỉnh" turns it back on. */
async function pictureOff() {
  const fetched = [];
  const listeners = new Map();
  const dataset = { nen: 'off' };
  const box = { classList: { add() {} }, querySelector: () => null, prepend() {} };
  const doc = {
    documentElement: { dataset },
    getElementById: id => (id === 'nen' ? box : null),
    createElement: () => { const img = {}; Object.defineProperty(img, 'src', { set: v => { fetched.push(v); setTimeout(() => img.onload()); } }); return img; },
    defaultView: { requestAnimationFrame: f => f() },
    addEventListener: (t, f) => listeners.set(f, t),
    removeEventListener: (t, f) => listeners.delete(f),
    dispatchEvent: e => [...listeners].filter(([, t]) => t === e.type).forEach(([f]) => f(e)),
  };
  const win = { matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
    fetch: async u => { fetched.push(u); return { ok: true, json: async () => ({ days: [{ date: '2026-11-10', file: '2026-11-10.webp' }] }) }; } };
  const done = nen.startNen({ win, doc, extension: false, now: () => new Date('2026-11-10T05:00:00Z') });
  await new Promise(r => setTimeout(r, 30));
  const whileOff = [...fetched];
  doc.dispatchEvent({ type: nen.NEN_ON });           // an event while still off changes nothing
  await new Promise(r => setTimeout(r, 30));
  const stillOff = [...fetched];
  delete dataset.nen;
  doc.dispatchEvent({ type: nen.NEN_ON });
  const shown = await done;
  return { whileOff, stillOff, after: fetched, shown, listenersLeft: listeners.size, event: nen.NEN_ON };
}
const quiet = console.warn; console.warn = () => {};
const off = await pictureOff();
console.warn = quiet;

process.stdout.write(JSON.stringify({ reload, themes, failing, cluster, off, defaults: tt.DEFAULTS, key: tt.KEY }) + '\n');

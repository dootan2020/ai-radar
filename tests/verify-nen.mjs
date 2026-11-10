// The day's picture (site/nen.js): the Bangkok day, the pick order, the phone rule and the fallbacks, with a fake page.
// Prints one JSON object; tests/test_nen_trang.py checks it. Usage: node tests/verify-nen.mjs
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1')), '..');
const nen = await import(pathToFileURL(path.join(root, 'site', 'nen.js')).href);

function fakePage({ wide, lich, broken = [], kept = null, extension = false }) {
  const log = { fetched: [], shown: [], cached: [] };
  const listeners = [];
  const query = { matches: wide, addEventListener: (_, f) => listeners.push(f), removeEventListener: (_, f) => listeners.splice(listeners.indexOf(f), 1) };
  const box = {
    children: [], classes: new Set(),
    classList: { add: c => box.classes.add(c) },
    querySelector: () => null,
    prepend: img => { box.children.unshift(img); log.shown.push(img.src); },
  };
  const doc = {
    getElementById: id => (id === 'nen' ? box : null),
    createElement: () => {
      const img = {};
      let src = '';
      Object.defineProperty(img, 'src', {
        get: () => src,
        set: v => { src = v; setTimeout(() => (broken.some(b => v.includes(b)) ? img.onerror() : img.onload())); },
      });
      return img;
    },
    defaultView: { requestAnimationFrame: f => f() },
  };
  const store = new Map(kept ? [['air2:nen', kept]] : []);
  const cache = new Map(kept ? [[kept, { blob: async () => 'blob-of-' + kept }]] : []);
  const win = {
    matchMedia: q => { log.query = q; return query; },
    fetch: async url => {
      log.fetched.push(url);
      if (lich === 'offline') throw new TypeError('Failed to fetch');
      if (lich === 404) return { ok: false, status: 404 };
      return { ok: true, json: async () => lich };
    },
    localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
    caches: { open: async () => ({
      match: async u => cache.get(u),
      add: async u => { cache.set(u, { blob: async () => 'blob-of-' + u }); log.cached.push(u); },
      keys: async () => [...cache.keys()].map(url => ({ url })),
      delete: async r => cache.delete(r.url),
    }) },
    URL: { createObjectURL: b => 'blob:' + b },
  };
  const widen = () => { query.matches = true; [...listeners].forEach(f => f({ matches: true })); };
  return { win, doc, box, log, widen, store, extension };
}

const at = iso => () => new Date(iso);
const days = { days: [
  { date: '2026-11-08', file: '2026-11-08.webp' },
  { date: '2026-11-10', file: '2026-11-10.avif' },
  { date: '2026-11-11', file: '2026-11-11.webp' },
  { date: '2026-11-09', file: '2026-11-09.webp' },
] };
const quiet = console.warn;
console.warn = () => {};

const result = {
  // 00:30 in Bangkok is already the next day; 23:59 is not.
  bangkok: [
    nen.bangkokDay(new Date('2026-11-09T17:30:00Z')),
    nen.bangkokDay(new Date('2026-11-09T16:59:00Z')),
    nen.bangkokDay(new Date('2026-12-31T17:00:00Z')),
  ],
  pick: {
    today: nen.pickDay(days, '2026-11-10')?.file,
    earlier: nen.pickDay({ days: days.days.filter(d => d.date !== '2026-11-10') }, '2026-11-10')?.file,
    none: nen.pickDay({ days: [{ date: '2026-11-12', file: '2026-11-12.webp' }] }, '2026-11-10'),
    malformed: nen.pickDay({ days: [{ date: '2026-11-10', file: '../x.webp' }, { date: '10/11/2026', file: '2026-11-10.webp' }, null] }, '2026-11-10'),
    empty: nen.pickDay(null, '2026-11-10'),
  },
  wide: nen.WIDE,
};

// The website, at 23:30 on 9 Nov UTC: 06:30 on 10 Nov in Bangkok, so today's file.
{
  const p = fakePage({ wide: true, lich: days });
  const shown = await nen.startNen({ ...p, extension: false, now: at('2026-11-09T23:30:00Z') });
  result.site = { shown, fetched: p.log.fetched, ready: p.box.classes.has('is-ready'), cached: p.log.cached };
}
// A phone: no request at all, not even nen/lich.json; widening the window later draws the picture once.
{
  const p = fakePage({ wide: false, lich: days });
  const pending = nen.startNen({ ...p, extension: false, now: at('2026-11-10T03:00:00Z') });
  await new Promise(r => setTimeout(r, 20));
  result.phone = { fetched: [...p.log.fetched], shown: [...p.log.shown], query: p.log.query };
  p.widen();
  result.phone.afterWiden = await pending;
}
// The website when the calendar is missing, or today's picture is broken: the packaged picture.
{
  const p = fakePage({ wide: true, lich: 404 });
  result.siteNoLich = await nen.startNen({ ...p, extension: false, now: at('2026-11-10T03:00:00Z') });
  const q = fakePage({ wide: true, lich: days, broken: ['nen/2026-11-10.avif'] });
  result.siteBrokenPicture = await nen.startNen({ ...q, extension: false, now: at('2026-11-10T03:00:00Z') });
}
// The new tab: online it reads the live site and keeps the picture; offline it shows the kept one; with nothing kept,
// the packaged one.
{
  const p = fakePage({ wide: true, lich: days });
  result.extOnline = { shown: await nen.startNen({ ...p, extension: true, now: at('2026-11-10T03:00:00Z') }) };
  await new Promise(r => setTimeout(r, 20));
  result.extOnline.cached = p.log.cached;
  result.extOnline.remembered = p.store.get('air2:nen');
  const kept = 'https://radar-ai-vn.pages.dev/nen/2026-11-09.webp';
  const q = fakePage({ wide: true, lich: 'offline', kept });
  result.extOffline = await nen.startNen({ ...q, extension: true, now: at('2026-11-10T03:00:00Z') });
  const r = fakePage({ wide: true, lich: 'offline' });
  result.extNothingKept = await nen.startNen({ ...r, extension: true, now: at('2026-11-10T03:00:00Z') });
}
console.warn = quiet;
console.log(JSON.stringify(result));

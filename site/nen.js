/* Halcyon · the day's picture behind the first screen (owner, 10/11: "còn về ảnh nền thì em làm như edge").
   A new 3D render every day. The publish job serves nen/lich.json ({"days":[{"date","file","family","w","h"}]}) and the
   files under nen/. Everyone sees the same picture on the same day: today's entry in Asia/Bangkok, else the latest
   earlier one, else the packaged picture. Only the one picture is loaded, never the collection, and only from 768 px:
   a phone keeps the plain page and downloads nothing (trang-msn.css draws the layer). The layer shows the renders'
   night colour until the picture arrives, so the first screen never flashes white.
   The new tab (chrome-extension:) reads the live site and keeps the last good picture in Cache Storage, so it still
   has one offline; the website leaves that to the browser's HTTP cache (its CSP allows no blob: pictures). */

const LIVE = 'https://radar-ai-vn.pages.dev/';
export const WIDE = '(min-width: 768px)';
export const PACKAGED = 'anh/nen-du-phong.webp';
const KEEP = 'halcyon-nen';
const LAST = 'air2:nen';
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const FILE = /^\d{4}-\d{2}-\d{2}\.(?:avif|webp)$/;
const INSTANT_MS = 80;   // a picture that arrives this fast came from a cache: show it at once, without the fade

/* The calendar day in Asia/Bangkok as YYYY-MM-DD, whatever the reader's own time zone. */
export function bangkokDay(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(now).reduce((all, p) => (all[p.type] = p.value, all), {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/* Today's entry, else the latest earlier one; null when there is none (the caller shows the packaged picture). A later
   day is never shown early, and an entry whose date or file is malformed is skipped. */
export function pickDay(lich, today) {
  const days = Array.isArray(lich?.days) ? lich.days : [];
  let best = null;
  for (const d of days) {
    if (!d || !DAY.test(d.date ?? '') || !FILE.test(d.file ?? '') || d.date > today) continue;
    if (!best || d.date > best.date) best = d;
  }
  return best;
}

async function todaysPicture(win, base, now) {
  const res = await win.fetch(`${base}nen/lich.json`, { cache: 'no-cache', signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`nen/lich.json: HTTP ${res.status}`);
  const day = pickDay(await res.json(), bangkokDay(now()));
  if (!day) throw new Error('nen/lich.json chưa có ngày nào tới hôm nay');
  return `${base}nen/${day.file}`;
}

function show(doc, box, src, now) {
  return new Promise((resolve, reject) => {
    const img = doc.createElement('img');
    const asked = now().getTime();
    img.className = 'nen-img';
    img.alt = '';
    img.decoding = 'async';
    img.onload = () => {
      box.querySelector('.nen-img')?.remove();
      if (now().getTime() - asked < INSTANT_MS) box.classList.add('is-instant');
      box.prepend(img);
      // Next frame, so the fade starts from the night colour instead of popping in.
      (doc.defaultView?.requestAnimationFrame ?? (f => f()))(() => box.classList.add('is-ready'));
      resolve(src);
    };
    img.onerror = () => reject(new Error(`ảnh nền không tải được: ${src}`));
    img.src = src;
  });
}

/* The new tab keeps exactly one picture: the last one that loaded. */
async function keep(win, url) {
  const cache = await win.caches.open(KEEP);
  if (!await cache.match(url)) await cache.add(url);
  for (const req of await cache.keys()) if (req.url !== url) await cache.delete(req);
  win.localStorage.setItem(LAST, url);
}

async function kept(win) {
  const url = win.localStorage.getItem(LAST);
  const res = url && await (await win.caches.open(KEEP)).match(url);
  return res ? win.URL.createObjectURL(await res.blob()) : null;
}

async function paint({ win, doc, box, extension, now }) {
  const base = extension ? LIVE : '';
  try {
    const url = await todaysPicture(win, base, now);
    await show(doc, box, url, now);
    if (extension) keep(win, url).catch(e => console.warn('Halcyon could not keep the day\'s picture offline', e));
    return url;
  } catch (e) {
    console.warn('The day\'s picture is unavailable; showing an earlier one', e);
  }
  if (extension) {
    try {
      const src = await kept(win);
      if (src) return await show(doc, box, src, now);
    } catch (e) { console.warn('No kept picture', e); }
  }
  return show(doc, box, PACKAGED, now).catch(() => null);
}

/* Draw the picture once the window is at least 768 px wide: at once, or the first time a narrow window is widened. */
export function startNen({
  win = globalThis,
  doc = globalThis.document,
  extension = globalThis.location?.protocol === 'chrome-extension:',
  now = () => new Date(),
} = {}) {
  const box = doc?.getElementById?.('nen');
  if (!box || typeof win.matchMedia !== 'function') return Promise.resolve(null);
  const wide = win.matchMedia(WIDE);
  if (wide.matches) return paint({ win, doc, box, extension, now });
  return new Promise(resolve => {
    const widened = e => {
      if (!e.matches) return;
      wide.removeEventListener('change', widened);
      resolve(paint({ win, doc, box, extension, now }));
    };
    wide.addEventListener('change', widened);
  });
}

if (typeof document !== 'undefined') startNen();

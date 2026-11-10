/* Halcyon · the top row's corners, after Edge's new tab (captain, 10/11 14:48: "để nút 9 dấu chấm góc trên phải";
   14:55: "chuyển cho anh cụm nhiệt độ, vị trí, thời tiết và ngày tháng năm, cùng ở góc trên trái"; "có nút tùy chỉnh
   hiển thị như edge"). Top left: the weather card's city, symbol and temperature, then the day in Asia/Bangkok. Top right,
   beside the 9 dots: "Tùy chỉnh", a panel that sets how much of the page shows above the fold, the day's picture, the
   weather in the corner and the theme. The choices stay in this browser (one localStorage key, the theme keeps its own
   air2:theme); the page's first-paint script applies them before anything is drawn (index.html, extension/theme.js).
   The cluster reads what the weather card painted (thoi-tiet.js onWeather): no request of its own. */
import { onWeather } from './thoi-tiet.js';
import { NEN_ON } from './nen.js';

export const KEY = 'halcyon:tuy-chinh';
export const THEME_KEY = 'air2:theme';
export const LAYOUTS = [['full', 'Toàn trang'], ['part', 'Một phần'], ['head', 'Đầu đề']];
export const THEMES = [['light', 'Sáng'], ['dark', 'Tối'], ['system', 'Theo máy']];
export const DEFAULTS = Object.freeze({ layout: 'full', picture: true, weather: true });
const WEEKDAY = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* The saved choices; anything missing, malformed or unreadable falls back to the defaults, one field at a time. */
export function readSettings(storage) {
  let saved = null;
  try { saved = JSON.parse(storage?.getItem(KEY) ?? 'null'); } catch { saved = null; }
  const s = saved && typeof saved === 'object' ? saved : {};
  return {
    layout: LAYOUTS.some(([v]) => v === s.layout) ? s.layout : DEFAULTS.layout,
    picture: typeof s.picture === 'boolean' ? s.picture : DEFAULTS.picture,
    weather: typeof s.weather === 'boolean' ? s.weather : DEFAULTS.weather,
  };
}

/* true when the choice was kept; a private window or full storage keeps it for this page only. */
export function saveSettings(storage, settings) {
  try { storage.setItem(KEY, JSON.stringify(settings)); return true; } catch { return false; }
}

export function readTheme(storage) {
  try {
    const t = JSON.parse(storage?.getItem(THEME_KEY) ?? 'null');
    return t === 'light' || t === 'dark' ? t : 'system';
  } catch { return 'system'; }
}

export function saveTheme(storage, theme) {
  try {
    if (theme === 'light' || theme === 'dark') storage.setItem(THEME_KEY, JSON.stringify(theme));
    else storage.removeItem(THEME_KEY);
    return true;
  } catch { return false; }
}

/* The page's attributes for the choices; the same rules as the first-paint script, so nothing moves once modules run. */
export function applySettings(root, settings, theme) {
  const d = root.dataset;
  if (settings.layout === DEFAULTS.layout) delete d.layout; else d.layout = settings.layout;
  if (settings.picture) delete d.nen; else d.nen = 'off';
  if (settings.weather) delete d.wx; else d.wx = 'off';
  if (theme === 'light' || theme === 'dark') d.theme = theme; else if (theme === 'system') delete d.theme;
}

/* The day in Asia/Bangkok: ISO for <time>, and "Thứ Ba, 10/11/2026" with its parts. */
export function today(now = new Date()) {
  const p = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' })
    .formatToParts(now).reduce((all, x) => (all[x.type] = x.value, all), {});
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(p.weekday);
  return { iso: `${p.year}-${p.month}-${p.day}`, text: `${WEEKDAY[wd]}, ${p.day}/${p.month}/${p.year}`,
    weekday: WEEKDAY[wd], dayMonth: `${p.day}/${p.month}`, year: p.year };
}

/* The cluster's markup: the weather (when the card has a reading) and the day. Text to read, nothing to press: the
   weather card in the first row is where the forecast opens. The weekday and the year are their own spans, so a corner
   too narrow for the whole line drops them (fitCluster) instead of running under the search. */
export function clusterHTML(weather, day) {
  const date = `<span class="top-date"><time datetime="${day.iso}"><span class="top-wd">${esc(day.weekday)}, </span>${esc(day.dayMonth)}<span class="top-yr">/${esc(day.year)}</span></time></span>`;
  if (!weather) return date;
  const t = `${weather.temp}°${weather.unit}`;
  return `<span class="top-wx" title="${esc(weather.label)}">`
    + `<span class="top-city">${esc(weather.city)}</span>`
    + `<svg class="top-wx-ic" aria-hidden="true"><use href="#wx-sym-${esc(weather.symbol)}"/></svg>`
    + `<span class="top-temp num">${esc(t)}</span><span class="sr">, ${esc(weather.label.toLowerCase())}</span></span>${date}`;
}

const SHEET = `<div class="tc-top"><h2 id="tc-h">Tùy chỉnh</h2>
    <button class="tc-close" type="button" data-tc-close aria-label="Đóng tùy chỉnh"><svg class="i" aria-hidden="true"><use href="#i-close"/></svg></button></div>
  <fieldset class="tc-group tc-wide"><legend>Bố cục</legend><div class="tc-layouts">${LAYOUTS.map(([v, name]) =>
    `<label class="tc-layout"><input class="sr" type="radio" name="tc-layout" value="${v}"><span class="tc-mini tc-mini-${v}" aria-hidden="true"><b></b><i></i></span><span class="tc-name">${name}</span></label>`).join('')}</div></fieldset>
  <div class="tc-group">
    <label class="tc-row tc-wide"><span>Hiện ảnh nền</span><input class="tc-switch" type="checkbox" role="switch" name="tc-picture"></label>
    <label class="tc-row"><span>Hiện thời tiết</span><input class="tc-switch" type="checkbox" role="switch" name="tc-weather"></label>
  </div>
  <fieldset class="tc-group"><legend>Giao diện</legend><div class="tc-seg">${THEMES.map(([v, name]) =>
    `<label><input class="sr" type="radio" name="tc-theme" value="${v}"><span>${name}</span></label>`).join('')}</div></fieldset>`;

const local = () => { try { return globalThis.localStorage; } catch { return null; } };

/* The corner is the row's first column (trang-msn.css); the search owns the middle one. When the whole line is wider
   than the corner (a 1280 px window, a long city name), drop the year, then the weekday, then the city, until it fits:
   the corner is never clipped and never runs under the search. */
export const FIT_STEPS = 3;
export function fitCluster(el) {
  if (!el) return 0;
  let fit = 0;
  el.dataset.fit = '0';
  while (fit < FIT_STEPS && el.scrollWidth > el.clientWidth + 0.5) el.dataset.fit = String(++fit);
  return fit;
}

export function startTopRow(doc = document) {
  const root = doc.documentElement;
  const storage = local();
  let settings = readSettings(storage);
  applySettings(root, settings);

  const now = doc.getElementById('top-now');
  let weather = null, day = today();
  const paintCluster = () => { if (now) { now.innerHTML = clusterHTML(weather, day); fitCluster(now); } };
  paintCluster();
  if (now && typeof ResizeObserver === 'function') new ResizeObserver(() => fitCluster(now)).observe(now);
  doc.fonts?.ready.then(() => fitCluster(now));   // the site font is wider than the fallback the first fit measured
  onWeather(w => { weather = w; paintCluster(); });
  // A new tab left open past midnight shows the new day.
  setInterval(() => { const d = today(); if (d.iso !== day.iso) { day = d; paintCluster(); } }, 60e3);

  const btn = doc.getElementById('tc-open');
  if (!btn) return;
  const sheet = doc.createElement('div');
  sheet.className = 'tc-sheet';
  sheet.id = 'tuy-chinh';
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-labelledby', 'tc-h');
  sheet.hidden = true;
  sheet.innerHTML = SHEET;
  doc.body.append(sheet);
  const field = name => sheet.querySelectorAll(`[name="${name}"]`);

  function sync() {
    const theme = root.dataset.theme === 'light' || root.dataset.theme === 'dark' ? root.dataset.theme : 'system';
    field('tc-layout').forEach(r => { r.checked = r.value === settings.layout; });
    field('tc-theme').forEach(r => { r.checked = r.value === theme; });
    field('tc-picture')[0].checked = settings.picture;
    field('tc-weather')[0].checked = settings.weather;
  }
  function change(next) {
    const wasOff = !settings.picture;
    settings = { ...settings, ...next };
    saveSettings(storage, settings);
    applySettings(root, settings);
    if (wasOff && settings.picture) doc.dispatchEvent(new Event(NEN_ON));
  }
  sheet.addEventListener('change', e => {
    const t = e.target;
    if (t.name === 'tc-layout') change({ layout: t.value });
    else if (t.name === 'tc-picture') change({ picture: t.checked });
    else if (t.name === 'tc-weather') change({ weather: t.checked });
    else if (t.name === 'tc-theme') {
      saveTheme(storage, t.value);
      applySettings(root, settings, t.value);
      const dark = t.value === 'dark' || (t.value === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
      doc.getElementById('theme-btn')?.setAttribute('aria-pressed', String(dark));
    }
  });

  let closing;
  function open(fromKeyboard) {
    clearTimeout(closing);
    sync();
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add('is-open'));
    btn.setAttribute('aria-expanded', 'true');
    const first = [...sheet.querySelectorAll('input')].find(i => i.offsetParent && (i.type !== 'radio' || i.checked));
    if (fromKeyboard && first) first.focus({ preventScroll: true });
    else { sheet.tabIndex = -1; sheet.focus({ preventScroll: true }); }
  }
  function close(focus = false) {
    if (sheet.hidden) return;
    btn.setAttribute('aria-expanded', 'false');
    sheet.classList.remove('is-open');
    closing = setTimeout(() => { sheet.hidden = true; }, 160);
    if (focus) btn.focus();
  }
  btn.addEventListener('click', e => (btn.getAttribute('aria-expanded') === 'true' ? close() : open(e.detail === 0)));
  sheet.addEventListener('click', e => { if (e.target.closest('[data-tc-close]')) close(true); });
  doc.addEventListener('pointerdown', e => { if (!sheet.hidden && !sheet.contains(e.target) && !btn.contains(e.target)) close(); });
  doc.addEventListener('keydown', e => { if (e.key === 'Escape' && !sheet.hidden) { e.preventDefault(); close(true); } });
}

if (typeof document !== 'undefined') startTopRow();

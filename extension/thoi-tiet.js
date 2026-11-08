/* The weather card of the front page (Mẫu A, captain 08/11 18:23: "a thấy card thời tiết của msn rất đẹp"), on the
   website home and the new tab alike. Open-Meteo, no key and no account: the reader's browser asks api.open-meteo.com
   for the chosen city's forecast (the privacy page names the host). The reader picks the city (Hà Nội by default) and the
   choice is kept on this machine; the browser's location is never asked for, and the extension's manifest gains no
   permission (Open-Meteo answers with CORS). Forecasts are kept for 30 minutes per city.
   MSN's look: the city menu and "…" on top, now and a one-line outlook, "Hàng giờ / Hàng ngày", five frosted columns in
   two pages, "Xem dự báo đầy đủ". Every number on the card is the forecast's own. */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const KEY_CITY = 'halcyon:city';
const KEY_UNIT = 'halcyon:wx-unit';
const KEY_CACHE = 'halcyon:wx2:';
const CACHE_MS = 30 * 60e3;
export const CITIES = [
  ['Hà Nội', 21.0285, 105.8542], ['TP. Hồ Chí Minh', 10.8231, 106.6297], ['Đà Nẵng', 16.0544, 108.2022], ['Hải Phòng', 20.8449, 106.6881],
  ['Cần Thơ', 10.0452, 105.7469], ['Huế', 16.4637, 107.5909], ['Nha Trang', 12.2388, 109.1967], ['Đà Lạt', 11.9404, 108.4583],
  ['Vinh', 18.6796, 105.6813], ['Quy Nhơn', 13.7820, 109.2196], ['Hạ Long', 20.9599, 107.0425], ['Buôn Ma Thuột', 12.6667, 108.0500],
];
/* WMO weather codes as Open-Meteo returns them -> words and a symbol. */
export function describe(code) {
  const c = Number(code);
  if (c === 0) return ['Trời quang', 'clear'];
  if (c === 1) return ['Ít mây', 'clear'];
  if (c === 2) return ['Có mây', 'partly'];
  if (c === 3) return ['Nhiều mây', 'cloud'];
  if (c === 45 || c === 48) return ['Sương mù', 'fog'];
  if (c >= 51 && c <= 57) return ['Mưa phùn', 'rain'];
  if (c === 61 || c === 80) return ['Mưa nhỏ', 'rain'];
  if (c === 63 || c === 81) return ['Mưa vừa', 'rain'];
  if (c === 65 || c === 82) return ['Mưa to', 'rain'];
  if (c === 66 || c === 67) return ['Mưa lạnh', 'rain'];
  if ((c >= 71 && c <= 77) || c === 85 || c === 86) return ['Tuyết', 'snow'];
  if (c === 95) return ['Dông', 'storm'];
  if (c === 96 || c === 99) return ['Dông kèm mưa đá', 'storm'];
  return ['Không rõ', 'cloud'];
}
export const forecastURL = (lat, lon) => 'https://api.open-meteo.com/v1/forecast'
  + `?latitude=${lat}&longitude=${lon}`
  + '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day'
  + '&hourly=temperature_2m,weather_code,precipitation_probability,is_day'
  + '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'
  + '&timezone=Asia%2FBangkok&forecast_days=10';

/* The card's coloured symbols, drawn once into the page; fills come from tokens through inline style (a <use> clone
   inherits custom properties but not the page's selectors). */
const SUN = '<g style="stroke:var(--msn-sun)" stroke-width="2.2" stroke-linecap="round" fill="none"><path d="M16 3v3M16 26v3M3 16h3M26 16h3M6.8 6.8l2.1 2.1M23.1 23.1l2.1 2.1M6.8 25.2l2.1-2.1M23.1 8.9l2.1-2.1"/></g><circle cx="16" cy="16" r="6.6" style="fill:var(--msn-sun)"/>';
const CLOUD_B = (y = 0) => `<path style="fill:var(--msn-cloud)" d="M8.5 ${26 + y}h12.4a5 5 0 0 0 .8-9.94A6.8 6.8 0 0 0 9 ${17.1 + y}a4.5 4.5 0 0 0-.5 8.9z"/>`;
const SYMBOLS = {
  sun: SUN,
  partly: '<g style="stroke:var(--msn-sun)" stroke-width="2" stroke-linecap="round" fill="none"><path d="M12 2.5v2.6M3.5 11H6M5.9 4.9l1.8 1.8M18.1 4.9l-1.8 1.8"/></g><circle cx="12" cy="11" r="5.4" style="fill:var(--msn-sun)"/><path style="fill:var(--msn-cloud)" d="M10.5 27h13.2a5.3 5.3 0 0 0 .9-10.52A7.2 7.2 0 0 0 11 17.6a4.7 4.7 0 0 0-.5 9.4z"/><path style="fill:var(--msn-cloud-2)" d="M10.5 27h13.2a5.3 5.3 0 0 0 5.2-4.2c-1.2 1.4-3 2.3-5 2.3H11.2a4.7 4.7 0 0 1-4.3-2.8A4.7 4.7 0 0 0 10.5 27z"/>',
  cloud: '<path style="fill:var(--msn-cloud-2)" d="M20 9.5a6 6 0 0 1 5.9 5 4.4 4.4 0 0 1-1 8.6H22V14a7 7 0 0 0-5.6-3.6A6 6 0 0 1 20 9.5z"/>' + CLOUD_B(),
  rain: CLOUD_B(-6) + '<g style="stroke:var(--msn-rain)" stroke-width="2.2" stroke-linecap="round"><path d="M11 23.5l-1.2 3.4M16 23.5l-1.2 3.4M21 23.5l-1.2 3.4"/></g>',
  storm: CLOUD_B(-6) + '<path style="fill:var(--msn-sun)" d="M16.5 21l-3.5 5h3l-1.5 4.5 5-6h-3l2-3.5z"/>',
  snow: CLOUD_B(-6) + '<g style="fill:var(--msn-cloud)"><circle cx="11" cy="25" r="1.4"/><circle cx="16" cy="27.5" r="1.4"/><circle cx="21" cy="25" r="1.4"/></g>',
  fog: CLOUD_B(-6) + '<g style="stroke:var(--msn-cloud)" stroke-width="2" stroke-linecap="round"><path d="M7 23.5h18M10 27.5h12"/></g>',
  night: '<path style="fill:var(--msn-moon)" d="M15.5 4.2a8 8 0 1 0 9.3 10.6A7 7 0 0 1 15.5 4.2z"/><path style="fill:var(--msn-cloud)" d="M12.5 28h11.2a4.6 4.6 0 0 0 .7-9.1 6.2 6.2 0 0 0-11.5 1 4.1 4.1 0 0 0-.4 8.1z"/>',
  moon: '<path style="fill:var(--msn-moon)" d="M18 4.5a10 10 0 1 0 9.6 13A8.6 8.6 0 0 1 18 4.5z"/>',
};
function ensureSymbols() {
  if (document.getElementById('wx-sym-sun')) return;
  const box = document.createElement('div');
  box.innerHTML = `<svg width="0" height="0" style="position:absolute" aria-hidden="true">${Object.entries(SYMBOLS)
    .map(([k, v]) => `<symbol id="wx-sym-${k}" viewBox="0 0 32 32">${v}</symbol>`).join('')}</svg>`;
  document.body.prepend(box.firstElementChild);
}
/* A kind from describe() and whether it is day -> one of the symbols above. */
const symbolOf = (kind, day = true) => kind === 'clear' ? (day ? 'sun' : 'moon') : kind === 'partly' && !day ? 'night' : kind;
const sym = (kind, day, cls = 'wx-ic') => `<svg class="${cls}" aria-hidden="true"><use href="#wx-sym-${symbolOf(kind, day)}"/></svg>`;
const ICON = {
  home: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z"/></svg>',
  down: '<svg class="i i-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
  next: '<svg class="i i-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>',
  more: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>',
  close: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>',
};

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window: this tab only */ } },
};
const WEEKDAY = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
const WEEKDAY_FULL = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
const r0 = v => Math.round(Number(v));
const wdOf = t => new Date(t + 'T00:00:00Z').getUTCDay();
const RAINY = new Set(['rain', 'storm', 'snow']);

/* One line about the days ahead, from the forecast: the first day that turns rainy or at least 3° colder than today. */
export function outlookText(daily) {
  const kinds = daily.weather_code.map(c => describe(c)[1]);
  const hi = daily.temperature_2m_max;
  for (let i = 1; i < Math.min(7, daily.time.length); i++) {
    const rain = RAINY.has(kinds[i]) && !RAINY.has(kinds[0]);
    const colder = Number.isFinite(hi[i]) && Number.isFinite(hi[0]) && hi[i] <= hi[0] - 3;
    if (!rain && !colder) continue;
    const name = i === 1 ? 'Ngày mai' : WEEKDAY_FULL[wdOf(daily.time[i])];
    const what = rain && colder ? `${describe(daily.weather_code[i])[0].toLowerCase()} và lạnh hơn` : rain ? describe(daily.weather_code[i])[0].toLowerCase() : 'lạnh hơn';
    return { text: `${name} ${what}`, day: i };
  }
  return { text: `${describe(daily.weather_code[0])[0]}, mấy ngày tới ít thay đổi`, day: 0 };
}

export function createWeatherCard() {
  ensureSymbols();
  let city = store.get(KEY_CITY);
  if (!CITIES.some(c => c[0] === city)) city = CITIES[0][0];
  let unit = store.get(KEY_UNIT) === 'F' ? 'F' : 'C';
  let data = null, mode = 'daily', page = 0;
  const deg = c => unit === 'F' ? r0(c * 9 / 5 + 32) : r0(c);

  const card = document.createElement('section');
  card.className = 'msn-card msn-wx';
  card.id = 'weather';
  card.innerHTML = `<div class="wx-head">
      <button class="wx-city" id="wx-city" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="wx-city-menu">${ICON.home}<span id="wx-city-name"></span>${ICON.down}<span class="sr">, đổi thành phố</span></button>
      <button class="wx-more" id="wx-more" type="button" aria-label="Tuỳ chọn thời tiết" aria-haspopup="menu" aria-expanded="false" aria-controls="wx-more-menu">${ICON.more}</button>
    </div>
    <div class="wx-menu at-left" id="wx-city-menu" role="menu" aria-label="Chọn thành phố" data-closed hidden></div>
    <div class="wx-menu at-right" id="wx-more-menu" role="menu" aria-label="Tuỳ chọn thời tiết" data-closed hidden></div>
    <div class="wx-body" id="wx-body"></div>`;
  const $ = s => card.querySelector(s);
  const body = $('#wx-body');

  function paintMenus() {
    $('#wx-city-name').textContent = city;
    card.setAttribute('aria-label', `Thời tiết ${city}`);
    $('#wx-city-menu').innerHTML = `<p>Thời tiết ở</p>${CITIES.map(([n]) => `<button type="button" role="menuitemradio" aria-checked="${n === city}" data-city="${esc(n)}">${esc(n)}</button>`).join('')}`;
    $('#wx-more-menu').innerHTML = `<button type="button" role="menuitem" data-wx-unit>Đổi sang ${unit === 'C' ? '°F' : '°C'}</button>
      <button type="button" role="menuitem" data-wx-refresh>Cập nhật dự báo</button>
      <a role="menuitem" href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Dữ liệu: Open-Meteo <span aria-hidden="true">↗</span></a>`;
  }

  function columns() {
    if (mode === 'daily') {
      const d = data.daily, from = page * 5;
      return d.time.slice(from, from + 5).map((t, k) => {
        const i = from + k, [label, kind] = describe(d.weather_code[i]);
        const name = i === 0 ? 'Nay' : WEEKDAY[wdOf(t)];
        return `<li aria-label="${i === 0 ? 'Hôm nay' : WEEKDAY_FULL[wdOf(t)]}: ${esc(label.toLowerCase())}, cao ${deg(d.temperature_2m_max[i])} độ, thấp ${deg(d.temperature_2m_min[i])} độ"><span>${name}</span>${sym(kind, true)}<span class="wx-hi">${deg(d.temperature_2m_max[i])}°</span><span class="wx-lo">${deg(d.temperature_2m_min[i])}°</span></li>`;
      }).join('');
    }
    const h = data.hourly, now = Date.parse(data.current.time);
    let start = h.time.findIndex(t => Date.parse(t) >= now - 36e5 + 1);
    if (start < 0) start = 0;
    const from = start + page * 5;
    return h.time.slice(from, from + 5).map((t, k) => {
      const i = from + k, [label, kind] = describe(h.weather_code[i]);
      const day = h.is_day ? h.is_day[i] === 1 : true;
      const rain = r0(h.precipitation_probability[i] ?? 0);
      const name = `${+t.slice(11, 13)}h`;
      return `<li aria-label="${name}: ${esc(label.toLowerCase())}, ${deg(h.temperature_2m[i])} độ, khả năng mưa ${rain}%"><span>${name}</span>${sym(kind, day)}<span class="wx-hi">${deg(h.temperature_2m[i])}°</span><span class="wx-lo">${rain}%</span></li>`;
    }).join('');
  }
  function paintColumns(animate) {
    const ul = $('#wx-days');
    if (!ul) return;
    const draw = () => { ul.innerHTML = columns(); ul.classList.remove('is-swapping'); };
    card.querySelectorAll('.wx-switch button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
    card.querySelectorAll('.wx-dots button').forEach(b => b.setAttribute('aria-current', String(+b.dataset.page === page)));
    if (!animate || matchMedia('(prefers-reduced-motion: reduce)').matches) { draw(); return; }
    ul.classList.add('is-swapping');
    setTimeout(draw, 120);
  }

  function paint(state) {
    paintMenus();
    if (state === 'loading') {
      body.innerHTML = '<div class="wx-skel" aria-hidden="true"><i></i><i></i><i></i></div><p class="sr" role="status">Đang lấy thời tiết</p>';
      return;
    }
    if (state === 'error') {
      body.innerHTML = '<div class="wx-error"><p>Chưa lấy được thời tiết.</p><button class="pill" type="button" data-wx-retry>Thử lại</button></div>';
      return;
    }
    const cur = data.current, [label, kind] = describe(cur.weather_code), day = cur.is_day === 1;
    const out = outlookText(data.daily);
    body.innerHTML = `<div class="wx-now">${sym(kind, day)}
        <p class="wx-temp num" role="img" aria-label="${deg(cur.temperature_2m)} độ ${unit}, ${esc(label.toLowerCase())}">${deg(cur.temperature_2m)}<small>°${unit}</small></p>
        <button class="wx-outlook" id="wx-outlook" type="button" aria-controls="wx-days" data-day="${out.day}">${esc(out.text)}${ICON.next}</button></div>
      <div class="wx-switch" role="group" aria-label="Kiểu dự báo"><button type="button" data-mode="hourly" aria-pressed="false">Hàng giờ</button><button type="button" data-mode="daily" aria-pressed="true">Hàng ngày</button></div>
      <ul class="wx-days num" id="wx-days" aria-live="polite"></ul>
      <div class="wx-foot">
        <div class="wx-dots" role="group" aria-label="Trang dự báo"><button type="button" data-page="0" aria-label="Trang 1" aria-current="true"></button><button type="button" data-page="1" aria-label="Trang 2" aria-current="false"></button></div>
        <button class="pill" id="wx-full" type="button" aria-expanded="false" aria-controls="wx-detail">Xem dự báo đầy đủ</button>
      </div>
      <div class="wx-detail" id="wx-detail" role="dialog" aria-label="Dự báo ${esc(city)} hôm nay" hidden>
        <div class="wx-detail-top"><p class="wx-detail-h">${esc(city)} · ${esc(label)}</p><button class="wx-more" type="button" data-wx-close aria-label="Đóng dự báo đầy đủ">${ICON.close}</button></div>
        <dl class="wx-stats num">
          <div><dt>Cảm giác như</dt><dd>${deg(cur.apparent_temperature)}°</dd></div>
          <div><dt>Cao / thấp hôm nay</dt><dd>${deg(data.daily.temperature_2m_max[0])}° / ${deg(data.daily.temperature_2m_min[0])}°</dd></div>
          <div><dt>Khả năng mưa</dt><dd>${r0(data.daily.precipitation_probability_max[0] ?? 0)}%</dd></div>
          <div><dt>Độ ẩm</dt><dd>${r0(cur.relative_humidity_2m)}%</dd></div>
          <div><dt>Gió</dt><dd>${r0(cur.wind_speed_10m)} km/h</dd></div>
        </dl>
        <p class="wx-credit">Dự báo của <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a></p>
      </div>`;
    paintColumns(false);
  }

  async function load(force = false) {
    const key = KEY_CACHE + city;
    if (!force) {
      try {
        const c = JSON.parse(store.get(key) || 'null');
        if (c && Date.now() - c.at < CACHE_MS && c.d && c.d.current) { data = c.d; paint('ok'); return; }
      } catch { /* a broken cache is fetched again */ }
    }
    paint('loading');
    const [, lat, lon] = CITIES.find(c => c[0] === city);
    try {
      const r = await fetch(forecastURL(lat, lon), { signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (!d.current || !d.hourly || !d.daily) throw new Error('dự báo thiếu dữ liệu');
      data = d;
      store.set(key, JSON.stringify({ at: Date.now(), d }));
      paint('ok');
    } catch (e) {
      console.warn('weather unavailable', e);
      paint('error');
    }
  }

  /* The two menus: they grow from their button, close on a pick, Escape or a click elsewhere. */
  const menuOf = btn => $('#' + btn.getAttribute('aria-controls'));
  function closeMenu(btn, focus = false) {
    const m = menuOf(btn);
    if (!m || m.hidden) return;
    btn.setAttribute('aria-expanded', 'false');
    m.setAttribute('data-closed', '');
    setTimeout(() => { if (m.hasAttribute('data-closed')) m.hidden = true; }, 160);
    if (focus) btn.focus();
  }
  function openMenu(btn) {
    const m = menuOf(btn);
    card.querySelectorAll('.wx-head [aria-haspopup]').forEach(b => { if (b !== btn) closeMenu(b); });
    m.hidden = false;
    requestAnimationFrame(() => m.removeAttribute('data-closed'));
    btn.setAttribute('aria-expanded', 'true');
    (m.querySelector('[aria-checked="true"]') || m.querySelector('button, a')).focus({ preventScroll: true });
  }
  const closeAll = (focus = false) => {
    card.querySelectorAll('.wx-head [aria-haspopup][aria-expanded="true"]').forEach(b => closeMenu(b, focus));
    const det = $('#wx-detail');
    if (det && !det.hidden) { det.hidden = true; $('#wx-full').setAttribute('aria-expanded', 'false'); if (focus) $('#wx-full').focus(); }
  };

  card.addEventListener('click', e => {
    const t = e.target instanceof Element ? e.target : null;
    if (!t) return;
    const pop = t.closest('.wx-head [aria-haspopup]');
    if (pop) { if (pop.getAttribute('aria-expanded') === 'true') closeMenu(pop); else openMenu(pop); return; }
    const pick = t.closest('[data-city]');
    if (pick) { city = pick.dataset.city; store.set(KEY_CITY, city); closeMenu($('#wx-city')); mode = 'daily'; page = 0; load().then(() => $('#wx-city').focus()); return; }
    if (t.closest('[data-wx-unit]')) { unit = unit === 'C' ? 'F' : 'C'; store.set(KEY_UNIT, unit); closeMenu($('#wx-more')); if (data) paint('ok'); return; }
    if (t.closest('[data-wx-refresh]')) { closeMenu($('#wx-more')); load(true); return; }
    if (t.closest('#wx-more-menu a')) { closeMenu($('#wx-more')); return; }
    if (t.closest('[data-wx-retry]')) { load(true); return; }
    const sw = t.closest('.wx-switch button');
    if (sw && sw.dataset.mode !== mode) { mode = sw.dataset.mode; page = 0; paintColumns(true); return; }
    const dot = t.closest('.wx-dots button');
    if (dot && +dot.dataset.page !== page) { page = +dot.dataset.page; paintColumns(true); return; }
    const ol = t.closest('#wx-outlook');
    if (ol) { mode = 'daily'; page = +ol.dataset.day >= 5 ? 1 : 0; paintColumns(true); return; }
    if (t.closest('#wx-full')) { const det = $('#wx-detail'); det.hidden = !det.hidden; $('#wx-full').setAttribute('aria-expanded', String(!det.hidden)); if (!det.hidden) det.querySelector('[data-wx-close]').focus(); return; }
    if (t.closest('[data-wx-close]')) { closeAll(true); }
  });
  card.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const open = card.querySelector('.wx-head [aria-expanded="true"]') || ($('#wx-detail') && !$('#wx-detail').hidden);
      if (open) { e.stopPropagation(); closeAll(true); }
      return;
    }
    const m = e.target instanceof Element && e.target.closest('.wx-menu');
    if (!m) return;
    const items = [...m.querySelectorAll('button, a')], i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0].focus(); }
    else if (e.key === 'End') { e.preventDefault(); items[items.length - 1].focus(); }
    else if (e.key === 'Tab') closeAll(false);
  });
  document.addEventListener('pointerdown', e => { if (!card.contains(e.target)) closeAll(false); });
  load();
  return card;
}

/* The new tab's weather (captain, 07/11: "thanh tìm kiếm google, thời tiết và các nút truy cập nhanh các dịch vụ
   google"). Open-Meteo, no key and no account. The reader picks the city (Hà Nội by default) and the choice is kept on
   this machine; the browser's location is never asked for, and no manifest permission is added (the page reads
   Open-Meteo's public CORS answer). The slim row shows now; a click opens the detail: the next hours and days (the point
   taken from mockup A). Forecasts are kept for 30 minutes per city. */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = (id, cls = 'i') => `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;
const KEY_CITY = 'halcyon:city';
const KEY_CACHE = 'halcyon:wx:';
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
const symbol = (kind, day) => kind === 'clear' ? (day ? 'w-clear-day' : 'w-clear-night') : `w-${kind}`;
export const forecastURL = (lat, lon) => 'https://api.open-meteo.com/v1/forecast'
  + `?latitude=${lat}&longitude=${lon}`
  + '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day'
  + '&hourly=temperature_2m,weather_code,precipitation_probability'
  + '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'
  + '&timezone=Asia%2FBangkok&forecast_days=5';

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window: this tab only */ } },
};
const WEEKDAY = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
const r0 = v => Math.round(Number(v));

export function createWeather(root) {
  let city = store.get(KEY_CITY);
  if (!CITIES.some(c => c[0] === city)) city = CITIES[0][0];
  let data = null;

  const cityMenu = () => `<div class="wx-menu" id="wx-menu" role="menu" aria-label="Chọn thành phố"><p class="wx-menu-label">Thời tiết ở</p>${CITIES.map(([n]) =>
    `<button type="button" role="menuitemradio" aria-checked="${n === city}" data-city="${esc(n)}">${esc(n)}</button>`).join('')}</div>`;
  const cityBtn = () => `<button class="wx-city" id="wx-city" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="wx-menu">${esc(city)}${icon('i-down')}<span class="sr">, đổi thành phố</span></button>`;

  function detailHTML(d) {
    const cur = d.current, [label, kind] = describe(cur.weather_code);
    const now = Date.parse(cur.time);
    let from = d.hourly.time.findIndex(t => Date.parse(t) >= now);
    if (from < 0) from = 0;
    const hours = d.hourly.time.slice(from, from + 6).map((t, k) => {
      const i = from + k, [hl, hk] = describe(d.hourly.weather_code[i]);
      return `<li><span>${esc(t.slice(11, 13))}h</span>${icon(symbol(hk, true))}<b class="num">${r0(d.hourly.temperature_2m[i])}°</b><span class="wx-rain num" title="${esc(hl)}">${r0(d.hourly.precipitation_probability[i] ?? 0)}%</span></li>`;
    }).join('');
    const days = d.daily.time.slice(0, 5).map((t, i) => {
      const [dl, dk] = describe(d.daily.weather_code[i]);
      const name = i === 0 ? 'Hôm nay' : i === 1 ? 'Ngày mai' : WEEKDAY[new Date(t + 'T00:00:00Z').getUTCDay()];
      return `<li><span class="wx-dname">${name}</span>${icon(symbol(dk, true))}<span class="wx-dlabel">${esc(dl)}</span><span class="wx-rain num">${r0(d.daily.precipitation_probability_max[i] ?? 0)}% mưa</span><span class="wx-range num">${r0(d.daily.temperature_2m_max[i])}° <span>/ ${r0(d.daily.temperature_2m_min[i])}°</span></span></li>`;
    }).join('');
    return `<div class="wx-panel" id="wx-panel" role="dialog" aria-label="Thời tiết ${esc(city)}" hidden>
      <div class="wx-big">${icon(symbol(kind, cur.is_day === 1), 'i wx-big-i')}<div><p class="wx-big-t num">${r0(cur.temperature_2m)}°C</p><p class="wx-big-l">${esc(label)} · ${esc(city)}</p></div></div>
      <p class="wx-stats"><span>Cảm giác <b class="num">${r0(cur.apparent_temperature)}°</b></span><span>Độ ẩm <b class="num">${r0(cur.relative_humidity_2m)}%</b></span><span>Gió <b class="num">${r0(cur.wind_speed_10m)} km/h</b></span></p>
      <h3 class="wx-h">Mấy giờ tới</h3><ul class="wx-hours">${hours}</ul>
      <h3 class="wx-h">Những ngày tới</h3><ul class="wx-days">${days}</ul>
      <p class="wx-credit">Dự báo của <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a></p></div>`;
  }

  function paint(state) {
    if (state === 'loading') {
      root.innerHTML = `<span class="wx-skel" aria-hidden="true"></span><span class="sr">Đang lấy thời tiết</span>${cityBtn()}${cityMenu()}`;
    } else if (state === 'error') {
      root.innerHTML = `${cityBtn()}<span class="wx-detail">Chưa lấy được thời tiết.</span><button class="wx-retry" type="button" data-wx-retry>Thử lại</button>${cityMenu()}`;
    } else {
      const cur = data.current, [label, kind] = describe(cur.weather_code);
      const max = data.daily.temperature_2m_max[0], min = data.daily.temperature_2m_min[0], rain = data.daily.precipitation_probability_max[0];
      root.innerHTML = `<button class="wx-now" id="wx-now" type="button" aria-expanded="false" aria-controls="wx-panel" aria-label="Thời tiết ${esc(city)}: ${r0(cur.temperature_2m)} độ, ${esc(label)}. Xem dự báo">${icon(symbol(kind, cur.is_day === 1))}<span class="wx-temp num">${r0(cur.temperature_2m)}°</span></button>`
        + cityBtn()
        + `<button class="wx-detail" type="button" data-wx-open tabindex="-1" aria-hidden="true">${esc(label)} · <span class="num">${r0(min)}–${r0(max)}°</span>${rain != null ? ` · mưa <span class="num">${r0(rain)}%</span>` : ''}</button>`
        + cityMenu() + detailHTML(data);
    }
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
      if (!d.current || !d.hourly || !d.daily) throw new Error('incomplete forecast');
      data = d;
      store.set(key, JSON.stringify({ at: Date.now(), d }));
      paint('ok');
    } catch (e) {
      console.warn('weather unavailable', e);
      paint('error');
    }
  }

  const menu = () => root.querySelector('#wx-menu');
  const panel = () => root.querySelector('#wx-panel');
  function closeAll(focusFrom) {
    const m = menu(), p = panel();
    if (m && m.classList.contains('open')) { m.classList.remove('open'); root.querySelector('#wx-city').setAttribute('aria-expanded', 'false'); if (focusFrom) root.querySelector('#wx-city').focus(); }
    if (p && !p.hidden) { p.hidden = true; root.querySelector('#wx-now').setAttribute('aria-expanded', 'false'); if (focusFrom) root.querySelector('#wx-now').focus(); }
  }
  root.addEventListener('click', e => {
    const t = e.target instanceof Element ? e.target : null;
    if (!t) return;
    if (t.closest('[data-wx-retry]')) { load(true); return; }
    const pick = t.closest('[data-city]');
    if (pick) { city = pick.dataset.city; store.set(KEY_CITY, city); closeAll(false); load().then(() => root.querySelector('#wx-city')?.focus()); return; }
    if (t.closest('#wx-city')) {
      const m = menu(), open = !m.classList.contains('open');
      closeAll(false);
      if (open) { m.classList.add('open'); t.closest('#wx-city').setAttribute('aria-expanded', 'true'); (m.querySelector('[aria-checked="true"]') || m.querySelector('button')).focus(); }
      return;
    }
    if (t.closest('#wx-now, [data-wx-open]')) {
      const p = panel(), open = p.hidden;
      closeAll(false);
      if (open) { p.hidden = false; root.querySelector('#wx-now').setAttribute('aria-expanded', 'true'); }
    }
  });
  root.addEventListener('keydown', e => {
    const m = menu();
    if (e.key === 'Escape') { e.stopPropagation(); closeAll(true); return; }
    if (!m || !m.classList.contains('open')) return;
    const items = [...m.querySelectorAll('button')], i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0].focus(); }
    else if (e.key === 'End') { e.preventDefault(); items[items.length - 1].focus(); }
    else if (e.key === 'Tab') closeAll(false);
  });
  document.addEventListener('pointerdown', e => { if (!root.contains(e.target)) closeAll(false); });
  load();
  return { load };
}

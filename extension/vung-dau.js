/* The new tab's first two rows (captain, 07/11 18:03, mockup D "Dòng ngày" chosen 18:26): the Google services, then
   the Google search (newtab.js) with the day line under it: the date, the lunar date and the weather.
   The website home has none of this; extension/sync-site.py puts these rows where the site has its masthead. */
import { solarToLunar, lunarText, todayVN } from './lich-am.js';
import { createWeather } from './thoi-tiet.js';

const $ = s => document.querySelector(s);

/* The day line under the search (mockup D, 07/11 18:26): the date, the lunar date, then the weather. The words are
   read in full; a phone shows the numeric form ("Thứ Bảy, 7/11 · 29/9 âm lịch"), hidden from screen readers so the
   date is announced once. */
function renderDateline() {
  const t = todayVN(), l = solarToLunar(t.d, t.m, t.y);
  const lunar = lunarText(l).replace(/^Âm lịch /, '').replace(', năm ', ' năm ');
  $('#day-date').innerHTML = `<span class="d-long"><b>${t.weekday}, ${t.d} tháng ${t.m}, ${t.y}</b><span class="sep" aria-hidden="true">·</span><span class="lunar"><span class="sr">Âm lịch </span>${lunar}</span></span>`
    + `<span class="d-short" aria-hidden="true"><b>${t.weekday}, ${t.d}/${t.m}</b><span class="sep">·</span><span class="lunar">${l.day}/${l.month}${l.leap ? ' nhuận' : ''} âm lịch</span></span>`;
}

/* Google's own published product icons; a letter holds the place until one loads (offline, blocked). The Calendar
   icon carries today's date, as Google's own does. Row 1 is icons only at every width (captain, 07/11 22:41: "thu gọn
   mấy cái truy cập nhanh đi"): each link is named by aria-label for screen readers and by title on hover. */
const fav = host => `https://www.google.com/s2/favicons?domain=${host}&sz=64`;
export const SERVICES = [
  ['Gmail', 'https://mail.google.com/', 'https://ssl.gstatic.com/images/branding/product/2x/gmail_2020q4_48dp.png'],
  ['YouTube', 'https://www.youtube.com/', fav('www.youtube.com')],
  ['Drive', 'https://drive.google.com/', 'https://ssl.gstatic.com/images/branding/product/2x/drive_2020q4_48dp.png'],
  ['Maps', 'https://www.google.com/maps', fav('maps.google.com')],
  ['Lịch', 'https://calendar.google.com/', day => `https://ssl.gstatic.com/calendar/images/dynamiclogo_2020q4/calendar_${day}_2x.png`],
  ['Dịch', 'https://translate.google.com/', fav('translate.google.com')],
  ['Gemini', 'https://gemini.google.com/', fav('gemini.google.com')],
];
function renderServices() {
  const day = todayVN().d;
  const list = $('#services');
  list.innerHTML = SERVICES.map(([name, url, src]) => `<li><a class="svc" href="${url}" title="${name}" aria-label="${name}">
    <span class="svc-icon" aria-hidden="true"><span class="svc-letter">${name[0]}</span><img src="${typeof src === 'function' ? src(day) : src}" width="20" height="20" alt="" referrerpolicy="no-referrer" hidden></span></a></li>`).join('');
  list.querySelectorAll('img').forEach(img => {
    img.addEventListener('load', () => { img.hidden = false; img.previousElementSibling.hidden = true; }, { once: true });
  });
}

renderDateline();
renderServices();
createWeather($('#weather'));

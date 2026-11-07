/* The new tab's top zone (captain, 07/11 13:15 and 13:54, mockup B with mockup A's named service buttons): the date
   with the lunar date, the web search (newtab.js keeps chrome.search.query), the weather and the Google services.
   The website home has none of this; extension/sync-site.py places the zone between the masthead and the news bar. */
import { solarToLunar, lunarText, todayVN } from './lich-am.js';
import { createWeather } from './thoi-tiet.js';

const $ = s => document.querySelector(s);

/* The date sits in the masthead beside the wordmark (07/11 17:12, the top zone gives its height back to the news). The
   words are read in full; narrow screens show the numeric form ("T7, 7/11 · 29/9 âm lịch"), which is hidden from
   screen readers so the date is announced once. */
const WD_SHORT = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
function renderDateline() {
  const t = todayVN(), l = solarToLunar(t.d, t.m, t.y);
  const wd = WD_SHORT[new Date(Date.UTC(t.y, t.m - 1, t.d)).getUTCDay()];
  $('#dateline').innerHTML = `<span class="d-long"><b>${t.weekday}, ${t.d} tháng ${t.m}, ${t.y}</b><span class="sep" aria-hidden="true">·</span><span class="lunar">${lunarText(l)}</span></span>`
    + `<span class="d-short" aria-hidden="true"><b>${wd}, ${t.d}/${t.m}</b><span class="sep">·</span><span class="lunar">${l.day}/${l.month}${l.leap ? ' nhuận' : ''} âm lịch</span></span>`;
}

/* Google's own published product icons; a letter holds the place until one loads (offline, blocked). The Calendar
   icon carries today's date, as Google's own does. Each button names its service (mockup A). */
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
  list.innerHTML = SERVICES.map(([name, url, src]) => `<li><a class="svc" href="${url}" title="${name}">
    <span class="svc-icon" aria-hidden="true"><span class="svc-letter">${name[0]}</span><img src="${typeof src === 'function' ? src(day) : src}" width="24" height="24" alt="" referrerpolicy="no-referrer" hidden></span><span class="svc-name">${name}</span></a></li>`).join('');
  list.querySelectorAll('img').forEach(img => {
    img.addEventListener('load', () => { img.hidden = false; img.previousElementSibling.hidden = true; }, { once: true });
  });
}

renderDateline();
renderServices();
createWeather($('#weather'));

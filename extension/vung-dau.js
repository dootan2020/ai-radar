/* The new tab's first two rows (captain, 07/11 18:03, mockup D "Dòng ngày" chosen 18:26): the Google services, then
   the Google search (newtab.js). The day line that sat under the search is gone (08/11, mockup H): its date, lunar date
   and weather live on the calendar card in the bento (the-lich.js).
   The website home has none of this; extension/sync-site.py puts these rows where the site has its masthead. */
import { todayVN } from './lich-am.js';
import { mountCalendarCard } from './the-lich.js';

const $ = s => document.querySelector(s);

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

renderServices();
mountCalendarCard();

/* The new tab's first two rows (captain, 07/11 18:03, mockup D "Dòng ngày" chosen 18:26): the Google services, then
   the Google search (newtab.js). They play the part of MSN's search bar above the Halcyon panel (Mẫu A, 08/11 18:23).
   The weather and the calendar are cards in the panel's first row, the same as on the website (feed.js builds them).
   The website home has none of this; extension/sync-site.py puts these rows where the site has its top row. */
import { todayVN } from './lich-am.js';

const $ = s => document.querySelector(s);

/* Each product's own colour logo, sharp at any screen density: Google's 96px product icons, or the vector logos shipped
   with the extension (google-apps/, CC0 "SVG Logos" set, see google-apps/LICENSE.txt) where the 64px favicon service was
   blurry (08/11). A letter holds the place until one loads (offline, blocked). The Calendar icon carries today's date,
   as Google's own does. Row 1 is icons only at every width (captain, 07/11 22:41: "thu gọn mấy cái truy cập nhanh đi"):
   each link is named by aria-label for screen readers and by title on hover. */
const GS = 'https://ssl.gstatic.com/images/branding/product/2x/';
export const SERVICES = [
  ['Gmail', 'https://mail.google.com/', GS + 'gmail_2020q4_48dp.png'],
  ['YouTube', 'https://www.youtube.com/', 'google-apps/youtube.svg'],
  ['Drive', 'https://drive.google.com/', GS + 'drive_2020q4_48dp.png'],
  ['Maps', 'https://www.google.com/maps', 'google-apps/maps.svg'],
  ['Lịch', 'https://calendar.google.com/', day => `https://ssl.gstatic.com/calendar/images/dynamiclogo_2020q4/calendar_${day}_2x.png`],
  ['Dịch', 'https://translate.google.com/', GS + 'translate_96dp.png'],
  ['Gemini', 'https://gemini.google.com/', 'google-apps/gemini.svg'],
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

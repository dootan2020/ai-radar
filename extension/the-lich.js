/* The calendar card of the front page, on the website home and the new tab alike: a page of a Vietnamese tear-off
   calendar (lịch bloc). Captain, 08/11 21:08: "Đưa con giáp tháng hoặc ngày, làm nền cho card lịch. Thiết kế lại card
   lịch cho giống phong cách lịch phương đông".
   The page, top to bottom: the coral band with the month and the year (the red head of a lịch bloc), the big solar day
   and its weekday (Sunday in coral, as the printed calendars do), then the lunar half: the lunar day large with its
   month on the left, the can chi of the day, the month and the year and the solar term on the right, and one note.
   Behind it all, the animal of the day as a coral seal: the day's animal changes every day, as a torn page does, while
   the month's would stay a month and the year's a year (on 08/11/2026 the day and the month are both Tuất).
   Everything is computed from today's date (lich-am.js); the twelve illustrations ship in con-giap/ (Fluent Emoji flat,
   MIT) and nothing is fetched for them. */
import { calendarDay, lunarMonthName, todayVN } from './lich-am.js';

// Resolved from this module, so the card draws the same on the home page, the new tab and the design showcase.
const art = file => new URL(`con-giap/${file}.svg`, import.meta.url).href;
const two = n => String(n).padStart(2, '0');
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

function cardHTML(c) {
  const a = c.animals, sunday = c.wdi === 0 ? ' is-sunday' : '';
  // On mùng 1 and rằm the note would only repeat the lunar date printed above it (captain, 09/11: "bỏ được thì bỏ").
  const note = c.lunar.day === 1 || c.lunar.day === 15 ? '' : c.note;
  return `<h2 class="sr">Hôm nay ${c.weekday}, ${c.d} tháng ${c.m} năm ${c.y}; âm lịch ${c.lunarDay}, năm ${a.year.canchi}, năm con ${a.year.name}; ngày ${a.day.canchi} (con ${a.day.name}), tháng ${a.month.canchi} (con ${a.month.name}); tiết ${c.term}. ${c.note}</h2>
    <span class="cal-art" aria-hidden="true"></span>
    <p class="cal-band" aria-hidden="true"><span>Tháng ${c.m}</span><span class="num">${c.y}</span></p>
    <div class="cal-hero${sunday}" aria-hidden="true"><span class="cal-day num">${two(c.d)}</span><span class="cal-week">${c.weekday}</span></div>
    <div class="cal-moon" aria-hidden="true">
      <p class="cal-lunar"><span class="cal-k">Âm lịch</span><b class="num">${two(c.lunar.day)}</b><span>${cap(lunarMonthName(c.lunar))}</span></p>
      <ul class="cal-canchi"><li>Ngày <b>${a.day.canchi}</b></li><li>Tháng <b>${a.month.canchi}</b></li><li>Năm <b>${a.year.canchi}</b></li><li>Tiết <b>${c.term}</b></li></ul>
    </div>
    ${note ? `<p class="cal-note" aria-hidden="true">${note}</p>` : ''}`;
}

/* The card element, filled for today. */
export function createCalendarCard(now = new Date()) {
  const t = todayVN(now);
  const c = calendarDay(t.d, t.m, t.y);
  const card = document.createElement('article');
  card.className = 'msn-card msn-cal';
  card.id = 'the-lich';
  card.dataset.animal = c.animals.day.file;
  card.setAttribute('aria-label', `Lịch dương và lịch âm ngày ${t.d} tháng ${t.m} năm ${t.y}`);
  card.innerHTML = cardHTML(c);
  card.style.setProperty('--cal-art', `url("${art(c.animals.day.file)}")`);
  return card;
}

/* The calendar card of the front page (Mẫu A, captain 08/11 18:23), on the website home and the new tab alike.
   The mockup's layout: "Lịch hôm nay" and the date, the big day with the year's animal, the weekday, the lunar block and
   one note. The band between the weekday and the lunar block carries the approved "Linh vật của năm" card's content
   (mockup H, 08/11 01:23): the day's and the month's animals with their can chi, so the card is full.
   Everything is computed from today's date (lich-am.js); the twelve illustrations ship in con-giap/ (Fluent Emoji flat,
   MIT) and nothing is fetched for them. */
import { calendarDay, todayVN } from './lich-am.js';

// Resolved from this module, so the card draws the same on the home page, the new tab and the design showcase.
const art = file => new URL(`con-giap/${file}.svg`, import.meta.url).href;
const two = n => String(n).padStart(2, '0');

function cardHTML(c) {
  const a = c.animals;
  const chip = (label, x) => `<li class="cal-chip"><img src="${art(x.file)}" alt="" width="28" height="28"><span>${label} <b>${x.canchi}</b></span></li>`;
  return `<h2 class="sr">Hôm nay ${c.weekday}, ${c.d} tháng ${c.m} năm ${c.y}; âm lịch ${c.lunarDay}, năm ${a.year.canchi}, năm con ${a.year.name}; ngày ${a.day.canchi} (con ${a.day.name}), tháng ${a.month.canchi} (con ${a.month.name}); tiết ${c.term}. ${c.note}</h2>
    <p class="cal-label" aria-hidden="true"><span>Lịch hôm nay</span><span class="num">${two(c.d)}/${two(c.m)}/${c.y}</span></p>
    <div class="cal-top" aria-hidden="true"><span class="cal-day num">${two(c.d)}</span><img class="cal-animal" src="${art(a.year.file)}" alt="" width="64" height="64"></div>
    <p class="cal-week${c.wdi === 0 ? ' is-sunday' : ''}" aria-hidden="true">${c.weekday}</p>
    <ul class="cal-chips" aria-hidden="true">${chip('Ngày', a.day)}${chip('Tháng', a.month)}</ul>
    <div class="cal-lunar" aria-hidden="true"><strong>${c.lunarDay} âm lịch</strong><span>Năm ${a.year.canchi} · ${c.term}</span></div>
    ${c.note ? `<p class="cal-note" aria-hidden="true">${c.note}</p>` : ''}`;
}

/* The card element, filled for today. */
export function createCalendarCard(now = new Date()) {
  const t = todayVN(now);
  const card = document.createElement('article');
  card.className = 'msn-card msn-cal';
  card.id = 'the-lich';
  card.setAttribute('aria-label', `Lịch dương và lịch âm ngày ${t.d} tháng ${t.m} năm ${t.y}`);
  card.innerHTML = cardHTML(calendarDay(t.d, t.m, t.y));
  return card;
}

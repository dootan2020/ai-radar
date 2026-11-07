/* The calendar card "Linh vật của năm" (mockup H, captain 08/11 01:23: "H linh vật năm"; asked for 07/11 23:15: "tạo 1
   cái card lịch và thời tiết cho user tiếng việt đi", and 08/11 00:46: "đẹp, hiện đại, có trang trí giống như lịch âm …
   là các con vật trong lịch âm ứng theo ngày tháng năm đó").
   The day as the wall calendar prints it: the big number, the weekday, the lunar day and one note; the year's animal on a
   soft coral disc running off the top-right corner; the day's and the month's animals as two chips with their can chi;
   the weather at the foot with the city switch. On a phone the same element becomes one strip before the lead (mockup
   I's strip: number and weekday, lunar day, weather, then the three animals). Everything is computed from today's date
   (lich-am.js); the twelve illustrations ship in con-giap/ (Fluent Emoji flat, MIT), nothing is fetched for them. */
import { calendarDay, todayVN } from './lich-am.js';
import { createWeather } from './thoi-tiet.js';

const art = file => `con-giap/${file}.svg`;

function cardHTML(c) {
  const a = c.animals;
  const chip = (cls, label, x) => `<li class="cal-chip ${cls}"><i><img src="${art(x.file)}" alt="" width="26" height="26"></i><span><span class="cal-chip-k">${label} </span><b>${x.canchi}</b></span></li>`;
  return `<h2 class="sr">Hôm nay ${c.weekday}, ${c.d} tháng ${c.m} năm ${c.y}; âm lịch ${c.lunarDay}, năm ${a.year.canchi}, năm con ${a.year.name}; ngày ${a.day.canchi} (con ${a.day.name}), tháng ${a.month.canchi} (con ${a.month.name}). ${c.note}</h2>
    <div class="cal-art" aria-hidden="true"><span class="cal-disc"></span><img class="cal-hero" src="${art(a.year.file)}" alt="" width="196" height="196"></div>
    <p class="cal-head" aria-hidden="true">Tháng ${c.m}, ${c.y}</p>
    <p class="cal-day num" aria-hidden="true">${c.d}</p>
    <p class="cal-wd${c.wdi === 0 ? ' is-sunday' : ''}" aria-hidden="true">${c.weekday}</p>
    <p class="cal-year" aria-hidden="true"><span class="cal-year-k">Năm </span><b>${a.year.canchi}</b></p>
    <p class="cal-lday" aria-hidden="true">${c.lunarDay}<span class="cal-lday-k"> âm lịch</span></p>
    <p class="cal-note" aria-hidden="true">${c.note}</p>
    <ul class="cal-chips" aria-hidden="true">${chip('is-day', 'Ngày', a.day)}${chip('is-month', 'Tháng', a.month)}${chip('is-year', 'Năm', a.year)}</ul>
    <div class="cal-wx"><div class="wx weather" id="weather" aria-live="polite"><span class="wx-skel" aria-hidden="true"></span><span class="sr">Đang lấy thời tiết</span></div></div>`;
}

/* The card element, filled for today; the weather starts loading into its foot. */
export function createCalendarCard(now = new Date()) {
  const t = todayVN(now);
  const card = document.createElement('section');
  card.className = 'the-lich';
  card.id = 'the-lich';
  card.setAttribute('aria-label', 'Lịch hôm nay và thời tiết');
  card.innerHTML = cardHTML(calendarDay(t.d, t.m, t.y));
  createWeather(card.querySelector('#weather'));
  return card;
}

/* Where the card stands: in the first bento that renders, right after its lead (the lead spans two rows, the card sits
   at its natural height top right and the next story fills the space under it; on a phone CSS moves it before the
   lead). A view with no bento (Xếp hạng) shows no card. feed.js rewrites the grids on every filter, sort and page, so
   the card is put back after each change; it is the same element, so the weather and the city menu keep their state. */
export function placeCalendarCard(card) {
  const picks = document.querySelector('#picks'), pickGrid = document.querySelector('#picks-grid');
  const feedGrid = document.querySelector('#feed-grid');
  const grid = picks && !picks.hidden && pickGrid && pickGrid.children.length ? pickGrid
    : feedGrid && !feedGrid.hidden && feedGrid.children.length ? feedGrid : null;
  if (!grid) { card.hidden = true; return; }
  card.hidden = false;
  const lead = grid.firstElementChild && grid.firstElementChild !== card && grid.firstElementChild.matches('.card-lead') ? grid.firstElementChild : null;
  if (lead) { if (lead.nextElementSibling !== card) lead.after(card); }
  else if (grid.firstElementChild !== card) grid.prepend(card);
  if (grid === pickGrid) lendNextStory(pickGrid, feedGrid, card);
}

/* When the front page's first row holds the lead alone (no second story young enough), the space under the card would
   stay empty beside a tall lead. The first story of the river's first row moves up under the card instead: it keeps
   its place in the reading order (the picks come before the river in the page), and the two stories left in that row
   share it (the-lich.css, .has-lent). feed.js rebuilds both grids on every view, so the lent story goes back with them. */
function lendNextStory(pickGrid, feedGrid, card) {
  if (!feedGrid) return;
  const lent = pickGrid.querySelector(':scope > .is-lent');
  if (lent && feedGrid.querySelector(`[data-sid="${CSS.escape(lent.dataset.sid || '')}"]`)) lent.remove();   // the river was rebuilt alone
  const alone = pickGrid.lastElementChild === card;
  const first = feedGrid.firstElementChild;
  if (alone && first && first.matches('.feed-card.card-card[data-sid]')) {
    first.classList.add('is-lent');
    card.after(first);
  }
  feedGrid.classList.toggle('has-lent', !!pickGrid.querySelector(':scope > .is-lent'));
}

export function mountCalendarCard() {
  const card = createCalendarCard();
  card.hidden = true;
  const grids = ['#picks', '#picks-grid', '#feed-grid'].map(s => document.querySelector(s)).filter(Boolean);
  const place = () => placeCalendarCard(card);
  // Runs before the next paint, in the same frame as feed.js's render, so placing the card shifts nothing on screen.
  const watch = new MutationObserver(place);
  grids.forEach(el => watch.observe(el, { childList: true, attributes: true, attributeFilter: ['hidden'] }));
  // Until a grid renders, the card waits outside the page, ready.
  place();
  return card;
}

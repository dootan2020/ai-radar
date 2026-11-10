/* How the page words time: relative ages, event countdowns, and YouTube fallback times shown as printed and
   never turned into instants.
   Pure functions (no DOM) so tests/test_app_streams.py can run them under Node. */

/* "Streamed 1d ago" -> "Đã phát 1 ngày trước". Anything else (or an unsafe number) -> null. */
export function streamedAge(text){
  const m = /^Streamed (\d+)\s*(second|minute|hour|day|s|m|h|d)s? ago$/i.exec(text || '');
  if (!m || !Number.isSafeInteger(Number(m[1]))) return null;
  const unit = {s:'giây', m:'phút', h:'giờ', d:'ngày'}[m[2][0].toLowerCase()];
  return `Đã phát ${m[1]} ${unit} trước`;
}

/* Clock and calendar day as read in Vietnam, whatever the reader's machine timezone. */
export const TZ = 'Asia/Ho_Chi_Minh';
/* Formatters are built once: constructing an Intl.DateTimeFormat per call cost ~10 ms of the first render on a phone. */
const HHMM = new Intl.DateTimeFormat('vi-VN', {hour:'2-digit', minute:'2-digit', timeZone:TZ});
const DAY = new Intl.DateTimeFormat('en-CA', {timeZone:TZ});
const DATE = new Intl.DateTimeFormat('vi-VN', {day:'numeric', month:'numeric', year:'numeric', timeZone:TZ});
export const hhmm = d => HHMM.format(d);
export const dayKey = d => DAY.format(d);

/* A published time as the page words it. Under 24 hours it counts hours; from 24 hours on it counts calendar days,
   so "Hôm qua" only ever means the previous calendar day (24 hours back is always at least one day back). */
export function ago(iso, nowMs = Date.now()){
  if (!iso) return 'không rõ thời gian';
  const d = new Date(iso), h = (nowMs - d) / 36e5;
  if (Number.isNaN(h)) return 'không rõ thời gian';
  if (h < 0) return 'sắp tới';
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} phút trước`;
  if (h < 24) return `${Math.round(h)} giờ trước`;
  const days = Math.round((new Date(dayKey(new Date(nowMs))) - new Date(dayKey(d))) / 864e5);
  if (days <= 1) return `Hôm qua, ${hhmm(d)}`;
  if (days < 7) return `${days} ngày trước`;
  return DATE.format(d);
}

/* Days until an event, as a row reads it: "còn N ngày" ahead, "hôm nay" on the day, "đang diễn ra" once started. */
export function daysLeftHTML(n){
  if (!Number.isFinite(n)) return '';
  return n > 0 ? `còn <span class="num">${n}</span> ngày` : n === 0 ? 'hôm nay' : 'đang diễn ra';
}

/* An event's verified dates as a row reads them: "16 tháng 10", "6–12 tháng 12", "30 tháng 11 – 2 tháng 12".
   Takes the YYYY-MM-DD strings from events[]; anything else is printed as given rather than guessed. */
export function eventRange(start, end){
  const p = s => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ''); return m ? {y: +m[1], m: +m[2], d: +m[3]} : null; };
  const a = p(start), b = p(end);
  if (!a) return start ? String(start) : 'chưa rõ ngày';
  if (!b || end === start) return `${a.d} tháng ${a.m}`;
  if (a.y === b.y && a.m === b.m) return `${a.d}–${b.d} tháng ${a.m}`;
  return `${a.d} tháng ${a.m} – ${b.d} tháng ${b.m}${a.y !== b.y ? ` năm ${b.y}` : ''}`;
}

/* The same dates at a ruler's end: "16.10", "6–12.12", "30.11–2.12". With no end, the one day. */
export function eventShort(start, end){
  const p = s => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ''); return m ? {m: +m[2], d: +m[3]} : null; };
  const a = p(start), b = p(end);
  if (!a) return '';
  if (!b || end === start) return `${a.d}.${a.m}`;
  return a.m === b.m ? `${a.d}–${b.d}.${a.m}` : `${a.d}.${a.m}–${b.d}.${b.m}`;
}

/* The day ruler of the next-event card. Before the event: `before` ticks of waiting (the first is today; their count
   is the whole days left, the number the card prints) and `event` ticks for the event's own days. A tick is one day
   while the ruler holds at most RULER_MAX ticks; a longer wait is drawn in weeks, then in months (`unit` = 1, 7 or 30
   days). Once it has started: `event` ticks, `done` of them already past, and `day`, the day it is on.
   start, end and now are instants in ms; no ruler without a start, or once the event is over. */
export const RULER_MAX = 60;
export function rulerPlan(start, end, now){
  const DAY = 864e5;
  if (!Number.isFinite(start) || !Number.isFinite(now) || (Number.isFinite(end) && now >= end)) return null;
  const span = Number.isFinite(end) && end > start ? Math.max(1, Math.round((end - start) / DAY)) : 1;
  const on = now >= start;
  const days = on ? 0 : Math.max(1, Math.floor((start - now) / DAY));
  const total = days + span;
  const unit = total <= RULER_MAX ? 1 : Math.ceil(total / 7) <= RULER_MAX ? 7 : 30;
  const event = Math.max(1, Math.round(span / unit));
  if (!on) return { state: 'soon', unit, days, span, before: Math.max(1, Math.ceil(days / unit)), event };
  const day = Math.min(span, Math.floor((now - start) / DAY) + 1);
  return { state: 'on', unit, day, span, before: 0, event, done: Math.min(event - 1, Math.floor((day - 1) / unit)) };
}

/* "Scheduled for 10/5/26, 9:00 PM" keeps YouTube's own date and clock and says the timezone is unknown. */
export function scheduleText(text){
  const m = /^Scheduled for\s+(.+)$/i.exec(text || '');
  return m ? `Dự kiến: ${m[1].replace(/\bAM\b/gi, 'sáng').replace(/\bPM\b/gi, 'chiều')} (chưa rõ múi giờ)` : 'chưa rõ giờ';
}

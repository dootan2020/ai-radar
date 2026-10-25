/* "Thêm vào lịch": an .ics file built in the browser, nothing sent anywhere.
   Date-only events stay all-day events (no invented midnight or timezone); an exact start
   without a known end gets no DTEND rather than an invented duration. */

const esc = s => String(s ?? '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
const ymd = s => s.replaceAll('-', '');
/* A real calendar date (rejects 2026-02-31) and a parseable instant. */
const isDate = s => { if (!/^\d{4}-\d{2}-\d{2}$/.test(s || '')) return false; const [y, m, d] = s.split('-').map(Number); const t = new Date(Date.UTC(y, m - 1, d)); return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d; };
const isInstant = s => typeof s === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(s) && !Number.isNaN(Date.parse(s));
const isTimezone = s => {
  if (typeof s !== 'string' || !s) return false;
  try { new Intl.DateTimeFormat('en', { timeZone: s }); return true; } catch { return false; }
};
/* URL is a URI value (RFC 5545 3.3.13): no backslash escaping, only line breaks removed. */
const uri = s => String(s ?? '').replace(/[\r\n]+/g, '');
const utc = iso => new Date(iso).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
export function nextDay(s) {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}
/* First instant of a local date, independent of the browser's timezone. Search the
   date boundary so midnight offset changes and 23/25-hour DST days stay correct. */
export function dateStart(s, timezone) {
  if (!isDate(s) || !isTimezone(timezone)) return NaN;
  const formatter = new Intl.DateTimeFormat('en', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' });
  const localDate = ms => {
    const parts = Object.fromEntries(formatter.formatToParts(ms).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const center = Date.parse(`${s}T00:00:00Z`);
  let low = center - 36 * 36e5, high = center + 36 * 36e5;
  while (high - low > 1) {
    const mid = Math.floor((low + high) / 2);
    if (localDate(mid) < s) low = mid; else high = mid;
  }
  return high;
}
/* RFC 5545 folds lines at 75 octets; Vietnamese letters take 2–3 bytes, so fold by bytes. */
function fold(line) {
  const enc = new TextEncoder();
  let out = '', cur = '', n = 0;
  for (const ch of line) {
    const b = enc.encode(ch).length;
    if (n + b > 74) { out += cur + '\r\n '; cur = ''; n = 1; }
    cur += ch; n += b;
  }
  return out + cur;
}

/* The note on a curated event says where its date was verified; a missing part is left out, never printed as "undefined". */
export function verifiedNote(verifiedAt, sourceUrl) {
  if (!verifiedAt && !sourceUrl) return '';
  return ['Ngày đã xác minh', verifiedAt, sourceUrl ? `từ ${sourceUrl}` : ''].filter(Boolean).join(' ');
}

/* ev: {uid, title, url, location, startDate, endDate, startAt, endAt, timezone, note} */
/* Every value that reaches the file must be valid; an optional end may be absent but never malformed. */
export function canCalendar(ev) {
  if (!ev) return false;
  if (ev.timezone != null && !isTimezone(ev.timezone)) return false;
  if (ev.startAt) return isInstant(ev.startAt) && (!ev.endAt || (isInstant(ev.endAt) && Date.parse(ev.endAt) >= Date.parse(ev.startAt)));
  return isDate(ev.startDate) && (!ev.endDate || (isDate(ev.endDate) && ev.endDate >= ev.startDate));
}

export function buildIcs(ev) {
  if (!canCalendar(ev)) throw new Error('sự kiện không có ngày hợp lệ');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ai-radar//vi', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
    ...(ev.timezone ? [`X-WR-TIMEZONE:${esc(ev.timezone)}`] : []), 'BEGIN:VEVENT',
    `UID:${esc(ev.uid)}@ai-radar`, `DTSTAMP:${utc(new Date().toISOString())}`];
  if (ev.startAt) {
    lines.push(`DTSTART:${utc(ev.startAt)}`);
    // RFC 5545 3.8.2.2: DTEND must be later than DTSTART, so an end equal to the start is left out.
    if (ev.endAt && Date.parse(ev.endAt) > Date.parse(ev.startAt)) lines.push(`DTEND:${utc(ev.endAt)}`);
  } else {
    lines.push(`DTSTART;VALUE=DATE:${ymd(ev.startDate)}`, `DTEND;VALUE=DATE:${ymd(nextDay(ev.endDate || ev.startDate))}`);
  }
  lines.push(`SUMMARY:${esc(ev.title)}`);
  if (ev.location) lines.push(`LOCATION:${esc(ev.location)}`);
  if (ev.url) lines.push(`URL:${uri(ev.url)}`);
  lines.push(`DESCRIPTION:${esc([ev.note, ev.url].filter(Boolean).join('\n'))}`, 'END:VEVENT', 'END:VCALENDAR');
  return lines.map(fold).join('\r\n') + '\r\n';
}

export function downloadIcs(ev) {
  const blob = new Blob([buildIcs(ev)], { type: 'text/calendar;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = (String(ev.title).normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').replace(/[^\w]+/g, '-').replace(/^-|-$/g, '').toLowerCase() || 'su-kien') + '.ics';
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

/* "Google Calendar": a link to Google's own event template, opened in a new tab; the page sends nothing.
   Same rules as the .ics file: a date-only event stays all-day (Google's end date is the day after the
   last day), and an exact start with no known end is sent with end = start, so no duration is invented. */
export function gcalURL(ev) {
  if (!canCalendar(ev)) return null;
  const dates = ev.startAt
    ? `${utc(ev.startAt)}/${utc(ev.endAt || ev.startAt)}`
    : `${ymd(ev.startDate)}/${ymd(nextDay(ev.endDate || ev.startDate))}`;
  const p = new URLSearchParams({ action: 'TEMPLATE', text: String(ev.title || ''), dates });
  if (ev.timezone) p.set('ctz', ev.timezone);
  const details = [ev.note, ev.url].filter(Boolean).join('\n');
  if (details) p.set('details', details);
  if (ev.location) p.set('location', String(ev.location));
  return `https://calendar.google.com/calendar/render?${p.toString()}`;
}

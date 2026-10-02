/* "Thêm vào lịch": an .ics file built in the browser, nothing sent anywhere.
   Date-only events stay all-day events (no invented midnight or timezone); an exact start
   without a known end gets no DTEND rather than an invented duration. */

const esc = s => String(s ?? '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
const ymd = s => s.replaceAll('-', '');
const utc = iso => new Date(iso).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
function nextDay(s) {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
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

/* ev: {uid, title, url, location, startDate, endDate, startAt, endAt, note} */
export function canCalendar(ev) {
  return !!ev && (/^\d{4}-\d{2}-\d{2}$/.test(ev.startDate || '') || (!!ev.startAt && !Number.isNaN(Date.parse(ev.startAt))));
}

export function buildIcs(ev) {
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ai-radar//vi', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'BEGIN:VEVENT',
    `UID:${esc(ev.uid)}@ai-radar`, `DTSTAMP:${utc(new Date().toISOString())}`];
  if (ev.startAt) {
    lines.push(`DTSTART:${utc(ev.startAt)}`);
    if (ev.endAt) lines.push(`DTEND:${utc(ev.endAt)}`);
  } else {
    lines.push(`DTSTART;VALUE=DATE:${ymd(ev.startDate)}`, `DTEND;VALUE=DATE:${ymd(nextDay(ev.endDate || ev.startDate))}`);
  }
  lines.push(`SUMMARY:${esc(ev.title)}`);
  if (ev.location) lines.push(`LOCATION:${esc(ev.location)}`);
  if (ev.url) lines.push(`URL:${esc(ev.url)}`);
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

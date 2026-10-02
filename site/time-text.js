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
export const hhmm = d => new Intl.DateTimeFormat('vi-VN', {hour:'2-digit', minute:'2-digit', timeZone:TZ}).format(d);
export const dayKey = d => new Intl.DateTimeFormat('en-CA', {timeZone:TZ}).format(d);

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
  return new Intl.DateTimeFormat('vi-VN', {day:'numeric', month:'numeric', year:'numeric', timeZone:TZ}).format(d);
}

/* Days until an event, as a row reads it: "còn N ngày" ahead, "hôm nay" on the day, "đang diễn ra" once started. */
export function daysLeftHTML(n){
  if (!Number.isFinite(n)) return '';
  return n > 0 ? `còn <span class="num">${n}</span> ngày` : n === 0 ? 'hôm nay' : 'đang diễn ra';
}

/* "Scheduled for 10/5/26, 9:00 PM" keeps YouTube's own date and clock and says the timezone is unknown. */
export function scheduleText(text){
  const m = /^Scheduled for\s+(.+)$/i.exec(text || '');
  return m ? `Dự kiến: ${m[1].replace(/\bAM\b/gi, 'sáng').replace(/\bPM\b/gi, 'chiều')} (chưa rõ múi giờ)` : 'chưa rõ giờ';
}

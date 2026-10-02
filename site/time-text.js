/* YouTube fallback times, shown as printed and never turned into instants.
   Pure functions (no DOM) so tests/test_app_streams.py can run them under Node. */

/* "Streamed 1d ago" -> "Đã phát 1 ngày trước". Anything else (or an unsafe number) -> null. */
export function streamedAge(text){
  const m = /^Streamed (\d+)\s*(second|minute|hour|day|s|m|h|d)s? ago$/i.exec(text || '');
  if (!m || !Number.isSafeInteger(Number(m[1]))) return null;
  const unit = {s:'giây', m:'phút', h:'giờ', d:'ngày'}[m[2][0].toLowerCase()];
  return `Đã phát ${m[1]} ${unit} trước`;
}

/* "Scheduled for 10/5/26, 9:00 PM" keeps YouTube's own date and clock and says the timezone is unknown. */
export function scheduleText(text){
  const m = /^Scheduled for\s+(.+)$/i.exec(text || '');
  return m ? `Dự kiến: ${m[1].replace(/\bAM\b/gi, 'sáng').replace(/\bPM\b/gi, 'chiều')} (chưa rõ múi giờ)` : 'chưa rõ giờ';
}

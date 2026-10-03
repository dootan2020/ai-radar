/* Is the snapshot the reader is looking at still fresh? The pipeline runs every 30 minutes (update.yml), and
   GitHub has been seen to delay a scheduled run by up to about six hours. Past STALE_AFTER_H the page says so,
   in words, with the build time; a mass source outage at build time is said the same way.
   Pure (no DOM) so tests/test_freshness.py can run it under Node. */
import { TZ, hhmm, ago } from './time-text.js';

export const STALE_AFTER_H = 3;          // six missed runs: no longer a normal delay, the reader should know
export const OUTAGE_SHARE = 0.2;         // more than one source in five failing (paused sources excluded)

/* sources: the snapshot's sources[]; a source the pipeline paused on purpose (disabled) is not an outage. */
export function freshness(generatedAt, sources, nowMs = Date.now()){
  const t = Date.parse(generatedAt || '');
  const ageH = Number.isFinite(t) ? (nowMs - t) / 36e5 : null;
  const active = (Array.isArray(sources) ? sources : []).filter(s => s && !s.disabled);
  const failed = active.filter(s => !s.ok).length;
  return {
    ageH,
    old: ageH != null && ageH >= STALE_AFTER_H,
    unknown: ageH == null,
    failed, active: active.length,
    outage: active.length > 0 && failed / active.length > OUTAGE_SHARE,
  };
}

/* The sentence under the bar, or '' when the snapshot is fresh and its sources answered. */
export function freshnessText(f, generatedAt, nowMs = Date.now()){
  const parts = [];
  if (f.unknown) parts.push('Bản tin này không ghi giờ tạo, nên chưa biết số liệu mới hay cũ.');
  else if (f.old) {
    const d = new Date(generatedAt);
    const day = new Intl.DateTimeFormat('vi-VN', {day:'numeric', month:'numeric', timeZone:TZ}).format(d);
    parts.push(`Bản tin chưa cập nhật từ ${hhmm(d)} ngày ${day} (${ago(generatedAt, nowMs)}). Trang thường cập nhật mỗi 30 phút, nên số liệu dưới đây có thể đã cũ.`);
  }
  if (f.outage) parts.push(`Lúc tạo bản tin, ${f.failed} trên ${f.active} nguồn không đọc được, nên có thể thiếu tin.`);
  return parts.join(' ');
}

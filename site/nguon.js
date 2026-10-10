/* ai·radar · trang nguồn của bản tin (nguon.html).
   Hiển thị tình trạng mọi nguồn tin, độ tươi dữ liệu và lớp đọc trực tiếp. */

import { esc, fmt, avatar, faceOfSource, watchImageErrors } from './faces.js';
import { hhmm, TZ } from './time-text.js';

const $ = s => document.querySelector(s);
const asArray = v => Array.isArray(v) ? v : [];
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';

const qp = new URLSearchParams(location.search).get('data');
const customData = !!qp && /^data\/[\w.-]+\.json$/.test(qp);
const DATA_URL = customData ? qp : 'data/radar-ui.json';
const SOURCES = customData ? [qp] : [DATA_URL, 'data/radar.json'];

const DATE_VN = new Intl.DateTimeFormat('vi-VN', { day: 'numeric', month: 'numeric', year: 'numeric', timeZone: TZ });
const EXACT = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'full', timeStyle: 'short', timeZone: TZ });

function updatedAt(iso) {
  const d = new Date(iso);
  return `${hhmm(d)} ngày ${DATE_VN.format(d)}`;
}
function exact(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso || '') : EXACT.format(d);
}

let D = null;
let SRC = new Map();
let storageOk = true;
try {
  localStorage.setItem('air2:probe', '1');
  localStorage.removeItem('air2:probe');
} catch (e) { storageOk = false; }

async function loadData() {
  for (const src of SOURCES) {
    try {
      const res = await fetch(src);
      if (res.ok) {
        D = await res.json();
        break;
      }
    } catch {}
  }
  if (!D) throw new Error('Không tải được dữ liệu nguồn');
  SRC = new Map(asArray(D.sources).map(s => [s.id, s]));
}

let liveState = null;
function liveRows() {
  if (!liveState) return '<li class="src-wait">Lớp trực tiếp đang đọc lần đầu</li>';
  return [...liveState.values()].map(s => `<li><span class="dot ${s.ok === true ? 'ok' : s.ok === false ? 'warn' : ''}" aria-hidden="true"></span><a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(s.label)}</a>
    <span class="src-n">${s.at ? `${s.ok ? `${s.matched} tin khớp · ` : ''}${hhmm(s.at)}` : 'đang đọc'}</span>${s.error ? `<span class="src-err">${esc(s.error)}. Đang giữ số trong bản tin.</span>` : ''}</li>`).join('');
}

function translationNote() {
  const t = D.translation;
  if (!t || typeof t !== 'object') return 'Tiêu đề giữ nguyên tiếng Anh như bài gốc.';
  const done = Number.isFinite(t.translated) && t.translated > 0;
  const base = done ? 'Tiêu đề tiếng Việt là bản dịch máy bằng mô hình NLLB-200 (giấy phép CC-BY-NC 4.0, chỉ dùng phi thương mại); tiêu đề gốc nằm ngay dưới, kèm nhãn “Translated”.' : 'Tiêu đề giữ nguyên tiếng Anh như bài gốc.';
  const left = Number.isFinite(t.pending) && t.pending > 0 ? ` Còn ${fmt(t.pending)} tiêu đề chưa dịch kịp, đang hiện bản gốc.` : '';
  return `${base}${t.error_vi ? ` ${esc(t.error_vi)}` : left}`;
}

function footHTML() {
  const r = D.ranking;
  const rank = r ? `Xếp hạng nóng: ${esc(r.description || 'xếp theo số đo của từng nguồn')}, cửa sổ ${esc(r.window_hours)} giờ${r.description && r.calibration ? `, hiệu chỉnh: ${esc(r.calibration)}` : ''}. Đây là cách xếp theo số đo, không phải phán xét tầm quan trọng.` : 'Bản dữ liệu này không mô tả cách xếp hạng nóng.';
  const scoring = ' Điểm đáng đọc được tính tự động từ 4 tín hiệu số đo (độ chú ý, độ lan rộng nhiều nguồn, độ mới và công bố gốc), không có điểm gõ tay.';
  const views = D.views && Number.isFinite(D.views.total) ? ` Lượt xem trên ai-radar: <span class="num">${fmt(D.views.total)}</span>, đo lúc ${esc(exact(D.views.measured_at))}, không dùng cookie.` : '';
  const local = storageOk ? 'Mốc đã xem, tin đã đọc, tin đã lưu và lựa chọn của bạn chỉ lưu trên máy này.'
    : 'Trình duyệt đang chặn bộ nhớ cục bộ, nên mốc đã xem, tin đã lưu và lựa chọn của bạn chỉ giữ tới khi đóng trang.';
  return `Dữ liệu tạo lúc ${esc(exact(D.generated_at))} giờ Việt Nam. ${rank}${scoring} ${translationNote()}${views} ${local}`;
}

function renderSources() {
  const srcs = asArray(D.sources), bad = srcs.filter(s => !s.ok);
  const srcCount = srcs.length;
  $('#src-update').innerHTML = `Cập nhật lúc <time datetime="${esc(D.generated_at)}">${esc(updatedAt(D.generated_at))}</time> · <span class="num">${srcCount}</span> nguồn`;
  $('#src-note').innerHTML = `<span class="num">${srcs.length - bad.length}/${srcs.length}</span> nguồn chạy được lúc ${esc(hhmm(new Date(D.generated_at)))}. Mỗi nguồn kèm số tin lấy được.`;
  $('#src-list').innerHTML = [...srcs].sort((a, b) => a.ok - b.ok || (b.count || 0) - (a.count || 0)).map(s => `<li${s.ok ? '' : ' class="is-bad"'}>${avatar(faceOfSource({ source: s.id, lab: s.lab, publisher: s.publisher }, SRC), 'xs')}<a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(s.name || s.id)}</a>
    <span class="src-n num">${s.ok ? `${s.count ?? 0} tin` : 'lỗi'}</span>${s.error ? `<span class="src-err">${esc(s.error_vi || 'Không đọc được nguồn này')}</span>` : ''}</li>`).join('');
  $('#src-live').innerHTML = liveRows();
  $('#src-foot').innerHTML = footHTML();
}

async function startLiveLayer() {
  try {
    const { startLive } = await import('./live.js');
    startLive({
      getStories: () => asArray(D.stories),
      priority: hnId => {
        const st = asArray(D.stories).find(s => (s.coverage || []).some(c => (c.discussion_url || '').endsWith('=' + hnId)));
        return st ? (st.hot_score || 0) : 0;
      },
      onUpdates: () => {},
      onStatus: st => {
        liveState = st;
        const el = $('#src-live');
        if (el) el.innerHTML = liveRows();
      },
    });
  } catch (e) {
    console.warn('lớp đọc trực tiếp chưa sẵn sàng', e);
  }
}

function initTheme() {
  const btn = $('#theme-btn');
  if (!btn) return;
  const getTheme = () => {
    try {
      const saved = JSON.parse(localStorage.getItem('air2:theme'));
      if (saved === 'light' || saved === 'dark') return saved;
    } catch {}
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  };
  const setTheme = t => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem('air2:theme', JSON.stringify(t)); } catch {}
    btn.setAttribute('aria-pressed', String(t === 'dark'));
  };
  btn.setAttribute('aria-pressed', String(getTheme() === 'dark'));
  btn.addEventListener('click', () => {
    const current = document.documentElement.dataset.theme || getTheme();
    setTheme(current === 'dark' ? 'light' : 'dark');
  });
}

function initKeys() {
  const d = $('#keys');
  if (!d) return;
  $('#keys-open')?.addEventListener('click', () => d.showModal());
  $('#keys-x')?.addEventListener('click', () => d.close());
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea')) return;
    if (e.key === '?') { e.preventDefault(); d.showModal(); }
    else if (e.key === '/') { e.preventDefault(); location.href = 'tra-cuu.html'; }
  });
}

async function init() {
  initTheme();
  initKeys();
  watchImageErrors();
  try {
    await loadData();
    renderSources();
    startLiveLayer();
  } catch (err) {
    $('#src-update').textContent = 'Không thể tải thông tin nguồn tin.';
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

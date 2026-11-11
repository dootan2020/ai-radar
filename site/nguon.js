/* Halcyon · trang nguồn tin (nguon.html).
   Trang cho người đọc (anh Tuấn, 08/11: "Làm sạch trang"): tên những nơi Halcyon đọc tin, xếp theo bảng chữ cái, mỗi
   tên dẫn về trang của nguồn. Không số tin, không trạng thái chạy hay lỗi, không lời giải thích cách hệ thống làm việc. */

import { esc, avatar, faceOfSource, watchImageErrors } from './faces.js';

const $ = s => document.querySelector(s);
const asArray = v => Array.isArray(v) ? v : [];
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';

const qp = new URLSearchParams(location.search).get('data');
const customData = !!qp && /^data\/[\w.-]+\.json$/.test(qp);
const DATA_URL = customData ? qp : 'data/radar-ui.json';
const SOURCES = customData ? [qp] : [DATA_URL, 'data/radar.json'];

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
  if (!D) throw new Error('Không tải được danh sách nguồn');
  SRC = new Map(asArray(D.sources).map(s => [s.id, s]));
}

const nameOf = s => s.name || s.id;

function sourceItemHTML(s) {
  const name = nameOf(s);
  return `<li>${avatar(faceOfSource({ source: s.id, lab: s.lab, publisher: s.publisher }, SRC), 'xs')}<a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(name)}</a></li>`;
}

/* Two quiet lines a reader may want: the machine-translation credit and where their marks are kept.
   The credit names Meta and links the licence and model card, as CC-BY-NC 4.0 asks of shared, modified output. */
const NLLB_LICENSE = 'https://creativecommons.org/licenses/by-nc/4.0/';
const NLLB_CARD = 'https://huggingface.co/facebook/nllb-200-distilled-600M';
function footHTML() {
  const t = D.translation;
  const translated = t && typeof t === 'object' && Number.isFinite(t.translated) && t.translated > 0;
  const mt = translated ? 'Tiêu đề tiếng Việt là bản dịch máy, đã được Halcyon chỉnh sửa, bằng mô hình '
    + `<a href="${NLLB_CARD}" target="_blank" rel="noopener">NLLB-200 của Meta</a> (giấy phép `
    + `<a href="${NLLB_LICENSE}" target="_blank" rel="noopener">CC-BY-NC 4.0</a>, chỉ dùng phi thương mại), kèm nhãn “Translated”. ` : '';
  const local = storageOk ? 'Tin đã đọc, tin đã lưu và lựa chọn của bạn chỉ lưu trên máy này.'
    : 'Trình duyệt đang chặn bộ nhớ cục bộ, nên tin đã lưu và lựa chọn của bạn chỉ giữ tới khi đóng trang.';
  return mt + local;
}

function renderSources() {
  const seen = new Set();
  const srcs = asArray(D.sources)
    .filter(s => s && s.id && !seen.has(nameOf(s)) && seen.add(nameOf(s)))
    .sort((a, b) => nameOf(a).localeCompare(nameOf(b), 'vi'));
  const listEl = $('#src-list');
  listEl.innerHTML = srcs.map(sourceItemHTML).join('');
  listEl.removeAttribute('aria-busy');
  $('#src-foot').innerHTML = footHTML();
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
    else if (e.key === '/') { e.preventDefault(); location.href = 'index.html#tim'; }
  });
}

async function init() {
  initTheme();
  initKeys();
  watchImageErrors();
  try {
    await loadData();
    renderSources();
  } catch (err) {
    $('#src-list').removeAttribute('aria-busy');
    $('#src-update').textContent = 'Chưa tải được danh sách nguồn. Bạn thử tải lại trang nhé.';
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

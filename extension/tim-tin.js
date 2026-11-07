/* Halcyon · the inline news search in the news bar (captain, 07/11 13:15: "chuyển nút tìm kiếm tin vào ngay tại navbar
   mà không làm trang riêng nữa. bỏ trang tìm kiếm riêng."). Results appear as the reader types, without accents
   ("anthropic", "dinh gia" find "Anthropic", "định giá"), grouped by the day the story ran so yesterday's story is found by
   its day. The index is data/radar-search.json (radar/search_index.py), loaded on the first focus; when it cannot be
   loaded (offline new tab), the stories already on the page are searched instead.
   Pure helpers (fold, matchRows, highlight) are exported for tests/test_tim_tin.py. */
import { esc } from './faces.js';
import { dayKey, hhmm } from './time-text.js';
import { headlineShown } from './editorial-headline.js';

const SEARCH_URL = 'https://radar-ai-vn.pages.dev/data/radar-search.json';
const MAX_SHOWN = 30;
const WEEKDAY = ['Chủ nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];

/* The same folding as radar/search_index.normalize_vietnamese: đ -> d, accents dropped, lower case, punctuation as space. */
export function fold(text) {
  return String(text || '').replace(/đ/g, 'd').replace(/Đ/g, 'd').normalize('NFD').replace(/\p{Mn}/gu, '')
    .normalize('NFC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').replace(/\s+/g, ' ').trim();
}
const terms = q => fold(q).split(' ').filter(Boolean);

/* Folded text with a map from each folded character back to its place in the original, for highlighting. */
function folded(text) {
  const map = []; let out = '';
  for (let i = 0; i < text.length; i++) {
    const f = String(text[i]).replace(/đ/g, 'd').replace(/Đ/g, 'd').normalize('NFD').replace(/\p{Mn}/gu, '').toLowerCase();
    for (const c of f) { out += c; map.push(i); }
  }
  return { out, map };
}
export function highlight(text, words) {
  const f = folded(String(text || '')), marks = new Array(String(text || '').length).fill(false);
  for (const t of words) {
    let i = f.out.indexOf(t);
    while (i !== -1) { for (let k = i; k < i + t.length; k++) marks[f.map[k]] = true; i = f.out.indexOf(t, i + t.length); }
  }
  let html = '', open = false;
  for (let i = 0; i < marks.length; i++) {
    if (marks[i] && !open) { html += '<mark>'; open = true; }
    if (!marks[i] && open) { html += '</mark>'; open = false; }
    html += esc(text[i]);
  }
  return html + (open ? '</mark>' : '');
}

/* A row as shown: the reader's headline and every word a reader may type for it. */
export function toRow(item, publisherName = p => p) {
  const head = headlineShown(item);
  const pubs = (Array.isArray(item.publishers) ? item.publishers : []).map(publisherName).filter(Boolean);
  const text = fold([item.search_text || '', head, item.title, item.title_vi, item.editorial_headline_vi, pubs.join(' ')].join(' '));
  // A headline taken from a Vietnamese field is a machine translation unless the desk wrote it; the row says so.
  const translated = !!head && head !== item.title && head !== item.headline && head !== item.editorial_headline_vi;
  return { id: item.id, url: item.url, at: item.published_at, head, headFold: fold(head), pubs, text, translated };
}

/* Every row holding every word; rows whose headline holds every word come first, newest first within each group. */
export function matchRows(rows, query) {
  const words = terms(query);
  if (!words.length) return null;
  const hits = rows.filter(r => words.every(w => r.text.includes(w)));
  const strong = hits.filter(r => words.every(w => r.headFold.includes(w)));
  const weak = hits.filter(r => !strong.includes(r));
  const newest = (a, b) => String(b.at || '').localeCompare(String(a.at || ''));
  return { words, strong: strong.sort(newest), weak: weak.sort(newest), total: hits.length };
}

function dayLabel(iso, now = new Date()) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'Không rõ ngày';
  const days = Math.round((new Date(dayKey(now)) - new Date(dayKey(d))) / 864e5);
  if (days === 0) return 'Hôm nay';
  if (days === 1) return 'Hôm qua';
  const [, m, dd] = dayKey(d).split('-').map(Number);
  return `${WEEKDAY[new Date(dayKey(d) + 'T00:00:00Z').getUTCDay()]} ${dd}/${m}`;
}

/* One result: the headline with the typed words marked, the publishers and the time (with the day when the group does
   not already say it). */
export function resultRow(r, withDay, words) {
  const mark = r.translated ? '<span class="mt" aria-hidden="true" title="Bản dịch máy">Translated</span><span class="sr" lang="vi">Bản dịch máy. </span>' : '';
  return `<li role="none"><a class="ns-row" role="option" href="${esc(/^https?:\/\//.test(r.url || '') ? r.url : '#')}" data-ns-id="${esc(r.id)}" target="_blank" rel="noopener">
    <span class="ns-h">${highlight(r.head, words)}</span>
    <span class="ns-meta">${esc(r.pubs.slice(0, 2).join(', '))}${r.pubs.length ? ' · ' : ''}${withDay ? `${esc(dayLabel(r.at))}, ` : ''}${r.at ? esc(hhmm(new Date(r.at))) : ''}${mark}</span></a></li>`;
}

export function createNewsSearch({ root, getStories = () => [], onOpenStory = () => false, searchUrl = SEARCH_URL }) {
  const input = root.querySelector('#ns-q');
  const results = root.querySelector('#ns-results');
  const openBtn = root.querySelector('#ns-open');
  const clearBtn = root.querySelector('#ns-clear');
  const status = document.getElementById('ns-status');
  let rows = null, loading = null, scope = '', activeIdx = -1;

  async function load() {
    if (rows) return rows;
    if (!loading) {
      loading = (async () => {
        try {
          const r = await fetch(searchUrl, { signal: AbortSignal.timeout(10000) });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const j = await r.json();
          if (!Array.isArray(j.stories)) throw new Error('chỉ mục không có tin');
          const names = new Map();
          for (const s of Array.isArray(j.sources) ? j.sources : []) if (s && s.publisher && !names.has(s.publisher)) names.set(s.publisher, s.name);
          rows = j.stories.filter(s => s && s.id).map(s => toRow(s, p => names.get(p) || p));
          scope = 'tin gần đây';
        } catch (e) {
          // Offline or blocked: search what the page already holds rather than show nothing.
          console.warn('search index unavailable; searching the stories on the page', e);
          rows = getStories().map(st => toRow({ ...st, publishers: (st.coverage || []).map(c => c && c.publisher).filter(Boolean) }));
          scope = 'tin trên trang';
        }
        return rows;
      })();
    }
    return loading;
  }

  const row = resultRow;

  function paint() {
    const q = input.value.trim();
    root.classList.toggle('has-q', !!input.value);
    const m = rows ? matchRows(rows, q) : null;
    if (!m) { hide(); status.textContent = ''; return; }
    let html = `<div class="ns-head"><span>${m.total ? `<b class="num">${m.total}</b> tin khớp “${esc(q)}”` : 'Không có tin khớp'}</span><span>trong <span class="num">${rows.length}</span> ${esc(scope)}</span></div>`;
    if (!m.total) {
      html += `<p class="ns-empty">Không thấy tin nào có <b>“${esc(q)}”</b>. Thử một từ ngắn hơn, tên công ty hoặc tên mô hình.</p>`;
    } else {
      const strong = m.strong.slice(0, MAX_SHOWN), weak = m.weak.slice(0, Math.max(0, MAX_SHOWN - strong.length));
      const days = new Map();
      for (const r of strong) { const d = dayLabel(r.at); if (!days.has(d)) days.set(d, []); days.get(d).push(r); }
      for (const [day, list] of days) {
        html += `<p class="ns-day">${esc(day)}</p><ul class="ns-list" role="listbox" aria-label="${esc(day)}">${list.map(r => row(r, false, m.words)).join('')}</ul>`;
      }
      if (weak.length) {
        const label = 'Khớp ở tiêu đề gốc hoặc nguồn';
        html += `<p class="ns-day">${label}</p><ul class="ns-list" role="listbox" aria-label="${label}">${weak.map(r => row(r, true, m.words)).join('')}</ul>`;
      }
    }
    results.innerHTML = html;
    results.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    activeIdx = -1;
    status.textContent = m.total ? `${m.total} tin khớp` : 'Không có tin khớp';
  }
  async function update() {
    if (!rows) { await load(); }
    paint();
  }
  function hide() { results.hidden = true; input.setAttribute('aria-expanded', 'false'); }
  function clear() { input.value = ''; root.classList.remove('has-q'); hide(); status.textContent = ''; }
  /* Closing the search never drops keyboard focus on the page body: it goes back to the button that opened the search
     when that button is on screen (phones, narrow bars), and otherwise stays in the field, which remains visible. */
  function collapse() {
    root.classList.remove('open');
    openBtn.setAttribute('aria-expanded', 'false');
    if (openBtn.getClientRects().length) openBtn.focus();
    else input.focus();
  }
  function open(query = null) {
    root.classList.add('open');
    openBtn.setAttribute('aria-expanded', 'true');
    if (query != null) input.value = query;
    input.focus({ preventScroll: true });
    if (query == null) input.select();
    load();
    if (input.value.trim()) update();
  }

  input.addEventListener('focus', () => { load(); if (input.value.trim()) update(); }, { passive: true });
  input.addEventListener('input', update);
  openBtn.addEventListener('click', () => open());
  clearBtn.addEventListener('click', () => {
    if (input.value) { clear(); input.focus(); }
    else { clear(); collapse(); }
  });
  root.addEventListener('keydown', e => {
    const opts = [...results.querySelectorAll('.ns-row')];
    if (e.key === 'Escape') {
      e.stopPropagation();
      if (!results.hidden) { e.preventDefault(); hide(); input.focus(); }
      else if (input.value) { e.preventDefault(); clear(); }
      else collapse();
      return;
    }
    if (results.hidden || !opts.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = e.key === 'ArrowDown' ? Math.min(opts.length - 1, activeIdx + 1) : activeIdx - 1;
      if (activeIdx < 0) { activeIdx = -1; input.focus(); } else opts[activeIdx].focus();
    } else if (e.key === 'Enter' && document.activeElement === input) {
      e.preventDefault();
      opts[0].click();
    }
  });
  results.addEventListener('click', e => {
    const a = e.target.closest('.ns-row');
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    // A story still in the snapshot opens in the page's story view; anything older opens its original article.
    if (onOpenStory(a.dataset.nsId, a)) { e.preventDefault(); hide(); }
  });
  document.addEventListener('pointerdown', e => {
    if (!root.contains(e.target) && !results.hidden && !document.querySelector('dialog[open]')) hide();
  });
  return { open, hide, load };
}

/* ai·radar · Trang Tra cứu câu chuyện AI 7 ngày qua (tra-cuu.js)
   Bento Keynote: Ô chính + dòng thời gian.
   Dữ liệu tải từ data/radar-search.json khi cần.
   Không phát sinh số liệu giả, tính toán trực tiếp từ dữ liệu thực tế. */

import { esc, fmt, faceOfStory, faceOfSource, avatar, avatarStack, monogram, watchImageErrors, loadDeferredImages } from './faces.js';
import { ago, dayKey, hhmm, TZ } from './time-text.js';
import { shown, origLine } from './titles.js';
import { KIND } from './words.js';

// Các từ dừng dùng khi so khớp tựa đề để gom nhóm câu chuyện
const STOPWORDS = new Set([
  'a', 'an', 'the', 'and', 'or', 'for', 'to', 'of', 'in', 'on', 'with', 'from', 'by', 'as', 'at',
  'is', 'are', 'was', 'were', 'be', 'been', 'this', 'that', 'it', 'its', 'cua', 'cac', 'nhung',
  'trong', 'tren', 'va', 'cho', 'la', 'co', 've', 'mot', 'nhieu', 'ngay', 'khi', 'sau', 'truoc'
]);

// Danh sách các thực thể gợi ý phổ biến có trong dữ liệu
const CANDIDATE_NAMES = [
  'DeepSeek', 'OpenAI', 'Anthropic', 'GPT-6.1', 'Google', 'Meta',
  'Nvidia', 'Apple', 'Qwen', 'Claude', 'Gemini', 'FPT', 'Llama', 'Trí tuệ nhân tạo'
];

let searchData = null;
let searchGeneratedAt = '';
let activeQuery = '';
let searchSources = [];
let SRC = new Map();
let leadId = null, leadOpen = false;

export const srcName = id => (SRC.get(id) || {}).name || id;

function buildSourceMap(sources) {
  SRC = new Map();
  (sources || []).forEach(s => {
    if (s.id) SRC.set(s.id, s);
  });
  (sources || []).forEach(s => {
    if (s.publisher && (!SRC.has(s.publisher) || s.id.endsWith('-news') || s.id === s.publisher)) {
      SRC.set(s.publisher, s);
    }
  });
}

/**
 * Kiểm tra xem một phân loại có phải là tin tức hay không (không phải model/repo)
 */
function isNewsKind(kind) {
  return kind !== 'model' && kind !== 'repository';
}

/**
 * Trả về avatar nguồn an toàn: nếu không có logo hoặc là HF thì dùng monogram theo thiết kế
 */
export function safeFaceOfStory(story, src = SRC) {
  if (!story) return { kind: 'mono', id: '?', label: '' };
  const st = story.coverage ? story : {
    ...story,
    coverage: (story.publishers || []).map(p => ({
      source: p,
      publisher: p,
      lab: (src && src.get(p) || {}).lab || ''
    }))
  };
  let f = faceOfStory(st, src);
  if (!f || f.kind === 'hf') {
    const firstPub = (story.publishers && story.publishers[0]) || '';
    const label = (src && src.get(firstPub) || {}).name || firstPub || story.url || '';
    return { kind: 'mono', id: monogram(label), label: label };
  }
  return f;
}

export function safeFaceOfSource(coverage, src = SRC) {
  let f = faceOfSource(coverage, src);
  if (!f || f.kind === 'hf') {
    const label = f ? (f.label || f.id) : (coverage && (coverage.name || coverage.publisher || coverage.source)) || '';
    return { kind: 'mono', id: monogram(label), label: label };
  }
  return f;
}

/**
 * Chuẩn hóa chuỗi tìm kiếm tiếng Việt và tiếng Anh đồng nhất với radar/search_index.py
 */
export function normalizeVietnamese(text) {
  if (!text || typeof text !== 'string') return '';
  const dClean = text.replace(/đ/g, 'd').replace(/Đ/g, 'd');
  const decomposed = dClean.normalize('NFD');
  const stripped = decomposed.replace(/[\u0300-\u036f]/g, '');
  const normalized = stripped.normalize('NFC').toLowerCase();
  const cleaned = normalized.replace(/[^a-z0-9]+/g, ' ');
  return cleaned.trim();
}

/**
 * Rút gọn liên kết URL thành dạng chuẩn để nhận diện trùng lặp
 */
function canonicalUrl(url) {
  if (!url || typeof url !== 'string') return '';
  try {
    const u = new URL(url);
    let host = u.hostname.toLowerCase();
    if (host.startsWith('www.')) host = host.slice(4);
    let path = u.pathname.replace(/\/+$/, '');
    return `${u.protocol}//${host}${path}`;
  } catch {
    return url;
  }
}

/**
 * Tách từ khóa quan trọng từ tựa đề
 */
function titleTokens(story) {
  const t1 = normalizeVietnamese(story.title || '');
  const t2 = normalizeVietnamese(story.title_vi || '');
  const raw = `${t1} ${t2}`.split(/\s+/);
  return new Set(raw.filter(w => w.length >= 3 && !STOPWORDS.has(w)));
}

function updateWhenLine() {
  const whenEl = document.getElementById('when-line');
  if (whenEl && searchGeneratedAt) {
    const g = new Date(searchGeneratedAt);
    whenEl.innerHTML = `<span class="wd">${esc(new Intl.DateTimeFormat('vi-VN',{weekday:'long',day:'numeric',month:'numeric',timeZone:TZ}).format(g).replace(/^./, c => c.toUpperCase()))} · </span>cập nhật ${hhmm(g)}`;
  }
}

/**
 * Tải chỉ mục dữ liệu tìm kiếm
 */
async function loadSearchData() {
  if (searchData) return searchData;
  try {
    const res = await fetch('data/radar-search.json');
    if (!res.ok) throw new Error('Không thể tải chỉ mục');
    const json = await res.json();
    searchData = json.stories || [];
    searchGeneratedAt = json.generated_at || '';
    searchSources = json.sources || [];
    buildSourceMap(searchSources);
    updateWhenLine();
    return searchData;
  } catch (err) {
    console.error('Lỗi tải dữ liệu tra cứu:', err);
    throw err;
  }
}

/**
 * Gom nhóm các dòng kết quả thành từng câu chuyện
 */
export function groupStories(matchedRows, queryWords, refDateIso = searchGeneratedAt) {
  const clusters = [];
  const qWordSet = new Set(queryWords);
  const refMs = refDateIso ? new Date(refDateIso).getTime() : Date.now();
  const limit7dMs = refMs - 7 * 864e5;

  for (const s of matchedRows) {
    const toks = titleTokens(s);
    const u = canonicalUrl(s.url);
    let assigned = false;

    for (const c of clusters) {
      // 1. Trùng URL chuẩn
      if (u && c.urls.has(u)) {
        c.rows.push(s);
        (s.publishers || []).forEach(p => c.publishers.add(p));
        if (s.published_at) c.dates.push(s.published_at);
        assigned = true;
        break;
      }

      // 2. Độ tương đồng từ khóa tựa đề (loại trừ từ khóa tìm kiếm)
      const specToks = new Set([...toks].filter(t => !qWordSet.has(t)));
      const cSpecToks = new Set([...c.tokens].filter(t => !qWordSet.has(t)));

      if (specToks.size > 0 && cSpecToks.size > 0) {
        let overlap = 0;
        for (const t of specToks) {
          if (cSpecToks.has(t)) overlap++;
        }
        const union = new Set([...specToks, ...cSpecToks]).size;
        const jaccard = union > 0 ? overlap / union : 0;
        const minLen = Math.min(specToks.size, cSpecToks.size);
        const containment = minLen > 0 ? overlap / minLen : 0;

        if (jaccard >= 0.35 || (containment >= 0.6 && overlap >= 3)) {
          c.rows.push(s);
          (s.publishers || []).forEach(p => c.publishers.add(p));
          if (s.published_at) c.dates.push(s.published_at);
          toks.forEach(t => c.tokens.add(t));
          if (u) c.urls.add(u);
          assigned = true;
          break;
        }
      }
    }

    if (!assigned) {
      const dates = s.published_at ? [s.published_at] : [];
      clusters.push({
        primary: s,
        rows: [s],
        publishers: new Set(s.publishers || []),
        dates: dates,
        tokens: toks,
        urls: new Set(u ? [u] : [])
      });
    }
  }

  // Tính số lượng nguồn và khoảng ngày cho mỗi câu chuyện
  for (const c of clusters) {
    c.sourceCount = c.publishers.size;
    // Chọn dòng chính: ưu tiên dòng tin tức trước, tựa đề tiếng Việt, sau đó ngày mới nhất
    c.rows.sort((a, b) => {
      const aNews = isNewsKind(a.kind) ? 1 : 0;
      const bNews = isNewsKind(b.kind) ? 1 : 0;
      if (aNews !== bNews) return bNews - aNews;

      const aHasVi = Boolean(a.title_vi && a.title_vi.trim());
      const bHasVi = Boolean(b.title_vi && b.title_vi.trim());
      if (aHasVi !== bHasVi) return bHasVi ? 1 : -1;

      return (b.published_at || '').localeCompare(a.published_at || '');
    });
    c.primary = c.rows[0];
    c.isNews = isNewsKind(c.primary.kind);

    // Tính số ngày đưa tin thực tế và thời gian mới nhất
    if (c.dates.length > 0) {
      const dayKeys = new Set(c.dates.map(d => dayKey(new Date(d))));
      c.daySpan = dayKeys.size;
      c.latestDate = c.dates.slice().sort().reverse()[0];
      c.latestMs = new Date(c.latestDate).getTime();
      c.isWithin7Days = c.latestMs >= limit7dMs;
    } else {
      c.daySpan = 0;
      c.latestDate = '';
      c.latestMs = 0;
      c.isWithin7Days = false;
    }
  }

  // Sắp xếp: Chuyện trong 7 ngày qua xếp trước; số nguồn nhiều nhất quyết định trước;
  // nếu bằng nguồn thì ưu tiên tin tức hơn mô hình/kho mã (giải quyết hòa nguồn); sau đó đến ngày
  clusters.sort((a, b) => {
    // 1. Chuyện trong 7 ngày qua luôn xếp trước chuyện cũ hơn
    if (a.isWithin7Days !== b.isWithin7Days) return b.isWithin7Days ? 1 : -1;
    // 2. Số nguồn kiểm chứng độc nhất quyết định trước ("chuyện nhiều nguồn nhất")
    if (b.sourceCount !== a.sourceCount) return b.sourceCount - a.sourceCount;
    // 3. Phân biệt tin tức với danh sách mô hình/kho mã để giải quyết hòa nguồn (tiebreak)
    if (a.isNews !== b.isNews) return b.isNews ? 1 : -1;
    // 4. Số ngày đưa tin
    if (b.daySpan !== a.daySpan) return b.daySpan - a.daySpan;
    // 5. Nếu là tin tức, số bài viết nhiều hơn
    if (a.isNews && b.rows.length !== a.rows.length) return b.rows.length - a.rows.length;
    // 6. Ngày xuất bản mới nhất
    return (b.latestDate || '').localeCompare(a.latestDate || '');
  });

  return clusters;
}

/**
 * Trích xuất danh sách gợi ý hợp lệ từ dữ liệu thực tế
 */
export function deriveSuggestedNames(stories) {
  if (!stories || stories.length === 0) return [];
  const results = [];
  for (const name of CANDIDATE_NAMES) {
    const norm = normalizeVietnamese(name);
    const words = norm.split(/\s+/);
    let count = 0;
    for (const s of stories) {
      const st = s.search_text || '';
      if (words.every(w => st.includes(w))) {
        count++;
      }
    }
    if (count > 0) {
      results.push({ name, count });
    }
  }
  // Sắp xếp theo số lượng câu chuyện giảm dần
  results.sort((a, b) => b.count - a.count);
  return results.slice(0, 8).map(r => r.name);
}

/**
 * Lịch sử tìm kiếm lưu trong máy người đọc
 */
const HISTORY_KEY = 'air2:search-history';
function getSearchHistory() {
  try {
    const saved = localStorage.getItem(HISTORY_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

function saveSearchHistory(query) {
  if (!query || !query.trim()) return;
  const q = query.trim();
  try {
    let hist = getSearchHistory().filter(item => item.toLowerCase() !== q.toLowerCase());
    hist.unshift(q);
    if (hist.length > 6) hist = hist.slice(0, 6);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(hist));
  } catch {
    // Trình duyệt chặn bộ nhớ cục bộ
  }
}

/**
 * Định dạng ngày theo lịch tiếng Việt
 */
function formatDayHeading(isoString, referenceIso = searchGeneratedAt) {
  if (!isoString) return 'Chưa rõ ngày xuất bản';
  const d = new Date(isoString);
  const ref = referenceIso ? new Date(referenceIso) : new Date();
  const dayK = dayKey(d);
  const todayK = dayKey(ref);

  const yesterday = new Date(ref.getTime() - 864e5);
  const yesterdayK = dayKey(yesterday);

  const weekdayFmt = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, weekday: 'long' }).format(d);
  const day = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, day: 'numeric' }).format(d);
  const month = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, month: 'numeric' }).format(d);
  const year = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, year: 'numeric' }).format(d);
  const refYear = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, year: 'numeric' }).format(ref);

  if (dayK === todayK) {
    return `Hôm nay, ngày ${day} tháng ${month}`;
  }
  if (dayK === yesterdayK) {
    return `Hôm qua, ngày ${day} tháng ${month}`;
  }
  if (year !== refYear) {
    return `${weekdayFmt}, ngày ${day} tháng ${month} năm ${year}`;
  }
  return `${weekdayFmt}, ngày ${day} tháng ${month}`;
}

/**
 * Hiển thị khối ô chính (Bento Lead Tile từ ngôn ngữ trang chủ)
 */
function renderHeroTile(topStory) {
  if (!topStory) return '';
  const p = topStory.primary;
  if (leadId !== p.id) {
    leadId = p.id;
    leadOpen = false;
  }
  const titleText = esc(shown(p.title, p.title_vi));
  const isTranslated = Boolean(p.title_vi && p.title && p.title_vi.trim() !== p.title.trim());

  // Avatars nguồn
  const faces = Array.from(topStory.publishers).map(pub => {
    const s = SRC.get(pub) || {};
    return safeFaceOfSource({ publisher: pub, source: pub, lab: s.lab, name: s.name || pub }, SRC);
  });
  const pubList = Array.from(topStory.publishers).map(srcName).join(', ');
  const timeLabel = ago(topStory.latestDate);
  const kindTag = KIND[p.kind] ? `<span class="kind">${esc(KIND[p.kind])}</span>` : '';

  const keynoteUnit = topStory.sourceCount > 1 ? 'nguồn cùng đưa chuyện này' : 'nguồn đưa tin';

  return `
    <article class="tile t-lead${leadOpen ? ' is-expanded' : ''}" aria-labelledby="lead-h">
      <div class="lead-top">
        ${faces.length > 1 ? avatarStack(faces, 'lg') : avatar(safeFaceOfStory(p, SRC), 'xl')}
        <p class="lead-label" id="lead-h">
          <span class="pill pill-hot"><svg class="i" aria-hidden="true"><use href="#i-flame"/></svg>Nhiều nguồn nhất trong 7 ngày</span>
          <span class="lead-src">${kindTag}${esc(pubList)}${timeLabel ? ` · ${esc(timeLabel)}` : ''}</span>
        </p>
      </div>

      <p class="keynote">
        <b class="num" data-count="${topStory.sourceCount}">${fmt(topStory.sourceCount)}</b>
        <span>${esc(keynoteUnit)}</span>
      </p>

      <h2 class="lead-title-wrap">
        <a class="lead-title" href="${esc(p.url)}" target="_blank" rel="noopener">
          ${titleText}
        </a>
      </h2>

      <div class="lead-disclosure">
        ${isTranslated ? '<span class="orig lead-attribution"><span class="mt" aria-hidden="true" title="Bản dịch máy; mở đầy đủ để xem tiêu đề gốc">Translated</span><span class="sr" lang="vi">Bản dịch máy. Tiêu đề gốc trong phần đầy đủ.</span></span>' : ''}
        <button class="btn-quiet lead-toggle" data-lead-details="lead" aria-controls="lead-details" aria-expanded="${leadOpen}">
          <span>${leadOpen ? 'Thu gọn' : 'Xem đầy đủ'}</span>
          <svg class="i" aria-hidden="true"><use href="#i-plus"/></svg>
        </button>
      </div>

      <div class="lead-details" id="lead-details">
        ${isTranslated ? `<p class="orig lead-orig">${esc(p.title)}</p>` : ''}
        ${p.summary ? `<p class="lead-sum">${esc(p.summary)}</p>` : ''}

        ${topStory.sourceCount > 1 ? `
          <ul class="cov" aria-label="Các nguồn đưa chuyện này">
            ${topStory.rows.map(r => `
              <li>
                ${avatar(safeFaceOfStory(r, SRC), 'xs')}
                <span class="pub">${esc((r.publishers || []).map(srcName).join(', '))}</span>
                <span class="faint">${r.published_at ? ago(r.published_at) : ''}</span>
                <a class="go" href="${esc(r.url)}" target="_blank" rel="noopener">Bài gốc</a>
              </li>
            `).join('')}
          </ul>
        ` : ''}

        <div class="lead-foot">
          <div class="lead-facts">
            ${topStory.daySpan > 0 ? `<p>Theo dõi qua <b class="num">${fmt(topStory.daySpan)}</b> ngày</p>` : ''}
            <div class="acts">
              <a class="btn primary" href="${esc(p.url)}" target="_blank" rel="noopener">
                Bài gốc <svg class="i" aria-hidden="true"><use href="#i-out"/></svg>
              </a>
            </div>
          </div>
        </div>
      </div>
    </article>
  `;
}

/**
 * Hiển thị một dòng câu chuyện (Bento Row từ ngôn ngữ trang chủ)
 */
function renderStoryCard(st) {
  const p = st.primary;
  const face = safeFaceOfStory(p, SRC);
  const titleText = esc(shown(p.title, p.title_vi));
  const isTranslated = Boolean(p.title_vi && p.title && p.title_vi.trim() !== p.title.trim());
  const timeStr = ago(st.latestDate || p.published_at);
  const pubsStr = Array.from(st.publishers).map(srcName).join(', ');
  const kindTag = KIND[p.kind] ? `<span class="kind">${esc(KIND[p.kind])}</span>` : '';

  return `
    <a class="row c" href="${esc(p.url)}" target="_blank" rel="noopener">
      ${avatar(face, 'sm')}
      <span class="row-m">
        <span class="t"><h4 class="tc-card-title">${titleText}</h4></span>
        ${isTranslated ? `<span class="orig">${esc(p.title)}</span>` : ''}
        <span class="k">${kindTag}<span class="pub">${esc(pubsStr)}</span>${timeStr ? ` · ${esc(timeStr)}` : ''}</span>
      </span>
      <span class="r">
        ${st.sourceCount > 1 ? `<span class="mv num">${fmt(st.sourceCount)}</span><span class="faint">nguồn</span>` : `<svg class="i" style="width:14px;height:14px;color:var(--color-ink-3)" aria-hidden="true"><use href="#i-out"/></svg>`}
      </span>
    </a>
  `;
}

/**
 * Hiển thị các nhóm ngày trong một phân đoạn dòng thời gian
 */
function renderDayGroups(stories, isOlder = false, refDateIso = searchGeneratedAt) {
  const dayGroups = new Map();
  for (const st of stories) {
    const k = dayKey(new Date(st.latestDate));
    if (!dayGroups.has(k)) {
      dayGroups.set(k, {
        dayKey: k,
        dateStr: st.latestDate,
        items: []
      });
    }
    dayGroups.get(k).items.push(st);
  }

  // Sắp xếp các ngày mới nhất trước
  const sortedDays = Array.from(dayGroups.values()).sort((a, b) => b.dayKey.localeCompare(a.dayKey));

  let html = '';
  for (const group of sortedDays) {
    const heading = formatDayHeading(group.dateStr, refDateIso);
    group.items.sort((a, b) => (b.latestDate || '').localeCompare(a.latestDate || ''));

    html += `
      <div class="tc-day-group">
        <h3 class="tc-day-title">${esc(heading)}</h3>
        <div class="tc-day-items">
          ${group.items.map(renderStoryCard).join('')}
        </div>
      </div>
    `;
  }
  return html;
}

/**
 * Hiển thị dòng thời gian các chuyện còn lại
 */
function renderTimeline(timelineStories, refDateIso = searchGeneratedAt) {
  // Sắp xếp các câu chuyện theo thời gian mới nhất trước
  const sortedStories = timelineStories.slice().sort((a, b) => {
    if (!a.latestDate && b.latestDate) return 1;
    if (a.latestDate && !b.latestDate) return -1;
    return (b.latestDate || '').localeCompare(a.latestDate || '');
  });

  const within7d = sortedStories.filter(s => s.isWithin7Days);
  const older = sortedStories.filter(s => s.latestDate && !s.isWithin7Days);
  const undated = sortedStories.filter(s => !s.latestDate);

  let html = '';

  // 1. Dòng thời gian 7 ngày qua
  html += `
    <section class="tile" aria-labelledby="tc-timeline-heading">
      <div class="tile-h">
        <h2 class="tc-section-title" id="tc-timeline-heading">Dòng thời gian 7 ngày qua</h2>
        <span class="aside"><b class="num">${fmt(within7d.length)}</b> chuyện khác</span>
      </div>
  `;

  if (within7d.length > 0) {
    html += `
      <div class="tc-timeline-container">
        ${renderDayGroups(within7d, false, refDateIso)}
      </div>
    `;
  } else {
    html += `
      <p class="empty-note">Không có câu chuyện nào khác về tên này trong 7 ngày qua.</p>
    `;
  }
  html += `</section>`;

  // 2. Khối các chuyện trước 7 ngày qua (nếu có)
  if (older.length > 0) {
    html += `
      <section class="tile" aria-labelledby="tc-older-heading">
        <div class="tile-h">
          <h2 class="tc-section-title" id="tc-older-heading">Trước 7 ngày qua</h2>
          <span class="aside"><b class="num">${fmt(older.length)}</b> chuyện cũ hơn</span>
        </div>
        <div class="tc-timeline-container">
          ${renderDayGroups(older, true, refDateIso)}
        </div>
      </section>
    `;
  }

  // 3. Khối các chuyện chưa rõ ngày xuất bản (nếu có)
  if (undated.length > 0) {
    html += `
      <section class="tile" aria-labelledby="tc-undated-heading">
        <div class="tile-h">
          <h2 class="tc-section-title" id="tc-undated-heading">Chưa rõ ngày xuất bản</h2>
          <span class="aside"><b class="num">${fmt(undated.length)}</b> chuyện</span>
        </div>
        <p class="empty-note">Các mục dưới đây không có ngày xuất bản trong dữ liệu nguồn.</p>
        <div class="tc-day-items">
          ${undated.map(renderStoryCard).join('')}
        </div>
      </section>
    `;
  }

  return html;
}

/**
 * Hiển thị trạng thái chưa tìm kiếm (rỗng) bằng ô Bento Keynote lớn
 */
function renderEmptyPrompt(suggestedNames, history) {
  const totalIndexed = searchData ? searchData.length : 0;
  return `
    <div class="board tc-results-board">
      <article class="tile t-lead" id="tc-prompt" style="padding: var(--tile-pad-hero);">
        <div class="lead-top">
          ${avatar({ kind: 'mono', id: 'AR', label: 'ai-radar' }, 'xl')}
          <p class="lead-label">
            <span class="pill pill-hot"><svg class="i" aria-hidden="true"><use href="#i-search"/></svg>Tra một chuyện</span>
            <span class="lead-src">Dữ liệu 7 ngày qua · Đo lường bằng số nguồn thật</span>
          </p>
        </div>

        <p class="keynote"><b class="num">${fmt(totalIndexed)}</b><span>câu chuyện trong 7 ngày</span></p>
        <h2 class="lead-title-wrap"><span class="lead-title">Tra cứu câu chuyện AI</span></h2>
        <p class="lead-sum">Nhập tên một mô hình, tổ chức hoặc chủ đề AI để xem câu chuyện lớn nhất trong 7 ngày qua kèm số nguồn kiểm chứng và dòng thời gian chi tiết.</p>

        <div style="margin-top: var(--space-24); border-top: 1px solid var(--color-hair); padding-top: var(--space-16);">
          <p class="sub-h" style="margin-bottom: var(--space-12);">Gợi ý tra cứu phổ biến</p>
          <div style="display: flex; flex-wrap: wrap; gap: var(--space-8);">
            ${suggestedNames.map(name => `
              <button class="btn second" type="button" data-suggest="${esc(name)}">${esc(name)}</button>
            `).join('')}
          </div>
        </div>

        ${history && history.length > 0 ? `
          <div style="margin-top: var(--space-20); border-top: 1px solid var(--color-hair); padding-top: var(--space-16);">
            <p class="sub-h" style="margin-bottom: var(--space-12);">Đã tra gần đây</p>
            <div style="display: flex; flex-wrap: wrap; gap: var(--space-8);">
              ${history.map(item => `
                <button class="btn-quiet" type="button" data-suggest="${esc(item)}" style="background: var(--color-fill);">${esc(item)}</button>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </article>
    </div>
  `;
}

/**
 * Hiển thị trạng thái không có kết quả bằng component tile rỗng từ trang chủ
 */
function renderNoResults(query, suggestedNames) {
  return `
    <div class="board tc-results-board">
      <div class="tile t-empty" role="status" style="padding: var(--tile-pad-hero); text-align: center; display: flex; flex-direction: column; align-items: center; gap: var(--space-16);">
        <svg class="i" style="width: 48px; height: 48px; stroke: var(--color-warn);" aria-hidden="true"><use href="#i-warn"/></svg>
        <h2 style="font-size: var(--text-tile); font-weight: var(--weight-bold);">Không tìm thấy câu chuyện nào</h2>
        <p class="muted" style="max-width: 50ch;">Không có câu chuyện nào về từ khóa &ldquo;${esc(query)}&rdquo; trong 7 ngày qua.</p>
        <div style="margin-top: var(--space-16);">
          <p class="sub-h" style="margin-bottom: var(--space-12);">Thử tra cứu các tên phổ biến:</p>
          <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-8);">
            ${suggestedNames.slice(0, 6).map(name => `
              <button class="btn second" type="button" data-suggest="${esc(name)}">${esc(name)}</button>
            `).join('')}
          </div>
        </div>
      </div>
    </div>
  `;
}

/**
 * Thực thi tìm kiếm và render giao diện
 */
export async function executeSearch(query) {
  const container = document.getElementById('tc-results');
  const counterEl = document.getElementById('tc-counter-row');
  if (!container) return;

  activeQuery = (query || '').trim();

  // Đồng bộ ô tìm kiếm và URL
  const inputEl = document.getElementById('tc-search-input');
  if (inputEl && inputEl.value !== activeQuery) {
    inputEl.value = activeQuery;
  }
  const clearBtn = document.getElementById('tc-clear-btn');
  if (clearBtn) {
    clearBtn.hidden = !activeQuery;
  }

  const url = new URL(window.location);
  if (activeQuery) {
    url.searchParams.set('q', activeQuery);
  } else {
    url.searchParams.delete('q');
  }
  window.history.replaceState({}, '', url);

  // Trạng thái chưa nhập từ khóa
  if (!activeQuery) {
    if (counterEl) counterEl.innerHTML = '';
    const stories = await loadSearchData();
    const suggestions = deriveSuggestedNames(stories);
    const history = getSearchHistory();
    container.innerHTML = renderEmptyPrompt(suggestions, history);
    return;
  }

  // Lưu lịch sử
  saveSearchHistory(activeQuery);

  // Hiển thị khung chờ tải
  container.innerHTML = `
    <div class="board tc-results-board tc-loading-box" role="status">
      <div class="tile t-lead sk-tile">
        <div class="sk sk-av"></div>
        <div class="sk sk-num"></div>
        <div class="sk sk-title" style="width:86%"></div>
        <div class="sk sk-title" style="width:60%"></div>
      </div>
      <p class="sr">Đang tải và đối chiếu dữ liệu...</p>
    </div>
  `;

  const stories = await loadSearchData();
  const suggestions = deriveSuggestedNames(stories);

  // Chuẩn hóa và lọc
  const normQ = normalizeVietnamese(activeQuery);
  const qWords = normQ.split(/\s+/).filter(Boolean);

  const matched = stories.filter(s => {
    const st = s.search_text || '';
    return qWords.every(w => st.includes(w));
  });

  // Nếu không có kết quả
  if (matched.length === 0) {
    if (counterEl) {
      counterEl.innerHTML = `Tìm thấy <b class="num">0</b> câu chuyện về &ldquo;${esc(activeQuery)}&rdquo; trong 7 ngày qua`;
    }
    container.innerHTML = renderNoResults(activeQuery, suggestions);
    return;
  }

  // Nhóm kết quả thành các câu chuyện
  const storyClusters = groupStories(matched, qWords);

  if (storyClusters.length === 0) {
    if (counterEl) counterEl.innerHTML = '';
    container.innerHTML = renderNoResults(activeQuery, suggestions);
    return;
  }

  // Cập nhật thanh đếm kết quả
  if (counterEl) {
    counterEl.innerHTML = `Tìm thấy <b class="num">${fmt(storyClusters.length)}</b> câu chuyện về &ldquo;${esc(activeQuery)}&rdquo; trong 7 ngày qua`;
  }

  // Tách Ô chính và Dòng thời gian
  const topStory = storyClusters[0];
  const timelineStories = storyClusters.slice(1);

  const heroHtml = renderHeroTile(topStory);
  const timelineHtml = renderTimeline(timelineStories, searchGeneratedAt);

  container.innerHTML = `
    <div class="board tc-results-board">
      ${heroHtml}
      <div class="tc-timeline-col">
        ${timelineHtml}
      </div>
    </div>
  `;

  loadDeferredImages(container);
}

/**
 * Khởi tạo trang tra cứu
 */
export function initSearchPage() {
  watchImageErrors();
  const form = document.getElementById('tc-search-form');
  const input = document.getElementById('tc-search-input');
  const clearBtn = document.getElementById('tc-clear-btn');
  const themeBtn = document.getElementById('theme');

  // Khởi tạo chủ đề sáng/tối
  if (themeBtn) {
    const isDark = () => document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);

    const updateThemeBtn = () => {
      const dark = isDark();
      themeBtn.setAttribute('aria-pressed', dark ? 'true' : 'false');
      themeBtn.setAttribute('aria-label', dark ? 'Chuyển sang nền sáng' : 'Chuyển sang nền tối');
    };

    updateThemeBtn();

    themeBtn.addEventListener('click', () => {
      const nextTheme = isDark() ? 'light' : 'dark';
      document.documentElement.dataset.theme = nextTheme;
      try {
        localStorage.setItem('air2:theme', JSON.stringify(nextTheme));
      } catch {}
      updateThemeBtn();
    });
  }

  // Xử lý nút xóa từ khóa
  if (clearBtn && input) {
    const checkClearVis = () => {
      clearBtn.hidden = !input.value.trim();
    };
    checkClearVis();

    input.addEventListener('input', checkClearVis);

    clearBtn.addEventListener('click', () => {
      input.value = '';
      checkClearVis();
      input.focus();
      executeSearch('');
    });
  }

  // Xử lý nộp biểu mẫu
  if (form && input) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      executeSearch(input.value);
    });

    // Tự động tìm sau 320ms dừng gõ
    let debounceTimer = null;
    input.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        executeSearch(input.value);
      }, 320);
    });
  }

  // Lắng nghe sự kiện click mở rộng chi tiết hoặc chọn gợi ý
  document.addEventListener('click', (e) => {
    const ld = e.target.closest('[data-lead-details]');
    if (ld) {
      const tile = ld.closest('.t-lead');
      if (tile) {
        const open = ld.getAttribute('aria-expanded') !== 'true';
        ld.setAttribute('aria-expanded', String(open));
        const span = ld.querySelector('span');
        if (span) span.textContent = open ? 'Thu gọn' : 'Xem đầy đủ';
        tile.classList.toggle('is-expanded', open);
      }
      return;
    }

    const suggest = e.target.closest('[data-suggest]');
    if (suggest) {
      const q = suggest.dataset.suggest;
      if (input) input.value = q;
      executeSearch(q);
      return;
    }
  });

  // Lắng nghe điều hướng lịch sử trình duyệt
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get('q') || '';
    if (input) input.value = q;
    executeSearch(q);
  });

  // Đọc từ khóa ban đầu từ URL (?q=...)
  const params = new URLSearchParams(window.location.search);
  const initialQ = params.get('q') || '';
  if (input && initialQ) {
    input.value = initialQ;
  }
  executeSearch(initialQ);
}

// Tự động chạy khi DOM sẵn sàng
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSearchPage);
  } else {
    initSearchPage();
  }
}

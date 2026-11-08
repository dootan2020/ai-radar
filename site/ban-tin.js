/* Halcyon · Bộ đọc Bản Tin Buổi Sáng (ban-tin.js)
   Bản quyền & quy chuẩn thiết kế: Bento Keynote Apple (docs/ngon-ngu-thiet-ke.md).
   - Tải bản tin đóng băng lúc 06:00 sáng theo giờ Việt Nam.
   - Trình bày 1-5 tin: tiêu đề tiếng Việt, logo nguồn, liên kết bài gốc, tóm tắt khi có.
   - Trang chỉ cho người đọc thấy tin: không giải thích cách chọn tin, không số đếm nội bộ (anh Tuấn, 08/11).
   - Ngày trống, ngày thiếu và lỗi kết nối nói ngắn gọn, tử tế, kèm một lối đi tiếp.
   - Điểm kết thúc rõ ràng ("Hết bản tin hôm nay") và lịch các ngày trước, chia theo tháng. */

import { esc, faceOfStory, faceOfSource, avatar, hydrateHF, watchImageErrors } from './faces.js';
import { ago } from './time-text.js';
import { KIND, METRIC, signalText } from './words.js';
import { origLine, uniqCoverage } from './titles.js';
import { headlineShown, sourceDescriptionMark } from './editorial-headline.js';

/* ---------- Hằng số & Cấu hình ---------- */
export const DEFAULT_DATA_DIR = 'data/editions';
export const TIMEZONE_VN = 'Asia/Ho_Chi_Minh';

/* Danh mục nguồn tin đã xác minh nhận diện và tên hiển thị */
export const KNOWN_SOURCES = new Map([
  ['huggingface-blog', { id: 'huggingface-blog', name: 'Hugging Face Blog', lab: 'huggingface', publisher: 'huggingface' }],
  ['hf-trending', { id: 'hf-trending', name: 'Hugging Face Trending', lab: 'huggingface', publisher: 'huggingface' }],
  ['google-deepmind', { id: 'google-deepmind', name: 'Google DeepMind', lab: 'google', publisher: 'google' }],
  ['google-ai', { id: 'google-ai', name: 'Google AI', lab: 'google', publisher: 'google' }],
  ['google-hf', { id: 'google-hf', name: 'google / Hugging Face', lab: 'google', publisher: 'google' }],
  ['google-youtube', { id: 'google-youtube', name: 'Google YouTube', lab: 'google', publisher: 'google' }],
  ['anthropic-news', { id: 'anthropic-news', name: 'Anthropic News', lab: 'anthropic', publisher: 'anthropic' }],
  ['anthropic-research', { id: 'anthropic-research', name: 'Anthropic Research', lab: 'anthropic', publisher: 'anthropic' }],
  ['anthropic-engineering', { id: 'anthropic-engineering', name: 'Anthropic Engineering', lab: 'anthropic', publisher: 'anthropic' }],
  ['anthropic-youtube', { id: 'anthropic-youtube', name: 'Anthropic YouTube', lab: 'anthropic', publisher: 'anthropic' }],
  ['openai-news', { id: 'openai-news', name: 'OpenAI News', lab: 'openai', publisher: 'openai' }],
  ['openai-hf', { id: 'openai-hf', name: 'openai / Hugging Face', lab: 'openai', publisher: 'openai' }],
  ['openai-youtube', { id: 'openai-youtube', name: 'OpenAI YouTube', lab: 'openai', publisher: 'openai' }],
  ['meta-news', { id: 'meta-news', name: 'Meta AI', lab: 'meta', publisher: 'meta' }],
  ['meta-hf', { id: 'meta-hf', name: 'meta-llama / Hugging Face', lab: 'meta', publisher: 'meta' }],
  ['mistral-news', { id: 'mistral-news', name: 'Mistral News', lab: 'mistral', publisher: 'mistral' }],
  ['mistral-hf', { id: 'mistral-hf', name: 'mistralai / Hugging Face', lab: 'mistral', publisher: 'mistral' }],
  ['xai-news', { id: 'xai-news', name: 'xAI News', lab: 'xai', publisher: 'xai' }],
  ['xai-hf', { id: 'xai-hf', name: 'xai-org / Hugging Face', lab: 'xai', publisher: 'xai' }],
  ['deepseek-hf', { id: 'deepseek-hf', name: 'deepseek-ai / Hugging Face', lab: 'deepseek', publisher: 'deepseek' }],
  ['qwen-hf', { id: 'qwen-hf', name: 'Qwen / Hugging Face', lab: 'qwen', publisher: 'qwen' }],
  ['github-trending', { id: 'github-trending', name: 'GitHub Trending', lab: '', publisher: 'github' }],
  ['hacker-news', { id: 'hacker-news', name: 'Hacker News', lab: '', publisher: 'hacker-news' }],
  ['lobsters', { id: 'lobsters', name: 'Lobsters', lab: '', publisher: 'lobsters' }],
  ['simon-willison', { id: 'simon-willison', name: 'Simon Willison', lab: '', publisher: 'simon-willison' }],
  ['interconnects', { id: 'interconnects', name: 'Interconnects', lab: '', publisher: 'interconnects' }],
  ['smol-ai', { id: 'smol-ai', name: 'Smol AI', lab: '', publisher: 'smol-ai' }],
]);

/* ---------- Định dạng ngày tháng tiếng Việt ---------- */
export function formatFullDateVi(dateStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('-');
  if (parts.length !== 3) return dateStr;
  const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  const weekdays = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
  const wd = weekdays[d.getDay()] || '';
  return `${wd}, ngày ${Number(parts[2])} tháng ${Number(parts[1])} năm ${parts[0]}`;
}

export function formatShortDateVi(dateStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('-');
  if (parts.length !== 3) return dateStr;
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

/* ---------- Trích xuất tóm tắt thật (khi có) ---------- */
export function getStorySummary(story) {
  if (!story) return null;
  if (typeof story.summary_vi === 'string' && story.summary_vi.trim()) {
    return story.summary_vi.trim();
  }
  if (typeof story.summary === 'string' && story.summary.trim()) {
    return story.summary.trim();
  }
  for (const c of story.coverage || []) {
    if (c && typeof c.summary_vi === 'string' && c.summary_vi.trim()) {
      return c.summary_vi.trim();
    }
    if (c && typeof c.summary === 'string' && c.summary.trim()) {
      return c.summary.trim();
    }
  }
  return null;
}

/* ---------- Điều hướng ngày trong Archive Index ---------- */
export function findEditionByDate(index, targetDate) {
  if (!index || !Array.isArray(index.editions)) return null;
  return index.editions.find(e => e.date === targetDate) || null;
}

export function getAdjacentEditions(index, currentDate) {
  if (!index || !Array.isArray(index.editions) || !currentDate) {
    return { prev: null, next: null };
  }
  const idx = index.editions.findIndex(e => e.date === currentDate);
  if (idx === -1) {
    return { prev: null, next: null };
  }
  // index.editions được sắp xếp từ mới nhất tới cũ nhất (newest first)
  // Ngày cũ hơn nằm ở idx + 1; ngày mới hơn nằm ở idx - 1
  const prev = (idx + 1 < index.editions.length) ? index.editions[idx + 1] : null;
  const next = (idx - 1 >= 0) ? index.editions[idx - 1] : null;
  return { prev, next };
}

/* ---------- Sinh HTML cho từng ô tin (Bento Story Tile) ---------- */
export function renderStoryTileHTML(story, isLead = false, sources = null) {
  const srcMap = (sources && sources instanceof Map) ? sources : KNOWN_SOURCES;
  const face = faceOfStory(story, srcMap);
  const firstCov = (story.coverage && story.coverage[0]) || {};
  const sItem = srcMap.get(firstCov.source);
  const sourceDisplayName = sItem?.name || firstCov.name || face.label || face.id || 'Nguồn tin';
  const titleDisplay = headlineShown(story);
  const origHtml = origLine(story.title, story.title_vi, esc);
  const summary = getStorySummary(story);
  const kindLabel = KIND[story.kind] || 'Bài viết';
  const kindIcon = story.kind ? `i-k-${story.kind}` : 'i-k-article';

  // Nguồn thảo luận / bài viết khác trong coverage
  const extraSources = (story.coverage || []).filter(c => c && c.url && c.url !== story.url);
  const extraSourcesHtml = extraSources.length > 0 ? `
    <div class="bt-sources-list">
      <span class="bt-sources-label">Góc nhìn khác:</span>
      ${extraSources.map(c => {
        const item = srcMap.get(c.source);
        const name = item?.name || c.publisher || c.source || 'Nguồn khác';
        return `
          <a class="bt-source-link" href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">
            ${esc(name)}
            <svg class="i" style="width:0.9em;height:0.9em"><use href="#i-out"/></svg>
          </a>
        `;
      }).join('')}
    </div>
  ` : '';

  return `
    <article class="bt-tile ${isLead ? 'bt-tile-lead' : ''}" id="story-${esc(story.id)}">
      <div class="bt-tile-head">
        <div class="bt-source-info">
          ${avatar(face, isLead ? 'md' : 'sm')}
          <span class="bt-source-name">${esc(sourceDisplayName)}</span>
        </div>
        <span class="bt-story-kind">
          <svg class="i"><use href="#${kindIcon}"/></svg>
          ${esc(kindLabel)}
        </span>
        <time class="bt-published-time" datetime="${esc(story.published_at || '')}">
          ${esc(ago(story.published_at))}
        </time>
      </div>

      <h2 class="bt-story-title">
        <a href="${esc(story.url)}" target="_blank" rel="noopener noreferrer">${esc(titleDisplay)}</a>
      </h2>

      ${origHtml ? origHtml : ''}

      ${summary ? `<p class="bt-story-summary">${sourceDescriptionMark()}${esc(summary)}</p>` : ''}

      <div class="bt-tile-actions">
        <a class="bt-btn-primary" href="${esc(story.url)}" target="_blank" rel="noopener noreferrer">
          Đọc bài gốc <svg class="i"><use href="#i-out"/></svg>
        </a>
        ${extraSourcesHtml}
      </div>
    </article>
  `;
}

/* ---------- Sinh HTML cho Ngày Trống (Empty Day) ---------- */
/* Ngắn gọn và tử tế: không giải thích tiêu chí, không số nguồn đã quét (anh Tuấn, 08/11). */
export function renderEmptyStateHTML(edition, isToday = true) {
  const day = formatShortDateVi(edition?.date);
  const lead = isToday || !day ? 'Bản tin sáng nay không có tin nào.' : `Bản tin ngày ${esc(day)} không có tin nào.`;
  return `
    <section class="bt-tile bt-tile-status" aria-labelledby="bt-status-h">
      <div class="bt-status-icon">
        <svg class="i" aria-hidden="true"><use href="#i-cup"/></svg>
      </div>
      <h2 class="bt-status-title" id="bt-status-h">Một buổi sáng yên ắng</h2>
      <p class="bt-status-text">${lead} Mời bạn đọc dòng tin mới nhất hoặc xem lại các ngày trước.</p>
      <div class="bt-status-actions">
        <a class="bt-btn-primary" href="index.html">Đọc dòng tin</a>
      </div>
    </section>
  `;
}

/* ---------- Sinh HTML cho Ngày Thiếu (Missing Day) ---------- */
export function renderMissingStateHTML(targetDate, latestDate) {
  return `
    <section class="bt-tile bt-tile-status" aria-labelledby="bt-status-h">
      <div class="bt-status-icon">
        <svg class="i" aria-hidden="true"><use href="#i-cal"/></svg>
      </div>
      <h2 class="bt-status-title" id="bt-status-h">Không tìm thấy bản tin ngày ${esc(formatShortDateVi(targetDate) || targetDate)}</h2>
      <p class="bt-status-text">Ngày này chưa có bản tin.</p>
      <div class="bt-status-actions">
        ${latestDate ? `
          <a class="bt-btn-primary" href="?ngay=${esc(latestDate)}">
            Về bản tin mới nhất (${esc(formatShortDateVi(latestDate))})
          </a>
        ` : ''}
      </div>
    </section>
  `;
}

/* ---------- Sinh HTML cho Lỗi Tải Dữ Liệu (Failed Fetch) ---------- */
export function renderErrorStateHTML() {
  return `
    <section class="bt-tile bt-tile-status" aria-labelledby="bt-status-h">
      <div class="bt-status-icon is-warn">
        <svg class="i" aria-hidden="true"><use href="#i-warn"/></svg>
      </div>
      <h2 class="bt-status-title" id="bt-status-h">Không thể tải bản tin</h2>
      <p class="bt-status-text">Bạn kiểm tra kết nối mạng rồi thử lại nhé.</p>
      <div class="bt-status-actions">
        <button class="bt-btn-primary" id="bt-retry-btn" type="button">
          Thử tải lại
        </button>
      </div>
    </section>
  `;
}

/* ---------- Lịch các ngày trước ----------
   Thay hàng nút ngày dài, lệch tâm (anh Tuấn, 08/11: "Bộ lọc theo ngày đang lệch lạc, rất xấu"): mỗi tháng một nhóm,
   mỗi ngày một ô cùng cỡ trong lưới căn trái (thứ viết tắt trên, số ngày dưới), như một tờ lịch. Ngày đang xem có
   mặt lót của màu nhấn. */
const WEEKDAY_SHORT = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
export function renderArchiveHTML(editions = [], currentDate = null) {
  const months = [];
  for (const e of editions || []) {
    const [y, m, d] = String(e?.date || '').split('-').map(Number);
    if (!y || !m || !d) continue;
    const key = `${y}-${m}`;
    let group = months[months.length - 1];
    if (!group || group.key !== key) months.push(group = { key, y, m, days: [] });
    group.days.push({ date: e.date, d, wd: new Date(y, m - 1, d).getDay() });
  }
  if (!months.length) return '';
  return `
    <nav class="bt-archive" aria-labelledby="bt-archive-h">
      <h3 class="bt-archive-heading" id="bt-archive-h">Các ngày trước</h3>
      ${months.map(g => `
        <section class="bt-archive-month" aria-label="Tháng ${g.m} năm ${g.y}">
          <h4 class="bt-archive-month-h">Tháng ${g.m}<span class="bt-archive-year">${g.y}</span></h4>
          <ol class="bt-archive-grid">
            ${g.days.map(x => `<li><a class="bt-archive-day" href="?ngay=${esc(x.date)}"${x.date === currentDate ? ' aria-current="date"' : ''} aria-label="${esc(formatFullDateVi(x.date))}"><span class="bt-archive-wd">${WEEKDAY_SHORT[x.wd]}</span><span class="bt-archive-d num">${String(x.d).padStart(2, '0')}</span></a></li>`).join('')}
          </ol>
        </section>
      `).join('')}
    </nav>
  `;
}

/* ---------- Sinh HTML Khối Kết Thúc ("Hết bản tin hôm nay") ---------- */
export function renderEndSectionHTML(currentDate, isToday, availableEditions = [], empty = false) {
  const titleText = isToday ? 'Hết bản tin hôm nay' : `Hết bản tin ngày ${formatShortDateVi(currentDate)}`;
  const subtitleText = isToday
    ? 'Bạn đã xem trọn vẹn điểm tin AI sáng nay. Chúc bạn một ngày làm việc hiệu quả.'
    : `Bạn đã xem trọn vẹn bản tin của ngày ${formatShortDateVi(currentDate)}.`;

  return `
    <section class="bt-end-section${empty ? ' is-archive-only' : ''}" aria-label="${empty ? 'Các ngày trước' : 'Kết thúc bản tin'}">
      ${empty ? '' : `
        <div class="bt-end-check">
          <svg class="i" aria-hidden="true"><use href="#i-check"/></svg>
        </div>
        <h2 class="bt-end-title">${esc(titleText)}</h2>
        <p class="bt-end-text">${esc(subtitleText)}</p>
      `}
      ${renderArchiveHTML(availableEditions, currentDate)}
      <a class="bt-back-to-top" href="#top">
        <svg class="i" aria-hidden="true"><use href="#i-arrow-up"/></svg> Về đầu trang
      </a>
    </section>
  `;
}

/* ---------- Lớp Quản Lý Ứng Dụng Đọc Bản Tin ---------- */
export class BanTinReader {
  constructor(options = {}) {
    this.dataDir = options.dataDir || DEFAULT_DATA_DIR;
    this.index = null;
    this.currentEdition = null;
    this.currentDate = null;
    this.state = 'loading'; // 'loading' | 'edition' | 'empty' | 'missing' | 'error'
    this.errorMessage = null;
    this.sources = new Map(KNOWN_SOURCES);

    // Elements
    this.boardEl = null;
    this.endSectionEl = null;
    this.titleEl = null;
    this.subtitleEl = null;
    this.currentDateBtnEl = null;
    this.prevBtnEl = null;
    this.nextBtnEl = null;
    this.themeBtnEl = null;
  }

  bindElements() {
    this.boardEl = document.getElementById('bt-board');
    this.endSectionEl = document.getElementById('bt-end-section');
    this.titleEl = document.getElementById('bt-title');
    this.subtitleEl = document.getElementById('bt-subtitle');
    this.currentDateBtnEl = document.getElementById('bt-current-date');
    this.prevBtnEl = document.getElementById('bt-prev');
    this.nextBtnEl = document.getElementById('bt-next');
    this.themeBtnEl = document.getElementById('theme');
  }

  async loadIndex() {
    try {
      const res = await fetch(`${this.dataDir}/index.json`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!data || !Array.isArray(data.editions)) {
        throw new Error('Mục lục bản tin không hợp lệ');
      }
      this.index = data;
      return data;
    } catch (err) {
      this.state = 'error';
      this.errorMessage = err.message || 'Lỗi nạp tệp mục lục bản tin';
      return null;
    }
  }

  async loadSources() {
    for (const url of ['data/radar-ui.json', 'data/radar.json']) {
      try {
        const res = await fetch(url);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data?.sources)) {
            data.sources.forEach(s => {
              if (s && s.id) this.sources.set(s.id, s);
            });
            break;
          }
        }
      } catch {
        // Tiếp tục dùng KNOWN_SOURCES khi ngoại tuyến hoặc không tìm thấy tệp
      }
    }
  }

  async loadEdition(date) {
    if (!this.index) {
      const ok = await this.loadIndex();
      if (!ok) return;
    }

    const targetDate = date || (this.index.latest ? this.index.latest.date : null);
    if (!targetDate) {
      this.state = 'error';
      this.errorMessage = 'Không có ngày nào trong kho lưu trữ bản tin';
      this.render();
      return;
    }

    this.currentDate = targetDate;
    const entry = findEditionByDate(this.index, targetDate);
    if (!entry) {
      this.state = 'missing';
      this.render();
      return;
    }

    this.state = 'loading';
    this.render();

    try {
      const filePath = `${this.dataDir}/${entry.path || (targetDate + '.json')}`;
      const res = await fetch(filePath);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const edition = await res.json();
      if (!edition || !Array.isArray(edition.stories)) {
        throw new Error('Dữ liệu bản tin không hợp lệ');
      }
      this.currentEdition = edition;
      this.state = (edition.stories.length === 0) ? 'empty' : 'edition';
    } catch (err) {
      this.state = 'error';
      this.errorMessage = err.message || 'Lỗi nạp tệp bản tin ngày ' + targetDate;
    }

    this.render();
  }

  navigateToDate(date, updateHistory = true) {
    if (!date || date === this.currentDate) return;
    if (updateHistory && typeof window !== 'undefined' && window.history) {
      const url = new URL(window.location.href);
      url.searchParams.set('ngay', date);
      window.history.pushState({ date }, '', url.toString());
    }
    this.loadEdition(date);
  }

  initTheme() {
    if (!this.themeBtnEl) return;
    const applyTheme = (theme) => {
      document.documentElement.dataset.theme = theme;
      this.themeBtnEl.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
      try {
        localStorage.setItem('air2:theme', JSON.stringify(theme));
      } catch (e) { /* lưu trữ bị chặn */ }
    };

    this.themeBtnEl.addEventListener('click', () => {
      const current = document.documentElement.dataset.theme ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
    });
  }

  initNavEvents() {
    if (this.prevBtnEl) {
      this.prevBtnEl.addEventListener('click', () => {
        const { prev } = getAdjacentEditions(this.index, this.currentDate);
        if (prev) this.navigateToDate(prev.date);
      });
    }

    if (this.nextBtnEl) {
      this.nextBtnEl.addEventListener('click', () => {
        const { next } = getAdjacentEditions(this.index, this.currentDate);
        if (next) this.navigateToDate(next.date);
      });
    }

    window.addEventListener('popstate', (e) => {
      const urlDate = new URLSearchParams(window.location.search).get('ngay') ||
                      new URLSearchParams(window.location.search).get('date');
      this.loadEdition(urlDate);
    });

    // Phím tắt bàn phím
    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      if (e.key === 'ArrowLeft' || e.key === 'j' || e.key === 'J') {
        const { prev } = getAdjacentEditions(this.index, this.currentDate);
        if (prev) this.navigateToDate(prev.date);
      } else if (e.key === 'ArrowRight' || e.key === 'k' || e.key === 'K') {
        const { next } = getAdjacentEditions(this.index, this.currentDate);
        if (next) this.navigateToDate(next.date);
      } else if (e.key === 't' || e.key === 'T') {
        if (this.themeBtnEl) this.themeBtnEl.click();
      }
    });
  }

  render() {
    if (!this.boardEl) return;

    // Cập nhật điều hướng ngày trên thanh bar
    const { prev, next } = getAdjacentEditions(this.index, this.currentDate);
    if (this.prevBtnEl) this.prevBtnEl.disabled = !prev;
    if (this.nextBtnEl) this.nextBtnEl.disabled = !next;
    if (this.currentDateBtnEl) {
      this.currentDateBtnEl.textContent = formatShortDateVi(this.currentDate) || 'Đang tải';
    }

    // 1. Trạng thái Loading
    if (this.state === 'loading') {
      this.boardEl.setAttribute('aria-busy', 'true');
      this.boardEl.innerHTML = `
        <div class="bt-tile bt-tile-lead bt-skeleton" style="min-height: 240px">
          <div class="sk-title" style="width: 40%"></div>
          <div class="sk-title" style="width: 80%"></div>
          <div class="sk-line" style="width: 60%"></div>
          <div class="sk-box"></div>
        </div>
      `;
      if (this.endSectionEl) this.endSectionEl.innerHTML = '';
      return;
    }

    this.boardEl.removeAttribute('aria-busy');

    // 2. Trạng thái Lỗi Kết Nối
    if (this.state === 'error') {
      if (this.subtitleEl) this.subtitleEl.hidden = true;
      this.boardEl.innerHTML = renderErrorStateHTML();
      const retryBtn = document.getElementById('bt-retry-btn');
      if (retryBtn) {
        retryBtn.addEventListener('click', () => this.loadEdition(this.currentDate));
      }
      if (this.endSectionEl) this.endSectionEl.innerHTML = '';
      return;
    }

    // 3. Trạng thái Ngày Thiếu
    if (this.state === 'missing') {
      const latestDate = this.index?.latest?.date;
      if (this.titleEl) this.titleEl.textContent = formatFullDateVi(this.currentDate) || 'Bản tin AI';
      if (this.subtitleEl) this.subtitleEl.hidden = true;
      this.boardEl.innerHTML = renderMissingStateHTML(this.currentDate, latestDate);
      if (this.endSectionEl) this.endSectionEl.innerHTML = '';
      return;
    }

    // 4. Trạng thái Ngày Trống hoặc Có Tin
    const edition = this.currentEdition;
    const isToday = Boolean(this.index?.latest?.date === edition.date);

    // Cập nhật Masthead: ngày và một dòng dẫn, không số đếm (anh Tuấn, 08/11)
    if (this.titleEl) {
      this.titleEl.textContent = formatFullDateVi(edition.date);
    }
    if (this.subtitleEl) {
      const hasStories = edition.stories.length > 0;
      this.subtitleEl.textContent = hasStories ? 'Những chuyện AI đáng đọc, gói gọn cho buổi sáng.' : '';
      this.subtitleEl.hidden = !hasStories;
    }

    // Render Board
    if (this.state === 'empty') {
      this.boardEl.className = 'bt-grid is-empty';
      this.boardEl.innerHTML = renderEmptyStateHTML(edition, isToday);
    } else {
      const isSingle = edition.stories.length === 1;
      this.boardEl.className = `bt-grid ${isSingle ? 'is-single' : ''}`;
      this.boardEl.innerHTML = edition.stories.map((st, i) => renderStoryTileHTML(st, i === 0, this.sources)).join('');
    }

    // Render End of Edition
    if (this.endSectionEl) {
      this.endSectionEl.innerHTML = renderEndSectionHTML(
        edition.date,
        isToday,
        this.index?.editions || [],
        this.state === 'empty'
      );
    }

    // Kích hoạt nạp avatar Hugging Face và bắt lỗi ảnh
    hydrateHF(this.boardEl);
    watchImageErrors();
  }

  async start() {
    this.bindElements();
    this.initTheme();
    this.initNavEvents();
    await this.loadSources();

    // Lấy ngày từ URL (?ngay=YYYY-MM-DD hoặc ?date=YYYY-MM-DD hoặc #YYYY-MM-DD)
    let initialDate = null;
    if (typeof window !== 'undefined' && window.location) {
      const sp = new URLSearchParams(window.location.search);
      initialDate = sp.get('ngay') || sp.get('date');
      if (!initialDate && window.location.hash) {
        const m = /^#(\d{4}-\d{2}-\d{2})$/.exec(window.location.hash);
        if (m) initialDate = m[1];
      }
    }

    await this.loadEdition(initialDate);
  }
}

// Tự động khởi tạo khi chạy trong trình duyệt
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  const reader = new BanTinReader();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => reader.start());
  } else {
    reader.start();
  }
}

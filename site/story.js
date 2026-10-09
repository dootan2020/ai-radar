/* ai·radar · site/story.js
   Shared render module for the story modal and static story page.
   Combines Direction A ("the article made whole") with Direction B's evidence block
   ("Vì sao được chọn": worth score, unique publishers, discussion signals).
   Adheres strictly to the Bento Keynote design language and 4pt token scale.
*/

import { esc, fmt, avatar, faceOfStory, faceOfSource } from './faces.js';
import { ago } from './time-text.js';
import { KIND, METRIC } from './words.js';
import { shown, uniqCoverage } from './titles.js';
import { fallbackWorth } from './worth-score.js';

const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const hostOf = u => {
  try {
    return new URL(u).hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
};

/* Format number to 1 decimal place with Vietnamese locale */
const nf1 = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat('vi-VN');

/* Publisher metadata resolution */
export function getPublisherMeta(story, srcMap = new Map()) {
  const c0 = (story.coverage && story.coverage[0]) || {};
  const s = srcMap.get(c0.source || story.source) || {};
  const pub = c0.publisher || s.publisher || hostOf(story.url) || 'nguon-tin';
  const name = s.name || c0.publisher || hostOf(story.url) || 'Nguồn gốc';
  return { publisher: pub, name };
}

/* Calculate worth score and components if missing */
export function worthOfStory(st, genTime = Date.now()) {
  if (typeof st.worth_score === 'number' && st.worth_parts) {
    return { score: st.worth_score, parts: st.worth_parts };
  }
  const meas = st.hot_signals && st.hot_signals.measurement;
  const hot = meas && Number.isFinite(st.hot_score) ? Math.max(0, st.hot_score) : 0;
  const n = Number.isFinite(st.source_count) ? st.source_count : (st.coverage && st.coverage.length) || 1;
  const own = (st.coverage || []).find(c => c && c.lab);
  const fh = own ? { why: `${own.lab} công bố trực tiếp` } : null;
  return fallbackWorth(st, genTime, hot, n, fh);
}

/* Unique publishers count from coverage list */
export function uniquePublishers(coverage = []) {
  const hosts = new Set();
  for (const item of coverage) {
    if (!item) continue;
    if (item.author_handle) {
      hosts.add('x');
      continue;
    }
    const url = item.url;
    if (url && /^https?:\/\//i.test(url)) {
      try {
        hosts.add(new URL(url).hostname.replace(/^www\./i, '').toLowerCase());
      } catch {}
    } else if (item.publisher) {
      hosts.add(String(item.publisher).toLowerCase());
    } else if (item.source) {
      hosts.add(String(item.source).toLowerCase());
    }
  }
  return Math.max(1, hosts.size);
}

/* Aggregate discussion points and comments across coverage items */
export function discussionMetrics(coverage = []) {
  const seen = new Set();
  let comments = 0;
  let points = 0;
  let hasComments = false;
  let hasPoints = false;
  let discussionUrl = null;

  for (const item of coverage) {
    if (!item) continue;
    const m = item.metrics;
    if (m && typeof m === 'object') {
      const thread = item.discussion_url || `${item.source || ''}:${item.url || ''}`;
      if (!seen.has(thread)) {
        seen.add(thread);
        if (Number.isFinite(m.comments) && m.comments >= 0) {
          comments += m.comments;
          hasComments = true;
        }
        if (Number.isFinite(m.points) && m.points >= 0) {
          points += m.points;
          hasPoints = true;
        }
      }
    }
    if (!discussionUrl && item.discussion_url && /^https?:\/\//i.test(item.discussion_url)) {
      discussionUrl = item.discussion_url;
    }
  }

  if (!hasComments && !hasPoints) return null;

  const parts = [];
  if (hasPoints) parts.push(`${nf0.format(points)} điểm`);
  if (hasComments) parts.push(`${nf0.format(comments)} bình luận`);
  return {
    text: parts.join(' · '),
    url: discussionUrl
  };
}

/* Substantive reasons why story is worth reading */
export function substantiveReasons(st, srcMap = new Map()) {
  const parts = [];
  const n = uniquePublishers(st.coverage || []);
  if (n >= 2) {
    parts.push(`${n} nguồn cùng đưa tin`);
  }
  const meas = st.hot_signals && st.hot_signals.measurement;
  if (meas) {
    const word = METRIC[meas.metric] || meas.metric;
    const s = srcMap.get(meas.source);
    const where = s ? s.name : meas.source;
    parts.push(`${fmt(meas.value)} ${word}${where ? ` trên ${where}` : ''}`);
  }
  const own = (st.coverage || []).find(c => c && c.lab);
  if (own) {
    parts.push(`${own.lab} công bố trực tiếp`);
  }
  return parts;
}

const LAB_NAME = {
  openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', meta: 'Meta', microsoft: 'Microsoft',
  nvidia: 'NVIDIA', amazon: 'Amazon', mistral: 'Mistral', xai: 'xAI', deepseek: 'DeepSeek', qwen: 'Qwen', huggingface: 'Hugging Face'
};

export function firstHandOf(st, srcMap = new Map()) {
  const own = (st.coverage || []).find(c => {
    if (!c) return false;
    const s = srcMap.get(c.source) || {};
    return !!(c.lab || s.lab);
  });
  if (own) {
    const lab = own.lab || (srcMap.get(own.source) || {}).lab || '';
    const name = LAB_NAME[lab] || lab;
    return { label: `${name} công bố`, why: `${name} công bố trực tiếp` };
  }
  if (st.kind === 'paper') return { label: 'Bài báo gốc', why: 'Bài báo gốc của nhóm nghiên cứu' };
  return null;
}

/* Render "Vì sao được chọn" evidence block (Direction B as a quiet editorial aside) */
export function renderEvidenceBlockHTML(story, srcMap = new Map()) {
  const worth = worthOfStory(story);
  const scoreFormatted = Number.isFinite(worth.score) ? nf1.format(worth.score) : '10.0';
  const cov = Array.isArray(story.coverage) ? story.coverage : [];
  const pubCount = Number.isFinite(story.source_count) ? story.source_count : uniquePublishers(cov);
  const disc = discussionMetrics(cov);

  const rows = [
    `<div class="story-evidence-row">
      <dt class="story-evidence-label">Điểm đáng đọc</dt>
      <dd class="story-evidence-val num">${scoreFormatted}</dd>
    </div>`,
    `<div class="story-evidence-row">
      <dt class="story-evidence-label">Nhà xuất bản</dt>
      <dd class="story-evidence-val num">${pubCount} nguồn</dd>
    </div>`
  ];

  if (disc) {
    rows.push(`
      <div class="story-evidence-row">
        <dt class="story-evidence-label">Thảo luận cộng đồng</dt>
        <dd class="story-evidence-val">
          ${disc.url ? `<a class="story-evidence-link" href="${esc(safe(disc.url))}" target="_blank" rel="noopener noreferrer">${esc(disc.text)} <span aria-hidden="true">↗</span></a>` : `<span class="num">${esc(disc.text)}</span>`}
        </dd>
      </div>
    `);
  }

  const fh = firstHandOf(story, srcMap);
  if (fh && fh.why) {
    rows.push(`
      <div class="story-evidence-row">
        <dt class="story-evidence-label">Công bố gốc</dt>
        <dd class="story-evidence-val">${esc(fh.why)}</dd>
      </div>
    `);
  }

  return `
    <aside class="story-evidence-box" aria-label="Vì sao được chọn">
      <h2 class="story-evidence-title">Vì sao được chọn</h2>
      <dl class="story-evidence-list">
        ${rows.join('')}
      </dl>
    </aside>
  `;
}

/* Render Key Points block (Direction A) */
export function renderKeyPointsHTML(keyPoints, publisherName = '') {
  if (!Array.isArray(keyPoints) || !keyPoints.length) return '';
  const items = keyPoints.map((point, idx) => `
    <li class="story-point-item">
      <span class="story-point-num">${idx + 1}</span>
      <span class="story-point-text">${esc(point)}</span>
    </li>
  `).join('');

  const sub = publisherName
    ? `Tóm tắt bởi AI từ bài viết gốc của ${esc(publisherName)}`
    : 'Tóm tắt bởi AI từ bài viết gốc';

  return `
    <section class="story-keypoints-box" aria-label="Ý chính của câu chuyện">
      <div class="story-section-head">
        <div>
          <h2 class="story-section-h2">Ý chính của câu chuyện</h2>
          <p class="story-section-sub">${sub}</p>
        </div>
      </div>
      <ol class="story-points-list">
        ${items}
      </ol>
      <p class="story-points-disclosure">ai-radar tóm tắt từ dữ liệu gốc để bạn đọc nhanh dưới 1 phút. Bản quyền thuộc về nhà xuất bản.</p>
    </section>
  `;
}

const NON_TERMINAL_ABBRS = new Set([
  'e.g.', 'i.e.', 'vs.', 'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.', 'st.', 'no.', 'vol.',
  'jan.', 'feb.', 'mar.', 'apr.', 'jun.', 'jul.', 'aug.', 'sep.', 'sept.', 'oct.', 'nov.', 'dec.'
]);

/* Trim excerpt to include only complete sentences */
export function trimCompleteSentences(text) {
  if (typeof text !== 'string') return '';
  text = text.trim();
  if (!text) return '';

  const regex = /(?:\.{3}|…|[.!?。！？])['"”’\)\]]*(?=\s|$)/g;
  let lastEnd = -1;
  let m;

  while ((m = regex.exec(text)) !== null) {
    const start = m.index;
    const end = regex.lastIndex;
    const punct = m[0];

    if (punct.startsWith('.') && !punct.startsWith('..')) {
      const prefix = text.slice(0, start);
      const tokens = prefix.trim().split(/\s+/);
      if (tokens.length && tokens[0]) {
        const lastToken = tokens[tokens.length - 1];
        const lastWord = (lastToken + punct).toLowerCase().replace(/^['"”’\(\[\{]+|['"”’\)\]\}]+$/g, '');
        if (NON_TERMINAL_ABBRS.has(lastWord) && end < text.length) {
          continue;
        }
        if (/^[a-zA-Z]\.$/.test(lastWord) && end < text.length) {
          continue;
        }
        if (/\.(?:com|org|net|io|ai|vn|is|ph|co|html|json|cpp)\b/.test(lastWord)) {
          continue;
        }
      }
    }

    lastEnd = end;
  }

  if (lastEnd <= 0) return '';
  return text.slice(0, lastEnd).trim();
}

/* Render Fallback Summary when key points are not available */
export function renderFallbackBodyHTML(story, publisherName = '') {
  const sumVi = trimCompleteSentences(story.summary_vi || '');
  const sumEn = trimCompleteSentences(story.summary || '');
  const sumText = sumVi || sumEn;
  const isTranslated = !!(sumVi && sumEn && sumVi !== sumEn);

  if (!sumText) {
    return `
      <section class="story-summary-box story-empty-box" aria-label="Đoạn trích bài viết">
        <p class="story-empty-text">Chưa có đoạn trích cho bài viết này. Bạn có thể mở đọc toàn văn bài viết gốc bên dưới.</p>
      </section>
    `;
  }

  const sub = isTranslated
    ? (publisherName
        ? `Đoạn trích từ bài viết gốc của ${esc(publisherName)}, bản dịch máy`
        : 'Đoạn trích từ bài viết gốc, bản dịch máy')
    : (publisherName
        ? `Đoạn trích từ bài viết gốc của ${esc(publisherName)}`
        : 'Đoạn trích từ bài viết gốc');

  return `
    <section class="story-summary-box" aria-label="Đoạn trích bài viết">
      <div class="story-section-head">
        <div>
          <h2 class="story-section-h2">Đoạn trích bài viết</h2>
          <p class="story-section-sub">${sub}</p>
        </div>
      </div>
      <p class="story-summary-text">${esc(sumText)}</p>
      ${isTranslated ? `
        <div class="card-orig" style="margin-top:var(--space-12)">
          <span class="mt" aria-hidden="true" title="Bản dịch máy; dòng này là đoạn trích gốc">Translated</span>
          <span class="sr" lang="vi">Bản dịch máy. Đoạn trích gốc: </span>
          <span class="orig-text" lang="en">${esc(sumEn)}</span>
        </div>
      ` : ''}
      <p class="story-points-disclosure">Đoạn trích do nhà xuất bản cung cấp. Bản quyền thuộc về nhà xuất bản.</p>
    </section>
  `;
}

/* Render Coverage List */
export function renderCoverageListHTML(coverage, srcMap = new Map()) {
  const uniq = [...uniqCoverage((coverage || []).filter(c => !c.author_handle), s => (srcMap.get(s) || {}).name),
    ...(coverage || []).filter(c => c.author_handle)];
  if (!uniq || uniq.length <= 1) return '';

  const rows = uniq.map(c => {
    const s = srcMap.get(c.source) || {};
    const pubName = c.author_handle
      ? `${c.author_name || s.name || c.publisher || 'X'} (@${c.author_handle})`
      : s.name || c.publisher || hostOf(c.url) || 'Nguồn tin';
    const cTitle = c.title_vi || c.title || '';
    const face = faceOfSource(c, srcMap);
    return `
      <li>
        <a class="story-cov-item" href="${esc(safe(c.url))}" target="_blank" rel="noopener noreferrer">
          <div class="story-cov-main">
            <div class="story-cov-header">
              <span class="src-av" aria-hidden="true">${avatar(face, 'xs')}</span>
              <span class="story-pub-name">${esc(pubName)}</span>
              <span class="story-pub-dot">·</span>
              <time datetime="${esc(c.published_at || '')}">${c.published_at ? esc(ago(c.published_at)) : ''}</time>
            </div>
            <h3 class="story-cov-title">${esc(cTitle)}</h3>
          </div>
          <span class="story-cov-arrow" aria-hidden="true">
            <svg class="i" style="width:18px;height:18px"><use href="#i-out"/></svg>
          </span>
        </a>
      </li>
    `;
  }).join('');

  return `
    <section class="story-coverage-wrap" aria-label="Các nguồn cùng đưa tin">
      <div class="story-section-head">
        <h2 class="story-section-h2">Các nguồn cùng đưa tin</h2>
        <span class="story-coverage-count">${uniq.length} bài viết liên quan</span>
      </div>
      <ul class="story-coverage-list">
        ${rows}
      </ul>
    </section>
  `;
}

/* Render Prominent Original Article Gateway (CTA to original publisher) */
export function renderOriginGatewayHTML(story, srcMap = new Map()) {
  const { name } = getPublisherMeta(story, srcMap);
  const origUrl = story.url || (story.coverage && story.coverage[0] && story.coverage[0].url) || '#';
  const hasKp = Array.isArray(story.key_points) && story.key_points.length > 0;
  const desc = hasKp
    ? 'ai-radar tóm tắt ý chính để bạn nắm nhanh sự kiện. Đọc bài gốc để xem trọn vẹn chi tiết, dẫn chứng và các phân tích chuyên sâu.'
    : 'Mở bài gốc để xem trọn vẹn chi tiết, dẫn chứng và các phân tích chuyên sâu.';

  return `
    <section class="story-origin-gateway" aria-label="Chuyển đến bài viết gốc">
      <div class="story-origin-info">
        <span class="story-origin-eyebrow">Toàn văn bài viết</span>
        <h3 class="story-origin-title">Đọc bài viết đầy đủ trên ${esc(name)}</h3>
        <p class="story-origin-desc">${desc}</p>
      </div>
      <a class="btn primary story-origin-btn" href="${esc(safe(origUrl))}" target="_blank" rel="noopener noreferrer" id="story-open-origin-btn">
        <span>Mở bài viết gốc</span>
        <svg class="i" aria-hidden="true"><use href="#i-out"/></svg>
      </a>
    </section>
  `;
}

/* Main render function used by both the Modal and the Static Story Page */
export function renderStoryHTML(story, srcMap = new Map(), options = {}) {
  if (!story || !story.id) return '<p class="story-error-msg">Không tìm thấy bài viết.</p>';

  const { name } = getPublisherMeta(story, srcMap);
  const titleVi = shown(story.title, story.title_vi);
  const hasOrig = !!(story.title_vi && story.title && story.title_vi.trim() !== story.title.trim());
  const face = faceOfStory(story, srcMap);
  const kindText = KIND[story.kind] || 'Bài viết';
  const hasKp = Array.isArray(story.key_points) && story.key_points.length > 0;
  const isSaved = !!options.isSaved;
  const isModal = !!options.isModal;
  const isPage = !!options.isPage;
  const origUrl = story.url || (story.coverage && story.coverage[0] && story.coverage[0].url) || '#';

  // Media image block
  let mediaHTML = '';
  if (story.image && story.image.src) {
    mediaHTML = `
      <figure class="story-media">
        <img class="story-media-img" src="${esc(story.image.src)}" alt="${esc(titleVi)}" loading="eager" decoding="async">
        <figcaption class="story-media-caption">
          <span>Ảnh từ bài viết gốc</span>
          <span class="story-pub-name">${esc(name)}</span>
        </figcaption>
      </figure>
    `;
  }

  // Footer navigation
  const footerHTML = isPage ? `
    <footer class="story-footer">
      <a class="story-footer-link" href="../../index.html">← Quay lại dòng tin chính</a>
      <a class="story-footer-link" href="#story-root">Lên đầu bài viết ↑</a>
    </footer>
  ` : `
    <footer class="story-footer">
      <button class="story-footer-link-btn" id="story-footer-close-btn" type="button">← Quay lại dòng tin chính</button>
      <button class="story-footer-link-btn" id="story-footer-top-btn" type="button">Lên đầu bài viết ↑</button>
    </footer>
  `;

  return `
    <article class="story-article" data-id="${esc(story.id)}" aria-labelledby="story-modal-title">
      <header class="story-header">
        <div class="story-meta-row">
          <div class="story-pub-info">
            <span class="src-av" aria-hidden="true">${avatar(face, 'sm')}</span>
            <a class="story-pub-name-link" href="${esc(safe(origUrl))}" target="_blank" rel="noopener noreferrer" title="Đọc bài viết gốc tại ${esc(name)}">
              ${esc(name)}
              <span class="story-ext-arrow" aria-hidden="true">↗</span>
            </a>
            <span class="story-kind-pill">${esc(kindText)}</span>
            <span class="story-pub-dot">·</span>
            <time datetime="${esc(story.published_at || '')}">${story.published_at ? esc(ago(story.published_at)) : ''}</time>
          </div>
          ${!isModal ? `
            <div class="story-header-actions">
              <button class="doc-icon-btn ${isSaved ? 'is-saved' : ''}" id="story-act-save" type="button" aria-label="${isSaved ? 'Bỏ lưu bài viết' : 'Lưu bài viết'}" title="${isSaved ? 'Bỏ lưu' : 'Lưu đọc sau (phím S)'}">
                <svg class="i" aria-hidden="true"><use href="#i-bookmark"/></svg>
              </button>
              <button class="doc-icon-btn" id="story-act-share" type="button" aria-label="Sao chép liên kết" title="Sao chép liên kết">
                <svg class="i" aria-hidden="true"><use href="#i-link"/></svg>
              </button>
            </div>
          ` : ''}
        </div>

        <h1 class="story-headline" id="story-modal-title">${esc(titleVi)}</h1>

        ${hasOrig ? `
          <div class="story-orig-block">
            <p class="card-orig">
              <span class="mt" aria-hidden="true" title="Bản dịch máy; dòng này là tiêu đề gốc">Translated</span>
              <span class="sr" lang="vi">Bản dịch máy. Tiêu đề gốc: </span>
              <span class="orig-text" lang="en">${esc(story.title)}</span>
            </p>
          </div>
        ` : ''}

        <div class="story-header-cta">
          <a class="story-origin-cta" href="${esc(safe(origUrl))}" target="_blank" rel="noopener noreferrer">
            <span>Đọc bài gốc tại ${esc(name)}</span>
            <span class="story-cta-arrow" aria-hidden="true">↗</span>
          </a>
        </div>
      </header>

      <div class="story-body-grid">
        <div class="story-col-main">
          ${hasKp ? renderKeyPointsHTML(story.key_points, name) : renderFallbackBodyHTML(story, name)}
        </div>
        <div class="story-col-aside">
          ${mediaHTML}
          ${renderEvidenceBlockHTML(story, srcMap)}
        </div>
      </div>

      ${renderCoverageListHTML(story.coverage, srcMap)}

      ${renderOriginGatewayHTML(story, srcMap)}

      ${footerHTML}
    </article>
  `;
}

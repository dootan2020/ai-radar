/* Halcyon · site/story.js
   Shared render module for the story modal and static story page.
   The story reads as one vertical column: publisher line, headline, link to the original,
   image, text, other coverage, then the full-article gateway. Nothing sits beside anything else.
   Adheres strictly to the Bento Keynote design language and 4pt token scale.
*/

import { esc, fmt, avatar, faceOfStory, faceOfSource } from './faces.js';
import { ago } from './time-text.js';
import { KIND, METRIC } from './words.js';
import { uniqCoverage } from './titles.js';
import { headlineShown, hasEditorialSummary, isDeskProse } from './editorial-headline.js';
export { hasEditorialSummary } from './editorial-headline.js';
import { fallbackWorth } from './worth-score.js';

const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const hostOf = u => {
  try {
    return new URL(u).hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
};

/* Format numbers with Vietnamese locale */
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

export function storyTitle(story) {
  return headlineShown(story, true);
}

const summaryText = text => esc(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

/* Summary sources carry the publisher key in lowercase ("nvidia", "hacker-news"). Show the
   source's display name instead: the story's own source first, then any source of that publisher,
   then the key with each word capitalised. A name that already has capitals is kept as written. */
export function sourceDisplayName(raw, story = {}, srcMap = new Map()) {
  const key = String(raw || '').trim();
  if (!key || key !== key.toLowerCase()) return key;
  const own = (story.coverage || []).map(c => c && srcMap.get(c.source)).find(s => s && s.publisher === key && s.name);
  if (own) return own.name;
  for (const s of srcMap.values()) {
    if (s && s.name && (s.publisher === key || s.id === key) && s.name !== s.name.toLowerCase()) return s.name;
  }
  return key.split(/[-_\s]+/).filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
}

export function renderEditorialSummaryHTML(story, publisherName = '', srcMap = new Map()) {
  if (!hasEditorialSummary(story)) return renderFallbackBodyHTML(story, publisherName);
  const shown = name => sourceDisplayName(name, story, srcMap);
  const sources = story.summary_sources.filter(s => safe(s?.url) !== '#').map(s =>
    `<a href="${esc(safe(s?.url))}" target="_blank" rel="noopener noreferrer">${esc(shown(s.name))}${s.role === 'primary' ? ' — nguồn gốc' : ''}</a>`).join(' · ');
  const partial = (story.summary_limitations || []).includes('partial_source');
  const outletRaw = (story.summary_sources.find(s => s?.role === 'outlet' && s?.name) || {}).name;
  const outlet = outletRaw ? shown(outletRaw) : publisherName;
  return `
    ${isDeskProse(story) ? renderDeskProseHTML(story.key_points, outlet) : renderKeyPointsHTML(story.key_points, publisherName)}
    <div class="story-summary-attribution">
      <p class="story-summary-sources"><span class="story-credit-label">Nguồn:</span> ${sources}</p>
      ${partial ? '<p class="story-section-sub">Bản tóm tắt dựa trên các phần nguồn đọc được.</p>' : ''}
      ${(story.summary_limitations || []).includes('missing_primary') ? '<p class="story-section-sub">Chưa đọc được nguồn gốc được bài báo dẫn.</p>' : ''}
    </div>`;
}

/* The newsroom writer desk's short paragraphs, labelled with who wrote them and from which source. */
export function renderDeskProseHTML(paragraphs, outletName = '') {
  if (!Array.isArray(paragraphs) || !paragraphs.length) return '';
  const label = outletName
    ? `Phòng báo Halcyon tóm tắt từ ${esc(outletName)}`
    : 'Phòng báo Halcyon tóm tắt từ bài gốc';
  return `
    <section class="story-keypoints-box story-prose-box" aria-label="Tóm tắt bài viết">
      <div class="story-section-head">
        <div>
          <p class="story-section-sub story-byline">${label}</p>
        </div>
      </div>
      <div class="story-prose">
        ${paragraphs.map(text => `<p class="story-prose-text">${summaryText(text)}</p>`).join('')}
      </div>
    </section>
  `;
}

/* Render Key Points block (Direction A) */
export function renderKeyPointsHTML(keyPoints, publisherName = '') {
  if (!Array.isArray(keyPoints) || !keyPoints.length) return '';
  const items = keyPoints.map((point, idx) => `
    <li class="story-point-item">
      <span class="story-point-num">${idx + 1}</span>
      <span class="story-point-text">${summaryText(point)}</span>
    </li>
  `).join('');

  const sub = publisherName
    ? `Tóm tắt bằng AI từ phần nội dung đọc được của ${esc(publisherName)}`
    : 'Tóm tắt bằng AI từ phần nội dung bài gốc đọc được';

  return `
    <section class="story-keypoints-box" aria-label="Tóm tắt bài viết">
      <div class="story-section-head">
        <div>
          <p class="story-section-sub story-byline">${sub}</p>
        </div>
      </div>
      <ol class="story-points-list">
        ${items}
      </ol>
      <p class="story-points-disclosure">Tóm tắt bằng AI từ nội dung nguồn; mở bài gốc để xem toàn bộ chi tiết và dẫn chứng.</p>
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
  /* A quiet closing line, not a card: the summary stays the main content and the exit reads as secondary. */
  return `
    <section class="story-origin-gateway" aria-label="Chuyển đến bài viết gốc">
      <p class="story-origin-desc">Toàn văn bài viết, với đầy đủ chi tiết và dẫn chứng, nằm trên ${esc(name)}.</p>
      <a class="story-origin-btn" href="${esc(safe(origUrl))}" target="_blank" rel="noopener noreferrer" id="story-open-origin-btn">
        <span>Mở bài viết gốc</span>
        <span class="story-cta-arrow" aria-hidden="true">↗</span>
      </a>
    </section>
  `;
}

/* Main render function used by both the Modal and the Static Story Page */
/* A social post used as a headline can run to several hundred characters. Measured on the live
   snapshot (10/10): median headline 70 characters, 90th percentile 122, 95th 214. Headlines up to
   100 characters keep the display size; longer ones step down so the summary stays on the first screen. */
export function headlineSizeClass(text) {
  const length = Array.from(String(text || '')).length;
  if (length > 180) return 'story-headline is-post';
  if (length > 100) return 'story-headline is-long';
  return 'story-headline';
}

export function renderStoryHTML(story, srcMap = new Map(), options = {}) {
  if (!story || !story.id) return '<p class="story-error-msg">Không tìm thấy bài viết.</p>';

  const { name } = getPublisherMeta(story, srcMap);
  const titleVi = storyTitle(story);
  const headlineClass = headlineSizeClass(titleVi);
  const hasOrig = !!(story.title_vi && story.title && story.title_vi.trim() !== story.title.trim());
  const face = faceOfStory(story, srcMap);
  const kindText = KIND[story.kind] || 'Bài viết';
  const hasKp = hasEditorialSummary(story);
  const isSaved = !!options.isSaved;
  const isModal = !!options.isModal;
  const isPage = !!options.isPage;
  const origUrl = story.url || (story.coverage && story.coverage[0] && story.coverage[0].url) || '#';

  // Media image block
  let mediaHTML = '';
  if (story.image && story.image.src) {
    const imageSrc = story.image.src.startsWith('assets/')
      ? new URL(story.image.src, import.meta.url).href : story.image.src;
    mediaHTML = `
      <figure class="story-media">
        <img class="story-media-img" src="${esc(imageSrc)}" alt="${esc(titleVi)}" loading="eager" decoding="async">
        <figcaption class="story-media-caption">
          <span>${story.image.via === 'ai' ? 'Ảnh minh hoạ do AI tạo' : 'Ảnh từ bài viết gốc'}</span>
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

        <h1 class="${headlineClass}" id="story-modal-title">${esc(titleVi)}</h1>

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
          <a class="story-origin-cta" href="${esc(safe(origUrl))}" target="_blank" rel="noopener noreferrer" title="Đọc bài gốc tại ${esc(name)}">
            <span class="story-cta-label">Đọc bài gốc tại ${esc(name)}</span>
            <span class="story-cta-arrow" aria-hidden="true">↗</span>
          </a>
        </div>
      </header>

      ${mediaHTML}

      <div class="story-body">
        ${renderEditorialSummaryHTML(story, name, srcMap)}
      </div>

      ${renderCoverageListHTML(story.coverage, srcMap)}

      ${(story.related_artifacts || []).length ? `<section class="story-coverage-wrap" aria-label="Tài nguyên liên quan">
        <h2>Tài nguyên liên quan</h2><ul class="story-coverage-list">${story.related_artifacts.map(a =>
          `<li><a href="${esc(safe(a.url))}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a></li>`).join('')}</ul>
      </section>` : ''}

      ${renderOriginGatewayHTML(story, srcMap)}

      ${footerHTML}
    </article>
  `;
}

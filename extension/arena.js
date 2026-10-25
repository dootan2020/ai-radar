import { esc } from './faces.js';

export const ARENA_CATEGORIES = { overall: 'Tổng', hard_prompts: 'Câu hỏi khó', non_english: 'Ngoài tiếng Anh' };
const dataset = 'https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset';
const licence = 'https://creativecommons.org/licenses/by/4.0/';
const number = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0, useGrouping: false });
const dateText = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value.split('-').reverse().join('/') : 'chưa có';
const words = { gpt: 'GPT', chatgpt: 'ChatGPT', chatglm: 'ChatGLM', codellama: 'CodeLlama',
  gpt4all: 'GPT4All', fastchat: 'FastChat', openchat: 'OpenChat', openhermes: 'OpenHermes',
  wizardlm: 'WizardLM', stablelm: 'StableLM', stripedhyena: 'StripedHyena', steerlm: 'SteerLM',
  deepseek: 'DeepSeek', glm: 'GLM', minimax: 'MiniMax', mimo: 'MiMo', longcat: 'LongCat',
  qwen: 'Qwen', qwq: 'QwQ', olmo: 'OLMo', smollm: 'SmolLM', internlm: 'InternLM',
  rwkv: 'RWKV', dbrx: 'DBRX', mpt: 'MPT', c4ai: 'C4AI', palm: 'PaLM',
  nvidia: 'NVIDIA', ibm: 'IBM', ai: 'AI', api: 'API', llm: 'LLM', lm: 'LM',
  oss: 'OSS', vl: 'VL', dpo: 'DPO', bf16: 'BF16', fp8: 'FP8', nvfp4: 'NVFP4',
  o1: 'o1', o3: 'o3', o4: 'o4' };
const makers = { openai: 'OpenAI', xai: 'xAI', zai: 'Z.ai', bytedance: 'ByteDance',
  deepseek: 'DeepSeek', minimax: 'MiniMax', nvidia: 'NVIDIA', ibm: 'IBM',
  allenai: 'AllenAI', stepfun: 'StepFun', 'ant-group': 'Ant Group', 'inception-ai': 'Inception AI' };
function readableWords(value) {
  // Numeric separators may encode versions or dates; leave unknown ones intact.
  return value.replace(/(?<!\d)-|-(?!\d)|-(?=\d+(?:\.\d+)?[bke](?:-|$))/gi, ' ').replace(/[A-Za-z0-9]+/g, word => {
    const key = word.toLowerCase();
    if (Object.hasOwn(words, key)) return words[key];
    if (/^a?\d+(?:x\d+)?[bke]$/i.test(word)) return word.toUpperCase();
    if (/^\d/.test(word)) return word;
    const family = /^(qwen|chatglm|smollm|internlm)(\d.*)$/i.exec(word);
    if (family) return words[family[1].toLowerCase()] + family[2];
    return word[0].toUpperCase() + word.slice(1);
  });
}
export function modelName(id) {
  let name = String(id);
  // Only these source families have a known hyphenated major/minor convention.
  name = name.replace(/^(claude-(?:(?:opus|sonnet|haiku)-)?)([34])-([1-9])(?=-|$)/i, '$1$2.$3')
    .replace(/^(grok-)4-1(?=-|$)/i, '$14.1')
    .replace(/^(claude-(?:opus|sonnet|haiku)-\d+(?:\.\d+)?)-(?=\d{8}(?:-|$))/i, '$1 ');
  let effort = '';
  // Product tiers such as Qwen Max and Mistral Medium are not reasoning effort.
  const effortFamily = [
    /^claude-(?:opus|sonnet|haiku|fable)-\d/i,
    /^gemini-\d[\d.]*-(?:flash|argon)-/i,
    /^gpt-\d[\d.]*(?:-(?:mini|nano|astra|sol|luna|terra))?-(?:xhigh|high|max|medium|low|minimal)$/i,
    /^(?:grok-\d|deepseek-v\d|glm-\d|kimi-k\d|muse-spark-\d|o[134]-mini-)/i,
  ].some(pattern => pattern.test(name));
  if (effortFamily) {
    name = name.replace(/\s*\((xhigh|high|max|medium|low|minimal)\)$/i, (_, level) => {
      effort = level.toLowerCase(); return '';
    });
    name = name.replace(/-(xhigh|high|max|medium|low|minimal)(?=-(?:\d+k|\d{8}|preview)$|$)/i, (_, level) => {
      effort = level.toLowerCase(); return '';
    });
  }
  return readableWords(name) + (effort ? ` (suy luận: ${effort})` : '');
}
export function makerName(maker) {
  const name = String(maker).trim();
  return name ? (Object.hasOwn(makers, name.toLowerCase()) ? makers[name.toLowerCase()] : readableWords(name)) : 'Chưa rõ hãng';
}
export const scoreText = score => number.format(score);

export function movement(row) {
  if (row.change_status === 'unlisted') return '<span class="arena-change">Chưa có hạng cũ</span>';
  if (row.change_status !== 'compared' || !Number.isInteger(row.rank_change)) return '<span class="arena-change">Chưa đủ dữ liệu</span>';
  const n = row.rank_change;
  if (!n) return '<span class="arena-change">— Giữ hạng</span>';
  return `<span class="arena-change ${n > 0 ? 'arena-up' : 'arena-down'}">${n > 0 ? '↑ Tăng' : '↓ Giảm'} ${Math.abs(n)}</span>`;
}

export function computeAxis(rows) {
  let minVal = Infinity;
  let maxVal = -Infinity;
  for (const row of rows) {
    const low = Number.isFinite(row?.rating_lower) ? row.rating_lower : row?.score;
    const high = Number.isFinite(row?.rating_upper) ? row.rating_upper : row?.score;
    if (Number.isFinite(low) && low < minVal) minVal = low;
    if (Number.isFinite(high) && high > maxVal) maxVal = high;
  }
  if (!Number.isFinite(minVal) || !Number.isFinite(maxVal)) {
    minVal = 1480;
    maxVal = 1540;
  }
  const STEP = 20;
  let floor = Math.floor(minVal / STEP) * STEP;
  let ceiling = Math.ceil(maxVal / STEP) * STEP;
  if (ceiling <= floor) ceiling = floor + STEP;
  const ticks = [];
  for (let t = floor; t <= ceiling; t += STEP) {
    ticks.push(t);
  }
  return { floor, ceiling, ticks };
}

export function formatCI(row) {
  if (!Number.isFinite(row?.rating_lower) || !Number.isFinite(row?.rating_upper)) return '';
  const low = row.rating_lower.toFixed(1);
  const high = row.rating_upper.toFixed(1);
  const margin = Math.round((row.rating_upper - row.rating_lower) / 2);
  return `CI 95%: ${low} – ${high} (±${margin})`;
}

function tableHTML(rows, category) {
  const { floor, ceiling, ticks } = computeAxis(rows);
  const rangeSpan = ceiling - floor;
  const rangeText = `${floor} – ${ceiling}`;

  return `<figure class="arena-card arena-chart" aria-labelledby="arena-title" aria-describedby="arena-comparison arena-note">
    <div class="arena-legend-strip">
      <div class="arena-legend-items">
        <span class="arena-legend-item">
          <span class="arena-legend-bar-icon" aria-hidden="true"></span>
          <span>Thanh điểm ước lượng</span>
        </span>
        <span class="arena-legend-item">
          <span class="arena-legend-ci-icon" aria-hidden="true">
            <svg width="24" height="12" viewBox="0 0 24 12" fill="none" aria-hidden="true">
              <line x1="1" y1="2" x2="1" y2="10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <line x1="1" y1="6" x2="23" y2="6" stroke="currentColor" stroke-width="1.5"/>
              <line x1="23" y1="2" x2="23" y2="10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="12" cy="6" r="2" fill="currentColor"/>
            </svg>
          </span>
          <span>Râu khoảng tin cậy 95% (CI)</span>
        </span>
      </div>
      <p class="arena-legend-note">Các mô hình có râu đè lên nhau nghĩa là chênh lệch nằm trong biên độ sai số.</p>
    </div>
    <table class="arena-table" aria-describedby="arena-comparison">
      <caption class="sr">10 mô hình dẫn đầu · ${esc(ARENA_CATEGORIES[category])}</caption>
      <thead>
        <tr>
          <th scope="col" class="arena-th-rank">Hạng</th>
          <th scope="col" class="arena-th-model">Mô hình / Hãng</th>
          <th scope="col" class="arena-th-plot">
            <div class="arena-axis-header">
              <span class="arena-axis-title">
                <span class="arena-title-full">Điểm Arena & <span class="arena-axis-ci-label">Khoảng tin cậy 95%</span></span>
                <span class="arena-title-short">Khoảng tin cậy 95%</span>
              </span>
              <span class="arena-axis-range">
                <span class="arena-range-full">Dải đo: ${rangeText}</span>
                <span class="arena-range-short">${rangeText}</span>
              </span>
            </div>
            <div class="arena-axis-ticks" aria-hidden="true">
              ${ticks.map((t, idx) => {
                const pct = (t - floor) / rangeSpan * 100;
                const alignClass = idx === 0 ? ' arena-tick-first' : idx === ticks.length - 1 ? ' arena-tick-last' : '';
                return `<span class="arena-axis-tick${alignClass}" style="left: ${pct}%">${t}</span>`;
              }).join('')}
            </div>
          </th>
          <th scope="col" class="arena-th-score">
            <span class="arena-score-full">Điểm Arena</span>
            <span class="arena-score-short">Điểm</span>
          </th>
          <th scope="col" class="arena-th-change">
            <span class="arena-change-full">So với tuần trước</span>
            <span class="arena-change-short">So tuần trước</span>
          </th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(row => {
          const isLeader = row.rank === 1;
          const scorePct = Math.max(0, Math.min(100, (row.score - floor) / rangeSpan * 100));
          const hasCI = Number.isFinite(row.rating_lower) && Number.isFinite(row.rating_upper);
          const low = hasCI ? row.rating_lower : row.score;
          const high = hasCI ? row.rating_upper : row.score;
          const lowPct = Math.max(0, Math.min(100, (low - floor) / rangeSpan * 100));
          const highPct = Math.max(0, Math.min(100, (high - floor) / rangeSpan * 100));
          const ciWidthPct = Math.max(0, highPct - lowPct);
          const ciText = formatCI(row);

          return `<tr class="arena-row${isLeader ? ' arena-leader' : ''}">
            <td class="arena-col-rank">
              <span class="arena-rank-num">${row.rank}</span>
            </td>
            <th scope="row" class="arena-col-model">
              <div class="arena-model-header">
                <div class="arena-model-left">
                  <span class="arena-rank-mobile">${row.rank}</span>
                  <span class="arena-model-name" title="${esc(row.id)}">${esc(modelName(row.id))}</span>
                </div>
                <span class="arena-score-mobile"><strong>${scoreText(row.score)}</strong></span>
              </div>
              <div class="arena-model-meta">
                <span class="arena-model-maker"><small>${esc(makerName(row.maker))}</small></span>
                <span class="arena-movement-mobile">${movement(row)}</span>
              </div>
            </th>
            <td class="arena-col-plot">
              <div class="arena-plot-track">
                <div class="arena-gridlines" aria-hidden="true">
                  ${ticks.map((t, idx) => {
                    const pct = (t - floor) / rangeSpan * 100;
                    const alignClass = idx === 0 ? ' arena-gridline-first' : idx === ticks.length - 1 ? ' arena-gridline-last' : '';
                    return `<span class="arena-gridline${alignClass}" style="left: ${pct}%"></span>`;
                  }).join('')}
                </div>
                <div class="arena-bar" style="width: ${scorePct}%" aria-hidden="true"></div>
                ${hasCI ? `<div class="arena-whisker" style="left: ${lowPct}%; width: ${ciWidthPct}%" aria-hidden="true">
                  <span class="arena-whisker-cap arena-cap-left"></span>
                  <span class="arena-whisker-stem"></span>
                  <span class="arena-whisker-cap arena-cap-right"></span>
                </div>` : ''}
                <div class="arena-dot" style="left: ${scorePct}%" aria-hidden="true"></div>
              </div>
              ${hasCI ? `<div class="arena-mobile-ci" aria-hidden="true">
                <span>${floor}</span>
                <span class="arena-mobile-ci-center">${ciText}</span>
                <span>${ceiling}</span>
              </div>` : ''}
            </td>
            <td class="arena-col-score">
              <strong>${scoreText(row.score)}</strong>
            </td>
            <td class="arena-col-change">
              ${movement(row)}
            </td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
  </figure>`;
}

export function arenaHTML(data, category = 'overall') {
  const rows = data?.categories?.[category];
  const valid = Array.isArray(rows) && rows.length === 10 && rows.every(row =>
    row && typeof row.id === 'string' && typeof row.maker === 'string' && Number.isInteger(row.rank) && row.rank > 0 && Number.isFinite(row.score));
  const source = `<a href="${dataset}" target="_blank" rel="noopener">Arena / LMArena</a>`;
  const intro = `<header class="arena-heading"><p class="arena-eyebrow">BẢNG XẾP HẠNG MÔ HÌNH</p><h2 id="arena-title">Ai đang dẫn đầu Arena?</h2><p>10 mô hình dẫn đầu theo bình chọn của người dùng Arena.</p></header>`;
  const attribution = `<p class="arena-credit">Nguồn: ${source} · <a href="${licence}" target="_blank" rel="noopener">CC BY 4.0</a>.<br>ai-radar lọc nhóm, trình bày tên mô hình, dịch nhãn và tính thay đổi hạng; giữ nguyên điểm và hạng từ nguồn.</p>`;
  if (!valid) return `${intro}<div class="arena-empty" role="status"><h3>Chưa tải được bảng xếp hạng</h3><p>Anh chị có thể tải lại hoặc xem dữ liệu tại ${source}.</p><button class="btn" type="button" data-arena-retry>Thử lại</button></div>${attribution}`;
  const tabs = Object.entries(ARENA_CATEGORIES).map(([id, label]) => `<button type="button" data-arena-category="${id}" aria-pressed="${id === category}">${label}</button>`).join('');
  const comparison = data.comparison_at ? `So với bản công bố ngày ${dateText(data.comparison_at)} (mốc tuần trước).` : 'Chưa có bản công bố phù hợp để so với tuần trước.';
  const status = data.fetch_status === 'failed' ? ' Lần kiểm tra gần nhất chưa thành công; đang giữ bản đã tải.' : '';
  const stale = data.stale ? ' Đây là bản đã công bố hơn 14 ngày trước.' : '';
  return `${intro}<p class="arena-date">Theo Arena, công bố ngày <strong>${dateText(data.published_at)}</strong>.${status}${stale}</p>
    <div class="arena-switch" role="group" aria-label="Nhóm xếp hạng Arena">${tabs}</div>
    <p class="arena-comparison" id="arena-comparison">${comparison}</p>
    ${tableHTML(rows, category)}
    <p class="arena-note" id="arena-note">Điểm cao hơn thể hiện được ưa thích hơn trong các lượt so sánh của Arena. Chênh lệch nhỏ có thể nằm trong sai số; thứ hạng không khẳng định mô hình tốt hơn cho mọi tác vụ.</p>${attribution}`;
}

export function createArenaView(root) {
  let data = null, category = 'overall', pending = null;
  const paint = () => { root.innerHTML = arenaHTML(data, category); };
  async function load() {
    if (pending) return pending;
    root.innerHTML = '<p class="arena-loading" role="status">Đang tải bảng xếp hạng Arena…</p>';
    pending = (async () => {
      try {
        const response = await fetch('data/arena.json', { signal: AbortSignal.timeout(12000) });
        if (!response.ok) throw new Error('Chưa tải được Arena');
        data = await response.json();
      } catch { data = null; }
      paint();
      pending = null;
    })();
    return pending;
  }
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-arena-category]');
    if (button && ARENA_CATEGORIES[button.dataset.arenaCategory]) {
      category = button.dataset.arenaCategory;
      paint();
      root.querySelector(`[data-arena-category="${category}"]`).focus({ preventScroll: true });
    }
    if (event.target.closest('[data-arena-retry]')) load();
  });
  return { show() { root.hidden = false; if (data) paint(); else load(); } };
}

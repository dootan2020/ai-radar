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
const gapNumber = new Intl.NumberFormat('vi-VN', { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false });
const makerStyles = { google: 'google', anthropic: 'anthropic', meta: 'meta', moonshot: 'moonshot', openai: 'openai' };
const makerStyle = maker => Object.hasOwn(makerStyles, maker.trim().toLowerCase()) ? makerStyles[maker.trim().toLowerCase()] : 'other';
export function makerInitial(maker) {
  const name = makerName(maker).trim();
  const lower = name.toLowerCase();
  if (lower === 'openai') return 'O';
  if (lower === 'anthropic') return 'A';
  if (lower === 'google') return 'G';
  if (lower === 'meta') return 'M';
  if (lower === 'moonshot') return 'M';
  if (lower === 'xai') return 'x';
  if (lower === 'deepseek') return 'D';
  if (lower === 'mistral') return 'M';
  if (lower === 'bytedance') return 'B';
  if (lower === 'alibaba' || lower === 'qwen') return 'Q';
  return (name[0] || '·').toUpperCase();
}
export function parseModelDisplay(id) {
  const full = modelName(id);
  const match = full.match(/^(.*?)(?:\s*\(suy luận:\s*([^)]+)\))?$/);
  if (!match) return { full, core: full, effort: '' };
  return { full, core: match[1].trim(), effort: match[2] ? match[2].trim() : '' };
}
function chartHTML(data, rows, category) {
  const highest = Math.max(...rows.map(row => row.score));
  const leaders = rows.filter(row => row.score === highest);
  const runnerUp = [...rows].sort((a, b) => b.score - a.score)[1];
  // Keep ten points below every score on one tight, shared absolute scale.
  const allScores = Object.keys(ARENA_CATEGORIES).flatMap(key => {
    const scores = Array.isArray(data.categories[key]) ? data.categories[key].map(row => row?.score) : [];
    return scores.length === 10 && scores.every(Number.isFinite) ? scores : [];
  });
  const floor = Math.floor(Math.min(...allScores) / 10) * 10 - 10;
  const ceiling = Math.max(floor + 20, Math.ceil(Math.max(...allScores) / 10) * 10);
  const midpoint = (floor + ceiling) / 2;
  const gap = gapNumber.format(highest - runnerUp.score);
  const legend = [...new Set(rows.map(row => row.maker))].map(maker => `<span class="arena-maker arena-maker-${makerStyle(maker)}"><span class="arena-mark" aria-hidden="true">${makerInitial(maker)}</span><small>${esc(makerName(maker))}</small></span>`).join('');
  return `<figure class="arena-chart" aria-labelledby="arena-chart-title" aria-describedby="arena-scale arena-note">
    <div class="arena-lead"><div class="arena-lead-main"><p class="arena-eyebrow">${leaders.length > 1 ? 'CÙNG ĐIỂM CAO NHẤT' : 'ĐIỂM CAO NHẤT'} · ${esc(ARENA_CATEGORIES[category])}</p><div class="arena-lead-title-row"><h3 id="arena-chart-title">${leaders.map(row => esc(modelName(row.id))).join(' · ')}</h3><span class="arena-lead-score-pill"><strong>${scoreText(highest)}</strong> điểm</span></div><p class="arena-lead-diff">${leaders.length > 1 ? 'Các mô hình dẫn đầu bằng điểm nhau.' : `Hơn mô hình kế tiếp <strong>${gap} điểm</strong>.`}</p></div></div>
    <div class="arena-chart-key"><span>Điểm Arena</span><div class="arena-legend" aria-label="Hãng phát triển">${legend}</div></div>
    <div class="arena-mobile-axis" aria-hidden="true"><span>${scoreText(floor)}</span><span>${scoreText(midpoint)}</span><span>${scoreText(ceiling)}</span></div>
    <ol class="arena-columns" role="list" aria-label="10 mô hình dẫn đầu, điểm Arena và thay đổi hạng so với tuần trước" aria-describedby="arena-comparison">
      ${rows.map(row => {
        const { full, core, effort } = parseModelDisplay(row.id);
        const effortPill = effort ? `<span class="arena-effort-tag">${esc(effort)}</span>` : '';
        return `<li class="arena-column arena-maker-${makerStyle(row.maker)}${row.score === highest ? ' arena-leader' : ''}" value="${row.rank}" tabindex="0" aria-label="${esc(full)}, Hạng ${row.rank}, ${scoreText(row.score)} điểm Arena, ${esc(makerName(row.maker))}, ${movement(row).replace(/<[^>]+>/g, '')}">
          <div class="arena-column-label">
            <div class="arena-model-block"><span class="arena-model" title="${esc(full)}">${esc(core)}</span>${effortPill}</div>
            <div class="arena-meta-line">
              <span class="arena-rank">#${row.rank}</span>
              <span class="arena-maker arena-maker-${makerStyle(row.maker)}" title="${esc(makerName(row.maker))}"><span class="arena-mark" aria-hidden="true">${makerInitial(row.maker)}</span><small>${esc(makerName(row.maker))}</small></span>
            </div>
          </div>
          <div class="arena-movement">${movement(row)}</div>
          <div class="arena-plot" style="--arena-bar-size:${(row.score - floor) / (ceiling - floor) * 100}%"><div class="arena-ticks" aria-hidden="true"><span>${scoreText(ceiling)}</span><span>${scoreText(midpoint)}</span><span>${scoreText(floor)}</span></div><div class="arena-bar" aria-hidden="true"></div><div class="arena-value"><strong class="arena-score"><span class="sr">Điểm Arena </span>${scoreText(row.score)}</strong></div></div>
          <div class="arena-tooltip" role="tooltip" aria-hidden="true">
            <div class="arena-tooltip-model">${esc(full)}</div>
            <div class="arena-tooltip-row">
              <span class="arena-tooltip-maker">${esc(makerName(row.maker))}</span>
              <span class="arena-tooltip-score"><strong>${scoreText(row.score)}</strong> điểm</span>
            </div>
            <div class="arena-tooltip-change">${movement(row)}</div>
          </div></li>`;
      }).join('')}
    </ol>
    <figcaption id="arena-scale" class="arena-scale-note"><strong>Trục điểm Arena: ${scoreText(floor)}–${scoreText(ceiling)}, dùng chung cho cả ba nhóm.</strong> ${floor === 0 ? 'Trục bắt đầu từ 0.' : 'Trục không bắt đầu từ 0; độ dài thanh không biểu thị tỷ lệ năng lực.'} Điểm hiển thị được làm tròn; biểu đồ và chênh lệch dùng điểm gốc.</figcaption>
  </figure>`;
}
export function movement(row) {
  if (row.change_status === 'unlisted') return '<span class="arena-change">Chưa có hạng cũ</span>';
  if (row.change_status !== 'compared' || !Number.isInteger(row.rank_change)) return '<span class="arena-change">Chưa đủ dữ liệu</span>';
  const n = row.rank_change;
  if (!n) return '<span class="arena-change">— Giữ hạng</span>';
  return `<span class="arena-change ${n > 0 ? 'arena-up' : 'arena-down'}">${n > 0 ? '↑ Tăng' : '↓ Giảm'} ${Math.abs(n)}</span>`;
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
    ${chartHTML(data, rows, category)}
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

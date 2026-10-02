/* ai·radar · token and component showcase (tokens.html).
   Components are built with the same faces.js pieces and the same class names the page ships, from data/radar.json.
   Forced states: every :hover / :focus-visible / :active rule in styles.css is copied to .is-hover / .is-focus /
   .is-active, so a state shown here is the page's own rule, never a showcase copy that could drift. */
import { esc, fmt, avatar, avatarStack, faceOfStory, faceOfSource, faceOfRepo, hydrateHF, watchImageErrors, hourHistogram, ring, meter } from './faces.js';
import { gcalURL } from './calendar.js';
import { KIND } from './words.js';

const $ = s => document.querySelector(s);
const icon = id => `<svg class="i" aria-hidden="true"><use href="#${id}"/></svg>`;
const css = (el, p) => getComputedStyle(el).getPropertyValue(p).trim();

/* ---------- theme toggle, same storage key as the page ---------- */
function applyTheme(t){
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  $('#theme').setAttribute('aria-pressed', String(dark));
}
let theme = null; try { theme = JSON.parse(localStorage.getItem('air2:theme')); } catch { /* storage blocked */ }
applyTheme(theme);
$('#theme').addEventListener('click', () => {
  const dark = $('#theme').getAttribute('aria-pressed') === 'true';
  theme = dark ? 'light' : 'dark'; applyTheme(theme);
  try { localStorage.setItem('air2:theme', JSON.stringify(theme)); } catch { /* memory only */ }
});

/* ---------- forced states ---------- */
function forceStates(){
  const out = [];
  const walk = (rules, wrap) => { for (const r of rules) {
    if (r.cssRules && !(r instanceof CSSStyleRule)) { const head = r instanceof CSSMediaRule ? `@media ${r.conditionText}` : null; walk(r.cssRules, head || wrap); continue; }
    if (!(r instanceof CSSStyleRule) || !/:(hover|focus-visible|active)/.test(r.selectorText)) continue;
    const sel = r.selectorText.replace(/:hover/g, '.is-hover').replace(/:focus-visible/g, '.is-focus').replace(/:active/g, '.is-active');
    const rule = `${sel}{${r.style.cssText}}`;
    out.push(wrap && !/hover: hover/.test(wrap) ? `${wrap}{${rule}}` : rule);
  } };
  for (const sh of document.styleSheets) { try { if (sh.href && !sh.href.startsWith(location.origin)) continue; walk(sh.cssRules, null); } catch { /* cross-origin sheet */ } }
  const st = document.createElement('style'); st.textContent = `@layer components{${out.join('\n')}}`; document.head.append(st);
  return out.length;
}

/* ---------- colour maths: OKLCH -> sRGB -> WCAG contrast, measured from the rendered value ---------- */
function oklchToRgb(L, C, H){
  const h = H * Math.PI / 180, a = C * Math.cos(h), b = C * Math.sin(h);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s]
    .map(v => Math.min(1, Math.max(0, v)));           // linear sRGB
}
function parseColor(str){
  let m = /oklch\(([\d.]+)%?\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+%?))?\)/.exec(str);
  if (m) { const L = str.includes('%') && +m[1] > 1 ? m[1] / 100 : +m[1]; return {lin: oklchToRgb(L, +m[2], +m[3]), a: m[4] ? parseFloat(m[4]) / (m[4].endsWith('%') ? 100 : 1) : 1}; }
  m = /rgba?\(([\d.]+),?\s*([\d.]+),?\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\)/.exec(str);
  if (m) { const lin = [m[1], m[2], m[3]].map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return {lin, a: m[4] ? +m[4] : 1}; }
  return null;
}
const lum = lin => 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
const toSrgb = v => v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
const toLin = v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
/* Translucent colours are composited over their background in sRGB space, as the browser paints them. */
function over(fg, bg){ if (fg.a >= 1) return fg.lin; return fg.lin.map((v, i) => toLin(toSrgb(v) * fg.a + toSrgb(bg.lin[i]) * (1 - fg.a))); }
export function contrast(fgStr, bgStr){
  const fg = parseColor(fgStr), bg = parseColor(bgStr); if (!fg || !bg) return null;
  const a = lum(over(fg, bg)), b = lum(bg.lin);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
const probe = (host, prop, value) => { const el = document.createElement('span'); el.style.setProperty(prop, value); host.append(el); const v = getComputedStyle(el)[prop === 'color' ? 'color' : 'backgroundColor']; el.remove(); return v; };

const SWATCHES = [
  ['--color-canvas', 'nền trang'], ['--color-surface', 'nền ô'], ['--color-inset', 'mảng trong ô'], ['--color-fill', 'nút chọn, rãnh đo'], ['--color-hair', 'đường mảnh'],
  ['--color-ink', 'chữ chính', 'text'], ['--color-ink-2', 'chữ phụ', 'text'], ['--color-ink-3', 'chữ mờ, giờ', 'text'],
  ['--color-accent', 'hành động, chọn', 'text'], ['--color-live', 'đang phát, nóng', 'text'], ['--color-ok', 'Dùng ngay', 'text'], ['--color-warn', 'Xào nấu được, giấy phép', 'text'],
  ['--color-accent-wash', 'nền đang chọn'], ['--color-live-wash', 'nền nhãn nóng'], ['--color-ok-wash', 'nền nhãn Dùng ngay'], ['--color-warn-wash', 'nền nhãn Xào nấu'],
];
function swatches(host){
  const surf = probe(host, 'background-color', 'var(--color-surface)');
  host.insertAdjacentHTML('beforeend', SWATCHES.map(([t, role, kind]) => {
    const val = probe(host, kind ? 'color' : 'background-color', `var(${t})`);
    const cr = kind ? contrast(val, surf) : null;
    return `<div class="sw" data-token="${t}"><i style="background:var(${t})"></i><span><code>${t}</code> · ${role}<br><code>${esc(css(host, t))}</code></span>${cr ? `<span class="cr" title="trên nền ô">${cr.toFixed(2)}:1</span>` : '<span></span>'}</div>`;
  }).join(''));
}

function typeScale(){
  const rows = [['--num-hero', 'Số keynote của ô chính', '353', true], ['--num-xl', 'Số lớn', '274.481', true], ['--num-lg', 'Số đếm ngược', '14', true], ['--num-md', 'Số đầu chương', '47', true],
    ['--text-lead', 'Tiêu đề chuyện chính', 'Đường ống dữ liệu mới, rõ ràng hơn'], ['--text-feature', 'Tiêu đề chương, tờ chi tiết', 'Tiếng nói chuyên gia'], ['--text-tile', 'Tiêu đề ô', 'Đang phát và sắp tới'],
    ['--text-title', 'Tóm tắt', 'Mỗi sáng, ba phút, biết điều chính.'], ['--text-body', 'Chữ đọc', 'Người làm AI đọc tin ở đây mỗi sáng.'], ['--text-small', 'Hàng tin', 'Nóng vì Hacker News 353 điểm'],
    ['--text-meta', 'Siêu dữ liệu', 'Hacker News · Thảo luận · 13 giờ trước'], ['--text-micro', 'Nhãn nhỏ', 'Dùng ngay · Xào nấu được']];
  $('#type-scale').innerHTML = rows.map(([t, role, sample, n]) => `<div class="ts"><span><code>${t}</code><br><code>${esc(css(document.documentElement, t))}</code><br><span class="aside">${role}</span></span>
    <span style="font-size:var(${t});font-weight:${n ? 700 : t === '--text-body' || t === '--text-meta' ? 400 : 600};letter-spacing:${n ? 'var(--tracking-number)' : 'normal'};line-height:${n ? 1 : 1.3}" class="${n ? 'num' : ''}">${sample}</span></div>`).join('')
    + `<p class="aside" style="margin-top:var(--space-16)">Dấu tiếng Việt chồng tầng: ế ộ ữ ặ ẫ ỡ Ừ Ỷ Đ đ. Chữ to nhất: <span style="font-size:var(--size-56);font-weight:700;letter-spacing:var(--tracking-number)">Ỗ ừ ậ</span></p>`;
}
function spaceScale(){
  const sp = [4, 8, 12, 16, 24, 32, 48, 64, 96];
  $('#space-scale').innerHTML = `<header class="tile-h"><h2>Khoảng cách, bước 4</h2></header>` + sp.map(n => `<div class="sp"><code style="width:96px">--space-${n}</code><i style="width:var(--space-${n})"></i><code>${n}px</code></div>`).join('')
    + `<div class="sp"><code style="width:96px">--grid-gap</code><span>${css(document.documentElement, '--grid-gap')}</span></div><div class="sp"><code style="width:96px">--tile-pad</code><span><code>${css(document.documentElement, '--tile-pad')}</code> · ô chính <code>${css(document.documentElement, '--tile-pad-hero')}</code></span></div>`;
  $('#radius-scale').innerHTML = `<header class="tile-h"><h2>Bo góc</h2></header><div class="tk-row">${['--radius-8', '--radius-12', '--radius-24', '--radius-full', '--av-radius'].map(t => `<div class="tk-cell"><span class="rd" style="border-radius:var(${t})"></span><code>${t}</code></div>`).join('')}</div>
    <p class="aside">Ô bo <code>24px</code>, mảng bên trong <code>12px</code> (24 trừ khoảng lõm), logo là hình vuông bo cong 28%.</p>`;
  $('#shadow-scale').innerHTML = `<header class="tile-h"><h2>Độ sâu</h2></header><p class="aside">Một cách duy nhất: ô sáng hơn nền. Bóng chỉ xuất hiện khi ô được nâng (lúc rê chuột) và ở tờ chi tiết.</p>
    <div class="tk-row"><div class="tk-cell"><span class="rd" style="background:var(--color-surface);box-shadow:none;border-radius:var(--radius-12)"></span><code>đứng yên</code></div>
    <div class="tk-cell"><span class="rd" style="background:var(--color-surface);box-shadow:var(--shadow-lift);border-radius:var(--radius-12)"></span><code>--shadow-lift</code></div>
    <div class="tk-cell"><span class="rd" style="background:var(--color-surface);box-shadow:var(--shadow-sheet);border-radius:var(--radius-12)"></span><code>--shadow-sheet</code></div></div>`;
}
function motionScale(){
  const r = document.documentElement;
  const d = [['--motion-feedback', 'nhấn, bật tắt; giữ lại khi giảm chuyển động'], ['--motion-state', 'rê chuột, đóng tờ chi tiết'], ['--motion-arrive', 'ô mới, tin mới trượt vào'], ['--motion-open', 'mở tờ chi tiết'], ['--motion-count', 'số chạy, vòng điểm vẽ']];
  $('#motion-scale').innerHTML = d.map(([t, role]) => `<div class="mo"><code style="width:160px">${t}</code><b class="num" style="width:56px">${css(r, t)}</b><span class="mo-track"><span class="mo-dot" style="animation-duration:calc(var(${t}) * 4);animation-timing-function:var(--ease-flow)"></span></span><span class="aside" style="width:260px">${role}</span></div>`).join('')
    + ['--ease-flow', '--ease-press', '--ease-exit'].map(t => `<div class="mo"><code style="width:160px">${t}</code><code>${css(r, t)}</code></div>`).join('');
}

/* ---------- components, from real data ---------- */
const state = (label, html) => `<div class="tk-cell"><div>${html}</div><span class="tk-cap">${label}</span></div>`;
function components(D){
  const SRC = new Map(D.sources.map(s => [s.id, s]));
  const S = new Map(D.stories.map(s => [s.id, s]));
  const hot = (D.sections.hot || []).map(id => S.get(id)).filter(Boolean);
  const repo = (D.repos || [])[0];
  const ev = (D.events || [])[0];
  const st = hot[0] || D.stories[0];
  const face = faceOfStory(st, SRC);
  const cmd = (D.repos || []).map(r => (/cài:\s*`([^`]+)`/.exec(r.why || '') || [])[1]).find(Boolean);
  const g = ev ? gcalURL({title: ev.title, url: ev.url, location: ev.location, startDate: ev.start_date, endDate: ev.end_date}) : null;
  const rowHTML = (s, cls = '', pressed = false) => `<button class="row c${cls}" aria-pressed="${pressed}">${avatar(faceOfStory(s, SRC), 'sm')}<span class="row-m"><span class="t">${cls.includes('new') ? '<span class="new-mark"></span>' : ''}${cls.includes('saved') ? `<span class="saved-mark">${icon('i-save')}</span>` : ''}${esc(s.title)}</span><span class="k"><span class="pub">${esc((SRC.get(((s.coverage || [])[0] || {}).source) || {}).name || '')}</span> · ${esc(KIND[s.kind] || s.kind)}</span></span><span class="r">${s.hot_score != null ? `điểm ${Math.round(s.hot_score)}` : ''}</span></button>`;
  const btn = (cls, txt, ic) => `<button class="btn ${cls}" tabindex="-1">${txt}${ic ? icon(ic) : ''}</button>`;
  const blocks = [
    ['Nút chính', ['mặc định', 'rê chuột', 'tiêu điểm', 'nhấn', 'đang tải', 'tắt'].map((l, i) => state(l, btn(`primary ${['', 'is-hover', 'is-focus', 'is-active', 'is-loading', ''][i]}`, 'Mở thảo luận', 'i-out').replace('<button', i === 5 ? '<button disabled' : '<button')))],
    ['Nút phụ và nút biểu tượng', ['mặc định', 'rê chuột', 'tiêu điểm', 'nhấn', 'đã lưu (bật)'].map((l, i) => state(l, i < 4 ? btn(`second ${['', 'is-hover', 'is-focus', 'is-active'][i]}`, 'Bài gốc', 'i-out') : `<button class="btn icon-only" aria-pressed="true" tabindex="-1">${icon('i-save')}</button>`))],
    ['Nút chữ và liên kết', ['mặc định', 'rê chuột', 'tiêu điểm', 'tắt'].map((l, i) => state(l, `<button class="btn-quiet ${['', 'is-hover', 'is-focus', ''][i]}" ${i === 3 ? 'disabled' : ''} tabindex="-1">${i === 3 ? 'Đã xem hết' : 'Đánh dấu đã xem'}</button>`)).concat([state('liên kết, rê chuột','<a class="link is-hover">Xem đủ 19</a>')])],
    ['Thêm vào lịch (Google Calendar + .ics)', g ? ['mặc định', 'rê chuột vào Google', 'tiêu điểm vào .ics', 'nhấn'].map((l, i) => state(l, `<span class="calbtn"><a class="calbtn-g ${i === 1 ? 'is-hover' : ''} ${i === 3 ? 'is-active' : ''}" href="${esc(g)}" target="_blank" rel="noopener" tabindex="-1">${icon('i-cal')}<span>Google Calendar</span></a><button class="calbtn-ics ${i === 2 ? 'is-focus' : ''}" tabindex="-1">.ics</button></span>`)) : [state('dữ liệu chưa có sự kiện', '<p class="empty-note">Chưa có sự kiện</p>')]],
    ['Chép lệnh cài', cmd ? ['mặc định', 'rê chuột', 'đã chép'].map((l, i) => state(l, `<span class="cmd" style="width:300px"><code>${esc(cmd)}</code><button class="cmd-copy ${['', 'is-hover', 'is-done'][i]}" tabindex="-1">${icon('i-copy')}${icon('i-check')}<span class="cmd-l">${i === 2 ? 'Đã chép' : 'Chép'}</span></button></span>`)) : [state('kho mã này không có lệnh cài', '')]],
    ['Nút chọn mảng', ['tắt', 'rê chuột', 'tiêu điểm', 'bật'].map((l, i) => state(l, `<button class="chip ${['', 'is-hover', 'is-focus', ''][i]}" aria-pressed="${i === 3}" tabindex="-1">${icon('i-check')}Tác tử lập trình <span class="n num">13</span></button>`))],
    ['Nhãn kho mã và cờ giấy phép', [state('Dùng ngay', '<span class="lab dung-ngay">Dùng ngay</span>'), state('Xào nấu được', '<span class="lab xao-nau">Xào nấu được</span>'), state('Nghiên cứu', '<span class="lab nghien-cuu">Nghiên cứu</span>'), state('cờ giấy phép', `<span class="lic">${icon('i-warn')}giấy phép riêng, đọc trước khi dùng thương mại</span>`), state('nhãn nóng', `<span class="pill pill-hot">${icon('i-flame')}Nóng nhất lúc này</span>`)]],
    ['Logo nguồn', [state('logo GitHub, cỡ lớn nhất', avatar(face, 'xl')), state('kho mã, cỡ lớn', repo ? avatar(faceOfRepo(repo), 'lg') : ''), state('nguồn, cỡ vừa',avatar(faceOfSource((st.coverage || [])[0], SRC), 'md')), state('chữ lồng (không có logo xác minh)', avatar({kind:'mono', id:'TC', label:'TechCrunch AI'}, 'md')), state('ảnh lỗi: rơi về chữ lồng', `<span class="av av-md is-fallback" data-mono="HN" style="--mono-h:30"></span>`), state('chồng nhiều nguồn', avatarStack(D.sources.slice(1, 4).map(s => faceOfSource({source:s.id, lab:s.lab, publisher:s.publisher}, SRC)), 'sm')), state('cỡ nhỏ nhất và cỡ nhỏ', avatar(face, 'xs') + ' ' + avatar(face, 'sm'))]],
    ['Số đo', [state('vòng điểm nóng', ring(st.hot_score ?? 0, 'Điểm nóng')), state('thước so với hạng 1', `<span style="display:block;width:160px">${meter(hot[3] ? hot[3].hot_score : 0, hot[0] ? hot[0].hot_score : 1)}</span>`), state('tin theo giờ, 24 giờ', `<span style="display:block;width:260px">${hourHistogram(D.stories, D.generated_at)}</span>`), state('số keynote', `<p class="keynote k-md"><b class="num">${fmt(repo ? repo.stars : 0)}</b><span>sao trên GitHub</span></p>`)]],
    ['Hàng tin', [state('mặc định', rowHTML(st)), state('rê chuột', rowHTML(st, ' is-hover')), state('tiêu điểm', rowHTML(st, ' is-focus')), state('đang mở (chọn)', rowHTML(st, '', true)), state('đã đọc', rowHTML(st, ' is-read')), state('mới · đã lưu', rowHTML(hot[1] || st, ' new saved'))]],
    ['Trạng thái phát', [state('đang phát', '<span class="state on"><span class="pulse on"></span>Đang phát</span>'), state('không có buổi nào', '<span class="state"><span class="pulse"></span>Không có buổi nào đang phát</span>'), state('ngày', '<span class="datebadge"><b>16</b><span>th 10</span></span>'), state('nguồn chạy / lỗi', '<span class="dots"><i class="ok"></i><i class="ok"></i><i class="warn"></i></span>')]],
    ['Chuyển giao diện, tin mới, thông báo', [state('nền sáng', `<button class="theme" aria-pressed="false" tabindex="-1">${icon('i-sun').replace('class="i"', 'class="i i-sun"')}${icon('i-moon').replace('class="i"', 'class="i i-moon"')}</button>`), state('nền tối', `<button class="theme" aria-pressed="true" tabindex="-1">${icon('i-sun').replace('class="i"', 'class="i i-sun"')}${icon('i-moon').replace('class="i"', 'class="i i-moon"')}</button>`), state('nút tin mới', `<button class="fresh-btn" tabindex="-1">${icon('i-up')}<span><span class="num">12</span> tin mới</span> · Xem</button>`), state('thông báo', '<span class="toast" style="position:static;transform:none"><span>Đã chép lệnh cài</span></span>'), state('khung xương khi tải', '<div style="width:220px;display:flex;flex-direction:column;gap:8px"><div class="sk sk-line"></div><div class="sk sk-row"></div></div>'), state('trống', '<p class="empty-note">Chưa có dữ liệu cho mục này. Trang không điền tin mẫu.</p>')]],
  ];
  $('#comp').innerHTML = blocks.map(([h, cells]) => `<div class="tile"><header class="tile-h"><h2>${h}</h2></header><div class="tk-row">${cells.join('')}</div></div>`).join('');

  /* Three real tiles at once: a story, a repo, an event, each with logo, number and label. */
  const n = ev ? Math.round((Date.UTC(...ev.start_date.split('-').map((v, i) => i === 1 ? v - 1 : +v)) - Date.now()) / 864e5) : null;
  $('#tiles').innerHTML = `
    <article class="tile"><div class="lead-top">${avatar(face, 'lg')}<p class="lead-label"><span class="pill pill-hot">${icon('i-flame')}Nóng</span><span class="lead-src">${esc((SRC.get(((st.coverage || [])[0] || {}).source) || {}).name || '')}</span></p></div>
      <p class="keynote k-md"><b class="num">${st.hot_signals && st.hot_signals.measurement ? fmt(st.hot_signals.measurement.value) : st.source_count}</b><span>${st.hot_signals && st.hot_signals.measurement ? 'điểm đo khi dựng bản tin' : 'nguồn'}</span></p><h3 class="tile-h" style="font-size:var(--text-tile)">${esc(st.title)}</h3></article>
    ${repo ? `<article class="tile"><div class="repo-hero">${avatar(faceOfRepo(repo), 'lg')}<span class="row-m"><span class="nm">${esc(repo.full_name)}</span><span class="lab ${esc(repo.label)}">${repo.label === 'dung-ngay' ? 'Dùng ngay' : repo.label === 'xao-nau' ? 'Xào nấu được' : 'Nghiên cứu'}</span></span></div><p class="keynote k-md"><b class="num">${fmt(repo.stars)}</b><span>${repo.source === 'hf' ? 'lượt thích' : 'sao'}</span></p></article>` : ''}
    ${ev ? `<article class="tile"><header class="tile-h"><h2>Sắp diễn ra</h2></header><div class="countdown"><p class="cd-n"><b class="num">${Math.max(0, n)}</b><span>ngày nữa</span></p><div class="cd-m"><span class="t">${esc(ev.title)}</span><span class="k">${esc(ev.location || '')}</span></div>
      <span class="calbtn"><a class="calbtn-g" href="${esc(g)}" target="_blank" rel="noopener">${icon('i-cal')}<span>Google Calendar</span></a><button class="calbtn-ics">.ics</button></span></div></article>` : ''}`;
  hydrateHF(document);
}

watchImageErrors();
typeScale(); spaceScale(); motionScale();
swatches($('#sw-light')); swatches($('#sw-dark'));
fetch('data/radar.json', {cache:'no-store'}).then(r => r.json()).then(D => { components(D); forceStates(); })
  .catch(e => { $('#comp').innerHTML = `<p class="empty-note">Không đọc được tệp <code>data/radar.json</code>. Trang trình bày không dùng dữ liệu mẫu.</p>`; forceStates(); });

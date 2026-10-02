/* ai·radar · renders data/radar.json (schema v2) into the approved "Bảng sáng" layout.
   Plain ES modules, no framework, no build. Every data string passes through esc(); every link through safe(). */
import { startLive } from './live.js';
import { canCalendar, downloadIcs } from './calendar.js';
import { streamedAge, scheduleText } from './time-text.js';

const TZ = 'Asia/Ho_Chi_Minh';
const KIND = {model:'Model',product:'Sản phẩm',research:'Nghiên cứu',other:'Bài viết',paper:'Paper',podcast:'Podcast',video:'Video',forum:'Thảo luận',event:'Sự kiện',repository:'Repo'};
const METRIC = {points:'điểm',comments:'bình luận',score:'điểm',upvotes:'upvote',likes:'lượt thích',downloads:'lượt tải',trendingScore:'điểm trending',trending_score:'điểm trending',stars_today:'sao hôm nay',stargazers_count:'sao',stars:'sao',forks:'fork'};
const CHAPTERS = [
  {id:'hom-nay', sec:'today', label:'Hôm nay', title:'Hôm nay', note:'Đăng trong 24 giờ qua, mới nhất trước.'},
  {id:'nong', sec:'hot', label:'Đang nóng', title:'Đang nóng', note:'Xếp theo điểm đo được trong 72 giờ.'},
  {id:'repo', sec:'repo', label:'Repo', title:'Repo đáng thử', note:'', wide:true},
  {id:'model', sec:'models', label:'Model', title:'Model mới', note:'Model mở và bài ra mắt model.'},
  {id:'paper', sec:'papers', label:'Paper', title:'Paper', note:'Paper được cộng đồng chọn đọc.'},
  {id:'nghe', sec:'listen', label:'Nghe và xem', title:'Nghe và xem', note:'Podcast, phỏng vấn, video.', wide:true},
  {id:'chuyen-gia', sec:'voices', label:'Chuyên gia', title:'Tiếng nói chuyên gia', note:'Blog nghiên cứu và bản tin.'},
  {id:'cong-dong', sec:'community', label:'Cộng đồng', title:'Cộng đồng đang bàn', note:'Hacker News, Lobsters và forum.'},
  {id:'sap-toi', sec:'upcoming', label:'Sắp tới', title:'Sắp diễn ra', note:'Hội nghị và sự kiện đã xác minh ngày.'},
];
/* The eight work areas chosen 02/10 (plans/261002-1630-ai-radar-v2/chot-chon-loc.md). */
const AREAS = [
  {id:'video', label:'Video và hình ảnh'}, {id:'agent-code', label:'Agent lập trình'}, {id:'quant', label:'Quant, tài chính'},
  {id:'local', label:'Chạy model trên máy'}, {id:'fine-tune', label:'Tinh chỉnh model'}, {id:'rag', label:'Dữ liệu cho RAG'},
  {id:'voice', label:'Giọng nói, âm thanh'}, {id:'browser-mcp', label:'Trình duyệt, MCP'},
];
const LABELS = {'dung-ngay':'Dùng ngay','xao-nau':'Xào nấu được','nghien-cuu':'Nghiên cứu'};
const SNAPSHOT_EVERY_MS = 180_000;

/* Same-origin JSON only; ?data=data/<file>.json lets a maintainer load another snapshot from site/data/. */
const qp = new URLSearchParams(location.search).get('data');
const DATA_URL = qp && /^data\/[\w.-]+\.json$/.test(qp) ? qp : 'data/radar.json';

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const nf = new Intl.NumberFormat('vi-VN');
const fmt = v => nf.format(Math.round(v));
const RM = matchMedia('(prefers-reduced-motion: reduce)');
const icon = (id, cls = 'i') => `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;

/* localStorage may be absent or throw (private mode, blocked cookies): fall back to memory for this tab. */
const mem = new Map();
let storageOk = true;
const store = {
  get(k, d){ try { const v = localStorage.getItem(k); return v == null ? (mem.has(k) ? mem.get(k) : d) : JSON.parse(v); } catch { storageOk = false; return mem.has(k) ? mem.get(k) : d; } },
  set(k, v){ mem.set(k, v); try { localStorage.setItem(k, JSON.stringify(v)); } catch { storageOk = false; } },
};

let D = null, S = new Map(), SRC = new Map(), R = new Map();
let lastSeen, firstVisit, selected = null, pending = null, liveState = null;
let arrived = new Set(), arriveIdx = 0;
const asArray = v => Array.isArray(v) ? v : [];
const read = new Set(asArray(store.get('air2:read', [])));
let saved = asArray(store.get('air2:saved', [])).filter(x => x && typeof x.key === 'string');
const areas = new Set(asArray(store.get('air2:areas', [])));
let withResearch = store.get('air2:research', false);

/* ---------- time ---------- */
const now = () => Date.now();
const hhmm = d => new Intl.DateTimeFormat('vi-VN',{hour:'2-digit',minute:'2-digit',timeZone:TZ}).format(d);
const dayKey = d => new Intl.DateTimeFormat('en-CA',{timeZone:TZ}).format(d);
function ago(iso){
  if (!iso) return 'không rõ thời gian';
  const d = new Date(iso), h = (now() - d) / 36e5;
  if (h < 0) return 'sắp tới';
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} phút trước`;
  if (h < 24) return `${Math.round(h)} giờ trước`;
  const days = Math.round((new Date(dayKey(new Date())) - new Date(dayKey(d))) / 864e5);
  if (days <= 1) return `Hôm qua, ${hhmm(d)}`;
  if (days < 7) return `${days} ngày trước`;
  return new Intl.DateTimeFormat('vi-VN',{day:'numeric',month:'numeric',year:'numeric',timeZone:TZ}).format(d);
}
/* Relative times stay honest while the tab is open: every <time data-ago> is refreshed each minute. */
const timeEl = iso => iso ? `<time datetime="${esc(iso)}" data-ago="${esc(iso)}">${esc(ago(iso))}</time>` : 'không rõ thời gian';
const exact = iso => iso ? new Intl.DateTimeFormat('vi-VN',{dateStyle:'medium',timeStyle:'short',timeZone:TZ}).format(new Date(iso)) : 'không rõ';
const dateOnly = ymd => { const [y,m,d] = ymd.split('-').map(Number); return {y,m,d}; };
const daysUntil = ymd => { const t = dateOnly(ymd); return Math.round((Date.UTC(t.y,t.m-1,t.d) - new Date(dayKey(new Date()) + 'T00:00:00Z')) / 864e5); };
/* ---------- data helpers ---------- */
const srcName = id => (SRC.get(id) || {}).name || id;
const pubOf = st => st.coverage && st.coverage[0] ? srcName(st.coverage[0].source) : '';
const kindName = st => KIND[st.kind] || esc(st.kind);
const viewsOf = id => (D.views && D.views.by_story && Number.isFinite(D.views.by_story[id])) ? D.views.by_story[id] : null;
const viewsEl = (n, id) => `<span class="views" title="Lượt xem trên ai-radar">${icon('i-eye')}<span class="num" data-views="${esc(id)}" data-v="${n}">${fmt(n)}</span><span class="sr"> lượt xem</span></span>`;
function metricsHTML(c){
  if (!c.metrics) return '';
  return Object.entries(c.metrics).filter(([,v]) => typeof v === 'number' && Number.isFinite(v))
    .map(([k,v]) => `<span class="lv num" data-live="${esc(c.id)}|${esc(k)}" data-v="${v}">${fmt(v)}</span> ${METRIC[k] || esc(k)}`).join(' · ');
}
/* hot_reason reads "hn-front: 236 điểm · đăng 6 giờ trước": show the publisher's name, and bind the measured
   number to its coverage item so the live layer can refresh it in place. */
function reasonHTML(st){
  if (!st.hot_reason) return '';
  let html = esc(st.hot_reason).replace(/([a-z0-9][a-z0-9-]*):\s*/g, (m, id) => SRC.has(id) ? `<b>${esc(srcName(id))}</b> ` : m);
  const ms = st.hot_signals && st.hot_signals.measurement;
  const cov = ms && (st.coverage || []).find(c => c.source === ms.source && c.metrics && ms.metric in c.metrics);
  if (cov) html = html.replace(/(<\/b> )(\d[\d.,]*)/, (m, a, n) => `${a}<span class="lv num" data-live="${esc(cov.id)}|${esc(ms.metric)}" data-v="${cov.metrics[ms.metric]}">${n}</span>`);
  return html;
}
function ytId(st){
  for (const c of st.coverage || []) {
    for (const md of c.media || []) { const m = /ytimg\.com\/vi\/([\w-]{6,})\//.exec(md.url); if (m) return m[1]; }
    const u = /[?&]v=([\w-]{6,})/.exec(c.url || ''); if (u && /youtube\.com/.test(c.url)) return u[1];
  }
  return null;
}
/* Only i.ytimg.com is allowed; feeds hand out i2/i3/i4 mirrors, so the same video id is rebuilt on i.ytimg.com. */
const thumbImg = (id, alt = '') => `<img src="https://i.ytimg.com/vi/${esc(id)}/hqdefault.jpg" alt="${esc(alt)}" loading="lazy" decoding="async" width="480" height="270">`;
const isNew = st => !!st.published_at && st.published_at > lastSeen && new Date(st.published_at) <= now();
const byNewest = (a, b) => (b.published_at || '').localeCompare(a.published_at || '');
const ids = sec => (D.sections[sec] || []).map(id => S.get(id)).filter(Boolean);
const eventOf = st => (D.events || []).find(e => e.url === st.url || e.title === st.title) || null;
const savedKey = k => saved.some(x => x.key === k);

/* Optional repos[]: shown only when the snapshot carries it; nothing is labelled by the page itself. */
function repoList(){
  if (!Array.isArray(D.repos)) return null;
  return D.repos.filter(r => r && r.id != null && r.full_name && LABELS[r.label]);
}
function repoPicks(list, opts = {}){
  return list.filter(r => (withResearch || opts.all || r.label !== 'nghien-cuu') && (!areas.size || areas.has(r.category)))
    .sort((a, b) => (a.label === b.label ? 0 : a.label === 'dung-ngay' ? -1 : b.label === 'dung-ngay' ? 1 : a.label === 'xao-nau' ? -1 : 1)
      || ((b.stars_gained_7d ?? -1) - (a.stars_gained_7d ?? -1)) || ((b.stars ?? 0) - (a.stars ?? 0)));
}

/* Calendar target for a story: a curated event (date-only stays all-day) or a verified upcoming stream with an exact start. */
function calOf(st){
  if (!st) return null;
  const e = eventOf(st);
  if (e) return {uid:e.id, title:e.title, url:e.url, location:e.location, startDate:e.start_date, endDate:e.end_date,
    startAt: e.time_precision === 'exact' ? e.start_at : null, endAt: e.time_precision === 'exact' ? e.end_at : null,
    note:`Ngày đã xác minh ${e.verified_at} từ ${e.source_url}`};
  const c = (st.coverage || []).find(c => c.status === 'upcoming' && c.start_at && c.time_precision !== 'relative');
  return c ? {uid:c.id, title:c.title, url:c.url, startAt:c.start_at, endAt:null, note:`Livestream của ${srcName(c.source)}`} : null;
}
const liveCal = v => v && v.status === 'upcoming' && v.start_at && v.time_precision !== 'relative'
  ? {uid:v.video_id, title:v.title, url:v.url, startAt:v.start_at, endAt:null, note:`Livestream của ${v.channel}`} : null;

function build(){
  S = new Map(); SRC = new Map(); R = new Map();
  D.stories.forEach(s => S.set(s.id, s));
  D.sources.forEach(s => SRC.set(s.id, s));
  (repoList() || []).forEach(r => R.set(String(r.id), r));
  const stored = store.get('air2:lastSeen', null);
  firstVisit = !stored;
  lastSeen = stored || new Date(new Date(D.generated_at) - 864e5).toISOString();
}

/* ---------- pieces ---------- */
const newMark = '<span class="new-mark" aria-hidden="true"></span><span class="sr">Mới. </span>';
const savedMark = `<span class="saved-mark" aria-hidden="true">${icon('i-save', '')}</span><span class="sr">Đã lưu. </span>`;
function arriveAttr(id){
  if (!arrived.has(id)) return '';
  return ` style="--i:${Math.min(arriveIdx++, 8)}"`;
}
function row(st, o = {}){
  const v = viewsOf(st.id);
  const right = o.right != null ? o.right : timeEl(st.published_at);
  return `<button class="row${o.compact ? ' c' : ''}${read.has(st.id) ? ' is-read' : ''}${arrived.has(st.id) ? ' arrive' : ''}"${arriveAttr(st.id)} data-sel="${esc(st.id)}" aria-pressed="${selected === st.id}">
    <span><span class="t">${savedKey(st.id) ? savedMark : ''}${isNew(st) ? newMark : ''}${esc(st.title)}</span>
    <span class="k"><span class="pub">${esc(pubOf(st))}</span> · ${kindName(st)}${st.source_count > 1 ? ` · <span class="num">${st.source_count}</span> nguồn` : ''}${v != null ? ` · ${viewsEl(v, st.id)}` : ''}</span></span>
    <span class="r">${right}</span></button>`;
}
function hotRow(st, i, max){
  const v = Math.max(0.02, (st.hot_score || 0) / max).toFixed(3);
  return `<button class="hrow${read.has(st.id) ? ' is-read' : ''}${arrived.has(st.id) ? ' arrive' : ''}"${arriveAttr(st.id)} data-sel="${esc(st.id)}" aria-pressed="${selected === st.id}">
    <span class="rk">${i + 1}</span>
    <span><span class="t">${savedKey(st.id) ? savedMark : ''}${esc(st.title)}</span>
      <span class="why">Nóng vì ${reasonHTML(st)}${st.source_count > 1 ? `, <b class="num">${st.source_count}</b> nguồn cùng đưa` : ''}</span>
      <span class="meter"><i style="--v:${v}" aria-hidden="true"></i><span class="num">${kindName(st)} · điểm ${Math.round(st.hot_score)}${viewsOf(st.id) != null ? ` · ${viewsEl(viewsOf(st.id), st.id)}` : ''}</span></span></span></button>`;
}
const labChip = l => `<span class="lab ${esc(l)}">${esc(LABELS[l] || l)}</span>`;
function repoStars(r){
  const unit = r.source === 'hf' ? 'lượt thích' : 'sao';
  const parts = [];
  if (Number.isFinite(r.stars)) parts.push(`<b class="num">${fmt(r.stars)}</b> ${unit}`);
  if (Number.isFinite(r.stars_gained_7d)) parts.push(`<span class="num">+${fmt(r.stars_gained_7d)}</span> tuần này`);
  return parts.join(' · ');
}
function repoRow(r, o = {}){
  const key = 'repo:' + r.id;
  const [own, ...rest] = String(r.full_name).split('/');
  const name = rest.length ? rest.join('/') : own;
  return `<button class="repo${o.compact ? ' c' : ''}${read.has(key) ? ' is-read' : ''}" data-repo="${esc(r.id)}" aria-pressed="${selected === key}">
    <span class="nm">${savedKey(key) ? savedMark : ''}${labChip(r.label)}${rest.length ? `<span class="own">${esc(own)}/</span>` : ''}${esc(name)}</span>
    <span class="st">${repoStars(r)}</span>
    <span class="why">${esc(r.why || r.description || '')}${r.license_flag ? ` · <span class="lic">${icon('i-warn')}${esc(r.license_flag)}</span>` : ''}</span></button>`;
}

/* ---------- the board ---------- */
const newtShown = () => matchMedia('(min-width: 1600px), (max-width: 1099px)').matches;
function pickLead(){
  const win = new Date(D.generated_at) - 72 * 36e5;
  const multi = D.stories.filter(s => s.source_count >= 2);
  const recent = multi.filter(s => s.published_at && new Date(s.published_at) >= win && new Date(s.published_at) <= now())
    .sort((a, b) => b.source_count - a.source_count || (b.hot_score || 0) - (a.hot_score || 0) || byNewest(a, b));
  if (recent.length) return {st: recent[0], mode:'multi', others: multi.filter(s => s !== recent[0]).sort(byNewest)};
  const hot = ids('hot');
  const st = hot[0] || ids('today')[0] || D.stories[0];
  return {st, mode:'single', others: multi.filter(s => s !== st).sort(byNewest)};
}

function renderBoard(){
  const board = $('#board');
  if (!D.stories.length) {
    board.innerHTML = `<div class="tile" style="padding:24px;grid-column:1/-1"><h2 style="margin:0 0 8px">Bản tin này chưa có tin nào</h2><p class="muted" style="margin:0">Dữ liệu tạo lúc ${esc(exact(D.generated_at))} không chứa tin. Trang không điền tin mẫu.</p></div>`;
    return;
  }
  arriveIdx = 0;
  const L = pickLead(), st = L.st;
  const hot = ids('hot'), max = hot.length ? hot[0].hot_score : 1;
  const newList = D.stories.filter(isNew).sort(byNewest);
  // 1920 gives "new" its own column, so the lead tile carries models and papers (item 3 of the product definition) that the
  // new column does not already show: each story appears in one place on the first screen.
  const newIds = new Set(newList.map(s => s.id));
  const modelsPapers = [...new Set([...ids('models'), ...ids('papers')])].filter(s => s !== st && !newIds.has(s.id)).sort(byNewest);
  const repos = repoList();
  const repoTop = repos ? repoPicks(repos).slice(0, newtShown() ? 3 : 2) : [];

  const cov = (st.coverage || []).map(c => `<li><span style="min-width:0"><span class="pub">${esc(srcName(c.source))}</span> <span class="tiny faint">· ${timeEl(c.published_at)}</span>
      ${c.title && c.title.trim() !== st.title.trim() ? `<a class="ttl" href="${esc(safe(c.url || c.discussion_url))}" target="_blank" rel="noopener">${esc(c.title)}</a>` : `<span class="ttl faint">cùng tiêu đề</span>`}</span>
      <span class="m">${metricsHTML(c) ? `${metricsHTML(c)}<br>` : ''}<a class="go" href="${esc(safe(c.discussion_url || c.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">${c.discussion_url ? 'Mở thảo luận' : 'Mở bài gốc'}</a></span></li>`).join('');

  const leadLabel = L.mode === 'multi' ? 'Nhiều nguồn cùng đưa nhất, 72 giờ qua' : 'Nóng nhất lúc này (chưa có chuyện nào nhiều nguồn trong 72 giờ)';
  const others = L.others.slice(0, 3);
  // "wide" = the separate new-items tile is on screen: from 1600px, and on stacked phone/tablet layouts below 1100px.
  const wide = newtShown();
  const fillList = wide ? modelsPapers : newList;
  const fillTitle = wide ? 'Model và paper mới' : (firstVisit ? 'Mới trong 24 giờ qua' : 'Mới từ lần bạn xem trước');
  const v = viewsOf(st.id);
  // Order inside the lead tile's list: below 1600 "new since last visit" comes first, because this tile is its only home there.
  // Older multi-source stories first used to take the room and leave a heading with no rows under it (the 140px gap of 02/10).
  const othersBlock = others.length ? `<div class="sub-h"><span>Các chuyện nhiều nguồn khác</span><span class="faint">${D.stories.filter(s => s.source_count >= 2).length} chuyện có từ 2 nguồn trở lên</span></div>
      ${others.map(o => row(o, {compact:true, right: `${o.source_count} nguồn · ${timeEl(o.published_at)}`})).join('')}` : '';
  const repoBlock = repoTop.length ? `<div class="sub-h"><span>Repo dùng được ngay</span><a class="faint" href="#repo">${areas.size ? 'theo mảng bạn chọn' : 'tất cả mảng'}</a></div>${repoTop.map(r => repoRow(r, {compact:true})).join('')}` : '';
  const fillBlock = `<div class="sub-h"><span>${fillTitle}</span><span class="faint num">${fillList.length} tin</span></div>
    ${fillList.map(s => row(s, {compact:true})).join('') || '<p class="empty-note">Không có tin nào mới từ lần bạn đánh dấu đã xem.</p>'}`;

  board.innerHTML = `
  <article class="tile lead" aria-labelledby="lead-h">
    <div class="lead-top">
      <div><p class="lead-label" id="lead-h">${leadLabel}</p>
        <button class="lead-title${read.has(st.id) ? ' is-read' : ''}" data-sel="${esc(st.id)}">${savedKey(st.id) ? savedMark : ''}${esc(st.title)}</button>
        ${st.summary ? `<p class="lead-sum">${esc(st.summary)}</p>` : `<p class="lead-sum small faint">Nguồn không kèm tóm tắt.</p>`}
        <p class="tiny faint" style="margin:6px 0 0">${kindName(st)} · ${timeEl(st.published_at)}${st.hot_reason ? ` · Nóng vì ${reasonHTML(st)}` : ''}${v != null ? ` · ${viewsEl(v, st.id)}` : ''}</p></div>
      <div class="count"><b data-count="${st.source_count}">${st.source_count}</b><span>nguồn<br>cùng đưa</span></div>
    </div>
    <ul class="cov" aria-label="Các nguồn đưa chuyện này">${cov}</ul>
    <div class="fit" data-fit>${wide ? othersBlock + repoBlock + fillBlock : repoBlock + fillBlock + othersBlock}</div>
    <div class="more-n" data-more><span></span><a class="link" href="${wide ? '#model' : '#hom-nay'}">Xem tất cả</a></div>
  </article>

  <section class="tile hot" aria-labelledby="hot-h">
    <div class="tile-h"><h2 id="hot-h">Đang nóng</h2><span class="aside">Điểm đo được, 72 giờ qua</span></div>
    ${hot.length ? `<div class="fit" data-fit data-fill-cap="16">${hot.slice(0, 5).map((s, i) => hotRow(s, i, max)).join('')}
      ${hot.length > 5 ? `<div class="sub-h"><span>Tiếp theo</span><span class="faint">${hot.length} tin có điểm</span></div>${hot.slice(5).map((s, i) => `<button class="crow${read.has(s.id) ? ' is-read' : ''}" data-sel="${esc(s.id)}" aria-pressed="${selected === s.id}"><span class="rk num faint" style="text-align:right">${i + 6}</span><span class="t">${esc(s.title)}</span><span class="s">${Math.round(s.hot_score)}</span></button>`).join('')}` : ''}</div>
    <div class="more-n" data-more><span></span><a class="link" href="#nong">Xem đủ ${hot.length}</a></div>` : '<p class="empty-note">Chưa có tin nào đủ số đo để xếp hạng.</p>'}
  </section>

  <section class="tile newt" id="moi" aria-labelledby="new-h">
    <div class="tile-h"><h2 id="new-h">${firstVisit ? 'Mới trong 24 giờ qua' : 'Mới từ lần trước'}</h2><span class="aside num">${newList.length} tin</span></div>
    <div class="fit" data-fit>${newList.map(s => row(s, {compact:true})).join('') || '<p class="empty-note">Không có tin nào mới từ lần bạn đánh dấu đã xem.</p>'}</div>
    <div class="more-n" data-more><span></span><a class="link" href="#hom-nay">Xem tất cả</a></div>
  </section>

  ${liveTile()}`;
  board.classList.remove('is-loading'); board.removeAttribute('aria-busy');
  fitAll();
  observeFit();
}

function liveTile(){
  // Live state comes from coverage status fields and the v1 live projection; nothing is assumed live without one.
  const liveNow = [], ended = [];
  D.stories.forEach(s => (s.coverage || []).forEach(c => { if (c.status === 'live') liveNow.push(s); if (c.status === 'ended') ended.push({s, c}); }));
  (D.live || []).forEach(v => { if (v.status === 'live' && !liveNow.length) liveNow.push({title:v.title, id:null, url:v.url}); });
  const upcomingStreams = (D.live || []).filter(v => v.status === 'upcoming');
  const upcoming = ids('upcoming');
  const vids = ids('listen').filter(s => s.kind === 'video' && ytId(s)).sort(byNewest);
  const lastEnded = ended.sort((a, b) => (b.c.end_at || '').localeCompare(a.c.end_at || ''))[0];
  const shownVid = vids.find(v => !lastEnded || v !== lastEnded.s);

  const nowCell = liveNow.length
    ? (liveNow[0].id
      ? `<button class="lcell" data-sel="${esc(liveNow[0].id)}"><span class="pulse on" aria-hidden="true"></span><span class="txt"><span class="lbl on">Đang phát</span><strong>${esc(liveNow[0].title)}</strong></span></button>`
      // A stream known only from the live projection has no story to open: the cell links straight to the broadcast.
      : `<a class="lcell has-go" href="${esc(safe(liveNow[0].url))}" target="_blank" rel="noopener"><span class="pulse on" aria-hidden="true"></span><span class="txt"><span class="lbl on">Đang phát</span><strong>${esc(liveNow[0].title)}</strong></span></a>`)
    : `<div class="lcell state-empty"><span class="pulse" aria-hidden="true"></span><span class="txt"><span class="lbl">Đang phát</span><strong>Không có buổi nào đang phát</strong><span class="sub">Kiểm lúc ${hhmm(new Date(D.generated_at))}. ${upcomingStreams.length ? '' : 'Chưa có lịch livestream sắp phát nào được xác minh.'}</span></span></div>`;
  const streamCells = upcomingStreams.slice(0, 1).map(v => {
    const cal = liveCal(v);
    return `<div class="lcell has-go">${cal ? `<button class="cal" data-cal-live="${esc(v.video_id)}" aria-label="Thêm ${esc(v.title)} vào lịch"><b>${icon('i-cal')}</b><span>Lịch</span><span class="plus">${icon('i-plus')}</span></button>` : ''}
      <span class="txt"><a class="go" href="${esc(safe(v.url))}" target="_blank" rel="noopener"><span class="lbl">Sắp phát · ${esc(v.channel)}</span><strong>${esc(v.title)}</strong></a><span class="sub">${v.start_at && v.time_precision !== 'relative' ? esc(exact(v.start_at)) : esc(scheduleText(v.time_text))}</span></span></div>`;
  }).join('');
  const evCells = upcoming.slice(0, 2).map(s => {
    const e = eventOf(s) || {};
    const sd = e.start_date ? dateOnly(e.start_date) : null, n = e.start_date ? daysUntil(e.start_date) : null;
    const cal = calOf(s);
    const badge = sd ? (cal
      ? `<button class="cal" data-cal="${esc(s.id)}" aria-label="Thêm ${esc(s.title)} vào lịch" title="Thêm vào lịch"><b>${sd.d}</b><span>th ${sd.m}</span><span class="plus">${icon('i-plus')}</span></button>`
      : `<span class="cal"><b>${sd.d}</b><span>th ${sd.m}</span></span>`) : '';
    return `<div class="lcell has-go">${badge}
      <span class="txt"><button class="go" data-sel="${esc(s.id)}"><span class="lbl">${n == null ? 'Sắp diễn ra' : n > 0 ? `Sắp diễn ra · còn <span class="num">${n}</span> ngày` : n === 0 ? 'Hôm nay' : 'Đang diễn ra'}</span><strong>${esc(s.title)}</strong></button><span class="sub">${esc(e.location || 'Chưa rõ địa điểm')}</span></span></div>`;
  }).join('') || `<div class="lcell state-empty"><span class="txt"><span class="lbl">Sắp diễn ra</span><strong>Chưa có sự kiện nào đã xác minh ngày</strong></span></div>`;
  const endCell = lastEnded ? (() => { const id = ytId(lastEnded.s);
    const when = lastEnded.c.end_at ? `Kết thúc ${timeEl(lastEnded.c.end_at)}` : esc(streamedAge(lastEnded.c.time_text) || 'Đã phát xong');
    return `<button class="lcell" data-sel="${esc(lastEnded.s.id)}">${id ? `<span class="thumb">${thumbImg(id)}</span>` : ''}<span class="txt"><span class="lbl">Vừa phát xong</span><strong>${esc(lastEnded.c.title)}</strong><span class="sub">${when}</span></span></button>`; })() : '';
  const vidCell = (vv, extra) => vv ? `<button class="lcell${extra ? ' extra5' : ''}" data-sel="${esc(vv.id)}"><span class="thumb">${thumbImg(ytId(vv))}</span><span class="txt"><span class="lbl">Video mới</span><strong>${esc(vv.title)}</strong><span class="sub">${esc(pubOf(vv))} · ${timeEl(vv.published_at)}</span></span></button>` : '';
  const vid2 = vids.filter(v => v !== shownVid && (!lastEnded || v !== lastEnded.s))[0];

  return `<section class="tile live" aria-labelledby="live-h">
    <div class="tile-h"><h2 id="live-h">Đang phát và sắp tới</h2><a class="link" href="#nghe">Nghe và xem</a></div>
    <div class="live-body">${nowCell}${streamCells}${evCells}${endCell}${vidCell(shownVid)}${vidCell(vid2, true)}</div></section>`;
}

/* Fit-to-height: lists in the first screen show only whole rows that fit, say how many more there are,
   then share the leftover height out as row padding so the tile ends flush, with no dead tail. */
function fitAll(){
  const desktop = matchMedia('(min-width: 1100px)').matches;
  $$('.extra5').forEach(el => el.style.display = matchMedia('(min-width: 1600px)').matches ? '' : 'none');
  $$('[data-fit]').forEach(box => {
    box.classList.remove('empty'); box.style.setProperty('--fill-pad', '0px');
    const lead = box.closest('.lead'); if (lead) lead.classList.remove('spread');
    const kids = [...box.children];
    kids.forEach(k => k.style.display = '');
    if (desktop) {
      const top = box.getBoundingClientRect().top, limit = box.clientHeight;
      let cut = false;
      kids.forEach(k => { if (cut || k.getBoundingClientRect().bottom - top > limit + 0.5) { cut = true; k.style.display = 'none'; } });
    } else {
      let n = 0;
      kids.forEach(k => { if (!k.classList.contains('sub-h') && ++n > 5) k.style.display = 'none'; });
    }
    // A heading with no visible rows under it goes too.
    kids.forEach((k, i) => {
      if (!k.classList.contains('sub-h') || k.style.display === 'none') return;
      const next = kids.slice(i + 1).find(x => x.style.display !== 'none');
      if (!next || next.classList.contains('sub-h')) k.style.display = 'none';
    });
    const rows = kids.filter(k => k.style.display !== 'none' && !k.classList.contains('sub-h') && !k.classList.contains('empty-note'));
    const hidden = kids.filter(k => k.style.display === 'none' && !k.classList.contains('sub-h')).length;
    const shown = kids.filter(k => k.style.display !== 'none');
    box.classList.toggle('empty', desktop && !shown.length);
    // No whole row fits (short laptop screens): the lead's remaining blocks share the height instead of leaving it at the bottom.
    if (lead) lead.classList.toggle('spread', desktop && !rows.length);
    if (desktop && rows.length && shown.length) {
      const top = box.getBoundingClientRect().top;
      const leftover = box.clientHeight - (shown[shown.length - 1].getBoundingClientRect().bottom - top);
      if (leftover > 1) box.style.setProperty('--fill-pad', `${Math.min(leftover / (rows.length * 2), Number(box.dataset.fillCap || 12)).toFixed(2)}px`);
    }
    const more = box.nextElementSibling && box.nextElementSibling.matches('[data-more]') ? box.nextElementSibling : null;
    if (more) more.querySelector('span').textContent = hidden ? `và ${nf.format(hidden)} tin nữa` : '';
  });
}

/* ---------- chapters below the fold ---------- */
function chapterList(c){
  if (c.sec === 'repo') return repoChapter();
  let list = ids(c.sec);
  if (c.sec !== 'hot' && c.sec !== 'upcoming') list = list.slice().sort(byNewest);
  if (!list.length) return `<p class="empty-note">Chưa có dữ liệu cho mục này. Trang không điền tin mẫu.</p>`;
  if (c.sec === 'listen') {
    const v = list.filter(s => ytId(s)).slice(0, 8), rest = list.filter(s => !ytId(s));
    return `<div class="vids">${v.map(s => `<button class="vid${read.has(s.id) ? ' is-read' : ''}" data-sel="${esc(s.id)}"><span class="thumb">${thumbImg(ytId(s), s.title)}</span><strong class="t">${esc(s.title)}</strong><span>${esc(pubOf(s))} · ${timeEl(s.published_at)}</span></button>`).join('')}</div>
      <div class="list" data-cap="6">${rest.map(s => row(s)).join('')}</div>`;
  }
  if (c.sec === 'upcoming') {
    return `<div class="list">${list.map(s => { const e = eventOf(s) || {}; const cal = calOf(s);
      const r = row(s, {right: e.start_date ? esc(e.start_date === e.end_date ? e.start_date : `${e.start_date} → ${e.end_date}`) : 'chưa rõ ngày'});
      return cal ? `<div class="row-tools">${r}<button class="cal-mini" data-cal="${esc(s.id)}" aria-label="Thêm ${esc(s.title)} vào lịch" title="Thêm vào lịch">${icon('i-cal')}</button></div>` : r; }).join('')}</div>`;
  }
  if (c.sec === 'hot') return `<div class="list" data-cap="8">${list.map(s => row(s, {right: `điểm ${Math.round(s.hot_score)}`})).join('')}</div>`;
  return `<div class="list" data-cap="8">${list.map(s => row(s)).join('')}</div>`;
}

function repoChapter(){
  const list = repoList();
  if (!list) {
    // No repos[] in this snapshot: list measured repositories as they are, without inventing labels.
    const reps = D.stories.filter(s => s.kind === 'repository' || (s.coverage || []).some(c => c.group === 'repository' && c.metrics && 'stars' in c.metrics))
      .map(s => ({s, n: Math.max(0, ...(s.coverage || []).map(c => (c.metrics && (c.metrics.stars_today ?? c.metrics.stars)) || 0))}))
      .filter(x => x.s.kind === 'repository').sort((a, b) => (b.s.hot_score || 0) - (a.s.hot_score || 0) || b.n - a.n).map(x => x.s);
    return `<p class="chips-note">Nhãn Dùng ngay, Xào nấu được, Nghiên cứu và 8 mảng sẽ hiện khi bản dữ liệu có phần chọn lọc repo. Bản này chưa có, nên dưới đây là repo xếp theo số đo, chưa gắn nhãn.</p>
      ${reps.length ? `<div class="list" data-cap="8">${reps.map(s => row(s, {right: repoMeasure(s)})).join('')}</div>` : '<p class="empty-note">Bản này không có repo nào.</p>'}`;
  }
  const count = id => list.filter(r => r.category === id && (withResearch || r.label !== 'nghien-cuu')).length;
  const research = list.filter(r => r.label === 'nghien-cuu').length;
  const shown = repoPicks(list);
  return `<div class="chips" role="group" aria-label="Chọn mảng bạn quan tâm">
      ${AREAS.map(a => `<button class="chip" data-area="${a.id}" aria-pressed="${areas.has(a.id)}">${esc(a.label)} <span class="n num">${count(a.id)}</span></button>`).join('')}
      ${research ? `<button class="chip" data-research aria-pressed="${withResearch}">Gồm cả Nghiên cứu <span class="n num">${research}</span></button>` : ''}
    </div>
    <p class="chips-note">${areas.size ? `Đang lọc ${areas.size} mảng, lưu trên máy này.` : 'Chưa chọn mảng nào, nên hiện tất cả.'} Mặc định chỉ hiện Dùng ngay và Xào nấu được.</p>
    ${shown.length ? `<div class="list" data-cap="10">${shown.map(r => repoRow(r)).join('')}</div>`
      : `<p class="empty-note">Hôm nay không có repo nào ở mảng đã chọn. <button class="btn-quiet" data-area-clear>Hiện mọi mảng</button></p>`}`;
}

/* Right-hand measure for an unlabelled repository: its own counters, never a guessed date. */
function repoMeasure(s){
  const c = (s.coverage || []).find(c => c.metrics && ('stars' in c.metrics || 'likes' in c.metrics));
  if (!c) return s.published_at ? timeEl(s.published_at) : '';
  const m = c.metrics, parts = [];
  if (Number.isFinite(m.stars)) parts.push(`${fmt(m.stars)} sao`); else if (Number.isFinite(m.likes)) parts.push(`${fmt(m.likes)} lượt thích`);
  if (Number.isFinite(m.stars_today)) parts.push(`+${fmt(m.stars_today)} hôm nay`);
  return `<span class="num">${parts.join(' · ')}</span>`;
}

function savedChapter(){
  if (!saved.length) return '';
  return `<section class="tile ch wide" id="da-luu" aria-labelledby="h-da-luu">
    <div class="tile-h"><h2 id="h-da-luu">Đã lưu</h2><span class="aside"><span class="num">${saved.length}</span> mục · chỉ lưu trên máy này</span></div>
    <div class="list">${saved.slice().reverse().map(x => {
      const st = S.get(x.key), rp = x.key.startsWith('repo:') ? R.get(x.key.slice(5)) : null;
      const body = st ? row(st) : rp ? repoRow(rp)
        : `<a class="row" href="${esc(safe(x.url))}" target="_blank" rel="noopener"><span><span class="t">${esc(x.title)}</span><span class="k">Không còn trong bản tin hiện tại · mở bài gốc</span></span><span class="r">${timeEl(x.at)}</span></a>`;
      return `<div class="row-tools">${body}<button class="cal-mini" data-unsave="${esc(x.key)}" aria-label="Bỏ lưu ${esc(x.title)}" title="Bỏ lưu">${icon('i-close')}</button></div>`;
    }).join('')}</div></section>`;
}

function liveRows(){
  if (!liveState) return '';
  return [...liveState.values()].map(s => `<div class="srow"><span class="dot ${s.ok === true ? 'ok' : s.ok === false ? 'warn' : ''}"></span>
    <span style="min-width:0"><a href="${esc(s.url)}" target="_blank" rel="noopener" style="font-weight:600">${esc(s.label)}</a>${s.error ? `<span class="err">${esc(s.error)}. Đang giữ số trong bản tin.</span>` : ''}</span>
    <span class="tiny faint">${s.at ? `${s.ok ? `${s.matched} tin khớp · ` : ''}${hhmm(s.at)}` : 'đang đọc'}</span></div>`).join('');
}

function renderChapters(){
  const bad = D.sources.filter(s => !s.ok);
  $('#chapters').innerHTML = `<h2 class="chap-title">Theo mục</h2>${savedChapter()}` + CHAPTERS.map(c => {
    const n = c.sec === 'repo' ? (repoList() ? repoList().length : D.stories.filter(s => s.kind === 'repository').length) : (D.sections[c.sec] || []).length;
    const note = c.sec === 'repo' ? (repoList() ? 'Chọn theo câu hỏi "lấy về dùng được không".' : 'Xếp theo số đo, chưa có nhãn.') : c.note;
    return `<section class="tile ch ${c.wide ? 'wide' : ''}" id="${c.id}" aria-labelledby="h-${c.id}">
      <div class="tile-h"><h2 id="h-${c.id}">${c.title}</h2><span class="aside"><span class="num">${n}</span> ${c.sec === 'repo' ? 'repo' : 'tin'} · ${note}</span></div>
      ${chapterList(c)}
    </section>`; }).join('') + `
    <section class="tile ch wide" id="nguon" aria-labelledby="h-nguon">
      <div class="tile-h"><h2 id="h-nguon">Nguồn</h2><span class="aside"><span class="num">${D.sources.length - bad.length}/${D.sources.length}</span> nguồn chạy được lúc ${hhmm(new Date(D.generated_at))}</span></div>
      <p class="src-sub">Đọc trực tiếp từ trình duyệt, mỗi 90 giây</p>
      <div class="srcgrid" id="live-rows">${liveRows()}</div>
      <p class="src-sub">Trong bản tin</p>
      <div class="srcgrid">${[...D.sources].sort((a, b) => a.ok - b.ok || b.count - a.count).map(s => `<div class="srow"><span class="dot ${s.ok ? 'ok' : 'warn'}"></span>
        <span style="min-width:0"><a href="${esc(safe(s.url))}" target="_blank" rel="noopener" style="font-weight:600">${esc(s.name)}</a>${s.error ? `<span class="err">${esc(s.error)}</span>` : ''}</span><span class="tiny faint num">${s.count} tin</span></div>`).join('')}</div>
    </section>`;
  // Long lists start capped and expand in place.
  $$('[data-cap]').forEach(l => {
    const cap = +l.dataset.cap, kids = [...l.children];
    if (kids.length <= cap) return;
    kids.slice(cap).forEach(k => k.hidden = true);
    const b = document.createElement('button'); b.className = 'btn-quiet expand'; b.textContent = `Xem thêm ${nf.format(kids.length - cap)}`;
    b.addEventListener('click', () => { kids.forEach((k, i) => { k.hidden = false; if (i >= cap && !RM.matches) { k.classList.add('arrive'); k.style.setProperty('--i', Math.min(i - cap, 8)); } }); b.remove(); });
    l.after(b);
  });
  const views = D.views && Number.isFinite(D.views.total) ? `Lượt xem trên ai-radar đo lúc ${esc(exact(D.views.measured_at))}, không dùng cookie. ` : '';
  $('#foot').innerHTML = `Dữ liệu tạo lúc ${esc(exact(D.generated_at))} giờ Việt Nam. ${D.ranking ? `Xếp hạng nóng: ${esc(D.ranking.method)}, cửa sổ ${esc(D.ranking.window_hours)} giờ, hiệu chỉnh: ${esc(D.ranking.calibration)}. Đây là cách xếp theo số đo, không phải phán xét tầm quan trọng.` : 'Bản dữ liệu này không mô tả cách xếp hạng nóng.'} Tiêu đề giữ nguyên tiếng Anh như bài gốc. ${views}
    ${storageOk ? 'Mốc đã xem, tin đã đọc, tin đã lưu và mảng bạn chọn chỉ lưu trên máy này.' : 'Trình duyệt đang chặn bộ nhớ cục bộ, nên mốc đã xem, tin đã lưu và mảng bạn chọn chỉ giữ tới khi đóng trang.'}
    <button id="keys-open">Phím tắt (?)</button>`;
}

/* ---------- chrome ---------- */
function navCounts(data){
  const seen = lastSeen, sm = new Map(data.stories.map(s => [s.id, s]));
  const fresh = st => !!st.published_at && st.published_at > seen && new Date(st.published_at) <= now();
  const per = {};
  CHAPTERS.forEach(c => { per[c.sec] = (data.sections[c.sec] || []).map(id => sm.get(id)).filter(s => s && fresh(s)).length; });
  return {total: data.stories.filter(fresh).length, per};
}
function renderNav(counts){
  $('#nav').innerHTML = (saved.length ? `<a href="#da-luu">Đã lưu <span class="n num">${saved.length}</span></a>` : '')
    + CHAPTERS.map(c => { const n = counts.per[c.sec] || 0; return `<a href="#${c.id}">${c.label}${n ? ` <span class="n num" aria-label="${n} mới">${n}</span>` : ''}</a>`; }).join('');
  spy();
}
function renderChrome(){
  const counts = navCounts(D);
  const g = new Date(D.generated_at);
  $('#when-line').innerHTML = `<span class="wd">${esc(new Intl.DateTimeFormat('vi-VN',{weekday:'long',day:'numeric',month:'numeric',timeZone:TZ}).format(g).replace(/^./, c => c.toUpperCase()))} · </span>cập nhật ${hhmm(g)}`;
  renderNav(counts);
  $('#since').innerHTML = `<span class="since-pill"><strong class="num" id="since-n" data-v="0">0</strong> tin mới ${firstVisit ? 'trong 24 giờ<span class="w"> qua</span>' : 'từ lần trước'}</span>
    <button class="btn-quiet" id="mark" ${counts.total ? '' : 'disabled'}>${counts.total ? 'Đánh dấu đã xem' : 'Đã xem hết'}</button>`;
  countTo($('#since-n'), counts.total);
  const tn = $('#tab-new'); tn.hidden = !counts.total; tn.textContent = counts.total > 99 ? '99+' : counts.total;
  renderSrcState();
}
function renderSrcState(){
  const bad = D.sources.filter(s => !s.ok).length;
  const live = liveState ? [...liveState.values()] : [];
  const liveOk = live.filter(s => s.ok).length, liveBad = live.filter(s => s.ok === false).length;
  const lastAt = live.map(s => s.at).filter(Boolean).sort((a, b) => b - a)[0];
  const views = D.views && Number.isFinite(D.views.total) ? ` · ${icon('i-eye')}<span class="num">${fmt(D.views.total)}</span><span class="sr"> lượt xem</span>` : '';
  $('#src-state').innerHTML = `<span class="dot ${bad ? 'warn' : 'ok'}"></span><span class="num">${D.sources.length - bad}/${D.sources.length}</span> nguồn`
    + (lastAt ? `<span class="live-at"><span class="dot ${liveBad === live.length ? 'warn' : 'ok breath'}" aria-hidden="true"></span><span class="w">trực tiếp </span>${hhmm(lastAt)}</span>` : '') + views;
  $('#src-state').setAttribute('aria-label', `${D.sources.length - bad} trên ${D.sources.length} nguồn chạy được${bad ? `, ${bad} lỗi` : ''}`
    + (lastAt ? `. Lớp trực tiếp: ${liveOk} trên ${live.length} nguồn đọc được lúc ${hhmm(lastAt)}` : '') + (views ? `. ${fmt(D.views.total)} lượt xem` : ''));
}

/* Numbers that change count over 600ms (ease-out) and get a short wash; reduced motion or off-screen: change at once. */
function countTo(el, to){
  if (!el) return;
  const from = Number(el.dataset.v || 0);
  el.dataset.v = to;
  const visible = (() => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight && r.width > 0; })();
  if (RM.matches || from === to || !visible) { el.textContent = fmt(to); return; }
  const t0 = performance.now(), dur = 600;
  const step = t => { const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3); el.textContent = fmt(from + (to - from) * e); if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
}

/* ---------- detail sheet ---------- */
function detailStory(st){
  const ev = eventOf(st), id = ytId(st), cal = calOf(st), v = viewsOf(st.id);
  const sig = st.hot_signals && st.hot_signals.measurement;
  const cov = [...(st.coverage || [])].sort((a, b) => (a.published_at || '').localeCompare(b.published_at || ''));
  const sv = savedKey(st.id);
  return `<h2>${esc(st.title)}</h2>
    ${id ? `<span class="thumb" style="display:block">${thumbImg(id, st.title)}</span>` : ''}
    ${st.summary ? `<p class="sum">${esc(st.summary)}</p>` : ''}
    <dl class="facts">
      <dt>Loại</dt><dd>${kindName(st)}</dd>
      <dt>Thời gian</dt><dd>${ev ? `${esc(ev.start_date)}${ev.end_date !== ev.start_date ? ` → ${esc(ev.end_date)}` : ''} (chỉ có ngày)` : `${esc(exact(st.published_at))}${st.time_basis === 'repository_created' ? ' (ngày tạo repo, không phải ngày phát hành)' : ''}`}</dd>
      ${ev ? `<dt>Địa điểm</dt><dd>${esc(ev.location || 'chưa rõ')}</dd><dt>Xác minh</dt><dd>${esc(ev.verified_at)}</dd>` : ''}
      <dt>Số nguồn</dt><dd class="num">${st.source_count}</dd>
      ${st.hot_score != null ? `<dt>Điểm nóng</dt><dd class="num">${Math.round(st.hot_score)} / 100</dd><dt>Vì sao</dt><dd>${reasonHTML(st)}</dd>` : `<dt>Điểm nóng</dt><dd class="faint">Chưa có số đo</dd>`}
      ${sig ? `<dt>Đo lúc</dt><dd>${esc(exact(sig.observed_at))}</dd>` : ''}
      ${v != null ? `<dt>Lượt xem</dt><dd>${viewsEl(v, st.id)} trên ai-radar</dd>` : ''}
    </dl>
    <div class="acts">
      <a class="primary" href="${esc(safe(st.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Mở bài gốc ${icon('i-out')}</a>
      <button class="second" data-save="${esc(st.id)}" aria-pressed="${sv}">${icon('i-save')}${sv ? 'Đã lưu' : 'Lưu đọc sau'}</button>
      ${cal ? `<button class="second" data-cal="${esc(st.id)}">${icon('i-cal')}Thêm vào lịch</button>` : ''}
    </div>
    <p class="hint">Phím: <kbd>O</kbd> mở bài gốc · <kbd>S</kbd> lưu${cal ? ' · <kbd>L</kbd> thêm vào lịch' : ''} · <kbd>Esc</kbd> đóng</p>
    <p class="tlh">Các nguồn, theo thời gian</p>
    <ol class="tl">${cov.map(c => `<li><span class="when">${esc(srcName(c.source))} · ${timeEl(c.published_at)}</span>
      <a href="${esc(safe(c.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">${esc(c.title)}</a>
      ${metricsHTML(c) ? `<span class="m">${metricsHTML(c)}</span>` : ''}
      ${c.discussion_url ? ` <a class="tiny" style="display:inline;color:var(--accent)" href="${esc(safe(c.discussion_url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Thảo luận</a>` : ''}</li>`).join('')}</ol>`;
}
function detailRepo(r){
  const key = 'repo:' + r.id, sv = savedKey(key);
  const area = AREAS.find(a => a.id === r.category);
  const sig = r.signals && typeof r.signals === 'object' ? Object.entries(r.signals).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v)) : [];
  return `<h2>${esc(r.full_name)}</h2>
    <p class="sum">${labChip(r.label)}${area ? esc(area.label) : 'Chưa xếp mảng'}</p>
    ${r.description ? `<p class="sum">${esc(r.description)}</p>` : ''}
    ${r.why ? `<p class="sum"><b>Vì sao đáng xem:</b> ${esc(r.why)}</p>` : ''}
    <dl class="facts">
      <dt>Nguồn</dt><dd>${r.source === 'hf' ? 'Hugging Face' : 'GitHub'}</dd>
      ${repoStars(r) ? `<dt>Số đo</dt><dd>${repoStars(r)}</dd>` : ''}
      <dt>License</dt><dd>${esc(r.license || 'không rõ')}${r.license_flag ? `<br><span class="lic">${icon('i-warn')}${esc(r.license_flag)}</span>` : ''}</dd>
    </dl>
    ${sig.length ? `<p class="tlh">Dấu hiệu đã đo</p><ul class="sig">${sig.map(([k, v]) => `<li><span class="faint">${esc(k)}:</span> ${esc(typeof v === 'boolean' ? (v ? 'có' : 'không') : v)}</li>`).join('')}</ul>` : ''}
    <div class="acts">
      <a class="primary" href="${esc(safe(r.url))}" target="_blank" rel="noopener" data-read="${esc(key)}">Mở repo ${icon('i-out')}</a>
      <button class="second" data-save="${esc(key)}" aria-pressed="${sv}">${icon('i-save')}${sv ? 'Đã lưu' : 'Lưu đọc sau'}</button>
    </div>
    <p class="hint">Phím: <kbd>O</kbd> mở repo · <kbd>S</kbd> lưu · <kbd>Esc</kbd> đóng</p>`;
}

const opened = new Set();   // story ids opened this visit; the views Worker (not deployed yet) would receive these
let lastTrigger = null, lastKey = null, pushed = false;
function itemOf(key){
  if (!key) return null;
  if (key.startsWith('repo:')) { const r = R.get(key.slice(5)); return r && {key, kind:'repo', r, title:r.full_name, url:r.url}; }
  const st = S.get(key); return st && {key, kind:'story', st, title:st.title, url:st.url};
}
function markRead(key){
  if (!key || read.has(key)) return;
  read.add(key);
  store.set('air2:read', [...read].slice(-3000));
  $$(`[data-sel="${CSS.escape(key)}"],[data-repo="${CSS.escape(key.replace(/^repo:/, ''))}"]`).forEach(el => {
    if (key.startsWith('repo:') ? el.matches('[data-repo]') : el.matches('[data-sel]')) el.classList.add('is-read');
  });
}
function open(key, trigger, fromHash = false){
  const it = itemOf(key); if (!it) return;
  const sheet = $('#sheet'), body = $('#sheet-body'), wasOpen = sheet.classList.contains('on');
  selected = key; lastKey = key; if (trigger) lastTrigger = trigger;
  $('#sheet-k').textContent = it.kind === 'repo' ? `Repo · ${it.r.source === 'hf' ? 'Hugging Face' : 'GitHub'}` : `${KIND[it.st.kind] || it.st.kind} · ${pubOf(it.st)}`;
  body.innerHTML = it.kind === 'repo' ? detailRepo(it.r) : detailStory(it.st);
  body.scrollTop = 0;
  if (wasOpen && !RM.matches) { body.classList.remove('swap'); void body.offsetWidth; body.classList.add('swap'); }
  sheet.classList.add('on'); sheet.setAttribute('aria-hidden', 'false'); sheet.inert = false;
  $$('[aria-pressed][data-sel],[aria-pressed][data-repo]').forEach(b => b.setAttribute('aria-pressed', (b.dataset.sel || 'repo:' + b.dataset.repo) === key ? 'true' : 'false'));
  markRead(key); if (it.kind === 'story') opened.add(key);
  const h = '#tin/' + encodeURIComponent(key);
  if (!fromHash && location.hash !== h) { if (wasOpen && pushed) history.replaceState({sheet:1}, '', h); else { history.pushState({sheet:1}, '', h); pushed = true; } }
  $('#sheet-x').focus({preventScroll:true});
}
function closeUI(){
  selected = null;
  const sheet = $('#sheet');
  sheet.classList.remove('on'); sheet.setAttribute('aria-hidden', 'true'); sheet.inert = true;
  $$('[aria-pressed="true"][data-sel],[aria-pressed="true"][data-repo],.crow[aria-pressed="true"]').forEach(b => b.setAttribute('aria-pressed', 'false'));
  // The trigger may have been re-rendered (saving redraws the board): fall back to the same story's new element.
  const back = lastTrigger && document.contains(lastTrigger) ? lastTrigger : items().find(el => keyOf(el) === lastKey);
  if (back) back.focus({preventScroll:true});
}
function close(){
  if (!selected) return;
  if (pushed && history.state && history.state.sheet) { pushed = false; history.back(); return; }   // popstate closes the UI
  pushed = false;
  history.replaceState(null, '', location.pathname + location.search);
  closeUI();
}
addEventListener('popstate', () => {
  const m = /^#tin\/(.+)$/.exec(location.hash);
  if (m) open(decodeURIComponent(m[1]), null, true); else if (selected) { pushed = false; closeUI(); }
});

/* ---------- save, calendar, toast ---------- */
let toastT;
function toast(msg){
  const el = $('#toast'); clearTimeout(toastT);
  el.innerHTML = `<span>${esc(msg)}</span>`;
  toastT = setTimeout(() => { const s = el.querySelector('span'); if (s) s.classList.add('out'); setTimeout(() => { el.innerHTML = ''; }, 260); }, 3200);
}
function toggleSave(key){
  const it = itemOf(key) || saved.find(x => x.key === key);
  if (!it) return;
  if (savedKey(key)) { saved = saved.filter(x => x.key !== key); toast('Đã bỏ lưu'); }
  else { saved.push({key, title: it.title, url: it.url, at: new Date().toISOString()}); toast('Đã lưu. Xem lại ở mục Đã lưu'); }
  store.set('air2:saved', saved.slice(-300));
  renderNav(navCounts(D)); renderChapters(); observeChapters();
  if (selected) { const b = $(`#sheet-body [data-save="${CSS.escape(selected)}"]`); if (b) { const on = savedKey(selected); b.setAttribute('aria-pressed', on); b.innerHTML = `${icon('i-save')}${on ? 'Đã lưu' : 'Lưu đọc sau'}`; } }
  renderBoard();
}
function addToCalendar(ev){
  if (!canCalendar(ev)) { toast('Sự kiện này chưa có ngày xác minh nên chưa thêm vào lịch được'); return; }
  try { downloadIcs(ev); } catch { toast('Không tạo được tệp lịch cho sự kiện này'); return; }
  toast('Đã tạo tệp lịch .ics. Mở tệp để thêm vào lịch của bạn');
}

/* ---------- live layer 1: counters refresh in place ---------- */
function applyLive(updates){
  for (const u of updates) {
    if (!u.cov.metrics) u.cov.metrics = {};
    u.cov.metrics[u.metric] = u.value;
    $$(`[data-live="${CSS.escape(u.cov.id + '|' + u.metric)}"]`).forEach(el => countTo(el, u.value));
  }
}

/* ---------- live layer 2: a fresh snapshot waits behind a "N tin mới" button ---------- */
async function pollSnapshot(){
  if (document.hidden || !D) return;
  try {
    const r = await fetch(DATA_URL, {cache:'no-store'});
    if (!r.ok) return;
    const j = await r.json();
    if (!j || !j.generated_at || !Array.isArray(j.stories) || j.generated_at <= D.generated_at) return;
    pending = j;
    const fresh = j.stories.filter(s => !S.has(s.id)).length;
    $('#fresh').innerHTML = `<button class="fresh-btn" id="fresh-go">${icon('i-up')}${fresh ? `<span><span class="num">${fresh}</span> tin mới</span>` : '<span>Số liệu vừa cập nhật</span>'} · Xem</button>`;
    // Counts in the bar update now, with no reflow of what the reader is looking at.
    const c = navCounts(j);
    countTo($('#since-n'), c.total);
    renderNav(c);
    const tn = $('#tab-new'); tn.hidden = !c.total; tn.textContent = c.total > 99 ? '99+' : c.total;
  } catch { /* a failed poll keeps the current snapshot; the next poll tries again */ }
}
function applyPending(){
  if (!pending) return;
  arrived = new Set(pending.stories.filter(s => !S.has(s.id)).map(s => s.id));
  D = pending; pending = null;
  $('#fresh').innerHTML = '';
  const update = () => { build(); renderAll(); };
  if (document.startViewTransition && !RM.matches) document.startViewTransition(update); else update();
  scrollTo({top:0, behavior: RM.matches ? 'auto' : 'smooth'});
  $('#board').focus({preventScroll:true});
  setTimeout(() => { arrived = new Set(); }, 1500);
}

/* ---------- keyboard ---------- */
function items(){
  return $$('[data-sel],[data-repo]').filter(el => el.dataset.sel !== '' && !el.closest('#sheet') && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden' && !el.closest('[hidden]'));
}
function keyOf(el){ return el ? (el.dataset.sel || (el.dataset.repo != null ? 'repo:' + el.dataset.repo : null)) : null; }
function current(){ return selected || keyOf(document.activeElement && document.activeElement.closest('[data-sel],[data-repo]')); }
function move(dir){
  const list = items(); if (!list.length) return;
  // With the sheet open, focus sits on its close button, so position comes from the open story:
  // the element that opened it if still on screen, otherwise that story's first visible element.
  let i = selected
    ? (lastTrigger && list.includes(lastTrigger) && keyOf(lastTrigger) === selected ? list.indexOf(lastTrigger) : list.findIndex(el => keyOf(el) === selected))
    : list.indexOf(document.activeElement && document.activeElement.closest('[data-sel],[data-repo]'));
  // Nothing focused yet: start from the first item below the bar, so J lands on what the reader is looking at.
  if (i < 0) { const top = $('#bar').getBoundingClientRect().bottom; const first = list.findIndex(el => el.getBoundingClientRect().top >= top); i = (first < 0 ? list.length : first) - (dir > 0 ? 1 : 0); }
  const next = list[Math.max(0, Math.min(list.length - 1, i + dir))];
  next.focus({preventScroll:true});
  next.scrollIntoView({block:'nearest', behavior: RM.matches ? 'auto' : 'smooth'});
  if (selected) open(keyOf(next), next);
}
document.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
  const t = e.target instanceof Element ? e.target : null;
  if (t && t.closest('input,textarea,select,[contenteditable="true"]')) return;
  if ($('#keys').open) return;
  const k = e.key;
  if (k === 'Escape' && selected) { close(); return; }
  if (k === 'j' || k === 'J') { e.preventDefault(); move(1); }
  else if (k === 'k' || k === 'K') { e.preventDefault(); move(-1); }
  else if (k === 'o' || k === 'O') { const it = itemOf(current()); if (it) { window.open(safe(it.url), '_blank', 'noopener'); markRead(it.key); } }
  else if (k === 's' || k === 'S') { const c = current(); if (c) toggleSave(c); }
  else if (k === 'l' || k === 'L') { const it = itemOf(current()); const cal = it && it.kind === 'story' ? calOf(it.st) : null; if (cal) addToCalendar(cal); else if (it) toast('Tin này không có lịch để thêm'); }
  else if (k === 'u' || k === 'U') { if (pending) applyPending(); else toast('Chưa có tin mới. Trang tự kiểm mỗi 3 phút'); }
  else if (k === 'm' || k === 'M') { const b = $('#mark'); if (b && !b.disabled) b.click(); }
  else if (k === 'g' || k === 'G') { scrollTo({top:0, behavior: RM.matches ? 'auto' : 'smooth'}); }
  else if (k === '?') { e.preventDefault(); $('#keys').showModal(); }
});

/* ---------- scroll spy: one pass for the top nav and the bottom tabs ---------- */
let spyQueued = false;
function spy(){
  if (spyQueued) return; spyQueued = true;
  requestAnimationFrame(() => {
    spyQueued = false;
    const line = innerHeight * 0.4;
    let cur = null;
    $$('.ch').forEach(s => { if (s.getBoundingClientRect().top <= line) cur = s.id; });
    $$('#nav a').forEach(a => a.setAttribute('aria-current', cur && a.getAttribute('href') === '#' + cur ? 'true' : 'false'));
    const tabTargets = ['top', 'moi', 'nong', 'repo', 'sap-toi'];
    let tab = 'top';
    tabTargets.forEach(id => { const el = document.getElementById(id); if (el && id !== 'top' && el.getBoundingClientRect().top <= line) tab = id; });
    $$('#tabs a').forEach(a => a.setAttribute('aria-current', a.dataset.tab === tab ? 'true' : 'false'));
    $('#bar').classList.toggle('scrolled', scrollY > 4);
  });
}
function observeChapters(){ spy(); }

function renderAll(){ renderChrome(); renderBoard(); renderChapters(); observeChapters();
  const b = $('#board'); b.classList.remove('ready'); void b.offsetWidth; b.classList.add('ready');
  if (D.stories.length) { const c = $('[data-count]'); if (c) { c.dataset.v = 0; countTo(c, Number(c.dataset.count)); } } }

/* ---------- events ---------- */
document.addEventListener('click', e => {
  const t = e.target;
  const save = t.closest('[data-save]'); if (save) { toggleSave(save.dataset.save); return; }
  const uns = t.closest('[data-unsave]'); if (uns) { toggleSave(uns.dataset.unsave); return; }
  const cal = t.closest('[data-cal]'); if (cal) { e.preventDefault(); const c = calOf(S.get(cal.dataset.cal)); if (c) addToCalendar(c); return; }
  const cl = t.closest('[data-cal-live]'); if (cl) { e.preventDefault(); addToCalendar(liveCal((D.live || []).find(v => v.video_id === cl.dataset.calLive))); return; }
  const area = t.closest('[data-area]'); if (area) { const a = area.dataset.area; areas.has(a) ? areas.delete(a) : areas.add(a); store.set('air2:areas', [...areas]); rerenderRepos(); return; }
  if (t.closest('[data-area-clear]')) { areas.clear(); store.set('air2:areas', []); rerenderRepos(); return; }
  if (t.closest('[data-research]')) { withResearch = !withResearch; store.set('air2:research', withResearch); rerenderRepos(); return; }
  if (t.closest('#fresh-go')) { applyPending(); return; }
  if (t.closest('#mark')) { store.set('air2:lastSeen', D.generated_at); lastSeen = D.generated_at; firstVisit = false; renderAll(); toast('Đã đánh dấu đã xem hết'); return; }
  if (t.closest('#keys-open')) { $('#keys').showModal(); return; }
  if (t.closest('#keys-x')) { $('#keys').close(); return; }
  const rd = t.closest('a[data-read]'); if (rd) { markRead(rd.dataset.read); return; }
  const b = t.closest('[data-sel],[data-repo]');
  if (b && !t.closest('a') && (b.dataset.sel || b.dataset.repo != null)) { e.preventDefault(); open(keyOf(b), b); }
});
function rerenderRepos(){
  const y = scrollY, focusArea = document.activeElement && document.activeElement.dataset.area;
  renderBoard(); renderChapters(); observeChapters();
  scrollTo(0, y);
  if (focusArea) { const el = $(`[data-area="${CSS.escape(focusArea)}"]`); if (el) el.focus({preventScroll:true}); }
}
$('#sheet-x').addEventListener('click', close);
$('#keys').addEventListener('click', e => { if (e.target === $('#keys')) $('#keys').close(); });
addEventListener('scroll', spy, {passive:true});
/* Fill-to-height must hold whenever layout settles, not only at first render: web fonts on a cold cache,
   thumbnails, live counter updates and window changes all move rows. Re-fit on the next frame whenever
   the board, a tile or the content above a list changes size, and whenever a font finishes loading.
   fitAll only changes row padding inside lists, which none of the observed boxes depend on, so it cannot loop. */
let wasWide = null, fitQueued = false;
function refit(){
  if (fitQueued || !D) return;
  fitQueued = true;
  requestAnimationFrame(() => {
    fitQueued = false;
    const w = newtShown();
    if (w !== wasWide) { wasWide = w; renderBoard(); } else fitAll();
    spy();
  });
}
const fitRO = 'ResizeObserver' in window ? new ResizeObserver(refit) : null;
function observeFit(){
  if (!fitRO) return;
  fitRO.disconnect();
  fitRO.observe(document.documentElement);
  $$('#board, #board .tile, #board .lead-top, #board .cov, #board .tile-h').forEach(el => fitRO.observe(el));
}
addEventListener('resize', refit);
if (document.fonts) { document.fonts.addEventListener('loadingdone', refit); document.fonts.ready.then(refit); }
setInterval(() => $$('[data-ago]').forEach(el => { el.textContent = ago(el.dataset.ago); }), 60_000);

/* ---------- start ---------- */
function showError(msg){
  const b = $('#board'); b.classList.remove('is-loading'); b.removeAttribute('aria-busy');
  b.innerHTML = `<div class="tile" role="alert" style="padding:24px;grid-column:1/-1"><h2 style="margin:0 0 8px">Chưa mở được bản tin</h2><p class="muted" style="margin:0 0 12px">${esc(msg)}. Trang không thay bằng tin mẫu.</p><button class="primary" id="retry">Thử lại</button></div>`;
  $('#retry').addEventListener('click', () => location.reload());
}
fetch(DATA_URL, {cache:'no-store'}).then(r => { if (!r.ok) throw new Error(`Máy chủ trả HTTP ${r.status} cho ${DATA_URL}`); return r.json(); }).then(j => {
  if (!j || j.schema_version !== 2 || !Array.isArray(j.stories) || !j.sections) throw new Error('Tệp dữ liệu không đúng hợp đồng v2');
  D = j; build(); wasWide = newtShown(); renderAll();
  const m = /^#tin\/(.+)$/.exec(location.hash); if (m) open(decodeURIComponent(m[1]), null, true);
  else if (location.hash.length > 1) { const el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView(); }
  startLive({
    getStories: () => D.stories,
    priority: hnId => { const st = D.stories.find(s => (s.coverage || []).some(c => (c.discussion_url || '').endsWith('=' + hnId))); return st ? (st.hot_score || 0) : 0; },
    onUpdates: applyLive,
    onStatus: st => { liveState = st; renderSrcState(); const lr = $('#live-rows'); if (lr) lr.innerHTML = liveRows(); },
  });
  setInterval(pollSnapshot, SNAPSHOT_EVERY_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollSnapshot(); });
}).catch(err => showError(err.message || 'Lỗi không rõ'));

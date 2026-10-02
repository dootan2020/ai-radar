/* ai·radar · renders data/radar.json (schema v2) as the "Bento Keynote" page (docs/ngon-ngu-thiet-ke.md).
   Plain ES modules, no framework, no build. Every data string passes through esc(); every link through safe().
   Each tile is one story: a source logo, one measured number, a label. A tile with no data hides or says so. */
import { startLive } from './live.js';
import { canCalendar, downloadIcs, gcalURL } from './calendar.js';
import { streamedAge, scheduleText } from './time-text.js';
import { esc, fmt, avatar, avatarStack, faceOfStory, faceOfSource, faceOfRepo, ytIdOf, hydrateHF, watchImageErrors, hourHistogram, ring, meter } from './faces.js';

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
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const nf = new Intl.NumberFormat('vi-VN');
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
const faceSt = st => faceOfStory(st, SRC);
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
  const cov = measuredCov(st);
  if (cov) html = html.replace(/(<\/b> )(\d[\d.,]*)/, (m, a, n) => `${a}<span class="lv num" data-live="${esc(cov.c.id)}|${esc(cov.metric)}" data-v="${cov.c.metrics[cov.metric]}">${n}</span>`);
  return html;
}
/* The coverage item and metric behind a story's hot score, when the pipeline measured one. */
function measuredCov(st){
  const ms = st.hot_signals && st.hot_signals.measurement;
  const c = ms && (st.coverage || []).find(c => c.source === ms.source && c.metrics && ms.metric in c.metrics);
  return c ? {c, metric: ms.metric} : null;
}
const ytId = ytIdOf;
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
/* The pipeline writes the install command inside backticks in `why`; the page only lifts it out, never writes one. */
const installOf = r => { const m = /cài:\s*`([^`]+)`/.exec(r.why || ''); return m ? m[1] : null; };
const whyShort = r => String(r.why || r.description || '').split(' · ').filter(p => p && p !== LABELS[r.label] && !/^cài:/.test(p)).slice(0, 3).join(' · ');

/* Calendar target for a story: a curated event (date-only stays all-day) or a verified upcoming stream with an exact start. */
function calOf(st){
  if (!st) return null;
  const e = eventOf(st);
  if (e) return {uid:e.id, title:String(e.title), url:e.url, location:e.location, startDate:e.start_date, endDate:e.end_date,
    startAt: e.time_precision === 'exact' ? e.start_at : null, endAt: e.time_precision === 'exact' ? e.end_at : null,
    note:`Ngày đã xác minh ${e.verified_at} từ ${e.source_url}`};
  const c = (st.coverage || []).find(c => c.status === 'upcoming' && c.start_at && c.time_precision !== 'relative');
  return c ? {uid:c.id, title:c.title, url:c.url, startAt:c.start_at, endAt:null, note:`Livestream của ${srcName(c.source)}`} : null;
}
const liveCal = v => v && v.status === 'upcoming' && v.start_at && v.time_precision !== 'relative'
  ? {uid:v.video_id, title:v.title, url:v.url, startAt:v.start_at, endAt:null, note:`Livestream của ${v.channel}`} : null;
/* "Thêm vào lịch" as one split control: Google Calendar opens Google's template in a new tab, .ics downloads a file. */
function calButtons(cal, attr, label){
  if (!cal || !canCalendar(cal)) return '';
  const g = gcalURL(cal);
  return `<span class="calbtn" role="group" aria-label="Thêm ${esc(label)} vào lịch">
    <a class="calbtn-g" href="${esc(g)}" target="_blank" rel="noopener">${icon('i-cal')}<span>Google Calendar</span></a>
    <button class="calbtn-ics" ${attr} title="Tải tệp .ics cho Apple Calendar, Outlook">.ics</button></span>`;
}

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
/* One row: a logo, the title with its source, and a measure on the right. Rows never carry text alone. */
function row(st, o = {}){
  const v = viewsOf(st.id);
  const right = o.right != null ? o.right : timeEl(st.published_at);
  return `<button class="row${o.compact ? ' c' : ''}${read.has(st.id) ? ' is-read' : ''}${arrived.has(st.id) ? ' arrive' : ''}"${arriveAttr(st.id)} data-sel="${esc(st.id)}" aria-pressed="${selected === st.id}">
    ${avatar(faceSt(st), o.compact ? 'sm' : 'md')}
    <span class="row-m"><span class="t">${savedKey(st.id) ? savedMark : ''}${isNew(st) ? newMark : ''}${esc(String(st.title))}</span>
    <span class="k"><span class="pub">${esc(pubOf(st))}</span> · ${kindName(st)}${st.source_count > 1 ? ` · <span class="num">${st.source_count}</span> nguồn` : ''}${v != null ? ` · ${viewsEl(v, st.id)}` : ''}</span></span>
    <span class="r">${right}</span></button>`;
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
  if (o.compact) return `<button class="repo c${read.has(key) ? ' is-read' : ''}" data-repo="${esc(r.id)}" aria-pressed="${selected === key}">
    ${avatar(faceOfRepo(r), 'sm')}<span class="row-m"><span class="nm">${savedKey(key) ? savedMark : ''}${rest.length ? `<span class="own">${esc(own)}/</span>` : ''}${esc(name)}</span><span class="k">${repoStars(r)}</span></span></button>`;
  return `<button class="repo${o.compact ? ' c' : ''}${read.has(key) ? ' is-read' : ''}" data-repo="${esc(r.id)}" aria-pressed="${selected === key}">
    ${avatar(faceOfRepo(r), o.compact ? 'sm' : 'md')}
    <span class="row-m"><span class="nm">${savedKey(key) ? savedMark : ''}${rest.length ? `<span class="own">${esc(own)}/</span>` : ''}${esc(name)}</span>
    <span class="why">${o.compact ? '' : `${labChip(r.label)} `}${esc(whyShort(r))}${r.license_flag ? ` · <span class="lic">${icon('i-warn')}${esc(r.license_flag)}</span>` : ''}</span></span>
    <span class="r">${repoStars(r)}</span></button>`;
}
const copyBtn = cmd => `<span class="cmd"><code>${esc(cmd)}</code><button class="cmd-copy" data-copy="${esc(cmd)}" aria-label="Chép lệnh cài: ${esc(cmd)}">${icon('i-copy')}${icon('i-check')}<span class="cmd-l">Chép</span></button></span>`;
const tileHead = (h, id, aside = '') => `<header class="tile-h"><h2 id="${id}">${h}</h2>${aside ? `<span class="aside">${aside}</span>` : ''}</header>`;

/* ---------- the board: the first screen as a bento of stories ---------- */
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
    board.innerHTML = `<div class="tile t-empty" role="status">${avatar({kind:'mono', id:'AR', label:'ai-radar'}, 'lg')}<h2>Bản tin này chưa có tin nào</h2><p class="muted">Dữ liệu tạo lúc ${esc(exact(D.generated_at))} không chứa tin. Trang không điền tin mẫu.</p></div>`;
    board.classList.remove('is-loading'); board.removeAttribute('aria-busy');
    return;
  }
  arriveIdx = 0;
  const L = pickLead(), st = L.st;
  const shown = new Set([st.id]);
  const tiles = [leadTile(L), liveTile(shown), repoTile(), hotTile(shown), newTile(shown), listenTile(shown), modelTile(shown), sourcesTile()].filter(Boolean);
  board.innerHTML = tiles.map((t, i) => t.replace('class="tile ', `style="--t:${i}" class="tile `)).join('');
  board.classList.remove('is-loading'); board.removeAttribute('aria-busy');
  hydrateVisible();
}

/* The lead: the day's most-covered story, or the hottest when no story has two sources. Its measured number is the keynote. */
function leadTile(L){
  const st = L.st, v = viewsOf(st.id), mc = measuredCov(st);
  const big = L.mode === 'multi' ? {n: st.source_count, unit: 'nguồn cùng đưa chuyện này'}
    : mc ? {n: mc.c.metrics[mc.metric], unit: `${METRIC[mc.metric] || mc.metric} trên ${srcName(mc.c.source)}`, live: `${mc.c.id}|${mc.metric}`}
    : {n: st.source_count, unit: st.source_count > 1 ? 'nguồn cùng đưa' : 'nguồn đưa tin'};
  const label = L.mode === 'multi' ? 'Nhiều nguồn cùng đưa nhất, 72 giờ qua' : 'Nóng nhất lúc này';
  const sub = L.mode === 'multi' ? '' : '<span class="lead-why">Chưa có chuyện nào được từ 2 nguồn đưa trong 72 giờ, nên đây là chuyện có điểm nóng cao nhất.</span>';
  const faces = [...new Map((st.coverage || []).map(c => [c.source, faceOfSource(c, SRC)])).values()];
  const primary = (st.coverage || []).find(c => c.discussion_url) ;
  const others = L.others.slice(0, 2);
  const cov = st.source_count > 1 ? `<ul class="cov" aria-label="Các nguồn đưa chuyện này">${(st.coverage || []).map(c => `<li>${avatar(faceOfSource(c, SRC), 'xs')}<span class="pub">${esc(srcName(c.source))}</span><span class="faint">${timeEl(c.published_at)}</span>${metricsHTML(c) ? `<span class="m">${metricsHTML(c)}</span>` : ''}<a class="go" href="${esc(safe(c.discussion_url || c.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">${c.discussion_url ? 'Thảo luận' : 'Bài gốc'}</a></li>`).join('')}</ul>` : '';
  return `<article class="tile t-lead" aria-labelledby="lead-h">
    <div class="lead-top">${faces.length > 1 ? avatarStack(faces, 'lg') : avatar(faceSt(st), 'xl')}
      <p class="lead-label" id="lead-h"><span class="pill pill-hot">${icon('i-flame')}${label}</span><span class="lead-src">${esc(pubOf(st))} · ${kindName(st)} · ${timeEl(st.published_at)}</span></p></div>
    <p class="keynote"><b class="num"${big.live ? ` data-live="${esc(big.live)}"` : ''} data-count="${big.n}" data-v="${big.n}">${fmt(big.n)}</b><span>${esc(big.unit)}</span></p>
    <h3 class="lead-title-wrap"><button class="lead-title${read.has(st.id) ? ' is-read' : ''}" data-sel="${esc(st.id)}">${savedKey(st.id) ? savedMark : ''}${esc(String(st.title))}</button></h3>
    ${st.summary ? `<p class="lead-sum">${esc(st.summary)}</p>` : ''}
    ${sub}
    ${cov}
    <div class="lead-foot">
      ${st.hot_score != null ? ring(st.hot_score, 'Điểm nóng') : ''}
      <div class="lead-facts">${st.hot_reason ? `<p>Nóng vì ${reasonHTML(st)}</p>` : ''}${v != null ? `<p>${viewsEl(v, st.id)} trên ai-radar</p>` : ''}
        <div class="acts">
          ${primary ? `<a class="btn primary" href="${esc(safe(primary.discussion_url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Mở thảo luận ${icon('i-out')}</a>` : ''}
          <a class="btn ${primary ? 'second' : 'primary'}" href="${esc(safe(st.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Bài gốc ${icon('i-out')}</a>
          <button class="btn icon-only" data-save="${esc(st.id)}" aria-pressed="${savedKey(st.id)}" aria-label="${savedKey(st.id) ? 'Bỏ lưu' : 'Lưu đọc sau'}">${icon('i-save')}</button>
        </div></div>
    </div>
    ${others.length ? `<div class="lead-more"><p class="sub-h">Chuyện nhiều nguồn khác</p>${others.map(o => `<button class="row c${read.has(o.id) ? ' is-read' : ''}" data-sel="${esc(o.id)}" aria-pressed="${selected === o.id}">${avatarStack([...new Map((o.coverage || []).map(c => [c.source, faceOfSource(c, SRC)])).values()], 'xs')}<span class="row-m"><span class="t">${esc(String(o.title))}</span><span class="k"><span class="num">${o.source_count}</span> nguồn · ${timeEl(o.published_at)}</span></span></button>`).join('')}</div>` : ''}
  </article>`;
}

/* "Đang phát và sắp tới": the strip the captain liked, now one tile. Live state comes only from status fields. */
function liveTile(shown){
  const liveNow = [], ended = [];
  D.stories.forEach(s => (s.coverage || []).forEach(c => { if (c.status === 'live') liveNow.push(s); if (c.status === 'ended') ended.push({s, c}); }));
  (D.live || []).forEach(v => { if (v.status === 'live' && !liveNow.length) liveNow.push({title:v.title, id:null, url:v.url}); });
  const upcomingStreams = (D.live || []).filter(v => v.status === 'upcoming');
  const upcoming = ids('upcoming');
  const lastEnded = ended.sort((a, b) => (b.c.end_at || '').localeCompare(a.c.end_at || ''))[0];
  // An ended stream known only from the live projection (no story yet) still has a verified thumbnail and end time.
  const endedLive = !lastEnded ? (D.live || []).filter(v => v.status === 'ended').sort((a, b) => (b.end_at || '').localeCompare(a.end_at || ''))[0] : null;

  let media;
  if (liveNow.length) {
    const L0 = liveNow[0];
    const inner = `<span class="state on"><span class="pulse on" aria-hidden="true"></span>Đang phát</span><strong>${esc(String(L0.title))}</strong>`;
    media = L0.id ? `<button class="media is-live" data-sel="${esc(L0.id)}">${inner}</button>` : `<a class="media is-live" href="${esc(safe(L0.url))}" target="_blank" rel="noopener">${inner}</a>`;
    if (L0.id) shown.add(L0.id);
  } else if (lastEnded) {
    const id = ytId(lastEnded.s);
    const when = lastEnded.c.end_at ? `Kết thúc ${timeEl(lastEnded.c.end_at)}` : esc(streamedAge(lastEnded.c.time_text) || 'Đã phát xong');
    media = `<button class="media${id ? ' has-thumb' : ''}" data-sel="${esc(lastEnded.s.id)}">${id ? `<span class="thumb">${thumbImg(id)}<span class="play" aria-hidden="true">${icon('i-play')}</span></span>` : ''}<span class="media-cap"><span class="state">Vừa phát xong · ${when}</span><strong>${esc(String(lastEnded.c.title))}</strong></span></button>`;
    shown.add(lastEnded.s.id);
  } else if (endedLive) {
    media = `<a class="media has-thumb" href="${esc(safe(endedLive.url))}" target="_blank" rel="noopener"><span class="thumb">${thumbImg(endedLive.video_id)}<span class="play" aria-hidden="true">${icon('i-play')}</span></span><span class="media-cap"><span class="state">Vừa phát xong · ${esc(endedLive.channel)} · ${endedLive.end_at ? `kết thúc ${timeEl(endedLive.end_at)}` : 'đã phát xong'}</span><strong>${esc(String(endedLive.title))}</strong></span></a>`;
  } else media = '';

  const status = liveNow.length ? '' : `<span class="state"><span class="pulse" aria-hidden="true"></span>Không có buổi nào đang phát · kiểm lúc ${hhmm(new Date(D.generated_at))}</span>`;
  const streams = upcomingStreams.slice(0, 1).map(v => {
    const cal = liveCal(v);
    return `<div class="ev-row">${avatar(faceOfSource({source:'', lab:v.lab}, SRC), 'sm')}<span class="row-m"><a class="t" href="${esc(safe(v.url))}" target="_blank" rel="noopener">${esc(String(v.title))}</a>
      <span class="k">Sắp phát · ${esc(v.channel)} · ${v.start_at && v.time_precision !== 'relative' ? esc(exact(v.start_at)) : esc(scheduleText(v.time_text))}</span></span>${calButtons(cal, `data-cal-live="${esc(v.video_id)}"`, v.title)}</div>`;
  }).join('');
  const evs = upcoming.map(s => ({s, e: eventOf(s) || {}})).filter(x => x.e.start_date).sort((a, b) => a.e.start_date.localeCompare(b.e.start_date));
  evs.forEach(x => shown.add(x.s.id));
  const first = evs[0], restEv = evs.slice(1, 2);
  const firstBlock = first ? (() => { const n = daysUntil(first.e.start_date), sd = dateOnly(first.e.start_date);
    return `<div class="countdown"><p class="cd-n"><b class="num" data-count="${Math.max(0, n)}" data-v="${Math.max(0, n)}">${Math.max(0, n)}</b><span>${n > 0 ? 'ngày nữa' : n === 0 ? 'hôm nay' : 'đang diễn ra'}</span></p>
      <div class="cd-m"><button class="t" data-sel="${esc(first.s.id)}">${esc(String(first.s.title))}</button><span class="k">${sd.d} tháng ${sd.m} · ${esc(first.e.location || 'chưa rõ địa điểm')}</span></div>
      ${calButtons(calOf(first.s), `data-cal="${esc(first.s.id)}"`, String(first.s.title))}</div>`; })()
    : `<p class="empty-note">Chưa có sự kiện nào đã xác minh ngày.</p>`;
  const restBlock = restEv.map(({s, e}) => { const sd = dateOnly(e.start_date), n = daysUntil(e.start_date);
    return `<div class="ev-row"><span class="datebadge" aria-hidden="true"><b>${sd.d}</b><span>th ${sd.m}</span></span><span class="row-m"><button class="t" data-sel="${esc(s.id)}">${esc(String(s.title))}</button><span class="k">còn <span class="num">${n}</span> ngày · ${esc(e.location || 'chưa rõ địa điểm')}</span></span>${calButtons(calOf(s), `data-cal="${esc(s.id)}"`, String(s.title))}</div>`; }).join('');

  return `<section class="tile t-live" aria-labelledby="live-h">
    ${tileHead('Đang phát và sắp tới', 'live-h', `<a class="link" href="#nghe">Nghe và xem</a>`)}
    ${status}${media}
    <div class="live-next">${firstBlock}${streams}${restBlock}</div>
  </section>`;
}

/* Repos: the one a reader can take home now, with its measured stars and its own install command. */
function repoTile(){
  const list = repoList();
  if (!list) return '';
  const picks = repoPicks(list);
  if (!picks.length) return `<section class="tile t-repo" aria-labelledby="repo-h">${tileHead('Repo lấy về dùng được', 'repo-h')}<p class="empty-note">Không có repo nào ở mảng bạn chọn. <button class="btn-quiet" data-area-clear>Hiện mọi mảng</button></p></section>`;
  const r = picks[0], key = 'repo:' + r.id, cmd = installOf(r);
  const [own, ...rest] = String(r.full_name).split('/');
  const unit = r.source === 'hf' ? 'lượt thích trên Hugging Face' : 'sao trên GitHub';
  return `<section class="tile t-repo" aria-labelledby="repo-h">
    ${tileHead('Repo lấy về dùng được', 'repo-h', `<a class="link" href="#repo"><span class="num">${list.length}</span> repo</a>`)}
    <button class="repo-hero${read.has(key) ? ' is-read' : ''}" data-repo="${esc(r.id)}" aria-pressed="${selected === key}">
      ${avatar(faceOfRepo(r), 'lg')}
      <span class="row-m"><span class="nm">${savedKey(key) ? savedMark : ''}${rest.length ? `<span class="own">${esc(own)}/</span>` : ''}${esc(rest.join('/') || own)}</span>${labChip(r.label)}</span>
    </button>
    ${Number.isFinite(r.stars) ? `<p class="keynote k-md"><b class="num" data-count="${r.stars}" data-v="${r.stars}">${fmt(r.stars)}</b><span>${unit}</span></p>` : ''}
    <p class="repo-why">${esc(whyShort(r))}${r.license_flag ? ` · <span class="lic">${icon('i-warn')}${esc(r.license_flag)}</span>` : ''}</p>
    ${cmd ? copyBtn(cmd) : ''}
    <div class="repo-next">${picks.slice(1, 4).map(x => repoRow(x, {compact:true})).join('')}</div>
  </section>`;
}

/* Hot: ranks 2 onward (the lead already holds the first), each with its measured score and a meter against the top. */
function hotTile(shown){
  const all = ids('hot'), max = all.length ? all[0].hot_score || 1 : 1;
  const list = all.filter(s => !shown.has(s.id)).slice(0, 5);
  if (!list.length) return `<section class="tile t-hot" aria-labelledby="hot-h">${tileHead('Đang nóng', 'hot-h')}<p class="empty-note">Chưa có tin nào đủ số đo để xếp hạng.</p></section>`;
  list.forEach(s => shown.add(s.id));
  return `<section class="tile t-hot" aria-labelledby="hot-h">
    ${tileHead('Đang nóng', 'hot-h', `Điểm đo được, 72 giờ qua · <a class="link" href="#nong">Xem đủ <span class="num">${all.length}</span></a>`)}
    <ol class="hot-list">${list.map(s => `<li><button class="hrow${read.has(s.id) ? ' is-read' : ''}${arrived.has(s.id) ? ' arrive' : ''}"${arriveAttr(s.id)} data-sel="${esc(s.id)}" aria-pressed="${selected === s.id}">
      <span class="rk num">${all.indexOf(s) + 1}</span>${avatar(faceSt(s), 'md')}
      <span class="row-m"><span class="t">${savedKey(s.id) ? savedMark : ''}${esc(String(s.title))}</span><span class="k">${reasonHTML(s)}${s.source_count > 1 ? ` · <b class="num">${s.source_count}</b> nguồn` : ''}</span></span>
      <span class="score"><b class="num">${Math.round(s.hot_score)}</b>${meter(s.hot_score, max)}</span></button></li>`).join('')}</ol>
  </section>`;
}

/* New since the last visit: the count is the keynote, the hour bars show when it arrived, three newest follow. */
function newTile(shown){
  const list = D.stories.filter(isNew).sort(byNewest);
  const rows = list.filter(s => !shown.has(s.id)).slice(0, 3);
  rows.forEach(s => shown.add(s.id));
  return `<section class="tile t-new" id="moi" aria-labelledby="new-h">
    ${tileHead(firstVisit ? 'Mới trong 24 giờ qua' : 'Mới từ lần bạn xem trước', 'new-h', `<a class="link" href="#hom-nay">Xem tất cả</a>`)}
    <div class="new-top"><p class="keynote k-md"><b class="num" data-count="${list.length}" data-v="${list.length}">${fmt(list.length)}</b><span>tin mới</span></p>
      <div class="new-hist">${hourHistogram(D.stories, D.generated_at, lastSeen)}<span class="hist-axis"><span>24 giờ trước</span><span>bây giờ</span></span></div></div>
    ${rows.length ? `<div class="stack">${rows.map(s => row(s, {compact:true})).join('')}</div>` : `<p class="empty-note">Không có tin nào mới từ lần bạn đánh dấu đã xem.</p>`}
  </section>`;
}

/* Listen and watch: real YouTube thumbnails are the only photographs the data carries, so they get the room. */
function listenTile(shown){
  const list = ids('listen').filter(s => !shown.has(s.id)).sort(byNewest);
  if (!list.length) return '';
  const vids = list.filter(s => ytId(s)).slice(0, 2), other = list.filter(s => !ytId(s)).slice(0, 1);
  vids.concat(other).forEach(s => shown.add(s.id));
  return `<section class="tile t-listen" aria-labelledby="listen-h">
    ${tileHead('Nghe và xem', 'listen-h', `<a class="link" href="#nghe"><span class="num">${(D.sections.listen || []).length}</span> mục</a>`)}
    <div class="vid2">${vids.map(s => `<button class="vid${read.has(s.id) ? ' is-read' : ''}" data-sel="${esc(s.id)}"><span class="thumb">${thumbImg(ytId(s), '')}<span class="play" aria-hidden="true">${icon('i-play')}</span></span><span class="t">${esc(String(s.title))}</span><span class="k">${esc(pubOf(s))} · ${timeEl(s.published_at)}</span></button>`).join('')}</div>
    ${other.map(s => row(s, {compact:true})).join('')}
  </section>`;
}

/* Models: launches and open weights, each with its lab's logo and, when measured, its likes. */
function modelTile(shown){
  const all = ids('models').sort(byNewest);
  const list = all.filter(s => !shown.has(s.id)).slice(0, 4);
  if (!list.length) return '';
  list.forEach(s => shown.add(s.id));
  const week = all.filter(s => s.published_at && now() - new Date(s.published_at) < 7 * 864e5).length;
  const right = s => { const c = (s.coverage || []).find(c => c.metrics && Number.isFinite(c.metrics.likes)); return c ? `<span class="num">${fmt(c.metrics.likes)}</span> thích` : timeEl(s.published_at); };
  return `<section class="tile t-model" aria-labelledby="model-h">
    ${tileHead('Model mới', 'model-h', `<a class="link" href="#model">Tất cả</a>`)}
    <p class="keynote k-sm"><b class="num" data-count="${week}" data-v="${week}">${fmt(week)}</b><span>model và bài ra mắt trong 7 ngày</span></p>
    <div class="stack">${list.map(s => row(s, {compact:true, right: right(s)})).join('')}</div>
  </section>`;
}

/* Sources: transparency as a tile. Every dot is one source and its real state at build time. */
function sourcesTile(){
  const bad = D.sources.filter(s => !s.ok), okN = D.sources.length - bad.length;
  return `<section class="tile t-src" aria-labelledby="src-h">
    ${tileHead('Nguồn', 'src-h', `<a class="link" href="#nguon">Chi tiết</a>`)}
    <p class="keynote k-sm"><b class="num">${okN}</b><span>/${D.sources.length} nguồn chạy được lúc ${hhmm(new Date(D.generated_at))}</span></p>
    <span class="dots" role="img" aria-label="${okN} nguồn chạy được, ${bad.length} nguồn lỗi">${[...D.sources].sort((a, b) => b.ok - a.ok).map(s => `<i class="${s.ok ? 'ok' : 'warn'}" title="${esc(s.name)}${s.ok ? '' : ': lỗi'}"></i>`).join('')}</span>
    <p class="src-live" id="src-live">${srcLiveText()}</p>
  </section>`;
}
function srcLiveText(){
  const live = liveState ? [...liveState.values()] : [];
  const okL = live.filter(s => s.ok).length, at = live.map(s => s.at).filter(Boolean).sort((a, b) => b - a)[0];
  return at ? `<span class="dot ${okL ? 'ok breath' : 'warn'}" aria-hidden="true"></span>Lớp trực tiếp: <span class="num">${okL}/${live.length}</span> nguồn đọc lúc ${hhmm(at)}` : `<span class="dot" aria-hidden="true"></span>Lớp trực tiếp đang đọc lần đầu`;
}

/* HF avatars cost one API call per organisation, so only faces on screen are looked up. */
function hydrateVisible(){ hydrateHF(document); }

/* ---------- chapters below the fold ---------- */
function chapterList(c){
  if (c.sec === 'repo') return repoChapter();
  let list = ids(c.sec);
  if (c.sec !== 'hot' && c.sec !== 'upcoming') list = list.slice().sort(byNewest);
  if (!list.length) return `<p class="empty-note">Chưa có dữ liệu cho mục này. Trang không điền tin mẫu.</p>`;
  if (c.sec === 'listen') {
    const v = list.filter(s => ytId(s)).slice(0, 8), rest = list.filter(s => !ytId(s));
    return `<div class="vids">${v.map(s => `<button class="vid${read.has(s.id) ? ' is-read' : ''}" data-sel="${esc(s.id)}"><span class="thumb">${thumbImg(ytId(s), s.title)}<span class="play" aria-hidden="true">${icon('i-play')}</span></span><span class="t">${esc(String(s.title))}</span><span class="k">${esc(pubOf(s))} · ${timeEl(s.published_at)}</span></button>`).join('')}</div>
      <div class="list" data-cap="6">${rest.map(s => row(s)).join('')}</div>`;
  }
  if (c.sec === 'upcoming') {
    return `<div class="list">${list.map(s => { const e = eventOf(s) || {}; const cal = calOf(s);
      const r = row(s, {right: e.start_date ? esc(e.start_date === e.end_date ? e.start_date : `${e.start_date} đến ${e.end_date}`) : 'chưa rõ ngày'});
      return cal ? `<div class="row-tools">${r}${calButtons(cal, `data-cal="${esc(s.id)}"`, String(s.title))}</div>` : r; }).join('')}</div>`;
  }
  if (c.sec === 'hot') { const max = list[0].hot_score || 1;
    return `<div class="list" data-cap="8">${list.map(s => row(s, {right: `<span class="score"><b class="num">${Math.round(s.hot_score)}</b>${meter(s.hot_score, max)}</span>`})).join('')}</div>`; }
  return `<div class="list" data-cap="8">${list.map(s => row(s, {right: rowMeasure(s)})).join('')}</div>`;
}
/* Right-hand measure: the story's own counter when it has one, else its time. */
function rowMeasure(s){
  const c = (s.coverage || []).find(c => c.metrics && Object.values(c.metrics).some(v => Number.isFinite(v)));
  if (!c) return timeEl(s.published_at);
  const [k, v] = Object.entries(c.metrics).find(([, v]) => Number.isFinite(v));
  return `<span class="mv"><span class="lv num" data-live="${esc(c.id)}|${esc(k)}" data-v="${v}">${fmt(v)}</span> ${METRIC[k] || esc(k)}</span><span class="faint">${timeEl(s.published_at)}</span>`;
}

function repoChapter(){
  const list = repoList();
  if (!list) {
    // No repos[] in this snapshot: list measured repositories as they are, without inventing labels.
    const reps = D.stories.filter(s => s.kind === 'repository').sort((a, b) => (b.hot_score || 0) - (a.hot_score || 0));
    return `<p class="chips-note">Nhãn Dùng ngay, Xào nấu được, Nghiên cứu và 8 mảng sẽ hiện khi bản dữ liệu có phần chọn lọc repo. Bản này chưa có, nên dưới đây là repo xếp theo số đo, chưa gắn nhãn.</p>
      ${reps.length ? `<div class="list" data-cap="8">${reps.map(s => row(s, {right: rowMeasure(s)})).join('')}</div>` : '<p class="empty-note">Bản này không có repo nào.</p>'}`;
  }
  const count = id => list.filter(r => r.category === id && (withResearch || r.label !== 'nghien-cuu')).length;
  const research = list.filter(r => r.label === 'nghien-cuu').length;
  const shown = repoPicks(list);
  return `<div class="chips" role="group" aria-label="Chọn mảng bạn quan tâm">
      ${AREAS.map(a => `<button class="chip" data-area="${a.id}" aria-pressed="${areas.has(a.id)}">${icon('i-check')}${esc(a.label)} <span class="n num">${count(a.id)}</span></button>`).join('')}
      ${research ? `<button class="chip" data-research aria-pressed="${withResearch}">${icon('i-check')}Gồm cả Nghiên cứu <span class="n num">${research}</span></button>` : ''}
    </div>
    <p class="chips-note">${areas.size ? `Đang lọc ${areas.size} mảng, lưu trên máy này.` : 'Chưa chọn mảng nào, nên hiện tất cả.'} Mặc định chỉ hiện Dùng ngay và Xào nấu được.</p>
    ${shown.length ? `<div class="list" data-cap="10">${shown.map(r => repoRow(r)).join('')}</div>`
      : `<p class="empty-note">Hôm nay không có repo nào ở mảng đã chọn. <button class="btn-quiet" data-area-clear>Hiện mọi mảng</button></p>`}`;
}

function savedChapter(){
  if (!saved.length) return '';
  return `<section class="tile ch wide" id="da-luu" aria-labelledby="h-da-luu">
    <header class="ch-h"><p class="ch-n"><b class="num">${saved.length}</b></p><div><h2 id="h-da-luu">Đã lưu</h2><p class="aside">Chỉ lưu trên máy này</p></div></header>
    <div class="list">${saved.slice().reverse().map(x => {
      const st = S.get(x.key), rp = x.key.startsWith('repo:') ? R.get(x.key.slice(5)) : null;
      const body = st ? row(st) : rp ? repoRow(rp)
        : `<a class="row" href="${esc(safe(x.url))}" target="_blank" rel="noopener">${avatar({kind:'mono', id:'?', label:x.title}, 'md')}<span class="row-m"><span class="t">${esc(x.title)}</span><span class="k">Không còn trong bản tin hiện tại · mở bài gốc</span></span><span class="r">${timeEl(x.at)}</span></a>`;
      return `<div class="row-tools">${body}<button class="icon-btn" data-unsave="${esc(x.key)}" aria-label="Bỏ lưu ${esc(x.title)}" title="Bỏ lưu">${icon('i-close')}</button></div>`;
    }).join('')}</div></section>`;
}

function liveRows(){
  if (!liveState) return '';
  return [...liveState.values()].map(s => `<div class="srow"><span class="dot ${s.ok === true ? 'ok' : s.ok === false ? 'warn' : ''}"></span>
    <span class="row-m"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>${s.error ? `<span class="err">${esc(s.error)}. Đang giữ số trong bản tin.</span>` : ''}</span>
    <span class="tiny faint">${s.at ? `${s.ok ? `${s.matched} tin khớp · ` : ''}${hhmm(s.at)}` : 'đang đọc'}</span></div>`).join('');
}

function renderChapters(){
  const bad = D.sources.filter(s => !s.ok);
  $('#chapters').innerHTML = `<h2 class="chap-title">Theo mục</h2>${savedChapter()}` + CHAPTERS.map(c => {
    const n = c.sec === 'repo' ? (repoList() ? repoList().length : D.stories.filter(s => s.kind === 'repository').length) : (D.sections[c.sec] || []).length;
    const note = c.sec === 'repo' ? (repoList() ? 'Chọn theo câu hỏi "lấy về dùng được không".' : 'Xếp theo số đo, chưa có nhãn.') : c.note;
    return `<section class="tile ch ${c.wide ? 'wide' : ''}" id="${c.id}" aria-labelledby="h-${c.id}">
      <header class="ch-h"><p class="ch-n"><b class="num">${n}</b><span>${c.sec === 'repo' ? 'repo' : 'tin'}</span></p><div><h2 id="h-${c.id}">${c.title}</h2><p class="aside">${note}</p></div></header>
      ${chapterList(c)}
    </section>`; }).join('') + `
    <section class="tile ch wide" id="nguon" aria-labelledby="h-nguon">
      <header class="ch-h"><p class="ch-n"><b class="num">${D.sources.length - bad.length}</b><span>/${D.sources.length}</span></p><div><h2 id="h-nguon">Nguồn</h2><p class="aside">Nguồn chạy được lúc ${hhmm(new Date(D.generated_at))}. Mỗi nguồn kèm số tin lấy được.</p></div></header>
      <p class="src-sub">Đọc trực tiếp từ trình duyệt, mỗi 90 giây</p>
      <div class="srcgrid" id="live-rows">${liveRows()}</div>
      <p class="src-sub">Trong bản tin</p>
      <div class="srcgrid">${[...D.sources].sort((a, b) => a.ok - b.ok || b.count - a.count).map(s => `<div class="srow">${avatar(faceOfSource({source:s.id, lab:s.lab, publisher:s.publisher}, SRC), 'xs')}
        <span class="row-m"><a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(s.name)}</a>${s.error ? `<span class="err">${esc(s.error)}</span>` : ''}</span><span class="tiny ${s.ok ? 'faint' : 'warn-t'} num">${s.ok ? `${s.count} tin` : 'lỗi'}</span></div>`).join('')}</div>
    </section>`;
  // Long lists start capped and expand in place.
  $$('[data-cap]').forEach(l => {
    const cap = +l.dataset.cap, kids = [...l.children];
    if (kids.length <= cap) return;
    kids.slice(cap).forEach(k => k.hidden = true);
    const b = document.createElement('button'); b.className = 'btn-quiet expand'; b.textContent = `Xem thêm ${nf.format(kids.length - cap)}`;
    b.addEventListener('click', () => { kids.forEach((k, i) => { k.hidden = false; if (i >= cap && !RM.matches) { k.classList.add('arrive'); k.style.setProperty('--i', Math.min(i - cap, 8)); } }); b.remove(); hydrateVisible(); });
    l.after(b);
  });
  const views = D.views && Number.isFinite(D.views.total) ? `Lượt xem trên ai-radar đo lúc ${esc(exact(D.views.measured_at))}, không dùng cookie. ` : '';
  $('#foot').innerHTML = `Dữ liệu tạo lúc ${esc(exact(D.generated_at))} giờ Việt Nam. ${D.ranking ? `Xếp hạng nóng: ${esc(D.ranking.method)}, cửa sổ ${esc(D.ranking.window_hours)} giờ, hiệu chỉnh: ${esc(D.ranking.calibration)}. Đây là cách xếp theo số đo, không phải phán xét tầm quan trọng.` : 'Bản dữ liệu này không mô tả cách xếp hạng nóng.'} Tiêu đề giữ nguyên tiếng Anh như bài gốc. ${views}
    ${storageOk ? 'Mốc đã xem, tin đã đọc, tin đã lưu và mảng bạn chọn chỉ lưu trên máy này.' : 'Trình duyệt đang chặn bộ nhớ cục bộ, nên mốc đã xem, tin đã lưu và mảng bạn chọn chỉ giữ tới khi đóng trang.'}
    <button class="btn-quiet" id="keys-open">Phím tắt (?)</button> <a class="btn-quiet" href="tokens.html">Ngôn ngữ thiết kế</a>`;
  hydrateVisible();
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
  $('#src-state').innerHTML = `<span class="dot ${bad ? 'warn' : 'ok'}"></span><span class="num">${D.sources.length - bad}/${D.sources.length}</span><span class="w"> nguồn</span>`
    + (lastAt ? `<span class="live-at"><span class="dot ${liveBad === live.length ? 'warn' : 'ok breath'}" aria-hidden="true"></span><span class="w">trực tiếp </span>${hhmm(lastAt)}</span>` : '') + views;
  $('#src-state').setAttribute('aria-label', `${D.sources.length - bad} trên ${D.sources.length} nguồn chạy được${bad ? `, ${bad} lỗi` : ''}`
    + (lastAt ? `. Lớp trực tiếp: ${liveOk} trên ${live.length} nguồn đọc được lúc ${hhmm(lastAt)}` : '') + (views ? `. ${fmt(D.views.total)} lượt xem` : ''));
  const sl = $('#src-live'); if (sl) sl.innerHTML = srcLiveText();
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
  return `<div class="sh-head">${avatar(faceSt(st), 'lg')}<h2>${esc(String(st.title))}</h2></div>
    ${id ? `<span class="thumb">${thumbImg(id, st.title)}</span>` : ''}
    ${st.summary ? `<p class="sum">${esc(st.summary)}</p>` : ''}
    ${st.hot_score != null ? `<div class="sh-score">${ring(st.hot_score, 'Điểm nóng')}<p>Nóng vì ${reasonHTML(st)}</p></div>` : ''}
    <dl class="facts">
      <dt>Loại</dt><dd>${kindName(st)}</dd>
      <dt>Thời gian</dt><dd>${ev ? `${esc(ev.start_date)}${ev.end_date !== ev.start_date ? ` đến ${esc(ev.end_date)}` : ''} (chỉ có ngày)` : `${esc(exact(st.published_at))}${st.time_basis === 'repository_created' ? ' (ngày tạo repo, không phải ngày phát hành)' : ''}`}</dd>
      ${ev ? `<dt>Địa điểm</dt><dd>${esc(ev.location || 'chưa rõ')}</dd><dt>Xác minh</dt><dd>${esc(ev.verified_at)}</dd>` : ''}
      <dt>Số nguồn</dt><dd class="num">${st.source_count}</dd>
      ${st.hot_score != null ? '' : `<dt>Điểm nóng</dt><dd class="faint">Chưa có số đo</dd>`}
      ${sig ? `<dt>Đo lúc</dt><dd>${esc(exact(sig.observed_at))}</dd>` : ''}
      ${v != null ? `<dt>Lượt xem</dt><dd>${viewsEl(v, st.id)} trên ai-radar</dd>` : ''}
    </dl>
    <div class="acts">
      <a class="btn primary" href="${esc(safe(st.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Mở bài gốc ${icon('i-out')}</a>
      <button class="btn second" data-save="${esc(st.id)}" aria-pressed="${sv}">${icon('i-save')}${sv ? 'Đã lưu' : 'Lưu đọc sau'}</button>
      ${calButtons(cal, `data-cal="${esc(st.id)}"`, String(st.title))}
    </div>
    <p class="hint">Phím: <kbd>O</kbd> mở bài gốc · <kbd>S</kbd> lưu${cal ? ' · <kbd>L</kbd> tải tệp lịch' : ''} · <kbd>J</kbd> <kbd>K</kbd> tin kế · <kbd>Esc</kbd> đóng</p>
    <p class="tlh">Các nguồn, theo thời gian</p>
    <ol class="tl">${cov.map(c => `<li>${avatar(faceOfSource(c, SRC), 'xs')}<span class="tl-m"><span class="when">${esc(srcName(c.source))} · ${timeEl(c.published_at)}</span>
      <a href="${esc(safe(c.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">${esc(String(c.title))}</a>
      ${metricsHTML(c) ? `<span class="m">${metricsHTML(c)}</span>` : ''}
      ${c.discussion_url ? `<a class="tl-d" href="${esc(safe(c.discussion_url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Thảo luận</a>` : ''}</span></li>`).join('')}</ol>`;
}
function detailRepo(r){
  const key = 'repo:' + r.id, sv = savedKey(key), cmd = installOf(r);
  const area = AREAS.find(a => a.id === r.category);
  const sig = r.signals && typeof r.signals === 'object' ? Object.entries(r.signals).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v)) : [];
  return `<div class="sh-head">${avatar(faceOfRepo(r), 'lg')}<h2>${esc(r.full_name)}</h2></div>
    <p class="sum">${labChip(r.label)} ${area ? esc(area.label) : 'Chưa xếp mảng'}</p>
    ${Number.isFinite(r.stars) ? `<p class="keynote k-sm"><b class="num">${fmt(r.stars)}</b><span>${r.source === 'hf' ? 'lượt thích' : 'sao'}</span></p>` : ''}
    ${r.description ? `<p class="sum">${esc(r.description)}</p>` : ''}
    ${r.why ? `<p class="sum"><b>Vì sao đáng xem:</b> ${esc(r.why)}</p>` : ''}
    ${cmd ? copyBtn(cmd) : ''}
    <dl class="facts">
      <dt>Nguồn</dt><dd>${r.source === 'hf' ? 'Hugging Face' : 'GitHub'}</dd>
      ${repoStars(r) ? `<dt>Số đo</dt><dd>${repoStars(r)}</dd>` : ''}
      <dt>License</dt><dd>${esc(r.license || 'không rõ')}${r.license_flag ? `<br><span class="lic">${icon('i-warn')}${esc(r.license_flag)}</span>` : ''}</dd>
    </dl>
    ${sig.length ? `<p class="tlh">Dấu hiệu đã đo</p><ul class="sig">${sig.map(([k, v]) => `<li><span class="faint">${esc(k)}:</span> ${esc(typeof v === 'boolean' ? (v ? 'có' : 'không') : v)}</li>`).join('')}</ul>` : ''}
    <div class="acts">
      <a class="btn primary" href="${esc(safe(r.url))}" target="_blank" rel="noopener" data-read="${esc(key)}">Mở repo ${icon('i-out')}</a>
      <button class="btn second" data-save="${esc(key)}" aria-pressed="${sv}">${icon('i-save')}${sv ? 'Đã lưu' : 'Lưu đọc sau'}</button>
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
  hydrateHF(body);
  if (wasOpen && !RM.matches) { body.classList.remove('swap'); void body.offsetWidth; body.classList.add('swap'); }
  sheet.classList.add('on'); sheet.setAttribute('aria-hidden', 'false'); sheet.inert = false;
  $('#scrim').classList.add('on');
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
  $('#scrim').classList.remove('on');
  $$('[aria-pressed="true"][data-sel],[aria-pressed="true"][data-repo]').forEach(b => b.setAttribute('aria-pressed', 'false'));
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

/* ---------- save, calendar, copy, toast ---------- */
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
async function copyCmd(btn){
  const cmd = btn.dataset.copy;
  try {
    await navigator.clipboard.writeText(cmd);
    btn.classList.add('is-done'); btn.querySelector('.cmd-l').textContent = 'Đã chép';
    setTimeout(() => { btn.classList.remove('is-done'); btn.querySelector('.cmd-l').textContent = 'Chép'; }, 1600);
    toast('Đã chép lệnh cài');
  } catch { toast('Trình duyệt không cho chép. Hãy bôi đen lệnh để chép'); }
}

/* ---------- theme: follows the system until the reader picks; the pick lives on this machine ---------- */
function applyTheme(t){
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  const b = $('#theme'); if (b) { b.setAttribute('aria-pressed', String(dark)); b.setAttribute('aria-label', dark ? 'Chuyển sang nền sáng' : 'Chuyển sang nền tối'); }
}
function toggleTheme(){
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  const run = () => { applyTheme(next); store.set('air2:theme', next); };
  if (document.startViewTransition && !RM.matches) document.startViewTransition(run); else run();
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
  $$('#board [data-count]').forEach(c => { c.dataset.v = 0; countTo(c, Number(c.dataset.count)); }); }

/* ---------- events ---------- */
document.addEventListener('click', e => {
  const t = e.target;
  const save = t.closest('[data-save]'); if (save) { toggleSave(save.dataset.save); return; }
  const uns = t.closest('[data-unsave]'); if (uns) { toggleSave(uns.dataset.unsave); return; }
  const cp = t.closest('[data-copy]'); if (cp) { copyCmd(cp); return; }
  const cal = t.closest('[data-cal]'); if (cal) { e.preventDefault(); const c = calOf(S.get(cal.dataset.cal)); if (c) addToCalendar(c); return; }
  const cl = t.closest('[data-cal-live]'); if (cl) { e.preventDefault(); addToCalendar(liveCal((D.live || []).find(v => v.video_id === cl.dataset.calLive))); return; }
  const area = t.closest('[data-area]'); if (area) { const a = area.dataset.area; areas.has(a) ? areas.delete(a) : areas.add(a); store.set('air2:areas', [...areas]); rerenderRepos(); return; }
  if (t.closest('[data-area-clear]')) { areas.clear(); store.set('air2:areas', []); rerenderRepos(); return; }
  if (t.closest('[data-research]')) { withResearch = !withResearch; store.set('air2:research', withResearch); rerenderRepos(); return; }
  if (t.closest('#fresh-go')) { applyPending(); return; }
  if (t.closest('#mark')) { store.set('air2:lastSeen', D.generated_at); lastSeen = D.generated_at; firstVisit = false; renderAll(); toast('Đã đánh dấu đã xem hết'); return; }
  if (t.closest('#keys-open')) { $('#keys').showModal(); return; }
  if (t.closest('#keys-x')) { $('#keys').close(); return; }
  if (t.closest('#theme')) { toggleTheme(); return; }
  if (t.closest('#scrim')) { close(); return; }
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
addEventListener('resize', spy);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(store.get('air2:theme', null)));
setInterval(() => $$('[data-ago]').forEach(el => { el.textContent = ago(el.dataset.ago); }), 60_000);

/* ---------- start ---------- */
function showError(msg){
  const b = $('#board'); b.classList.remove('is-loading'); b.removeAttribute('aria-busy');
  b.innerHTML = `<div class="tile t-empty" role="alert">${avatar({kind:'mono', id:'!', label:'lỗi'}, 'lg')}<h2>Chưa mở được bản tin</h2><p class="muted">${esc(msg)}. Trang không thay bằng tin mẫu.</p><button class="btn primary" id="retry">Thử lại</button></div>`;
  $('#retry').addEventListener('click', () => location.reload());
}
watchImageErrors();
applyTheme(store.get('air2:theme', null));
fetch(DATA_URL, {cache:'no-store'}).then(r => { if (!r.ok) throw new Error(`Máy chủ trả HTTP ${r.status} cho ${DATA_URL}`); return r.json(); }).then(j => {
  if (!j || j.schema_version !== 2 || !Array.isArray(j.stories) || !j.sections) throw new Error('Tệp dữ liệu không đúng hợp đồng v2');
  D = j; build(); renderAll();
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

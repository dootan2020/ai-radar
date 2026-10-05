/* ai·radar · the site root since 05/10 (owner, 05/10 ~01:30: the feed replaces the bento home).
   Owner, 04/10 20:28: flat like the Edge start page and Google Discover. No borders, no accent bars, every card led by
   a picture. Pictures are the ones each source publishes, or a labelled AI illustration from the pipeline; a story
   without either gets a flat cover drawn from its own data.

   One function decides every story picture: pickImage(). It walks IMAGE_PROVIDERS in order and falls back to the
   cover.

   "Đáng đọc" round (owner, 04/10 21:35): what to read first. One score per story from measured signals only (WORTH,
   worthOf), a block of 3 to 5 stories on top with a reason line in real numbers, a reason chip per card, a sort switch,
   and "Biên tập chọn" only from editor-picks.json.

   Carried over from the bento home (now bento.html, rollback only), in the feed's own look: the edition and search
   links (static, in index.html), the new / seen / skipped marks with the same keys and priority, the "N tin mới" pill
   that goes to the first new story, the fresh-snapshot pill, the stale-data line, saved stories, the repository lists,
   calendar export, live counters, every source's state, keyboard shortcuts, and every address the bento home answered
   (#tin/<id>, and the section anchors the search page links to). */

import { esc, fmt, avatar, avatarStack, faceOfStory, faceOfSource, hydrateHF, monogram, watchImageErrors, ytIdOf } from './faces.js';
import { ago, dayKey, hhmm, TZ, streamedAge, scheduleText, daysLeftHTML, eventRange } from './time-text.js';
import { KIND, METRIC } from './words.js';
import { shown, uniqCoverage } from './titles.js';
import { canCalendar, downloadIcs, gcalURL, verifiedNote } from './calendar.js';
import { freshness, freshnessText } from './freshness.js';

/* Same-origin JSON only; ?data=data/<file>.json lets a maintainer load another snapshot from site/data/ (as on the
   bento home). The first request matches index.html's preload (same mode, no cache option), so it is reused. */
const qp = new URLSearchParams(location.search).get('data');
const customData = !!qp && /^data\/[\w.-]+\.json$/.test(qp);
const DATA_URL = customData ? qp : 'data/radar-ui.json';
const SOURCES = customData ? [qp] : [DATA_URL, 'data/radar.json'];
const IMAGES_URL = 'feed-images.json';
const PICKS_URL = 'editor-picks.json';   // the owner's own picks; the only thing allowed to say "Biên tập chọn"
/* The bento home's keys, so a returning reader keeps what they read, skipped, saved and chose there. */
const K = { theme: 'air2:theme', read: 'air2:read', skipped: 'air2:skipped', lastSeen: 'air2:lastSeen', saved: 'air2:saved',
  sort: 'air2:sort', repoView: 'air2:repoView', repoWindow: 'air2:repoWindow', repoTotal: 'air2:repoTotal', areas: 'air2:areas' };
const LEGACY = { read: 'airtl:read', saved: 'airtl:saved', sort: 'airtl:sort' };   // the 04/10 prototype's keys, folded in once
const PAGE_FIRST = 40, PAGE_MORE = 24;
const SNAPSHOT_EVERY_MS = 180_000;

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const icon = id => `<svg class="i" aria-hidden="true"><use href="#${id}"/></svg>`;
const nf1 = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 });
const EXACT = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'full', timeStyle: 'short', timeZone: TZ });
const ms = iso => new Date(iso).getTime() || 0;
const RM = matchMedia('(prefers-reduced-motion: reduce)');
const CSSq = s => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&');
/* Vietnamese letters with diacritics: a text without any of them is English and is marked lang="en". */
const VI_RE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;
const langAttr = text => VI_RE.test(text || '') ? '' : ' lang="en"';
/* Same formula as faces.js (not exported there), so a cover and its avatar share a tint. */
const monoHue = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };

/* localStorage may be absent or throw (private mode, blocked cookies): fall back to memory for this tab. */
const mem = new Map();
let storageOk = true;
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? (mem.has(k) ? mem.get(k) : d) : JSON.parse(v); } catch { storageOk = false; return mem.has(k) ? mem.get(k) : d; } },
  set(k, v) { mem.set(k, v); try { localStorage.setItem(k, JSON.stringify(v)); } catch { storageOk = false; } }
};
const asArray = v => Array.isArray(v) ? v : [];

let D = null;
let SRC = new Map();
const IMG = {};               // verified picture per address: {src, via}
let allStories = [];
let STORY = new Map();
let STORY_ANY = new Map();    // every story in the snapshot, also outside the window (sections, saved, #tin/<id>)
let bigSet = new Set();
let HOT = [];
let filter = 'all';
let sortMode = 'worth';       // 'worth' (Đáng đọc nhất) or 'new' (Mới nhất); the reader's choice is remembered
const PICKS = new Map();      // story id -> {note}, from editor-picks.json, in the file's order
let RAW_PICKS = [];
let PICKLIST = [];            // the "Đáng đọc hôm nay" block: editor picks first, then the highest scores
let seq = [], pos = 0, shownCards = 0, totalCards = 0;

/* ---------- new, seen, skipped (the bento home's rules, tests/test_tin_moi.py) ----------
   new: published after the reader's last look; seen: opened; skipped: scrolled past without opening.
   Priority: seen, then skipped, then new. The last look moves on engagement (five seconds or the first scroll), when
   the page is hidden or left, and when the reader applies a fresh snapshot; never only by a button. */
const read = new Set([...asArray(store.get(K.read, [])), ...asArray(store.get(LEGACY.read, []))]);
const skipped = new Set(asArray(store.get(K.skipped, [])));
let saved = asArray(store.get(K.saved, [])).filter(x => x && typeof x.key === 'string');
for (const id of asArray(store.get(LEGACY.saved, []))) if (typeof id === 'string' && !saved.some(x => x.key === id)) saved.push({ key: id, title: '', url: '', at: new Date().toISOString() });
const savedHas = id => saved.some(x => x.key === id);
let lastSeen = null, firstVisit = false;
let arrived = new Set();      // stories that came with a fresh snapshot the reader just applied
const isNew = st => !!lastSeen && !!st.published_at && st.published_at > lastSeen && ms(st.published_at) <= Date.now();
function storyStatus(id, st) {
  if (!id) return 'none';
  if (read.has(id)) return 'seen';
  if (skipped.has(id)) return 'skipped';
  if (arrived.has(id) || (st && isNew(st))) return 'new';
  return 'none';
}
const MARK = {
  new: '<span class="new-mark" aria-hidden="true"></span><span class="sr">Mới. </span>',
  seen: `<span class="seen-mark" aria-hidden="true">${icon('i-check')}</span><span class="sr">Đã xem. </span>`,
  skipped: '<span class="skipped-mark" aria-hidden="true"></span><span class="sr">Bỏ qua chưa xem. </span>',
  none: '',
};
const STATUS_CLASS = { seen: 'is-read', new: 'is-new', skipped: 'is-skipped', none: '' };
const markHTML = st => `<span class="st-mark">${MARK[storyStatus(st.id, st)]}</span>`;
const statusClass = st => STATUS_CLASS[storyStatus(st.id, st)];
function commitLastSeen(ts = D ? D.generated_at : null) {
  if (!ts) return;
  const stored = store.get(K.lastSeen, null);
  if (!stored || ts > stored) store.set(K.lastSeen, ts);
}
/* Every element that stands for a story carries data-sid; its mark and class follow the story's state in place. */
function paintStatus(id) {
  const st = STORY_ANY.get(id), s = storyStatus(id, st);
  $$(`[data-sid="${CSSq(id)}"]`).forEach(el => {
    el.classList.remove('is-read', 'is-new', 'is-skipped');
    if (STATUS_CLASS[s]) el.classList.add(STATUS_CLASS[s]);
    el.dataset.status = s;
    const m = el.querySelector('.st-mark'); if (m) m.innerHTML = MARK[s];
  });
}
function markRead(id) {
  if (!id || read.has(id)) return;
  read.add(id); arrived.delete(id);
  if (skipped.delete(id)) store.set(K.skipped, [...skipped].slice(-2000));
  store.set(K.read, [...read].slice(-3000));
  paintStatus(id);
}
function markSkipped(id) {
  if (!id || read.has(id) || skipped.has(id) || arrived.has(id)) return;
  skipped.add(id);
  store.set(K.skipped, [...skipped].slice(-2000));
  paintStatus(id);
}
let skipObserver = null;
function observeSkips() {
  if (typeof IntersectionObserver === 'undefined') return;
  if (!skipObserver) skipObserver = new IntersectionObserver(entries => {
    for (const e of entries) {
      const el = e.target, id = el.dataset.sid;
      if (!id || read.has(id)) continue;
      if (e.isIntersecting) el._seen = true;
      else if (el._seen && e.boundingClientRect.bottom <= ($('#bar') ? $('#bar').offsetHeight : 64) + 12) markSkipped(id);
    }
  }, { threshold: [0, 0.2] });
  $$('[data-sid]').forEach(el => { if (!el._observed) { el._observed = true; skipObserver.observe(el); } });
}

/* ---------- data ---------- */
/* Same-origin requests only, in the default mode, so index.html's preload of the snapshot is reused. */
async function fetchJSON(url, init = {}) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 10000);
  try {
    const r = await fetch(url, { signal: ctl.signal, ...init });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally { clearTimeout(timer); }
}

/* editor-picks.json: {picks: [{id | url, note?, until?}]}. Empty by default. A missing or broken file means no picks. */
async function loadPicks() {
  try {
    const j = await fetchJSON(PICKS_URL, { cache: 'no-cache' });
    return Array.isArray(j && j.picks) ? j.picks : [];
  } catch (e) { console.warn('editor-picks.json unavailable; no editor picks', e); return []; }
}
function matchPicks(list) {
  const now = Date.now();
  PICKS.clear();
  for (const p of list) {
    if (PICKS.size >= WORTH.picksMax) { console.info('editor picks beyond the first', WORTH.picksMax, 'are ignored'); break; }
    if (!p || typeof p !== 'object' || (!p.id && !p.url)) continue;
    // "until" must be a readable date in the future; an unreadable one counts as expired rather than pinning forever.
    if (p.until != null && !(Date.parse(p.until) > now)) continue;
    const st = allStories.find(s => (p.id && s.id === p.id) ||
      (p.url && (s.url === p.url || (s.coverage || []).some(c => c.url === p.url))));
    if (!st) { console.info('editor pick not in the current window', p.id || p.url); continue; }
    if (!PICKS.has(st.id)) PICKS.set(st.id, { note: typeof p.note === 'string' ? p.note.trim().slice(0, 240) : '' });
  }
}

async function loadImages() {
  try {
    const j = await fetchJSON(IMAGES_URL);
    // New format {_meta, images}; the previous round wrote a flat {url: src} map.
    const map = j && j.images ? j.images : (j || {});
    for (const [u, v] of Object.entries(map)) {
      if (u.startsWith('_')) continue;
      if (typeof v === 'string') IMG[u] = { src: v, via: 'og:image' };
      else if (v && v.src) IMG[u] = v;
    }
  } catch (e) { console.warn('feed-images.json unavailable; using feed media and source addresses only', e); }
}

async function loadData(init = {}) {
  let lastErr;
  for (const url of SOURCES) {
    try {
      const j = await fetchJSON(url, init);
      if (j && j.schema_version === 2 && Array.isArray(j.stories)) return j;
      if (j && Array.isArray(j.updates)) {
        return {
          schema_version: 1, generated_at: j.generated_at, sources: j.sources || [], repos: [], events: [], live: [],
          stories: j.updates.map(u => ({ id: u.id, title: u.title, url: u.url, summary: u.summary, published_at: u.published_at,
            kind: u.kind, source_count: 1, coverage: [{ id: u.id, source: u.source, lab: u.lab, title: u.title, url: u.url, metrics: {} }] }))
        };
      }
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error('Không nạp được dữ liệu');
}

/* ---------- small readers ---------- */
const SHORT_NAMES = {
  'github-ai': 'GitHub',
  'github-trending': 'GitHub',
  'techcrunch-ai': 'TechCrunch',
  'ars-technica-ai': 'Ars Technica',
  'the-verge-ai': 'The Verge',
  'lobsters-ai': 'Lobsters',
};
const srcName = id => SHORT_NAMES[id] || String((SRC.get(id) || {}).name || id || '').replace(/\s*\(.*?\)\s*/g, ' ').trim();
const covsOf = st => uniqCoverage(st.coverage, srcName);
const nSrc = st => covsOf(st).length;
const exact = iso => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? 'không rõ' : EXACT.format(d); };
/* Relative times stay honest while the tab is open: every <time data-ago> is refreshed each minute. */
const timeEl = iso => `<time datetime="${esc(iso)}" data-ago="${esc(iso)}" title="${esc(exact(iso))}">${esc(ago(iso))}</time>`;

/* A measure also names the coverage item and metric it came from ("covId|metric"), so the live counters (live.js, as
   on the bento home) can refresh that number in place. */
const PREFER = ['points', 'score', 'stars', 'upvotes', 'likes', 'trending_score', 'downloads', 'comments'];
function measureOf(st) {
  const m = st.hot_signals && st.hot_signals.measurement;
  if (m && Number.isFinite(m.value)) {
    const c = (st.coverage || []).find(c => c.source === m.source && c.metrics && m.metric in c.metrics);
    return { value: m.value,
      word: METRIC[m.metric] || m.metric, where: srcName(m.source), live: c && c.id ? `${c.id}|${m.metric}` : null,
      speed: Number.isFinite(m.velocity_per_hour) && m.velocity_per_hour > 0 ? m.velocity_per_hour : null };
  }
  for (const key of PREFER) for (const c of st.coverage || []) {
    const v = c.metrics && c.metrics[key];
    if (typeof v === 'number' && Number.isFinite(v)) return { value: v, word: METRIC[key] || key, where: srcName(c.source), live: c.id ? `${c.id}|${key}` : null, speed: null };
  }
  return null;
}
const numB = m => `<b class="num"${m.live ? ` data-live="${esc(m.live)}"` : ''}>${fmt(m.value)}</b>`;

/* The headline a reader sees: the story's Vietnamese title, else a coverage item's Vietnamese title (paired with that
   item's own original), else the original. The old page skipped the coverage-level translation, so the lead read in
   English while a Vietnamese title sat in the data. When the headline comes from a coverage item, `cov` is that item:
   the card then names that item's source and links to that item's address, so headline, source and link agree. */
function titleOf(st) {
  const ok = (o, v) => typeof v === 'string' && v.trim() && v.trim() !== String(o || '').trim();
  if (ok(st.title, st.title_vi)) return { text: st.title_vi.trim(), orig: st.title, cov: null };
  for (const c of st.coverage || []) if (ok(c.title, c.title_vi)) return { text: c.title_vi.trim(), orig: c.title, cov: c };
  return { text: String(st.title || ''), orig: null, cov: null };
}
/* Under a translated headline: a "Translated" chip, a gap, then the original. Never glued together. */
const origLine = t => !t.orig ? '' :
  `<p class="card-orig"><span class="mt" aria-hidden="true" title="Bản dịch máy; dòng này là tiêu đề gốc">Translated</span><span class="sr" lang="vi">Bản dịch máy. Tiêu đề gốc: </span><span class="orig-text"${langAttr(t.orig)}>${esc(t.orig)}</span></p>`;

/* ==========================================================================
   "ĐÁNG ĐỌC": WHAT TO READ FIRST
   Owner, 04/10 21:35: "có một tiêu chí gì đó để người dùng nên xem cái nào? các tin tức ở đây có trọng số chưa?"
   One score per story from four signals the feed already carries. Nothing here is typed in by hand.
     attention  hot_score (percentile of the story's number within its own source, times freshness; see `ranking`
                in the feed). Counted only when the story carries a measurement: without one, the feed's hot_score
                comes from "N nguồn độc lập cùng đưa", which breadth below already counts.
     breadth    independent publishers carrying the same story (uniqCoverage: one entry per publisher).
     freshness  hours since published_at, measured from the snapshot's generated_at, halving every halfLifeH.
                Only for stories without a measurement: a measured story's hot_score already decays with age, so
                adding freshness again would count its age twice.
      firstHand  a lab publishing the story itself (coverage `lab`), or the researchers' own paper (kind 'paper').
    score = (attention + breadth + freshness) x (firstHand ? WORTH.firstHand : 1)
    firstHand multiplies instead of adding, so a lab's routine post with nothing else going for it (most of the
    window's 24 first-hand stories are AWS and NVIDIA tutorials) never outranks a story people are reading.
    THE WEIGHTS ARE A FIRST GUESS (04/10). They will be calibrated on a week of real snapshots: what readers open,
    what the daily edition keeps, what an editor would have chosen (plans/reports/feed-dang-doc-report.md).
    The "Cách chấm" note on the page is written from this object, so the page and the code cannot disagree.
    ========================================================================== */
const WORTH = {
  attention: 35, attentionFull: 60,   // points; full at hot_score 60 (the window's top on 04/10 ran from 57 to 69)
  breadth: 35, breadthFull: 4,        // points; 0 for one publisher, full at 4 independent publishers
  freshness: 15, halfLifeH: 24,       // points at publication (unmeasured stories); half after 24 h, a quarter after 48 h
  firstHand: 1.3,                     // multiplier for a first-hand story
  hotLabel: 20,                       // hot_score from which a card says "Đang bàn nhiều" or "Đang được chú ý"
  picksMax: 5,                        // "Đáng đọc hôm nay" shows up to 5; fewer only when fewer stories have evidence
  sameEvent: 0.34,                    // title-word overlap from which two stories count as one event in the block
};

/* A source's `lab` names who publishes it. Not for this one: a trending list of other people's models, whose lab
   field names the platform (Hugging Face), not the model's author. */
const NOT_FIRST_HAND = new Set(['hf-trending']);
const LAB_NAME = { openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', meta: 'Meta', microsoft: 'Microsoft',
  nvidia: 'NVIDIA', amazon: 'Amazon', mistral: 'Mistral', xai: 'xAI', deepseek: 'DeepSeek', qwen: 'Qwen', huggingface: 'Hugging Face' };
const labOf = c => (c && (c.lab || (SRC.get(c.source) || {}).lab)) || '';
function firstHandOf(st) {
  const own = (st.coverage || []).filter(c => labOf(c) && !NOT_FIRST_HAND.has(c.source))
    .sort((a, b) => ms(a.published_at) - ms(b.published_at))[0];
  if (own) { const name = LAB_NAME[labOf(own)] || labOf(own); return { label: `${name} công bố`, why: `${name} công bố trực tiếp` }; }
  if (st.kind === 'paper') return { label: 'Bài báo gốc', why: 'bài báo gốc của nhóm nghiên cứu' };
  return null;
}

let GEN = 0;                  // the snapshot's generated_at: ages count from it, so a score can be recomputed from the file
const WORTHS = new Map();
function worthOf(st) {
  let w = WORTHS.get(st.id);
  if (w) return w;
  const meas = st.hot_signals && st.hot_signals.measurement;
  const hot = meas && Number.isFinite(st.hot_score) ? Math.max(0, st.hot_score) : 0;
  const n = nSrc(st);
  const fh = firstHandOf(st);
  if (typeof st.worth_score === 'number' && st.worth_parts) {
    w = {
      score: st.worth_score,
      parts: st.worth_parts,
      hot,
      n,
      fh,
      metric: meas ? meas.metric : null,
      evidence: !!fh || n >= 2 || hot > 0
    };
    WORTHS.set(st.id, w);
    return w;
  }
  const ageH = Math.max(0, (GEN - ms(st.published_at)) / 36e5);
  const parts = {
    attention: WORTH.attention * Math.min(1, hot / WORTH.attentionFull),
    breadth: WORTH.breadth * Math.min(1, Math.max(0, n - 1) / (WORTH.breadthFull - 1)),
    freshness: WORTH.freshness * Math.pow(0.5, ageH / WORTH.halfLifeH),
  };
  const score = (parts.attention + parts.breadth + parts.freshness) * (fh ? WORTH.firstHand : 1);
  w = { score, parts, hot, n, fh, metric: meas ? meas.metric : null, evidence: !!fh || n >= 2 || hot > 0 };
  WORTHS.set(st.id, w);
  return w;
}

/* The small label on a card: the one strongest reason it is there, or nothing when the only reason is its age. */
const DISCUSSED = new Set(['points', 'score', 'comments', 'upvotes']);
function reasonOf(st) {
  if (PICKS.has(st.id)) return { text: 'Biên tập chọn', editor: true };
  const w = worthOf(st);
  if (w.fh) return { text: w.fh.label };
  const loud = w.hot >= WORTH.hotLabel;
  const att = (w.parts && w.parts.attention) || 0;
  const brd = (w.parts && w.parts.breadth) || 0;
  if (w.n >= 2 && (!loud || brd >= att)) return { text: `${w.n} nguồn đưa tin` };
  if (loud) return { text: DISCUSSED.has(w.metric) ? 'Đang bàn nhiều' : 'Đang được chú ý' };
  return null;
}
const reasonTag = st => {
  const r = reasonOf(st);
  return r ? `<span class="why-tag${r.editor ? ' is-editor' : ''}"><span class="sr">Vì sao có mặt: </span>${esc(r.text)}</span>` : '';
};

/* "Vì sao nên đọc": facts only, each one a field of the feed. At most four parts, the age always last. */
function worthWhy(st) {
  const w = worthOf(st), m = measureOf(st), parts = [];
  if (w.fh) parts.push(esc(w.fh.why));
  if (w.n >= 2) parts.push(`<b class="num">${w.n}</b> nguồn cùng đưa tin`);
  if (m) parts.push(`${numB(m)} ${esc(m.word)}${m.where ? ` trên ${esc(m.where)}` : ''}`);
  if (m && m.speed && parts.length < 3) parts.push(`tăng <b class="num">${nf1.format(m.speed)}</b> ${esc(m.word)} mỗi giờ`);
  parts.push(`đăng ${esc(ago(st.published_at).replace(/^Hôm qua/, 'hôm qua'))}`);
  return parts.join(' · ');
}

/* The pipeline sometimes leaves one event as two stories (two outlets, two headlines). In the five-story block that
   reads as a repeat, so a story whose headline shares most of its words with one already picked is skipped there.
   It stays in the feed below. */
const STOP = new Set(('the and for with from that this its are was has have will into over after about says said than '
  + 'then what when your their they them how why who now new via').split(' '));
const WORDS = new Map();
const wordsOf = st => {
  if (!WORDS.has(st.id)) WORDS.set(st.id, new Set(String(st.title || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .split(/[^a-z0-9]+/).filter(x => x.length >= 3 && !STOP.has(x))));
  return WORDS.get(st.id);
};
function sameEvent(a, b) {
  const A = wordsOf(a), B = wordsOf(b);
  if (!A.size || !B.size) return false;
  let k = 0;
  A.forEach(x => { if (B.has(x)) k++; });
  return k / (A.size + B.size - k) >= WORTH.sameEvent;
}

const byWorth = (a, b) => worthOf(b).score - worthOf(a).score || ms(b.published_at) - ms(a.published_at);
const byNew = (a, b) => ms(b.published_at) - ms(a.published_at);
const pinFirst = (a, b) => (PICKS.has(b.id) ? 1 : 0) - (PICKS.has(a.id) ? 1 : 0);
/* Every list on the page goes through here: editor picks first, then the reader's chosen order. */
const ordered = list => [...list].sort((a, b) => pinFirst(a, b) || (sortMode === 'new' ? byNew : byWorth)(a, b));

const isNewsCov = c => c && c.source !== 'hn-ai' && c.publisher !== 'hacker-news';
const newsCovsOf = st => covsOf(st).filter(isNewsCov);
const nNewsSrc = st => newsCovsOf(st).length;

function choosePicks() {
  const out = [...PICKS.keys()].map(id => STORY.get(id)).filter(st => st && nNewsSrc(st) >= 2).slice(0, 3);
  const candidates = allStories.filter(st => !PICKS.has(st.id) && nNewsSrc(st) >= 2 && worthOf(st).evidence).sort(byWorth);
  if (!out.length) {
    const photoLeadIndex = candidates.findIndex(st => pickImage(st).kind === 'photo');
    if (photoLeadIndex >= 0) {
      out.push(candidates.splice(photoLeadIndex, 1)[0]);
    }
  }
  for (const st of candidates) {
    if (out.length >= 3) break;
    if (!out.some(o => sameEvent(o, st))) out.push(st);
  }
  if (out.length < 3) {
    const fallback = allStories.filter(st => !PICKS.has(st.id) && !out.includes(st) && nNewsSrc(st) >= 2 && worthOf(st).evidence).sort(byWorth);
    for (const st of fallback) {
      if (out.length >= 3) break;
      if (!out.some(o => sameEvent(o, st))) out.push(st);
    }
  }
  return out;
}

/* ==========================================================================
   THE IMAGE SEAM. Every story picture comes from pickImage(st).
   Returns {src, via, kind}: kind 'photo' (an editorial picture: text may sit on it), 'graphic' (a generated card such
   as GitHub's social preview: text goes below it), or 'cover' (no published picture; drawn from data, see coverFor).
   To plug in AI-generated or stock pictures later, add a provider to IMAGE_PROVIDERS before the cover fallback, with
   its own `via` (for example 'ai' or 'stock') so the report and the page can always tell them apart.
   ========================================================================== */
const KIND_OF_VIA = { 'feed-media': 'photo', 'og:image': 'photo', 'linked-article': 'photo', 'youtube': 'photo',
  'github-social': 'graphic', 'hf-thumbnail': 'graphic', 'ai': 'photo' };
const asPick = (src, via) => ({ src, via, kind: KIND_OF_VIA[via] || 'photo' });

function fromVerifiedMap(st) {
  for (const u of [st.url, ...(st.coverage || []).map(c => c.url)]) {
    const v = u && IMG[u];
    if (v && v.src) return asPick(v.src, v.via || 'og:image');
  }
  return null;
}
function fromFeedMedia(st) {
  for (const c of st.coverage || []) for (const m of c.media || []) {
    if ((m.type === 'image' || /^image\//.test(m.mime_type || '')) && /^https:\/\//.test(m.url || '')) return asPick(m.url, 'feed-media');
  }
  return null;
}
/* Pictures a source publishes at a predictable address. The fetcher verified these for the snapshot it saw; the
   client derives them too, so stories that arrived after that run still get them. A broken one falls back to the cover. */
function fromSourceAddress(st) {
  const yt = ytIdOf({ coverage: [{ url: st.url }, ...(st.coverage || [])] });
  if (yt) return asPick(`https://i.ytimg.com/vi/${yt}/hqdefault.jpg`, 'youtube');
  for (const u of [st.url, ...(st.coverage || []).map(c => c.url)]) {
    const g = /^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/.exec(u || '');
    if (g && !['orgs', 'topics', 'features', 'sponsors'].includes(g[1])) return asPick(`https://opengraph.githubassets.com/1/${g[1]}/${g[2]}`, 'github-social');
    const p = /^https:\/\/huggingface\.co\/papers\/([\w.-]+)\/?$/.exec(u || '');
    if (p) return asPick(`https://cdn-thumbnails.huggingface.co/social-thumbnails/papers/${p[1]}.png`, 'hf-thumbnail');
    const h = /^https:\/\/huggingface\.co\/(?:(datasets|spaces)\/)?([\w.-]+)\/([\w.-]+)\/?$/.exec(u || '');
    if (h && !['papers', 'blog', 'docs', 'api'].includes(h[2])) return asPick(`https://cdn-thumbnails.huggingface.co/social-thumbnails/${h[1] || 'models'}/${h[2]}/${h[3]}.png`, 'hf-thumbnail');
  }
  return null;
}
function fromAIProvider(st) {
  if (st.image && st.image.via === 'ai' && st.image.src) return asPick(st.image.src, 'ai');
  const v = IMG[`ai:${st.id}`];
  if (v && v.src) return asPick(v.src, 'ai');
  return null;
}
const IMAGE_PROVIDERS = [fromVerifiedMap, fromFeedMedia, fromSourceAddress, fromAIProvider];
/* An AI or stock provider goes at the end of this list: after every published picture, before the cover. */

const PICKED = new Map();
function pickImage(st) {
  if (PICKED.has(st.id)) return PICKED.get(st.id);
  let r = null;
  if (st.image && st.image.src) {
    r = { src: st.image.src, via: st.image.via, kind: st.image.kind || KIND_OF_VIA[st.image.via] || 'photo' };
  } else {
    for (const p of IMAGE_PROVIDERS) { r = p(st); if (r) break; }
    if (!r) r = coverPick(st);
  }
  PICKED.set(st.id, r);
  return r;
}
const coverPick = st => ({ src: null, via: 'cover', kind: 'cover', cover: coverFor(st) });

/* ---------- covers: an image-sized picture made of the story's own facts ---------- */
/* Source colours (OKLCH hue, chroma, lightness). Dark enough that white text passes contrast. */
const BRAND = {
  'hacker-news': { h: 45, c: 0.15 }, 'lobsters': { h: 27, c: 0.12 }, 'github': { h: 255, c: 0.02, l: 0.30 },
  'huggingface': { h: 88, c: 0.11, l: 0.40 }, 'amazon': { h: 255, c: 0.04, l: 0.32 },
  'openai': { h: 265, c: 0.006, l: 0.24 }, 'wired': { h: 265, c: 0.006, l: 0.24 }, 'bloomberg': { h: 265, c: 0.006, l: 0.24 },
  'techcrunch': { h: 142, c: 0.13 }, 'ars-technica': { h: 40, c: 0.15 }, 'vnexpress': { h: 2, c: 0.13 },
  'google': { h: 260, c: 0.14 }, 'meta': { h: 262, c: 0.16 }, 'nvidia': { h: 128, c: 0.15, l: 0.40 },
};
function coverFor(st) {
  const c0 = covsOf(st)[0] || {};
  const s = SRC.get(c0.source) || {};
  const pub = c0.publisher || s.publisher || '';
  const name = srcName(c0.source) || pub || hostOf(st.url) || 'ai-radar';
  const b = BRAND[pub] || { h: monoHue(name), c: 0.07, l: 0.40 };
  const m = measureOf(st), n = nSrc(st);
  let num = null, word;
  if (m) { num = fmt(m.value); word = `${m.word}${m.where ? ` trên ${m.where}` : ''}`; }
  else if (n > 1) { num = String(n); word = 'nguồn cùng đưa tin'; }
  else word = hostOf(st.url) || KIND[st.kind] || name;
  return { face: faceOfStory(st, SRC), name, num, word, glyph: monogram(name), h: b.h, c: b.c, l: b.l ?? 0.42 };
}
const coverStyle = cv => `--cv-l:${cv.l};--cv-c:${cv.c};--cv-h:${cv.h}`;
const coverHTML = cv => `<div class="cover" style="${coverStyle(cv)}" aria-hidden="true">
  <span class="cover-glyph">${esc(cv.glyph)}</span>
  <span class="cover-top">${avatar(cv.face, 'sm')}</span>
  <span class="cover-fig">${cv.num
    ? `<span class="cover-num num">${esc(cv.num)}</span><span class="cover-word">${esc(cv.word)}</span>`
    : `<span class="cover-word is-big">${esc(cv.word)}</span>`}</span></div>`;
const miniCover = st => { const cv = coverFor(st); return `<span class="cover is-mini" style="${coverStyle(cv)}" aria-hidden="true"><span class="cover-glyph">${esc(cv.glyph)}</span></span>`; };

/* ---------- story card ---------- */
const DIMS = { lead: [1280, 720], wide: [1280, 720], std: [640, 360] };
function mediaHTML(img, size) {
  if (!img.src) return `<div class="media">${coverHTML(img.cover)}</div>`;
  const [w, h] = DIMS[size];
  const aiBadge = img.via === 'ai' ? `<span class="ai-badge" title="Ảnh minh hoạ do AI tạo"><span class="sr">Loại ảnh: </span>Ảnh minh hoạ do AI tạo</span>` : '';
  return `<div class="media"><img class="media-img" src="${esc(img.src)}" alt="" width="${w}" height="${h}" loading="lazy" decoding="async" referrerpolicy="no-referrer"${size === 'lead' ? ' fetchpriority="high"' : ''}>${aiBadge}</div>`;
}

/* ---------- calendar: the bento home's targets, the same split control ---------- */
const eventOf = st => asArray(D && D.events).find(e => e.url === st.url || e.title === st.title) || null;
function calOf(st) {
  if (!st) return null;
  const e = eventOf(st);
  if (e) return { uid: e.id, title: String(e.title), url: e.url, location: e.location, startDate: e.start_date, endDate: e.end_date,
    startAt: e.time_precision === 'exact' ? e.start_at : null, endAt: e.time_precision === 'exact' ? e.end_at : null,
    note: verifiedNote(e.verified_at, e.source_url) };
  const c = (st.coverage || []).find(c => c.status === 'upcoming' && c.start_at && c.time_precision !== 'relative');
  return c ? { uid: c.id, title: c.title, url: c.url, startAt: c.start_at, endAt: null, note: c.source ? `Buổi phát trực tiếp của ${srcName(c.source)}` : '' } : null;
}
const liveCal = v => v && v.status === 'upcoming' && v.start_at && v.time_precision !== 'relative'
  ? { uid: v.video_id, title: v.title, url: v.url, startAt: v.start_at, endAt: null, note: v.channel ? `Buổi phát trực tiếp của ${v.channel}` : '' } : null;
function calButtons(cal, attr, label) {
  if (!cal || !canCalendar(cal)) return '';
  return `<span class="calbtn" role="group" aria-label="Thêm ${esc(label)} vào lịch">
    <a class="calbtn-g" href="${esc(gcalURL(cal))}" target="_blank" rel="noopener">${icon('i-cal')}<span>Google Calendar</span></a>
    <button class="calbtn-ics" ${attr} title="Tải tệp .ics cho Apple Calendar, Outlook">.ics</button></span>`;
}
function addToCalendar(ev) {
  if (!ev || !canCalendar(ev)) { toast('Sự kiện này chưa có ngày xác minh nên chưa thêm vào lịch được'); return; }
  try { downloadIcs(ev); } catch { toast('Không tạo được tệp lịch cho sự kiện này'); return; }
  toast('Đã tạo tệp lịch .ics. Mở tệp để thêm vào lịch của bạn');
}

/* ---------- a story's detail: what the bento home's sheet showed, opened in place under the card ---------- */
function metricsHTML(c) {
  return Object.entries(c.metrics || {}).filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
    .map(([k, v]) => `<b class="num" data-live="${esc(c.id)}|${esc(k)}">${fmt(v)}</b> ${esc(METRIC[k] || k)}`).join(' · ');
}
function hotReasonHTML(st) {
  if (!st.hot_reason) return '';
  return esc(st.hot_reason).replace(/([a-z0-9][a-z0-9-]*):\s*/g, (m, id) => SRC.has(id) ? `<b>${esc(srcName(id))}</b> ` : m);
}
function detailHTML(st) {
  const covs = [...covsOf(st)].sort((a, b) => ms(a.published_at) - ms(b.published_at));
  const sum = shown(st.summary, st.summary_vi);
  const e = eventOf(st);
  const facts = [
    st.hot_score != null && st.hot_reason ? `<p class="dt-hot">Nóng vì ${hotReasonHTML(st)}</p>` : '',
    sum ? `<p class="dt-sum"${langAttr(sum)}>${esc(sum)}</p>` : '',
    e ? `<p class="dt-ev">${esc(eventRange(e.start_date, e.end_date))} · ${esc(e.location || 'chưa rõ địa điểm')}${e.verified_at ? ` · xác minh ${esc(e.verified_at)}` : ''}</p>` : '',
    st.time_basis === 'repository_created' ? '<p class="dt-ev">Ngày ghi là ngày tạo kho mã, không phải ngày phát hành.</p>' : '',
  ].join('');
  return `${facts}<p class="dt-h">Các nguồn, theo thời gian</p><ul class="dt-src">${covs.map(c => {
    const ct = typeof c.title_vi === 'string' && c.title_vi.trim() ? c.title_vi.trim() : String(c.title || '');
    const mx = metricsHTML(c);
    return `<li><span class="cov-src">${esc(srcName(c.source) || hostOf(c.url))}${c.published_at ? ` · ${timeEl(c.published_at)}` : ''}</span>
      <a class="cov-t" href="${esc(safe(c.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}"${langAttr(ct)}>${esc(ct)}</a>
      ${mx || c.discussion_url ? `<span class="cov-m">${mx}${mx && c.discussion_url ? ' · ' : ''}${c.discussion_url ? `<a href="${esc(safe(c.discussion_url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Thảo luận</a>` : ''}</span>` : ''}</li>`;
  }).join('')}</ul>`;
}
function toggleDetail(btn, open) {
  const panel = document.getElementById(btn.getAttribute('aria-controls'));
  const st = STORY_ANY.get(btn.dataset.cov);
  if (!panel || !st) return;
  const on = open ?? btn.getAttribute('aria-expanded') !== 'true';
  if (on) { panel.innerHTML = detailHTML(st); hydrateHF(panel); }
  panel.hidden = !on;
  btn.setAttribute('aria-expanded', String(on));
}

/* opts (only the "Đáng đọc hôm nay" lead uses them): rank, the block position; why, show the reason line; h, the
   heading level under the block's own h2. */
function renderCard(st, size = 'std', opts = {}) {
  const img = pickImage(st);
  const photo = (size === 'lead' || size === 'wide') && img.kind === 'photo';
  const covs = covsOf(st);
  const first = covs[0] || {};
  const t = titleOf(st);
  const from = t.cov || first;
  const href = safe(t.cov ? t.cov.url : st.url);
  const face = t.cov ? faceOfSource(t.cov, SRC) : faceOfStory(st, SRC);
  const name = srcName(from.source) || hostOf(href);
  const tid = `t-${esc(st.id)}`;
  const m = measureOf(st);
  const h = opts.h || 'h2';
  const pin = PICKS.get(st.id);
  // Summaries only on the big cards, and only in Vietnamese: an English paragraph under a Vietnamese headline reads as noise.
  const sumRaw = shown(st.summary, st.summary_vi);
  const sum = (size !== 'std' && sumRaw && VI_RE.test(sumRaw) && sumRaw.trim() !== t.text.trim()) ? sumRaw : '';
  // The foot carries a measured number (and where it was measured, when that is not the source named above) and the
  // disclosure that replaces the bento home's story sheet: "N nguồn" (or "Chi tiết" for one source) opens why the
  // story is hot, its summary and every publisher that carried it, in time order, each with its own counters and
  // discussion link. #tin/<id> opens the same panel.
  const covId = `cov-${esc(st.id)}`;
  const metric = [
    (m && !opts.why) ? `<span>${numB(m)} ${esc(m.word)}</span>` : '',
    `<button class="cov-btn" data-cov="${esc(st.id)}" aria-expanded="false" aria-controls="${covId}" aria-describedby="${tid}">${covs.length > 1 ? `${avatarStack(covs.slice(0, 3).map(c => faceOfSource(c, SRC)), 'xs')}<span><b class="num">${covs.length}</b> nguồn</span>` : '<span>Chi tiết</span>'}</button>`
  ].filter(Boolean).join('<span aria-hidden="true">·</span>');
  const cal = calOf(st);
  const isSaved = savedHas(st.id);
  const cls = ['feed-card', `card-${size}`, opts.debate ? 'card-debate' : '', photo ? 'card-photo' : '', statusClass(st)].filter(Boolean).join(' ');

  return `<article class="${cls}" data-id="${esc(st.id)}" data-sid="${esc(st.id)}" data-status="${storyStatus(st.id, st)}" data-via="${esc(img.via)}" data-worth="${worthOf(st).score.toFixed(1)}">
  ${reasonTag(st)}
  ${mediaHTML(img, size)}
  <div class="${photo ? 'photo-body' : 'card-body'}">
    <div class="src-row">${markHTML(st)}${opts.rank ? `<span class="pick-n num"><span class="sr">Số </span>${opts.rank}</span>` : ''}<span class="src-av" aria-hidden="true">${avatar(face, 'xs')}</span><span class="src-name">${esc(name)}</span><span aria-hidden="true">·</span>${timeEl(st.published_at)}</div>
    ${h === 'h3'
      ? `<h3 class="card-title" id="${tid}"${langAttr(t.text)}><a class="story-link" href="${esc(href)}" target="_blank" rel="noopener" data-id="${esc(st.id)}">${esc(t.text)}</a></h3>`
      : `<h2 class="card-title" id="${tid}"${langAttr(t.text)}><a class="story-link" href="${esc(href)}" target="_blank" rel="noopener" data-id="${esc(st.id)}">${esc(t.text)}</a></h2>`}
    ${origLine(t)}
    ${opts.why ? `<p class="why-line"><span class="sr">Vì sao nên đọc: </span>${worthWhy(st)}</p>` : ''}
    ${opts.why && pin && pin.note ? `<p class="pick-note">Ghi chú biên tập: ${esc(pin.note)}</p>` : ''}
    ${sum ? `<p class="card-sum">${esc(sum)}</p>` : ''}
    <div class="card-foot">
      <span class="metric">${metric}</span>
      <div class="card-actions">
        <button class="act${isSaved ? ' is-saved' : ''}" data-act="save" data-id="${esc(st.id)}" aria-pressed="${isSaved}" aria-label="Lưu tin này" aria-describedby="${tid}" aria-keyshortcuts="S" title="Lưu">${icon('i-bookmark')}</button>
        <button class="act" data-act="copy" data-url="${esc(href)}" aria-label="Chép liên kết" aria-describedby="${tid}" title="Chép liên kết">${icon('i-link')}</button>
      </div>
    </div>
    ${cal ? `<div class="card-cal">${calButtons(cal, `data-cal="${esc(st.id)}"`, t.text)}</div>` : ''}
    <div class="cov-list" id="${covId}" hidden></div>
  </div>
</article>`;
}

/* ---------- tile: live and upcoming ---------- */
const todayKey = () => dayKey(new Date());
function daysUntil(start, end) {
  const t = Date.parse(todayKey()), a = Date.parse(start), b = Date.parse(end || start);
  if (!Number.isFinite(a)) return NaN;
  if (t > a && t <= b) return -1;
  return Math.round((a - t) / 864e5);
}
function renderLive() {
  const items = D.live || [];
  const it = items.find(x => x.status === 'live') || items.find(x => x.status === 'upcoming') || items[0];
  const tk = todayKey();
  const events = (D.events || []).filter(e => (e.end_date || e.start_date || '') >= tk)
    .sort((a, b) => String(a.start_date).localeCompare(String(b.start_date))).slice(0, 3);
  if (!it && !events.length) return '';

  let head = 'Sắp diễn ra', video = '';
  if (it) {
    // Three honest states. The old tile called an ended stream "Sắp phát sóng" and offered a reminder.
    const onYT = /(^|\.)(youtube\.com|youtu\.be)$/.test(hostOf(it.url));
    const where = onYT ? ' trên YouTube' : '';
    const S = it.status === 'live'
      ? { head: 'Đang phát', badge: 'Trực tiếp', action: 'Xem trực tiếp', live: true }
      : it.status === 'upcoming'
        ? { head: 'Sắp phát', badge: scheduleText(it.time_text), action: `Đặt nhắc${where}`, live: false }
        : { head: 'Xem lại', badge: streamedAge(it.time_text) || 'Đã phát', action: `Xem lại${where}`, live: false };
    head = S.head;
    const thumb = it.thumbnail || (it.video_id ? `https://i.ytimg.com/vi/${it.video_id}/hqdefault.jpg` : '');
    video = `<a class="tile-video" href="${esc(safe(it.url))}" target="_blank" rel="noopener" aria-label="${esc(S.action)}: ${esc(it.title)}">
      ${thumb ? `<img src="${esc(thumb)}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ''}
      <span class="video-badge${S.live ? ' is-live' : ''}">${esc(S.badge)}</span>
      <span class="video-play">${icon('i-play')}</span>
    </a>
    <p class="video-title"${langAttr(it.title)}>${esc(it.title)}</p>
    <p class="video-meta">${esc(it.channel || '')}${where}</p>
    <a class="tile-action${S.live ? ' is-live' : ''}" href="${esc(safe(it.url))}" target="_blank" rel="noopener">${icon('i-play')}${esc(S.action)}</a>
    ${it.status === 'upcoming' ? calButtons(liveCal(it), `data-cal-live="${esc(it.video_id || '')}"`, it.title) : ''}`;
  }
  const evStory = e => asArray(D.stories).find(s => s.url === e.url || s.title === e.title);
  const evHTML = events.length ? `${it ? '<h3 class="tile-sub">Sắp diễn ra</h3>' : ''}
    <ul class="events">${events.map(e => {
      const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(e.start_date || '');
      const st = evStory(e);
      const cal = st ? calOf(st) : { uid: e.id, title: String(e.title), url: e.url, location: e.location, startDate: e.start_date, endDate: e.end_date,
        startAt: e.time_precision === 'exact' ? e.start_at : null, endAt: e.time_precision === 'exact' ? e.end_at : null, note: verifiedNote(e.verified_at, e.source_url) };
      return `<li${st ? ` data-sid="${esc(st.id)}" class="${statusClass(st)}"` : ''}><a class="event" href="${esc(safe(e.url))}" target="_blank" rel="noopener"${st ? ` data-read="${esc(st.id)}"` : ''}>
        <span class="date-badge" aria-hidden="true">${d ? `<b class="num">${+d[3]}</b><span>thg ${+d[2]}</span>` : ''}</span>
        <span class="event-text"><span class="event-name"${langAttr(e.title)}>${st ? markHTML(st) : ''}${esc(e.title)}</span>
        <span class="event-when">${esc(eventRange(e.start_date, e.end_date))} · ${esc(e.location || '')} · ${daysLeftHTML(daysUntil(e.start_date, e.end_date))}</span></span></a>
        ${calButtons(cal, st ? `data-cal="${esc(st.id)}"` : `data-cal-ev="${esc(e.id)}"`, e.title)}</li>`;
    }).join('')}</ul>` : '';
  return `<section class="tile tile-live" aria-labelledby="live-h">
    <div class="tile-head"><h2 class="tile-title" id="live-h">${esc(head)}</h2>${it ? '<span class="tile-note">phát sóng</span>' : ''}</div>
    ${video}${evHTML}</section>`;
}

/* ---------- tile: hot, and why ---------- */
function whyHTML(st) {
  const m = measureOf(st), n = nSrc(st), parts = [];
  if (m) parts.push(`${numB(m)} ${esc(m.word)}${m.where ? ` trên ${esc(m.where)}` : ''}`);
  if (m && m.speed) parts.push(`tăng <b class="num">${nf1.format(m.speed)}</b> mỗi giờ`);
  if (n > 1) parts.push(`<b class="num">${n}</b> nguồn cùng đưa`);
  if (!parts.length) parts.push(esc(ago(st.published_at)));
  return parts.join(' · ');
}
function renderHot(list = HOT) {
  if (!list.length) return '';
  return `<section class="tile tile-hot" aria-labelledby="hot-h">
    <div class="tile-head"><h2 class="tile-title" id="hot-h">Đang nóng</h2><span class="tile-note">xếp theo số đo thật</span></div>
    <ol class="hot-list">${list.map((st, i) => {
      const img = pickImage(st), t = titleOf(st);
      return `<li><a class="hot-row ${statusClass(st)}" href="${esc(safe(t.cov ? t.cov.url : st.url))}" target="_blank" rel="noopener" data-sid="${esc(st.id)}" data-read="${esc(st.id)}" data-status="${storyStatus(st.id, st)}">
        <span class="thumb" data-id="${esc(st.id)}">${img.src ? `<img src="${esc(img.src)}" alt="" width="144" height="144" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : miniCover(st)}</span>
        <span class="hot-rank num" aria-hidden="true">${i + 1}</span>
        <span class="hot-text"><span class="hot-title"${langAttr(t.text)}>${markHTML(st)}${esc(t.text)}</span><span class="hot-why">${whyHTML(st)}</span></span></a></li>`;
    }).join('')}</ol></section>`;
}

/* ---------- tiles: repositories and models ---------- */
const LABEL = { 'dung-ngay': 'Dùng ngay', 'xao-nau': 'Xào nấu được', 'nghien-cuu': 'Nghiên cứu' };
const ghPreview = r => { const v = IMG[r.url]; return v && v.src ? v.src : `https://opengraph.githubassets.com/1/${r.full_name}`; };
const hfPreview = r => { const v = IMG[r.url]; return v && v.src ? v.src : `https://cdn-thumbnails.huggingface.co/social-thumbnails/models/${r.full_name}.png`; };
/* The bento home's repository controls (owner, 03/10 02:11): three lists, the GitHub Trending window or the total,
   and the eight work areas. The orderings come from the pipeline (repos_meta.rankings); the page only picks one.
   Same keys as the bento home, so a reader's choice carries over. */
const AREAS = [
  { id: 'video', label: 'Video và hình ảnh' }, { id: 'agent-code', label: 'Tác tử lập trình' }, { id: 'quant', label: 'Giao dịch, tài chính' },
  { id: 'local', label: 'Chạy mô hình trên máy' }, { id: 'fine-tune', label: 'Tinh chỉnh mô hình' }, { id: 'rag', label: 'Dữ liệu cho RAG' },
  { id: 'voice', label: 'Giọng nói, âm thanh' }, { id: 'browser-mcp', label: 'Trình duyệt, MCP' },
];
const REPO_VIEWS = [{ id: 'trending', label: 'Đang lên' }, { id: 'stars', label: 'Nhiều sao' }, { id: 'usable', label: 'Dùng ngay' }];
const WINDOWS = [
  { id: 'day', label: 'Hôm nay', gained: 'sao hôm nay', phrase: 'hôm nay' },
  { id: 'week', label: 'Tuần này', gained: 'sao tuần này', phrase: 'trong tuần' },
  { id: 'month', label: 'Tháng này', gained: 'sao tháng này', phrase: 'trong tháng' },
];
const TOTALS = [{ id: 'stars', label: 'Theo sao', unit: 'sao' }, { id: 'forks', label: 'Theo phân nhánh', unit: 'lượt phân nhánh' }];
const pickOpt = (k, list, d) => { const v = store.get(k, d); return list.some(x => x.id === v) ? v : d; };
let repoView = pickOpt(K.repoView, REPO_VIEWS, 'trending');
let repoWindow = pickOpt(K.repoWindow, WINDOWS, 'day');
let repoTotal = pickOpt(K.repoTotal, TOTALS, 'stars');
const areas = new Set(asArray(store.get(K.areas, [])));
const winOf = id => WINDOWS.find(w => w.id === id);
const totalOf = id => TOTALS.find(t => t.id === id);
let REPO = new Map();         // repository id -> record (labelled GitHub repositories and Hugging Face models)
function rankings() { const rk = D.repos_meta && D.repos_meta.rankings; return rk && rk.trending && rk.usable ? rk : null; }
function rankedRepos() {
  const rk = rankings(); if (!rk) return null;
  return asArray(repoView === 'stars' ? rk[repoTotal] : (rk[repoView] || {})[repoWindow]).map(id => REPO.get(String(id))).filter(Boolean);
}
function windowGap() {
  if (repoView === 'stars') return '';
  const w = D.repos_meta && D.repos_meta.windows && D.repos_meta.windows[repoWindow];
  return w && !w.measured ? `Chưa đo được số sao tăng ${winOf(repoWindow).phrase}${w.error ? `: ${w.error}` : ''}.` : '';
}
function repoMeasure(r) {
  if (repoView === 'stars') {
    const v = r[repoTotal];
    return Number.isFinite(v) ? `<b class="num">${fmt(v)}</b> ${esc(totalOf(repoTotal).unit)}` : `chưa đo được ${repoTotal === 'forks' ? 'lượt phân nhánh' : 'số sao'}`;
  }
  const g = r.stars_gained ? r.stars_gained[repoWindow] : null;
  return Number.isFinite(g) ? `<b class="num">+${fmt(g)}</b> ${esc(winOf(repoWindow).gained)}` : `chưa đo được số sao tăng ${esc(winOf(repoWindow).phrase)}`;
}
function repoListNote() {
  if (repoView === 'stars') return `Kho mã AI đang thịnh hành trên GitHub, xếp theo tổng ${totalOf(repoTotal).unit}.`;
  const w = winOf(repoWindow);
  return repoView === 'usable'
    ? `Kho mã gắn nhãn Dùng ngay (có lệnh cài, bản phát hành mới, giấy phép dễ dùng), xếp theo số sao tăng ${w.phrase} trên trang thịnh hành của GitHub.`
    : `Kho mã AI tăng sao nhanh nhất ${w.phrase} trên trang thịnh hành của GitHub. Nhãn chỉ để tham khảo, không đổi thứ tự.`;
}
function repoControls(full, inList) {
  const second = repoView === 'stars'
    ? TOTALS.map(t => ({ kind: 'total', id: t.id, label: t.label, on: repoTotal === t.id }))
    : WINDOWS.map(w => ({ kind: 'window', id: w.id, label: w.label, on: repoWindow === w.id }));
  const count = id => inList.filter(r => r.category === id).length;
  return `<div class="repo-ctl">
    <div class="seg" role="group" aria-label="Chọn danh sách kho mã">${REPO_VIEWS.map(v => `<button class="seg-b" data-repo-view="${v.id}" aria-pressed="${repoView === v.id}">${esc(v.label)}</button>`).join('')}</div>
    <div class="seg seg-quiet" role="group" aria-label="${repoView === 'stars' ? 'Xếp theo tổng số sao hay lượt phân nhánh' : 'Chọn khung thời gian'}">${second.map(x => `<button class="seg-b" data-repo-${x.kind}="${x.id}" aria-pressed="${x.on}">${esc(x.label)}</button>`).join('')}</div>
  </div>
  ${full ? `<div class="area-chips" role="group" aria-label="Chọn mảng bạn quan tâm">${AREAS.map(a => `<button class="area-chip" data-area="${a.id}" aria-pressed="${areas.has(a.id)}">${esc(a.label)} <span class="count num">${count(a.id)}</span></button>`).join('')}</div>
  <p class="tile-note repo-note">${esc(repoListNote())} ${areas.size ? `Đang lọc ${areas.size} mảng, lưu trên máy này.` : 'Chưa chọn mảng nào, nên hiện mọi mảng.'}</p>` : ''}`;
}
function repoCard(r, measure) {
  const desc = r.description_vi || r.description || '';
  const key = `repo:${r.id}`, on = savedHas(key);
  return `<div class="repo-cell${read.has(key) ? ' is-read' : ''}" data-sid="${esc(key)}"><a class="repo" href="${esc(safe(r.url))}" target="_blank" rel="noopener" data-read="${esc(key)}">
      <span class="repo-img"><img src="${esc(ghPreview(r))}" alt="" width="1200" height="600" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>
      <span class="repo-name" lang="en"><span class="st-mark">${read.has(key) ? MARK.seen : ''}</span>${esc(r.full_name)}</span>
      <span class="repo-desc"${langAttr(desc)}>${esc(desc)}</span>
      <span class="repo-meta">${LABEL[r.label] ? `<span class="label ${esc(r.label)}">${esc(LABEL[r.label])}</span>` : ''}<span>${measure}</span></span>
    </a><button class="act repo-save${on ? ' is-saved' : ''}" data-act="save" data-id="${esc(key)}" aria-pressed="${on}" aria-label="Lưu kho mã ${esc(r.full_name)}" title="Lưu">${icon('i-bookmark')}</button></div>`;
}
/* full: the "Mã và mô hình" view (up to 12, with the work areas); otherwise the tile in the feed (4). */
function renderRepos(full = false) {
  const ranked = rankedRepos();
  const head = `<div class="tile-head"><h2 class="tile-title" id="repos-h">Kho mã đáng lấy</h2><span class="tile-note">thịnh hành trên GitHub</span></div>`;
  if (!ranked) {
    // A snapshot built before 03/10 has no orderings: the old pick, labelled repositories by stars gained in 7 days.
    const repos = asArray(D.repos).filter(r => r.source !== 'hf' && (r.label === 'dung-ngay' || r.label === 'xao-nau'))
      .sort((a, b) => (b.stars_gained_7d || 0) - (a.stars_gained_7d || 0)).slice(0, full ? 12 : 4);
    if (!repos.length) return '';
    return `<section class="tile tile-repos${full ? ' is-full' : ''}" aria-labelledby="repos-h">${head}
      <div class="repo-row">${repos.map(r => repoCard(r, r.stars_gained_7d ? `<b class="num">+${fmt(r.stars_gained_7d)}</b> sao trong 7 ngày` : `<b class="num">${fmt(r.stars || 0)}</b> sao`)).join('')}</div></section>`;
  }
  const list = ranked.filter(r => !areas.size || areas.has(r.category)).slice(0, full ? 12 : 4);
  const why = windowGap() || (areas.size ? 'Không có kho mã nào ở mảng bạn chọn.' : 'Danh sách này chưa có kho mã nào.');
  return `<section class="tile tile-repos${full ? ' is-full' : ''}" aria-labelledby="repos-h">${head}
    ${repoControls(full, ranked)}
    ${list.length ? `<div class="repo-row">${list.map(r => repoCard(r, repoMeasure(r))).join('')}</div>`
      : `<p class="tile-note repo-empty">${esc(why)}${areas.size ? ' <button class="text-btn" data-area-clear>Hiện mọi mảng</button>' : ''}</p>`}
  </section>`;
}
function setRepo(kind, value) {
  if (kind === 'view' && REPO_VIEWS.some(v => v.id === value)) { repoView = value; store.set(K.repoView, value); }
  else if (kind === 'window' && WINDOWS.some(w => w.id === value)) { repoWindow = value; store.set(K.repoWindow, value); }
  else if (kind === 'total' && TOTALS.some(t => t.id === value)) { repoTotal = value; store.set(K.repoTotal, value); }
  else return;
  rerenderRepos();
}
/* Redraw only the tile, and put focus back on the control the reader used. */
function rerenderRepos() {
  const old = $('.tile-repos'); if (!old) return;
  const a = document.activeElement;
  const attr = a && a.dataset ? ['area', 'repoView', 'repoWindow', 'repoTotal'].find(k => a.dataset[k] != null) : null;
  const value = attr ? a.dataset[attr] : null;
  const tmp = document.createElement('div');
  tmp.innerHTML = renderRepos(old.classList.contains('is-full'));
  const next = tmp.firstElementChild;
  if (next) old.replaceWith(next); else old.remove();
  if (attr && next) {
    const name = 'data-' + attr.replace(/[A-Z]/g, c => '-' + c.toLowerCase());
    const el = next.querySelector(`[${name}="${CSSq(value)}"]`);
    if (el) el.focus({ preventScroll: true });
  }
}
function renderModels() {
  const sig = r => r.signals || {};
  const models = (D.repos || []).filter(r => r.source === 'hf')
    .sort((a, b) => (sig(b).hf_score ?? b.hf_score ?? 0) - (sig(a).hf_score ?? a.hf_score ?? 0)).slice(0, 3);
  if (!models.length) return '';
  return `<section class="tile tile-models" aria-labelledby="models-h">
    <div class="tile-head"><h2 class="tile-title" id="models-h">Mô hình đáng thử</h2></div>
    <p class="tile-note">thịnh hành trên Hugging Face</p>
    <div class="model-list">${models.map(r => {
      const likes = sig(r).likes ?? r.stars, dl = sig(r).downloads;
      return `<a class="model" href="${esc(safe(r.url))}" target="_blank" rel="noopener">
        <span class="model-img"><img src="${esc(hfPreview(r))}" alt="" width="1200" height="648" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>
        <span class="model-name" lang="en">${esc(r.full_name)}</span>
        <span class="model-meta">${Number.isFinite(likes) ? `<span><b class="num">${fmt(likes)}</b> lượt thích</span>` : ''}${Number.isFinite(dl) ? `<span><b class="num">${fmt(dl)}</b> lượt tải</span>` : ''}</span>
      </a>`;
    }).join('')}</div></section>`;
}

/* ---------- "Đáng đọc hôm nay": the lead photo is number 1, a tile beside it ranks 2 to 5 ---------- */
function pickRow(st, rank) {
  const img = pickImage(st), t = titleOf(st), pin = PICKS.get(st.id);
  return `<li><a class="hot-row pick-row ${statusClass(st)}" href="${esc(safe(t.cov ? t.cov.url : st.url))}" target="_blank" rel="noopener" data-id="${esc(st.id)}" data-sid="${esc(st.id)}" data-read="${esc(st.id)}" data-status="${storyStatus(st.id, st)}" data-worth="${worthOf(st).score.toFixed(1)}">
    <span class="thumb pick-thumb" data-id="${esc(st.id)}">${img.src ? `<img src="${esc(img.src)}" alt="" width="320" height="180" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : miniCover(st)}</span>
    <span class="hot-rank num" aria-hidden="true">${rank}</span>
    <span class="hot-text"><span class="hot-title"${langAttr(t.text)}>${markHTML(st)}${esc(t.text)}</span>
      <span class="hot-why">${pin ? '<span class="tag is-editor">Biên tập chọn</span>' : ''}<span class="sr">Vì sao nên đọc: </span>${worthWhy(st)}</span>
      ${pin && pin.note ? `<span class="pick-note">Ghi chú biên tập: ${esc(pin.note)}</span>` : ''}</span></a></li>`;
}
function renderPicks() {
  const show = filter === 'all' && PICKLIST.length > 0;
  $('#picks').hidden = !show;
  if (!show) return;
  const [first, ...mid] = PICKLIST;
  const noteEl = $('#picks-note');
  if (noteEl) noteEl.textContent = '';
  const grid = $('#picks-grid');
  grid.innerHTML = renderCard(first, 'lead', { why: true, h: 'h3' })
    + (mid.length ? `<div class="picks-mid">${mid.map(st => renderCard(st, 'std', { h: 'h3' })).join('')}</div>` : '')
    + renderLive();
}

/* "Cách chấm": written from WORTH, so the note always matches the code. */
function renderHow() {
  const W = WORTH, f1 = v => nf1.format(v);
  $('#how-panel').innerHTML = `
    <p>Mỗi tin trong ${winH} giờ qua được chấm từ bốn tín hiệu có sẵn trong dữ liệu. Không có điểm nào do người gõ tay.</p>
    <ul class="how-list">
      <li><b>Độ chú ý</b>, tối đa <span class="num">${W.attention}</span> điểm: điểm nóng của tin, tức thứ hạng con số của tin (điểm Hacker News, sao GitHub…) so với các tin khác cùng nguồn, nhân với độ mới. Điểm nóng từ <span class="num">${W.attentionFull}</span> trở lên được đủ <span class="num">${W.attention}</span>.</li>
      <li><b>Độ lan rộng</b>, tối đa <span class="num">${W.breadth}</span> điểm: mỗi nơi đăng độc lập thêm vào sau nơi đầu tiên được <span class="num">${f1(W.breadth / (W.breadthFull - 1))}</span> điểm, đủ khi có <span class="num">${W.breadthFull}</span> nơi.</li>
      <li><b>Độ mới</b>: <span class="num">${W.freshness}</span> điểm lúc vừa đăng, còn một nửa sau mỗi <span class="num">${W.halfLifeH}</span> giờ.</li>
      <li><b>Nguồn gốc</b>: tin do chính phòng nghiên cứu công bố, hoặc bài báo gốc của nhóm nghiên cứu, được nhân <span class="num">${f1(W.firstHand)}</span>.</li>
    </ul>
    <p>Nhãn trên thẻ ghi lý do mạnh nhất. “Đang bàn nhiều” và “Đang được chú ý” là tin có điểm nóng từ <span class="num">${W.hotLabel}</span> trở lên. Tin không có nhãn là tin chưa có tín hiệu nào ngoài giờ đăng. Chỉ tin mang nhãn “Biên tập chọn” là do người chọn.</p>
    <p>Trọng số hiện là phỏng đoán ban đầu, sẽ được chỉnh lại sau một tuần dữ liệu thật.</p>`;
}

/* ==========================================================================
   ORDER AND RHYTHM
   Above the grid, "Đáng đọc hôm nay" holds the lead photo (number 1) and the ranked tile (2 to 5).
   Laptop grid (12 columns): the live tile (3 wide, 2 rows) beside six cards, three per row; then the hot and
   repository tiles side by side, rows of four cards, a wide photo card every third row. Phone: the same order, one
   column. The river follows the switch: "Đáng đọc nhất" (score) or "Mới nhất" (published time).
   ========================================================================== */
const C = (st, size = 'std', opts = {}) => ({ t: 'card', st, size, opts });
const photoIndex = river => river.findIndex((st, k) => k < 12 && pickImage(st).kind === 'photo');

function rows(river, out) {
  for (let r = 1; river.length; r++) {
    const wi = r % 3 === 0 ? photoIndex(river) : -1;
    if (wi >= 0) { out.push(C(river.splice(wi, 1)[0], 'wide')); for (let i = 0; i < 2 && river.length; i++) out.push(C(river.shift())); }
    else for (let i = 0; i < 4 && river.length; i++) out.push(C(river.shift()));
  }
  return out;
}

function buildAll() {
  const out = [], used = new Set(PICKLIST.map(st => st.id));

  // --- Khối 2: Cộng đồng đang tranh luận ---
  HOT = allStories.filter(st => !used.has(st.id) && (st.hot_score || 0) > 0 && !PICKLIST.some(p => sameEvent(p, st)))
    .sort((a, b) => b.hot_score - a.hot_score).slice(0, 5);
  HOT.forEach(st => used.add(st.id));

  const discussions = allStories.filter(st => !used.has(st.id) && (st.kind === 'forum' || (st.hot_score || 0) > 0))
    .sort((a, b) => (b.hot_score || 0) - (a.hot_score || 0) || ms(b.published_at) - ms(a.published_at));
  const debateCards = [];
  for (const st of discussions) {
    if (debateCards.length >= 2) break;
    if (!HOT.some(h => sameEvent(h, st))) {
      debateCards.push(st);
      used.add(st.id);
    }
  }

  out.push({
    t: 'section-head',
    id: 'sec-tranh-luan',
    title: 'Cộng đồng đang tranh luận',
    sub: 'Các chủ đề thu hút nhiều thảo luận và tốc độ quan tâm đột biến trên Hacker News và các diễn đàn.'
  });
  out.push({ t: 'hot' });
  debateCards.forEach(st => out.push(C(st, 'std', { debate: true })));

  // --- Khối 3: Vừa ra mắt & Công bố mới ---
  const productCandidates = allStories.filter(st => !used.has(st.id) && (st.kind === 'product' || firstHandOf(st)))
    .sort((a, b) => (sortMode === 'new' ? byNew : byWorth)(a, b));
  const productCards = [];
  for (const st of productCandidates) {
    if (productCards.length >= 4) break;
    if (!productCards.some(p => sameEvent(p, st))) {
      productCards.push(st);
      used.add(st.id);
    }
  }

  if (productCards.length) {
    out.push({
      t: 'section-head',
      id: 'sec-ra-mat',
      title: 'Vừa ra mắt & Công bố mới',
      sub: 'Các sản phẩm, tính năng và công bố chính thức từ các hãng và phòng nghiên cứu.'
    });
    const wi = photoIndex(productCards);
    if (wi >= 0 && productCards.length >= 3) {
      out.push(C(productCards.splice(wi, 1)[0], 'wide'));
      productCards.slice(0, 2).forEach(st => out.push(C(st, 'std')));
    } else {
      productCards.forEach(st => out.push(C(st, 'std')));
    }
  }

  // --- Khối 4: Kho mã & Mô hình đáng thử ---
  out.push({
    t: 'section-head',
    id: 'sec-kho-ma',
    title: 'Kho mã & Mô hình đáng thử',
    sub: 'Kho mã nguồn mở tăng sao nhanh nhất trên GitHub và mô hình thịnh hành trên Hugging Face.'
  });
  out.push({ t: 'repos' });
  out.push({ t: 'models' });

  // --- Khối 5: Dòng tin 72 giờ qua ---
  const river = ordered(allStories.filter(st => !used.has(st.id)));
  if (river.length) {
    out.push({
      t: 'section-head',
      id: 'sec-dong-tin',
      title: 'Dòng tin 72 giờ qua',
      sub: 'Toàn bộ diễn biến khác trong 72 giờ qua, cập nhật liên tục từ các nguồn tin độc lập.'
    });
    rows(river, out);
  }

  return out;
}

const FILTERS = {
  big: st => bigSet.has(st.id),
  hot: st => st.hot_score > 0,
  product: st => st.kind === 'product',
  forum: st => st.kind === 'forum',
  code: st => st.kind === 'repository' || st.kind === 'model',
};
/* The bento home's chapters, as views of the same feed. Their lists come from the snapshot's sections (the pipeline's
   choice), so they may reach outside the window, as the chapters did. The search page links to these addresses. */
const SECTIONS = {
  'hom-nay': { sec: 'today', label: 'Hôm nay', order: 'new' },
  model: { sec: 'models', label: 'Mô hình mới', order: 'new' },
  paper: { sec: 'papers', label: 'Bài báo khoa học', order: 'new' },
  nghe: { sec: 'listen', label: 'Nghe và xem', order: 'new' },
  'chuyen-gia': { sec: 'voices', label: 'Tiếng nói chuyên gia', order: 'new' },
  'cong-dong': { sec: 'community', label: 'Cộng đồng đang bàn', order: 'new' },
  'sap-toi': { sec: 'upcoming', label: 'Sắp diễn ra', order: 'date' },
};
const secOf = f => f.startsWith('sec:') ? SECTIONS[f.slice(4)] : null;
const savedStories = () => saved.slice().reverse().map(x => STORY_ANY.get(x.key)).filter(Boolean);
function listFor(f) {
  if (f === 'all') return allStories;
  if (f === 'saved') return savedStories();
  const s = secOf(f);
  if (s) return asArray(D.sections && D.sections[s.sec]).map(id => STORY_ANY.get(id)).filter(Boolean);
  return allStories.filter(FILTERS[f] || (() => false));
}
function buildFiltered(f) {
  const s = secOf(f);
  if (f === 'saved') {
    // Saved stories in the order the reader saved them (newest first); anything no longer in the snapshot follows as links.
    const out = savedStories().map(st => C(st));
    if (saved.some(x => !STORY_ANY.has(x.key))) out.push({ t: 'saved-rest' });
    return out;
  }
  if (s) {
    const list = listFor(f);
    const river = s.order === 'date'
      ? list.slice().sort((a, b) => String((eventOf(a) || {}).start_date || a.published_at).localeCompare(String((eventOf(b) || {}).start_date || b.published_at)))
      : list.slice().sort(byNew);
    const out = s.sec === 'upcoming' ? [{ t: 'live' }] : [];
    if (river.length && s.sec !== 'upcoming') out.push(C(river.shift(), 'lead'));
    return rows(river, out);
  }
  const river = ordered(listFor(f)), out = [];
  if (f === 'code') { out.push({ t: 'repos-full' }, { t: 'models' }); return rows(river, out); }
  if (river.length) out.push(C(river.shift(), 'lead'));
  for (let i = 0; i < 4 && river.length; i++) out.push(C(river.shift()));
  return rows(river, out);
}
/* Saved items that left the snapshot (and saved repositories): the title and address kept at save time. */
function renderSavedRest() {
  const rest = saved.slice().reverse().filter(x => !STORY_ANY.has(x.key));
  if (!rest.length) return '';
  return `<section class="tile tile-saved" aria-labelledby="saved-h">
    <div class="tile-head"><h2 class="tile-title" id="saved-h">Đã lưu trước đây</h2><span class="tile-note">không còn trong bản tin hiện tại, chỉ lưu trên máy này</span></div>
    <ul class="saved-list">${rest.map(x => `<li><a href="${esc(safe(x.url))}" target="_blank" rel="noopener">${esc(x.title || x.url || x.key)}</a>
      <span class="saved-at">${x.at ? timeEl(x.at) : ''}</span>
      <button class="act is-saved" data-act="save" data-id="${esc(x.key)}" aria-pressed="true" aria-label="Bỏ lưu ${esc(x.title || '')}" title="Bỏ lưu">${icon('i-close')}</button></li>`).join('')}</ul></section>`;
}

function renderSectionHead(it) {
  return `<header class="briefing-head" id="${esc(it.id || '')}">
    <h2 class="briefing-title">${esc(it.title)}</h2>
    <p class="briefing-sub">${esc(it.sub)}</p>
  </header>`;
}

function renderItem(it) {
  if (it.t === 'card') return renderCard(it.st, it.size, it.opts);
  if (it.t === 'live') return renderLive();
  if (it.t === 'hot') return renderHot();
  if (it.t === 'repos') return renderRepos();
  if (it.t === 'repos-full') return renderRepos(true);
  if (it.t === 'models') return renderModels();
  if (it.t === 'saved-rest') return renderSavedRest();
  if (it.t === 'section-head') return renderSectionHead(it);
  return '';
}

function renderChunk(limit) {
  let html = '';
  while (pos < seq.length) {
    const it = seq[pos];
    if (it.t === 'card' && shownCards >= limit) break;
    html += renderItem(it);
    if (it.t === 'card') shownCards++;
    pos++;
  }
  return html;
}

function updateMore() {
  const left = totalCards - shownCards;
  $('#feed-more').hidden = left <= 0;
  $('#more-btn').textContent = `Xem thêm ${Math.min(PAGE_MORE, left)} tin`;
  $('#feed-end').hidden = left > 0 || !totalCards;
}

/* The end block speaks for what this view holds: the whole feed, or only the filtered stories. */
function renderEnd() {
  const n = listFor(filter).length;
  const every = D.freshness && Number(D.freshness.expected_interval_seconds);
  const cadence = Number.isFinite(every) && every > 0 ? ` Bản tin được làm mới khoảng ${Math.round(every / 60)} phút một lần.` : '';
  $('#feed-end-stats').innerHTML = filter === 'all'
    ? `Bạn đã xem hết <span class="num">${n}</span> tin trong ${winH} giờ qua, từ <span class="num">${srcCount}</span> nguồn.${cadence} Mỗi tin đều dẫn về bài gốc.`
    : `Bạn đã xem hết <span class="num">${n}</span> tin trong nhóm ${esc(LABELS[filter])}.`;
  $('#mark-all-btn').textContent = filter === 'all' ? 'Đánh dấu đã xem hết' : 'Đánh dấu nhóm này đã xem';
}

function renderFeed() {
  renderPicks();
  seq = filter === 'all' ? buildAll() : buildFiltered(filter);
  pos = 0; shownCards = 0;
  totalCards = seq.filter(x => x.t === 'card').length;
  const html = renderChunk(PAGE_FIRST);
  const empty = !html.trim();                      // tiles with no data render nothing, so judge by the output
  $('#feed-empty').hidden = !empty;
  $('#feed-grid').innerHTML = html;
  updateMore();
  renderSub();
  renderEnd();
  renderChips();
  $('#top').removeAttribute('aria-busy');
  hydrateHF(document);
  observeSkips();
}

function more(focus = true) {
  const grid = $('#feed-grid');
  const before = grid.querySelectorAll('.feed-card').length;
  grid.insertAdjacentHTML('beforeend', renderChunk(shownCards + PAGE_MORE));
  updateMore();
  hydrateHF(document);
  observeSkips();
  // Keep keyboard users in place: focus the first card that just arrived.
  const next = grid.querySelectorAll('.feed-card')[before];
  if (focus && next) next.querySelector('.story-link').focus({ preventScroll: true });
}
/* Render further chunks until an element for a matching story exists (the first new story, #tin/<id>). */
function revealStory(pred, cardsOnly = false) {
  const sel = cardsOnly ? '#picks-grid .feed-card[data-sid], #feed-grid .feed-card[data-sid]' : '#picks-grid [data-sid], #feed-grid [data-sid]';
  const find = () => $$(sel).find(el => !el.closest('[hidden]') && pred(el.dataset.sid));
  let el = find();
  while (!el && pos < seq.length) { more(false); el = find(); }
  return el || null;
}
function focusStory(el) {
  const bar = $('#bar') ? $('#bar').offsetHeight : 64;
  window.scrollTo({ top: Math.max(0, scrollY + el.getBoundingClientRect().top - bar - 16), behavior: RM.matches ? 'auto' : 'smooth' });
  const f = el.matches('a, button') ? el : el.querySelector('.story-link, a');
  if (f) f.focus({ preventScroll: true });
}

/* ---------- head, filters, new items ---------- */
let winH = 72, srcCount = 0;
const LABELS = {};
const DATE_VN = new Intl.DateTimeFormat('vi-VN', { day: 'numeric', month: 'numeric', timeZone: TZ });
function updatedAt(iso) {
  const d = new Date(iso);
  return dayKey(d) === todayKey() ? hhmm(d) : `${hhmm(d)} ngày ${DATE_VN.format(d)}`;
}
function renderSub() {
  const sub = $('#feed-sub');
  if (filter === 'all') {
    sub.innerHTML = `<span class="num">${allStories.length}</span> tin trong ${winH} giờ qua, từ <a class="text-link" href="#nguon"><span class="num">${srcCount}</span> nguồn</a>. Cập nhật lúc <time datetime="${esc(D.generated_at)}">${esc(updatedAt(D.generated_at))}</time>.`;
  } else {
    const s = secOf(filter), n = filter === 'saved' ? saved.length : listFor(filter).length;
    sub.innerHTML = `${s ? 'Đang xem mục' : 'Đang lọc'}: ${esc(LABELS[filter] || '')} · <span class="num">${n}</span> ${filter === 'saved' ? 'mục' : 'tin'} <button class="text-btn" data-reset>${s ? 'Về dòng tin' : 'Bỏ lọc'}</button>`;
  }
}
function renderChips() {
  $$('.filter-chip').forEach(b => {
    const f = b.dataset.filter;
    LABELS[f] = LABELS[f] || b.textContent.trim();
    const n = f === 'all' ? allStories.length : f === 'saved' ? saved.length : listFor(f).length;
    b.innerHTML = `${esc(LABELS[f])} <span class="count num">${n}</span>`;
    b.hidden = f !== 'all' && n === 0 && f !== filter;
    b.setAttribute('aria-pressed', String(f === filter));
  });
}
/* fromHash: the address chose the view, so it stays in the address bar; a chip clears it. */
function setFilter(f, fromHash = false) {
  if (!D) return;
  filter = f;
  if (!fromHash && location.hash.length > 1) history.replaceState(null, '', location.pathname + location.search);
  renderFeed();
  const top = $('#top').getBoundingClientRect().top;
  if (top < 0) window.scrollTo({ top: window.scrollY + top - 8 });
}
function renderSortSwitch() {
  $$('.sort-btn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.sort === sortMode)));
  $('#sort-switch').hidden = false;
}
function setSort(m) {
  sortMode = m === 'new' ? 'new' : 'worth';
  store.set(K.sort, sortMode);
  renderSortSwitch();
  renderFeed();
}
const newCount = () => allStories.filter(st => storyStatus(st.id, st) === 'new').length;
/* "N tin mới": what arrived since the reader's last look (on a first visit, the last 24 hours), as on the bento home. */
function renderNewItems() {
  const n = newCount();
  $('#moi').hidden = !n;
  if (n) $('#new-items-text').textContent = firstVisit ? `${n} tin mới trong 24 giờ qua` : `${n} tin mới từ lần trước bạn ghé`;
}
function goFirstNew() {
  if (!D) return;
  if (filter !== 'all') setFilter('all', true);
  const el = revealStory(id => { const st = STORY_ANY.get(id); return !!st && storyStatus(id, st) === 'new'; });
  if (!el) { toast('Chưa có tin mới. Trang tự kiểm mỗi 3 phút'); return; }
  focusStory(el);
}
/* "Đánh dấu đã xem": the last look moves to this snapshot, so nothing here counts as new any more. */
function markSeen() {
  if (!D) return;
  const hadFocus = $('#moi').contains(document.activeElement);
  store.set(K.lastSeen, D.generated_at);
  lastSeen = D.generated_at; firstVisit = false; arrived = new Set();
  new Set($$('[data-sid]').map(el => el.dataset.sid)).forEach(paintStatus);
  renderNewItems();
  if (hadFocus) $('#top').focus({ preventScroll: true });
  toast('Đã đánh dấu đã xem hết');
}

let toastT = 0;
function toast(msg) {
  const c = $('#toast-container');
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg;
  c.replaceChildren(t);
  clearTimeout(toastT);
  toastT = setTimeout(() => t.remove(), 3200);
}

/* ---------- saving: stories and repositories, under the bento home's key and record shape ---------- */
function toggleSave(key) {
  if (!key) return;
  const st = STORY_ANY.get(key), rp = key.startsWith('repo:') ? REPO.get(key.slice(5)) : null;
  if (savedHas(key)) { saved = saved.filter(x => x.key !== key); toast('Đã bỏ lưu'); }
  else {
    if (!st && !rp) return;
    saved.push({ key, title: st ? titleOf(st).text : rp.full_name, url: st ? st.url : rp.url, at: new Date().toISOString() });
    toast('Đã lưu. Xem lại ở mục Đã lưu');
  }
  store.set(K.saved, saved.slice(-300));
  const on = savedHas(key);
  $$(`[data-act="save"][data-id="${CSSq(key)}"]`).forEach(b => { b.classList.toggle('is-saved', on); b.setAttribute('aria-pressed', String(on)); });
  // The saved view keeps an unsaved item on screen until the reader leaves it, so a mistaken tap can be undone in place.
  renderChips();
  renderSub();
}

/* ---------- a newer snapshot: polled every 3 minutes, applied only when the reader asks ---------- */
let pending = null;
async function pollSnapshot() {
  if (document.hidden || !D) return;
  try {
    const j = await loadData({ cache: 'no-cache' });
    if (!j || !j.generated_at || j.generated_at <= D.generated_at) return;
    pending = j;
    const fresh = asArray(j.stories).filter(s => !STORY_ANY.has(s.id)).length;
    $('#fresh').innerHTML = `<button class="fresh-btn" id="fresh-go" aria-keyshortcuts="U">${icon('i-up')}<span>${fresh ? `<span class="num">${fresh}</span> tin mới` : 'Số liệu vừa cập nhật'}</span><span aria-hidden="true">·</span><span>Xem</span></button>`;
  } catch { /* a failed poll keeps the current snapshot; the next poll tries again */ }
}
function applyPending() {
  if (!pending) return;
  commitLastSeen();
  const newIds = asArray(pending.stories).filter(s => !STORY_ANY.has(s.id)).map(s => s.id);
  arrived = new Set(newIds);
  const data = pending; pending = null;
  $('#fresh').innerHTML = '';
  ingest(data);
  if (filter !== 'all') filter = 'all';
  renderAll();
  const el = newIds.length ? revealStory(id => arrived.has(id)) : null;
  if (el) focusStory(el);
  else { scrollTo({ top: 0, behavior: RM.matches ? 'auto' : 'smooth' }); $('#top').focus({ preventScroll: true }); }
  setTimeout(() => { arrived = new Set(); }, 3000);
}

/* ---------- old data says so in words; rewritten only when the words change, so a screen reader hears it once ---------- */
function renderStale() {
  const el = $('#stale'); if (!el || !D) return;
  const text = freshnessText(freshness(D.generated_at, D.sources), D.generated_at);
  if (el.dataset.text === text) return;
  el.dataset.text = text;
  el.hidden = !text;
  el.textContent = text || '';
}

/* ---------- every source of the snapshot, the live layer, and how the page works ---------- */
let liveState = null;
function liveRows() {
  if (!liveState) return '<li class="src-wait">Lớp trực tiếp đang đọc lần đầu</li>';
  return [...liveState.values()].map(s => `<li><span class="dot ${s.ok === true ? 'ok' : s.ok === false ? 'warn' : ''}" aria-hidden="true"></span><a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(s.label)}</a>
    <span class="src-n">${s.at ? `${s.ok ? `${s.matched} tin khớp · ` : ''}${hhmm(s.at)}` : 'đang đọc'}</span>${s.error ? `<span class="src-err">${esc(s.error)}. Đang giữ số trong bản tin.</span>` : ''}</li>`).join('');
}
function translationNote() {
  const t = D.translation;
  if (!t || typeof t !== 'object') return 'Tiêu đề giữ nguyên tiếng Anh như bài gốc.';
  const done = Number.isFinite(t.translated) && t.translated > 0;
  const base = done ? 'Tiêu đề tiếng Việt là bản dịch máy bằng mô hình NLLB-200 (giấy phép CC-BY-NC 4.0, chỉ dùng phi thương mại); tiêu đề gốc nằm ngay dưới, kèm nhãn “Translated”.' : 'Tiêu đề giữ nguyên tiếng Anh như bài gốc.';
  const left = Number.isFinite(t.pending) && t.pending > 0 ? ` Còn ${fmt(t.pending)} tiêu đề chưa dịch kịp, đang hiện bản gốc.` : '';
  return `${base}${t.error_vi ? ` ${esc(t.error_vi)}` : left}`;
}
function footHTML() {
  const r = D.ranking;
  const rank = r ? `Xếp hạng nóng: ${esc(r.description || 'xếp theo số đo của từng nguồn')}, cửa sổ ${esc(r.window_hours)} giờ${r.description && r.calibration ? `, hiệu chỉnh: ${esc(r.calibration)}` : ''}. Đây là cách xếp theo số đo, không phải phán xét tầm quan trọng.` : 'Bản dữ liệu này không mô tả cách xếp hạng nóng.';
  const scoring = ' Điểm đáng đọc được tính tự động từ 4 tín hiệu số đo (độ chú ý, độ lan rộng nhiều nguồn, độ mới và công bố gốc), không có điểm gõ tay.';
  const views = D.views && Number.isFinite(D.views.total) ? ` Lượt xem trên ai-radar: <span class="num">${fmt(D.views.total)}</span>, đo lúc ${esc(exact(D.views.measured_at))}, không dùng cookie.` : '';
  const local = storageOk ? 'Mốc đã xem, tin đã đọc, tin đã lưu và lựa chọn của bạn chỉ lưu trên máy này.'
    : 'Trình duyệt đang chặn bộ nhớ cục bộ, nên mốc đã xem, tin đã lưu và lựa chọn của bạn chỉ giữ tới khi đóng trang.';
  return `Dữ liệu tạo lúc ${esc(exact(D.generated_at))} giờ Việt Nam. ${rank}${scoring} ${translationNote()}${views} ${local}`;
}
function renderSources() {
  const srcs = asArray(D.sources), bad = srcs.filter(s => !s.ok);
  $('#src-note').innerHTML = `<span class="num">${srcs.length - bad.length}/${srcs.length}</span> nguồn chạy được lúc ${esc(hhmm(new Date(D.generated_at)))}. Mỗi nguồn kèm số tin lấy được.`;
  $('#src-list').innerHTML = [...srcs].sort((a, b) => a.ok - b.ok || (b.count || 0) - (a.count || 0)).map(s => `<li${s.ok ? '' : ' class="is-bad"'}>${avatar(faceOfSource({ source: s.id, lab: s.lab, publisher: s.publisher }, SRC), 'xs')}<a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(s.name || s.id)}</a>
    <span class="src-n num">${s.ok ? `${s.count ?? 0} tin` : 'lỗi'}</span>${s.error ? `<span class="src-err">${esc(s.error_vi || 'Không đọc được nguồn này')}</span>` : ''}</li>`).join('');
  $('#src-live').innerHTML = liveRows();
  $('#src-foot').innerHTML = footHTML();
  $('#nguon').hidden = false;
}

/* ---------- live counters (live.js, as on the bento home): the numbers on screen follow the sources ---------- */
function applyLive(updates) {
  for (const u of updates) {
    if (!u.cov.metrics) u.cov.metrics = {};
    u.cov.metrics[u.metric] = u.value;
    $$(`[data-live="${CSSq(u.cov.id + '|' + u.metric)}"]`).forEach(el => { el.textContent = fmt(u.value); });
  }
}

/* ---------- addresses: every one the bento home answered, and the search page links to ---------- */
function openStory(id) {
  const st = STORY_ANY.get(id);
  if (!st) { toast('Tin này không còn trong bản tin hiện tại'); return; }
  const is = el => el.dataset.sid === id;
  let el = revealStory(sid => sid === id, true);
  if (!el) {
    // Not a card in the main feed (the hot tile or the ranked block shows it, or it is outside the window): open the
    // first view that lists it as a card.
    const views = [...Object.keys(FILTERS), ...Object.keys(SECTIONS).map(k => 'sec:' + k)];
    for (const f of views) {
      if (!listFor(f).some(s => s.id === id)) continue;
      setFilter(f, true);
      el = revealStory(sid => sid === id, true);
      if (el) break;
    }
  }
  if (!el || !is(el)) { toast('Tin này không còn trong dòng tin'); return; }
  const btn = el.querySelector('.cov-btn');
  if (btn) toggleDetail(btn, true);
  focusStory(el);
}
function route() {
  if (!D) return;
  const h = decodeURIComponent(location.hash.slice(1));
  if (!h || h === 'top') return;                 // the browser scrolls; a filter the reader chose stays
  if (h === 'moi') { goFirstNew(); return; }
  if (h === 'nong') { setFilter('hot', true); return; }
  if (h === 'repo') { setFilter('code', true); return; }
  if (h === 'da-luu') { if (saved.length) setFilter('saved', true); return; }
  if (h === 'nguon') { $('#nguon').scrollIntoView(); return; }
  if (SECTIONS[h]) { setFilter('sec:' + h, true); return; }
  const m = /^tin\/(.+)$/.exec(h);
  if (m) openStory(m[1]);
}

/* ---------- a picture that fails to load becomes its cover, never an empty box ---------- */
function watchPictures() {
  document.addEventListener('error', e => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || img.classList.contains('av-img')) return;
    if (img.classList.contains('media-img')) {
      const card = img.closest('.feed-card'), st = card && STORY_ANY.get(card.dataset.id);
      if (!st) return;
      const cv = coverPick(st);
      PICKED.set(st.id, cv);
      card.dataset.via = 'cover';
      img.parentElement.innerHTML = coverHTML(cv.cover);
      if (card.classList.contains('card-photo')) {
        card.classList.remove('card-photo');
        const b = card.querySelector('.photo-body'); if (b) b.className = 'card-body';
      }
      return;
    }
    const thumb = img.closest('.thumb');
    if (thumb) { const st = STORY_ANY.get(thumb.dataset.id); thumb.innerHTML = st ? miniCover(st) : ''; return; }
    if (img.closest('.tile-video, .repo-img, .model-img')) img.remove();
  }, true);
}

/* ---------- keyboard: the bento home's shortcuts ---------- */
const STORY_SEL = '#picks-grid .story-link, #picks-grid .pick-row, #feed-grid .story-link, #feed-grid .hot-row, #feed-grid .repo';
const storyEls = () => $$(STORY_SEL).filter(el => el.getClientRects().length && !el.closest('[hidden]'));
function move(dir) {
  const list = storyEls(); if (!list.length) return;
  let i = list.indexOf(document.activeElement);
  if (i < 0) {
    // Nothing focused yet: start from the first story below the bar, so J lands on what the reader is looking at.
    const top = $('#bar').getBoundingClientRect().bottom;
    const first = list.findIndex(el => el.getBoundingClientRect().top >= top);
    i = (first < 0 ? list.length : first) - (dir > 0 ? 1 : 0);
  }
  const next = list[Math.max(0, Math.min(list.length - 1, i + dir))];
  next.focus({ preventScroll: true });
  next.scrollIntoView({ block: 'nearest', behavior: RM.matches ? 'auto' : 'smooth' });
}
const currentEl = () => { const a = document.activeElement; return a && a.closest ? a.closest('[data-sid]') : null; };
function openCurrent() {
  const el = currentEl(); if (!el) return;
  const a = el.matches('a[href]') ? el : el.querySelector('.story-link, a.repo, a[href]');
  if (!a) return;
  window.open(a.href, '_blank', 'noopener');
  markRead(el.dataset.sid);
}
function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
  const t = e.target instanceof Element ? e.target : null;
  if (t && t.closest('input,textarea,select,[contenteditable="true"]')) return;
  if ($('#keys').open) return;
  const k = e.key;
  if (k === 'Escape') {
    const panel = t && t.closest('.cov-list:not([hidden])');
    const card = t && t.closest('.feed-card');
    const btn = card && card.querySelector('.cov-btn[aria-expanded="true"]');
    if (btn && (panel || t === btn)) { toggleDetail(btn, false); btn.focus(); }
    return;
  }
  if (k === 'j' || k === 'J') { e.preventDefault(); move(1); }
  else if (k === 'k' || k === 'K') { e.preventDefault(); move(-1); }
  else if (k === 'o' || k === 'O') openCurrent();
  else if (k === 's' || k === 'S') { const el = currentEl(); if (el) toggleSave(el.dataset.sid); }
  else if (k === 'l' || k === 'L') {
    const el = currentEl(), st = el && STORY_ANY.get(el.dataset.sid), cal = st ? calOf(st) : null;
    if (cal) addToCalendar(cal); else if (el) toast('Tin này không có lịch để thêm');
  }
  else if (k === 'u' || k === 'U') { if (pending) applyPending(); else goFirstNew(); }
  else if (k === 'm' || k === 'M') { if (D && newCount()) markSeen(); }
  else if (k === 'g' || k === 'G') { scrollTo({ top: 0, behavior: RM.matches ? 'auto' : 'smooth' }); }
  else if (k === '/') { e.preventDefault(); location.href = 'tra-cuu.html'; }
  else if (k === '?') { e.preventDefault(); $('#keys').showModal(); }
}

/* ---------- events ---------- */
function onClick(e) {
  const t = e.target instanceof Element ? e.target : null;
  if (!t) return;
  const act = t.closest('.act');
  if (act && act.dataset.act === 'copy') {
    const u = act.dataset.url;
    (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject(new Error())).then(() => toast('Đã chép liên kết'), () => toast(u));
    return;
  }
  if (act && act.dataset.act === 'save') { toggleSave(act.dataset.id); return; }
  const cov = t.closest('.cov-btn'); if (cov) { toggleDetail(cov); return; }
  const cal = t.closest('[data-cal]'); if (cal) { e.preventDefault(); addToCalendar(calOf(STORY_ANY.get(cal.dataset.cal))); return; }
  const cl = t.closest('[data-cal-live]'); if (cl) { e.preventDefault(); addToCalendar(liveCal(asArray(D.live).find(v => v.video_id === cl.dataset.calLive))); return; }
  const ce = t.closest('[data-cal-ev]');
  if (ce) {
    e.preventDefault();
    const ev = asArray(D.events).find(x => String(x.id) === ce.dataset.calEv);
    if (ev) addToCalendar({ uid: ev.id, title: String(ev.title), url: ev.url, location: ev.location, startDate: ev.start_date, endDate: ev.end_date,
      startAt: ev.time_precision === 'exact' ? ev.start_at : null, endAt: ev.time_precision === 'exact' ? ev.end_at : null, note: verifiedNote(ev.verified_at, ev.source_url) });
    return;
  }
  const area = t.closest('[data-area]');
  if (area) { const a = area.dataset.area; if (areas.has(a)) areas.delete(a); else areas.add(a); store.set(K.areas, [...areas]); rerenderRepos(); return; }
  if (t.closest('[data-area-clear]')) { areas.clear(); store.set(K.areas, []); rerenderRepos(); return; }
  const rc = t.closest('button[data-repo-view],button[data-repo-window],button[data-repo-total]');
  if (rc) { const k = ['repoView', 'repoWindow', 'repoTotal'].find(k => rc.dataset[k] != null); setRepo(k.slice(4).toLowerCase(), rc.dataset[k]); return; }
  if (t.closest('#fresh-go')) { applyPending(); return; }
  if (t.closest('#keys-open')) { $('#keys').showModal(); return; }
  if (t.closest('#keys-x')) { $('#keys').close(); return; }
  if (t.closest('[data-reset]')) { setFilter('all'); return; }
  onOpenLink(e);
}
/* Opening a story by any link (left, middle or keyboard) marks it seen. */
function onOpenLink(e) {
  const t = e.target instanceof Element ? e.target : null;
  const a = t && t.closest('a[data-read], a.story-link');
  if (!a) return;
  markRead(a.dataset.read || a.dataset.id);
}
function attachEvents() {
  $('#theme-btn').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.getAttribute('data-theme') === 'dark' || (!root.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    $('#theme-btn').setAttribute('aria-pressed', String(next === 'dark'));
    store.set(K.theme, next);
  });
  $('.feed-brand').addEventListener('click', () => { if (filter !== 'all') setFilter('all'); });
  $('#feed-filters').addEventListener('click', e => { const b = e.target.closest('.filter-chip'); if (b) setFilter(b.dataset.filter); });
  $('#reset-filter-btn').addEventListener('click', () => setFilter('all'));
  $('#more-btn').addEventListener('click', () => more());
  $('#new-go').addEventListener('click', goFirstNew);
  $('#mark-seen-btn').addEventListener('click', markSeen);
  $('#mark-all-btn').addEventListener('click', () => {
    if (!D) return;
    listFor(filter).forEach(st => markRead(st.id));
    if (filter === 'all') markSeen();
    else toast('Đã đánh dấu nhóm này đã xem');
  });
  const howBtn = $('#how-btn');
  if (howBtn) {
    howBtn.addEventListener('click', () => {
      const panel = $('#how-panel');
      if (!panel) return;
      const open = panel.hidden;
      panel.hidden = !open;
      howBtn.setAttribute('aria-expanded', String(open));
      howBtn.textContent = open ? 'Ẩn cách chấm' : 'Cách chấm';
    });
  }
  $('#keys').addEventListener('click', e => { if (e.target === $('#keys')) $('#keys').close(); });
  document.addEventListener('click', onClick);
  document.addEventListener('auxclick', e => { if (e.button === 1) onOpenLink(e); });
  document.addEventListener('keydown', onKey);
}

/* ---------- one snapshot in: everything the page derives from it ---------- */
function ingest(data) {
  D = data;
  SRC = new Map(asArray(D.sources).map(s => [s.id, s]));
  winH = Number(D.ranking && D.ranking.window_hours);
  if (!Number.isFinite(winH) || winH <= 0) winH = 72;
  const gen = ms(D.generated_at), from = gen - winH * 36e5;
  GEN = gen || Date.now();
  allStories = asArray(D.stories).filter(st => { const t = ms(st.published_at); return t && t >= from && t <= gen + 3e5; })
    .sort((a, b) => ms(b.published_at) - ms(a.published_at));
  STORY = new Map(allStories.map(st => [st.id, st]));
  STORY_ANY = new Map(asArray(D.stories).map(st => [st.id, st]));
  REPO = new Map(asArray(D.repos).filter(r => r && r.id != null && r.full_name).map(r => [String(r.id), r]));
  srcCount = new Set(allStories.flatMap(st => (st.coverage || []).map(c => srcName(c.source)))).size;
  WORTHS.clear(); PICKED.clear(); WORDS.clear();
  const hot = allStories.filter(st => st.hot_score > 0).sort((a, b) => b.hot_score - a.hot_score);
  const k = Math.max(3, Math.min(10, Math.round(allStories.length / 12)));
  bigSet = new Set(hot.slice(0, k).map(st => st.id));
  allStories.forEach(st => { if (nSrc(st) >= 3) bigSet.add(st.id); });
  matchPicks(RAW_PICKS);
  PICKLIST = choosePicks();
  // The bento home's rule: a first visit counts the last 24 hours as new; later visits count from the last look.
  const stored = store.get(K.lastSeen, null);
  firstVisit = !stored;
  lastSeen = stored || new Date((gen || Date.now()) - 864e5).toISOString();
}
function renderAll() {
  renderChips();
  renderNewItems();
  renderHow();
  renderSortSwitch();
  renderFeed();
  renderStale();
  renderSources();
}

/* ---------- start ---------- */
const whenIdle = () => new Promise(r => {
  const go = () => 'requestIdleCallback' in window ? requestIdleCallback(() => r(), { timeout: 3000 }) : setTimeout(r, 1000);
  if (document.readyState === 'complete') go(); else addEventListener('load', go, { once: true });
});
function startLifecycle() {
  setInterval(pollSnapshot, SNAPSHOT_EVERY_MS);
  document.addEventListener('visibilitychange', () => { if (document.hidden) commitLastSeen(); else pollSnapshot(); });
  addEventListener('pagehide', () => commitLastSeen());
  // The last look moves on engagement: five seconds on the page or the first scroll.
  let engaged = false;
  const onEngage = () => { if (!engaged) { engaged = true; commitLastSeen(); } };
  setTimeout(onEngage, 5000);
  addEventListener('scroll', onEngage, { passive: true, once: true });
  // Relative times and the stale line stay honest while the tab is open.
  setInterval(() => { $$('[data-ago]').forEach(el => { el.textContent = ago(el.dataset.ago); }); renderStale(); }, 60_000);
  window.commitLastSeen = commitLastSeen; window.storyStatus = storyStatus;
}
async function startLiveLayer() {
  await whenIdle();
  try {
    const { startLive } = await import('./live.js');
    startLive({
      getStories: () => D.stories,
      priority: hnId => { const st = asArray(D.stories).find(s => (s.coverage || []).some(c => (c.discussion_url || '').endsWith('=' + hnId))); return st ? (st.hot_score || 0) : 0; },
      onUpdates: applyLive,
      onStatus: st => { liveState = st; const el = $('#src-live'); if (el) el.innerHTML = liveRows(); },
    });
  } catch (e) { console.warn('live counters unavailable; the snapshot numbers stay', e); }
}
async function init() {
  const th = store.get(K.theme, null);
  if (th) document.documentElement.setAttribute('data-theme', th);
  $('#theme-btn').setAttribute('aria-pressed', String(th ? th === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches));
  watchImageErrors();
  watchPictures();
  attachEvents();
  try {
    const [, data, picks] = await Promise.all([loadImages(), loadData(), loadPicks()]);
    RAW_PICKS = picks;
    ingest(data);
    sortMode = store.get(K.sort, store.get(LEGACY.sort, 'worth')) === 'new' ? 'new' : 'worth';
    for (const [k, s] of Object.entries(SECTIONS)) LABELS['sec:' + k] = s.label;
    $('#feed-empty p').textContent = `Trong ${winH} giờ qua chưa có tin thuộc nhóm này. Chọn nhóm khác hoặc xem tất cả.`;
    renderAll();
  } catch (err) {
    console.error('feed load failed', err);
    $('#top').removeAttribute('aria-busy');
    $('#feed-grid').innerHTML = '';
    $('#feed-sub').textContent = 'Chưa nạp được dòng tin. Kiểm tra kết nối rồi tải lại trang.';
    const em = $('#feed-empty');
    em.querySelector('h2').textContent = 'Chưa nạp được dòng tin';
    em.querySelector('p').textContent = 'Lỗi mạng hoặc dữ liệu không hợp lệ. Trang không thay bằng tin mẫu.';
    const b = $('#reset-filter-btn');
    b.textContent = 'Tải lại';
    b.addEventListener('click', () => location.reload());
    em.hidden = false;
    return;
  }
  route();
  addEventListener('hashchange', route);
  startLifecycle();
  startLiveLayer();
}

init();

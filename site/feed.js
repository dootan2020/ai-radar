/* Halcyon · the site root since 05/10 (owner, 05/10 ~01:30: the feed replaces the bento home).
   Owner, 04/10 20:28: flat like the Edge start page and Google Discover. No borders, no accent bars, every card led by
   a picture. Pictures are the ones each source publishes, or a labelled AI illustration from the pipeline; a story
   without either gets the site's factual cover.

   One function decides every story picture: pickImage(). Screened stories use the pipeline image, then the cover; legacy
   stories walk IMAGE_PROVIDERS before the cover fallback.

   "Đáng đọc" round (owner, 04/10 21:35): what to read first. One score per story from measured signals only (WORTH,
   worthOf), a block of 3 to 5 stories on top with a reason line in real numbers, a reason chip per card, a sort switch,
   and "Biên tập chọn" only from editor-picks.json.

   Carried over from the bento home (retired 09/11), in the feed's own look: the edition and search
   links (static, in index.html), the new / seen marks with the same storage keys, the "N tin mới" pill
   that goes to the first new story, saved stories, the repository lists,
   calendar export, live counters, every source's state, keyboard shortcuts, and every address the bento home answered
   (#tin/<id>, #sap-toi; the retired section anchors land on the home feed). */

import { esc, fmt, avatar, faceOfStory, faceOfSource, hydrateHF, monogram, watchImageErrors, ytIdOf } from './faces.js';
import { ago, dayKey, hhmm, TZ, streamedAge, scheduleText, eventRange } from './time-text.js';
import { KIND, METRIC } from './words.js';
import { shown, uniqCoverage } from './titles.js';
import { headlineShown, hasEditorialSummary, sourceDescriptionMark } from './editorial-headline.js';
import { canCalendar, downloadIcs, gcalURL, verifiedNote, dateStart, nextDay } from './calendar.js';
import { WORTH, fallbackWorth, hotEligible } from './worth-score.js';
import { renderStoryHTML, mediaBackdrop } from './story.js';
import { createArenaView, loadArena, modelName, makerName, scoreText } from './arena.js';
import { createNewsSearch } from './tim-tin.js';
import { createWeatherCard } from './thoi-tiet.js';
import { createCalendarCard } from './the-lich.js';

/* Same-origin JSON only; ?data=data/<file>.json lets a maintainer load another snapshot from site/data/ (as on the
   bento home). The first request matches index.html's preload (same mode, no cache option), so it is reused. */
const qp = new URLSearchParams(location.search).get('data');
const customData = !!qp && /^data\/[\w.-]+\.json$/.test(qp);
const DATA_URL = customData ? qp : 'data/radar-ui.json';
const SOURCES = customData ? [qp] : [DATA_URL, 'data/radar.json'];
/* First load: only the stories inside the ranking window, every other field whole (radar/site_payload.py,
   window_payload). The first screen is drawn from those stories alone, so it paints from about a fifth of the bytes.
   The complete snapshot follows once the page has settled, for sections, saved stories and story addresses outside
   the window. index.html preloads this file. */
const WINDOW_URL = customData ? null : 'data/radar-window.json';
let complete = customData;    // true once D holds every story of the snapshot
let completeLoad = null;      // the one request for the complete snapshot in flight
const IMAGES_URL = 'feed-images.json';
const PICKS_URL = 'editor-picks.json';   // the owner's own picks; the only thing allowed to say "Biên tập chọn"
const FIELD_RANKINGS_URL = 'data/field-rankings.json';
let FIELD_DATA = null;
let FIELD_MAP = new Map();
/* The bento home's keys, so a returning reader keeps what they read, skipped, saved and chose there. */
const K = { theme: 'air2:theme', read: 'air2:read', skipped: 'air2:skipped', lastSeen: 'air2:lastSeen', saved: 'air2:saved',
  sort: 'air2:sort', repoView: 'air2:repoView', repoWindow: 'air2:repoWindow', repoTotal: 'air2:repoTotal', areas: 'air2:areas' };
const LEGACY = { read: 'airtl:read', saved: 'airtl:saved', sort: 'airtl:sort' };   // the 04/10 prototype's keys, folded in once
const PAGE_FIRST = 22, PAGE_MORE = 14;   // infinite scroll (Mẫu A): the first screenful, then quiet batches
const EDITION_URL = 'ban-tin.html';
const SNAPSHOT_EVERY_MS = 180_000;

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const icon = id => `<svg class="i" aria-hidden="true"><use href="#${id}"/></svg>`;
const nf1 = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 });
const EXACT = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'full', timeStyle: 'short', timeZone: TZ });
const ms = iso => new Date(iso).getTime() || 0;
const CSSq = s => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&');
const RM = matchMedia('(prefers-reduced-motion: reduce)');
if (!RM.matches) {
  document.documentElement.classList.add('js-motion');
}
if (RM.addEventListener) {
  RM.addEventListener('change', () => {
    if (RM.matches) document.documentElement.classList.remove('js-motion');
    else document.documentElement.classList.add('js-motion');
  });
}
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
let arenaView = null;
let sortMode = 'worth';       // 'worth' (Đáng đọc nhất) or 'new' (Mới nhất); the reader's choice is remembered
const PICKS = new Map();      // story id -> {note}, from editor-picks.json, in the file's order
let RAW_PICKS = [];
let PICKLIST = [];            // the "Đáng đọc hôm nay" block: editor picks first, then the highest scores
let seq = [], pos = 0, shownCards = 0, totalCards = 0;
let newsSearch = null;        // the news bar's inline search (tim-tin.js)

/* ---------- new, seen, skipped (the bento home's rules, tests/test_tin_moi.py) ----------
   new: published after the reader's last look; seen: opened; skipped: scrolled past without opening.
   Skipped IDs suppress the new dot without adding a visual mark. Priority: seen, then skipped, then new.
   The last look moves on engagement (five seconds or the first scroll), when the page is hidden or left, and when
   the reader applies a fresh snapshot; never only by a button. */
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
  if (skipped.has(id)) return 'none';
  if (arrived.has(id) || (st && isNew(st))) return 'new';
  return 'none';
}
const MARK = {
  new: '<span class="new-mark" aria-hidden="true"></span><span class="sr">Mới. </span>',
  seen: `<span class="seen-mark" aria-hidden="true">${icon('i-check')}</span><span class="sr">Đã xem. </span>`,
  none: '',
};
const STATUS_CLASS = { seen: 'is-read', new: 'is-new', none: '' };
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
    el.classList.remove('is-read', 'is-new');
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
  retireNewItem(id);
}
function markSkipped(id) {
  if (!id || read.has(id) || skipped.has(id) || arrived.has(id)) return;
  skipped.add(id);
  store.set(K.skipped, [...skipped].slice(-2000));
  paintStatus(id);
  retireNewItem(id);
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
  // The "Vừa đăng" row repeats stories that also have their own place; only that place counts as passed.
  $$('[data-sid]').forEach(el => { if (!el._observed && !el.closest('#fresh-row')) { el._observed = true; skipObserver.observe(el); } });
}

/* ---------- motion: staggered fade-up & blur-up images ---------- */
function markImgLoaded(img) {
  if (img && !img.classList.contains('is-loaded')) {
    img.classList.add('is-loaded');
  }
}

function watchImageLoad() {
  document.addEventListener('load', e => {
    const t = e.target;
    if (t instanceof HTMLImageElement && (t.classList.contains('media-img') || t.closest('.thumb, .tile-video, .repo-img, .model-img'))) {
      markImgLoaded(t);
    }
  }, true);
}

function hydrateLoadedImages(root = document) {
  root.querySelectorAll('.media-img, .thumb img, .tile-video img, .repo-img img, .model-img img').forEach(img => {
    if (img.complete && img.naturalWidth > 0) {
      markImgLoaded(img);
    }
  });
}

let motionObserver = null;
const STAGGER_STEP = 60;   // ms per card
const STAGGER_CAP = 240;   // max stagger delay so long lists never delay readers
const CARD_ENTER_MS = 280; // duration matching CSS

function observeCardMotion(root = document) {
  if (RM.matches || typeof IntersectionObserver === 'undefined') return;

  const candidates = [...root.querySelectorAll('.feed-card, .tile')]
    .filter(el => !el.classList.contains('motion-entry') && !el.classList.contains('motion-done'));
  if (!candidates.length) return;

  if (!motionObserver) {
    motionObserver = new IntersectionObserver((entries, obs) => {
      const visible = entries
        .filter(e => e.isIntersecting)
        .map(e => e.target)
        .filter(el => el.classList.contains('motion-entry') && !el.classList.contains('is-entered'));

      if (!visible.length) return;

      visible.forEach((el, index) => {
        obs.unobserve(el);
        const delay = Math.min(index * STAGGER_STEP, STAGGER_CAP);
        el.style.transitionDelay = `${delay}ms`;
        requestAnimationFrame(() => {
          el.classList.add('is-entered');
        });
        setTimeout(() => {
          el.classList.remove('motion-entry', 'is-entered');
          el.classList.add('motion-done');
          el.style.transitionDelay = '';
        }, delay + CARD_ENTER_MS + 40);
      });
    }, {
      rootMargin: '300px 0px',
      threshold: 0.05
    });
  }

  candidates.forEach(card => {
    card.classList.add('motion-entry');
    motionObserver.observe(card);
  });
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
async function loadFieldRankings() {
  try {
    const j = await fetchJSON(FIELD_RANKINGS_URL);
    if (j && Array.isArray(j.fields)) return j;
  } catch (e) {
    console.warn('field-rankings.json unavailable; area browsing falls back to snapshot repos', e);
  }
  return null;
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

/* The window file, or the complete snapshot when the window file is missing or unreadable. An address that names a
   section, the saved list or a story opens on the complete snapshot directly: drawing the window feed first and then
   switching view would count the stories on that first screen as scrolled past. */
async function loadFirst() {
  if (WINDOW_URL && !needsComplete(true)) {
    try {
      const j = await fetchJSON(WINDOW_URL);
      if (j && j.schema_version === 2 && Array.isArray(j.stories)) return j;
      console.warn('radar-window.json is not a v2 snapshot; loading the complete snapshot');
    } catch (e) { console.warn('radar-window.json unavailable; loading the complete snapshot', e); }
  }
  complete = true;
  return loadData();
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
const covName = c => c.author_handle
  ? `${c.author_name || srcName(c.source)} (@${c.author_handle})`
  : srcName(c.source);
const covsOf = st => [...uniqCoverage((st.coverage || []).filter(c => !c.author_handle), srcName),
  ...(st.coverage || []).filter(c => c.author_handle)];
const nSrc = st => Number.isFinite(st.source_count) ? st.source_count
  : new Set(covsOf(st).map(c => c.author_handle
    ? 'x' : String(c.publisher || c.source || '').toLowerCase())).size;
const exact = iso => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? 'không rõ' : EXACT.format(d); };
/* Relative times stay honest while the tab is open: every <time data-ago> is refreshed each minute. */
const timeEl = iso => `<time datetime="${esc(iso)}" data-ago="${esc(iso)}" title="${esc(exact(iso))}">${esc(ago(iso))}</time>`;

/* A measure also names the coverage item and metric it came from ("covId|metric"), so the live counters (live.js, as
   on the bento home) can refresh that number in place. */
/* A card shows a number only when it measures the page the card links to (the item titleOf picks): a story's own
   counters, or a forum thread about that same link. A cluster also holds other items (another outlet's article, a
   social post quoting it) whose counters say nothing about this headline; under it they read as this story's numbers.
   The pipeline's measurement still ranks the whole cluster; it is only not printed on a card it does not belong to.
   One forum can hold two threads in a cluster (one per link), so the measurement is matched by its value too. */
const linkKey = u => String(u || '').trim().replace(/#.*$/, '').replace(/\/+$/, '');
const cardLink = st => { const t = titleOf(st); return t.cov ? t.cov.url : st.url; };
const PREFER = ['points', 'score', 'stars', 'upvotes', 'likes', 'trending_score', 'downloads', 'comments'];
function measureOf(st) {
  const link = linkKey(cardLink(st));
  const own = link ? (st.coverage || []).filter(c => linkKey(c.url) === link) : [];
  const m = st.hot_signals && st.hot_signals.measurement;
  const mc = m && Number.isFinite(m.value) ? own.find(c => c.source === m.source && c.metrics && c.metrics[m.metric] === m.value) : null;
  if (mc) {
    return { value: m.value,
      word: METRIC[m.metric] || m.metric, where: srcName(m.source), live: mc.id ? `${mc.id}|${m.metric}` : null,
      speed: Number.isFinite(m.velocity_per_hour) && m.velocity_per_hour > 0 ? m.velocity_per_hour : null };
  }
  for (const key of PREFER) for (const c of own) {
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
  if (hasEditorialSummary(st) && st.editorial_headline_vi) return { text: headlineShown(st), orig: st.title, cov: null };
  if (ok(st.title, st.title_vi)) return { text: headlineShown(st), orig: st.title, cov: null };
  for (const c of st.coverage || []) if (ok(c.title, c.title_vi)) return { text: headlineShown(c), orig: c.title, cov: c };
  return { text: headlineShown(st), orig: null, cov: null };
}
/* Feed metadata identifies machine translations; the reading view carries the original. */
const translationMark = t => !t.orig ? '' :
  `<span class="mt" aria-hidden="true" title="Bản dịch máy">Translated</span><span class="sr" lang="vi">Bản dịch máy. </span>`;

/* ==========================================================================
   "ĐÁNG ĐỌC": WHAT TO READ FIRST
   Owner, 04/10 21:35: "có một tiêu chí gì đó để người dùng nên xem cái nào? các tin tức ở đây có trọng số chưa?"
   One score per story from four signals the feed already carries. Nothing here is typed in by hand.
     attention  hot_score (percentile of the story's number within its own source; see `ranking`
                in the feed). Counted only when the story carries a measurement: without one, the feed's hot_score
                comes from "N nguồn độc lập cùng đưa", which breadth below already counts.
     breadth    independent publishers carrying the same story (uniqCoverage: one entry per publisher).
     freshness  an additional age signal, halving every halfLifeH from the newest coverage publication time.
                The whole score also halves over that period, so renewed coverage makes an older story current again.
      firstHand  a lab publishing the story itself (coverage `lab`), or the researchers' own paper (kind 'paper').
    score = (attention + breadth + freshness) x recency x (firstHand ? WORTH.firstHand : 1)
    firstHand multiplies instead of adding, so a lab's routine post with nothing else going for it (most of the
    window's 24 first-hand stories are AWS and NVIDIA tutorials) never outranks a story people are reading.
    THE WEIGHTS ARE A FIRST GUESS (04/10). They will be calibrated on a week of real snapshots: what readers open,
    what the daily edition keeps, what an editor would have chosen (plans/reports/feed-dang-doc-report.md).
    The "Cách chấm" note on the page is written from this object, so the page and the code cannot disagree.
    ========================================================================== */
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
  const scored = fallbackWorth(st, GEN, hot, n, fh);
  w = { ...scored, hot, n, fh, metric: meas ? meas.metric : null, evidence: !!fh || n >= 2 || hot > 0 };
  WORTHS.set(st.id, w);
  return w;
}

/* The small label on a card: the one strongest reason it is there, or nothing when the only reason is its age. */
const DISCUSSED = new Set(['points', 'score', 'comments', 'upvotes']);
function reasonOf(st) {
  if (PICKS.has(st.id)) return { text: 'Biên tập chọn', editor: true };
  const w = worthOf(st);
  if (w.fh) return { text: w.fh.label };
  return null;
}
/* Hot is no longer a label but a flame at the start of the headline, the way a news front marks a hot story (owner,
   10/10 19:44: "ngọn lửa đó phải gắn ở tiêu đề bài viết '[ngọn lửa] tiêu đề'"). The flame and the first word stay
   together, so a wrap never leaves the flame alone on a line; a screen reader hears the reason once. */
const isHot = st => worthOf(st).hot >= WORTH.hotLabel;
const FLAME = '<svg class="flame" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill-rule="evenodd" d="M12.2 1.5c.9 3.1 3.2 4.9 4.9 7.2 1.4 1.9 2.2 3.9 2.2 6a7.3 7.3 0 0 1-14.6 0c0-2.9 1.6-5 3.3-6.7.1 1.9.8 3.2 2.1 3.7-.5-3.7.5-7.2 2.1-10.2zM12 21.2a3.1 3.1 0 0 0 3.1-3.1c0-1.6-.9-2.7-2-3.9-.3 1-.9 1.6-1.6 1.8.1-1.3-.2-2.4-.8-3.4-1.3 1.4-1.9 2.9-1.9 4.5A3.1 3.1 0 0 0 12 21.2z"/></svg>';
function titleHTML(st, text) {
  if (!isHot(st)) return esc(text);
  const why = DISCUSSED.has(worthOf(st).metric) ? 'Đang bàn nhiều' : 'Đang được chú ý';
  const m = /^(\S+)([\s\S]*)$/.exec(String(text));
  return `<span class="sr">${why}: </span><span class="flame-lead">${FLAME}${esc(m ? m[1] : text)}</span>${esc(m ? m[2] : '')}`;
}
const reasonTag = st => {
  const r = reasonOf(st);
  return r ? `<span class="why-tag${r.editor ? ' is-editor' : ''}"${r.why ? ` title="${esc(r.why)}"` : ''}><span class="sr">Vì sao có mặt: </span>${esc(r.text)}</span>` : '';
};

/* A ranked row's facts, each kept whole; the dot between two is drawn by CSS and is clipped when a fact starts a
   line, so a wrap never leaves "·" hanging at either end. */
const whyParts = parts => parts.map(p => `<span class="why-part">${p}</span>`).join('<span class="sr">, </span>');

/* The pipeline sometimes leaves one event as two stories (two outlets, two headlines). In the five-story block that
   reads as a repeat, so a story whose headline shares most of its words with one already picked is skipped there.
   It stays in the feed below. */
const STOP = new Set(('the and for with from that this its are was has have will into over after about says said than '
  + 'then what when your their they them how why who now new via').split(' '));
const WORDS = new Map();
const titleWords = t => String(t || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
  .split(/[^a-z0-9]+/).filter(x => x.length >= 3 && !STOP.has(x));
const wordsOf = st => {
  if (!WORDS.has(st.id)) WORDS.set(st.id, new Set(titleWords(st.title)));
  return WORDS.get(st.id);
};
function sameEvent(a, b) {
  const A = wordsOf(a), B = wordsOf(b);
  if (!A.size || !B.size) return false;
  let k = 0;
  A.forEach(x => { if (B.has(x)) k++; });
  return k / (A.size + B.size - k) >= WORTH.sameEvent;
}

const rankTime = st => ms(st.latest_coverage_at || st.published_at);
const byWorth = (a, b) => (Number.isFinite(b.importance_weight) ? b.importance_weight : worthOf(b).score)
  - (Number.isFinite(a.importance_weight) ? a.importance_weight : worthOf(a).score)
  || rankTime(b) - rankTime(a);
const byNew = (a, b) => rankTime(b) - rankTime(a);
const pinFirst = (a, b) => (PICKS.has(b.id) ? 1 : 0) - (PICKS.has(a.id) ? 1 : 0);
/* Every list on the page goes through here: editor picks first, then the reader's chosen order. */
const ordered = list => [...list].sort((a, b) => pinFirst(a, b) || (sortMode === 'new' ? byNew : byWorth)(a, b));


/* One event, told once on the first screen (owner, 10/10 21:01): the top row skips any story that is the same event as
   one shown in "Vừa đăng", and its lead and cards are different events among themselves (the higher-ranked one stays;
   the next eligible story fills the place). Same event, strongest signal first:
     1. the pipeline's own identity: the same story id, or one listed in the other's `aliases` (merged clusters);
     2. a shared address: any article or discussion URL that both stories' coverage carries;
     3. the cluster's own wording: at least four of the newer headline's words, and 60% of the shorter word set, appear
        across every headline the other story's coverage carries (each outlet titles one event differently, so one
        title against one title misses it: "Rogue Anthropic AI agent gave police fake tip…" shares 0.20 with
        TechCrunch's title but 0.70 with that cluster's coverage); the block's own title check (sameEvent) also counts. */
const urlsOf = st => new Set([st.url, ...(st.coverage || []).flatMap(c => [c && c.url, c && c.discussion_url])].filter(Boolean));
const coverageWords = st => new Set([st.title, ...(st.coverage || []).map(c => c && c.title)].flatMap(titleWords));
function oneEvent(a, b) {
  if (a.id === b.id || asArray(a.aliases).includes(b.id) || asArray(b.aliases).includes(a.id)) return true;
  const ua = urlsOf(a);
  for (const u of urlsOf(b)) if (ua.has(u)) return true;
  const A = coverageWords(a), B = coverageWords(b);
  let k = 0;
  A.forEach(x => { if (B.has(x)) k++; });
  if (k >= 4 && k / Math.min(A.size, B.size) >= 0.6) return true;
  return sameEvent(a, b);
}

/* ==========================================================================
   THE IMAGE SEAM. Every story picture comes from pickImage(st).
   Returns {src, via, kind}: kind 'photo' (an editorial picture: text may sit on it), 'graphic' (a generated card such
   as GitHub's social preview: text goes below it), or 'cover' (no published picture; drawn from data, see coverFor).
   Screened stories use story.image or a factual cover. IMAGE_PROVIDERS serve unscreened archives only.
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
  } else if (!st.image_screened) {
    for (const p of IMAGE_PROVIDERS) { r = p(st); if (r) break; }
  }
  if (!r) r = coverPick(st);
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
  const name = srcName(c0.source) || pub || hostOf(st.url) || 'Halcyon';
  const b = BRAND[pub] || { h: monoHue(name), c: 0.07, l: 0.40 };
  const m = measureOf(st), n = nSrc(st);
  let num = null, word;
  if (m) { num = fmt(m.value); word = `${m.word}${m.where ? ` trên ${m.where}` : ''}`; }
  else if (n > 1) { num = String(n); word = 'nguồn cùng đưa tin'; }
  else word = KIND[st.kind] || 'Bài viết';
  return { face: faceOfStory(st, SRC), name, num, word, glyph: monogram(name), h: b.h, c: b.c, l: b.l ?? 0.42 };
}
const coverStyle = cv => `--cv-l:${cv.l};--cv-c:${cv.c};--cv-h:${cv.h}`;
const miniCover = st => { const cv = coverFor(st); return `<span class="cover is-mini" style="${coverStyle(cv)}" aria-hidden="true"><span class="cover-glyph">${esc(cv.glyph)}</span></span>`; };

/* ---------- calendar: the bento home's targets, the same split control ---------- */
const eventOf = st => asArray(D && D.events).find(e => e.url === st.url || e.title === st.title) || null;
const eventCal = e => ({ uid: e.id, title: String(e.title), url: e.url, location: e.location, timezone: e.timezone,
  startDate: e.start_date, endDate: e.end_date,
  startAt: e.time_precision === 'exact' ? e.start_at : null, endAt: e.time_precision === 'exact' ? e.end_at : null,
  note: verifiedNote(e.verified_at, e.source_url) });
function calOf(st) {
  if (!st) return null;
  const e = eventOf(st);
  if (e) return eventCal(e);
  const c = (st.coverage || []).find(c => c.status === 'upcoming' && c.start_at && c.time_precision !== 'relative');
  return c ? { uid: c.id, title: c.title, url: c.url, startAt: c.start_at, endAt: null, note: c.source ? `Buổi phát trực tiếp của ${srcName(c.source)}` : '' } : null;
}
const liveCal = v => v && v.status === 'upcoming' && v.start_at && v.time_precision !== 'relative'
  ? { uid: v.video_id, title: v.title, url: v.url, startAt: v.start_at, endAt: null, note: v.channel ? `Buổi phát trực tiếp của ${v.channel}` : '' } : null;
function calButtons(cal, attr, label) {
  if (!cal || !canCalendar(cal)) return '';
  return `<span class="calbtn" role="group" aria-label="Thêm ${esc(label)} vào lịch">
    <a class="calbtn-g" href="${esc(gcalURL(cal))}" target="_blank" rel="noopener" aria-label="Thêm vào Google Calendar">${icon('i-cal')}<span>Google<span class="calbtn-long"> Calendar</span></span></a>
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
    e ? `<p class="dt-ev">${esc(eventWhen(e))}${e.verified_at ? ` · xác minh ${esc(e.verified_at)}` : ''}</p>` : '',
    st.time_basis === 'repository_created' ? '<p class="dt-ev">Ngày ghi là ngày tạo kho mã, không phải ngày phát hành.</p>' : '',
  ].join('');
  const artifacts = (st.related_artifacts || []).filter(a => a && a.url && a.title);
  const related = artifacts.length ? `<p class="dt-h">Tài nguyên liên quan</p><ul class="dt-src">${artifacts.map(a =>
    `<li><a class="cov-t" href="${esc(safe(a.url))}" target="_blank" rel="noopener">${esc(a.title)}</a></li>`).join('')}</ul>` : '';
  return `${facts}${related}<p class="dt-h">Các nguồn, theo thời gian</p><ul class="dt-src">${covs.map(c => {
    const ct = typeof c.title_vi === 'string' && c.title_vi.trim() ? c.title_vi.trim() : String(c.title || '');
    const mx = metricsHTML(c);
    return `<li><span class="cov-src">${esc(covName(c) || hostOf(c.url))}${c.published_at ? ` · ${timeEl(c.published_at)}` : ''}</span>
      <a class="cov-t" href="${esc(safe(c.url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}"${langAttr(ct)}>${esc(ct)}</a>
      ${mx || c.discussion_url ? `<span class="cov-m">${mx}${mx && c.discussion_url ? ' · ' : ''}${c.discussion_url ? `<a href="${esc(safe(c.discussion_url))}" target="_blank" rel="noopener" data-read="${esc(st.id)}">Thảo luận</a>` : ''}</span>` : ''}</li>`;
  }).join('')}</ul>`;
}
/* ---------- story modal (the captain's approval 06/10 04:50: one way to see detail) ---------- */
let currentModalStoryId = null;
let lastScrollY = 0;
let lastFocusedEl = null;

function syncModalSaveState() {
  if (!currentModalStoryId) return;
  const isSaved = savedHas(currentModalStoryId);
  const btns = [document.getElementById('story-modal-save'), document.getElementById('story-act-save')];
  btns.forEach(b => {
    if (b) {
      b.classList.toggle('is-saved', isSaved);
      b.setAttribute('aria-label', isSaved ? 'Bỏ lưu bài viết' : 'Lưu bài viết');
      b.title = isSaved ? 'Bỏ lưu' : 'Lưu đọc sau (phím S)';
    }
  });
}

function openStoryModal(id, opts = {}) {
  const story = STORY_ANY.get(id);
  if (!story) {
    toast('Tin này không còn trong bản tin hiện tại');
    return;
  }
  const dialog = document.getElementById('story-dialog');
  const body = document.getElementById('story-dialog-body');
  const scroller = document.getElementById('story-dialog-scroller');
  if (!dialog || !body) return;

  currentModalStoryId = id;
  lastScrollY = window.scrollY;
  lastFocusedEl = document.activeElement;

  body.innerHTML = renderStoryHTML(story, SRC, {
    isModal: true,
    isSaved: savedHas(id)
  });

  syncModalSaveState();

  if (scroller) scroller.scrollTop = 0;

  $('#top')?.setAttribute('aria-hidden', 'true');
  $('#bar')?.setAttribute('aria-hidden', 'true');

  if (!dialog.open) {
    dialog.showModal();
  }

  const closeBtn = document.getElementById('story-modal-close');
  if (closeBtn) {
    closeBtn.focus({ preventScroll: true });
  }

  markRead(id);

  if (opts.pushHistory !== false && !opts.fromHistory) {
    const targetUrl = `tin/${encodeURIComponent(id)}/`;
    history.pushState({ storyModal: id, scrollY: lastScrollY }, '', targetUrl);
  }
}

function closeStoryModal(opts = {}) {
  const dialog = document.getElementById('story-dialog');
  if (!dialog || !dialog.open) return;

  dialog.close();
  $('#top')?.removeAttribute('aria-hidden');
  $('#bar')?.removeAttribute('aria-hidden');

  const prevScroll = lastScrollY;
  const prevFocus = lastFocusedEl;
  currentModalStoryId = null;

  if (!opts.fromHistory) {
    if (history.state && history.state.storyModal) {
      history.back();
    } else {
      const cleanUrl = location.pathname.replace(/\/tin\/[^/]+\/?$/, '/') || './';
      history.replaceState(null, '', cleanUrl);
    }
  }

  if (Number.isFinite(prevScroll)) {
    window.scrollTo({ top: prevScroll, behavior: 'instant' });
  }

  if (prevFocus && typeof prevFocus.focus === 'function') {
    prevFocus.focus({ preventScroll: true });
  }
}

function toggleDetail(btn, open) {
  const st = STORY_ANY.get(btn.dataset.cov);
  if (!st) return;
  openStoryModal(btn.dataset.cov);
}

/* ---------- tile: live and upcoming ---------- */
/* Old snapshots without timezone keep their Vietnam fallback. New curated rows
   require IANA zones; each boundary uses its own date's offset, including DST. */
function eventSpan(e) {
  const exact = e.time_precision === 'exact';
  const timezone = e.timezone ?? TZ;
  const start = exact && e.start_at ? Date.parse(e.start_at) : dateStart(e.start_date, timezone);
  let end = exact && e.end_at ? Date.parse(e.end_at) : NaN;
  if (!Number.isFinite(end)) end = dateStart(nextDay(e.end_date || e.start_date), timezone);
  return { start, end };
}
function eventWhen(e) {
  const range = eventRange(e.start_date, e.end_date);
  if (e.time_precision !== 'exact' || !e.start_at) {
    return [range, e.location, 'chưa rõ giờ khai mạc'].filter(Boolean).join(' · ');
  }
  const timezone = e.timezone ?? TZ, start = new Date(e.start_at);
  const localTime = new Intl.DateTimeFormat('vi-VN', { timeZone: timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(start);
  const place = String(e.location || timezone).split(',')[0].trim();
  // Include the Vietnam date if conversion crosses a calendar day.
  const vnDate = dayKey(start);
  const vn = `${hhmm(start)}${vnDate !== e.start_date ? ` ngày ${eventRange(vnDate, vnDate)}` : ''} giờ Việt Nam`;
  return `${range} · ${localTime} giờ ${place}${timezone !== TZ ? ` (${vn})` : ''}`;
}
function countdownParts(start, end, now) {
  if (!Number.isFinite(start)) return null;
  if (Number.isFinite(end) && now >= end) return { state: 'over' };
  if (now >= start) return { state: 'on' };
  const t = Math.floor((start - now) / 1000);
  return { state: 'soon', d: Math.floor(t / 86400), h: Math.floor(t % 86400 / 3600), m: Math.floor(t % 3600 / 60), s: t % 60 };
}
const pad2 = n => String(n).padStart(2, '0');
// Words, to the minute: what a screen reader hears, and what the line shows when motion is reduced.
function countdownWords(p, num = x => x) {
  if (p.d) return `${num(p.d)} ngày${p.h ? ` ${num(p.h)} giờ` : ''}`;
  if (p.h) return `${num(p.h)} giờ${p.m ? ` ${num(p.m)} phút` : ''}`;
  return p.m ? `${num(p.m)} phút` : 'dưới 1 phút';
}
const countdownSR = p => p.state === 'on' ? 'Đang diễn ra' : p.state === 'over' ? 'Đã kết thúc' : `Còn ${countdownWords(p)}`;
// The face: days in words, then a clock of hours, minutes and seconds in tabular figures, so nothing jitters.
function countdownFace(p, seconds) {
  if (p.state === 'on') return '<span class="cd-dot" aria-hidden="true"></span>Đang diễn ra';
  if (p.state === 'over') return 'Đã kết thúc';
  if (!seconds) return `còn ${countdownWords(p, x => `<b class="num">${x}</b>`)}`;
  return `còn ${p.d ? `<b class="num">${p.d}</b> ngày ` : ''}<b class="num cd-clock">${pad2(p.h)}:${pad2(p.m)}:${pad2(p.s)}</b>`;
}
function countdownHTML(e) {
  const { start, end } = eventSpan(e);
  const p = countdownParts(start, end, Date.now());
  if (!p) return '';
  return `<span class="event-left cd is-${p.state}" data-cd="${start}" data-cd-end="${end}"><span class="sr">${countdownSR(p)}</span><span class="cd-face" aria-hidden="true">${countdownFace(p, !RM.matches)}</span></span>`;
}
/* One timer for every countdown on the page: each second (each minute when motion is reduced), only while the page
   is visible and a countdown is on it. */
let cdTimer = 0;
function tickCountdowns() {
  const now = Date.now(), seconds = !RM.matches;
  for (const el of document.querySelectorAll('.cd[data-cd]')) {
    const p = countdownParts(Number(el.dataset.cd), Number(el.dataset.cdEnd), now);
    if (!p) continue;
    const face = countdownFace(p, seconds), sr = countdownSR(p);
    if (el.lastElementChild.dataset.f !== face) { el.lastElementChild.innerHTML = face; el.lastElementChild.dataset.f = face; }
    if (el.firstElementChild.textContent !== sr) el.firstElementChild.textContent = sr;
    el.className = `event-left cd is-${p.state}`;
  }
}
function scheduleCountdown() {
  clearTimeout(cdTimer);
  cdTimer = 0;
  if (document.hidden || !document.querySelector('.cd[data-cd]')) return;
  tickCountdowns();
  const step = RM.matches ? 60000 : 1000;
  cdTimer = setTimeout(scheduleCountdown, step - (Date.now() % step) + 15);
}
/* The home shows the nearest events on a shelf, a row that scrolls sideways, so a few more cost no height; past
   six it links to the "Sắp diễn ra" view, which lists them all as rows. */
const HOME_EVENTS = 6;
const SHELF_LABEL = 'Sự kiện sắp diễn ra, trượt ngang để xem thêm';
const chevron = next => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="${next ? 'M9 5l7 7-7 7' : 'M15 5l-7 7 7 7'}"/></svg>`;
function renderLive(all = false) {
  const items = D.live || [];
  const it = items.find(x => x.status === 'live') || items.find(x => x.status === 'upcoming') || items[0];
  const now = Date.now();
  const upcoming = (D.events || []).filter(e => eventSpan(e).end > now)
    .sort((a, b) => eventSpan(a).start - eventSpan(b).start);
  const events = all ? upcoming : upcoming.slice(0, HOME_EVENTS);
  const shelf = !all && events.length > 1;
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
    video = `<div class="live-video"><a class="tile-video" href="${esc(safe(it.url))}" target="_blank" rel="noopener" aria-label="${esc(S.action)}: ${esc(it.title)}">
      ${thumb ? `<img src="${esc(thumb)}" alt="" width="480" height="360" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ''}
      <span class="video-badge${S.live ? ' is-live' : ''}">${esc(S.badge)}</span>
      <span class="video-play">${icon('i-play')}</span>
    </a>
    <div class="video-text"><p class="video-title"${langAttr(it.title)}>${esc(it.title)}</p>
    <p class="video-meta">${esc(it.channel || '')}${where}</p>
    <a class="tile-action${S.live ? ' is-live' : ''}" href="${esc(safe(it.url))}" target="_blank" rel="noopener">${icon('i-play')}${esc(S.action)}</a>
    ${it.status === 'upcoming' ? calButtons(liveCal(it), `data-cal-live="${esc(it.video_id || '')}"`, it.title) : ''}</div></div>`;
  }
  const evStory = e => asArray(D.stories).find(s => s.url === e.url || s.title === e.title);
  const more = upcoming.length - events.length;
  const moreHTML = more > 0 ? `<a class="tile-more" href="#sap-toi"><span>Xem cả <span class="num">${upcoming.length}</span> sự kiện</span></a>` : '';
  // Previous/next, shown by initShelves only when the shelf is wider than its box and the pointer is a mouse.
  const navHTML = shelf ? `<span class="shelf-nav" hidden>
    <button type="button" class="shelf-btn" data-shelf="-1" aria-controls="live-shelf" aria-label="Sự kiện trước">${chevron(false)}</button>
    <button type="button" class="shelf-btn" data-shelf="1" aria-controls="live-shelf" aria-label="Sự kiện tiếp theo">${chevron(true)}</button></span>` : '';
  const tools = moreHTML || navHTML ? `<span class="tile-tools">${moreHTML}${navHTML}</span>` : '';
  const evHTML = events.length ? `<div class="live-events"${shelf ? ` role="region" aria-label="${SHELF_LABEL}"` : ''}>${it ? `<div class="tile-subhead"><h3 class="tile-sub">Sắp diễn ra</h3>${tools}</div>` : ''}
    <ul class="events${!all ? ' shelf' : ''}"${shelf ? ' id="live-shelf"' : ''} data-n="${events.length}">${events.map(e => {
      const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(e.start_date || '');
      const st = evStory(e);
      const cal = eventCal(e);
      const left = countdownHTML(e);
      // Only the parts that exist, so a missing place never leaves a stray "·".
      const when = esc(eventWhen(e));
      return `<li${st ? ` data-sid="${esc(st.id)}" class="${statusClass(st)}"` : ''}><div class="ev"><a class="event" href="${esc(safe(e.url))}" target="_blank" rel="noopener"${st ? ` data-read="${esc(st.id)}"` : ''}>
        <span class="date-badge" aria-hidden="true">${d ? `<span class="date-m">thg ${+d[2]}</span><b class="num">${+d[3]}</b>` : ''}</span>
        <span class="event-text">${left}<span class="event-name"${langAttr(e.title)}>${st ? markHTML(st) : ''}${esc(e.title)}</span>
        <span class="event-when">${when}</span></span></a>
        ${calButtons(cal, st ? `data-cal="${esc(st.id)}"` : `data-cal-ev="${esc(e.id)}"`, e.title)}</div></li>`;
    }).join('')}</ul></div>` : '';
  return `<section class="tile tile-live${it ? ' has-video' : ''}" aria-labelledby="live-h">
    <div class="tile-head"><h2 class="tile-title" id="live-h">${esc(head)}</h2>${it ? '<span class="tile-note">phát sóng</span>' : tools}</div>
    <div class="live-body">${video}${evHTML}</div></section>`;
}
/* The shelf's arrows exist only when there is something to scroll to; at either end that arrow reads as unavailable
   (aria-disabled, so a focused button keeps its focus). */
let shelfRO = null;
function shelfState(ul) {
  const nav = ul && ul.closest('.tile') && ul.closest('.tile').querySelector('.shelf-nav');
  if (!nav) return;
  const max = ul.scrollWidth - ul.clientWidth, x = Math.abs(ul.scrollLeft);
  nav.hidden = max <= 1;
  const [prev, next] = nav.querySelectorAll('.shelf-btn');
  prev.setAttribute('aria-disabled', String(x <= 1));
  next.setAttribute('aria-disabled', String(x >= max - 1));
}
function initShelves(root) {
  if (shelfRO) shelfRO.disconnect();
  shelfRO = null;
  const shelves = [...root.querySelectorAll('.shelf[id]')];
  if (!shelves.length) return;
  if ('ResizeObserver' in window) shelfRO = new ResizeObserver(es => es.forEach(en => shelfState(en.target.closest('.events'))));
  for (const ul of shelves) {
    if (!ul._shelf) {             // the home's two shelves are set up together, so a redraw of one meets the other again
      ul._shelf = true;
      ul.addEventListener('scroll', () => shelfState(ul), { passive: true });
      // Tab onto a card that only peeks: bring the whole card in (the snap would otherwise hold the row where it was).
      ul.addEventListener('focusin', e => {
        const li = e.target.closest('.shelf > li');
        if (li) li.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: RM.matches ? 'auto' : 'smooth' });
      });
    }
    if (shelfRO) { shelfRO.observe(ul); if (ul.firstElementChild) shelfRO.observe(ul.firstElementChild); }
    shelfState(ul);
  }
}
/* One press moves by as many whole cards as fit, so the card that was peeking lands at the start. */
function scrollShelf(btn) {
  if (btn.getAttribute('aria-disabled') === 'true') return;
  const ul = document.getElementById(btn.getAttribute('aria-controls'));
  const card = ul && ul.firstElementChild;
  if (!card) return;
  const gap = parseFloat(getComputedStyle(ul).columnGap) || 0;
  const step = card.getBoundingClientRect().width + gap;
  const per = Math.max(1, Math.floor((ul.clientWidth + gap) / step));
  ul.scrollBy({ left: Number(btn.dataset.shelf) * per * step, behavior: RM.matches ? 'auto' : 'smooth' });
}

/* ---------- the front page's next event, beside the calendar ----------
   Owner, 09/11: "Đưa sự kiện sắp diễn ra lên phần đầu trang, đặt nó ở vị trí phù hợp." The calendar card says what day
   it is; the cell to its left says what is coming: a stream that is on or about to start, then the nearest verified
   event with its countdown, its calendar export and its source. Every event, and a past stream's replay, are in
   "Sắp diễn ra" (#sap-toi), which the dock's "Sự kiện" opens. Nothing coming: no card, and a story takes the cell. */
const upcomingEvents = () => asArray(D && D.events).filter(e => eventSpan(e).end > Date.now())
  .sort((a, b) => eventSpan(a).start - eventSpan(b).start);
const nextStream = () => { const v = asArray(D && D.live); return v.find(x => x.status === 'live') || v.find(x => x.status === 'upcoming') || null; };
/* The dates as a calendar would print them: the days large, the month and year under them. */
function evDateHTML(e) {
  const p = s => /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
  const a = p(e.start_date), b = p(e.end_date) || a;
  if (!a) return '';
  const days = b[0] === a[0] ? `${+a[3]}` : b[2] === a[2] && b[1] === a[1] ? `${+a[3]}–${+b[3]}` : `${+a[3]}/${+a[2]}–${+b[3]}/${+b[2]}`;
  const under = b[2] === a[2] && b[1] === a[1] ? `Tháng ${+a[2]} · ${a[1]}` : a[1] === b[1] ? a[1] : `${a[1]}–${b[1]}`;
  return `<span class="ev-date" aria-hidden="true"><b class="num">${days}</b><span>${under}</span></span>`;
}
function renderNext() {
  const it = nextStream(), events = upcomingEvents(), e = events[0];
  if (!it && !e) return '';
  const live = !!it && it.status === 'live';
  const all = events.length > 1 ? '<a class="ev-all" href="#sap-toi">Xem tất cả</a>' : '';
  const stream = it ? `<a class="ev-stream" href="${esc(safe(it.url))}" target="_blank" rel="noopener">
      <span class="ev-stream-k${live ? ' is-live' : ''}">${live ? '<span class="cd-dot" aria-hidden="true"></span>Trực tiếp' : esc(scheduleText(it.time_text))}${live && it.channel ? ` · ${esc(it.channel)}` : ''}</span>
      <span class="ev-stream-t"${langAttr(it.title)}>${esc(it.title)}</span></a>
    ${!e && !live ? calButtons(liveCal(it), `data-cal-live="${esc(it.video_id || '')}"`, it.title) : ''}` : '';
  let event = '';
  if (e) {
    const st = asArray(D.stories).find(s => s.url === e.url || s.title === e.title);
    const range = eventRange(e.start_date, e.end_date), when = eventWhen(e);
    const rest = when.startsWith(range) ? when.slice(range.length).replace(/^ · /, '') : when;
    event = `<div class="ev-next${st ? ` ${statusClass(st)}` : ''}"${st ? ` data-sid="${esc(st.id)}"` : ''}>
      <a class="ev-link" href="${esc(safe(e.url))}" target="_blank" rel="noopener"${st ? ` data-read="${esc(st.id)}"` : ''}>${evDateHTML(e)}<span class="sr">${esc(range)}: </span>
        <span class="ev-name"${langAttr(e.title)}>${st ? markHTML(st) : ''}${esc(e.title)}</span>${rest ? `<span class="ev-when">${esc(rest)}</span>` : ''}</a>
      <div class="ev-foot">${countdownHTML(e)}${calButtons(eventCal(e), st ? `data-cal="${esc(st.id)}"` : `data-cal-ev="${esc(e.id)}"`, e.title)}</div></div>`;
  }
  return `<section class="msn-card msn-ev" id="su-kien" aria-labelledby="ev-h">
    <div class="ev-head"><h2 id="ev-h">${live ? 'Đang phát' : 'Sắp diễn ra'}</h2>${all}</div>${stream}${event}</section>`;
}
/* "Sắp diễn ra" with nothing coming and no story to show: one calm line where the list would be. */
const eventsEmptyHTML = () => '<p class="msn-card ev-empty" role="status">Chưa có sự kiện nào sắp diễn ra.</p>';

/* ---------- tile: hot, and why ---------- */
function whyHTML(st) {
  const m = measureOf(st), n = nSrc(st), parts = [];
  if (m) parts.push(`${numB(m)} ${esc(m.word)}${m.where ? ` trên ${esc(m.where)}` : ''}`);
  if (m && m.speed) parts.push(`tăng <b class="num">${nf1.format(m.speed)}</b> mỗi giờ`);
  if (n > 1) parts.push(`<b class="num">${n}</b> nguồn cùng đưa`);
  if (!parts.length) parts.push(esc(ago(st.published_at)));
  return whyParts(parts);
}
function renderHot(list = HOT) {
  if (!list.length) return '';
  return `<section class="tile tile-hot" aria-labelledby="hot-h">
    <div class="tile-head"><h2 class="tile-title" id="hot-h">Đang nóng</h2></div>
    <ol class="hot-list">${list.map((st, i) => {
      const img = pickImage(st), t = titleOf(st);
      return `<li><a class="hot-row ${statusClass(st)}" href="tin/${esc(st.id)}/" data-sid="${esc(st.id)}" data-read="${esc(st.id)}" data-status="${storyStatus(st.id, st)}">
        <span class="thumb" data-id="${esc(st.id)}">${img.src ? `${mediaBackdrop(img.src)}<img src="${esc(img.src)}" alt="" width="144" height="144" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : miniCover(st)}</span>
        <span class="hot-rank num" aria-hidden="true">${i + 1}</span>
        <span class="hot-text"><span class="hot-title"${langAttr(t.text)}>${markHTML(st)}${titleHTML(st, t.text)}</span><span class="hot-why">${translationMark(t)}${whyHTML(st)}</span></span></a></li>`;
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
  { id: 'video', label: 'Video và hình ảnh' }, { id: 'agent-code', label: 'Tác tử lập trình' }, { id: 'agents', label: 'Tác tử tự động' },
  { id: 'browser-mcp', label: 'Trình duyệt, MCP' }, { id: 'quant', label: 'Giao dịch, tài chính' }, { id: 'local', label: 'Chạy mô hình trên máy' },
  { id: 'fine-tune', label: 'Tinh chỉnh mô hình' }, { id: 'rag', label: 'Dữ liệu cho RAG' }, { id: 'voice', label: 'Giọng nói, âm thanh' },
  { id: 'robotics', label: 'Người máy, AI thể nghiệm' }, { id: 'evaluation', label: 'Đánh giá mô hình' }, { id: 'translation', label: 'Dịch thuật' },
];
const AREA_FIELDS = {
  'video': ['video', 'images', 'animation'],
  'agent-code': ['coding'],
  'agents': ['agents'],
  'browser-mcp': ['mcp'],
  'quant': ['trading'],
  'local': ['local-models'],
  'fine-tune': ['training'],
  'rag': ['rag', 'ocr'],
  'voice': ['audio', 'music'],
  'robotics': ['robotics'],
  'evaluation': ['evaluation'],
  'translation': ['translation'],
};
function repoAreas(r) {
  if (!r) return [];
  const set = new Set(asArray(r.areas));
  if (r.category) set.add(r.category);
  return Array.from(set);
}
function repoMatchesArea(r) {
  if (!areas.size) return true;
  const a = repoAreas(r);
  for (const id of areas) {
    if (a.includes(id)) return true;
  }
  return false;
}
function areaPool(areaId) {
  if (!FIELD_DATA || !FIELD_MAP.size) return [];
  const fieldIds = AREA_FIELDS[areaId] || [areaId];
  const seen = new Set();
  const list = [];
  let hasRanked = false;

  for (const fid of fieldIds) {
    const f = FIELD_MAP.get(fid);
    if (!f) continue;
    // The pipeline marks a field "ready", "partial" or "stale" (radar/field_rankings.py), never "ranked": the ranked rows
    // themselves say whether the field was measured.
    const isRanked = Array.isArray(f.ranked) && f.ranked.length > 0;
    const pool = isRanked ? f.ranked : asArray(f.tracking);
    if (isRanked) hasRanked = true;
    for (const r of pool) {
      const name = r.full_name || r.id;
      if (!name || seen.has(name)) continue;
      seen.add(name);
      list.push({
        id: r.id || r.repository_id || name,
        full_name: r.full_name || name,
        url: r.url,
        description: r.description || '',
        description_vi: r.description_vi || '',
        stars: r.stars,
        stars_net_7d: r.stars_net_7d,
        field_id: fid,
        is_ranked: isRanked && Number.isFinite(r.stars_net_7d),
      });
    }
  }

  if (hasRanked) {
    list.sort((a, b) => {
      const aR = a.is_ranked ? 1 : 0, bR = b.is_ranked ? 1 : 0;
      if (aR !== bR) return bR - aR;
      if (a.is_ranked) return (b.stars_net_7d || 0) - (a.stars_net_7d || 0);
      return (b.stars || 0) - (a.stars || 0);
    });
  } else {
    list.sort((a, b) => (b.stars || 0) - (a.stars || 0));
  }
  return list;
}

function selectedAreasPool(areaSet) {
  if (!areaSet || !areaSet.size) return [];
  const seen = new Set();
  const list = [];
  let hasRanked = false;

  for (const aid of areaSet) {
    const p = areaPool(aid);
    for (const r of p) {
      if (!seen.has(r.full_name)) {
        seen.add(r.full_name);
        list.push(r);
        if (r.is_ranked) hasRanked = true;
      }
    }
  }

  if (hasRanked) {
    list.sort((a, b) => {
      const aR = a.is_ranked ? 1 : 0, bR = b.is_ranked ? 1 : 0;
      if (aR !== bR) return bR - aR;
      if (a.is_ranked) return (b.stars_net_7d || 0) - (a.stars_net_7d || 0);
      return (b.stars || 0) - (a.stars || 0);
    });
  } else {
    list.sort((a, b) => (b.stars || 0) - (a.stars || 0));
  }
  return list;
}







const REPO_PAGE_SIZE = 6;
const REPO_PAGE_DEFAULT = 4;
const repoPageSize = isArea => (isArea ? REPO_PAGE_SIZE : REPO_PAGE_DEFAULT);
let repoVisibleLimit = REPO_PAGE_DEFAULT;
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
const rankedList = (rk, view, second) => asArray(view === 'stars' ? rk[second] : (rk[view] || {})[second]).map(id => REPO.get(String(id))).filter(Boolean);
/* Only the lists, windows and totals the pipeline measured are offered: GitHub's daily or weekly trending page can fail
   (repos_meta.windows), and a selected default must never lead to an empty list. The reader's saved choice is kept in
   storage and comes back once its list has data again; until then the first measured one shows. */
function repoOptions() {
  const rk = rankings(); if (!rk) return null;
  const seconds = view => (view === 'stars' ? TOTALS : WINDOWS).filter(x => rankedList(rk, view, x.id).length);
  return { rk, views: REPO_VIEWS.filter(v => seconds(v.id).length), seconds };
}
function settleRepoChoice() {
  const o = repoOptions(); if (!o || !o.views.length) return o;
  if (!o.views.some(v => v.id === repoView)) repoView = o.views[0].id;
  const opts = o.seconds(repoView);
  if (repoView === 'stars') { if (!opts.some(x => x.id === repoTotal)) repoTotal = opts[0].id; }
  else if (!opts.some(x => x.id === repoWindow)) repoWindow = opts[0].id;
  return o;
}
function rankedRepos() {
  const o = settleRepoChoice(); if (!o) return null;
  return rankedList(o.rk, repoView, repoView === 'stars' ? repoTotal : repoWindow);
}

function repoMeasure(r) {
  if (repoView === 'stars') {
    const v = r[repoTotal];
    return Number.isFinite(v) ? `<b class="num">${fmt(v)}</b> ${esc(totalOf(repoTotal).unit)}` : `chưa đo được ${repoTotal === 'forks' ? 'lượt phân nhánh' : 'số sao'}`;
  }
  const g = r.stars_gained ? r.stars_gained[repoWindow] : null;
  return Number.isFinite(g) ? `<b class="num">+${fmt(g)}</b> ${esc(winOf(repoWindow).gained)}` : `chưa đo được số sao tăng ${esc(winOf(repoWindow).phrase)}`;
}

function formatRepoName(fullName) {
  const s = String(fullName || '');
  const slash = s.indexOf('/');
  if (slash > 0) {
    return `${esc(s.slice(0, slash))}/<wbr>${esc(s.slice(slash + 1))}`;
  }
  return esc(s);
}
function repoControls(full, inList) {
  const isArea = areas.size > 0 && FIELD_DATA && FIELD_MAP.size;
  const o = settleRepoChoice();
  const views = o ? o.views : REPO_VIEWS;
  const seconds = o ? o.seconds(repoView) : repoView === 'stars' ? TOTALS : WINDOWS;
  const second = repoView === 'stars'
    ? seconds.map(t => ({ kind: 'total', id: t.id, label: t.label, on: repoTotal === t.id }))
    : seconds.map(w => ({ kind: 'window', id: w.id, label: w.label, on: repoWindow === w.id }));
  // A switch with one position is not a choice: it is left out, and the measure under each card names its window.
  const viewSeg = views.length > 1 ? `<div class="seg" role="group" aria-label="Chọn danh sách kho mã">${views.map(v => `<button class="seg-b" data-repo-view="${v.id}" aria-pressed="${String(repoView === v.id)}">${esc(v.label)}</button>`).join('')}</div>` : '';
  const secondSeg = isArea || second.length < 2 ? '' : `<div class="seg seg-quiet" role="group" aria-label="${repoView === 'stars' ? 'Xếp theo tổng số sao hay lượt phân nhánh' : 'Chọn khung thời gian'}">${second.map(x => `<button class="seg-b" data-repo-${x.kind}="${x.id}" aria-pressed="${x.on}">${esc(x.label)}</button>`).join('')}</div>`;
  // Work areas are offered only once the field rankings arrived, and only those with repositories in them.
  const areaList = FIELD_DATA && FIELD_MAP.size ? AREAS.filter(a => areas.has(a.id) || areaPool(a.id).length) : [];
  return `${viewSeg || secondSeg ? `<div class="repo-ctl">${viewSeg}${secondSeg}</div>` : ''}
  ${areaList.length ? `<div class="area-chips" role="group" aria-label="Chọn mảng bạn quan tâm">${areaList.map(a => `<button class="area-chip" data-area="${a.id}" aria-pressed="${areas.has(a.id)}">${esc(a.label)}</button>`).join('')}</div>` : ''}
  ${isArea ? '<p class="tile-note repo-note"><button class="text-btn" data-area-clear>Hiện mọi mảng</button></p>' : ''}`;
}
function repoCard(r, measure) {
  const desc = r.description_vi || r.description || '';
  const key = `repo:${r.id || r.repository_id || r.full_name}`, on = savedHas(key);
  return `<div class="repo-cell${read.has(key) ? ' is-read' : ''}" data-sid="${esc(key)}"><a class="repo" href="${esc(safe(r.url))}" target="_blank" rel="noopener" data-read="${esc(key)}">
      <span class="repo-img"><img src="${esc(ghPreview(r))}" alt="" width="1200" height="600" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>
      <span class="repo-name" lang="en"><span class="st-mark">${read.has(key) ? MARK.seen : ''}</span>${formatRepoName(r.full_name)}</span>
      <span class="repo-desc"${langAttr(desc)}>${esc(desc)}</span>
      <span class="repo-meta">${LABEL[r.label] ? `<span class="label ${esc(r.label)}">${esc(LABEL[r.label])}</span>` : ''}<span>${measure}</span></span>
    </a><button class="act repo-save${on ? ' is-saved' : ''}" data-act="save" data-id="${esc(key)}" aria-pressed="${on}" aria-label="Lưu kho mã ${esc(r.full_name)}" title="Lưu">${icon('i-bookmark')}</button></div>`;
}
/* full: the "Mã và mô hình" view; otherwise the tile in the feed. */
function renderRepos(full = false) {
  const isArea = areas.size > 0 && FIELD_DATA && FIELD_MAP.size;
  const head = `<div class="tile-head"><h2 class="tile-title" id="repos-h">Kho mã đáng lấy</h2><span class="tile-note">thịnh hành trên GitHub</span></div>`;

  let matching = [];
  if (isArea) {
    matching = selectedAreasPool(areas);
  } else {
    const ranked = rankedRepos();
    if (ranked) {
      matching = ranked;
    } else {
      matching = asArray(D.repos).filter(r => r.source !== 'hf' && (r.label === 'dung-ngay' || r.label === 'xao-nau'));
    }
  }

  const pageSize = repoPageSize(isArea);
  const list = matching.slice(0, repoVisibleLimit);
  const remaining = matching.length - list.length;
  const why = isArea ? 'Không có kho mã nào ở mảng bạn chọn.' : 'Danh sách này chưa có kho mã nào.';
  return `<section class="tile tile-repos${full ? ' is-full' : ''}${isArea ? ' has-area' : ''}" aria-labelledby="repos-h">${head}
    ${repoControls(full, matching)}
    ${list.length ? `<div class="repo-row" id="repos-list">${list.map(r => {
      const measure = isArea
        ? (r.is_ranked ? `<b class="num">+${fmt(r.stars_net_7d)}</b> sao trong 7 ngày` : `<b class="num">${fmt(r.stars || 0)}</b> sao`)
        : repoMeasure(r);
      return repoCard(r, measure);
    }).join('')}</div>`
      : `<p class="tile-note repo-empty">${esc(why)}${areas.size ? ' <button class="text-btn" data-area-clear>Hiện mọi mảng</button>' : ''}</p>`}
    ${remaining > 0 ? `<div class="repo-more"><button class="repo-more-btn" data-repo-more="true" aria-controls="repos-list">Xem thêm kho mã</button></div>` : ''}
    <div class="sr" role="status" aria-live="polite" id="repo-status"></div>
  </section>`;
}
function showMoreRepos(moreBtn) {
  const isArea = areas.size > 0 && FIELD_DATA && FIELD_MAP.size;
  const pageSize = repoPageSize(isArea);
  let matching = [];
  if (isArea) {
    matching = selectedAreasPool(areas);
  } else {
    const ranked = rankedRepos();
    matching = ranked ? ranked : asArray(D.repos).filter(r => r.source !== 'hf' && (r.label === 'dung-ngay' || r.label === 'xao-nau'));
  }
  const total = matching.length;
  const start = repoVisibleLimit;
  const end = Math.min(start + pageSize, total);
  const nextSlice = matching.slice(start, end);
  if (!nextSlice.length) {
    const container = moreBtn.closest('.repo-more');
    if (container) container.remove();
    return;
  }
  repoVisibleLimit = end;

  const row = document.getElementById('repos-list') || document.querySelector('.tile-repos .repo-row');
  if (!row) { rerenderRepos(); return; }

  const tmp = document.createElement('div');
  tmp.innerHTML = nextSlice.map(r => {
    const measure = isArea
      ? (r.is_ranked ? `<b class="num">+${fmt(r.stars_net_7d)}</b> sao trong 7 ngày` : `<b class="num">${fmt(r.stars || 0)}</b> sao`)
      : repoMeasure(r);
    return repoCard(r, measure);
  }).join('');
  const newCells = [...tmp.children];
  newCells.forEach(cell => row.appendChild(cell));

  animateNewRepoCells(newCells);

  const remaining = total - repoVisibleLimit;
  const statusEl = document.getElementById('repo-status');
  if (statusEl) statusEl.textContent = 'Đã tải thêm kho mã.';

  if (remaining > 0) {
    moreBtn.focus();
  } else {
    const container = moreBtn.closest('.repo-more');
    if (container) container.remove();
    const firstLink = newCells[0] && newCells[0].querySelector('a.repo');
    if (firstLink) firstLink.focus({ preventScroll: true });
  }
}
function animateNewRepoCells(cells) {
  if (RM.matches || !cells.length) return;
  cells.forEach((cell, idx) => {
    cell.classList.add('motion-entry');
    const delay = Math.min(idx * 40, 200);
    cell.style.transitionDelay = `${delay}ms`;
    requestAnimationFrame(() => {
      cell.classList.add('is-entered');
    });
    setTimeout(() => {
      cell.classList.remove('motion-entry', 'is-entered');
      cell.classList.add('motion-done');
      cell.style.transitionDelay = '';
    }, delay + CARD_ENTER_MS + 40);
  });
}
function setRepo(kind, value) {
  repoVisibleLimit = repoPageSize(areas.size > 0);
  if (kind === 'view' && REPO_VIEWS.some(v => v.id === value)) {
    repoView = value;
    store.set(K.repoView, value);
    if (areas.size > 0) {
      areas.clear();
      store.set(K.areas, []);
    }
  }
  else if (kind === 'window' && WINDOWS.some(w => w.id === value)) { repoWindow = value; store.set(K.repoWindow, value); }
  else if (kind === 'total' && TOTALS.some(t => t.id === value)) { repoTotal = value; store.set(K.repoTotal, value); }
  else return;
  rerenderRepos();
}
/* ---------- Apple-like sliding tab indicator and smooth chip scroll ---------- */
function glideTab(container, activeBtn, { immediate = false } = {}) {
  if (!container || !activeBtn) return;
  const w = activeBtn.offsetWidth, hitHeight = activeBtn.offsetHeight;
  if (w === 0 && hitHeight === 0) return;
  // Header controls retain their hit area while the painted pill hugs the label.
  const inset = parseFloat(getComputedStyle(container).getPropertyValue('--tab-pill-inset')) || 0;
  const h = Math.max(0, hitHeight - inset * 2);

  let pill = container.querySelector(':scope > .tab-pill');
  if (!pill) {
    pill = document.createElement('span');
    pill.className = 'tab-pill';
    pill.setAttribute('aria-hidden', 'true');
    container.prepend(pill);
  }
  container.classList.add('has-pill');

  const x = activeBtn.offsetLeft, y = activeBtn.offsetTop + inset;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (immediate || reduced || !pill.classList.contains('is-active')) {
    pill.style.transition = 'none';
    pill.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    pill.style.width = `${w}px`;
    pill.style.height = `${h}px`;
    pill.classList.add('is-active');
    if (!reduced) {
      pill.getBoundingClientRect();
      pill.style.transition = '';
    }
    return;
  }

  pill.style.transition = '';
  pill.style.transform = `translate3d(${x}px, ${y}px, 0)`;
  pill.style.width = `${w}px`;
  pill.style.height = `${h}px`;
}

/* Which edge of the sideways-scrolling section tabs still hides tabs: trang-msn.css fades that edge. */
function markTabOverflow(el) {
  if (!el || !el.dataset) return;
  const max = el.scrollWidth - el.clientWidth, x = Math.abs(el.scrollLeft);
  const more = max <= 1 ? '' : x <= 1 ? 'end' : x >= max - 1 ? 'start' : 'both';
  if (el.dataset.more !== more) el.dataset.more = more;
}

function scrollChipIntoView(container, chip) {
  if (!container || !chip) return;
  const scroller = container.scrollWidth > container.clientWidth + 1
    ? container
    : (container.closest('.feed-navigation') || container);
  const maxScroll = scroller.scrollWidth - scroller.clientWidth;
  if (maxScroll <= 0) return;

  const cRect = scroller.getBoundingClientRect();
  const bRect = chip.getBoundingClientRect();
  const isPartlyOff = bRect.left < cRect.left + 12 || bRect.right > cRect.right - 32;
  if (!isPartlyOff) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const currentScroll = scroller.scrollLeft;
  const chipRelLeft = bRect.left - cRect.left + currentScroll;
  const targetScroll = Math.max(0, Math.min(maxScroll, chipRelLeft - (scroller.clientWidth - chip.offsetWidth) / 2));
  scroller.scrollTo({ left: targetScroll, behavior: reduced ? 'auto' : 'smooth' });
}

function flipRepoPill(container, oldBox, oldVal) {
  if (!container) return;
  const activeBtn = container.querySelector('.seg-b[aria-pressed="true"]');
  if (!activeBtn) return;

  const targetW = activeBtn.offsetWidth, targetH = activeBtn.offsetHeight;
  if (targetW === 0 && targetH === 0) return;
  const targetX = activeBtn.offsetLeft, targetY = activeBtn.offsetTop;

  let pill = container.querySelector(':scope > .tab-pill');
  if (!pill) {
    pill = document.createElement('span');
    pill.className = 'tab-pill';
    pill.setAttribute('aria-hidden', 'true');
    container.prepend(pill);
  }
  container.classList.add('has-pill');

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (reduced || !oldBox) {
    pill.style.transition = 'none';
    pill.style.transform = `translate3d(${targetX}px, ${targetY}px, 0)`;
    pill.style.width = `${targetW}px`;
    pill.style.height = `${targetH}px`;
    pill.classList.add('is-active');
    if (!reduced) {
      pill.getBoundingClientRect();
      pill.style.transition = '';
    }
    return;
  }

  const newBox = activeBtn.getBoundingClientRect();
  const dx = oldBox.left - newBox.left;
  const dy = oldBox.top - newBox.top;

  if (Math.abs(dx) < 1 && Math.abs(oldBox.width - targetW) < 1) {
    pill.style.transition = 'none';
    pill.style.transform = `translate3d(${targetX}px, ${targetY}px, 0)`;
    pill.style.width = `${targetW}px`;
    pill.style.height = `${targetH}px`;
    pill.classList.add('is-active');
    return;
  }

  activeBtn.style.transition = 'none';
  activeBtn.style.color = 'var(--color-ink-2)';
  if (oldVal) {
    const oldBtn = container.querySelector(`[data-repo-view="${CSSq(oldVal)}"],[data-repo-window="${CSSq(oldVal)}"],[data-repo-total="${CSSq(oldVal)}"]`);
    if (oldBtn) {
      oldBtn.style.transition = 'none';
      oldBtn.style.color = 'var(--color-ink)';
    }
  }

  // Invert: position pill at old location without animation
  pill.style.transition = 'none';
  pill.style.transform = `translate3d(${targetX + dx}px, ${targetY + dy}px, 0)`;
  pill.style.width = `${oldBox.width}px`;
  pill.style.height = `${targetH}px`;
  pill.classList.add('is-active');

  pill.getBoundingClientRect(); // force reflow of inverted state

  // Play: glide smoothly to target location
  requestAnimationFrame(() => {
    pill.style.transition = 'transform var(--motion-tab-glide, 280ms) var(--ease-flow), width var(--motion-tab-glide, 280ms) var(--ease-flow)';
    pill.style.transform = `translate3d(${targetX}px, ${targetY}px, 0)`;
    pill.style.width = `${targetW}px`;

    activeBtn.style.transition = 'color var(--motion-tab-glide, 280ms) var(--ease-flow)';
    activeBtn.style.color = '';
    if (oldVal) {
      const oldBtn = container.querySelector(`[data-repo-view="${CSSq(oldVal)}"],[data-repo-window="${CSSq(oldVal)}"],[data-repo-total="${CSSq(oldVal)}"]`);
      if (oldBtn) {
        oldBtn.style.transition = 'color var(--motion-tab-glide, 280ms) var(--ease-flow)';
        oldBtn.style.color = '';
      }
    }
  });
}

function initRepoPills(scope = document) {
  const tile = scope.querySelector('.tile-repos');
  if (!tile) return;
  const viewSeg = tile.querySelector('.seg:not(.seg-quiet)');
  if (viewSeg) {
    const active = viewSeg.querySelector('.seg-b[aria-pressed="true"]');
    if (active) glideTab(viewSeg, active, { immediate: true });
  }
  const winSeg = tile.querySelector('.seg.seg-quiet');
  if (winSeg) {
    const active = winSeg.querySelector('.seg-b[aria-pressed="true"]');
    if (active) glideTab(winSeg, active, { immediate: true });
  }
}

/* Redraw only the tile, and put focus back on the control the reader used. */
function rerenderRepos() {
  const old = $('.tile-repos'); if (!old) return;
  const oldViewSeg = old.querySelector('.seg:not(.seg-quiet)');
  const oldViewBtn = oldViewSeg ? oldViewSeg.querySelector('.seg-b[aria-pressed="true"]') : null;
  const oldViewPill = oldViewSeg ? oldViewSeg.querySelector('.tab-pill') : null;
  const oldViewBox = (oldViewPill && oldViewPill.classList.contains('is-active')) ? oldViewPill.getBoundingClientRect() : (oldViewBtn ? oldViewBtn.getBoundingClientRect() : null);
  const oldViewVal = oldViewBtn ? oldViewBtn.dataset.repoView : null;

  const oldWinSeg = old.querySelector('.seg.seg-quiet');
  const oldWinBtn = oldWinSeg ? oldWinSeg.querySelector('.seg-b[aria-pressed="true"]') : null;
  const oldWinPill = oldWinSeg ? oldWinSeg.querySelector('.tab-pill') : null;
  const oldWinBox = (oldWinPill && oldWinPill.classList.contains('is-active')) ? oldWinPill.getBoundingClientRect() : (oldWinBtn ? oldWinBtn.getBoundingClientRect() : null);
  const oldWinVal = oldWinBtn ? (oldWinBtn.dataset.repoWindow || oldWinBtn.dataset.repoTotal) : null;

  const a = document.activeElement;
  const attr = a && a.dataset ? ['area', 'repoView', 'repoWindow', 'repoTotal'].find(k => a.dataset[k] != null) : null;
  const value = attr ? a.dataset[attr] : null;
  const tmp = document.createElement('div');
  tmp.innerHTML = renderRepos(old.classList.contains('is-full'));
  const next = tmp.firstElementChild;
  if (next) old.replaceWith(next); else old.remove();

  if (next) {
    const nextViewSeg = next.querySelector('.seg:not(.seg-quiet)');
    if (nextViewSeg) flipRepoPill(nextViewSeg, oldViewBox, oldViewVal);
    const nextWinSeg = next.querySelector('.seg.seg-quiet');
    if (nextWinSeg) flipRepoPill(nextWinSeg, oldWinBox, oldWinVal);
    const repoCtl = next.querySelector('.repo-ctl');
    const activeSeg = repoCtl && repoCtl.querySelector('.seg-b[aria-pressed="true"]');
    if (repoCtl && activeSeg) scrollChipIntoView(repoCtl, activeSeg);
  }

  if (next && areas.size) {
    const chipContainer = next.querySelector('.area-chips');
    const activeChip = chipContainer && chipContainer.querySelector('.area-chip[aria-pressed="true"]');
    if (chipContainer && activeChip) scrollChipIntoView(chipContainer, activeChip);
  }

  if (attr && next) {
    const name = 'data-' + attr.replace(/[A-Z]/g, c => '-' + c.toLowerCase());
    const el = next.querySelector(`[${name}="${CSSq(value)}"]`);
    if (el) el.focus({ preventScroll: true });
  }
}
const MODEL_LIMIT = 8;
function getTrendingModels() {
  const sig = r => r.signals || {};
  const reposHf = (D.repos || []).filter(r => r.source === 'hf').map(r => ({
    full_name: r.full_name || r.name || r.id,
    url: r.url,
    likes: sig(r).likes ?? r.stars,
    downloads: sig(r).downloads,
    hf_score: sig(r).hf_score ?? r.hf_score ?? 0,
  }));
  const trendingHf = ((D.trending && D.trending.huggingface) || [])
    .filter(x => x.type === 'model' || !x.type)
    .map(x => ({
      full_name: x.id || x.name,
      url: x.url || `https://huggingface.co/${x.id}`,
      likes: x.likes,
      downloads: x.downloads,
      hf_score: x.likes ?? 0,
    }));
  const map = new Map();
  for (const m of [...reposHf, ...trendingHf]) {
    if (m.full_name && !map.has(m.full_name)) {
      map.set(m.full_name, m);
    }
  }
  return [...map.values()]
    .sort((a, b) => (b.hf_score ?? 0) - (a.hf_score ?? 0) || (b.likes ?? 0) - (a.likes ?? 0))
    .slice(0, MODEL_LIMIT);
}

function renderModels() {
  const models = getTrendingModels();
  if (!models.length) return '';
  return `<section class="tile tile-models" aria-labelledby="models-h">
    <div class="tile-head"><h2 class="tile-title" id="models-h">Mô hình đáng thử</h2></div>
    <p class="tile-note">thịnh hành trên Hugging Face</p>
    <div class="model-list">${models.map(r => {
      const likes = r.likes, dl = r.downloads;
      return `<a class="model" href="${esc(safe(r.url))}" target="_blank" rel="noopener">
        <span class="model-img"><img src="${esc(hfPreview(r))}" alt="" width="1200" height="648" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>
        <span class="model-name" lang="en">${formatRepoName(r.full_name)}</span>
        <span class="model-meta">${Number.isFinite(likes) ? `<span><b class="num">${fmt(likes)}</b> lượt thích</span>` : ''}${Number.isFinite(dl) ? `<span><b class="num">${fmt(dl)}</b> lượt tải</span>` : ''}</span>
      </a>`;
    }).join('')}</div></section>`;
}

/* ==========================================================================
   THE FRONT PAGE (Mẫu A, captain 08/11 18:23: "nói chung là em làm giống msn cho anh nhưng là nội dung về AI của
   halcyon"). One grid. Its first row: the lead carousel (the four strongest stories with a photograph), the weather,
   the calendar and "Chuyện lớn" (the next four). Then the stories in the reader's order, where a notable one takes a
   2x2 cell (a photograph and the editorial tier, or hot, or worth) or a 2x1 cell, at least four ordinary cards apart so
   they spread through the page ("phải có những thẻ tin tức đáng chú ý có kích thước lớn hơn"). The front page's own
   tiles (the Arena leaders, "Vừa đăng", "Đang nóng", live and upcoming, repositories, models) sit in the grid as 2x2
   widgets, the way MSN's sport and market cards do. Every story appears once on the page.
   ========================================================================== */
const C = (st, size = '', opts = {}) => ({ t: 'card', st, size, opts });
const storyHref = st => `tin/${esc(st.id)}/`;
const hasPhoto = st => { const p = pickImage(st); return !!p.src && p.kind === 'photo'; };
const TIER = { top: 3, notable: 2 };
const frontScore = st => (TIER[st.importance_tier] || 0) + (st.hot_score || 0) / 20 + Math.min(worthOf(st).score, 8) / 4;
const isBig = st => hasPhoto(st) && (st.importance_tier === 'top' || st.importance_tier === 'notable' || (st.hot_score || 0) >= 15 || worthOf(st).score >= 3);
const isWide = st => st.importance_tier === 'notable' || (st.hot_score || 0) >= 8 || worthOf(st).score >= 1;
let FRONT_TOP = [];           // "Chuyện lớn" in the first row
let FRONT_IDS = new Set();    // stories the front page already shows above the river (carousel, list, tiles)
let weatherCard = null, calendarCard = null;   // built once; the same elements return to the grid on every redraw

/* The carousel takes the editor's picks first, then the strongest stories with a photograph; "Chuyện lớn" the next
   four of the big ones. One event is told once. */
function chooseFront() {
  const ranked = [...allStories].sort((a, b) => pinFirst(a, b) || frontScore(b) - frontScore(a) || rankTime(b) - rankTime(a));
  const lead = [], top = [];
  const distinct = (list, st) => !list.some(o => oneEvent(o, st));
  for (const st of ranked) { if (lead.length >= 4) break; if (hasPhoto(st) && distinct(lead, st)) lead.push(st); }
  const big = ranked.filter(st => bigSet.has(st.id));
  for (const st of [...big, ...ranked]) { if (top.length >= 4) break; if (!top.includes(st) && distinct([...lead, ...top], st)) top.push(st); }
  return { lead, top };
}
/* Spread the notable cards: a big or wide card needs four ordinary cards since the last one. */
function sizeRiver(list) {
  let since = 4;
  return list.map(st => {
    let size = '';
    if (since >= 4 && isBig(st)) size = 'big';
    else if (since >= 4 && isWide(st)) size = 'wide';
    since = size ? 0 : since + 1;
    return C(st, size);
  });
}
const liveAvailable = () => !!(D && ((D.live || []).length || (D.events || []).some(e => eventSpan(e).end > Date.now())));

function buildAll() {
  const used = new Set([...PICKLIST, ...FRONT_TOP].map(st => st.id));
  const shownAbove = [...PICKLIST, ...FRONT_TOP];
  // The hot list: the stories people are discussing most, measured, one event told once.
  HOT = allStories.filter(st => !used.has(st.id) && (st.hot_score || 0) > 0 && hotEligible(st) && !shownAbove.some(p => sameEvent(p, st)))
    .sort(byWorth).slice(0, 5);
  HOT.forEach(st => used.add(st.id));
  FRONT_IDS = new Set(used);
  const fresh = D ? newestStories().list.slice(0, FRESH_TILE_ROWS) : [];
  fresh.forEach(st => used.add(st.id));
  const river = sizeRiver(ordered(allStories.filter(st => !used.has(st.id))));
  // The events are not a widget here: the next one sits beside the calendar (renderNext), the rest in "Sắp diễn ra".
  const widgets = [{ t: 'arena' }, fresh.length ? { t: 'fresh' } : null, HOT.length ? { t: 'hot' } : null,
    { t: 'repos' }, getTrendingModels().length ? { t: 'models' } : null].filter(Boolean);
  // The first widget after eight stories, then one every ten.
  const out = [];
  river.forEach((it, i) => { out.push(it); if ((i + 1) % 10 === 8 && widgets.length) out.push(widgets.shift()); });
  PLACED = new Set([...used, ...allStories.map(st => st.id)]);
  return out.concat(widgets, olderItems());
}

/* ---------- older days (captain, 09/11 13:16: scrolling replaces the sections) ----------
   When the ranked window runs out, the stream goes on into every other story the snapshot keeps, newest first, under a
   quiet line naming the day (Vietnam's calendar). Each story once: PLACED holds what the ranked part already shows.
   Each day has a grid of its own (placeChunk), so a story never slips above its day's line into a gap of the dense grid. */
let PLACED = new Set();
const WEEKDAY = new Intl.DateTimeFormat('vi-VN', { weekday: 'long', timeZone: TZ });
const pubTime = st => ms(st.published_at) || rankTime(st);
function dayLabel(key) {
  const days = Math.round((new Date(dayKey(new Date())) - new Date(key)) / 864e5);
  if (days <= 0) return 'Hôm nay';
  if (days === 1) return 'Hôm qua';
  const [, m, d] = key.split('-').map(Number);
  const name = WEEKDAY.format(new Date(key + 'T12:00:00+07:00'));
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${d}/${m}`;
}
function olderItems() {
  // Only from the complete snapshot, so the older days are built once, in one order (the window file may hold a few).
  if (!complete) return [];
  const rest = asArray(D && D.stories).filter(st => st && st.id && !PLACED.has(st.id)).sort((a, b) => pubTime(b) - pubTime(a));
  const out = [];
  let day = '';
  for (const st of rest) {
    PLACED.add(st.id);
    const k = dayKey(new Date(pubTime(st)));
    if (k !== day) { day = k; out.push({ t: 'day', key: k }); }
    out.push({ ...C(st), older: true });
  }
  return out;
}
const dayLineHTML = key => `<h2 class="day-line" id="day-${esc(key)}"><time datetime="${esc(key)}">${esc(dayLabel(key))}</time></h2>`;
/* The complete snapshot arrived under the same front page: its older days join the end of the stream. */
function appendOlder() {
  if (filter !== 'all' || !seq.length) return;
  const more = olderItems();
  if (!more.length) { updateMore(); return; }
  seq.push(...more);
  totalCards += more.filter(x => x.t === 'card').length;
  updateMore();
  requestAnimationFrame(() => { if (nearEnd()) loadMore(); });
}

/* ---------- the first row's cards ---------- */
const srcOf = st => { const t = titleOf(st), c = t.cov || covsOf(st)[0] || {}; return { name: covName(c) || hostOf(st.url), face: faceOfSource(c, SRC) }; };
/* Who and when; a machine-translated headline says so ("Translated") here on a slide, under the headline on a card. */
const metaHTML = (st, mark = false) => { const s = srcOf(st); return `<p class="nc-meta">${markHTML(st)}<span class="nc-fav" aria-hidden="true">${avatar(s.face, 'xs')}</span><span class="nc-src">${esc(s.name)}</span><span class="nc-dot" aria-hidden="true"></span>${timeEl(st.published_at)}${mark ? translationMark(titleOf(st)) : ''}</p>`; };
const aiBadgeHTML = img => img.via === 'ai' ? '<span class="ai-badge" title="Ảnh minh hoạ do AI tạo"><span class="sr">Loại ảnh: </span>Ảnh minh hoạ do AI tạo</span>' : '';
/* A news picture is drawn whole on a blurred copy of itself (captain, 07/11: "không bị cắt thông tin"), inside the slot
   Mẫu A gives it, so a chart or a screenshot keeps its edges. */
function mediaHTML(img, size) {
  const loading = size === 'lead' ? 'eager' : 'lazy';
  const [w, h] = size === 'lead' ? [1280, 720] : [640, 360];
  return `${mediaBackdrop(img.src, { loading })}<img class="media-img nc-img" src="${esc(img.src)}" alt="" width="${w}" height="${h}" loading="${loading}" decoding="async" referrerpolicy="no-referrer"${size === 'lead' ? ' fetchpriority="high"' : ''}>${aiBadgeHTML(img)}`;
}
function leadHTML(list) {
  if (!list.length) return '';
  const n = list.length;
  const slides = list.map((st, i) => {
    const img = pickImage(st), t = titleOf(st);
    return `<article class="slide${i ? '' : ' is-active'} ${statusClass(st)}" data-id="${esc(st.id)}" data-sid="${esc(st.id)}" data-status="${storyStatus(st.id, st)}" aria-roledescription="slide" aria-label="${i + 1} trên ${n}"${i ? ' inert' : ''}>
      <div class="slide-media media">${mediaHTML(img, i ? 'card' : 'lead')}</div>
      <div class="slide-box"><p class="nc-kicker">Tin nổi bật</p><h2 class="slide-title"${langAttr(t.text)}><a class="story-link" href="${storyHref(st)}" data-id="${esc(st.id)}">${esc(t.text)}</a></h2>${metaHTML(st, true)}</div></article>`;
  }).join('');
  const nav = n > 1 ? `<div class="lead-dots" role="group" aria-label="Chọn tin nổi bật">${list.map((st, i) => `<button type="button" data-slide="${i}" aria-label="Tin nổi bật ${i + 1}" aria-current="${i === 0}"></button>`).join('')}</div>` : '';
  return `<section class="msn-card msn-lead" id="lead" aria-roledescription="carousel" aria-label="Tin nổi bật">${slides}${nav}</section>`;
}
function showSlide(lead, n) {
  const slides = [...lead.querySelectorAll('.slide')];
  if (!slides.length) return;
  const k = (n + slides.length) % slides.length;
  slides.forEach((el, i) => { el.classList.toggle('is-active', i === k); el.inert = i !== k; });
  lead.querySelectorAll('.lead-dots button').forEach((b, i) => b.setAttribute('aria-current', String(i === k)));
  lead.dataset.slide = String(k);
}
/* With no prev/next buttons, a horizontal swipe on the card moves one story (left = next); a vertical one still scrolls. */
const SWIPE_MIN = 40;
let swipe = null;
function onLeadTouchStart(e) {
  const lead = e.touches.length === 1 && e.target instanceof Element && e.target.closest('.msn-lead');
  swipe = lead ? { lead, x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
}
function onLeadTouchEnd(e) {
  if (!swipe) return;
  const { lead, x, y } = swipe; swipe = null;
  const t = e.changedTouches[0], dx = t.clientX - x, dy = t.clientY - y;
  if (Math.abs(dx) >= SWIPE_MIN && Math.abs(dx) > Math.abs(dy)) showSlide(lead, (+lead.dataset.slide || 0) + (dx < 0 ? 1 : -1));
}
function topListHTML(list) {
  if (!list.length) return '';
  return `<section class="msn-card msn-toplist" id="top-list" aria-labelledby="top-list-h"><h2 id="top-list-h">Chuyện lớn</h2><ol>${list.map((st, i) => {
    const t = titleOf(st), s = srcOf(st);
    return `<li class="${statusClass(st)}" data-sid="${esc(st.id)}" data-status="${storyStatus(st.id, st)}"><b class="num" aria-hidden="true">${i + 1}</b><span class="top-text"><a class="story-link top-title" href="${storyHref(st)}" data-id="${esc(st.id)}"${langAttr(t.text)}>${esc(t.text)}</a><span class="top-meta">${markHTML(st)}<span class="top-who"><span class="top-src">${esc(s.name)}</span><span aria-hidden="true">·</span>${timeEl(st.published_at)}</span>${translationMark(t)}</span></span></li>`;
  }).join('')}</ol></section>`;
}

/* ---------- the story card: a picture over the source line and the headline; notable ones carry their dek ---------- */
function msnCard(st, size = '') {
  const img = pickImage(st), t = titleOf(st);
  const pic = !!img.src;
  const tid = `t-${esc(st.id)}`;
  const sumRaw = shown(st.summary, st.summary_vi);
  const sum = sumRaw && VI_RE.test(sumRaw) && sumRaw.trim() !== t.text.trim() ? sumRaw : '';
  const cls = ['msn-card', 'nc', size ? `nc-${size}` : '', pic ? 'has-photo' : 'no-photo', statusClass(st)].filter(Boolean).join(' ');
  return `<article class="${cls}" data-id="${esc(st.id)}" data-sid="${esc(st.id)}" data-status="${storyStatus(st.id, st)}" data-via="${esc(img.via)}">
  ${pic ? `<div class="nc-photo media">${mediaHTML(img, 'card')}</div>` : ''}
  <div class="nc-body">
    ${size ? '<p class="nc-kicker">Đáng chú ý</p>' : ''}
    ${metaHTML(st)}
    <h3 class="nc-title" id="${tid}"${langAttr(t.text)}><a class="story-link" href="${storyHref(st)}" data-id="${esc(st.id)}">${esc(t.text)}</a></h3>
    ${t.orig ? `<p class="nc-mt">${translationMark(t)}</p>` : ''}
    ${sum ? `<p class="nc-sum">${sourceDescriptionMark()}${esc(sum)}</p>` : ''}
  </div>
</article>`;
}

const FILTERS = {
  code: st => st.kind === 'repository' || st.kind === 'model',
};
/* "Sắp diễn ra", the one section left as a view of its own; its list comes from the snapshot's sections (the pipeline's
   choice), so it may reach outside the window. The other chapters of the bento home, and the section tabs, went when
   scrolling into older days replaced them (captain, 09/11 13:16): their old addresses land on the home feed. */
const SECTIONS = {
  'sap-toi': { sec: 'upcoming', label: 'Sắp diễn ra', order: 'date' },
};
const RETIRED_VIEWS = new Set(['hom-nay', 'model', 'paper', 'nghe', 'chuyen-gia', 'cong-dong', 'nong']);
const secOf = f => f.startsWith('sec:') ? SECTIONS[f.slice(4)] : null;
const savedStories = () => saved.slice().reverse().map(x => STORY_ANY.get(x.key)).filter(Boolean);
function listFor(f) {
  if (f === 'all') return allStories;
  if (f === 'saved') return savedStories();
  const s = secOf(f);
  if (s) return asArray(D.sections && D.sections[s.sec]).map(id => STORY_ANY.get(id)).filter(Boolean);
  return allStories.filter(FILTERS[f] || (() => false));
}
/* A section, a filter or the saved list (Mẫu A): every matching story once, as ordinary cards, without the front
   page's first row; the view's own tiles (the repositories and models, the events, saved links) lead or close it. */
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
    if (s.sec !== 'upcoming') return river.map(st => C(st));
    const lead = liveAvailable() ? { t: 'live', all: true } : river.length ? null : { t: 'ev-empty' };
    return [...(lead ? [lead] : []), ...river.map(st => C(st))];
  }
  // "Mã và mô hình" is the two lists only: a news story about a repository is told on the home stream, and here it stood
  // alone under the lists, one card in an otherwise empty row (owner, 09/11).
  if (f === 'code') return [{ t: 'repos-full' }, { t: 'models' }];
  return ordered(listFor(f)).map(st => C(st));
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

/* ---------- tile: the Arena leaders, woven into the front page; the full table is the "Xếp hạng" view ---------- */
let ARENA_DATA = null;
const arenaChange = r => r.change_status === 'unlisted' ? '<small>mới vào bảng</small>'
  : r.change_status !== 'compared' || !Number.isInteger(r.rank_change) ? '<small>chưa đủ dữ liệu</small>'
  : !r.rank_change ? '<small>giữ hạng</small>'
  : r.rank_change > 0 ? `<small class="up"><span aria-hidden="true">↑ </span>tăng <span class="num">${r.rank_change}</span></small>`
  : `<small><span aria-hidden="true">↓ </span>giảm <span class="num">${-r.rank_change}</span></small>`;
function arenaTileBody(data) {
  const rows = data && data.categories && Array.isArray(data.categories.overall) ? data.categories.overall.slice(0, 5) : [];
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec((data && data.published_at) || '');
  const head = `<div class="tile-head"><h2 class="tile-title" id="arena-tile-h">Mô hình dẫn đầu</h2><span class="tile-note">LMArena${date ? ` · <span class="num">${+date[3]}/${+date[2]}</span>` : ''}</span></div>`;
  if (!rows.length) return `${head}<p class="tile-note arena-tile-empty" role="status">${data === false ? 'Chưa tải được bảng xếp hạng.' : 'Đang tải bảng xếp hạng…'}</p>
    <div class="tile-foot"><button class="text-btn" type="button" data-filter-go="rankings">Mở bảng xếp hạng</button></div>`;
  return `${head}<ol class="arena-list">${rows.map(r => `<li class="arena-row"><span class="arena-rank num">${esc(r.rank)}</span>
      <span class="arena-name"><b lang="en">${esc(modelName(r.id))}</b><span>${esc(makerName(r.maker))}${Number.isFinite(r.vote_count) ? ` · <span class="num">${fmt(r.vote_count)}</span> lượt bình chọn` : ''}</span></span>
      <span class="arena-score num">${esc(scoreText(r.score))}${arenaChange(r)}</span></li>`).join('')}</ol>
    <div class="tile-foot"><span>Điểm theo bình chọn, bảng tổng</span><button class="text-btn" type="button" data-filter-go="rankings">Xem đủ 10 mô hình</button></div>`;
}
function renderArenaTile() {
  if (!ARENA_DATA) loadArena().then(d => { ARENA_DATA = d; }, () => { ARENA_DATA = false; }).then(() => {
    const el = $('#arena-tile'); if (el) el.innerHTML = arenaTileBody(ARENA_DATA);
  });
  return `<section class="tile tile-arena" id="arena-tile" aria-labelledby="arena-tile-h">${arenaTileBody(ARENA_DATA)}</section>`;
}

function renderItem(it) {
  if (it.t === 'card') return msnCard(it.st, it.size);
  if (it.t === 'live') return renderLive(!!it.all);
  if (it.t === 'hot') return renderHot();
  if (it.t === 'repos') return renderRepos();
  if (it.t === 'repos-full') return renderRepos(true);
  if (it.t === 'models') return renderModels();
  if (it.t === 'arena') return renderArenaTile();
  if (it.t === 'fresh') return freshTileHTML();
  if (it.t === 'saved-rest') return renderSavedRest();
  if (it.t === 'ev-empty') return eventsEmptyHTML();
  return '';
}

/* The next stories: the ranked part goes into the grid itself; the older days into a block at its end, one section per
   day (its line, then its own grid of cards). */
function renderChunk(limit) {
  let html = '';
  const days = [];
  while (pos < seq.length && shownCards < limit) {
    const it = seq[pos];
    if (it.t === 'day' || it.older) days.push(it); else html += renderItem(it);
    if (it.t === 'card') shownCards++;
    pos++;
  }
  return { html, days };
}
const lastDayGrid = grid => [...grid.querySelectorAll(':scope > .msn-days .msn-day-grid')].pop() || null;
function placeChunk(grid, { html, days = [] }) {
  if (html) grid.insertAdjacentHTML('beforeend', html);
  if (!days.length) return;
  let box = grid.querySelector(':scope > .msn-days');
  if (!box) { grid.insertAdjacentHTML('beforeend', '<div class="msn-days"></div>'); box = grid.lastElementChild; }
  let target = lastDayGrid(grid), cards = '';
  const flush = () => { if (cards && target) target.insertAdjacentHTML('beforeend', cards); cards = ''; };
  for (const it of days) {
    if (it.t !== 'day') { cards += renderItem(it); continue; }
    flush();
    box.insertAdjacentHTML('beforeend', `<section class="msn-day" aria-labelledby="day-${esc(it.key)}">${dayLineHTML(it.key)}<div class="msn-day-grid"></div></section>`);
    target = lastDayGrid(grid);
  }
  flush();
}

/* ---------- infinite scroll (Mẫu A: "cuộn để xuống dưới để tải tin") ----------
   A sentinel under the grid asks for the next batch 900 px before the reader reaches it. While a batch is built a row
   of grey cards breathes in its place and "Đang tải thêm tin" is read out. The front page's ranked part runs into the
   older days (olderItems); when nothing is left the stream just ends, with one quiet action under it (captain, 09/11:
   no closing card). */
let scrollWatch = null, loadingMore = false;
const nearEnd = () => { const el = $('#feed-sentinel'); return !!el && el.getBoundingClientRect().top < innerHeight + 900; };
const gridCols = grid => getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length || 1;
function setLoading(on) {
  const grid = $('#feed-grid');
  grid.querySelectorAll('.msn-sk').forEach(n => n.remove());
  $('#feed-status').innerHTML = on ? '<p class="loading-line"><span class="spinner" aria-hidden="true"></span>Đang tải thêm tin</p>' : '';
  const host = lastDayGrid(grid) || grid;
  if (on) host.insertAdjacentHTML('beforeend', Array.from({ length: gridCols(host) }, () => '<div class="msn-card msn-sk" aria-hidden="true"></div>').join(''));
}
function loadMore() {
  if (filter === 'all' && pos >= seq.length && D && !complete) { waitOlder(); return; }
  if (loadingMore || pos >= seq.length || filter === 'rankings' || $('#feed-grid').hidden) return;
  loadingMore = true;
  setLoading(true);
  const go = () => {
    setLoading(false);
    more(false);
    loadingMore = false;
    if (pos < seq.length) requestAnimationFrame(() => { if (nearEnd()) loadMore(); });
  };
  // The batch is built when the browser is idle, so the scroll that asked for it stays smooth.
  if ('requestIdleCallback' in window) requestIdleCallback(go, { timeout: 300 }); else setTimeout(go, 0);
}
function watchScroll() {
  if (scrollWatch) return;
  if (typeof IntersectionObserver === 'undefined') { scrollWatch = true; return; }
  scrollWatch = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) loadMore(); }, { rootMargin: '0px 0px 900px 0px' });
  scrollWatch.observe($('#feed-sentinel'));
}
/* The ranked part ran out before the complete snapshot (the older days) arrived: ask for it now, with the loading line.
   Without it (offline, a failed request) the stream ends here; a later poll that brings it continues the stream. */
let waitingOlder = false, olderUnavailable = false;
function waitOlder() {
  if (waitingOlder) return;
  waitingOlder = true;
  setLoading(true);
  loadComplete().then(() => {
    waitingOlder = false;
    setLoading(false);
    if (!complete) { olderUnavailable = true; updateMore(); }
  });
}
/* Under the last story, once nothing more can come: the one quiet action, "Đánh dấu đã xem hết". */
function updateMore() {
  const end = $('#feed-end');
  if (pos < seq.length) { end.hidden = true; if (scrollWatch === true) more(false); return; }
  const front = filter === 'all';
  if (front && D && !complete && !olderUnavailable) { end.hidden = true; waitOlder(); return; }
  end.hidden = !totalCards || filter === 'rankings' || filter === 'code';
  $('#mark-all-btn').textContent = front ? 'Đánh dấu đã xem hết' : 'Đánh dấu nhóm này đã xem';
}

/* The weather and the calendar keep one place at the start of the grid on every section, sort and redraw (captain,
   08/11 19:50: "cố định vị trí thẻ thời tiết và âm lịch"); trang-msn.css pins their cells. They are built once and the
   same elements go back after every redraw, so the city menu, the forecast page and the weather request survive a
   filter or sort change. */
const FIXED_SLOTS = '<i data-slot="wx"></i><i data-slot="cal"></i>';
function placeFixedCards(grid) {
  if (!weatherCard) weatherCard = createWeatherCard();
  if (!calendarCard) calendarCard = createCalendarCard();
  grid.querySelector('[data-slot="wx"]')?.replaceWith(weatherCard);
  grid.querySelector('[data-slot="cal"]')?.replaceWith(calendarCard);
}

function renderFeed() {
  const skeleton = $('#feed-skeleton');
  if (skeleton) skeleton.remove();
  const rankings = filter === 'rankings';
  const grid = $('#feed-grid');
  $('#arena').hidden = !rankings;
  grid.hidden = rankings;
  // "Mã và mô hình" is two lists with their own order controls, so the news order has nothing to sort there.
  const code = filter === 'code';
  $('#sort-switch').hidden = rankings || code || !D;
  $('#feed-status').innerHTML = '';
  if (rankings) {
    for (const id of ['feed-empty', 'filter-context']) $('#' + id).hidden = true;
    $('#top').removeAttribute('aria-busy');
    arenaView.show();
    renderChips();
    renderFrontMeta();
    return;
  }
  if (!D) { $('#feed-empty').hidden = false; renderChips(); return; }
  const front = filter === 'all';
  ({ lead: PICKLIST, top: FRONT_TOP } = front ? chooseFront() : { lead: [], top: [] });
  seq = front ? buildAll() : buildFiltered(filter);
  pos = 0; shownCards = 0;
  totalCards = seq.filter(x => x.t === 'card').length;
  const chunk = renderChunk(PAGE_FIRST);
  const empty = !chunk.html.trim() && !chunk.days.length;   // tiles with no data render nothing, so judge by the output
  $('#feed-empty').hidden = !empty;
  grid.classList.toggle('is-front', front);
  // The weather and the calendar are the home's furniture; a reader who opened "Mã và mô hình" came for repositories and
  // models (owner, 09/11: "QA các thành phần giao diện có nên hiển thị ở đó hay không"), so that view leaves them out.
  grid.innerHTML = (front ? leadHTML(PICKLIST) + FIXED_SLOTS + renderNext() + topListHTML(FRONT_TOP) : code ? '' : FIXED_SLOTS) + chunk.html;
  placeChunk(grid, { html: '', days: chunk.days });
  placeFixedCards(grid);
  renderSub();
  renderChips();
  renderFrontMeta();
  initRepoPills(grid);
  initShelves($('#top'));
  scheduleCountdown();
  $('#top').removeAttribute('aria-busy');
  hydrateHF(document);
  observeSkips();
  observeCardMotion(grid);
  hydrateLoadedImages(document);
  watchScroll();
  updateMore();
  requestAnimationFrame(() => { if (nearEnd()) loadMore(); });
}

function more(focus = true) {
  const grid = $('#feed-grid');
  const before = grid.querySelectorAll('.nc').length;
  placeChunk(grid, renderChunk(shownCards + PAGE_MORE));
  initRepoPills(grid);
  hydrateHF(document);
  observeSkips();
  observeCardMotion(grid);
  hydrateLoadedImages(grid);
  updateMore();
  // Keep keyboard users in place: focus the first card that just arrived.
  const next = grid.querySelectorAll('.nc')[before];
  if (focus && next) next.querySelector('.story-link').focus({ preventScroll: true });
}
/* Render further chunks until an element for a matching story exists (the first new story, #tin/<id>). */
function revealStory(pred, cardsOnly = false) {
  const sel = cardsOnly ? '#feed-grid .nc[data-sid], #feed-grid .slide[data-sid]' : '#feed-grid [data-sid]';
  const find = () => $$(sel).find(el => !el.closest('[hidden]') && pred(el.dataset.sid));
  let el = find();
  while (!el && pos < seq.length) { more(false); el = find(); }
  const lead = el && el.matches('.slide') && el.closest('.msn-lead');   // a carousel story: bring its slide forward
  if (lead) showSlide(lead, [...lead.querySelectorAll('.slide')].indexOf(el));
  return el || null;
}
function focusStory(el) {
  const card = el.closest('.msn-card, .tile');
  if (card && card.classList.contains('motion-entry')) {
    if (motionObserver) motionObserver.unobserve(card);
    card.style.transitionDelay = '0ms';
    card.classList.remove('motion-entry', 'is-entered');
    card.classList.add('motion-done');
  }
  window.scrollTo({ top: Math.max(0, scrollY + el.getBoundingClientRect().top - 16), behavior: RM.matches ? 'auto' : 'smooth' });
  const f = el.matches('a, button') ? el : el.querySelector('.story-link, a');
  if (f) f.focus({ preventScroll: true });
}

/* ---------- head, filters, new items ---------- */
let winH = 72, srcCount = 0;
const LABELS = {};
function renderSub() {
  // A view with a tab (the sections, "Đã lưu") needs no line: its tab is pressed and "Trang nhất" is the way back. A
  // section opened from a link (#sap-toi) has no tab, so it names itself and offers the way back.
  const sub = $('#filter-context');
  const s = secOf(filter);
  sub.hidden = !s;
  sub.innerHTML = s ? `<span class="filter-name">${esc(s.label)}</span><button class="text-btn" data-reset>Về dòng tin</button>` : '';
}
function renderChips() {
  $$('.filter-chip').forEach(b => {
    const f = b.dataset.filter;
    LABELS[f] = LABELS[f] || (b.querySelector('.chip-label') || b).textContent.trim();
    const n = !D ? 0 : f === 'all' ? allStories.length : f === 'saved' ? saved.length : f === 'rankings' ? 0 : listFor(f).length;
    // "Mã và mô hình" and "Xếp hạng" show lists, not stories: their tabs never depend on a story count.
    b.hidden = f !== 'all' && f !== 'rankings' && f !== 'code' && n === 0 && f !== filter;
    b.setAttribute('aria-pressed', String(f === filter));
  });
  const container = $('#feed-filters');
  const active = container ? container.querySelector('.filter-chip[aria-pressed="true"]') : null;
  if (container && active) glideTab(container, active);
  markTabOverflow(container);
  syncDock();
}
/* The phone dock (menu-cong-cu.js) marks "Sự kiện" while "Sắp diễn ra" is open and "Dòng tin" the rest of the time. */
function syncDock() {
  const dest = filter === 'sec:sap-toi' ? 'events' : 'feed';
  for (const a of $$('.mobile-nav-link[data-dest]')) {
    if (a.dataset.dest === dest) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
}
/* The view's name, for screen readers only: the pressed tab shows it on screen. No update time and no date (captain,
   09/11: the calendar card already carries today's date). */
function renderFrontMeta() {
  const h = $('#front-h');
  if (h) h.textContent = filter === 'all' ? 'Toàn cảnh AI hôm nay' : (LABELS[filter] || '');
}
/* Keep the Arena deep link when its tab is selected; news filters retain their existing URL behavior. */
function setFilter(f, fromHash = false) {
  if (!D && f !== 'rankings' && f !== 'all') return;
  filter = f;
  if (!fromHash) history.replaceState(null, '', location.pathname + location.search + (f === 'rankings' ? '#xep-hang' : ''));
  renderFeed();
  const top = $('#top').getBoundingClientRect().top;
  if (top < 0) window.scrollTo({ top: window.scrollY + top - 8 });
  const container = $('#feed-filters');
  const active = container ? container.querySelector(`.filter-chip[data-filter="${CSSq(f)}"]`) : null;
  if (container && active) scrollChipIntoView(container, active);
}
function renderSortSwitch() {
  $$('.sort-btn:not(.sort-btn-compact)').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.sort === sortMode)));
  const compact = $('.sort-btn-compact');
  if (compact) {
    const next = sortMode === 'worth' ? 'Mới nhất' : 'Đáng đọc nhất';
    compact.setAttribute('aria-label', `Đang sắp xếp: ${sortMode === 'worth' ? 'Đáng đọc nhất' : 'Mới nhất'}. Chuyển sang ${next}`);
    compact.setAttribute('aria-pressed', String(sortMode === 'new'));
    compact.querySelector('.sort-current').textContent = sortMode === 'worth' ? 'Đáng đọc' : 'Mới nhất';
  }
  $('#sort-switch').hidden = false;
  const container = $('#sort-switch');
  const active = container ? container.querySelector('.sort-btn[aria-pressed="true"]:not(.sort-btn-compact)') : null;
  if (container && active && matchMedia('(min-width: 768px)').matches) glideTab(container, active);
}
function setSort(m) {
  sortMode = m === 'new' ? 'new' : 'worth';
  store.set(K.sort, sortMode);
  renderSortSwitch();
  renderFeed();
}
const newCount = () => allStories.filter(st => storyStatus(st.id, st) === 'new').length;
/* One notice per batch. Dismissed IDs cannot be re-offered by an unchanged poll or a redraw. */
const RETURN_NEW_CAP = 20, NEW_NOTICE_MS = 12_000;
let returnNoticeChecked = false, noticeTimer = 0, noticeDeferred = false;
let noticeIds = new Set();
const offeredNewIds = new Set();
function positionNewItems() {
  document.documentElement.style.setProperty('--feed-bar-height', `${$('#bar').offsetHeight}px`);
  const box = $('#fresh');
  if (box.hidden) return;
  const barBottom = $('#bar').getBoundingClientRect().bottom;
  box.style.top = `${barBottom + 12}px`;
}
function dismissNewItems() {
  clearTimeout(noticeTimer);
  // Automatic dismissal must never remove the keyboard user's current control.
  if ($('#fresh').contains(document.activeElement)) { noticeDeferred = true; return; }
  $('#fresh').hidden = true;
  $('#fresh-announcement').textContent = '';
  noticeIds.clear();
  noticeDeferred = false;
}
function scheduleNewItemsDismissal() {
  clearTimeout(noticeTimer);
  if ($('#fresh').hidden || $('#fresh').contains(document.activeElement) || $('#fresh').matches(':hover')) return;
  if (noticeDeferred) { dismissNewItems(); return; }
  noticeTimer = setTimeout(dismissNewItems, NEW_NOTICE_MS);
}
function offerNewItems(ids) {
  const eligible = [...new Set(ids)].filter(id => !read.has(id) && !skipped.has(id)
    && (!offeredNewIds.has(id) || noticeIds.has(id)));
  if (!eligible.some(id => !offeredNewIds.has(id))) return;
  const wasVisible = !$('#fresh').hidden;
  noticeIds = new Set(eligible);
  eligible.forEach(id => offeredNewIds.add(id));
  $('#fresh-text').textContent = `${noticeIds.size} tin mới`;
  $('#fresh').hidden = false;
  noticeDeferred = false;
  positionNewItems();
  // Count changes within a visible notice are silent; a new appearance gets one announcement.
  if (!wasVisible) $('#fresh-announcement').textContent = `${noticeIds.size} tin mới. Nhấn U để tới tin mới đầu tiên.`;
  scheduleNewItemsDismissal();
}
function retireNewItem(id) {
  if (!noticeIds.delete(id)) return;
  if (!noticeIds.size) dismissNewItems();
  else $('#fresh-text').textContent = `${noticeIds.size} tin mới`;
}
function checkNewItemsScroll() {
  if ($('#fresh').hidden) return;
  positionNewItems();
  const edge = $('#bar').getBoundingClientRect().bottom;
  const elements = $$('#feed-grid [data-sid]');
  for (const id of noticeIds) {
    if (elements.some(el => el.dataset.sid === id && !el.closest('[hidden]') && el.getBoundingClientRect().bottom <= edge)) retireNewItem(id);
  }
}
function renderNewItems() {
  if (returnNoticeChecked) return;
  returnNoticeChecked = true;
  const ids = allStories.filter(st => storyStatus(st.id, st) === 'new').map(st => st.id);
  if (!firstVisit && ids.length <= RETURN_NEW_CAP && ids.length < allStories.length / 2) offerNewItems(ids);
}
/* "Vừa đăng" (renamed from "Mới nhất" on 10/10 21:01 so it no longer reads as the sort switch): the top of the home, directly under the header and above "Nhiều nguồn cùng đưa". A reader opening a news
   page wants the newest first (owner, 10/10 19:50: "người dùng vào đọc tin thì luôn muốn xem tin mới trước chứ"), so
   this row holds the stories published in the last NEWEST.hours, newest first; when fewer than NEWEST.min stories are
   that young it reaches back up to NEWEST.maxHours. The "N tin mới" pill brings the reader here: the batch it announced
   leads the row (newest first) with the usual new dot until each is opened. The row is a view; every story keeps its
   own place in the blocks below and in "Dòng tin", whose order is untouched. */
const NEWEST = { hours: 6, min: 4, maxHours: 24, cap: 8 };
let freshIds = [];            // the batch the reader asked to see with the pill, pinned first while unread
const FRESH_TILE_ROWS = 5;
function newestStories() {
  const young = h => allStories.filter(st => GEN - ms(st.published_at) <= h * 36e5 && !FRONT_IDS.has(st.id));
  let pool = young(NEWEST.hours), hours = NEWEST.hours;
  if (pool.length < NEWEST.min) { pool = young(NEWEST.maxHours); hours = NEWEST.maxHours; }
  const pinned = freshIds.filter(id => !read.has(id)).map(id => STORY_ANY.get(id)).filter(Boolean).sort(byNew);
  const rest = pool.slice().sort(byNew).filter(st => !pinned.includes(st));
  return { list: [...pinned, ...rest].slice(0, Math.max(NEWEST.cap, pinned.length)), hours };
}
/* "Vừa đăng" is a front-page tile (mockup B's "Tin nhanh"): the clock time each story was published, then its headline. */
function freshItem(st) {
  const t = titleOf(st);
  return `<li class="${statusClass(st)}" data-sid="${esc(st.id)}" data-status="${storyStatus(st.id, st)}"><a class="brief fresh-item" href="tin/${esc(st.id)}/" data-id="${esc(st.id)}" data-read="${esc(st.id)}">
    <time class="num" datetime="${esc(st.published_at)}" title="${esc(exact(st.published_at))}">${esc(hhmm(new Date(st.published_at)))}</time>
    <span class="brief-h"${langAttr(t.text)}>${markHTML(st)}${titleHTML(st, t.text)}${translationMark(t)}</span></a></li>`;
}
function freshInnerHTML() {
  const { list } = D && filter === 'all' ? newestStories() : { list: [] };
  if (!list.length) return '';
  // Five rows sit beside two cards (mockup B); a batch the "N tin mới" pill pinned is shown whole.
  const shown = list.slice(0, Math.max(FRESH_TILE_ROWS, freshIds.filter(id => !read.has(id)).length));
  return `<div class="tile-head"><h2 class="tile-title" id="fresh-row-h" tabindex="-1">Vừa đăng</h2></div>
    <ul class="briefs fresh-list" data-n="${shown.length}">${shown.map(freshItem).join('')}</ul>`;
}
function freshTileHTML() {
  const inner = freshInnerHTML();
  return inner ? `<section class="tile tile-fresh" id="fresh-row" aria-labelledby="fresh-row-h">${inner}</section>` : '';
}
/* Redraw the tile in place (the "N tin mới" pill pins its batch first). */
function renderFreshRow() {
  const box = $('#fresh-row');
  if (!box) return;
  const inner = freshInnerHTML();
  box.innerHTML = inner;
  box.hidden = !inner;
}
function goFirstNew() {
  if (!D) return;
  const targets = new Set(noticeIds);
  if (pending) {
    if (!targets.size) pendingNewIds(pending).forEach(id => targets.add(id));
    applyPending();
  }
  if (filter !== 'all') setFilter('all', true);
  let heading = null;
  if (targets.size) {
    freshIds = [...targets];
    renderFreshRow();
    // Every story once: when the river already shows a story the tile now pins, redraw so the river leaves it out.
    if ([...targets].some(id => $(`#feed-grid .nc[data-id="${CSSq(id)}"]`))) renderFeed();
    const box = $('#fresh-row');
    if (box && !box.hidden) heading = $('#fresh-row-h');
  }
  if (heading) {
    // Bring the tile to the top of the window (Mẫu A's panel head scrolls away), then hand keyboard and screen-reader
    // users its heading.
    const tile = $('#fresh-row');
    window.scrollTo({ top: Math.max(0, scrollY + tile.getBoundingClientRect().top - 16), behavior: RM.matches ? 'auto' : 'smooth' });
    heading.focus({ preventScroll: true });
    dismissNewItems();
    return;
  }
  const matches = id => { const st = STORY_ANY.get(id); return !!st && storyStatus(id, st) === 'new'; };
  const el = (targets.size && revealStory(id => targets.has(id) && matches(id))) || revealStory(matches);
  if (el) focusStory(el);
  else {
    if ($('#fresh').contains(document.activeElement)) $('#top').focus({ preventScroll: true });
    toast('Chưa có tin mới. Trang tự kiểm mỗi 3 phút');
  }
  dismissNewItems();
}
/* "Đánh dấu đã xem": the last look moves to this snapshot, so nothing here counts as new any more. */
function markSeen() {
  if (!D) return;
  const hadFocus = $('#fresh').contains(document.activeElement);
  store.set(K.lastSeen, D.generated_at);
  lastSeen = D.generated_at; firstVisit = false; arrived = new Set();
  new Set($$('[data-sid]').map(el => el.dataset.sid)).forEach(paintStatus);
  if (hadFocus) $('#top').focus({ preventScroll: true });
  freshIds = [];
  dismissNewItems();
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
function pendingNewIds(data) {
  const hours = Number(data.ranking && data.ranking.window_hours) || 72;
  const gen = ms(data.generated_at), from = gen - Math.max(1, hours) * 36e5;
  return asArray(data.stories).filter(st => !STORY_ANY.has(st.id) && !read.has(st.id) && !skipped.has(st.id)
    && ms(st.published_at) >= from && ms(st.published_at) <= Math.min(gen + 3e5, Date.now())).map(st => st.id);
}
async function pollSnapshot() {
  if (document.hidden || !D) return;
  try {
    const j = await loadData({ cache: 'no-cache' });
    // The window file holds every story the new snapshot's window can share with this one, so new stories are
    // judged correctly before the complete snapshot arrives; a poll that brings the same snapshot completes it.
    if (!complete && j && j.generated_at === D.generated_at) { adoptComplete(j); return; }
    if (!j || !j.generated_at || j.generated_at <= (pending || D).generated_at) return;
    pending = j;
    offerNewItems(pendingNewIds(j));
  } catch { /* a failed poll keeps the current snapshot; the next poll tries again */ }
}
function applyPending() {
  if (!pending) return;
  commitLastSeen();
  arrived = new Set(pendingNewIds(pending));
  const data = pending; pending = null;
  ingest(data);
  complete = true;              // a polled snapshot is always the complete one
  if (filter !== 'all') filter = 'all';
  renderAll();
  setTimeout(() => { arrived = new Set(); }, 3000);
}

/* ---------- no footer (captain, 09/11): the snapshot time stays on the grid as data for measurement scripts, never on screen ---------- */
function renderSources() {
  const el = $('#feed-grid');
  if (!el) return;
  el.dataset.generated = D.generated_at || '';
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
  revealStory(sid => sid === id, true);
  openStoryModal(id);
}
/* The search page's old addresses land here (tra-cuu.html forwards ?q=): the news bar's search opens with the query
   filled, and the address is cleaned so a reload or a shared link does not reopen it. */
function openSearchFromAddress() {
  const url = new URL(location.href);
  const q = url.searchParams.get('q');
  if (q == null && url.hash !== '#tim') return false;
  url.searchParams.delete('q');
  if (url.hash === '#tim') url.hash = '';
  history.replaceState(history.state, '', url.pathname + url.search + url.hash);
  if (newsSearch) newsSearch.open(q || '');
  return true;
}
function route() {
  if (location.hash === '#xep-hang') { setFilter('rankings', true); return; }
  if (location.hash === '#tim') { openSearchFromAddress(); return; }
  if (!D) return;
  const h = decodeURIComponent(location.hash.slice(1));
  if (!h || h === 'top') return;                 // the browser scrolls; a filter the reader chose stays
  if (h === 'moi') { goFirstNew(); return; }
  // A retired section's old link (#hom-nay, #nong...) opens the home feed, which now scrolls on through those stories.
  if (RETIRED_VIEWS.has(h)) { history.replaceState(history.state, '', location.pathname + location.search); if (filter !== 'all') setFilter('all'); return; }
  if (h === 'repo') { setFilter('code', true); return; }
  if (h === 'da-luu') { if (saved.length) setFilter('saved', true); return; }
  if (h === 'nguon') { location.replace('nguon.html'); return; }
  if (SECTIONS[h]) { setFilter('sec:' + h, true); return; }
  const m = /^tin\/(.+)$/.exec(h);
  if (m) openStory(m[1]);
}

/* A publisher that blocks hotlinking, a dead address or a picture too small to be one (under 40 px, a tracking pixel)
   never shows as a broken image: the card drops its picture slot and becomes a text card (Mẫu A); a carousel slide
   keeps its dark frame and shows its headline large. */
function dropPhoto(img) {
  const card = img.closest('.nc, .slide');
  if (!card) return;
  const st = STORY_ANY.get(card.dataset.id);
  if (st) { const cv = coverPick(st); PICKED.set(st.id, cv); card.dataset.via = cv.via; }
  card.classList.remove('has-photo');
  card.classList.add('no-photo');
  (img.closest('.nc-photo, .slide-media') || img).remove();
}
/* Failed pictures use the site's factual cover without consulting external providers. */
function watchPictures() {
  document.addEventListener('load', e => {
    const img = e.target;
    if (img instanceof HTMLImageElement && img.classList.contains('nc-img') && img.naturalWidth < 40) dropPhoto(img);
  }, true);
  document.addEventListener('error', e => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || img.classList.contains('av-img')) return;
    if (img.classList.contains('nc-img')) { dropPhoto(img); return; }
    const thumb = img.closest('.thumb');
    if (thumb) {
      const st = STORY_ANY.get(thumb.dataset.id);
      if (st && st.image_screened) PICKED.set(st.id, coverPick(st));
      thumb.innerHTML = st ? miniCover(st) : '';
      return;
    }
    if (img.closest('.tile-video, .repo-img, .model-img')) img.remove();
  }, true);
}

/* ---------- keyboard: the bento home's shortcuts ---------- */
const STORY_SEL = '#feed-grid .story-link, #feed-grid .hot-row, #feed-grid .repo';
const storyEls = () => $$(STORY_SEL).filter(el => el.getClientRects().length && !el.closest('[hidden], [inert]'));
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
  const dots = t && t.closest('.lead-dots');
  if (dots && (k === 'ArrowLeft' || k === 'ArrowRight')) {   // the lead's dots: arrows move the story and keep focus on its dot
    e.preventDefault();
    const lead = dots.closest('.msn-lead');
    showSlide(lead, (+lead.dataset.slide || 0) + (k === 'ArrowRight' ? 1 : -1));
    dots.querySelectorAll('button')[+lead.dataset.slide].focus();
    return;
  }

  if (currentModalStoryId) {
    if (k === 'Escape') {
      e.preventDefault();
      closeStoryModal();
      return;
    }
    if (k === 's' || k === 'S') {
      e.preventDefault();
      toggleSave(currentModalStoryId);
      syncModalSaveState();
      return;
    }
    return;
  }

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
  else if (k === 'u' || k === 'U') goFirstNew();
  else if (k === 'm' || k === 'M') { if (D && newCount()) markSeen(); }
  else if (k === 'g' || k === 'G') { scrollTo({ top: 0, behavior: RM.matches ? 'auto' : 'smooth' }); }
  else if (k === '/') { e.preventDefault(); if (newsSearch) newsSearch.open(); }
  else if (k === '?') { e.preventDefault(); $('#keys').showModal(); }
}

/* ---------- events ---------- */
function onClick(e) {
  const t = e.target instanceof Element ? e.target : null;
  if (!t) return;

  // Modal interactions
  if (t.closest('#story-modal-close')) {
    e.preventDefault();
    closeStoryModal();
    return;
  }
  if (t.closest('#story-modal-save, #story-act-save, [data-story-act="save"]')) {
    e.preventDefault();
    if (currentModalStoryId) {
      toggleSave(currentModalStoryId);
      syncModalSaveState();
    }
    return;
  }
  if (t.closest('#story-modal-share, #story-act-share, [data-story-act="share"]')) {
    e.preventDefault();
    if (currentModalStoryId) {
      const u = location.origin + (location.pathname.replace(/\/tin\/[^/]+\/?$/, '/') || '/') + 'tin/' + encodeURIComponent(currentModalStoryId) + '/';
      if (navigator.clipboard) {
        navigator.clipboard.writeText(u).then(() => toast('Đã chép liên kết bài viết'), () => toast(u));
      } else {
        toast(u);
      }
    }
    return;
  }
  if (t === document.getElementById('story-dialog')) {
    closeStoryModal();
    return;
  }

  // Intercept clicks on story links or cards to open modal
  const storyLink = t.closest('.story-link, .hot-row[data-sid], .pick-row[data-sid], .fresh-item[data-id]');
  if (storyLink && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
    const sid = storyLink.dataset.id || storyLink.dataset.sid || storyLink.closest('[data-sid]')?.dataset.sid;
    if (sid && STORY_ANY.has(sid)) {
      e.preventDefault();
      openStoryModal(sid);
      return;
    }
  }

  const act = t.closest('.act');
  if (act && act.dataset.act === 'copy') {
    const u = act.dataset.url;
    (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject(new Error())).then(() => toast('Đã chép liên kết'), () => toast(u));
    return;
  }
  if (act && act.dataset.act === 'save') { toggleSave(act.dataset.id); return; }
  const cov = t.closest('.cov-btn'); if (cov) { toggleDetail(cov); return; }
  const sb = t.closest('.shelf-btn'); if (sb) { scrollShelf(sb); return; }
  const cal = t.closest('[data-cal]'); if (cal) { e.preventDefault(); addToCalendar(calOf(STORY_ANY.get(cal.dataset.cal))); return; }
  const cl = t.closest('[data-cal-live]'); if (cl) { e.preventDefault(); addToCalendar(liveCal(asArray(D.live).find(v => v.video_id === cl.dataset.calLive))); return; }
  const ce = t.closest('[data-cal-ev]');
  if (ce) {
    e.preventDefault();
    const ev = asArray(D.events).find(x => String(x.id) === ce.dataset.calEv);
    if (ev) addToCalendar(eventCal(ev));
    return;
  }
  const area = t.closest('[data-area]');
  if (area) { const a = area.dataset.area; if (areas.has(a)) areas.delete(a); else areas.add(a); store.set(K.areas, [...areas]); repoVisibleLimit = repoPageSize(areas.size > 0); rerenderRepos(); return; }
  if (t.closest('[data-area-clear]')) { areas.clear(); store.set(K.areas, []); repoVisibleLimit = REPO_PAGE_DEFAULT; rerenderRepos(); return; }
  const rc = t.closest('button[data-repo-view],button[data-repo-window],button[data-repo-total]');
  if (rc) {
    const k = ['repoView', 'repoWindow', 'repoTotal'].find(k => rc.dataset[k] != null);
    if (k === 'repoView' && areas.size > 0) {
      areas.clear();
      store.set(K.areas, []);
    }
    repoVisibleLimit = repoPageSize(areas.size > 0);
    setRepo(k.slice(4).toLowerCase(), rc.dataset[k]);
    return;
  }
  const moreBtn = t.closest('[data-repo-more]');
  if (moreBtn) { showMoreRepos(moreBtn); return; }
  if (t.closest('#fresh-go')) { goFirstNew(); return; }
  if (t.closest('#keys-x')) { $('#keys').close(); return; }
  if (t.closest('[data-reset]')) { setFilter('all'); return; }
  if (t.closest('#mark-all-btn')) {
    if (!D) return;
    // The front page shows every story of the snapshot (the ranked part, then the older days).
    (filter === 'all' ? asArray(D.stories) : listFor(filter)).forEach(st => markRead(st.id));
    if (filter === 'all') markSeen();
    else toast('Đã đánh dấu nhóm này đã xem');
    return;
  }
  const dot = t.closest('.lead-dots button');
  if (dot) { showSlide(dot.closest('.msn-lead'), +dot.dataset.slide); return; }
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
  $('#feed-filters').addEventListener('scroll', e => markTabOverflow(e.currentTarget), { passive: true });
  if (document.fonts) document.fonts.ready.then(() => markTabOverflow($('#feed-filters')));
  // Tiles that lead to a view of their own ("Xem đủ 10 mô hình" opens "Xếp hạng").
  document.addEventListener('click', e => {
    const go = e.target instanceof Element && e.target.closest('[data-filter-go]');
    if (go) { setFilter(go.dataset.filterGo); $('#top').focus({ preventScroll: true }); }
  });
  newsSearch = createNewsSearch({
    root: $('#news-search'),
    getStories: () => allStories,
    onOpenStory: id => {
      if (!STORY_ANY.has(id)) return false;
      openStoryModal(id);
      return true;
    },
  });
  // "Tìm tin" beside the field (Mẫu A) runs the search on what is typed, or puts the cursor in the field.
  const go = $('#ns-go');
  if (go) go.addEventListener('click', () => newsSearch.open($('#ns-q').value));
  $('#sort-switch').addEventListener('click', e => {
    const b = e.target.closest('.sort-btn');
    if (!b) return;
    if (b.dataset.sort === 'toggle') setSort(sortMode === 'worth' ? 'new' : 'worth');
    else if (b.dataset.sort) setSort(b.dataset.sort);
  });
  $('#reset-filter-btn').addEventListener('click', () => setFilter('all'));
  const notice = $('#fresh');
  notice.addEventListener('mouseenter', () => clearTimeout(noticeTimer));
  notice.addEventListener('mouseleave', scheduleNewItemsDismissal);
  notice.addEventListener('focusin', () => clearTimeout(noticeTimer));
  notice.addEventListener('focusout', () => setTimeout(scheduleNewItemsDismissal, 0));
  window.addEventListener('scroll', checkNewItemsScroll, { passive: true });
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(positionNewItems).observe($('#bar'));
  $('#keys').addEventListener('click', e => { if (e.target === $('#keys')) $('#keys').close(); });
  window.addEventListener('resize', () => {
    positionNewItems();
    const filters = $('#feed-filters');
    if (filters) {
      const activeChip = filters.querySelector('.filter-chip[aria-pressed="true"]');
      if (activeChip) {
        glideTab(filters, activeChip, { immediate: true });
        scrollChipIntoView(filters, activeChip);
      }
      markTabOverflow(filters);
    }
    const sort = $('#sort-switch');
    if (sort) {
      const activeSort = sort.querySelector('.sort-btn[aria-pressed="true"]:not(.sort-btn-compact)');
      if (activeSort && matchMedia('(min-width: 768px)').matches) glideTab(sort, activeSort, { immediate: true });
    }
    initRepoPills();
  }, { passive: true });
  document.addEventListener('click', onClick);
  document.addEventListener('touchstart', onLeadTouchStart, { passive: true });
  document.addEventListener('touchend', onLeadTouchEnd, { passive: true });
  document.addEventListener('auxclick', e => { if (e.button === 1) onOpenLink(e); });
  document.addEventListener('keydown', onKey);

  const storyDialog = document.getElementById('story-dialog');
  if (storyDialog) {
    storyDialog.addEventListener('cancel', e => {
      e.preventDefault();
      closeStoryModal();
    });
  }
  window.addEventListener('popstate', e => {
    if (e.state && e.state.storyModal) {
      openStoryModal(e.state.storyModal, { pushHistory: false, fromHistory: true });
    } else if (currentModalStoryId) {
      closeStoryModal({ fromHistory: true });
    }
  });
}

/* ---------- one snapshot in: everything the page derives from it ---------- */
function ingest(data) {
  D = data;
  SRC = new Map(asArray(D.sources).map(s => [s.id, s]));
  winH = Number(D.ranking && D.ranking.window_hours);
  if (!Number.isFinite(winH) || winH <= 0) winH = 72;
  const gen = ms(D.generated_at), from = gen - winH * 36e5;
  GEN = gen || Date.now();
  allStories = asArray(D.stories).filter(st => { const t = rankTime(st); return t && t >= from && t <= gen + 3e5; })
    .sort(byNew);
  STORY = new Map(allStories.map(st => [st.id, st]));
  STORY_ANY = new Map(asArray(D.stories).map(st => [st.id, st]));
  REPO = new Map(asArray(D.repos).filter(r => r && r.id != null && r.full_name).map(r => [String(r.id), r]));
  srcCount = new Set(allStories.flatMap(st => (st.coverage || []).map(c => c.author_handle
    ? 'x' : srcName(c.source)))).size;
  WORTHS.clear(); PICKED.clear(); WORDS.clear();
  const hot = allStories.filter(st => st.hot_score > 0).sort((a, b) => b.hot_score - a.hot_score);
  const k = Math.max(3, Math.min(10, Math.round(allStories.length / 12)));
  bigSet = new Set(hot.slice(0, k).map(st => st.id));
  allStories.forEach(st => { if (nSrc(st) >= 3) bigSet.add(st.id); });
  matchPicks(RAW_PICKS);
  ({ lead: PICKLIST, top: FRONT_TOP } = chooseFront());
  // The bento home's rule: a first visit counts the last 24 hours as new; later visits count from the last look.
  const stored = store.get(K.lastSeen, null);
  firstVisit = !stored;
  lastSeen = stored || new Date((gen || Date.now()) - 864e5).toISOString();
}
function renderAll() {
  renderChips();
  renderSortSwitch();
  renderFeed();
  renderSources();
  renderNewItems();
  positionNewItems();
}

/* ---------- start ---------- */
const whenIdle = () => new Promise(r => {
  const go = () => 'requestIdleCallback' in window ? requestIdleCallback(() => r(), { timeout: 3000 }) : setTimeout(r, 1000);
  if (document.readyState === 'complete') go(); else addEventListener('load', go, { once: true });
});
function startLifecycle() {
  setInterval(pollSnapshot, SNAPSHOT_EVERY_MS);
  document.addEventListener('visibilitychange', () => { if (document.hidden) commitLastSeen(); else pollSnapshot(); });
  document.addEventListener('visibilitychange', scheduleCountdown);   // stops while hidden, catches up on return
  if (RM.addEventListener) RM.addEventListener('change', scheduleCountdown);
  addEventListener('pagehide', () => commitLastSeen());
  // The last look moves on engagement: five seconds on the page or the first scroll.
  let engaged = false;
  const onEngage = () => { if (!engaged) { engaged = true; commitLastSeen(); } };
  setTimeout(onEngage, 5000);
  addEventListener('scroll', onEngage, { passive: true, once: true });
  // Relative times stay honest while the tab is open; the source panel uses an absolute date.
  setInterval(() => { $$('[data-ago]').forEach(el => { el.textContent = ago(el.dataset.ago); }); }, 60_000);
  window.commitLastSeen = commitLastSeen; window.storyStatus = storyStatus;
  window.openStoryModal = openStoryModal; window.closeStoryModal = closeStoryModal; window.getStory = id => STORY_ANY.get(id);
}
async function startLiveLayer() {
  await whenIdle();
  try {
    const { startLive } = await import('./live.js');
    startLive({
      getStories: () => D.stories,
      priority: hnId => { const st = asArray(D.stories).find(s => (s.coverage || []).some(c => (c.discussion_url || '').endsWith('=' + hnId))); return st ? (st.hot_score || 0) : 0; },
      onUpdates: applyLive,
      onStatus: () => {},
    });
  } catch (e) { console.warn('live counters unavailable; the snapshot numbers stay', e); }
}
/* Field rankings add repositories the snapshot does not carry; every ingest rebuilds REPO from the snapshot. */
function mergeFieldRepos() {
  if (!FIELD_DATA || !Array.isArray(FIELD_DATA.fields)) return;
  for (const f of FIELD_DATA.fields) {
    for (const r of [...asArray(f.ranked), ...asArray(f.tracking)]) {
      const key = String(r.id || r.repository_id || r.full_name);
      if (!REPO.has(key)) REPO.set(key, r);
    }
  }
}
/* The complete snapshot, once, at low priority so it never competes with the first screen's pictures. */
function loadComplete() {
  if (complete || !D) return Promise.resolve();
  if (!completeLoad) {
    completeLoad = loadData({ priority: 'low' }).then(adoptComplete).catch(e => {
      console.warn('complete snapshot unavailable; the feed keeps the window stories and tries again on the next poll', e);
    }).finally(() => { completeLoad = null; });
  }
  return completeLoad;
}
/* The same snapshot as the window file draws the same feed, so the page stays as the reader sees it: only a view that
   reaches outside the window (a section, saved stories) is drawn again. A newer snapshot redraws everything; an older
   one (a deploy still spreading) is dropped and the next poll asks again. */
function adoptComplete(data) {
  if (complete || !data || !data.generated_at || data.generated_at < D.generated_at) return;
  const same = data.generated_at === D.generated_at;
  const keep = { lastSeen, firstVisit };
  ingest(data);
  mergeFieldRepos();
  ({ lastSeen, firstVisit } = keep);
  complete = true;
  if (!same) renderAll();
  else if (filter !== 'all' && filter !== 'rankings') renderFeed();
  else { renderChips(); appendOlder(); }
}
/* Addresses that name a section, the saved list or a story outside the window wait for the complete snapshot. */
function needsComplete(beforeData = false) {
  if (complete || (!D && !beforeData)) return false;
  let h = '';
  try { h = decodeURIComponent(location.hash.slice(1)); } catch { return false; }
  const m = /^tin\/(.+)$/.exec(h);
  return !!SECTIONS[h] || h === 'da-luu' || (!!m && (beforeData || !STORY_ANY.has(m[1])));
}
async function routeWhenReady() {
  if (needsComplete()) await loadComplete();
  route();
}
async function init() {
  const th = store.get(K.theme, null);
  if (th) document.documentElement.setAttribute('data-theme', th);
  $('#theme-btn').setAttribute('aria-pressed', String(th ? th === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches));
  watchImageErrors();
  watchPictures();
  watchImageLoad();
  attachEvents();
  openSearchFromAddress();
  arenaView = createArenaView($('#arena'));
  addEventListener('hashchange', routeWhenReady);
  route();
  try {
    const [, data, picks, fieldData] = await Promise.all([loadImages(), loadFirst(), loadPicks(), loadFieldRankings()]);
    RAW_PICKS = picks;
    FIELD_DATA = fieldData;
    if (FIELD_DATA && Array.isArray(FIELD_DATA.fields)) {
      FIELD_MAP = new Map(FIELD_DATA.fields.map(f => [f.id, f]));
    }
    ingest(data);
    mergeFieldRepos();
    sortMode = store.get(K.sort, store.get(LEGACY.sort, 'worth')) === 'new' ? 'new' : 'worth';
    for (const [k, s] of Object.entries(SECTIONS)) LABELS['sec:' + k] = s.label;
    renderAll();
  } catch (err) {
    console.error('feed load failed', err);
    $('#top').removeAttribute('aria-busy');
    const skeleton = $('#feed-skeleton');
    if (skeleton) skeleton.remove();
    // The news failed, not the weather or the date: those two cards stay in their place.
    $('#feed-grid').innerHTML = FIXED_SLOTS;
    placeFixedCards($('#feed-grid'));
    const em = $('#feed-empty');
    em.querySelector('h2').textContent = 'Chưa nạp được dòng tin';
    em.querySelector('p').textContent = 'Bạn kiểm tra kết nối mạng rồi thử lại nhé.';
    const b = $('#reset-filter-btn');
    b.textContent = 'Tải lại';
    b.addEventListener('click', () => location.reload());
    em.hidden = filter === 'rankings';
    return;
  }
  const reopen = history.state && history.state.storyModal;
  if (reopen && !STORY_ANY.has(reopen)) await loadComplete();
  if (reopen && STORY_ANY.has(reopen)) {
    openStoryModal(reopen, { pushHistory: false, fromHistory: true });
  } else {
    await routeWhenReady();
  }
  startLifecycle();
  startLiveLayer();
  whenIdle().then(loadComplete);
}

init();

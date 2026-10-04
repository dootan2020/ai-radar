/* ai·radar · Khám phá, flat round (04/10).
   Owner, 04/10 20:28: flat like the Edge start page and Google Discover. No borders, no accent bars, every card led by
   a picture. Pictures are only ones the source itself publishes (feed-images.json, written and verified by
   plans/nhap/fetch_images.py); a story without one gets a flat cover drawn from its own data.

   One function decides every story picture: pickImage(). It walks IMAGE_PROVIDERS in order and falls back to the
   cover. That list is the seam for a later round (AI-generated or stock images): add a provider before the cover.

   "Đáng đọc" round (owner, 04/10 21:35): what to read first. One score per story from measured signals only (WORTH,
   worthOf), a block of 3 to 5 stories on top with a reason line in real numbers, a reason chip per card, a sort switch,
   and "Biên tập chọn" only from editor-picks.json. */

import { esc, fmt, avatar, avatarStack, faceOfStory, faceOfSource, hydrateHF, monogram, watchImageErrors, ytIdOf } from './faces.js';
import { ago, dayKey, hhmm, TZ, streamedAge, scheduleText, daysLeftHTML, eventRange } from './time-text.js';
import { KIND, METRIC } from './words.js';
import { shown, uniqCoverage } from './titles.js';

const SOURCES = ['https://dootan2020.github.io/ai-radar/data/radar-ui.json', 'data/radar-ui.json', 'data/radar.json'];
const IMAGES_URL = 'feed-images.json';
const PICKS_URL = 'editor-picks.json';   // the owner's own picks; the only thing allowed to say "Biên tập chọn"
const K = { theme: 'air2:theme', read: 'airtl:read', saved: 'airtl:saved', visit: 'airtl:lastVisit', sort: 'airtl:sort' };
const PAGE_FIRST = 40, PAGE_MORE = 24;

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const safe = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
const icon = id => `<svg class="i" aria-hidden="true"><use href="#${id}"/></svg>`;
const nf1 = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 });
const EXACT = new Intl.DateTimeFormat('vi-VN', { dateStyle: 'full', timeStyle: 'short', timeZone: TZ });
const ms = iso => new Date(iso).getTime() || 0;
/* Vietnamese letters with diacritics: a text without any of them is English and is marked lang="en". */
const VI_RE = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;
const langAttr = text => VI_RE.test(text || '') ? '' : ' lang="en"';
/* Same formula as faces.js (not exported there), so a cover and its avatar share a tint. */
const monoHue = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: memory only */ } }
};

let D = null;
let SRC = new Map();
const IMG = {};               // verified picture per address: {src, via}
let allStories = [];
let STORY = new Map();
let bigSet = new Set();
let HOT = [];
let filter = 'all';
let sortMode = 'worth';       // 'worth' (Đáng đọc nhất) or 'new' (Mới nhất); the reader's choice is remembered
const PICKS = new Map();      // story id -> {note}, from editor-picks.json, in the file's order
let PICKLIST = [];            // the "Đáng đọc hôm nay" block: editor picks first, then the highest scores
let seq = [], pos = 0, shownCards = 0, totalCards = 0;
let lastVisit = null;
const readSet = new Set(store.get(K.read, []));
const savedSet = new Set(store.get(K.saved, []));

/* ---------- data ---------- */
async function fetchJSON(url, init = {}) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 10000);
  try {
    const r = await fetch(url, { signal: ctl.signal, credentials: 'omit', referrerPolicy: 'no-referrer', ...init });
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

async function loadData() {
  let lastErr;
  for (const url of SOURCES) {
    try {
      const j = await fetchJSON(url);
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
const srcName = id => String((SRC.get(id) || {}).name || id || '').replace(/\s*\(.*?\)\s*/g, ' ').trim();
const covsOf = st => uniqCoverage(st.coverage, srcName);
const nSrc = st => covsOf(st).length;
const timeEl = iso => `<time datetime="${esc(iso)}" title="${esc(EXACT.format(new Date(iso)))}">${esc(ago(iso))}</time>`;
const isNew = st => !!lastVisit && ms(st.published_at) > ms(lastVisit);

const PREFER = ['points', 'score', 'stars', 'upvotes', 'likes', 'trending_score', 'downloads', 'comments'];
function measureOf(st) {
  const m = st.hot_signals && st.hot_signals.measurement;
  if (m && Number.isFinite(m.value)) {
    return { value: m.value, word: METRIC[m.metric] || m.metric, where: srcName(m.source),
      speed: Number.isFinite(m.velocity_per_hour) && m.velocity_per_hour > 0 ? m.velocity_per_hour : null };
  }
  for (const key of PREFER) for (const c of st.coverage || []) {
    const v = c.metrics && c.metrics[key];
    if (typeof v === 'number' && Number.isFinite(v)) return { value: v, word: METRIC[key] || key, where: srcName(c.source), speed: null };
  }
  return null;
}

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
/* Under a translated headline: a "dịch máy" chip, a gap, then the original. Never glued together. */
const origLine = t => !t.orig ? '' :
  `<p class="card-orig"><span class="mt" title="Tiêu đề được dịch máy; dòng này là tiêu đề gốc">dịch máy</span><span class="sr">Tiêu đề gốc: </span><span class="orig-text"${langAttr(t.orig)}>${esc(t.orig)}</span></p>`;

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
  if (m) parts.push(`<b class="num">${fmt(m.value)}</b> ${esc(m.word)}${m.where ? ` trên ${esc(m.where)}` : ''}`);
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

function choosePicks() {
  const out = [...PICKS.keys()].map(id => STORY.get(id)).filter(Boolean).slice(0, WORTH.picksMax);
  const auto = allStories.filter(st => !PICKS.has(st.id) && worthOf(st).evidence).sort(byWorth);
  for (const st of auto) {
    if (out.length >= WORTH.picksMax) break;
    if (!out.some(o => sameEvent(o, st))) out.push(st);
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
  'github-social': 'graphic', 'hf-thumbnail': 'graphic' };
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
const IMAGE_PROVIDERS = [fromVerifiedMap, fromFeedMedia, fromSourceAddress];
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
  return `<div class="media"><img class="media-img" src="${esc(img.src)}" alt="" width="${w}" height="${h}" loading="lazy" decoding="async" referrerpolicy="no-referrer"${size === 'lead' ? ' fetchpriority="high"' : ''}></div>`;
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
  // The foot carries a measured number (and where it was measured, when that is not the source named above) or the
  // sources that carried the story; with neither, only the kind when it says something.
  const metric = [
    m ? `<span><b class="num">${fmt(m.value)}</b> ${esc(m.word)}${m.where && m.where !== name ? ` trên ${esc(m.where)}` : ''}</span>` : '',
    covs.length > 1 ? `${avatarStack(covs.slice(0, 3).map(c => faceOfSource(c, SRC)), 'xs')}<span><b class="num">${covs.length}</b> nguồn</span>` : ''
  ].filter(Boolean).join('<span aria-hidden="true">·</span>') || (st.kind && st.kind !== 'other' && KIND[st.kind] ? `<span>${esc(KIND[st.kind])}</span>` : '');
  const saved = savedSet.has(st.id);
  const cls = ['feed-card', `card-${size}`, photo ? 'card-photo' : '', readSet.has(st.id) ? 'is-read' : ''].filter(Boolean).join(' ');

  return `<article class="${cls}" data-id="${esc(st.id)}" data-via="${esc(img.via)}" data-worth="${worthOf(st).score.toFixed(1)}">
  ${reasonTag(st)}
  ${mediaHTML(img, size)}
  <div class="${photo ? 'photo-body' : 'card-body'}">
    <div class="src-row">${opts.rank ? `<span class="pick-n num"><span class="sr">Số </span>${opts.rank}</span>` : ''}<span class="src-av" aria-hidden="true">${avatar(face, 'xs')}</span><span class="src-name">${esc(name)}</span><span aria-hidden="true">·</span>${timeEl(st.published_at)}${isNew(st) ? '<span class="new-tag">Mới</span>' : ''}</div>
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
        <button class="act${saved ? ' is-saved' : ''}" data-act="save" data-id="${esc(st.id)}" aria-pressed="${saved}" aria-label="Lưu tin này" aria-describedby="${tid}" title="Lưu">${icon('i-bookmark')}</button>
        <button class="act" data-act="copy" data-url="${esc(href)}" aria-label="Chép liên kết" aria-describedby="${tid}" title="Chép liên kết">${icon('i-link')}</button>
      </div>
    </div>
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
    <a class="tile-action${S.live ? ' is-live' : ''}" href="${esc(safe(it.url))}" target="_blank" rel="noopener">${icon('i-play')}${esc(S.action)}</a>`;
  }
  const evHTML = events.length ? `${it ? '<h3 class="tile-sub">Sắp diễn ra</h3>' : ''}
    <ul class="events">${events.map(e => {
      const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(e.start_date || '');
      return `<li><a class="event" href="${esc(safe(e.url))}" target="_blank" rel="noopener">
        <span class="date-badge" aria-hidden="true">${d ? `<b class="num">${+d[3]}</b><span>thg ${+d[2]}</span>` : ''}</span>
        <span class="event-text"><span class="event-name"${langAttr(e.title)}>${esc(e.title)}</span>
        <span class="event-when">${esc(eventRange(e.start_date, e.end_date))} · ${esc(e.location || '')} · ${daysLeftHTML(daysUntil(e.start_date, e.end_date))}</span></span></a></li>`;
    }).join('')}</ul>` : '';
  return `<section class="tile tile-live" aria-labelledby="live-h">
    <div class="tile-head"><h2 class="tile-title" id="live-h">${esc(head)}</h2>${it ? '<span class="tile-note">phát sóng</span>' : ''}</div>
    ${video}${evHTML}</section>`;
}

/* ---------- tile: hot, and why ---------- */
function whyHTML(st) {
  const m = measureOf(st), n = nSrc(st), parts = [];
  if (m) parts.push(`<b class="num">${fmt(m.value)}</b> ${esc(m.word)}${m.where ? ` trên ${esc(m.where)}` : ''}`);
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
      return `<li><a class="hot-row" href="${esc(safe(t.cov ? t.cov.url : st.url))}" target="_blank" rel="noopener">
        <span class="thumb" data-id="${esc(st.id)}">${img.src ? `<img src="${esc(img.src)}" alt="" width="144" height="144" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : miniCover(st)}</span>
        <span class="hot-rank num" aria-hidden="true">${i + 1}</span>
        <span class="hot-text"><span class="hot-title"${langAttr(t.text)}>${esc(t.text)}</span><span class="hot-why">${whyHTML(st)}</span></span></a></li>`;
    }).join('')}</ol></section>`;
}

/* ---------- tiles: repositories and models ---------- */
const LABEL = { 'dung-ngay': 'Dùng ngay', 'xao-nau': 'Xào nấu được', 'nghien-cuu': 'Nghiên cứu' };
const ghPreview = r => { const v = IMG[r.url]; return v && v.src ? v.src : `https://opengraph.githubassets.com/1/${r.full_name}`; };
const hfPreview = r => { const v = IMG[r.url]; return v && v.src ? v.src : `https://cdn-thumbnails.huggingface.co/social-thumbnails/models/${r.full_name}.png`; };
function renderRepos() {
  const repos = (D.repos || []).filter(r => r.source !== 'hf' && (r.label === 'dung-ngay' || r.label === 'xao-nau'))
    .sort((a, b) => (b.stars_gained_7d || 0) - (a.stars_gained_7d || 0)).slice(0, 4);
  if (!repos.length) return '';
  return `<section class="tile tile-repos" aria-labelledby="repos-h">
    <div class="tile-head"><h2 class="tile-title" id="repos-h">Kho mã đáng lấy</h2><span class="tile-note">thịnh hành trên GitHub</span></div>
    <div class="repo-row">${repos.map(r => {
      const desc = r.description_vi || r.description || '';
      return `<a class="repo" href="${esc(safe(r.url))}" target="_blank" rel="noopener">
        <span class="repo-img"><img src="${esc(ghPreview(r))}" alt="" width="1200" height="600" loading="lazy" decoding="async" referrerpolicy="no-referrer"></span>
        <span class="repo-name" lang="en">${esc(r.full_name)}</span>
        <span class="repo-desc"${langAttr(desc)}>${esc(desc)}</span>
        <span class="repo-meta"><span class="label ${esc(r.label)}">${esc(LABEL[r.label] || r.label)}</span>${r.stars_gained_7d ? `<span><b class="num">+${fmt(r.stars_gained_7d)}</b> sao trong 7 ngày</span>` : `<span><b class="num">${fmt(r.stars || 0)}</b> sao</span>`}</span>
      </a>`;
    }).join('')}</div></section>`;
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
  return `<li><a class="hot-row pick-row" href="${esc(safe(t.cov ? t.cov.url : st.url))}" target="_blank" rel="noopener" data-id="${esc(st.id)}" data-worth="${worthOf(st).score.toFixed(1)}">
    <span class="thumb pick-thumb" data-id="${esc(st.id)}">${img.src ? `<img src="${esc(img.src)}" alt="" width="320" height="180" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : miniCover(st)}</span>
    <span class="hot-rank num" aria-hidden="true">${rank}</span>
    <span class="hot-text"><span class="hot-title"${langAttr(t.text)}>${esc(t.text)}</span>
      <span class="hot-why">${pin ? '<span class="tag is-editor">Biên tập chọn</span>' : ''}<span class="sr">Vì sao nên đọc: </span>${worthWhy(st)}</span>
      ${pin && pin.note ? `<span class="pick-note">Ghi chú biên tập: ${esc(pin.note)}</span>` : ''}</span></a></li>`;
}
function renderPicks() {
  const show = filter === 'all' && PICKLIST.length > 0;
  $('#picks').hidden = !show;
  if (!show) return;
  const [first, ...rest] = PICKLIST;
  const nEd = PICKLIST.filter(st => PICKS.has(st.id)).length;
  // Says who chose what, every time: automatic picks are never presented as an editor's.
  $('#picks-note').textContent = !nEd ? 'chấm tự động theo số đo, không phải do người chọn'
    : nEd === PICKLIST.length ? 'do biên tập chọn'
    : `${nEd} tin do biên tập chọn, ${PICKLIST.length - nEd} tin chấm tự động theo số đo`;
  const grid = $('#picks-grid');
  grid.classList.toggle('is-solo', !rest.length);
  grid.innerHTML = renderCard(first, 'lead', { rank: 1, why: true, h: 'h3' })
    + (rest.length ? `<ol class="tile picks-list" start="2" aria-label="Đáng đọc tiếp theo">${rest.map((st, i) => pickRow(st, i + 2)).join('')}</ol>` : '');
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
const C = (st, size = 'std') => ({ t: 'card', st, size });
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
  // The hot tile skips what the block already shows, including the same event under another headline.
  HOT = allStories.filter(st => !used.has(st.id) && st.hot_score > 0 && !PICKLIST.some(p => sameEvent(p, st)))
    .sort((a, b) => b.hot_score - a.hot_score).slice(0, 5);
  HOT.forEach(st => used.add(st.id));
  const river = ordered(allStories.filter(st => !used.has(st.id)));
  // Another headline for an event the block already shows would read as a repeat right under it: it keeps its place
  // in the feed but starts after the opening rows (six cards, the two tiles, four cards). "Mới nhất" stays by time.
  const twins = sortMode === 'new' ? [] : river.filter(st => PICKLIST.some(p => sameEvent(p, st)));
  if (twins.length) {
    const rest = river.filter(st => !twins.includes(st));
    river.splice(0, river.length, ...rest.slice(0, 10), ...twins, ...rest.slice(10));
  }

  out.push({ t: 'live' });
  for (let i = 0; i < 6 && river.length; i++) out.push(C(river.shift()));
  out.push({ t: 'hot' }, { t: 'repos' });
  for (let i = 0; i < 4 && river.length; i++) out.push(C(river.shift()));
  const wi = photoIndex(river);
  if (wi >= 0) out.push(C(river.splice(wi, 1)[0], 'wide'));
  else if (river.length) out.push(C(river.shift()));
  for (let i = 0; i < (wi >= 0 ? 1 : 2) && river.length; i++) out.push(C(river.shift()));
  out.push({ t: 'models' });
  return rows(river, out);
}

const FILTERS = {
  big: st => bigSet.has(st.id),
  hot: st => st.hot_score > 0,
  product: st => st.kind === 'product',
  forum: st => st.kind === 'forum',
  code: st => st.kind === 'repository' || st.kind === 'model',
};
function listFor(f) {
  return f === 'all' ? allStories : allStories.filter(FILTERS[f]);
}
function buildFiltered(f) {
  const river = ordered(listFor(f)), out = [];
  if (f === 'code') { out.push({ t: 'repos' }, { t: 'models' }); return rows(river, out); }
  if (river.length) out.push(C(river.shift(), 'lead'));
  for (let i = 0; i < 4 && river.length; i++) out.push(C(river.shift()));
  return rows(river, out);
}

function renderItem(it) {
  if (it.t === 'card') return renderCard(it.st, it.size);
  if (it.t === 'live') return renderLive();
  if (it.t === 'hot') return renderHot();
  if (it.t === 'repos') return renderRepos();
  if (it.t === 'models') return renderModels();
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
  $('#feed-main').removeAttribute('aria-busy');
  hydrateHF(document);
}

function more() {
  const grid = $('#feed-grid');
  const before = grid.querySelectorAll('.feed-card').length;
  grid.insertAdjacentHTML('beforeend', renderChunk(shownCards + PAGE_MORE));
  updateMore();
  hydrateHF(document);
  // Keep keyboard users in place: focus the first card that just arrived.
  const next = grid.querySelectorAll('.feed-card')[before];
  if (next) next.querySelector('.story-link').focus({ preventScroll: true });
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
    sub.innerHTML = `<span class="num">${allStories.length}</span> tin trong ${winH} giờ qua, từ <span class="num">${srcCount}</span> nguồn. Cập nhật lúc <time datetime="${esc(D.generated_at)}">${esc(updatedAt(D.generated_at))}</time>.`;
  } else {
    sub.innerHTML = `Đang lọc: ${esc(LABELS[filter])} · <span class="num">${listFor(filter).length}</span> tin <button class="text-btn" data-reset>Bỏ lọc</button>`;
  }
}
function renderChips() {
  $$('.filter-chip').forEach(b => {
    const f = b.dataset.filter;
    LABELS[f] = LABELS[f] || b.textContent.trim();
    const n = f === 'all' ? allStories.length : listFor(f).length;
    b.innerHTML = `${esc(LABELS[f])} <span class="count num">${n}</span>`;
    b.hidden = f !== 'all' && n === 0;
    b.setAttribute('aria-pressed', String(f === filter));
  });
}
function setFilter(f) {
  filter = f;
  $$('.filter-chip').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.filter === f)));
  renderFeed();
  const top = $('#feed-main').getBoundingClientRect().top;
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
function renderNewItems() {
  const n = lastVisit ? allStories.filter(isNew).length : 0;
  $('#new-items').hidden = !n;
  if (n) $('#new-items-text').textContent = `${n} tin mới từ lần trước bạn ghé`;
}
function markSeen() {
  lastVisit = new Date().toISOString();
  store.set(K.visit, lastVisit);
  $$('.new-tag').forEach(e => e.remove());
  $('#new-items').hidden = true;
}

function toast(msg) {
  const c = $('#toast-container');
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

/* ---------- a picture that fails to load becomes its cover, never an empty box ---------- */
function watchPictures() {
  document.addEventListener('error', e => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || img.classList.contains('av-img')) return;
    if (img.classList.contains('media-img')) {
      const card = img.closest('.feed-card'), st = card && STORY.get(card.dataset.id);
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
    if (thumb) { const st = STORY.get(thumb.dataset.id); thumb.innerHTML = st ? miniCover(st) : ''; return; }
    if (img.closest('.tile-video, .repo-img, .model-img')) img.remove();
  }, true);
}

/* ---------- events ---------- */
function attachEvents() {
  $('#theme-btn').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.getAttribute('data-theme') === 'dark' || (!root.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    $('#theme-btn').setAttribute('aria-pressed', String(next === 'dark'));
    store.set(K.theme, next);
  });
  $('#feed-filters').addEventListener('click', e => { const b = e.target.closest('.filter-chip'); if (b) setFilter(b.dataset.filter); });
  $('#reset-filter-btn').addEventListener('click', () => setFilter('all'));
  $('#feed-sub').addEventListener('click', e => { if (e.target.closest('[data-reset]')) setFilter('all'); });
  $('#more-btn').addEventListener('click', more);
  $('#mark-seen-btn').addEventListener('click', markSeen);
  $('#mark-all-btn').addEventListener('click', () => {
    listFor(filter).forEach(st => readSet.add(st.id));
    store.set(K.read, [...readSet]);
    $$('.feed-card').forEach(c => c.classList.add('is-read'));
    if (filter === 'all') markSeen();
    toast(filter === 'all' ? 'Đã đánh dấu đã xem hết' : 'Đã đánh dấu nhóm này đã xem');
  });
  $('#feed-grid').addEventListener('click', onCardClick);
  $('#picks').addEventListener('click', onCardClick);
  $('#sort-switch').addEventListener('click', e => { const b = e.target.closest('.sort-btn'); if (b) setSort(b.dataset.sort); });
  $('#how-btn').addEventListener('click', () => {
    const panel = $('#how-panel'), open = panel.hidden;
    panel.hidden = !open;
    $('#how-btn').setAttribute('aria-expanded', String(open));
    $('#how-btn').textContent = open ? 'Ẩn cách chấm' : 'Cách chấm';
  });
  // The next visit counts what arrived after this one.
  addEventListener('pagehide', () => store.set(K.visit, new Date().toISOString()));
}
function onCardClick(e) {
  const act = e.target.closest('.act');
  if (act && act.dataset.act === 'copy') {
    const u = act.dataset.url;
    (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject(new Error())).then(() => toast('Đã chép liên kết'), () => toast(u));
    return;
  }
  if (act && act.dataset.act === 'save') {
    const id = act.dataset.id, on = !savedSet.has(id);
    if (on) savedSet.add(id); else savedSet.delete(id);
    store.set(K.saved, [...savedSet]);
    act.classList.toggle('is-saved', on);
    act.setAttribute('aria-pressed', String(on));
    toast(on ? 'Đã lưu tin này' : 'Đã bỏ lưu');
    return;
  }
  const link = e.target.closest('.story-link, .pick-row');
  if (link) {
    readSet.add(link.dataset.id);
    store.set(K.read, [...readSet]);
    const card = link.closest('.feed-card'); if (card) card.classList.add('is-read');
  }
}

/* ---------- start ---------- */
async function init() {
  const th = store.get(K.theme, null);
  if (th) document.documentElement.setAttribute('data-theme', th);
  $('#theme-btn').setAttribute('aria-pressed', String(th ? th === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches));
  watchImageErrors();
  watchPictures();
  try {
    const [, data, picks] = await Promise.all([loadImages(), loadData(), loadPicks()]);
    D = data;
    SRC = new Map((D.sources || []).map(s => [s.id, s]));
    winH = Number(D.ranking && D.ranking.window_hours);
    if (!Number.isFinite(winH) || winH <= 0) winH = 72;
    const gen = ms(D.generated_at), from = gen - winH * 36e5;
    GEN = gen || Date.now();
    allStories = (D.stories || []).filter(st => { const t = ms(st.published_at); return t && t >= from && t <= gen + 3e5; })
      .sort((a, b) => ms(b.published_at) - ms(a.published_at));
    STORY = new Map(allStories.map(st => [st.id, st]));
    srcCount = new Set(allStories.flatMap(st => (st.coverage || []).map(c => srcName(c.source)))).size;
    const hot = allStories.filter(st => st.hot_score > 0).sort((a, b) => b.hot_score - a.hot_score);
    const k = Math.max(3, Math.min(10, Math.round(allStories.length / 12)));
    bigSet = new Set(hot.slice(0, k).map(st => st.id));
    allStories.forEach(st => { if (nSrc(st) >= 3) bigSet.add(st.id); });
    matchPicks(picks);
    PICKLIST = choosePicks();
    sortMode = store.get(K.sort, 'worth') === 'new' ? 'new' : 'worth';

    lastVisit = store.get(K.visit, null);
    if (!lastVisit) store.set(K.visit, new Date().toISOString());   // first visit: nothing is "new" yet
    $('#feed-empty p').textContent = `Trong ${winH} giờ qua chưa có tin thuộc nhóm này. Chọn nhóm khác hoặc xem tất cả.`;
    renderChips();
    renderNewItems();
    renderHow();
    renderSortSwitch();
    renderFeed();
    attachEvents();
  } catch (err) {
    console.error('feed load failed', err);
    $('#feed-main').removeAttribute('aria-busy');
    $('#feed-grid').innerHTML = '';
    $('#feed-sub').textContent = 'Chưa nạp được dòng tin. Kiểm tra kết nối rồi tải lại trang.';
    const em = $('#feed-empty');
    em.querySelector('h2').textContent = 'Chưa nạp được dòng tin';
    em.querySelector('p').textContent = String((err && err.message) || 'Lỗi mạng hoặc dữ liệu không hợp lệ');
    const b = $('#reset-filter-btn');
    b.textContent = 'Tải lại';
    b.addEventListener('click', () => location.reload());
    em.hidden = false;
  }
}

init();

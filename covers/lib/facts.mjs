// The facts a cover may show, taken from one story of the snapshot. Nothing is invented: every name and figure is a
// verbatim substring of the story's own text, and the logo is the one the site already shows for that source
// (site/faces.js: a GitHub avatar for a verified lab, else a monogram).
//
// The hero, in order (owner, 2026-11-10: "Ok, dùng B, con số"):
//   1. a figure quoted from the story's key points ("100 tỷ tham số");
//   2. else the story's subject, when its name is confidently a proper noun;
//   3. else the outlet or company that published it, with its logo larger.
// Counts are never shown (Halcyon's standing rule "không số đếm"): no number of sources, no Hacker News points.
import { GH_IDENT, monogram } from '../../site/faces.js';

const KIND = { product: 'Sản phẩm', research: 'Nghiên cứu', paper: 'Bài báo', forum: 'Thảo luận', model: 'Mô hình',
  repository: 'Kho mã', release: 'Phát hành', video: 'Video', other: 'Tin tức' };

// Capitalised words that are ordinary Vietnamese with no diacritics (so they look Latin), and words or phrases too
// generic to tell one story from another. Neither is a name.
const NOT_NAMES = new Set(['Theo', 'Trong', 'Sau', 'Khi', 'Cho', 'Con', 'Nam', 'Anh', 'Trung', 'Tin', 'Hai', 'Ba', 'Bao',
  'Tai', 'Hay', 'Nhung', 'Mot', 'Doanh', 'Nga', 'Lan', 'Hoa', 'Kinh', 'Hang', 'Nhom', 'Giao', 'Tong', 'Thanh', 'Ngay',
  'Thang', 'Phan', 'Ban', 'Do', 'Ta', 'In', 'On', 'The', 'A', 'An', 'And', 'Of', 'For', 'To', 'With', 'Is', 'Are', 'New',
  'How', 'Why', 'What', 'Introducing', 'Announces', 'AI', 'USD', 'W', 'CEO', 'CTO', 'GPU', 'GPUs', 'CPU', 'RAM', 'API',
  'LLM', 'LLMs', 'TB', 'GB', 'MB', 'AGI', 'PR', 'App', 'Big Tech', 'Wall Street', 'Silicon Valley', 'Show HN', 'Ask HN']);
const LATIN = /^[A-Za-z0-9][A-Za-z0-9.\-+&]*$/;

// Runs of Latin-script tokens that carry a capital ("Claude Fable 5.2", "DX-M2", "SEEWAY.AI"), in reading order.
function latinRuns(text) {
  const runs = [];
  let cur = [], prevViName = false;
  const flush = () => { if (cur.length) runs.push(cur.join(' ')); cur = []; };
  for (const raw of String(text || '').split(/\s+/)) {
    const t = raw.replace(/^[("“'‘]+|[)"”,;:!?…]+$/g, '').replace(/[’']s$/, '').replace(/\.$/, '');
    // A capitalised word right after a capitalised Vietnamese one is the rest of a Vietnamese name ("Hà Lan").
    const afterVi = prevViName;
    prevViName = /^\p{Lu}/u.test(t) && !LATIN.test(t);
    // A run never starts with a number ("64GB", "3D"): that is a measure, not a name.
    const name = !afterVi && LATIN.test(t) && !NOT_NAMES.has(t) && (cur.length ? /[A-Z\d]/.test(t) : /^[A-Za-z]/.test(t) && /[A-Z]/.test(t));
    if (name && !(t.length === 1 && !cur.length)) cur.push(t); else flush();
    if (/[,;:!?)]$/.test(raw)) flush();
  }
  flush();
  return runs;
}
const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// A candidate is a name only when the English source text has it as a whole word (a repository may be lowercase
// there); short all-letter tokens ("TK") and generic phrases are too easily something else.
function confident(name, english) {
  if (NOT_NAMES.has(name)) return false;
  if (name.replace(/[^A-Za-z0-9]/g, '').length < 3 && !/\d/.test(name)) return false;
  return new RegExp(`(?<![A-Za-z0-9])${escRe(name)}(?![A-Za-z0-9])`, 'i').test(english);
}
// A run, or the run without its trailing numbers: "DeepSeek 284B" stands as "DeepSeek" when only that is in the
// English text. Words are never dropped ("Big Tech" does not become "Big").
function confirmedHead(run, english) {
  const words = run.split(' ');
  for (let n = words.length; n > 0; n--) {
    if (n < words.length && !/\d/.test(words[n])) break;
    const head = words.slice(0, n).join(' ');
    if (confident(head, english)) return head;
  }
  return null;
}

function namesOf(st, skipNames) {
  const skip = new Set(skipNames.map(norm).filter(Boolean));
  const english = [st.title, st.summary, st.headline, ...(st.coverage || []).flatMap(c => [c.title, c.summary])]
    .filter(s => typeof s === 'string').join('\n');
  const vi = [st.editorial_headline_vi || st.title_vi, ...(st.key_points || [])].join(' ');   // repeats an English name
  const out = [];
  const take = list => {
    for (const n of list) {
      const name = confirmedHead(n, english);
      const k = norm(name);
      // Not the source itself, nor a compound built on it ("MSIT-NVIDIA" on NVIDIA's newsroom), nor a repeat.
      if (!k || [...skip].some(s => k === s || (name.includes('-') && s.length >= 4 && k.includes(s)))) continue;
      if (out.some(o => norm(o) === k || norm(o).includes(k) || k.includes(norm(o)))) continue;
      out.push(name);
    }
  };
  // The Vietnamese headline names the story's subject; then the English title's names the Vietnamese text repeats.
  // Names found only deeper in the key points are left out: there they are as often a venue or a cited outlet.
  take(latinRuns(st.editorial_headline_vi || st.title_vi));
  take(latinRuns(st.title).filter(n => vi.includes(n)));
  return out.slice(0, 3);
}

// One figure from the key points, quoted exactly, with a unit a reader understands without its sentence.
const NUM = String.raw`\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?`;
const UNITS = [
  { re: String.raw`(?:tỷ|triệu|nghìn) (?:USD|đô la|nhân dân tệ|tệ|euro|won|yên|đồng)`, w: 5 },
  { re: String.raw`(?:USD|nhân dân tệ|tệ|đô la)`, w: 4 },
  { re: String.raw`(?:tỷ|triệu|nghìn tỷ) (?:tham số|người dùng|token|lượt tải|giờ|USD)`, w: 4 },
  { re: String.raw`(?:tham số|GB\/s|TB\/s|W|MW|GW|TOPS|%)`, w: 3 },
  { re: String.raw`(?:lần)`, w: 2 },
  { re: String.raw`(?:giờ|mẫu xe|quốc gia|GPU)`, w: 1 },
];
const FIG = new RegExp(String.raw`(?<![\d.,])(${NUM}) (${UNITS.map(u => u.re).join('|')})(?![\p{L}\d])`, 'gu');
export function figureOf(st) {
  let best = null;
  (st.key_points || []).slice(0, 4).forEach((p, i) => {
    for (const m of String(p).matchAll(FIG)) {
      const w = UNITS.find(u => new RegExp(`^${u.re}$`, 'u').test(m[2])).w;
      const score = w * 10 - i * 4;   // a stronger unit wins; an earlier point breaks ties
      if (!best || score > best.score) best = { value: m[1], unit: m[2], score };
    }
  });
  return best && { value: best.value, unit: best.unit };
}

// The short names the feed shows for these sources (site/feed.js SHORT_NAMES).
const SHORT_NAMES = { 'github-ai': 'GitHub', 'github-trending': 'GitHub', 'techcrunch-ai': 'TechCrunch',
  'ars-technica-ai': 'Ars Technica', 'the-verge-ai': 'The Verge', 'verge-ai': 'The Verge', 'lobsters-ai': 'Lobsters' };
const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };

export function factsOf(st, sources) {
  const c0 = (st.coverage || [])[0] || {};
  const s = sources.get(c0.source) || {};
  const name = String(s.name || c0.source || hostOf(st.url)).replace(/\s*\(.*?\)\s*/g, ' ').trim();
  const lab = c0.lab || s.lab || '';
  const gh = [c0.lab, s.lab, c0.publisher, s.publisher].map(k => k && GH_IDENT[k]).find(Boolean);
  // A link shared on an aggregator: the outlet that published the article is who the story comes from.
  const aggregator = /^(hn-|lobsters|reddit)/.test(c0.source || '');
  const outlet = (aggregator && hostOf(st.url)) || SHORT_NAMES[c0.source] || name;
  const names = namesOf(st, [name, lab, name.split(' ')[0], outlet]);
  const figure = figureOf(st);
  const hero = figure ? { type: 'figure', value: figure.value, unit: figure.unit }
    : names.length ? { type: 'name', text: names[0] }
    : { type: 'outlet', text: outlet };
  return {
    id: st.id,
    source: name,
    // github.com/<login>.png follows to the account's real avatar; avatars.githubusercontent.com/<login> serves the
    // default silhouette for some organisations (measured 2026-11-10: NVIDIA, anthropics).
    face: gh ? { kind: 'gh', src: `https://github.com/${gh}.png?size=256`, mono: monogram(name) }
             : { kind: 'mono', mono: monogram(name) },
    kind: st.kind, kindLabel: KIND[st.kind] || 'Tin tức',
    hero,
    names: hero.type === 'name' ? names.slice(1) : names,
  };
}

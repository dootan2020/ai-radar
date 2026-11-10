// The facts a cover may show, taken from one story of the live snapshot. Nothing is invented: every name and figure
// is a verbatim substring of the story's own text (Vietnamese headline, key points, English title), and the logo is
// the one the site already shows for that source (site/faces.js: a GitHub avatar for a verified lab, else a monogram).
import { GH_IDENT, monogram } from '../../site/faces.js';

// Source colours, the same table as site/feed.js coverFor (OKLCH hue, chroma, lightness); unknown sources get the
// monogram hue the site already gives them, so a source keeps one colour everywhere.
const BRAND = {
  'hacker-news': { h: 45, c: 0.15 }, 'lobsters': { h: 27, c: 0.12 }, 'github': { h: 255, c: 0.02, l: 0.30 },
  'huggingface': { h: 88, c: 0.11, l: 0.40 }, 'amazon': { h: 255, c: 0.04, l: 0.32 },
  'openai': { h: 265, c: 0.006, l: 0.24 }, 'wired': { h: 265, c: 0.006, l: 0.24 }, 'bloomberg': { h: 265, c: 0.006, l: 0.24 },
  'techcrunch': { h: 142, c: 0.13 }, 'ars-technica': { h: 40, c: 0.15 }, 'vnexpress': { h: 2, c: 0.13 },
  'google': { h: 260, c: 0.14 }, 'meta': { h: 262, c: 0.16 }, 'nvidia': { h: 128, c: 0.15, l: 0.40 },
};
const monoHue = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

const KIND = { product: 'Sản phẩm', research: 'Nghiên cứu', paper: 'Bài báo', forum: 'Thảo luận', model: 'Mô hình',
  repository: 'Kho mã', release: 'Phát hành', video: 'Video', other: 'Tin tức' };

// Capitalised words that are ordinary Vietnamese (no diacritics, so they look Latin), and words too generic to tell a
// story apart. Neither is a name.
const NOT_NAMES = new Set(['Theo', 'Trong', 'Sau', 'Khi', 'Cho', 'Con', 'Nam', 'Anh', 'Trung', 'Tin', 'Hai', 'Ba', 'Bao',
  'Tai', 'Hay', 'Nhung', 'Mot', 'Doanh', 'Nga', 'Lan', 'Hoa', 'Kinh', 'Tin', 'Hang', 'Nhom', 'Giao', 'Tong', 'Thanh', 'Ngay', 'Thang', 'Phan', 'Ban', 'Do', 'Ta', 'In', 'On', 'The',
  'A', 'An', 'And', 'Of', 'For', 'To', 'With', 'Is', 'Are', 'New', 'How', 'Why', 'What', 'Introducing', 'Announces',
  'AI', 'USD', 'W', 'CEO', 'GPU', 'GPUs', 'API', 'LLM', 'TB', 'GB', 'MB', 'AGI']);
const LATIN = /^[A-Za-z0-9][A-Za-z0-9.\-+&'’]*$/;
const hasUpper = t => /[A-Z]/.test(t);

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
    const name = !afterVi && LATIN.test(t) && !NOT_NAMES.has(t) && (hasUpper(t) || (cur.length && /\d/.test(t)));
    if (name && !(t.length === 1 && !cur.length)) cur.push(t); else flush();
    if (/[,;:!?)]$/.test(raw)) flush();
  }
  flush();
  return runs;
}
const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');

function namesOf(st, srcName, lab) {
  const skip = new Set([norm(srcName), norm(lab || ''), norm((srcName || '').split(' ')[0])].filter(Boolean));
  const keep = (list, out) => {
    for (const n of list) {
      const k = norm(n);
      if (!k || skip.has(k) || out.some(o => norm(o) === k || norm(o).includes(k))) continue;
      out.push(n);
    }
    return out;
  };
  // 1. names in the Vietnamese headline the reader sees under the picture are the story's subject;
  const out = keep(latinRuns(st.editorial_headline_vi || st.title_vi), []);
  // 2. else names of the English title that the Vietnamese text repeats verbatim;
  const vi = [st.editorial_headline_vi, ...(st.key_points || [])].join(' ');
  if (!out.length) keep(latinRuns(st.title).filter(n => vi.includes(n)), out);
  // 3. else names in the key points, except the outlet a sentence cites ("Theo Bloomberg, ...").
  if (!out.length) keep((st.key_points || []).flatMap(p => latinRuns(p.replace(/Theo [^,]+,/g, ' '))), out);
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
  { re: String.raw`(?:giờ|startup|mẫu xe|quốc gia|GPU)`, w: 1 },
];
const FIG = new RegExp(String.raw`(?<![\d.,])(${NUM}) (${UNITS.map(u => u.re).join('|')})(?![\p{L}\d])`, 'gu');
function figureOf(st) {
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

const hostOf = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };

export function hasImage(st) { return !!(st.image && st.image.src); }

export function factsOf(st, sources) {
  const c0 = (st.coverage || [])[0] || {};
  const s = sources.get(c0.source) || {};
  const name = String(s.name || c0.source || hostOf(st.url)).replace(/\s*\(.*?\)\s*/g, ' ').trim();
  const pub = c0.publisher || s.publisher || '';
  const lab = c0.lab || s.lab || '';
  const gh = [c0.lab, s.lab, c0.publisher, s.publisher].map(k => k && GH_IDENT[k]).find(Boolean);
  const b = BRAND[pub] || { h: monoHue(name), c: 0.07, l: 0.40 };
  const points = (st.coverage || []).reduce((m, c) => Math.max(m, (c.metrics || {}).points || 0), 0);
  let names = namesOf(st, name, lab);
  // A link shared on an aggregator: the outlet that published the article is part of who the story is.
  const host = hostOf(st.url);
  const aggregator = /^(hn-|lobsters|reddit)/.test(c0.source || '');
  return {
    id: st.id,
    source: name,
    face: gh ? { kind: 'gh', src: `https://avatars.githubusercontent.com/${gh}?s=256`, mono: monogram(name) }
             : { kind: 'mono', mono: monogram(name) },
    hue: b.h, chroma: b.c, light: b.l ?? 0.42,
    kind: st.kind, kindLabel: KIND[st.kind] || 'Tin tức',
    names,
    outlet: aggregator && host ? host : '',
    figure: figureOf(st),
    sourceCount: st.source_count || (st.coverage || []).length || 1,
    points: points || null,
  };
}

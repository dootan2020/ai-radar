/* ai·radar · the visual pieces every tile is built from: source logos (avatars), measured charts.
   Shared by app.js (the page) and design/tokens.js (the showcase), so the showcase renders the markup the page ships.
   Nothing here invents an image or a number:
   - a logo is a GitHub or Hugging Face avatar derived from a real owner or organisation in the data, or a
     YouTube thumbnail; with none of those, a monogram of the publisher's own name;
   - a chart is drawn only from measured values (publish times, hot scores, counters). */

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf = new Intl.NumberFormat('vi-VN');
export const fmt = v => nf.format(Math.round(v));

/* Publisher or lab id (sources[] in data/radar.json) -> its GitHub organisation. Carried over from the
   v2-ui-claude branch, where each login was checked on 02/10/2026 to resolve and to belong to that publisher.
   Publishers without a verified GitHub identity (press, some podcasts) get a monogram, never a guessed logo. */
export const GH_IDENT = {
  'anthropic':'anthropics', 'openai':'openai', 'google':'google', 'nvidia':'NVIDIA', 'meta':'facebook',
  'mistral':'mistralai', 'microsoft':'microsoft', 'huggingface':'huggingface', 'xai':'xai-org',
  'deepseek':'deepseek-ai', 'qwen':'QwenLM', 'hacker-news':'HackerNews', 'lobsters':'lobsters',
  'simon-willison':'simonw', 'interconnects':'natolambert', 'smol-ai':'smol-ai', 'github':'github',
};

const ytRe = /ytimg\.com\/vi\/([\w-]{6,})\//;
export function ytIdOf(st){
  for (const c of st.coverage || []) {
    for (const md of c.media || []) { const m = ytRe.exec(md.url || ''); if (m) return m[1]; }
    const u = /[?&]v=([\w-]{6,})/.exec(c.url || ''); if (u && /youtube\.com/.test(c.url)) return u[1];
    const s = /youtube\.com\/shorts\/([\w-]{6,})/.exec(c.url || ''); if (s) return s[1];
  }
  return null;
}
const ghOwner = url => { const m = /^https:\/\/github\.com\/([\w.-]+)\/[\w.-]+/.exec(url || ''); return m && !['orgs','topics','features','sponsors'].includes(m[1]) ? m[1] : null; };
const hfOwner = url => { const m = /^https:\/\/huggingface\.co\/(?:spaces\/)?([\w.-]+)\/[\w.-]+\/?$/.exec(url || ''); return m && !['papers','datasets','api','blog','docs'].includes(m[1]) ? m[1] : null; };

/* Letters and digits only, each kept whole with its combining marks (decomposed "ế" is one letter), so an
   emoji or symbol in a name ("🚨 AI News") is skipped instead of being split into half a surrogate pair. */
const lettersOf = word => word.match(/[\p{L}\p{N}]\p{M}*/gu) || [];
export function monogram(name){
  const w = String(name || '').replace(/\(.*?\)/g, '').trim().split(/[\s/._|-]+/).map(lettersOf).filter(l => l.length);
  if (!w.length) return '?';
  return (w[0][0] + (w[1] ? w[1][0] : (w[0][1] || ''))).toUpperCase();
}
/* A monogram's tint comes from its letters, so the same publisher always gets the same tile. */
const monoHue = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

/* The face of a story: its repository owner when the story IS a repository or model, else its first source.
   A discussion or article that links to a repository keeps its own source's logo, matching the source named beside it. */
export function faceOfStory(st, src){
  if (st.kind === 'repository' || st.kind === 'model') {
    for (const c of [{url: st.url}, ...(st.coverage || [])]) {
      const g = ghOwner(c.url); if (g) return {kind:'gh', id:g, label:g};
      const h = hfOwner(c.url); if (h) return {kind:'hf', id:h, label:h};
    }
  }
  return faceOfSource((st.coverage || [])[0], src);
}
/* c: a coverage item {source, lab, publisher}; `name` is a display name for items with no source id (a YouTube channel). */
export function faceOfSource(c, src){
  const s = (c && src && src.get(c.source)) || {};
  const name = s.name || (c && (c.name || c.source)) || '';
  for (const k of [c && c.lab, s.lab, c && c.publisher, s.publisher]) if (k && GH_IDENT[k]) return {kind:'gh', id:GH_IDENT[k], label:name};
  return {kind:'mono', id:monogram(name), label:name};
}
export function faceOfRepo(r){
  const owner = String(r.full_name || '').split('/')[0];
  return {kind: r.source === 'hf' ? 'hf' : 'gh', id: owner, label: owner};
}

/* While the page draws its first screen it holds image addresses in data-src, so logos and thumbnails never compete
   with the snapshot for the connection; app.js calls loadDeferredImages() once that screen has painted. The box,
   its size and its monogram are there from the start, so nothing moves when the image arrives. */
let deferImages = false;
export const setDeferImages = on => { deferImages = !!on; };
export const imgSrc = url => `${deferImages ? 'data-src' : 'src'}="${url}"`;
export function loadDeferredImages(root = document){
  root.querySelectorAll('img[data-src]').forEach(img => { img.src = img.dataset.src; img.removeAttribute('data-src'); });
}

/* size: xs | sm | md | lg | xl. Every face carries its monogram, so a broken image falls back without a reflow. */
const PX = {xs:20, sm:28, md:40, lg:56, xl:72};
export function avatar(face, size = 'md'){
  const px = PX[size] || 40;
  const mono = esc(face.kind === 'mono' ? face.id : monogram(face.label || face.id));
  const style = ` style="--mono-h:${monoHue(face.label || face.id)}"`;
  if (face.kind === 'mono') return `<span class="av av-${size} is-fallback" data-mono="${mono}"${style} role="img" aria-label="${esc(face.label || '')}"></span>`;
  if (face.kind === 'gh') return `<span class="av av-${size}" data-mono="${mono}"${style}><img class="av-img" ${imgSrc(`https://avatars.githubusercontent.com/${esc(face.id)}?s=${px * 2}`)} alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" width="${px}" height="${px}"></span>`;
  const cached = hfCache.get(face.id);
  return `<span class="av av-${size}${cached === null ? ' is-fallback' : ''}" data-mono="${mono}" data-hf="${esc(face.id)}"${style}>${cached ? `<img class="av-img" ${imgSrc(esc(cached))} alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" width="${px}" height="${px}">` : ''}</span>`;
}
/* Several sources as one overlapping stack. */
export function avatarStack(faces, size = 'sm'){
  return `<span class="av-stack">${faces.map(f => `<span class="av-stack-item" title="${esc(f.label)}">${avatar(f, size)}</span>`).join('')}</span>`;
}

/* ---------- Hugging Face avatars: one API call per organisation, cached on this machine for a week ---------- */
const HF_KEY = 'air2:hf-avatars', HF_TTL = 7 * 864e5;
const hfCache = new Map();
try { const o = JSON.parse(localStorage.getItem(HF_KEY) || '{}'); for (const [k, v] of Object.entries(o)) if (v && Date.now() - v.t < HF_TTL) hfCache.set(k, v.u); } catch { /* storage blocked: memory only */ }
const hfInflight = new Map();
const okHF = u => typeof u === 'string' && /^https:\/\/cdn-avatars\.huggingface\.co\//.test(u);
async function hfLookup(name){
  for (const kind of ['organizations', 'users']) {
    try {
      const r = await fetch(`https://huggingface.co/api/${kind}/${encodeURIComponent(name)}/avatar`, {credentials:'omit', referrerPolicy:'no-referrer'});
      if (!r.ok) continue;
      const j = await r.json();
      if (okHF(j && j.avatarUrl)) return j.avatarUrl;
    } catch { /* network: try the next kind, then fall back to the monogram */ }
  }
  return null;
}
function hfSave(){
  try { const o = {}; hfCache.forEach((u, k) => { o[k] = {u, t: Date.now()}; }); localStorage.setItem(HF_KEY, JSON.stringify(o)); } catch { /* ignore */ }
}
export function hydrateHF(root = document){
  root.querySelectorAll('.av[data-hf]:not(.is-fallback)').forEach(el => {
    // Only faces that are laid out: a capped list's hidden rows wait until they are expanded.
    if (el.querySelector('img') || !el.getClientRects().length) return;
    const name = el.dataset.hf;
    const fill = u => document.querySelectorAll(`.av[data-hf="${CSS.escape(name)}"]`).forEach(a => {
      if (a.querySelector('img')) return;
      if (!u) { a.classList.add('is-fallback'); return; }
      const px = PX[(a.className.match(/av-(xs|sm|md|lg|xl)/) || [])[1]] || 40;
      a.insertAdjacentHTML('afterbegin', `<img class="av-img" src="${esc(u)}" alt="" decoding="async" referrerpolicy="no-referrer" width="${px}" height="${px}">`);
    });
    if (hfCache.has(name)) { fill(hfCache.get(name)); return; }
    if (!hfInflight.has(name)) hfInflight.set(name, hfLookup(name).then(u => { hfCache.set(name, u); hfSave(); return u; }));
    hfInflight.get(name).then(fill);
  });
}
/* A broken image (deleted account, blocked host) falls back to the monogram already carried in data-mono. */
export function watchImageErrors(){
  document.addEventListener('error', e => {
    const t = e.target;
    if (t instanceof HTMLImageElement && t.classList.contains('av-img')) { const a = t.closest('.av'); if (a) { a.classList.add('is-fallback'); t.remove(); } }
  }, true);
}

/* ---------- measured charts ---------- */
/* Stories published per hour over the 24 hours before endIso. Hours after sinceIso are the reader's new ones. */
export function hourHistogram(stories, endIso, sinceIso){
  const end = new Date(endIso).getTime(), since = sinceIso ? new Date(sinceIso).getTime() : end - 864e5;
  const bins = Array(24).fill(0);
  for (const s of stories) {
    if (!s.published_at) continue;
    const age = (end - new Date(s.published_at).getTime()) / 36e5;
    if (age >= 0 && age < 24) bins[23 - Math.floor(age)]++;
  }
  const max = Math.max(1, ...bins), total = bins.reduce((a, b) => a + b, 0);
  const cells = bins.map((n, i) => `<i class="hist-bar${end - (23 - i) * 36e5 > since ? ' is-new' : ''}${n ? '' : ' is-zero'}" style="--h:${(n / max).toFixed(3)}"></i>`).join('');
  return `<span class="hist" role="img" aria-label="${total} tin đăng trong 24 giờ, nhiều nhất ${max} tin trong một giờ">${cells}</span>`;
}
/* A ring for a 0..100 measured score; the number in its centre is the same value, so the ring never says more than the data. */
export function ring(value, label){
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const r = 44, c = 2 * Math.PI * r;
  return `<span class="ring" role="img" aria-label="${esc(label)}: ${Math.round(v)} trên 100">
    <svg viewBox="0 0 100 100" aria-hidden="true"><circle class="ring-track" cx="50" cy="50" r="${r}"/><circle class="ring-val" cx="50" cy="50" r="${r}" style="--c:${c.toFixed(2)};--off:${(c * (1 - v / 100)).toFixed(2)}"/></svg>
    <span class="ring-n"><b class="num">${Math.round(v)}</b><span>/100</span></span></span>`;
}
/* A horizontal meter for one value against the largest in its list. */
export const meter = (v, max) => `<span class="meter" aria-hidden="true"><i style="--v:${Math.max(0.02, max ? v / max : 0).toFixed(3)}"></i></span>`;

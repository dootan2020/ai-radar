// Shared by every cover template: read the story's facts from the address, build the logo, fit type, report ready.
// The facts come from lib/facts.mjs; a template only arranges them.
export const facts = JSON.parse(decodeURIComponent(location.hash.slice(1) || '%7B%7D'));

// A name never breaks before its number or version ("Claude Fable 5.2"): that space becomes a no-break space.
export const glue = s => String(s ?? '').replace(/ (?=[\d.,]+(?:\s|$))/g, '\u00a0');
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// The source's logo as the site shows it: its GitHub avatar, or its monogram when it has none (or the avatar fails).
export function logo(f = facts, cls = 'logo') {
  const mono = `<span class="${cls} is-mono" aria-hidden="true"><b>${esc(f.face.mono)}</b></span>`;
  if (f.face.kind !== 'gh') return mono;
  return `<span class="${cls} is-img" data-mono="${esc(f.face.mono)}"><img src="${esc(f.face.src)}" alt="" onerror="this.parentNode.outerHTML=${esc(JSON.stringify(mono))}"></span>`;
}

// The figure for a hero slot: the key point's own number, else a measured count the snapshot carries.
export function hero(f = facts) {
  if (f.figure) return { value: f.figure.value, unit: f.figure.unit, measured: false };
  if (f.points) return { value: String(f.points), unit: 'điểm Hacker News', measured: true };
  if (f.sourceCount > 1) return { value: String(f.sourceCount), unit: 'nguồn đưa tin', measured: true };
  return null;
}

// Shrink an element's font until its lines fit its box, between max and min px. The element holds one block child
// per line group; their line boxes are measured, not scrollHeight, because the font's tall Vietnamese marks make its
// glyph box overflow the line box by a pixel or two at every size. A word wider than the box also counts as not
// fitting; only at the minimum size may a word break.
export function fit(el, max, min = 8) {
  if (!el) return;
  const kids = [...el.children];
  const fits = () => kids.reduce((a, k) => a + k.offsetHeight, 0) <= el.clientHeight + 0.5 &&
    Math.max(...kids.map(k => k.scrollWidth)) <= el.clientWidth + 0.5;
  let size = max;
  el.style.fontSize = `${size}px`;
  while (size > min && !fits()) { size -= 0.5; el.style.fontSize = `${size}px`; }
  if (!fits()) el.style.overflowWrap = 'anywhere';
}

// One design pixel: the template is drawn on a 261 x 148 card (the 1440 px feed) and scales to any frame.
export const unit = () => Math.min(innerWidth / 261, innerHeight / 148);

export async function ready() {
  await document.fonts.ready;
  await Promise.all([...document.images].map(i => i.complete ? null : new Promise(r => {
    i.addEventListener('load', r, { once: true }); i.addEventListener('error', r, { once: true });
  })));
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  document.documentElement.dataset.ready = '1';
}

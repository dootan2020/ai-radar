/* Halcyon · the shell of the pages beside the front page (trang-phu.css): "Tùy chỉnh" at the top right, and the news
   search form of the 404 page. The front page's own sheet (thanh-tren.js) also sets the layout, the day's picture and the
   weather; a sub-page has none of those, so its sheet carries the theme and the two pages the front page's sheet links
   (captain, 16/11, decision 4: "Chính sách riêng tư" and "Nguồn tin"). The theme is the same choice as on the front page:
   one localStorage key (air2:theme) that every page's first-paint script reads. Links resolve from this file's own
   address, so the shell works at /, at /tin/<id>/ and on the 404 page at any depth. */

export const THEME_KEY = 'air2:theme';
export const THEMES = [['light', 'Sáng'], ['dark', 'Tối'], ['system', 'Theo máy']];
const here = file => new URL(file, import.meta.url).href;
export const LINKS = [['nguon.html', 'Nguồn tin'], ['chinh-sach-rieng-tu.html', 'Chính sách riêng tư']];

export function readTheme(storage) {
  try {
    const t = JSON.parse(storage?.getItem(THEME_KEY) ?? 'null');
    return t === 'light' || t === 'dark' ? t : 'system';
  } catch { return 'system'; }
}

export function saveTheme(storage, theme) {
  try {
    if (theme === 'light' || theme === 'dark') storage.setItem(THEME_KEY, JSON.stringify(theme));
    else storage.removeItem(THEME_KEY);
    return true;
  } catch { return false; }
}

export function applyTheme(root, theme) {
  if (theme === 'light' || theme === 'dark') root.dataset.theme = theme; else delete root.dataset.theme;
}

const ICON_CLOSE = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>';
const ICON_GO = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>';   // a page of this site, not a way out

export function sheetHTML() {
  return `<div class="tc-top"><h2 id="phu-tc-h">Tùy chỉnh</h2>`
    + `<button class="tc-close" type="button" data-tc-close aria-label="Đóng tùy chỉnh">${ICON_CLOSE}</button></div>`
    + `<fieldset class="tc-group"><legend>Giao diện</legend><div class="tc-seg">${THEMES.map(([v, name]) =>
      `<label><input class="sr" type="radio" name="phu-theme" value="${v}"><span>${name}</span></label>`).join('')}</div></fieldset>`
    + `<div class="tc-group">${LINKS.map(([file, name]) =>
      `<a class="tc-row" href="${here(file)}"><span>${name}</span>${ICON_GO}</a>`).join('')}</div>`;
}

const local = () => { try { return globalThis.localStorage; } catch { return null; } };

export function startSettings(doc = document) {
  const btn = doc.getElementById('phu-tc');
  if (!btn) return null;
  const root = doc.documentElement;
  const storage = local();
  const sheet = doc.createElement('div');
  sheet.className = 'phu-sheet';
  sheet.id = 'phu-tuy-chinh';
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-labelledby', 'phu-tc-h');
  sheet.hidden = true;
  sheet.innerHTML = sheetHTML();
  doc.body.append(sheet);
  btn.setAttribute('aria-controls', sheet.id);
  const radios = () => sheet.querySelectorAll('[name="phu-theme"]');

  const sync = () => {
    const theme = root.dataset.theme === 'light' || root.dataset.theme === 'dark' ? root.dataset.theme : 'system';
    radios().forEach(r => { r.checked = r.value === theme; });
  };
  sheet.addEventListener('change', e => {
    if (e.target.name !== 'phu-theme') return;
    saveTheme(storage, e.target.value);
    applyTheme(root, e.target.value);
  });

  let closing;
  const open = fromKeyboard => {
    clearTimeout(closing);
    sync();
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add('is-open'));
    btn.setAttribute('aria-expanded', 'true');
    const first = [...radios()].find(r => r.checked);
    if (fromKeyboard && first) first.focus({ preventScroll: true });
    else { sheet.tabIndex = -1; sheet.focus({ preventScroll: true }); }
  };
  const close = (focus = false) => {
    if (sheet.hidden) return;
    btn.setAttribute('aria-expanded', 'false');
    sheet.classList.remove('is-open');
    closing = setTimeout(() => { sheet.hidden = true; }, 160);
    if (focus) btn.focus();
  };
  btn.addEventListener('click', e => (btn.getAttribute('aria-expanded') === 'true' ? close() : open(e.detail === 0)));
  sheet.addEventListener('click', e => { if (e.target.closest('[data-tc-close]')) close(true); });
  doc.addEventListener('pointerdown', e => { if (!sheet.hidden && !sheet.contains(e.target) && !btn.contains(e.target)) close(); });
  doc.addEventListener('keydown', e => { if (e.key === 'Escape' && !sheet.hidden) { e.preventDefault(); close(true); } });
  return { sheet, open, close };
}

/* The 404 page's search: the front page opens its news search with the words of ?q= (feed.js openSearchFromAddress, the
   address tra-cuu.html forwards to). The pages' policy forbids form submission (form-action 'none'), so the script sends
   the reader there itself. */
export function searchHref(words) {
  const q = String(words ?? '').trim();
  return here('./') + (q ? `?q=${encodeURIComponent(q)}` : '#tim');
}

export function startSearch(doc = document) {
  doc.querySelectorAll('form[data-tim-tin]').forEach(form => form.addEventListener('submit', e => {
    e.preventDefault();
    location.href = searchHref(form.querySelector('input')?.value);
  }));
}

if (typeof document !== 'undefined') {
  const start = () => { startSettings(); startSearch(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
}

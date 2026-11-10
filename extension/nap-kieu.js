/* The front page's stylesheets, applied without holding the first paint (Lighthouse, 11/11).
   index.html inlines the rules its first screen draws before any script runs (the "critical css" block, written by
   radar/critical_css.py from these same files) and asks for the complete files with <link rel="preload" as="style">.
   A preload applies nothing by itself, and the page's policy allows no inline event handler, so this module turns each
   one into a stylesheet. Whatever a script draws (the feed, the top row) waits for stylesReady, so nothing is ever
   drawn with only part of its rules. A page without such preloads (the extension's new tab, the other pages) gets a
   promise that is already settled. */

/* A file that never answers must not keep the page in its skeleton: after STYLES_WAIT_MS the page draws with what has
   arrived (the inline first-screen rules at least) and the late file still applies when it comes. */
export const STYLES_WAIT_MS = 4000;

export function applyLateSheets(doc, waitMs = STYLES_WAIT_MS) {
  const links = [...doc.querySelectorAll('link[rel="preload"][as="style"]')];
  const all = Promise.all(links.map(link => new Promise(done => {
    link.addEventListener('load', done, { once: true });
    link.addEventListener('error', done, { once: true });   // a missing file must not keep the page from drawing
    link.rel = 'stylesheet';
  })));
  let timer;
  const late = new Promise(done => { timer = setTimeout(done, waitMs); });
  return Promise.race([all, late]).then(() => { clearTimeout(timer); });
}

export const stylesReady = typeof document === 'undefined' ? Promise.resolve() : applyLateSheets(document);

/* The front page's stylesheets, applied without holding the first paint (Lighthouse, 11/11).
   index.html inlines the rules its first screen draws before any script runs (the "critical css" block, written by
   radar/critical_css.py from these same files) and asks for the complete files with <link rel="preload" as="style">.
   A preload applies nothing by itself, and the page's policy allows no inline event handler, so this module turns each
   one into a stylesheet. Whatever a script draws (the feed, the top row) waits for stylesReady, so nothing is ever
   drawn with only part of its rules. A page without such preloads (the extension's new tab, the other pages) gets a
   promise that is already settled. */

function applyLateSheets(doc) {
  const links = [...doc.querySelectorAll('link[rel="preload"][as="style"]')];
  return Promise.all(links.map(link => new Promise(done => {
    link.addEventListener('load', done, { once: true });
    link.addEventListener('error', done, { once: true });   // a missing file must not keep the page from drawing
    link.rel = 'stylesheet';
  }))).then(() => undefined);
}

export const stylesReady = typeof document === 'undefined' ? Promise.resolve() : applyLateSheets(document);

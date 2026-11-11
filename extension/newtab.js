/* "Tìm trên web": the query goes to the reader's own default search engine through the Chrome Search API, in this
   tab. The Chrome Web Store rejects a new tab whose search ignores the user's search settings (Quality Guidelines,
   checked 11/11), so the box no longer opens Google directly as it did from 07/11. Outside an extension page there is
   no chrome.search and the box does nothing: any fallback would have to name an engine the reader never chose. */
document.querySelector('#web-search').addEventListener('submit', event => {
  event.preventDefault();
  const text = document.querySelector('#web-query').value.trim();
  if (text && globalThis.chrome?.search?.query) chrome.search.query({text, disposition: 'CURRENT_TAB'});
});

let initialSnapshotKnown = false;
let awaitingFirstSnapshot = false;
let snapshotChangedDuringLoad = false;
let reloading = false;
function reloadForFirstSnapshot() {
  if (reloading) return;
  reloading = true;
  location.reload();
}
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !changes.radarWindow?.newValue) return;
  if (!initialSnapshotKnown) snapshotChangedDuringLoad = true;
  else if (awaitingFirstSnapshot) reloadForFirstSnapshot();
});
chrome.storage.local.get('radarWindow').then(({radarWindow}) => {
  awaitingFirstSnapshot = !radarWindow;
  initialSnapshotKnown = true;
  if (snapshotChangedDuringLoad) reloadForFirstSnapshot();
});

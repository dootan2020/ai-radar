/* "Tìm trên Google" (captain, 07/11 18:26: "không đặt tìm kiếm web mà là tìm kiếm google luôn"): the query opens
   Google's results in this tab, whatever the reader's default engine is. A plain link needs no permission. */
export const googleSearchURL = query => `https://www.google.com/search?q=${encodeURIComponent(query)}`;
document.querySelector('#web-search').addEventListener('submit', event => {
  event.preventDefault();
  const query = document.querySelector('#web-query').value.trim();
  if (query) location.assign(googleSearchURL(query));
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

document.querySelector('#web-search').addEventListener('submit', event => {
  event.preventDefault();
  const query = document.querySelector('#web-query').value.trim();
  if (query) chrome.search.query({text: query, disposition: 'CURRENT_TAB'});
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

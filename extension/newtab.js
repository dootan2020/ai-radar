document.querySelector('#web-search').addEventListener('submit', event => {
  event.preventDefault();
  const query = document.querySelector('#web-query').value.trim();
  if (query) chrome.search.query({text: query, disposition: 'CURRENT_TAB'});
});

let awaitingFirstSnapshot = false;
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.radarWindow && awaitingFirstSnapshot) location.reload();
});
chrome.storage.local.get('radarWindow').then(({radarWindow}) => {
  awaitingFirstSnapshot = !radarWindow;
});

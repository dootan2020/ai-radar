import {renderFeed} from './render.js';

const stories = document.querySelector('#stories');
const freshness = document.querySelector('#freshness');

function showCache(cache) {
  const payload = cache.radarHead;
  stories.replaceChildren(renderFeed(payload));
  const fetched = Date.parse(cache.radarFetchedAt);
  if (!payload || !Number.isFinite(fetched)) {
    freshness.textContent = 'Đang chờ bản tin đầu tiên';
    return;
  }
  const cadence = Number(payload.freshness?.expected_interval_seconds) || 1800;
  const stale = Date.now() - fetched > cadence * 1000;
  const time = new Intl.DateTimeFormat('vi-VN', {dateStyle: 'short', timeStyle: 'short'}).format(fetched);
  freshness.textContent = `${stale ? 'Dữ liệu cũ · ' : 'Cập nhật · '}Lấy lần cuối ${time}`;
}

chrome.storage.local.get(['radarHead', 'radarFetchedAt']).then(showCache);
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.radarHead || changes.radarFetchedAt)) {
    chrome.storage.local.get(['radarHead', 'radarFetchedAt']).then(showCache);
  }
});

document.querySelector('#search').addEventListener('submit', event => {
  event.preventDefault();
  const query = document.querySelector('#query').value.trim();
  if (query) chrome.search.query({text: query, disposition: 'CURRENT_TAB'});
});

chrome.topSites.get(sites => {
  const items = document.querySelector('#shortcuts');
  for (const site of sites.slice(0, 8)) {
    try {
      const url = new URL(site.url);
      if (!['http:', 'https:'].includes(url.protocol)) continue;
      const entry = document.createElement('li');
      const anchor = document.createElement('a');
      anchor.href = url.href;
      anchor.textContent = site.title || url.hostname;
      entry.append(anchor);
      items.append(entry);
    } catch { /* Ignore invalid browser history entries. */ }
  }
});

const DATA_URL = 'https://radar-ai-vn.pages.dev/data/radar-head.json';
const ALARM = 'refresh-radar-head';

async function refresh() {
  try {
    const response = await fetch(DATA_URL, {cache: 'no-cache'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload.schema_version !== 2 || !Array.isArray(payload.stories) ||
        !payload.sections || typeof payload.sections !== 'object') {
      throw new Error('Invalid radar-head payload');
    }
    await chrome.storage.local.set({radarHead: payload, radarFetchedAt: new Date().toISOString()});
  } catch (error) {
    console.warn('ai·radar refresh failed; saved stories remain available', error);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM, {periodInMinutes: 30});
  void refresh();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, {periodInMinutes: 30});
  void refresh();
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM) void refresh();
});

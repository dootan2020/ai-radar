const DATA_URL = 'https://radar-ai-vn.pages.dev/data/radar-window.json';
const ALARM = 'refresh-radar-window';

async function ensureAlarm() {
  if (!await chrome.alarms.get(ALARM)) {
    await chrome.alarms.create(ALARM, {periodInMinutes: 30});
  }
}

void ensureAlarm();

async function refresh() {
  try {
    const response = await fetch(DATA_URL, {cache: 'no-cache', signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload.schema_version !== 2 || !Array.isArray(payload.stories) ||
        !payload.sections || typeof payload.sections !== 'object') {
      throw new Error('Invalid radar-window payload');
    }
    await chrome.storage.local.set({radarWindow: payload, radarFetchedAt: new Date().toISOString()});
  } catch (error) {
    console.warn('AIBit News refresh failed; saved stories remain available', error);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void refresh();
});
chrome.runtime.onStartup.addListener(() => {
  void refresh();
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM) void refresh();
});

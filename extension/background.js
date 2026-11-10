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
    console.warn('Halcyon refresh failed; saved stories remain available', error);
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

// The toolbar button. Chrome draws an extension without an action of its own in grey (captain, 10/11 18:54: "nút
// extension ở góc phải trên chrome có màu nền xám"); with one, it shows the Coral Tile in colour. A click opens a new tab,
// which is Halcyon.
chrome.action.onClicked.addListener(() => {
  void chrome.tabs.create({});
});

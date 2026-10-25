const object = value => value && typeof value === 'object' && !Array.isArray(value);
const entries = value => Array.isArray(value) ? value.filter(object) : [];
const LIVE = 'https://radar-ai-vn.pages.dev/';
const imageSrc = src => {
  try { return new URL(src, LIVE).href; }
  catch { return src; }
};

export function normalizeSnapshot(payload) {
  if (!object(payload) || payload.schema_version !== 2 || !Array.isArray(payload.stories)) {
    throw new Error('Invalid radar-window payload');
  }
  return {
    ...payload,
    stories: entries(payload.stories).map(story => ({
      ...story,
      title: story.title || story.headline || 'Bài viết chưa có tiêu đề',
      image: object(story.image) && typeof story.image.src === 'string' && story.image.src ?
        {...story.image, src: imageSrc(story.image.src)} : story.image,
      coverage: entries(story.coverage),
    })),
    live: entries(payload.live),
    repos: entries(payload.repos).map(repo => ({
      ...repo,
      full_name: repo.full_name || String(repo.id || 'Kho mã chưa có tên'),
    })),
    sources: entries(payload.sources),
    events: entries(payload.events),
  };
}

export async function cachedSnapshot() {
  const {radarWindow} = await chrome.storage.local.get('radarWindow');
  return radarWindow ? normalizeSnapshot(radarWindow) : null;
}

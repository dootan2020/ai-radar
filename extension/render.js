const text = value => typeof value === 'string' ? value : '';
const list = value => Array.isArray(value) ? value : [];
const safeUrl = value => {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
};

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value) node.textContent = value;
  return node;
}

function link(item, label) {
  const url = safeUrl(item.url);
  const node = element(url ? 'a' : 'span', '', label);
  if (url) {
    node.href = url;
    node.rel = 'noopener noreferrer';
  }
  return node;
}

function storyCard(story, lead = false) {
  const card = element('article', lead ? 'card lead' : 'card');
  const title = element(lead ? 'h3' : 'h4');
  title.append(link(story, text(story.headline_vi) || text(story.title_vi) || text(story.headline) || text(story.title)));
  card.append(title);
  const description = text(story.summary_vi) || text(story.summary);
  if (description) card.append(element('p', 'summary', description));
  const details = [];
  if (Number.isFinite(story.source_count) && story.source_count > 0) details.push(`${story.source_count} nguồn`);
  if (Number.isFinite(story.hot_score)) details.push(`${story.hot_score} điểm nóng`);
  if (details.length) card.append(element('p', 'measure', details.join(' · ')));
  return card;
}

function section(title, kind, items, renderItem) {
  if (!items.length) return null;
  const wrapper = element('section', 'feed-section');
  wrapper.dataset.kind = kind;
  wrapper.append(element('h3', '', title));
  const body = element('div', 'card-grid');
  for (const item of items) body.append(renderItem(item));
  wrapper.append(body);
  return wrapper;
}

export function renderFeed(payload) {
  const root = element('div', 'feed-content');
  const stories = list(payload?.stories);
  const byId = new Map(stories.map(story => [story.id, story]));
  const hot = list(payload?.sections?.hot).map(id => byId.get(id)).filter(Boolean);
  const lead = hot[0] || stories[0];
  if (!lead) {
    root.append(element('p', 'empty', 'Chưa có dữ liệu. Bản tin sẽ xuất hiện sau lần cập nhật đầu tiên.'));
    return root;
  }
  root.append(storyCard(lead, true));
  const hotSection = section('Đang nóng', 'hot', hot.filter(story => story.id !== lead.id), storyCard);
  if (hotSection) root.append(hotSection);
  const live = list(payload?.live);
  const liveSection = section('Phát trực tiếp', 'live', live, item => {
    const card = element('article', 'card');
    const heading = element('h4');
    heading.append(link(item, text(item.title)));
    card.append(heading);
    if (text(item.status)) card.append(element('p', 'measure', text(item.status)));
    return card;
  });
  if (liveSection) root.append(liveSection);
  const repos = list(payload?.repos);
  const repoSection = section('Kho mã đang lên', 'repos', repos, repo => {
    const card = element('article', 'card');
    const heading = element('h4');
    heading.append(link(repo, text(repo.full_name) || text(repo.id)));
    card.append(heading);
    const description = text(repo.description_vi) || text(repo.description);
    if (description) card.append(element('p', 'summary', description));
    if (Number.isFinite(repo.stars)) card.append(element('p', 'measure', `${repo.stars.toLocaleString('vi-VN')} sao`));
    return card;
  });
  if (repoSection) root.append(repoSection);
  return root;
}

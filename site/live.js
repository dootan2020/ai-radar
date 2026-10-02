/* Live layer 1: the browser re-reads three public, CORS-open measurement endpoints every 90 s
   and refreshes the counters of stories that are already in the snapshot. It never adds stories,
   never re-ranks (ranking belongs to the pipeline) and never hides a failure: each endpoint
   reports its own state, and a failed endpoint leaves the snapshot's numbers in place. */

const EVERY_MS = 90_000;
const TIMEOUT_MS = 15_000;

export const LIVE_SOURCES = [
  { id: 'hn', label: 'Hacker News (Algolia)', url: 'https://hn.algolia.com/' },
  { id: 'hf-papers', label: 'Hugging Face Daily Papers', url: 'https://huggingface.co/papers' },
  { id: 'hf-models', label: 'Mô hình thịnh hành trên Hugging Face', url: 'https://huggingface.co/models?sort=trending' },
];

export const hnItemId = url => (/^https:\/\/news\.ycombinator\.com\/item\?id=(\d+)$/.exec(url || '') || [])[1] || null;
export const paperId = url => (/(?:arxiv\.org\/(?:abs|pdf|html)\/|huggingface\.co\/papers\/)(\d{4}\.\d{4,5})/.exec(url || '') || [])[1] || null;
export const hfModelId = url => (/^https:\/\/huggingface\.co\/(?!papers\/|spaces\/|datasets\/|api\/)([\w.-]+\/[\w.-]+)\/?$/.exec(url || '') || [])[1] || null;

async function getJSON(url) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { signal: ctl.signal, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer' });
    if (!r.ok) throw Object.assign(new Error(`máy chủ trả mã HTTP ${r.status}`), { vi: true });
    return await r.json();
  } catch (e) {
    // A browser's own error text is English and technical; the reader sees the page's words only.
    throw new Error(e.name === 'AbortError' ? `hết ${TIMEOUT_MS / 1000} giây chờ` : (e.vi ? e.message : 'lỗi mạng hoặc phản hồi không đọc được'));
  } finally { clearTimeout(t); }
}

/* Build lookups from the current snapshot: external id -> coverage items carrying that id. */
function indexCoverage(stories) {
  const hn = new Map(), papers = new Map(), models = new Map();
  const put = (m, k, c) => { if (!k) return; if (!m.has(k)) m.set(k, []); m.get(k).push(c); };
  for (const s of stories) for (const c of s.coverage || []) {
    if (c.metrics && 'points' in c.metrics) put(hn, hnItemId(c.discussion_url), c);
    if (c.source === 'hf-papers') put(papers, paperId(c.discussion_url) || paperId(c.url), c);
    if (c.metrics && 'trending_score' in c.metrics) put(models, hfModelId(c.url), c);
  }
  return { hn, papers, models };
}

const finite = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;

const READERS = {
  // Only the HN threads the snapshot already carries, newest first, at most 40 per request.
  async hn(ix, priority) {
    const ids = [...ix.hn.keys()].sort((a, b) => (priority(b) - priority(a)) || (b - a)).slice(0, 40);
    if (!ids.length) return [];
    const j = await getJSON(`https://hn.algolia.com/api/v1/search?tags=story,(${ids.map(i => 'story_' + i).join(',')})&hitsPerPage=50`);
    if (!Array.isArray(j.hits)) throw new Error('phản hồi không có danh sách bài');
    const out = [];
    for (const h of j.hits) for (const c of ix.hn.get(String(h.objectID)) || []) {
      if (finite(h.points)) out.push({ cov: c, metric: 'points', value: h.points });
      if (finite(h.num_comments)) out.push({ cov: c, metric: 'comments', value: h.num_comments });
    }
    return out;
  },
  async 'hf-papers'(ix) {
    if (!ix.papers.size) return [];
    const j = await getJSON('https://huggingface.co/api/daily_papers?limit=100');
    if (!Array.isArray(j)) throw new Error('phản hồi không phải danh sách');
    const out = [];
    for (const row of j) {
      const p = row && row.paper; if (!p) continue;
      for (const c of ix.papers.get(String(p.id)) || []) {
        if (finite(p.upvotes)) out.push({ cov: c, metric: 'upvotes', value: p.upvotes });
        if (finite(row.numComments)) out.push({ cov: c, metric: 'comments', value: row.numComments });
      }
    }
    return out;
  },
  async 'hf-models'(ix) {
    if (!ix.models.size) return [];
    const j = await getJSON('https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=100');
    if (!Array.isArray(j)) throw new Error('phản hồi không phải danh sách');
    const out = [];
    for (const m of j) for (const c of ix.models.get(String(m.id)) || []) {
      if (finite(m.trendingScore)) out.push({ cov: c, metric: 'trending_score', value: m.trendingScore });
      if (finite(m.likes)) out.push({ cov: c, metric: 'likes', value: m.likes });
    }
    return out;
  },
};

/* getStories(): current snapshot stories. onUpdates(list): apply changed counters. onStatus(map): render states. */
export function startLive({ getStories, priority = () => 0, onUpdates, onStatus }) {
  const state = new Map(LIVE_SOURCES.map(s => [s.id, { ...s, ok: null, at: null, error: null, matched: 0 }]));
  let last = 0, running = false, timer = null;

  async function tick() {
    if (running || document.hidden) return;
    running = true; last = Date.now();
    const ix = indexCoverage(getStories());
    await Promise.all(LIVE_SOURCES.map(async s => {
      const st = state.get(s.id);
      try {
        const ups = await READERS[s.id](ix, priority);
        const changed = ups.filter(u => !u.cov.metrics || u.cov.metrics[u.metric] !== u.value);
        Object.assign(st, { ok: true, at: new Date(), error: null, matched: new Set(ups.map(u => u.cov.id)).size });
        if (changed.length) onUpdates(changed);
      } catch (e) {
        Object.assign(st, { ok: false, at: new Date(), error: e.message });
      }
    }));
    running = false;
    onStatus(state);
  }
  const schedule = () => { clearInterval(timer); timer = setInterval(tick, EVERY_MS); };
  document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - last > EVERY_MS) tick(); });
  onStatus(state);
  tick(); schedule();
  return { state, tick };
}

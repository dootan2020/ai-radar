import fs from 'fs';
import path from 'path';

const STOP = new Set(('the and for with from that this its are was has have will into over after about says said than '
  + 'then what when your their they them how why who now new via').split(' '));

const WORDS = new Map();
function wordsOf(st) {
  if (!WORDS.has(st.id)) {
    WORDS.set(st.id, new Set(
      String(st.title || '')
        .toLowerCase()
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .split(/[^a-z0-9]+/)
        .filter(x => x.length >= 3 && !STOP.has(x))
    ));
  }
  return WORDS.get(st.id);
}

function sameEvent(a, b) {
  const A = wordsOf(a), B = wordsOf(b);
  if (!A.size || !B.size) return false;
  let k = 0;
  A.forEach(x => { if (B.has(x)) k++; });
  return k / (A.size + B.size - k) >= 0.34;
}

const SHORT_NAMES = {
  'github-ai': 'GitHub',
  'github-trending': 'GitHub',
  'techcrunch-ai': 'TechCrunch',
  'ars-technica-ai': 'Ars Technica',
  'the-verge-ai': 'The Verge',
  'lobsters-ai': 'Lobsters',
};

function srcName(id) {
  return SHORT_NAMES[id] || String(id || '').replace(/\s*\(.*?\)\s*/g, ' ').trim();
}

function uniqCoverage(coverage) {
  const best = new Map();
  (coverage || []).forEach((c, i) => {
    if (!c) return;
    const key = String(c.publisher || srcName(c.source) || c.source || i).toLowerCase();
    const score = c.metrics ? Object.values(c.metrics).filter(v => typeof v === 'number' && Number.isFinite(v)).length : 0;
    const prev = best.get(key);
    if (!prev || score > prev.score) best.set(key, { c, i: prev ? prev.i : i, score });
  });
  return [...best.values()].sort((a, b) => a.i - b.i).map(x => x.c);
}

const isNewsCov = c => c && c.source !== 'hn-ai' && c.publisher !== 'hacker-news';
const covsOf = st => uniqCoverage(st.coverage || []);
const newsCovsOf = st => covsOf(st).filter(isNewsCov);
const nNewsSrc = st => newsCovsOf(st).length;
const nSrc = st => covsOf(st).length;

const ms = iso => new Date(iso).getTime() || 0;

function worthOf(st) {
  const meas = st.hot_signals && st.hot_signals.measurement;
  const hot = meas && Number.isFinite(st.hot_score) ? Math.max(0, st.hot_score) : 0;
  const n = nSrc(st);
  const score = typeof st.worth_score === 'number' ? st.worth_score : 0;
  return {
    score,
    parts: st.worth_parts || {},
    hot,
    n,
    evidence: n >= 2 || hot > 0 || !!(st.worth_parts && Object.keys(st.worth_parts).length)
  };
}

const KIND_OF_VIA = {
  'feed-media': 'photo',
  'og:image': 'photo',
  'linked-article': 'photo',
  'youtube': 'photo',
  'github-social': 'graphic',
  'hf-thumbnail': 'graphic',
  'ai': 'photo',
};

export function pickImageKind(st) {
  const img = st?.image;
  if (img && typeof img === 'object' && img.src) {
    return img.kind || KIND_OF_VIA[img.via] || 'photo';
  }
  for (const c of st?.coverage || []) {
    if (!c || typeof c !== 'object') continue;
    for (const m of c.media || []) {
      if (typeof m === 'object') {
        const isImg = m.type === 'image' || String(m.mime_type || '').startsWith('image/');
        if (isImg && String(m.url || '').startsWith('https://')) return 'photo';
      }
    }
  }
  const url = String(st?.url || '');
  if (/https?:\/\/(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/i.test(url)) return 'photo';
  if (/https?:\/\/(?:www\.)?github\.com\/[\w.-]+\/[\w.-]+/i.test(url)) return 'graphic';
  if (/https?:\/\/huggingface\.co\/(?:papers|models|datasets|spaces)\//i.test(url)) return 'graphic';
  return 'cover';
}

export function isTranslatedStory(st) {
  return !!(st && typeof st.title_vi === 'string' && st.title_vi.trim().length > 0);
}

const byWorth = (a, b) => worthOf(b).score - worthOf(a).score || ms(b.published_at) - ms(a.published_at);

export function selectThreeStories(snapshot, options = {}) {
  const allStories = snapshot?.stories || [];
  const editorPicks = options.editorPicks || null;

  const out = [];
  const editorSet = new Set();

  if (Array.isArray(editorPicks)) {
    for (const p of editorPicks) {
      if (out.length >= 3) break;
      const pid = typeof p === 'object' && p !== null ? p.id : String(p);
      const st = allStories.find(s => s && s.id === pid);
      if (st && isTranslatedStory(st) && nNewsSrc(st) >= 2 && !out.some(o => o.id === st.id)) {
        out.push(st);
        editorSet.add(st.id);
      }
    }
  }

  // Follow choosePicks() logic from site/feed.js strictly for translated stories
  const candidates = allStories
    .filter(st => st && !editorSet.has(st.id) && isTranslatedStory(st) && nNewsSrc(st) >= 2 && worthOf(st).evidence)
    .sort(byWorth);

  if (!out.length && candidates.length > 0) {
    const photoLeadIndex = candidates.findIndex(st => pickImageKind(st) === 'photo');
    if (photoLeadIndex >= 0) {
      out.push(candidates.splice(photoLeadIndex, 1)[0]);
    }
  }

  for (const st of candidates) {
    if (out.length >= 3) break;
    if (!out.some(o => sameEvent(o, st))) {
      out.push(st);
    }
  }

  // Fallback if less than 3 (without relaxing translation or news coverage threshold)
  if (out.length < 3) {
    const fallback = allStories
      .filter(st => st && !editorSet.has(st.id) && !out.some(o => o.id === st.id) && isTranslatedStory(st) && nNewsSrc(st) >= 2 && worthOf(st).evidence)
      .sort(byWorth);
    for (const st of fallback) {
      if (out.length >= 3) break;
      if (!out.some(o => sameEvent(o, st))) {
        out.push(st);
      }
    }
  }

  return out.slice(0, 3);
}

export function computeFeedStoryStats(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.stories)) {
    return { storyCount: 0, windowHours: 72, eligibleStories: [] };
  }
  const winH = Number(snapshot.ranking && snapshot.ranking.window_hours);
  const windowHours = (Number.isFinite(winH) && winH > 0) ? winH : 72;
  const gen = ms(snapshot.generated_at);
  const from = gen - windowHours * 36e5;
  const eligibleStories = snapshot.stories.filter(st => {
    const t = ms(st?.published_at);
    return t && t >= from && t <= gen + 3e5;
  });
  return {
    storyCount: eligibleStories.length,
    windowHours,
    eligibleStories,
  };
}

// CLI runner if executed directly
if (process.argv[1] && process.argv[1].endsWith('pick-stories.js')) {
  const args = process.argv.slice(2);
  const jsonMode = args.includes('--json');
  const statsMode = args.includes('--stats');
  const fileArg = args.find(a => !a.startsWith('--'));

  const defaultSample = fs.existsSync(path.resolve('sample/radar-ui.json'))
    ? path.resolve('sample/radar-ui.json')
    : path.resolve('video/sample/radar-ui.json');
  const filePath = fileArg || defaultSample;

  if (!jsonMode && !statsMode) {
    console.log('Reading snapshot from:', filePath);
  }
  const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const picks = selectThreeStories(data);

  if (jsonMode) {
    process.stdout.write(JSON.stringify(picks.map(p => p.id)));
    process.exit(0);
  }

  if (statsMode) {
    const stats = computeFeedStoryStats(data);
    process.stdout.write(JSON.stringify({
      storyCount: stats.storyCount,
      windowHours: stats.windowHours,
      picks: picks.map(p => p.id),
    }));
    process.exit(0);
  }

  if (picks.length < 3) {
    console.log(`\nFound only ${picks.length} eligible translated stories with >= 2 news sources (need 3).`);
  } else {
    console.log(`\nSelected ${picks.length} stories:`);
    picks.forEach((p, idx) => {
      const w = worthOf(p);
      console.log(`\n[${idx + 1}] ID: ${p.id}`);
      console.log(`    Worth score: ${w.score.toFixed(2)} | Sources: ${nNewsSrc(p)} news (${nSrc(p)} total)`);
      console.log(`    Tiêu đề VI: ${p.title_vi || p.title}`);
      console.log(`    Tiêu đề EN: ${p.title}`);
      console.log(`    Tóm tắt: ${p.summary_vi || p.description_vi || p.summary || ''}`);
      console.log(`    Published: ${p.published_at}`);
    });
  }
}


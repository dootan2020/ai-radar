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

const byWorth = (a, b) => worthOf(b).score - worthOf(a).score || ms(b.published_at) - ms(a.published_at);

export function selectThreeStories(snapshot) {
  const allStories = snapshot.stories || [];
  
  // Follow choosePicks() logic from site/feed.js
  // 1. candidates: multi-source (nNewsSrc >= 2) and has evidence
  const candidates = allStories
    .filter(st => nNewsSrc(st) >= 2 && worthOf(st).evidence)
    .sort(byWorth);

  const out = [];

  // Check if any candidate has image
  const photoLeadIndex = candidates.findIndex(st => {
    return !!(st.image || (st.coverage && st.coverage.some(c => c.image)));
  });
  if (photoLeadIndex >= 0) {
    out.push(candidates.splice(photoLeadIndex, 1)[0]);
  }

  for (const st of candidates) {
    if (out.length >= 3) break;
    if (!out.some(o => sameEvent(o, st))) {
      out.push(st);
    }
  }

  // Fallback if less than 3
  if (out.length < 3) {
    const fallback = allStories
      .filter(st => !out.includes(st) && (nNewsSrc(st) >= 2 || nSrc(st) >= 2))
      .sort(byWorth);
    for (const st of fallback) {
      if (out.length >= 3) break;
      if (!out.some(o => sameEvent(o, st))) {
        out.push(st);
      }
    }
  }

  // Final fallback if still less than 3
  if (out.length < 3) {
    const remaining = allStories.filter(st => !out.includes(st)).sort(byWorth);
    for (const st of remaining) {
      if (out.length >= 3) break;
      out.push(st);
    }
  }

  return out.slice(0, 3);
}

// CLI runner if executed directly
if (process.argv[1] && process.argv[1].endsWith('pick-stories.js')) {
  const defaultSample = fs.existsSync(path.resolve('sample/radar-ui.json'))
    ? path.resolve('sample/radar-ui.json')
    : path.resolve('video/sample/radar-ui.json');
  const filePath = process.argv[2] || defaultSample;
  console.log('Reading snapshot from:', filePath);
  const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const picks = selectThreeStories(data);
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

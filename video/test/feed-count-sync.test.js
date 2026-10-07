import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { computeFeedStoryStats, generateFallbackScript } from '../src/daily-audio.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../..');

/**
 * Replicate site/feed.js ingest calculation exactly:
 * winH = Number(D.ranking && D.ranking.window_hours);
 * if (!Number.isFinite(winH) || winH <= 0) winH = 72;
 * const gen = ms(D.generated_at), from = gen - winH * 36e5;
 * allStories = asArray(D.stories).filter(st => { const t = ms(st.published_at); return t && t >= from && t <= gen + 3e5; });
 */
function homePageHeaderCount(snapshot) {
  const winH = Number(snapshot?.ranking && snapshot?.ranking?.window_hours);
  const windowHours = (Number.isFinite(winH) && winH > 0) ? winH : 72;
  const gen = new Date(snapshot.generated_at).getTime() || 0;
  const from = gen - windowHours * 36e5;
  const stories = Array.isArray(snapshot?.stories) ? snapshot.stories : [];
  const allStories = stories.filter(st => {
    const t = new Date(st?.published_at).getTime() || 0;
    return t && t >= from && t <= gen + 3e5;
  });
  return {
    count: allStories.length,
    windowHours,
  };
}

test('video story count strictly matches home page header count on fixture with out-of-window stories', () => {
  const fixturePath = path.resolve(REPO_ROOT, 'tests/fixtures/feed-count-divergence-fixture.json');
  assert.ok(fs.existsSync(fixturePath), `Missing fixture at ${fixturePath}`);

  const snapshot = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

  // 1. Home page header count
  const homeStats = homePageHeaderCount(snapshot);
  assert.equal(homeStats.count, 4, 'Fixture has exactly 4 stories within the 72h window');
  assert.equal(homeStats.windowHours, 72);
  assert.equal(snapshot.stories.length, 8, 'Raw snapshot length must be 8 (diverges from window count)');

  // 2. Video calculation
  const videoStats = computeFeedStoryStats(snapshot);
  assert.equal(
    videoStats.storyCount,
    homeStats.count,
    `Video count (${videoStats.storyCount}) must strictly match home page count (${homeStats.count})`
  );
  assert.equal(videoStats.windowHours, homeStats.windowHours);

  // 3. Fallback script hook
  const script = generateFallbackScript(snapshot, snapshot.stories.slice(0, 3));
  assert.ok(script, 'Fallback script must be generated');
  assert.equal(
    script.hook,
    `Trong ${homeStats.windowHours} giờ qua, ai-radar theo dõi ${homeStats.count} tin AI từ các nguồn công nghệ.`,
    'Spoken hook must honestly reflect the window and the matching story count'
  );

  // 4. Assert divergence check: if video had used raw stories.length (8), it would diverge from home (4)
  assert.notEqual(
    snapshot.stories.length,
    homeStats.count,
    'Fixture must demonstrate divergence between raw snapshot length and home page count'
  );
});

test('video story count strictly matches home page header count on live snapshot', () => {
  const livePath = path.resolve(REPO_ROOT, 'site/data/radar-ui.json');
  if (!fs.existsSync(livePath)) {
    return;
  }

  const snapshot = JSON.parse(fs.readFileSync(livePath, 'utf8'));
  const homeStats = homePageHeaderCount(snapshot);
  const videoStats = computeFeedStoryStats(snapshot);

  assert.equal(
    videoStats.storyCount,
    homeStats.count,
    `Video count (${videoStats.storyCount}) must match live site count (${homeStats.count})`
  );
  assert.equal(videoStats.windowHours, homeStats.windowHours);

  // Verify that raw snapshot stories count diverges from active ranking window count
  assert.notEqual(
    snapshot.stories.length,
    homeStats.count,
    'Live snapshot contains archive stories outside window; video count must not use raw stories.length'
  );

  const script = generateFallbackScript(snapshot);
  if (script) {
    assert.ok(
      script.hook.includes(`${homeStats.count} tin AI`),
      `Fallback hook must state exactly ${homeStats.count} tin AI`
    );
    assert.ok(
      script.hook.includes(`Trong ${homeStats.windowHours} giờ qua`),
      `Fallback hook must state exactly Trong ${homeStats.windowHours} giờ qua`
    );
    assert.ok(
      !script.hook.includes('Hôm nay'),
      'Fallback hook must not state Hôm nay when window is 72h'
    );
  }
});

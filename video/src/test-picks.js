import assert from 'assert';
import fs from 'fs';
import path from 'path';
import { selectThreeStories } from './pick-stories.js';

console.log('[TEST] Starting pick-stories verification suite...');

// Test 1: Real snapshot selection
const samplePath = [
  path.resolve('sample/radar-ui.json'),
  path.resolve('../site/data/radar-ui.json'),
  path.resolve('video/sample/radar-ui.json'),
].find(candidate => fs.existsSync(candidate));
assert.ok(samplePath, 'A local radar-ui.json snapshot is required for story selection tests');
const sampleData = JSON.parse(fs.readFileSync(samplePath, 'utf8'));

const picks = selectThreeStories(sampleData);
assert.strictEqual(picks.length, 3, 'Must select exactly 3 stories');
console.log('✓ Test 1: Exactly 3 stories selected from live snapshot');

// Test 2: Check multi-source coverage
picks.forEach((p, idx) => {
  assert.ok(p.id, `Story ${idx + 1} must have an ID`);
  assert.ok(p.title, `Story ${idx + 1} must have a title`);
  assert.ok(p.coverage && p.coverage.length >= 2, `Story ${idx + 1} must be multi-source (>= 2 sources)`);
});
console.log('✓ Test 2: All 3 picked stories have multi-source coverage');

// Test 3: Check deduplication (no duplicate events)
const ids = new Set(picks.map(p => p.id));
assert.strictEqual(ids.size, 3, 'All 3 story IDs must be distinct');
console.log('✓ Test 3: Deduplication ensures 3 distinct stories');

// Test 4: Check fallback behavior when few stories exist
const mockSnapshot = {
  generated_at: '2026-10-05T12:00:00Z',
  stories: [
    {
      id: 'mock-1',
      title: 'AI model 1 release',
      title_vi: 'Mô hình AI 1 ra mắt',
      worth_score: 10,
      coverage: [{ source: 'src-1' }, { source: 'src-2' }]
    },
    {
      id: 'mock-2',
      title: 'AI model 2 benchmark',
      title_vi: 'Điểm đánh giá mô hình AI 2',
      worth_score: 8,
      coverage: [{ source: 'src-1' }, { source: 'src-3' }]
    },
    {
      id: 'mock-3',
      title: 'AI chip breakthrough',
      title_vi: 'Đột phá chip AI mới',
      worth_score: 6,
      coverage: [{ source: 'src-2' }, { source: 'src-3' }]
    }
  ]
};
const mockPicks = selectThreeStories(mockSnapshot);
assert.strictEqual(mockPicks.length, 3, 'Fallback must return 3 stories from mock snapshot');
assert.strictEqual(mockPicks[0].id, 'mock-1', 'Highest score must be first');
console.log('✓ Test 4: Mock snapshot ranking and fallback verified');

// Test 5: Verify all live picked stories have Vietnamese titles
picks.forEach((p, idx) => {
  assert.ok(p.title_vi && typeof p.title_vi === 'string' && p.title_vi.trim(), `Story ${idx + 1} (${p.id}) must have a non-empty Vietnamese title`);
});
console.log('✓ Test 5: All 3 picked stories have valid Vietnamese titles (title_vi)');

// Test 6: Untranslated top story is skipped in favor of lower-worth translated stories
const snapshotWithUntranslatedTop = {
  generated_at: '2026-10-05T12:00:00Z',
  stories: [
    {
      id: 'untranslated-top',
      title: 'Top story but untranslated',
      title_vi: null,
      worth_score: 99,
      coverage: [{ source: 'src-1' }, { source: 'src-2' }]
    },
    ...mockSnapshot.stories
  ]
};
const picksSkippingUntranslated = selectThreeStories(snapshotWithUntranslatedTop);
assert.strictEqual(picksSkippingUntranslated.length, 3);
assert.ok(!picksSkippingUntranslated.some(p => p.id === 'untranslated-top'), 'Untranslated top story must be skipped');
assert.strictEqual(picksSkippingUntranslated[0].id, 'mock-1');
console.log('✓ Test 6: Untranslated top story is skipped in favor of translated stories');

// Test 7: Fewer than 3 translated stories returns only qualifying stories (no untranslated fallback)
const snapshotWithOnlyTwo = {
  generated_at: '2026-10-05T12:00:00Z',
  stories: [
    mockSnapshot.stories[0],
    mockSnapshot.stories[1],
    {
      id: 'untranslated-filler',
      title: 'Untranslated filler',
      title_vi: '',
      worth_score: 5,
      coverage: [{ source: 'src-1' }, { source: 'src-2' }]
    }
  ]
};
const picksShort = selectThreeStories(snapshotWithOnlyTwo);
assert.strictEqual(picksShort.length, 2, 'Must return only the 2 translated stories');
assert.ok(!picksShort.some(p => p.id === 'untranslated-filler'));
console.log('✓ Test 7: Fewer than 3 translated stories returns only qualifying stories');

console.log('\n[PASS] All 7 tests passed successfully!\n');


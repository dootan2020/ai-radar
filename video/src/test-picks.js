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

console.log('\n[PASS] All 4 tests passed successfully!\n');

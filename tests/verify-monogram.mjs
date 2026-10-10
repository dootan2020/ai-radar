// Monograms take whole letters or digits and skip emoji and symbols. No npm dependencies.
// node tests/verify-monogram.mjs
import assert from 'node:assert/strict';
import { monogram } from '../site/faces.js';

const lone = /[\uD800-\uDFFF]/;
const cases = [
  // A real publisher name from the snapshot that used to render "\uD83DA" (half an emoji, then A).
  ['🚨 AI News | TestingCatalog (@testingcatalog)', 'AN'],
  ['GenK AI', 'GA'],
  ['Lobsters', 'LO'],
  ['simon-willison', 'SW'],
  ['Ethan Mollick trên Bluesky', 'EM'],
  ['Đời sống & Pháp luật', 'ĐS'],
  ['ếch', 'ẾC'],
  ['éch xanh', 'ÉX'],          // decomposed é keeps its accent
  ['🔥🔥', '?'],
  ['', '?'],
  [null, '?'],
  ['42 Labs', '4L'],
];
for (const [name, expected] of cases) {
  const got = monogram(name);
  assert.equal(got, expected, `monogram(${JSON.stringify(name)})`);
  assert.ok(!lone.test(got), `monogram(${JSON.stringify(name)}) holds a lone surrogate`);
}
console.log('PASS monogram skips emoji and symbols and keeps letters whole');

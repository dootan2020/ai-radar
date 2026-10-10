// Long headlines step down in size; short ones keep the display size. No npm dependencies.
// node tests/verify-headline-size.mjs
import assert from 'node:assert/strict';
import { headlineSizeClass, renderStoryHTML } from '../site/story.js';

const of = n => 'a'.repeat(n);
assert.equal(headlineSizeClass(of(70)), 'story-headline');
assert.equal(headlineSizeClass(of(100)), 'story-headline');
assert.equal(headlineSizeClass(of(101)), 'story-headline is-long');
assert.equal(headlineSizeClass(of(180)), 'story-headline is-long');
assert.equal(headlineSizeClass(of(181)), 'story-headline is-post');
assert.equal(headlineSizeClass(''), 'story-headline');
// Counted in characters, not UTF-16 units: 100 emoji are 200 code units but still 100 characters.
assert.equal(headlineSizeClass('🔥'.repeat(100)), 'story-headline');

const post = { id: 'p1', title: of(300), url: 'https://example.com/p', kind: 'social' };
const html = renderStoryHTML(post, new Map(), { isPage: true });
assert.match(html, /<h1 class="story-headline is-post" id="story-modal-title">/);
assert.match(html, /<a class="story-origin-cta"[^>]* title="Đọc bài gốc tại [^"]+">/);
console.log('PASS headline size tiers and one-line source CTA label');

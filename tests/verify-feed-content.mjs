/* Execute production renderers offline; DOM doubles cover only image-error delivery. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {headlineShown} from '../site/titles.js';
import {renderStoryHTML} from '../site/story.js';
import {renderStoryTileHTML} from '../site/ban-tin.js';

async function renderer(file, stop, expose, globals = {}) {
  const url = new URL(`../site/${file}`, import.meta.url);
  let source = (await readFile(url, 'utf8')).split(stop)[0];
  const modules = {};
  for (const m of source.matchAll(/^import \{([^}]+)\} from '([^']+)';$/gm)) {
    modules[m[2]] = await import(new URL(m[2], url));
  }
  source = source.replace(/^import \{([^}]+)\} from '([^']+)';$/gm,
    (_, bindings, path) => `const {${bindings.replace(/\s+as\s+/g, ':')}} = modules[${JSON.stringify(path)}];`)
    .replace(/^export /gm, '');
  return new Function('modules', ...Object.keys(globals), `${source}\n${expose}`)(modules, ...Object.values(globals));
}

const story = {
  id:'screened-story', title:'Full original title with all the evidence.', title_vi:'Tiêu đề đầy đủ có mọi chi tiết.',
  headline:'Short original', headline_vi:'Tiêu đề ngắn', image_screened:true,
  url:'https://publisher.example/story', published_at:'2026-10-09T12:00:00Z', kind:'article',
  coverage:[{source:'publisher', publisher:'Publisher', title:'Full coverage title', title_vi:'Tiêu đề nguồn đầy đủ',
    headline:'Short coverage', headline_vi:'Tin nguồn ngắn', url:'https://publisher.example/coverage', metrics:{points:10}}]
};
assert.equal(headlineShown(story), story.headline_vi);
assert.equal(headlineShown({...story, headline_vi:' '}), story.title_vi);
for (const title_vi of [undefined, '', ' ', story.title]) {
  assert.equal(headlineShown({...story, title_vi}), story.headline, 'stale compact translation is ineligible');
}
assert.equal(headlineShown({title:'Full', title_vi:'Dịch', headline:'Short'}), 'Dịch');
assert.equal(headlineShown({title:'Full', headline:' '}), 'Full');

let errorHandler;
class ImageElement {}
const feed = await renderer('feed.js', '\ninit();', `
return {titleOf, pickImage, renderCard, renderHot, pickRow, watchPictures, mediaHTML,
  configure(stories, images = {}) {
    D = {stories, events:[], sources:[], generated_at:'2026-10-10T00:00:00Z'};
    GEN = Date.parse(D.generated_at); STORY_ANY = new Map(stories.map(s => [s.id, s]));
    PICKED.clear(); WORTHS.clear();
    for (const key of Object.keys(IMG)) delete IMG[key];
    Object.assign(IMG, images);
  }};`, {
  location:{search:''}, matchMedia:() => ({matches:true}), localStorage:{getItem:() => null},
  document:{addEventListener:(type, fn) => { if (type === 'error') errorHandler = fn; }},
  HTMLImageElement:ImageElement,
});
feed.configure([story]);
assert.deepEqual(feed.titleOf(story), {text:story.headline_vi, orig:story.title, cov:null});
const coverageTranslated = {...story, title_vi:undefined};
assert.equal(feed.titleOf(coverageTranslated).text, story.coverage[0].headline_vi);
assert.equal(feed.titleOf(coverageTranslated).orig, story.coverage[0].title);
assert.equal(feed.titleOf(coverageTranslated).cov, story.coverage[0]);
assert.equal(feed.titleOf({...story, title_vi:undefined, coverage:[]}).text, story.headline);

// Each old provider is a real candidate, not merely absent from the input.
const candidates = [
  {url:story.url, images:{[story.url]:{src:'https://rejected.example/seed.jpg'}}},
  {url:'https://publisher.example/other', images:{[story.coverage[0].url]:{src:'https://rejected.example/coverage-seed.jpg'}}},
  {coverage:[{...story.coverage[0], media:[{type:'image', url:'https://rejected.example/media.jpg'}]}]},
  {url:'https://github.com/owner/project'},
  {url:'https://huggingface.co/owner/model'},
  {url:'https://huggingface.co/papers/1234.5678'},
  {url:'https://youtube.com/watch?v=abcdefghijk'},
  {images:{[`ai:${story.id}`]:{src:'https://rejected.example/old-ai.jpg'}}},
  {url:'https://publisher.example/no-image', coverage:[]},
];
for (const candidate of candidates) {
  const item = {...story, ...candidate};
  feed.configure([item], candidate.images);
  assert.equal(feed.pickImage(item).kind, 'none');
  for (const html of [feed.renderCard(item, 'lead'), feed.renderHot([item]), feed.pickRow(item, 2)]) {
    assert.ok(html.includes(story.headline_vi));
    assert.ok(!html.includes('class="media-img"') && !html.includes('class="cover'));
    assert.ok(!html.includes('rejected.example') && !html.includes('<img'), 'screened story cannot borrow imagery');
  }
}

for (const image of [
  {src:'https://approved.example/photo.jpg', via:'og:image', kind:'photo'},
  {src:'assets/ai/story.jpg', via:'ai', kind:'photo'},
]) {
  const item = {...story, image};
  feed.configure([item]);
  assert.equal(feed.pickImage(item).src, image.src);
  const html = feed.renderCard(item, 'lead');
  assert.ok(html.includes(`src="${image.src}"`));
  assert.ok(html.includes('Translated') && html.includes(story.title));
  assert.ok(html.includes(story.headline_vi));
  if (image.via === 'ai') assert.ok(html.includes('Ảnh minh hoạ do AI tạo'));
}

// Previously cached legacy imagery is discarded when a fresh snapshot is configured.
const legacy = {...story, image_screened:false};
feed.configure([legacy], {[story.url]:{src:'https://legacy.example/photo.jpg'}});
assert.equal(feed.pickImage(legacy).src, 'https://legacy.example/photo.jpg');
feed.configure([story]);
assert.equal(feed.pickImage(story).kind, 'none');

feed.watchPictures();
const photoStory = {...story, image:{src:'https://approved.example/broken.jpg', via:'og:image'}};
feed.configure([photoStory]);
let removed = false, coverWritten = false, photoRemoved = false;
const body = {className:'photo-body'};
const card = {dataset:{id:story.id}, classList:{contains:() => true, remove:() => { photoRemoved = true; }}, querySelector:() => body};
const image = new ImageElement();
image.classList = {contains:cls => cls === 'media-img'};
image.closest = selector => selector === '.feed-card' ? card : null;
image.parentElement = {remove:() => { removed = true; }, set innerHTML(value) { coverWritten = true; }};
errorHandler({target:image});
assert.ok(removed && photoRemoved && !coverWritten);
assert.equal(body.className, 'card-body');
assert.equal(card.dataset.via, 'none');
assert.equal(feed.pickImage(photoStory).kind, 'none', 'rerender must not resurrect a failed approved picture');
const thumb = {dataset:{id:story.id}, innerHTML:'old image'};
image.classList = {contains:() => false};
image.closest = selector => selector === '.thumb' ? thumb : null;
errorHandler({target:image});
assert.equal(thumb.innerHTML, '');

for (const options of [{isModal:true}, {isPage:true}]) {
  const html = renderStoryHTML(story, new Map(), options);
  assert.ok(html.includes(`id="story-modal-title">${story.title_vi}</h1>`));
  assert.ok(html.includes(story.title) && html.includes('Translated'));
  assert.ok(!html.includes('class="story-media-img"'));
  const ai = renderStoryHTML({...story, image:{src:'assets/ai/story.jpg', via:'ai'}}, new Map(), options);
  assert.ok(ai.includes(new URL('../site/assets/ai/story.jpg', import.meta.url).href));
  assert.ok(ai.includes('Ảnh minh hoạ do AI tạo'));
}
const edition = renderStoryTileHTML(story);
assert.ok(edition.includes(story.headline_vi) && edition.includes(story.title) && edition.includes('Translated'));
const search = await renderer('tra-cuu.js', '// Tự động chạy khi DOM sẵn sàng',
  'return {renderHeroTile, renderStoryCard, groupStories};');
const group = {primary:story, publishers:new Set(['Publisher']), sourceCount:1, latestDate:story.published_at, rows:[story]};
for (const html of [search.renderHeroTile(group), search.renderStoryCard(group)]) {
  assert.ok(html.includes(story.headline_vi) && html.includes(story.title) && html.includes('Translated'));
}
console.log('PASS headline eligibility, coverage attribution, feed/ranked cards, image providers and errors, modal/page, edition and search renderers');

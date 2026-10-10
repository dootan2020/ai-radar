/* Execute production renderers and notification behavior offline with controlled browser boundaries. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {headlineShown} from '../site/titles.js';
import {renderStoryHTML} from '../site/story.js';
import {renderStoryTileHTML} from '../site/ban-tin.js';
import {buildIcs, canCalendar, gcalURL, dateStart} from '../site/calendar.js';

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
return {titleOf, pickImage, renderCard, renderHot, pickRow, watchPictures, mediaHTML, oneEvent,
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
// Unillustrated stories describe their existing category, never advertise a raw host.
for (const [kind, label] of [['research', 'Nghiên cứu'], ['product', 'Sản phẩm'], ['unknown', 'Bài viết']]) {
  const item = {...story, id:`cover-${kind}`, kind, url:'https://aws.amazon.com/blogs/machine-learning/example', coverage:[]};
  feed.configure([item]);
  const cover = feed.pickImage(item).cover;
  assert.equal(cover.word, label);
  assert.equal(cover.num, null, 'a category cover does not invent a measurement');
  assert.ok(!feed.mediaHTML(feed.pickImage(item), 'std').includes('aws.amazon.com'));
}
feed.configure([story]);
assert.equal(feed.pickImage(story).cover.num, null, "another item's counter is not the card's measurement");
const measured = {...story, id:'measured-story', coverage:[{...story.coverage[0], url:story.url}]};
feed.configure([measured]);
assert.equal(feed.pickImage(measured).cover.num, '10', 'real measured evidence keeps precedence over the category');

// A number on a card measures the page the card links to. A cluster's other items (a social post quoting the article,
// another outlet's piece, a forum thread about a different link) keep their counters to the detail panel.
{
  const lead = {source:'outlet-a', publisher:'outlet-a', title:'Lead article', url:'https://outlet-a.example/lead', metrics:{}};
  const post = {id:'post-1', source:'social-b', publisher:'social-b', title:'A post quoting it',
    url:'https://social-b.example/post/1', metrics:{likes:99, reposts:15}};
  const thread = {id:'thread-1', source:'forum-c', publisher:'forum-c', title:'Lead article',
    url:'https://outlet-a.example/lead/', discussion_url:'https://forum-c.example/item/1', metrics:{points:47}};
  const other = {...thread, id:'thread-2', url:'https://outlet-d.example/other', metrics:{points:61}};
  const base = {id:'cluster', title:'Lead article', url:lead.url, published_at:'2026-10-09T12:00:00Z', kind:'article', image_screened:true, source_count:2};
  const numbers = item => [item.id, feed.pickImage(item).cover, ['std', 'lead', 'wide'].map(size => feed.renderCard(item, size)).join('')
    + feed.renderCard(item, 'lead', {rank:1, why:true, h:'h3'}) + feed.renderHot([item])];
  const borrowed = {...base, coverage:[lead, post]};
  const pipeBorrowed = {...base, id:'cluster-pipe', coverage:[lead, other],
    hot_signals:{measurement:{source:'forum-c', metric:'points', value:61}}};
  for (const item of [borrowed, pipeBorrowed]) {
    feed.configure([item]);
    const [id, cover, html] = numbers(item);
    assert.notEqual(cover.num, '99', `${id}: cover borrows a social post's likes`);
    assert.notEqual(cover.num, '61', `${id}: cover borrows a thread about another link`);
    assert.equal(cover.num, '2', `${id}: cover falls back to the independent source count`);
    assert.ok(!/>(99|61)</.test(html), `${id}: card, why line or hot row shows another item's number`);
  }
  const ownThread = {...base, id:'cluster-own', coverage:[lead, thread, post],
    hot_signals:{measurement:{source:'forum-c', metric:'points', value:47}}};
  feed.configure([ownThread]);
  assert.equal(feed.pickImage(ownThread).cover.num, '47', 'a forum thread about the same link (trailing slash aside) is shown');
  assert.match(feed.pickImage(ownThread).cover.word, / trên forum-c$/, 'the forum is named with its number');
  assert.match(feed.renderCard(ownThread, 'std'), /data-live="thread-1\|points">47</);
  // The same forum with a thread on each link: the measurement taken from the other link's thread is not printed
  // under this card's thread id; this card shows its own thread's number.
  const twoThreads = {...base, id:'cluster-two', coverage:[lead, other, thread],
    hot_signals:{measurement:{source:'forum-c', metric:'points', value:61}}};
  feed.configure([twoThreads]);
  assert.equal(feed.pickImage(twoThreads).cover.num, '47');
  assert.ok(!/>61</.test(feed.renderCard(twoThreads, 'std')), "the other thread's points are not shown");
  // When the headline comes from a coverage item, the card links there, and that item's own counter is the one shown.
  const fromPost = {...base, id:'cluster-post', title_vi:undefined, coverage:[lead, {...post, title_vi:'Bài đăng đã dịch'}]};
  feed.configure([fromPost]);
  assert.equal(feed.pickImage(fromPost).cover.num, '99', "the linked item's own counter is shown");
}
const coverageTranslated = {...story, title_vi:undefined};
assert.equal(feed.titleOf(coverageTranslated).text, story.coverage[0].headline_vi);
assert.equal(feed.titleOf(coverageTranslated).orig, story.coverage[0].title);
assert.equal(feed.titleOf(coverageTranslated).cov, story.coverage[0]);
assert.equal(feed.titleOf({...story, title_vi:undefined, coverage:[]}).text, story.headline);

// Feed variants carry accessible attribution; complete originals belong to the reading view.
const longOriginal = {...story, title:'A long original with evidence and context. '.repeat(30).trim()};
const feedVariants = item => [
  ...['std', 'lead', 'wide'].map(size => feed.renderCard(item, size)),
  feed.renderCard(item, 'std', {debate:true}),
  feed.renderCard(item, 'lead', {rank:1, why:true, h:'h3'}),
  feed.renderHot([item]), feed.pickRow(item, 2),
];
// Generated article summaries belong only to reader views, including any retired fields.
const summaryOnly = {...story, key_points_prompt_version:'summary-vi-5-full',
  editorial_headline_vi:'SUMMARY_HEADLINE_SENTINEL',
  key_points:Array.from({length:4}, (_, i) => `SUMMARY_POINT_SENTINEL_${i}`),
  short_vi:'SUMMARY_SHORT_SENTINEL', takeaway_vi:'SUMMARY_TAKEAWAY_SENTINEL',
  summary_sources:[{name:'SUMMARY_SOURCE_SENTINEL', role:'outlet', url:'https://summary.example/source'}]};
feed.configure([summaryOnly]);
for (const html of [...feedVariants(summaryOnly), renderStoryTileHTML(summaryOnly, true)]) {
  assert.doesNotMatch(html, /SUMMARY_\w+_SENTINEL|summary\.example/);
}
for (const translated of [longOriginal, coverageTranslated]) {
  for (const image of [undefined, {src:'https://approved.example/photo.jpg', via:'og:image', kind:'photo'}]) {
    const item = {...translated, image};
    feed.configure([item]);
    for (const html of feedVariants(item)) {
      assert.equal((html.match(/>Translated<\/span>/g) || []).length, 1);
      assert.match(html, /<span class="sr" lang="vi">Bản dịch máy\. <\/span>/);
      assert.match(html, /(?:class="src-row"|class="hot-why")[\s\S]*?class="mt"/);
      assert.doesNotMatch(html, /card-orig|orig-text/);
      assert.ok(!html.includes(feed.titleOf(item).orig), 'feed does not print the original title');
      assert.ok(html.includes(feed.titleOf(item).text), 'translated headline remains present');
    }
  }
}
for (const title_vi of [undefined, '', ' ', story.title]) {
  const item = {...story, title_vi, coverage:[]};
  feed.configure([item]);
  for (const html of feedVariants(item)) {
    assert.ok(html.includes(story.headline), 'untranslated headline remains readable');
    assert.doesNotMatch(html, /Translated|Bản dịch máy|card-orig|orig-text/);
  }
}
for (const options of [{isModal:true}, {isPage:true}]) {
  const html = renderStoryHTML(longOriginal, new Map(), options);
  assert.ok(html.includes(`<span class="orig-text" lang="en">${longOriginal.title}</span>`),
    'story views retain the complete original');
  assert.match(html, /<span class="sr" lang="vi">Bản dịch máy\. Tiêu đề gốc: <\/span>/);
  assert.ok(html.includes('>Translated</span>'));
}

// Each old provider is a real candidate, not merely absent from the input.
const candidates = [
  {url:story.url, images:{[story.url]:{src:'https://rejected.example/seed.jpg'}}},
  {url:'https://publisher.example/other', images:{[story.coverage[0].url]:{src:'https://rejected.example/coverage-seed.jpg'}}},
  {coverage:[{...story.coverage[0], media:[{type:'image', url:'https://rejected.example/media.jpg'}]}]},
  {url:'https://github.com/owner/project'},
  {url:'https://huggingface.co/owner/model'},
  {url:'https://huggingface.co/datasets/owner/data'},
  {url:'https://huggingface.co/spaces/owner/demo'},
  {url:'https://huggingface.co/papers/1234.5678'},
  {url:'https://youtube.com/watch?v=abcdefghijk'},
  {images:{[`ai:${story.id}`]:{src:'https://rejected.example/old-ai.jpg'}}},
  {url:'https://publisher.example/no-image', coverage:[]},
];
const cardRenders = item => ['lead', 'wide', 'std'].map(size => feed.renderCard(item, size));
const rankedRenders = item => [feed.renderHot([item]), feed.pickRow(item, 2)];
for (const candidate of candidates) {
  const item = {...story, ...candidate};
  feed.configure([item], candidate.images);
  assert.equal(feed.pickImage(item).kind, 'cover');
  assert.equal(feed.pickImage(item).src, null);
  for (const html of [...cardRenders(item), ...rankedRenders(item)]) {
    assert.ok(html.includes(story.headline_vi));
    assert.ok(html.includes('class="cover'), 'screened absence uses the factual cover');
    assert.ok(!html.includes('rejected.example') && !html.includes('<img'), 'screened story cannot borrow imagery');
  }
  // The same candidates remain available to unscreened archives.
  const legacy = {...item, image_screened:false};
  feed.configure([legacy], candidate.images);
  assert.equal(feed.pickImage(legacy).kind === 'cover', candidate.coverage?.length === 0);
}

for (const image of [null, {}, {src:''}]) {
  const item = {...story, image};
  feed.configure([item]);
  assert.equal(feed.pickImage(item).kind, 'cover', 'empty approved image uses the factual cover');
}

for (const image of [
  {src:'https://approved.example/photo.jpg', via:'og:image', kind:'photo'},
  {src:'assets/ai/story.jpg', via:'ai', kind:'photo'},
]) {
  const item = {...story, image};
  feed.configure([item], {[story.url]:{src:'https://rejected.example/seed.jpg'}});
  assert.equal(feed.pickImage(item).src, image.src);
  for (const html of [...cardRenders(item), ...rankedRenders(item)]) {
    assert.ok(html.includes(`src="${image.src}"`));
    assert.ok(!html.includes('class="cover') && !html.includes('rejected.example'));
  }
  const html = feed.renderCard(item, 'lead');
  assert.ok(html.includes(`src="${image.src}"`));
  assert.ok(html.includes('Translated') && !html.includes(story.title));
  assert.ok(html.includes(story.headline_vi));
  if (image.via === 'ai') assert.ok(html.includes('Ảnh minh hoạ do AI tạo'));
}

// Previously cached legacy imagery is discarded when a fresh snapshot is configured.
const legacy = {...story, image_screened:false};
feed.configure([legacy], {[story.url]:{src:'https://legacy.example/photo.jpg'}});
assert.equal(feed.pickImage(legacy).src, 'https://legacy.example/photo.jpg');
feed.configure([story]);
assert.equal(feed.pickImage(story).kind, 'cover');

feed.watchPictures();
for (const image_screened of [true, false]) for (const via of ['og:image', 'ai']) {
  const photoStory = {...story, image_screened, image:{src:'https://approved.example/broken.jpg', via}};
  feed.configure([photoStory], {[story.url]:{src:'https://rejected.example/seed.jpg'}});
  assert.equal(feed.pickImage(photoStory).src, photoStory.image.src);
  let removed = false, photoRemoved = false;
  const body = {className:'photo-body'};
  const card = {dataset:{id:story.id}, classList:{contains:() => true, remove:() => { photoRemoved = true; }}, querySelector:() => body};
  const image = new ImageElement();
  image.classList = {contains:cls => cls === 'media-img'};
  image.closest = selector => selector === '.feed-card' ? card : null;
  image.parentElement = {remove:() => { removed = true; }, innerHTML:'old image and badge'};
  errorHandler({target:image});
  assert.ok(!removed && photoRemoved);
  assert.ok(image.parentElement.innerHTML.includes('class="cover"'));
  assert.ok(!image.parentElement.innerHTML.includes('<img') && !image.parentElement.innerHTML.includes('ai-badge'));
  assert.equal(body.className, 'card-body');
  assert.equal(card.dataset.via, 'cover');
  assert.equal(feed.pickImage(photoStory).kind, 'cover', 'rerender must not resurrect a failed approved picture');
  for (const html of [...cardRenders(photoStory), ...rankedRenders(photoStory)]) {
    assert.ok(html.includes('class="cover') && !html.includes(photoStory.image.src) && !html.includes('rejected.example'));
  }

  // Exercise thumbnail failure independently, before any card has failed.
  feed.configure([photoStory]);
  assert.equal(feed.pickImage(photoStory).src, photoStory.image.src);
  const thumb = {dataset:{id:story.id}, innerHTML:'old image'};
  image.classList = {contains:() => false};
  image.closest = selector => selector === '.thumb' ? thumb : null;
  errorHandler({target:image});
  assert.ok(thumb.innerHTML.includes('class="cover is-mini"'));
  assert.equal(feed.pickImage(photoStory).kind, image_screened ? 'cover' : 'photo');
  if (image_screened) for (const html of [...cardRenders(photoStory), ...rankedRenders(photoStory)]) {
    assert.ok(html.includes('class="cover') && !html.includes(photoStory.image.src));
  }
}

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
// One event, told once on the first screen: the pipeline's identity, a shared address, or the cluster's own wording.
const ev = (id, title, coverage = [], extra = {}) => ({id, title, url:`https://x.example/${id}`, coverage, ...extra});
const bbc = ev('bbc', 'Rogue Anthropic AI agent gave police fake tip in unsolved murder case');
const tc = ev('tc', 'An Anthropic AI model sent a false homicide tip to Philadelphia police', [
  {title:'An Anthropic AI model sent a false homicide tip to Philadelphia police', url:'https://techcrunch.example/a'},
  {title:'Rogue AI agent gave police a fake tip in an unsolved murder, Anthropic says', url:'https://verge.example/b'}]);
assert.equal(feed.oneEvent(bbc, tc), true, "one event across the cluster's coverage headlines");
assert.equal(feed.oneEvent(ev('a', 'Alpha'), ev('b', 'Beta', [], {aliases:['a']})), true, 'merged clusters (aliases)');
assert.equal(feed.oneEvent(ev('a', 'Alpha', [{url:'https://same.example/x'}]), ev('b', 'Beta', [{discussion_url:'https://same.example/x'}])), true, 'a shared address');
assert.equal(feed.oneEvent(bbc, ev('diary', 'Anthropic reported diary entry to police, woman faces felony charge')), false,
  'two Anthropic police stories are not one event');
console.log('PASS headline eligibility, coverage attribution, feed/ranked cards, image providers and errors, modal/page, edition and search renderers');

// Execute the real notification state, navigation and poll against deterministic DOM/time/network boundaries.
const nodes = new Map(), timers = new Map(), jumps = [];
const home = await readFile(new URL('../site/index.html', import.meta.url), 'utf8');
const chips = [...home.matchAll(/<button class="filter-chip" data-filter="([^"]+)"[^>]*>([^<]+)<\/button>/g)]
  .map(([, filter, label]) => ({dataset:{filter}, textContent:label, innerHTML:label, hidden:false,
    attributes:{}, setAttribute(key, value) { this.attributes[key] = value; }}));
let timerId = 0, announcements = 0, visibleStories = [], responseData;
const navLocation = {pathname:'/index.html', search:'', hash:'#moi'};
const replacedURLs = [];
const doc = {activeElement:null, hidden:false, documentElement:{style:{setProperty() {}}},
  querySelector:selector => nodes.get(selector),
  querySelectorAll:selector => selector === '.filter-chip' ? chips : selector.includes('[data-sid]') ? visibleStories : [],
};
for (const selector of ['#fresh', '#fresh-text', '#fresh-announcement', '#bar', '#top', '#filter-context', '#src-update', '#src-note', '#src-list', '#src-live', '#src-foot', '#nguon']) {
  nodes.set(selector, {hidden:true, textContent:'', innerHTML:'', style:{}, dataset:{}, offsetHeight:64,
    getBoundingClientRect:() => ({bottom:64}), contains:el => el === nodes.get('#fresh-go'),
    matches:() => false, focus() { doc.activeElement = this; }});
}
nodes.set('#fresh-go', {});
Object.defineProperty(nodes.get('#fresh-announcement'), 'textContent', {
  set(value) { if (value) announcements++; },
});
const newFeed = await renderer('feed.js', '\ninit();', `
return {renderNewItems, offerNewItems, dismissNewItems, scheduleNewItemsDismissal, checkNewItemsScroll,
  goFirstNew, route, setFilter, pollSnapshot, pendingNewIds, renderSub, renderChips, renderSources, markHTML, markRead,
  configure(count, total, first = false) {
    D = {schema_version:2, generated_at:'2026-10-09T14:00:00Z', sources:[], stories:[]};
    allStories = Array.from({length:total}, (_, i) => ({id:'item-'+i,
      published_at:i < count ? '2026-10-09T13:00:00Z' : '2026-10-08T10:00:00Z'}));
    D.stories = allStories;
    STORY_ANY = new Map(allStories.map(st => [st.id, st]));
    firstVisit = first; lastSeen = '2026-10-09T12:00:00Z'; returnNoticeChecked = false;
    read.clear(); skipped.clear(); arrived.clear(); offeredNewIds.clear(); noticeIds.clear();
    pending = null; filter = 'all'; noticeDeferred = false;
  },
  filter(value) { filter = value; },
  save(items) { saved = items; },
  sourceTime(iso) { D.generated_at = iso; renderSources(); },
  skip(id) { skipped.add(id); },
  seen(id) { read.add(id); },
  renderNavigation() { renderAll = () => {}; },
  noNewsArena(show) { D = null; arenaView = {show}; },
};`, {
  location:navLocation, history:{replaceState:(_state, _title, url) => replacedURLs.push(url)}, document:doc, matchMedia:() => ({matches:true}),
  localStorage:{getItem:() => null, setItem:() => {}},
  window:{scrollTo:options => jumps.push(options)}, scrollY:100,
  setTimeout:(fn, ms) => { const id = ++timerId; timers.set(id, {fn, ms}); return id; },
  clearTimeout:id => timers.delete(id),
  fetch:async () => { if (responseData instanceof Error) throw responseData; return {ok:true, json:async () => responseData}; },
});
function configureNotice(count, total, first = false) {
  newFeed.configure(count, total, first);
  newFeed.renderChips();
  nodes.get('#fresh').hidden = true;
  doc.activeElement = null; visibleStories = []; timers.clear(); announcements = 0;
}
for (const [count, total, first] of [[0, 100, false], [3, 100, true], [21, 100, false], [3, 6, false], [95, 100, false]]) {
  configureNotice(count, total, first); newFeed.renderNewItems();
  assert.equal(nodes.get('#fresh').hidden, true, 'first visits, large counts and most-of-feed returns stay quiet');
}
configureNotice(20, 100); newFeed.renderNewItems();
assert.equal(nodes.get('#fresh').hidden, false);
assert.equal(nodes.get('#fresh-text').textContent, '20 tin mới');
assert.equal(announcements, 1);
newFeed.renderNewItems(); newFeed.offerNewItems(['item-0']);
assert.equal(announcements, 1, 'redraw and identical candidates do not announce again');
assert.deepEqual([...timers.values()].map(t => t.ms), [12000]);
[...timers.values()][0].fn();
assert.equal(nodes.get('#fresh').hidden, true);
newFeed.offerNewItems(['item-0']);
assert.equal(nodes.get('#fresh').hidden, true, 'expired candidates stay dismissed');
newFeed.offerNewItems(['item-0', 'later-arrival']);
assert.equal(nodes.get('#fresh-text').textContent, '1 tin mới', 'a later batch does not revive dismissed candidates');
assert.equal(announcements, 2, 'a genuinely new appearance gets one announcement');

configureNotice(1, 10); newFeed.renderNewItems();
nodes.get('#fresh').matches = () => true; newFeed.scheduleNewItemsDismissal();
assert.equal(timers.size, 0, 'hover pauses automatic expiry');
nodes.get('#fresh').matches = () => false; newFeed.scheduleNewItemsDismissal();
assert.equal(timers.size, 1, 'leaving the pill resumes expiry');
newFeed.markRead('item-0');
assert.equal(nodes.get('#fresh').hidden, true, 'opening the final new story retires the notice');
assert.match(newFeed.markHTML({id:'item-0'}), /seen-mark/);

configureNotice(2, 10); newFeed.renderNewItems();
doc.activeElement = nodes.get('#fresh-go'); newFeed.dismissNewItems();
assert.equal(nodes.get('#fresh').hidden, false, 'automatic dismissal preserves keyboard focus');
doc.activeElement = null; newFeed.scheduleNewItemsDismissal();
assert.equal(nodes.get('#fresh').hidden, true, 'deferred dismissal runs after focus leaves');

const card = (id, bottom = 50) => ({dataset:{sid:id}, closest:() => null,
  getBoundingClientRect:() => ({top:200, bottom}), matches:() => true,
  focus() { doc.activeElement = this; }});
configureNotice(2, 10); newFeed.renderNewItems();
visibleStories = [card('item-0')]; newFeed.checkNewItemsScroll();
assert.equal(nodes.get('#fresh-text').textContent, '1 tin mới');
assert.equal(nodes.get('#fresh').hidden, false, 'an unrendered new story is not considered passed');
visibleStories.push(card('item-1')); newFeed.checkNewItemsScroll();
assert.equal(nodes.get('#fresh').hidden, true);

configureNotice(1, 10); newFeed.renderNewItems();
visibleStories = [card('item-0', 500)]; doc.activeElement = nodes.get('#fresh-go');
newFeed.route();
assert.equal(doc.activeElement, visibleStories[0], '#moi focuses the first new story');
assert.equal(jumps.at(-1).top, 220);
assert.equal(jumps.at(-1).behavior, 'auto', 'reduced motion is respected');
assert.equal(nodes.get('#fresh').hidden, true);

// With the home's "Vừa đăng" row in place, the pill leads to the top of the page: the announced batch first, the
// heading focused, no smooth scroll under reduced motion.
const rowItems = [];
nodes.set('#fresh-row', {hidden:true, contains:el => el === nodes.get('#fresh-row-h'),
  get innerHTML() { return rowItems.at(-1) || ''; }, set innerHTML(v) { rowItems.push(v); }});
nodes.set('#fresh-row-h', {focus() { doc.activeElement = this; }});
nodes.get('#top').querySelectorAll = () => [];
configureNotice(2, 10); newFeed.renderNewItems();
visibleStories = [card('item-1', 500)]; doc.activeElement = nodes.get('#fresh-go');
newFeed.route();
assert.equal(doc.activeElement, nodes.get('#fresh-row-h'), '#moi focuses the "Vừa đăng" heading');
assert.deepEqual(jumps.at(-1), {top:0, behavior:'auto'}, 'the row is at the top; reduced motion jumps');
assert.equal(nodes.get('#fresh-row').hidden, false);
const rowIds = [...rowItems.at(-1).matchAll(/<li[^>]*data-sid="([^"]+)"/g)].map(m => m[1]);
assert.deepEqual(rowIds.slice(0, 2).sort(), ['item-0', 'item-1'], 'the announced stories lead the row');
assert.match(rowItems.at(-1), /new-mark/, 'arrivals carry the new dot, not pill text');
assert.equal(nodes.get('#fresh').hidden, true);

configureNotice(0, 10, true); newFeed.renderNavigation();
responseData = {schema_version:2, generated_at:'2026-10-09T15:00:00Z', sources:[],
  stories:[{id:'live-new', published_at:'2026-10-09T14:30:00Z', coverage:[]}]};
await newFeed.pollSnapshot();
assert.equal(nodes.get('#fresh-text').textContent, '1 tin mới', 'live arrivals qualify on a first visit');
assert.equal(announcements, 1);
await newFeed.pollSnapshot(); assert.equal(announcements, 1, 'same snapshot is silent');
responseData = {...responseData, generated_at:'2026-10-09T15:01:00Z'};
await newFeed.pollSnapshot(); assert.equal(announcements, 1, 'a metrics-only update does not repeat the announcement');
visibleStories = [card('live-new', 500)];
newFeed.goFirstNew();
assert.equal(doc.activeElement, nodes.get('#fresh-row-h'), 'pending snapshot is applied and its arrivals shown at the top');
assert.match(rowItems.at(-1), /data-sid="live-new"/);
assert.equal(nodes.get('#fresh').hidden, true);
assert.match(newFeed.markHTML({id:'live-new'}), /new-mark/);
newFeed.skip('live-new'); assert.doesNotMatch(newFeed.markHTML({id:'live-new'}), /new-mark|skipped-mark/);
newFeed.seen('live-new'); assert.match(newFeed.markHTML({id:'live-new'}), /seen-mark/);

configureNotice(0, 10);
responseData = {schema_version:2, generated_at:'2026-10-09T15:00:00Z', sources:[],
  stories:[{id:'old-backfill', published_at:'2026-09-01T00:00:00Z'}]};
await newFeed.pollSnapshot(); assert.equal(nodes.get('#fresh').hidden, true, 'old backfills do not claim new arrivals');
responseData = new Error('offline');
await newFeed.pollSnapshot(); assert.equal(nodes.get('#fresh').hidden, true, 'failed polls preserve the feed');
newFeed.renderSub(); assert.equal(nodes.get('#filter-context').hidden, true);
newFeed.filter('saved'); newFeed.renderSub();
assert.equal(nodes.get('#filter-context').hidden, false);
assert.match(nodes.get('#filter-context').innerHTML, /Đã lưu.*Bỏ lọc/);
newFeed.filter('all'); newFeed.renderSub();
assert.equal(nodes.get('#filter-context').hidden, true);
for (const total of [0, 1, 88, 999]) {
  configureNotice(0, total);
  newFeed.renderChips();
  assert.deepEqual(chips.map(b => b.innerHTML), ['Tất cả', 'Chuyện lớn', 'Đang nóng', 'Sản phẩm', 'Thảo luận', 'Mã và mô hình', 'Xếp hạng', 'Đã lưu']);
  assert.equal(chips[0].hidden, false, 'all remains available even with no stories');
  assert.equal(chips.find(b => b.dataset.filter === 'saved').hidden, true, 'empty saved tab stays hidden');
}
newFeed.filter('saved'); newFeed.renderChips();
const savedChip = chips.find(b => b.dataset.filter === 'saved');
assert.equal(savedChip.hidden, false, 'active empty tab remains available');
assert.equal(savedChip.attributes['aria-pressed'], 'true');
newFeed.save([{key:'item-0'}]); newFeed.filter('all'); newFeed.renderChips();
assert.equal(savedChip.hidden, false, 'saving reveals the named tab without a count');
assert.equal(savedChip.innerHTML, 'Đã lưu');
newFeed.filter('saved'); newFeed.renderSub();
assert.match(nodes.get('#filter-context').innerHTML, /Đã lưu.*<span class="num">1<\/span> mục.*Bỏ lọc/);
for (const [iso, wording] of [
  [new Date().toISOString(), null],
  ['2026-10-09T02:00:00Z', '09:00 ngày 9/10/2026'],
  ['2025-12-31T18:30:00Z', '01:30 ngày 1/1/2026'],
]) {
  newFeed.sourceTime(iso);
  const html = nodes.get('#src-update').innerHTML;
  assert.ok(html.includes(`datetime="${iso}"`));
  assert.match(html, /Cập nhật lúc.*\d{2}:\d{2} ngày \d{1,2}\/\d{1,2}\/\d{4}.*nguồn/);
  if (wording) assert.ok(html.includes(wording), 'old snapshots retain their full Vietnam date');
}
console.log('PASS new-story eligibility, expiry, focus, scroll, deep link, live polling, marks, filters and metadata');

// Arena deep links and navigation work even when the news request has failed.
for (const id of ['arena', 'feed-grid', 'feed-footer', 'sort-switch', 'picks', 'feed-empty', 'feed-more', 'feed-end']) {
  nodes.set('#' + id, {hidden:false});
}
nodes.get('#top').removeAttribute = () => {};
nodes.get('#top').getBoundingClientRect = () => ({top:0});
let arenaShows = 0;
newFeed.noNewsArena(() => arenaShows++);
navLocation.hash = '#xep-hang';
newFeed.route();
assert.equal(arenaShows, 1);
assert.equal(nodes.get('#arena').hidden, false);
for (const id of ['feed-grid', 'feed-footer', 'sort-switch', 'picks', 'feed-empty', 'feed-more', 'feed-end', 'filter-context']) {
  assert.equal(nodes.get('#' + id).hidden, true, id);
}
assert.equal(chips.find(b => b.dataset.filter === 'rankings').attributes['aria-pressed'], 'true');
newFeed.setFilter('all');
assert.equal(nodes.get('#arena').hidden, true);
assert.equal(nodes.get('#feed-empty').hidden, false);
assert.equal(replacedURLs.at(-1), '/index.html');
navLocation.search = '?data=data/reader.json';
newFeed.setFilter('rankings');
assert.equal(replacedURLs.at(-1), '/index.html?data=data/reader.json#xep-hang');
assert.equal(chips.find(b => b.dataset.filter === 'rankings').hidden, false);
console.log('PASS Arena deep link, named tab, URL persistence and independence from failed news');

// Event clocks and calendar exports use verified local dates, independent of the host timezone.
const curatedEvents = JSON.parse(await readFile(new URL('../data/events.json', import.meta.url), 'utf8'));
let eventNow = Date.parse('2026-10-10T12:00:00Z');
class EventClock extends Date {
  constructor(...args) { super(...(args.length ? args : [eventNow])); }
  static now() { return eventNow; }
}
const eventMotion = {matches:false, addEventListener() {}};
const eventTimers = new Map();
let eventTimerId = 0;
const eventNode = {dataset:{}, firstElementChild:{textContent:''}, lastElementChild:{dataset:{}, innerHTML:''}};
const eventDocument = {
  hidden:false,
  documentElement:{classList:{add() {}, remove() {}}},
  querySelector:() => eventNode,
  querySelectorAll:() => [eventNode],
};
const eventFeed = await renderer('feed.js', '\ninit();', `
return {eventSpan, eventWhen, eventCal, calOf, countdownParts, countdownHTML, scheduleCountdown,
  render(events, stories = []) { D = {events, stories, live:[]}; return renderLive(); }};`, {
  location:{search:''}, matchMedia:() => eventMotion, localStorage:{getItem:() => null},
  Date:EventClock, document:eventDocument,
  setTimeout:(fn, ms) => { const id = ++eventTimerId; eventTimers.set(id, {fn, ms}); return id; },
  clearTimeout:id => eventTimers.delete(id),
});
const [bengaluru, sydney] = curatedEvents;
for (const [row, start, end] of [
  [bengaluru, '2026-10-16T08:30:00Z', '2026-10-16T18:30:00Z'],
  [sydney, '2026-12-05T13:00:00Z', '2026-12-12T13:00:00Z'],
]) {
  const span = eventFeed.eventSpan(row);
  assert.deepEqual(span, {start:Date.parse(start), end:Date.parse(end)});
  for (const [now, state] of [[span.start - 1, 'soon'], [span.start, 'on'], [span.end - 1, 'on'], [span.end, 'over']]) {
    assert.equal(eventFeed.countdownParts(span.start, span.end, now).state, state);
    eventNow = now;
    assert.match(eventFeed.countdownHTML(row), new RegExp(`is-${state}`));
    assert.equal(eventFeed.render([row]).includes(row.title), state !== 'over');
  }
}
for (const [day, start, end, hours] of [
  ['2026-10-04', '2026-10-03T14:00:00Z', '2026-10-04T13:00:00Z', 23],
  ['2026-04-05', '2026-04-04T13:00:00Z', '2026-04-05T14:00:00Z', 25],
]) {
  const span = eventFeed.eventSpan({...sydney, start_date:day, end_date:day});
  assert.deepEqual(span, {start:Date.parse(start), end:Date.parse(end)});
  assert.equal((span.end - span.start) / 36e5, hours, 'local days can be shorter or longer than 24 hours');
}
assert.equal(dateStart('2026-10-16', 'Asia/Kolkata'), Date.parse('2026-10-15T18:30:00Z'));
assert.ok(Number.isNaN(dateStart('2026-02-30', 'Asia/Kolkata')));
assert.ok(Number.isNaN(dateStart('2026-10-16', 'Not/A_Zone')));
assert.equal(eventFeed.eventSpan({...sydney, timezone:undefined}).start, Date.parse('2026-12-05T17:00:00Z'), 'legacy snapshots retain their fallback');
const exactEnd = {...bengaluru, end_at:'2026-10-16T16:00:00+05:30'};
assert.equal(eventFeed.eventSpan(exactEnd).end, Date.parse('2026-10-16T10:30:00Z'));
eventNow = Date.parse('2026-10-16T17:30:00Z'); // Already the next date in Vietnam, still the event date in India.
assert.ok(eventFeed.render([bengaluru]).includes(bengaluru.title));
eventNow = Date.parse('2026-10-17T06:59:59Z'); // Already the next UTC date, still the event date in Los Angeles.
assert.ok(eventFeed.render([{...sydney, timezone:'America/Los_Angeles', start_date:'2026-10-16', end_date:'2026-10-16'}]).includes(sydney.title));

assert.equal(eventFeed.eventWhen(bengaluru), '16 tháng 10 · 14:00 giờ Bengaluru (15:30 giờ Việt Nam)');
assert.equal(eventFeed.eventWhen(sydney), '6–12 tháng 12 · Sydney, Australia · chưa rõ giờ khai mạc');
assert.match(eventFeed.eventWhen({...bengaluru, start_at:'2026-10-16T23:30:00+05:30'}), /01:00 ngày 17 tháng 10 giờ Việt Nam/);
const bengaluruCal = eventFeed.eventCal(bengaluru), sydneyCal = eventFeed.eventCal(sydney);
const exactIcs = buildIcs(bengaluruCal), dateIcs = buildIcs(sydneyCal);
assert.match(exactIcs, /DTSTART:20261016T083000Z\r\n/);
assert.match(exactIcs, /X-WR-TIMEZONE:Asia\/Kolkata\r\n/);
assert.doesNotMatch(exactIcs, /DTEND|DURATION|VALUE=DATE/);
assert.match(dateIcs, /DTSTART;VALUE=DATE:20261206\r\nDTEND;VALUE=DATE:20261213\r\n/);
assert.match(dateIcs, /X-WR-TIMEZONE:Australia\/Sydney\r\n/);
assert.match(buildIcs(eventFeed.eventCal(exactEnd)), /DTEND:20261016T103000Z/);
for (const [cal, dates, zone] of [
  [bengaluruCal, '20261016T083000Z/20261016T083000Z', 'Asia/Kolkata'],
  [sydneyCal, '20261206/20261213', 'Australia/Sydney'],
]) {
  const params = new URL(gcalURL(cal)).searchParams;
  assert.equal(params.get('dates'), dates);
  assert.equal(params.get('ctz'), zone);
}
assert.equal(canCalendar({...bengaluruCal, startAt:'2026-10-16T14:00:00'}), false);
assert.equal(canCalendar({...bengaluruCal, timezone:'Not/A_Zone'}), false);
eventNow = Date.parse('2026-10-10T12:00:00Z');
const eventCards = eventFeed.render(curatedEvents);
assert.match(eventCards, /class="events shelf"/);
assert.ok(eventCards.includes('14:00 giờ Bengaluru (15:30 giờ Việt Nam)'));
assert.ok(eventCards.includes('ctz=Asia%2FKolkata'));
assert.ok(eventCards.includes('ctz=Australia%2FSydney'));
eventFeed.render(curatedEvents, [{id:'event-story', title:bengaluru.title, url:bengaluru.url, coverage:[]}]);
assert.deepEqual(eventFeed.calOf({title:bengaluru.title, url:bengaluru.url}), bengaluruCal);

// Exercise the existing shared timer with a controlled scheduler, including the exact opening transition.
const opening = eventFeed.eventSpan(bengaluru);
eventNode.dataset = {cd:String(opening.start), cdEnd:String(opening.end)};
eventNow = opening.start - 2000;
eventFeed.scheduleCountdown();
eventFeed.scheduleCountdown();
assert.equal(eventTimers.size, 1);
assert.match(eventNode.lastElementChild.innerHTML, /00:00:02/);
assert.equal(eventNode.firstElementChild.textContent, 'Còn dưới 1 phút');
assert.match(eventFeed.countdownHTML(bengaluru), /class="sr".*class="cd-face" aria-hidden="true"/);
eventDocument.hidden = true;
eventFeed.scheduleCountdown();
assert.equal(eventTimers.size, 0);
eventNow = opening.start;
eventDocument.hidden = false;
eventFeed.scheduleCountdown();
assert.equal(eventNode.firstElementChild.textContent, 'Đang diễn ra');
eventMotion.matches = true;
eventNow = opening.start - 5 * 6e4;
eventFeed.scheduleCountdown();
assert.equal(eventTimers.size, 1);
assert.equal([...eventTimers.values()][0].ms, 60015);
assert.match(eventNode.lastElementChild.innerHTML, /5<\/b> phút/);
assert.doesNotMatch(eventNode.lastElementChild.innerHTML, /cd-clock/);
eventNow = opening.end;
eventFeed.scheduleCountdown();
assert.equal(eventNode.firstElementChild.textContent, 'Đã kết thúc');
eventDocument.hidden = true;
eventFeed.scheduleCountdown();
assert.equal(eventTimers.size, 0);
console.log('PASS event timezone boundaries, DST, partial exact times, cards, calendar exports and shared countdown timer');

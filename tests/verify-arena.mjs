import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {arenaHTML, movement, modelName, makerName, scoreText, createArenaView} from '../site/arena.js';
const rows = Array.from({length: 10}, (_, i) => ({id: `claude-opus-${i}`, maker: 'anthropic', rank: i + 1, score: 1500.125,
  rank_change: i === 0 ? 2 : 0, change_status: 'compared'}));
const data = {published_at: '2026-10-08', comparison_at: '2026-09-30', categories: {overall: rows, hard_prompts: rows, non_english: rows}};
const names = {
  'claude-opus-4-6-high': 'Claude Opus 4.6 (suy luận: high)',
  'claude-opus-4-7': 'Claude Opus 4.7',
  'claude-opus-4-8-high': 'Claude Opus 4.8 (suy luận: high)',
  'claude-opus-5.5-high': 'Claude Opus 5.5 (suy luận: high)',
  'claude-fable-5-high': 'Claude Fable 5 (suy luận: high)',
  'claude-fable-5.1-max': 'Claude Fable 5.1 (suy luận: max)',
  'claude-sonnet-5.5-xhigh': 'Claude Sonnet 5.5 (suy luận: xhigh)',
  'claude-3-5-sonnet-20241022': 'Claude 3.5 Sonnet 20241022',
  'claude-3-7-sonnet-20250219-thinking-32k': 'Claude 3.7 Sonnet 20250219 Thinking 32K',
  'claude-haiku-4-5-20251001': 'Claude Haiku 4.5 20251001',
  'claude-opus-4-1-20250805': 'Claude Opus 4.1 20250805',
  'claude-sonnet-4-5-20250929-high-32k': 'Claude Sonnet 4.5 20250929 32K (suy luận: high)',
  'claude-opus-4-20250514': 'Claude Opus 4 20250514',
  'gemini-4-argon-high': 'Gemini 4 Argon (suy luận: high)',
  'gemini-3.5-flash-medium': 'Gemini 3.5 Flash (suy luận: medium)',
  'muse-spark-1.3-max': 'Muse Spark 1.3 (suy luận: max)',
  'muse-spark-1.2 (xHigh)': 'Muse Spark 1.2 (suy luận: xhigh)',
  'gpt-6-astra-max': 'GPT 6 Astra (suy luận: max)',
  'gpt-5.6-luna-xhigh': 'GPT 5.6 Luna (suy luận: xhigh)',
  'gpt-5.4-mini-high': 'GPT 5.4 Mini (suy luận: high)',
  'grok-4-1-fast-reasoning': 'Grok 4.1 Fast Reasoning',
  'grok-4.20-beta-0309-reasoning': 'Grok 4.20 Beta 0309 Reasoning',
  'deepseek-v4-pro-high-20260813': 'DeepSeek V4 Pro 20260813 (suy luận: high)',
  'deepseek-v4-pro-high-preview': 'DeepSeek V4 Pro Preview (suy luận: high)',
  'glm-5.2-max': 'GLM 5.2 (suy luận: max)',
  'kimi-k3-max': 'Kimi K3 (suy luận: max)',
  'o3-mini-high': 'o3 Mini (suy luận: high)',
  'gpt-4-turbo-2024-04-09': 'GPT 4 Turbo 2024-04-09',
  'gpt-4o-2024-08-06': 'GPT 4o 2024-08-06',
  'gpt-4o-mini-2024-07-18': 'GPT 4o Mini 2024-07-18',
  'step-1o-turbo-202506': 'Step 1o Turbo 202506',
  'qwen3.5-397b-a17b': 'Qwen3.5 397B A17B',
  'gpt4all-13b-snoozy': 'GPT4All 13B Snoozy',
  'amazon-nova-experimental-chat-26-01-10': 'Amazon Nova Experimental Chat 26-01-10',
  'gemini-2.0-flash-lite-preview-02-05': 'Gemini 2.0 Flash Lite Preview 02-05',
  'command-r-08-2024': 'Command R 08-2024',
  'qwen3.8-max': 'Qwen3.8 Max',
  'qwen-max-0919': 'Qwen Max 0919',
  'mistral-medium-3.5': 'Mistral Medium 3.5',
  'llama-3.1-405b-instruct-bf16': 'Llama 3.1 405B Instruct BF16',
  'minimax-m2.1-preview': 'MiniMax M2.1 Preview',
  'mimo-v2.5': 'MiMo V2.5',
  'future-lab-2-7-2026-10-09-high': 'Future Lab 2-7-2026-10-09 High',
  'future-v12.03-8b': 'Future V12.03 8B',
  'gpt-future-2-7-max': 'GPT Future 2-7 Max',
  'constructor-1.2': 'Constructor 1.2',
};
for (const [id, expected] of Object.entries(names)) assert.equal(modelName(id), expected, id);
for (const [maker, expected] of Object.entries({google: 'Google', anthropic: 'Anthropic', meta: 'Meta',
  openai: 'OpenAI', xai: 'xAI', zai: 'Z.ai', bytedance: 'ByteDance', minimax: 'MiniMax',
  nvidia: 'NVIDIA', 'ant-group': 'Ant Group', 'inception-ai': 'Inception AI',
  'future-lab': 'Future Lab', '': 'Chưa rõ hãng', '  ': 'Chưa rõ hãng', constructor: 'Constructor'})) {
  assert.equal(makerName(maker), expected);
}
for (const [score, expected] of [[1525.3956, '1525'], [1501, '1501'], [1494, '1494'], [1494.5, '1495'], [999.9, '1000'], [10000, '10000']]) {
  assert.equal(scoreText(score), expected);
}
for (const category of Object.keys(data.categories)) {
  const html = arenaHTML(data, category);
  assert.equal((html.match(/<li class="arena-column /g) || []).length, 10);
  assert.ok(html.includes(`data-arena-category="${category}" aria-pressed="true"`));
  for (const text of ['08/10/2026', '30/09/2026', '↑ Tăng 2', 'Giữ hạng', '1500', '<small>Anthropic</small>', 'CC BY 4.0', 'giữ nguyên điểm', 'https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset', 'https://creativecommons.org/licenses/by/4.0/']) assert.ok(html.includes(text), text);
}
assert.ok(movement({...rows[0], rank_change: -2}).includes('↓ Giảm 2'));
assert.ok(movement({...rows[0], change_status: 'unlisted', rank_change: null}).includes('Chưa có hạng cũ'));
assert.ok(movement({...rows[0], change_status: 'unavailable', rank_change: null}).includes('Chưa đủ dữ liệu'));
assert.ok(arenaHTML({...data, comparison_at: null}).includes('Chưa có bản công bố phù hợp'));
assert.ok(arenaHTML({...data, stale: true, fetch_status: 'failed'}).includes('đang giữ bản đã tải'));
assert.ok(arenaHTML({...data, stale: true}).includes('hơn 14 ngày'));
for (const invalid of [null, {}, {categories: {overall: []}}, {categories: {overall: [...rows.slice(1), null]}}, {categories: {overall: [...rows.slice(1), {...rows[0], score: null}]}}]) {
  assert.ok(arenaHTML(invalid).includes('Chưa tải được bảng xếp hạng'));
  assert.ok(arenaHTML(invalid).includes('CC BY 4.0'));
}
const hostile = {...data, categories: {overall: rows.map(r => ({...r, id: '<script>alert(1)</script>', maker: '<img src=x onerror=evil()>'}))}};
assert.ok(!arenaHTML(hostile).includes('<script>'));
assert.ok(!arenaHTML(hostile).includes('<img'));
assert.ok(!arenaHTML(hostile).includes('arena-maker-<'));

// Absolute scores share one padded scale across categories and orientations.
const scores = [1525.3956435571818, 1507.0758687407206, 1504.355209789498,
  1503.693577172815, 1501.0258966973688, 1500.7290291564887,
  1497.7335923252954, 1496.5039548814862, 1494.1854645692001, 1493.9734271816128];
const chartRows = rows.map((row, i) => ({...row, score: scores[i], maker: i % 2 ? 'anthropic' : 'google'}));
const chartData = {...data, categories: {overall: chartRows,
  hard_prompts: chartRows.map((row, i) => ({...row, score: i ? row.score : 1600})), non_english: rows}};
const chart = arenaHTML(chartData);
const heights = html => [...html.matchAll(/--arena-bar-size:([\d.]+)%/g)].map(match => Number(match[1]));
const plotted = heights(chart);
assert.equal(plotted.length, 10);
assert.ok(plotted.every(height => height > 0 && height <= 100), 'Every model must have a visible, in-range bar');
assert.ok(Math.abs(plotted[0] - (scores[0] - 1480) / 120 * 100) < 1e-10);
assert.ok(plotted[8] > plotted[9], 'Distinct source scores remain distinct even when both labels round to 1494');
assert.ok(chart.includes('18,3 điểm'));
assert.ok(chart.includes('Trục điểm Arena: 1480–1600'));
assert.ok(chart.includes('Trục không bắt đầu từ 0'));
assert.ok(chart.includes('không biểu thị tỷ lệ năng lực'));
assert.ok(chart.includes('aria-describedby="arena-comparison"'));
for (const category of Object.keys(data.categories)) {
  const rendered = arenaHTML(chartData, category);
  assert.ok(rendered.includes('<span>1600</span><span>1540</span><span>1480</span>'));
  assert.ok(rendered.includes('<div class="arena-mobile-axis" aria-hidden="true"><span>1480</span><span>1540</span><span>1600</span></div>'));
  const sizes = heights(rendered);
  for (const [i, row] of chartData.categories[category].entries()) {
    assert.ok(Math.abs(sizes[i] - (row.score - 1480) / 120 * 100) < 1e-10);
  }
}
assert.deepEqual(heights(arenaHTML(chartData, 'hard_prompts')).slice(1), plotted.slice(1), 'Equal scores retain equal geometry after switching');
assert.ok(heights(arenaHTML(data)).every(height => height > 0 && height === heights(arenaHTML(data))[0]));
const boundaryRows = rows.map(row => ({...row, score: 1500}));
const boundaryChart = arenaHTML({...data, categories: {overall: boundaryRows}});
assert.ok(boundaryChart.includes('Trục điểm Arena: 1490–1510'));
assert.ok(heights(boundaryChart).every(height => height === 50), 'Scores exactly on a round boundary still have visible bars');
assert.ok(arenaHTML(data).includes('CÙNG ĐIỂM CAO NHẤT'));
const tiedRanks = chartRows.map((row, i) => ({...row, rank: i < 2 ? 1 : i + 1}));
assert.equal((arenaHTML({...data, categories: {overall: tiedRanks}}).match(/value="1"/g) || []).length, 2);
assert.ok(arenaHTML({...data, categories: {overall: chartRows, hard_prompts: {}}}).includes('18,3 điểm'));
// Real reader snapshot captured on 10 October from the 8 October Arena publication.
// Keep this fixture stable so later refreshes cannot erase the axis regression.
const snapshot = JSON.parse(await readFile(new URL('./fixtures/arena-2026-10-08.json', import.meta.url), 'utf8'));
const snapshotSizes = {};
for (const category of Object.keys(data.categories)) {
  const rendered = arenaHTML(snapshot, category);
  const sizes = snapshotSizes[category] = heights(rendered);
  assert.equal(sizes.length, 10);
  assert.ok(rendered.includes('Trục điểm Arena: 1470–1560'));
  assert.ok(rendered.includes('<span>1560</span><span>1515</span><span>1470</span>'));
  assert.ok(rendered.includes('<div class="arena-mobile-axis" aria-hidden="true"><span>1470</span><span>1515</span><span>1560</span></div>'));
  assert.ok(rendered.includes('Trục không bắt đầu từ 0'));
  assert.ok(sizes.every(size => size > 0 && size <= 100), `${category}: every real model has a visible bar`);
  assert.ok(sizes[0] / sizes[9] >= 1.5, `${category}: leader is at least 1.5 times the tenth's height`);
  for (const [i, row] of snapshot.categories[category].entries()) {
    assert.ok(Math.abs(sizes[i] - (row.score - 1470) / 90 * 100) < 1e-10, `${category}: shared raw-score geometry`);
  }
}
assert.ok(snapshotSizes.overall[0] / snapshotSizes.overall[9] >= 2, 'Overall leader is at least twice the tenth’s height');
assert.ok(Math.max(...Object.values(snapshotSizes).flat()) >= 85, 'Real scores use at least 85% of the shared plot height');
const arenaCSS = await readFile(new URL('../site/arena.css', import.meta.url), 'utf8');
const narrowCSS = arenaCSS.split('@media (max-width: 1199px)')[1].split('@media (max-width: 599px)')[0];
assert.match(arenaCSS, /grid-template-columns: repeat\(10, minmax\(0, 1fr\)\)/);
assert.match(arenaCSS, /height: var\(--arena-bar-size\)/);
assert.match(narrowCSS, /\.arena-columns \{ grid-template-columns: minmax\(0, 1fr\)/);
assert.match(narrowCSS, /\.arena-mobile-axis \{ display: flex/);
assert.match(narrowCSS, /\.arena-bar \{ left: 0; width: var\(--arena-bar-size\); height: 100%/);
assert.ok(!/repeat\([25],/.test(arenaCSS), 'Narrow charts must never split into mini column charts');
const tokensCSS = await readFile(new URL('../site/tokens.css', import.meta.url), 'utf8');
for (const maker of ['google', 'anthropic', 'meta', 'moonshot', 'openai', 'other']) {
  assert.ok(arenaCSS.includes(`--arena-maker-color: var(--color-maker-${maker})`));
  const colors = [...tokensCSS.matchAll(new RegExp(`--color-maker-${maker}: (#[a-f0-9]+);`, 'g'))].map(match => match[1]);
  assert.equal(colors.length, 3, `${maker}: light, explicit dark and system dark tokens`);
  assert.notEqual(colors[0], colors[1]);
  assert.equal(colors[1], colors[2]);
}
let click, focused = false, calls = 0;
const root = {innerHTML: '', hidden: true, addEventListener: (_, fn) => { click = fn; }, querySelector: () => ({focus: () => { focused = true; }})};
globalThis.fetch = async () => { calls++; return {ok: true, json: async () => data}; };
const view = createArenaView(root);
view.show();
assert.ok(root.innerHTML.includes('Đang tải'));
await new Promise(r => setImmediate(r));
assert.equal(root.hidden, false);
assert.ok(root.innerHTML.includes('08/10/2026'));
click({target: {closest: selector => selector === '[data-arena-category]' ? {dataset: {arenaCategory: 'non_english'}} : null}});
assert.ok(root.innerHTML.includes('data-arena-category="non_english" aria-pressed="true"'));
assert.ok(focused);
view.show();
assert.equal(calls, 1);
globalThis.fetch = async () => { throw new Error('offline'); };
click({target: {closest: selector => selector === '[data-arena-retry]' ? {} : null}});
await new Promise(r => setImmediate(r));
assert.ok(root.innerHTML.includes('Chưa tải được'));
globalThis.fetch = async () => ({ok: true, json: async () => data});
click({target: {closest: selector => selector === '[data-arena-retry]' ? {} : null}});
await new Promise(r => setImmediate(r));
assert.ok(root.innerHTML.includes('08/10/2026'));
const html = await readFile(new URL('../site/index.html', import.meta.url), 'utf8');
assert.match(html, /data-filter="code"[^>]*>Mã và mô hình<\/button>\s*<button[^>]*data-filter="rankings"[^>]*>Xếp hạng<\/button>/);
console.log('PASS Arena categories, dates, movement, escaping, errors, retry and selection');

if (process.argv.includes('--source-rows')) {
  const source = JSON.parse(readFileSync(0, 'utf8'));
  const expectedMakers = {alibaba: 'Alibaba', allenai: 'AllenAI', amazon: 'Amazon', 'ant-group': 'Ant Group',
    anthropic: 'Anthropic', baidu: 'Baidu', bytedance: 'ByteDance', cohere: 'Cohere', deepseek: 'DeepSeek',
    google: 'Google', ibm: 'IBM', 'inception-ai': 'Inception AI', meituan: 'Meituan', meta: 'Meta',
    microsoft: 'Microsoft', minimax: 'MiniMax', mistral: 'Mistral', moonshot: 'Moonshot', nvidia: 'NVIDIA',
    openai: 'OpenAI', stepfun: 'StepFun', tencent: 'Tencent', thinky: 'Thinky', upstage: 'Upstage',
    xai: 'xAI', xiaomi: 'Xiaomi', zai: 'Z.ai', '': 'Chưa rõ hãng'};
  for (const row of source) {
    const id = row.model_name, label = modelName(id);
    // Every numeric component, including dates, budgets and trailing zeroes, survives in order.
    assert.deepEqual(label.match(/\d+/g), id.match(/\d+/g), id);
    for (const version of id.match(/\d+(?:\.\d+)+/g) || []) assert.ok(label.includes(version), id);
    // Typography and the explicit effort label must not rename a model or drop a word.
    const tokens = text => (text.toLowerCase().match(/[a-z]+|\d+/g) || []).sort();
    assert.deepEqual(tokens(label.replace('suy luận: ', '')), tokens(id), id);
    const maker = makerName(row.organization || '');
    if (Object.hasOwn(expectedMakers, row.organization || '')) assert.equal(maker, expectedMakers[row.organization || '']);
    else assert.match(maker, /^[A-Z]/, row.organization);
    assert.match(scoreText(row.rating), /^\d+$/, id);
    assert.equal(Number(scoreText(row.rating)), Math.round(row.rating), id);
  }
  // Render every row in every category through the actual ten-row reader, not only today's leaders.
  for (const category of Object.keys(data.categories)) {
    const categoryRows = source.filter(row => row.category === category);
    assert.ok(categoryRows.length >= 10, category);
    for (let start = 0; start < categoryRows.length; start += 10) {
      const page = categoryRows.slice(start, start + 10);
      while (page.length < 10) page.push(categoryRows[page.length]);
      const rows = page.map(row => ({id: row.model_name, maker: row.organization || '', rank: row.rank, score: row.rating}));
      const rendered = arenaHTML({...data, categories: {[category]: rows}}, category);
      assert.equal((rendered.match(/<li class="arena-column /g) || []).length, 10, category);
      assert.equal((rendered.match(/Điểm Arena <\/span>\d+<\/strong>/g) || []).length, 10, category);
      for (const row of rows) {
        assert.ok(rendered.includes(modelName(row.id)), row.id);
        assert.ok(rendered.includes(`<small>${makerName(row.maker)}</small>`), row.maker);
      }
    }
  }
  console.log(`PASS all ${source.length} source rows: lossless names, maker casing and whole-number scores in three categories`);
}

# Arena model rankings

The home tab **Xếp hạng** is available at `/#xep-hang`. It reads
`site/data/arena.json` independently of the news feed. The three groups are
`overall` (Tổng), `hard_prompts` (Câu hỏi khó), and `non_english` (Ngoài tiếng Anh).
Each shows ten models, source rank, readable model identifier, maker, Arena score
and rank movement. Source ties and gaps are retained; equal ranks are ordered by
score and then identifier. Scores are rounded to whole numbers with no grouping
separator (for example, `1525`), without changing
the underlying value. A short explanation warns that small differences may be
within uncertainty; confidence intervals and vote counts are omitted from the
reader view.

## Reading the column chart

The ranking uses the home feed's full content width. Ten vertical columns show
the top ten at desktop widths of 1200px and above. Below 1200px, one horizontal
bar chart contains all ten models on a common aligned track, with source rank,
full name, maker, score and weekly movement. It does not wrap into separate
mini charts or require horizontal scrolling. Maker identity is presented through small, elegant monogram marks (such as [G], [A], [M], [O])
paired with brand names in the legend and rich detail on hover or keyboard focus. The palette is
calm and restrained: runner-up columns use a subtle neutral fill while the leader carries the
primary accent colour, making "who leads, by how much" unmistakable in a single glance. Columns
are slim and softly finished with light hairline gridlines. The leader callout is seamlessly
integrated into the headline without visual clutter, and technical axis notes rest quietly as a
footnote below the columns. On mobile and narrow viewports below 1200px, one aligned horizontal
bar chart provides the same restrained, dignified experience without overflowing.

The axis measures **absolute Arena scores**. Its shared floor is the lowest
score across all available complete categories, rounded down to a multiple of
10, then reduced by 10. This guarantees at least 10 points of space below the
lowest model, including scores on a round boundary. The ceiling is the highest
score rounded up to 10, with a minimum range of 20 points above the floor for
ties or tightly clustered scores. Endpoints are multiples of 10; midpoint ticks
are multiples of 5. The supplied 8 October 2026 snapshot uses 1470–1560 in all
three categories, with ticks at 1470, 1515 and 1560 on desktop and mobile.
The lowest score is 1483.92 in the non-English category; the highest column fills
about 90% of the plot. Overall, the leader's column is about 2.31 times the
tenth's height, making the point gap visible while every column remains positive.
The caption explicitly states that this axis does
not start at zero and that bar lengths do not represent ability ratios.

Column height and mobile bar width both equal `(score - floor) / (ceiling -
floor)`. They use raw source values, so two models labelled `1494` can still
have different lengths. Every model has a positive bar, without an artificial
minimum size that distorts the scale. Rounded scores are shown above desktop
columns and in an aligned score column beside mobile bars. Category switching
and layout changes never rescale the same snapshot. New snapshots can change
the range, whose endpoints remain explicit in the caption. The native HTML
figure and single list expose every value in real text; no canvas, tooltip,
image or chart library is required. Category controls retain keyboard focus.

Names are formatted in the reader, so cached JSON benefits immediately. Known
Claude major/minor slugs and Grok `4-1` recover their version dots; existing
decimal versions, dates, sizes and budgets retain every numeric component.
Known reasoning-effort variants appear in parentheses, such as
`Claude Opus 4.6 (suy luận: high)` and `Muse Spark 1.3 (suy luận: max)`.
The source effort spelling is retained to distinguish settings without claiming
they are equivalent across makers. Product tiers such as Qwen Max and Mistral
Medium remain part of the name. Unknown names receive typography only; ambiguous
numeric hyphens remain intact rather than guessing a version or product identity.
Maker names use brand casing (Google, Anthropic, Meta, OpenAI, xAI); unknown makers
are capitalized and a missing maker stays **Chưa rõ hãng**. The original model ID
remains in the name's title attribute. IDs, scores, ranks and movement in the data
are unchanged. Ungrouped integer scores avoid confusing decimal and thousands
punctuation in the Vietnamese chart.

## Source and attribution

The collector reads only the official public Hugging Face
[Arena / LMArena leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset),
configuration `text_style_control`. The supplied dataset card declares
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It does not scrape
arena.ai. The tab credits Arena / LMArena, links to the dataset and licence, and
states the changes: category filtering, readable names, translated labels and
computed rank movement, with source scores and ranks retained. Model-level
`license` values describe the models and are not the dataset's licence.

## Collection and persistence

[radar.arena](../radar/arena.py) is an optional standalone publisher. New steps in
the [update workflow](../.github/workflows/update.yml) restore
`data/arena-state.json`, install the optional pinned PyArrow reader, refresh the
public output, and save the state using the existing pinned Actions cache action.
News collection and its publication quorum are unchanged. Core `build.py` does
not install or require PyArrow; a local news-only build will show the ranking
empty state until this optional command runs:

```sh
python -m pip install pyarrow==23.0.1
python -m radar.arena
```

The module checks `latest-00000-of-00001.parquet` at most once per 24 hours,
including after a failure. It retains the last valid snapshot and successful
fetch time. Before network work, it writes a dated last-good fallback and attempt
checkpoint so even an interrupted refresh leaves reader output. The public file is regenerated each run so the stale flag ages even
without another download. Invalid dates, non-finite scores, duplicate model IDs,
missing categories, regressed publication dates and future publication dates
reject the incoming snapshot. Empty organizations in the real source remain
unknown rather than inferred.

The latest source was 608,613 bytes in the supplied fixture. A cold cache or
missing weekly baseline permits one historical fetch of
`full-00000-of-00001.parquet` (approximately 52 MB), with a seven-day retry limit.
Only requested columns and the last 60 days of relevant categories are retained;
Parquet batches are processed incrementally. Downloads have a 60-second socket
timeout and explicit byte limits. CI also bounds the refresh step to four minutes.
The fixture-generated reader JSON is about 4.2 KB and the compact state about
251 KB. State stores all models' ranks, not only the top ten, so models entering
the top ten can still have genuine prior ranks.

Caches are best-effort, not a durable archive. Cache eviction requires bootstrap
again. A failed first fetch leaves an explicit unavailable state. A failed history
fetch still permits the latest valid top ten, with comparisons marked unavailable.
No fixture is a production fallback.

## Weekly comparison and freshness

The reference is the latest publication at or before **current publication date
minus seven days**, provided it is no more than fourteen days before the current
publication. For the supplied 8 October 2026 publication, this selects 30 September,
not 2 October. The exact reference date is visible. A positive movement is
`previous_rank - current_rank`. Missing models say **Chưa có hạng cũ**, not “new
model”; a missing reference says **Chưa đủ dữ liệu**. More distant history is not
presented as a weekly change.

The public contract includes `published_at`, `comparison_at`, `fetched_at`,
`checked_at`, `fetch_status`, `stale`, and category arrays. Each row has `id`,
`maker`, `rank`, `score`, `rank_change` and `change_status` (`compared`, `unlisted`,
`unavailable`). Dates of publication and comparison are calendar dates. Fetch
and attempt times are UTC timestamps. A publication older than fourteen days is
marked stale. The reader always sees the publication date and sees inline text
for a failed refresh or old publication; no banner is introduced.

## Verification and rollback

```sh
python -m pytest tests/test_arena.py -q
node tests/verify-arena.mjs
python -m pytest tests -q
node tests/verify-feed-content.mjs
```

Real Parquet integration tests also send every source ID in all three categories
to the production JavaScript formatter and renderer, checking numeric and name
token preservation, maker casing and one integer score format. They cover all
414 models per category in the supplied latest snapshot, not only its top ten.
The tests use the coordinator's ignored files in
`plans/live-data/arena/` and report an explicit skip when they or PyArrow are not
installed. The comparison, failure preservation and renderer tests do not need
Parquet or network access. For local real-data preview only:

```sh
python -m radar.arena --fixture-dir plans/live-data/arena --state plans/live-data/arena/preview-state.json
```

On the first live runner check public Hugging Face downloads, the dataset card's
licence, all three top tens, the historical reference date, cache restore/save,
and the deployed `data/arena.json`. A second run within 24 hours should preserve
`checked_at`; a forced failing fetch in an isolated state must retain the scores
and publication date. Confirm no calls to arena.ai. Local tests do not verify
runner network access, cache survival or deployment.

Rollback removes the Arena workflow steps, tab, module import and associated
styles. Existing news data is independent and does not need migration.

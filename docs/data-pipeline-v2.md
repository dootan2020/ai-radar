# Data pipeline v2

AI Radar is a map to original reporting, research and discussion. Its data must
separate a collected observation from an editorial ranking decision. Unknown
times, counters and failed sources must remain visible as unknown or failed.

## Where to work

- [CLI publication](../build.py) and [collection boundary](../radar/pipeline.py).
- [Source inventory](../radar/catalog.py), [RSS/media](../radar/v2feeds.py),
  [community](../radar/community.py), [paper/repository APIs](../radar/discovery.py),
  and the optional [official X collector](../radar/x_collector.py) with its
  [verified account roster](../data/x-accounts.json) and independent paid ledger.
- [Observation identity](../radar/items.py), [clustering](../radar/clustering.py),
  [ranking](../radar/ranking.py), [story/section assembly](../radar/assembly.py).
- [Measurement baseline policy](../radar/measurement_cache.py) and its
  [retention/publication tests](../tests/test_measurement_cache.py).
- [Curated calendar](../data/events.json) and [calendar validation](../radar/events.py).
- [Transport evidence](../radar/transport.py), [workflow](../.github/workflows/update.yml),
  and [offline tests](../tests/).
- [Publication policy](../radar/publication.py), [operations and rollback](operations.md),
  and [dated feed verification](source-feed-check-2026-10-03.md).
- [Daily editions and durable archive](daily-editions.md), separate from the rolling snapshot.
- [Official product updates](tool-updates.md), including dated release evidence,
  product/version grouping and attributed changelog excerpts.
- [Free-source collection decisions and hosted-runner probes](../plans/reports/nguon-mien-phi.md).

## Decisions to preserve

Feed count is not independent corroboration: mirrors and multiple endpoints of
one publisher count once. Different discussion threads retain their own
measurement identity even when they link to the same story. An event occurrence
also needs its own identity when an official landing page serves several dates.

Ranking is an editorial heuristic, not an assertion of objective importance.
Missing observations cannot be replaced with plausible zeroes. A repository's
creation time is not its model's release date. Date-only event announcements
must not acquire invented midnight timestamps or timezones.

Hot ranking scores the equally weighted percentiles for engagement, measured
velocity and distinct-publisher breadth, omitting unavailable signals before
averaging. Publisher breadth is ranked among hot-eligible candidates; ties use
average ranks, with a lone candidate assigned the midpoint. Stories with
measured engagement counters retain the 24-hour freshness half-life and
72-hour scoring window. Stories without counters can score from publisher
breadth with a 72-hour half-life and a seven-day scoring window. Mirrors still
count as one publisher, and age alone never creates a score. Eligibility and
freshness rules are independent of the breadth score.

The previous snapshot exists only to compare measurements. Republishing its old
content with a new build time would mislead readers about freshness. Frozen
fixtures support reproducible tests; they do not establish current source health.

### Press subject relevance

All `press` feeds, including AI category feeds with `filter_ai=False`, pass the
[press subject check](../radar/press_relevance.py) before observations enter the
v2 feed. The existing keyword flag still applies afterward; other source groups
keep their existing relevance rules. Category membership alone is insufficient
when the title and available description show no AI evidence. Original feed copy
is used, never translated headlines, URL/category keywords or generated summaries.

Consumer banking/payment rule headlines whose only AI evidence is an incidental
relationship phrase (for example, “related to AI”) are excluded. A separate AI
anchor in the headline keeps actual AI banking, fraud/deepfake and policy coverage.
Explicit side mentions in headlines or descriptions do not establish a subject.
Otherwise AI evidence anywhere in the short feed description can keep a story;
requiring a headline keyword alone would lose real coverage. Sparse category-feed
copy, ambiguous relationship headlines and emerging product/infrastructure clues
are kept conservatively. This is a bounded heuristic, not a semantic classifier.

Assembly applies the same check to retained coverage before the seven-day merge,
so yesterday's rejected observations cannot return during a source outage. Mixed
stories are rebuilt from surviving observations; rejected primary text and its
derived enrichment are removed while old IDs remain aliases. Unchanged stories
retain their enrichment. A retained story whose observations no longer form one
cluster under the current matching rules is rebuilt the same way: the piece that
keeps the story's id and headline keeps its enrichment and aliases, and the other
pieces become their own stories, so a grouping published by an earlier build
cannot keep pulling unrelated fresh coverage together for seven days. No model
calls, paid-ledger changes or additional fetches are involved.

Job posts are not news: [radar/noise.py](../radar/noise.py) refuses links to
applicant-tracking hosts and forum hiring ads or hiring threads, with a reason
code and a one-line reader sentence for each, and the build log counts refusals.
Press reporting that a company is hiring is not matched. [Synthetic tests](../tests/test_press_relevance.py) cover admission
and retention; `python tests/measure_press_relevance.py` lists all dropped and
borderline kept press inputs from committed JSON fixtures and local `site/data`
snapshots without modifying either.

The official X collector is disabled unless `RADAR_X_ENABLED=1` and
`X_BEARER_TOKEN` are present on the main workflow. It searches AI-related posts
server-side and records the original post URL and author identity. Its separate
durable ledger enforces $30 per UTC month and $1 per UTC day. Daily reconciliation
removes posts no longer returned by X; if reconciliation fails, X observations
older than 24 hours are removed from the publication candidate.

The owner maintains the calendar from official pages. Reverify a date before
changing its record and retain the official evidence URL. A source outage must
not silently erase the distinction between a valid empty feed and a failed feed.

### Curated event times

Every row in [data/events.json](../data/events.json) requires a unique `id`,
`title`, safe `url` and `source_url`, `verified_at`, `start_date`,
`time_precision`, and a valid IANA `timezone` (for example `Asia/Kolkata` or
`Australia/Sydney`). `start_date` and optional `end_date` are local calendar
dates in `YYYY-MM-DD` form; a missing end date means the same date as the start.
`verified_at` is a verification date or explicit-offset timestamp and must not
be in the future. `location` is optional display text, not a timezone identifier.

- `time_precision: "date"` requires `start_at` and `end_at` to be null or absent.
  Do not infer an opening hour from a published date.
- `time_precision: "exact"` requires an explicit-offset `start_at`. `end_at`
  may remain null when the official source gives no closing hour. If present,
  it must be an explicit-offset timestamp no earlier than `start_at`.
  Each timestamp must fall on its corresponding local date in `timezone`.

[The loader](../radar/events.py) validates zones with Python `zoneinfo`; the
runtime needs an IANA timezone database (OS zoneinfo or the `tzdata` package on
platforms without it). It retains an event until its exact end, or otherwise
until the first instant after its final local date. The browser applies the
same exclusive end boundary. It counts down to an exact start when known;
otherwise it uses the start of the first local date and displays that the
opening hour is unknown. Each date boundary uses that date's timezone offset,
so daylight-saving transitions do not assume a 24-hour day. Older snapshots
without `timezone` keep the browser's previous Vietnam fallback; newly loaded
curated rows must supply the field.

Cards show known opening times in the event's local zone and Vietnam time,
including the Vietnam date when conversion crosses midnight. The existing
shared countdown timer, hidden-tab pause, reduced-motion wording and
screen-reader sentence remain unchanged.

[Calendar exports](../site/calendar.js) preserve precision. Google Calendar
receives UTC instants and the IANA `ctz` for timed events; an unknown end uses
the same instant as the start rather than inventing a duration. The `.ics`
file uses UTC `DTSTART` and, only when known and later, `DTEND`, with the IANA
zone retained as calendar-level `X-WR-TIMEZONE` metadata. UTC instants remain
unambiguous even in clients that ignore that optional metadata. Date-only
events remain all-day in both formats, ending on the date after `end_date`;
the countdown's midnight boundaries never become claimed opening hours in
calendar exports.

The Bengaluru DevDay row was verified on 2026-10-10: October 16 at 14:00
`Asia/Kolkata`, with no published end time. The NeurIPS Sydney row was verified
on the same date: December 6–12 in `Australia/Sydney`, with no published opening
hour (AEDT, UTC+11 in December). The rows' `source_url` fields retain the
official evidence pages.

Equivalent Unicode spellings and alternate paper reading formats must not split
one story, while accents, release versions and publication timing still carry
meaning. The [clustering regressions](../tests/test_v2_core_regressions.py) own
the Vietnamese NFC and arXiv HTML identity examples; the clustering module owns
the conservative matching rules.

Cross-publisher title matching runs within 48 hours and uses complete-link
clusters. A shared entity is only an anchor: it does not count as a second
content word. Entity matches require two independent shared content words, a
shared adjacent entity/content phrase, a multiword entity phrase with
independent content evidence, or (for newly inferred names) a shared content
word with announcement language in both headlines. This keeps a
famous company, product name or capitalized common word from joining unrelated
events by itself. The halves of a shared hyphenated word ("open-source") count
once, as that word.

The outlet behind a forum post is the site it links to, so two posts of one news
item on Hacker News linking different outlets meet the cross-publisher rules,
while self-posts and posts more than a day apart stay one publisher. One
publisher's own headlines merge above the standard overlap, or when they re-title
one report: exactly the same figures (not only a year), two shared content words
and at least 0.4 overlap. Two different repository roots on a code or model host
never merge below the standard overlap.

Retention carries published stories by id and URL. After it,
`merge_repeated_events` folds a carried story into the story that already lists
it as an alias, or whose every observation passes the same complete-link test
(fresh stories are never re-compared). This is what joins an outlet's re-titled
article to yesterday's version under a new URL.

The "Đáng đọc" score counts attention only for a story that is hot by
`hot_eligible` (two independent publishers, or a count in the top fifth of its
source), the same bar as `sections.hot`; an ordinary count is shown but does not
promote. A repository dated only by its creation earns no freshness without a
first-hand origin, a second publisher or a hot count.

## Trending repositories

The repository lists are GitHub Trending's own day, week and month pages, ranked
by the stars each repository gained in that window; a window whose page failed
or printed another window's count stays unmeasured rather than borrowing one.
Only repositories whose name, description or topics say they are about AI are
kept, and area rules use generic phrases, never a repository or product name.
[Curation](../radar/curation.py) owns the windows, the relevance rule and the
orderings published as `repos_meta.rankings`; the page only chooses which one to
show. [Window and ordering tests](../tests/test_repo_windows.py) are the proof.

Reader-facing text is Vietnamese except names and original titles. Source
records keep the technical `error` and add `error_vi` for the page;
[the language test](../tests/test_vietnamese_ui.py) lists its exceptions.

## Title and summary translation

[Optional translation](../radar/translate.py) runs after collection and before
publication. It adds `title_vi`, `summary_vi` (existing story/coverage summaries
only), and repository `description_vi` beside unchanged originals. Events keep
their original identities. Empty summaries never acquire generated prose. The
daily edition projection still includes titles only, not summaries.

The default `--provider auto` prefers [Gemini whole-field translations](../radar/translation_gemini.py)
and falls back to the existing NLLB segment cache/model, then original text.
`--provider nllb` explicitly selects that fallback without Gemini cache or API
use. Collection and Gemini HTTP remain standard-library only; NLLB's optional
dependencies stay in [requirements-translate.txt](../requirements-translate.txt).
The [README attribution](../README.md#optional-translation-and-attribution) owns
the noncommercial constraint on NLLB output.

Live Gemini requests require `GEMINI_API_KEY` and an explicitly enabled route:
the owner-authorized `RADAR_GEMINI_PAID_ENABLED=1` route uses the shared
[paid ledger](../radar/gemini_paid_budget.py), capped at USD 1/run, USD 6/day
and USD 20/month, with a tighter USD 0.57 UTC-day pace and at most USD 0.20
held per run; `RADAR_GEMINI_FREE_TIER_CONFIRMED=1` asserts a verified
free-tier project. Code cannot verify billing or force a billed project onto
a free tier; Google has no per-request free-only parameter. Credentials remain
GitHub secrets and are passed only to the workflow's model steps, in the HTTPS
header to Google's fixed endpoint; redirects and environment proxies are disabled.
No key, header, response error body or exception text is written into diagnostics.

[Google's model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
identifies `gemini-3.8-flash`. Standard `generateContent` accepts multiple source
strings in one JSON request; this is **not** Google's paid Batch API.
[Pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-flash) lists
free Standard input/output as checked on 2026-10-03. [Quota documentation](https://ai.google.dev/gemini-api/docs/rate-limits)
does not publish numeric limits: actual limits are project-specific in AI Studio,
with daily Google quota reset at midnight Pacific. Free-tier source content may
be used to improve Google products; only already-public feed text is submitted.

Free-mode application ceilings are deliberately smaller than the twice-hourly schedule:
one attempt/run, 24 distinct normalized strings and 12,000 source characters
per request, 8,192 output tokens, 45 seconds per API request, and 12 attempts
in any rolling 24 hours. These are **local policy, not claimed Google quotas**.
The rolling window avoids timezone dependencies and is independent of Google's
Pacific calendar-day reset. A cold snapshot will need multiple runs; NLLB
or originals cover the remainder. `RADAR_GEMINI_MAX_REQUESTS`, `DAILY_LIMIT`,
`BATCH_SIZE`, `MAX_CHARS` and `TIMEOUT` (each with the `RADAR_GEMINI_` prefix)
can lower these values, never raise the ceilings. Invalid values disable that
budget. HTTP/429, authentication, blocked/malformed output and timeouts are not
retried. Both providers share `RADAR_TRANSLATE_BUDGET` (default 600 seconds).

The [local ledger](../radar/translation_budget.py) reserves before sending,
including failed attempts. Corrupt, locked or unwritable ledgers disable live
requests. A model/prompt-scoped hash cursor continues after the last attempted
source on later runs, wrapping through the current priority list; permanently
rejected first-page text cannot consume every attempt indefinitely. The ledger
never stores invalid translations. The workflow preserves `data/translation-gemini-attempts.json` with
`data/translations-gemini-vi.json` through Actions cache. Cache eviction, failed
restore/save, separate machines or simultaneous branches can lose accounting:
this is not a distributed quota guarantee or a billing safeguard. A missing
ledger starts a new local window. Keep the upstream project on its free tier
when using the free route. The paid route instead reserves against the durable
shared USD ledger before each call. Its separate UTC-day consumer shares are
40,000 tokens for translation, 100,000 for summaries and 12,000 for video.
At the code's conservative 2026 ledger rate of USD 3.75 per million total
tokens, these shares cost `(40,000 + 100,000 + 12,000) × 3.75 / 1,000,000 =
0.57 USD/day`. The 31-day envelope is `31 × 0.57 = 17.67 USD`, leaving
`20 - 17.67 = 2.33 USD` below the hard cap. This is a ledger enforcement
envelope, not a provider invoice forecast. Dollar pacing remains authoritative
after rate changes.
Reservations and missing-usage failures consume these shares; validated provider
usage settles them. Shares cannot borrow from each other. The monthly cap is
still downward-only. The hold shrinks to available day/month budget and unused
money is released only after successful finalization. Interrupted holds stay
charged against every consumer. Legacy daily spend without consumer attribution
was incurred entirely by translation and summary workflows prior to per-consumer
tracking, so it is charged against translation and summaries on the migration
day, while video had no legacy spend and remains bounded by the overall daily pace.

Paid work prioritizes active editor pins, the three promoted picks and the five
home hot-score leaders, then high-worth stories within the home ranking window.
Spending priority includes untranslated picks; video selection still requires
translated titles. The larger `sections.hot` list is not used as the home tile. Front-page titles precede other fields. Coverage
excerpts are no longer translation targets because reader projections omit them.
Validation failures receive a 24-hour model/prompt-scoped cooldown keyed by a
source hash. Paid runs restore valid published/NLLB translations before gating
new Gemini work, so cache loss does not cause automatic paid upgrades.

Gemini cache identity includes provider, model and prompt/schema version.
Normalized identical text across titles, summaries and coverage uses one key;
current roles and the union of protected identities accompany each request.
Every cache hit is revalidated against the current source/context. The legacy
`data/translations-vi.json` remains exclusively NLLB. Free mode can upgrade
NLLB output; paid mode preserves valid existing output to save its title quota. CLI dirty detection includes entry replacements/deletions. Optional
`--gemini-cache` and `--gemini-ledger` override files beside `--cache`.

Shared guards reject lost names/numbers, added numbers, repetition, implausible
length and untranslated English. Quotation structure is preserved while quoted
sentences may be translated. Catalog/model/snapshot identities, backtick tokens,
and detectable unknown names in launch/context positions are protected. These
checks cannot prove semantic equivalence or identify every unknown proper name:
representative live translations still require a human quality check. Source
conditioned glossary corrections run after both Gemini and NLLB, including
validated Gemini cache hits, so common AI terminology is consistent without
additional provider requests. Source text is untrusted data, never instructions;
the prompt prohibits summarizing, embellishing, following embedded commands or
inventing facts.

`translation` records `requested_provider`, actual `provider` (`gemini`, `nllb`,
`mixed`, `original`), `providers`, `models`, and `provider_counts` for distinct
accepted strings. `gemini` records safe status/error codes, requests, cache hits
and new translations. Existing aggregate status/counts/error_vi remain; license
is NLLB's only when NLLB output is present. `model_ready` continues to mean NLLB
weights actually loaded. Originals remain usable if the optional step fails.
Offline proof: `python -m unittest discover -s tests -p "test_translat*.py"`.
Tests use fake transports and model factories; they do not establish live
Gemini wording quality or make real API calls.

## Article-backed Vietnamese summaries

[The summary step](../radar/summarize.py) is separate from excerpt translation.
`summary_vi` remains a translation of the publisher's excerpt. The
`summary-vi-5-full` contract on `gemini-3.8-flash` generates one full summary:
4–8 standalone Vietnamese points, with no short form or separate takeaway.
Dense investigations target 7–8 points, ordinary reports 5–6, and brief
announcements 4; insufficient body evidence must not be padded. The
[system prompt](../radar/summary-system-prompt.txt) and
[JSON schema](../radar/summary-output-schema.json) are the executable contract.
Generation uses one story, low thinking and a 4,096-output-token ceiling.
The response contains an evidence-bound editorial title, points, used source IDs,
limitations and a ready/insufficient-evidence status. It never supplies URLs.
`editorial_headline_vi` is separate from the complete `title_vi` translation.

[Evidence selection](../radar/summary_sources.py) keeps whole paragraphs across
the article, prioritizing openings, endings, limits, responses and results.
The outlet window is 8,000 characters; one linked official primary post may
contribute up to 10,000. Up to two distinct coverage excerpts contribute up to
1,500 each, within a 16,000-character shared source cap and a 24,000-character
serialized story cap. The primary must be an in-body HTTPS link to a detailed
post on a supported official host; no search or model browsing discovers sources.
A blocked primary retains its discovered source link with `missing_primary`,
without pretending its body was read. Paragraph omissions set `partial_source`.
Robots, paywall, redirect and short-text skips remain enforced; a headline or
publisher excerpt alone never becomes a full summary.

The reader fetches robots.txt with the same honest `AI-Radar` user agent as
article requests. Parsed rules are cached per origin, but permission is checked
for each article path. HTTP 401/403, other unavailable rules and redirects
remain blocked; a 404 permits reading. The extractor reads semantic
`article`/`main` regions, explicitly labelled Framer blog content, and Pandaily's
matching public post body from Remix loader data. Labelled `entry-content` takes
precedence over a surrounding `main` that also contains authors or unrelated
news; otherwise the innermost semantic `article` is preferred. Embedded data is parsed as
JSON, never executed, and must match the requested publisher and article slug.

The [offline article fixtures](../tests/fixtures/summary-articles/index.json)
are synthetic structure replicas with self-authored titles and body text.
They preserve the semantic regions, Remix loader references, Framer labels
and excluded navigation/recommendation regions used by the extraction tests.
Publisher URLs remain only to exercise host and slug matching; these fixtures
contain no captured publisher prose and do not establish live source health.

[Input preparation](../radar/summary_pipeline.py) prioritizes paid work using
the shared reader order: editor picks, promoted stories, hot leaders, then worth
and recency. The free route uses worth and recency within the ranking window.
No ranking or budget constants change. An input that cannot retain at least
300 article characters is skipped with `skipped_reasons.input_limit`.
Cache identity includes the fitted evidence, all source hashes, source links,
selection version, model, prompt version, prompt text and schema. Fetch time
alone does not invalidate an otherwise identical input.

[Validation](../radar/summary_validation.py) checks exact schema and IDs, 4–8
nonduplicate points, complete responses, lengths, safe markup and source/ref
consistency. Facts must cite supplied body paragraphs; headlines and engagement
metrics cannot license body facts. Checks reject unsupported names and numbers,
known number/unit and funding/valuation swaps, selected polarity errors, missing
replay qualifications, English connective prose and long verbatim overlaps.
Grounded English proper nouns, GPU punctuation, numeric notation such as
`7.5 billion` to `7,5 tỷ`, and `a third` to `một phần ba` are supported.
These deterministic checks are not a general semantic verifier: attribution,
conflicts, translated names and novel relations still need live editorial review.
The prompt requires independent paraphrasing and limits direct quotations;
passing a regex is not a copyright or factuality guarantee.

There is at most one new story per run, with one separately reserved retry
only on HTTP 503. Free summaries retain the rolling 12-attempt/25,000-token
allowance in `summary-gemini-ledger.json`. Paid summaries use their separate
100,000-token UTC-day share in the durable paid ledger; the old free allowance
cannot constrain or authorize paid work. UTF-8 request bytes plus the full
output ceiling are reserved before transmission. Missing usage keeps that
conservative reservation. At the ledger's 2026 rate, the summary share costs
at most USD 0.375/day or USD 11.625/31 days. The shared USD 0.57 daily pace and
USD 20 monthly cap always take precedence, including after rate changes.

`summary-article-inputs.json` stores fitted article evidence for 24 hours keyed
by ID, outlet URL, title, excerpt and coverage identity. Entries also require
the current prompt version; old short/full caches cannot be restored. It is restored with the summary cache
before credentials/quota gating; valid cached points for later stories are
not blocked by the first uncached story. Changed source fields or expired
evidence require fetching again. No raw article text enters the site payload.
The workflow restores and saves all four summary files together: generated
points, the free attempt ledger, article failures and fitted article evidence.
The unique run/attempt key falls back to the current branch and then main;
any changed file triggers saving. A cache miss before any successful summary
or after cache eviction does not by itself show a restore/save mismatch.
The failure cache remembers unfittable input, rejected points and unsuccessful
attempts for 24 hours, so the next run advances rather than paying repeatedly
for the same top story. Sentence-leading ASCII entities are grounded too;
Vietnamese sentence starts are allowed without treating them as foreign names.

Daily video identity uses the saved date/completion record, independently of
current picks. Paid attempts also record the date in the durable ledger on
finalization, including rejected attempts. The 12,000-token video share covers
the real three-story request captured on October 10, 2026: 8,309 reservation
tokens, leaving 3,691 tokens (44.4%) of headroom. The share costs at most
USD 0.045/day or USD 1.395/31 days at the 2026 ledger rate. It is funded by the
overall daily pace; title and article-summary shares remain unchanged. The
request retains its full evidence, instructions, schema and grounding checks.
Requests above the share still skip with `paid_video_daily_tokens`; unavailable
run/day/month money, interrupted holds, provider failures and rejected
output can also prevent a fresh script. Budget admission does not guarantee
successful model generation.

The finalizer logs `Gemini paid pacing` JSON with `day`, `daily_micros`,
`monthly_micros`, `run_micros`, `hold_micros`, `consumer_micros`,
`pending_micros` and `daily_pace_micros`. Divide micros by 1,000,000 for
ledger-USD. These conservative ledger figures are not Google's invoice.

`summary` reports status, new summaries, cache hits, pending stories, requests,
tokens, trimmed inputs, input characters, exact request bytes, selected source
characters, skip counts/reasons and rejections. Each CLI run also logs
`Summary contract: summary-vi-5-full; model=gemini-3.8-flash; full=4-8 points; max_source_chars=16000; max_output_tokens=4096`.
Missing credentials, missing route confirmation or a zero configuration limit
report a safe error; restored cache can still provide points. Active work reports `ok`, `cache`, `partial` or `failed`.
Budget exhaustion and unreadable sources legitimately produce no new summary.
The `stories` denominator counts eligible non-event stories in the ranking
window, not the one-story request limit. Read production diagnostics from the
`Summarize stories` step; offline CLI tests use a stub provider and do not
measure production requests or spend.
The snapshot marks `machine_written`; individual summaries retain
`key_points_machine`, `key_points_source` and `key_points_prompt_version`.
Previously validated points survive recollection only while the primary URL,
title and publisher excerpt match; a rejected refresh removes old points.

The shared [story renderer](../site/story.js) and
[static HTML renderer](../radar/story_pages.py) show machine-labelled key points
with trusted outlet/primary source links and applicable source limitations.
There are no reading-mode headings, toggles, short paragraphs or takeaway lines.
A valid full summary replaces the excerpt in both modal and static reader views.
Missing or obsolete summaries leave an honestly labelled “Đoạn trích bài viết”.
Feed cards do not consume any generated summary fields. Public projection exposes
only points, editorial headline, trusted source names/URLs, limitations and summary
version/disclosure fields; source paragraphs and evidence refs stay in private
cache inputs, never the site payload. No captured publisher text belongs in tests.
The video request reserves its own output ceiling, independently of the larger
article-summary ceiling.
Offline examples and regression checks:
`python -m pytest tests/test_summary.py tests/test_summary_examples.py tests/test_summary_display.py tests/test_story_pages.py tests/test_retention.py -q`.
Offline stubs verify the path and guards, not Gemini's live editorial quality.

## Measurement continuity and source policy

Fresh displayed evidence and reusable measurements have different lifetimes.
An outage must remain visible in the current snapshot without replacing a useful
measurement baseline. [Baseline policy](../radar/measurement_cache.py) owns
validation and promotion thresholds; [CLI publication](../build.py) owns the
independent files and optional `RADAR_OUTPUT` / `RADAR_BASELINE` overrides.
Use separate output and baseline paths when collecting isolated local evidence.

Promotion favors continuity over accepting every successful collection. The
active-source quorum rejects broad outages; per-source measurement retention
rejects truncation hidden by healthy unrelated feeds. This may withhold a
legitimate smaller feed. An expired baseline becomes unavailable instead of
acquiring a new timestamp, so this policy never promises uninterrupted velocity.

The [workflow](../.github/workflows/update.yml) owns branch-to-main cache lookup
and conditional saving. The isolated baseline namespace deliberately starts
cold rather than trusting legacy display-snapshot caches; a qualifying main
run establishes the shared seed.

Disabled is an inventory decision, not a successful empty response or a fresh
HTTP failure. [Source inventory](../radar/catalog.py), [legacy lab inventory](../radar/feeds.py)
and [collection boundary](../radar/pipeline.py) own that distinction. The
[dated source decisions and disabled-source contract](p1-r2-source-status.md)
record publisher evidence, replacement trade-offs and re-enablement criteria;
[request-suppression tests](../tests/test_source_replacements.py) provide the
executable proof.

## Verification boundary

Publication eligibility is separate from ranking-measurement continuity.
[Publication policy](../radar/publication.py) rejects an unusable candidate
before [the CLI](../build.py) replaces displayed data. A rejected attempt must
not relabel an older snapshot as fresh. Workflow promotion of the last-published
reference follows a successful Pages deployment; a collected candidate alone
is not evidence that readers received it.

Individual malformed rows in `updates`, `hf_releases`, `live`, `events` and
`repos` are removed before assessment and writing. Their names/URLs, supplied
timestamps, event dates/precision, live status and JSON values are validated;
unknown timestamps remain unknown. `prepare_publication` returns the filtered
candidate and diagnostics without mutating the collected input. Both the accepted
snapshot and `data/publish-status.json` carry `dropped_projection_rows`, an object
with one nonnegative integer count for each of those five arrays, including zero
counts. Counts describe this attempt, not cumulative source failures; original
source collection counts remain unchanged. A rejected attempt still records its
drop counts in diagnostics.

Filtering cannot repair a broken array container, schema, source/story identity,
coverage or section reference. The nonempty remote-backed story requirement,
two-thirds non-tool source quorum and freshness checks still reject the whole attempt,
leaving output, publication cache, measurement baseline and sitemap unchanged.
Optional `group: tool` sources retain diagnostics but do not affect this news quorum.
Loading a prior publication remains strict and never silently sanitizes it.

The additive `freshness` object on an accepted snapshot has this consumer contract;
the publication module owns values and thresholds:

| Field | Meaning |
| --- | --- |
| `generated_at` | Candidate collection time, UTC ISO timestamp. |
| `expected_interval_seconds` | Intended cadence, not a scheduling guarantee. |
| `stale_after_seconds` | Age threshold used by freshness policy. |
| `previous_generated_at` | Prior accepted publication time, or null when unknown. |
| `previous_age_seconds` | Prior publication age at assessment, or null. |
| `previous_stale` | Whether that measured prior age exceeds the threshold. |
| `gap_seconds` | Candidate-to-prior timestamp difference, or null. |
| `scheduler_gap` | A measured gap beyond the threshold; not a diagnosis of GitHub's scheduler. |

Attempt diagnostics are written separately to `data/publish-status.json`,
including `published`, `reason`, `attempted_at`, source success/failure counts,
and the same `freshness` evidence. Here `published` means eligible for local
publication, not a confirmation that the later Pages deploy succeeded. A failed
build's diagnostic artifact remains useful without overwriting the last good
site. Paths and overrides are owned by [the CLI](../build.py).

Follow the [README](../README.md) for local commands and the workflow for runner
steps. A green build or test suite alone does not establish live coverage.
Inspect the collected artifact's per-source errors and HTTP evidence, then
review actual clusters. Branch verification and production deployment have
different authority; inspect the workflow's branch guards before dispatching.

## Reader snapshot

### Editorial image and headline producer contract

[Headline extraction](../radar/headlines.py) adds `headline` and, when a
translation exists, `headline_vi` to stories and coverage. Each is at most 140
characters. A long title uses its first sentence of at least 35 characters that
fits the limit; otherwise it ends at a word boundary with an ellipsis. Source
`title`, translated `title_vi`, summaries, identities and worth fields remain
unchanged. Assembly and the translation CLI refresh these derived fields in the
full snapshot; reader and first-screen projections also derive them from current
titles. The shared writer leaves its input evidence unchanged. This extraction does not invent a
summary or claim to rewrite a headline editorially.

The frontend consumer must select `headline_vi` alongside the same object's
`title_vi`, and `headline` alongside its `title`. Coverage-level translation
fallback must still carry that coverage item's own attribution and original.
The existing `title` remains the full original for the “Translated” treatment.
These additive producer fields require consumer integration; they do not change
old frontend code automatically.

[X parsing](../radar/x_collector.py) independently rejects `replied_to`
references, reply-user/status metadata and mention-led conversational text,
even if the search query's `-is:reply` filter leaks. Assembly applies the same
rule to fresh observations and retained coverage before clustering/retention,
ranking and section generation. A story with only replies disappears; mixed
coverage survives with a remaining representative. Quotes and mentions inside
an original post survive. An original post beginning with `@handle` can be
excluded by the conservative legacy heuristic; stored snapshots cannot prove
reply identity from text alone.

[Image screening](../radar/image_quality.py) uses local layout heuristics, not
a model API. Known repository preview endpoints and explicit logo, screenshot
or banner asset names are rejected. Pixel inspection requires **Pillow installed
before collection**. The [update workflow](../.github/workflows/update.yml)
pins the decoder in its required `Install image decoder` step before offline
tests and collection. For local collection, use that same install command.
Core collection can run without it, but uninspected source images are withheld.
The later optional translation-library installation is independent of this step.

Inspection caps downloads at 5 MiB and decoded images at 80 million pixels for
resource safety, then measures at most 400 × 300 pixels. JPEG draft decoding
reduces memory use for large photographs. Images at least 64 pixels on each
side are eligible regardless of aspect ratio. The policy favors retaining
photographs: a small label or aligned scene texture alone is insufficient to
reject an image. Flat-color rejection requires stronger dominance; glyph rows
require substantial coverage and a sufficiently smooth surrounding image.
Thresholds and diagnostic metrics live in the screening module. Policy version
2 invalidates earlier cached decisions, including rejected photographs.
This heuristic cannot distinguish every logo from a minimalist illustration,
or every photographed logo from a subject. Download limits can still withhold
large photographs; truncated bytes are never treated as a complete picture.
Missing decoders, unreadable images and expired/unversioned approval records
fail closed. Source-image checks are cached by URL and policy version for 48
hours; old seeds and carried images receive the same checks as fresh candidates.

Screened stories carry `image_screened: true`. A screened story uses its
approved `story.image` (source photo or pipeline AI illustration) first, then
the site's own factual cover; static story pages fall back to the site's
`site/og-image.png` for sharing. Third-party fallbacks (`site/feed-images.json`,
coverage media, GitHub/HF/YouTube previews, the client AI manifest) stay
blocked. The AI provider's window, 8,000-neuron daily cap, per-run limit and
ledger behavior are unchanged.

Offline contracts: [content quality](../tests/test_content_quality.py),
[source images](../tests/test_images.py) and [AI fallback](../tests/test_ai_images.py).
Synthetic pixel fixtures exercise the algorithms; they do not measure precision
on publisher photos. Network access and frontend integration remain separate
release checks.

Repository rankings by field are a separate optional data contract:
[field rankings, history and live verification](field-rankings.md). Their
`field-rankings.json` does not affect news publication eligibility or replace
the existing Trending repository projections.

The homepage preloads `site/data/radar-ui.json`, a compact, complete reader
projection of the full `radar.json`. It keeps every story ID, section ordering,
story/detail text, translated titles, repository data, calendar information,
source failure/disabled state and original `generated_at`. It removes duplicated
legacy collections and observation/ranking evidence that the page does not use.
The full snapshot remains the authority for collection, translation, archives,
health checks and raw evidence; the projection is never fed back into them.

[The shared writer](../radar/site_payload.py) generates both files after accepted
collection and again after optional translation, including fallback/failure to
original text. Custom CLI output paths receive a sibling `<stem>-ui.json`.
Rejected collection leaves both previous files unchanged. Each replacement is
atomic; if writing the projection fails after the full snapshot changed, its old
copy is removed. Initial load and periodic polling fall back to full `radar.json`
when the projection cannot be fetched, parsed or validated. An explicit
`?data=data/<file>.json` remains an isolated maintainer override without fallback.

Offline invariance and failure checks live in
[test_site_payload.py](../tests/test_site_payload.py). The
[reader verifier](../tests/verify-reader-payload.mjs) executes the page's actual
markup functions against both artifacts, including all story details, expanded
chapters, repository filter combinations and freshness labels. This proves
content equivalence; browser layout, LCP and Lighthouse scores still require
rendered measurements.

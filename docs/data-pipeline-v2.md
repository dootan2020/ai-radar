# Data pipeline v2

AI Radar is a map to original reporting, research and discussion. Its data must
separate a collected observation from an editorial ranking decision. Unknown
times, counters and failed sources must remain visible as unknown or failed.

## Where to work

- [CLI publication](../build.py) and [collection boundary](../radar/pipeline.py).
- [Source inventory](../radar/catalog.py), [RSS/media](../radar/v2feeds.py),
  [community](../radar/community.py), [paper/repository APIs](../radar/discovery.py).
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

## Decisions to preserve

Feed count is not independent corroboration: mirrors and multiple endpoints of
one publisher count once. Different discussion threads retain their own
measurement identity even when they link to the same story. An event occurrence
also needs its own identity when an official landing page serves several dates.

Ranking is an editorial heuristic, not an assertion of objective importance.
Missing observations cannot be replaced with plausible zeroes. A repository's
creation time is not its model's release date. Date-only event announcements
must not acquire invented midnight timestamps or timezones.

Hot ranking uses distinct publishers as measured breadth. Stories with measured
engagement counters retain the 24-hour freshness half-life and 72-hour scoring
window. Stories without counters can score from independent publisher breadth
with a 72-hour half-life and a seven-day scoring window. Mirrors still count as
one publisher, and age alone never creates a score.

The previous snapshot exists only to compare measurements. Republishing its old
content with a new build time would mislead readers about freshness. Frozen
fixtures support reproducible tests; they do not establish current source health.

The owner maintains the calendar from official pages. Reverify a date before
changing its record and retain the official evidence URL. A source outage must
not silently erase the distinction between a valid empty feed and a failed feed.

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
events by itself.

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

Live Gemini requests require **both** `GEMINI_API_KEY` and
`RADAR_GEMINI_FREE_TIER_CONFIRMED=1`. The latter is an operator assertion:
before setting the repository variable, verify in AI Studio that the key's
project has no billing attached and inspect its current free-tier quotas.
Code cannot verify billing or force a billed project onto a free tier; Google
has no per-request free-only parameter. Never attach billing to enable this
feature. The key is passed only to the translation step, only in the HTTPS
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

Application ceilings are deliberately smaller than the twice-hourly schedule:
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
ledger starts a new local window. Keep the upstream project on its free tier.

Gemini cache identity includes provider, model and prompt/schema version.
Normalized identical text across titles, summaries and coverage uses one key;
current roles and the union of protected identities accompany each request.
Every cache hit is revalidated against the current source/context. The legacy
`data/translations-vi.json` remains exclusively NLLB and never blocks Gemini
upgrades. CLI dirty detection includes entry replacements/deletions. Optional
`--gemini-cache` and `--gemini-ledger` override files beside `--cache`.

Shared guards reject lost names/numbers, added numbers, repetition, implausible
length and untranslated English. Quotation structure is preserved while quoted
sentences may be translated. Catalog/model/snapshot identities, backtick tokens,
and detectable unknown names in launch/context positions are protected. These
checks cannot prove semantic equivalence or identify every unknown proper name:
representative live translations still require a human quality check. Source
text is untrusted data, never instructions; the prompt prohibits summarizing,
embellishing, following embedded commands or inventing facts.

`translation` records `requested_provider`, actual `provider` (`gemini`, `nllb`,
`mixed`, `original`), `providers`, `models`, and `provider_counts` for distinct
accepted strings. `gemini` records safe status/error codes, requests, cache hits
and new translations. Existing aggregate status/counts/error_vi remain; license
is NLLB's only when NLLB output is present. `model_ready` continues to mean NLLB
weights actually loaded. Originals remain usable if the optional step fails.
Offline proof: `python -m unittest discover -s tests -p "test_translat*.py"`.
Tests use fake transports and model factories; they do not establish live
Gemini wording quality or make real API calls.

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

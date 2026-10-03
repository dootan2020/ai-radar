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

## Decisions to preserve

Feed count is not independent corroboration: mirrors and multiple endpoints of
one publisher count once. Different discussion threads retain their own
measurement identity even when they link to the same story. An event occurrence
also needs its own identity when an official landing page serves several dates.

Ranking is an editorial heuristic, not an assertion of objective importance.
Missing observations cannot be replaced with plausible zeroes. A repository's
creation time is not its model's release date. Date-only event announcements
must not acquire invented midnight timestamps or timezones.

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

## Headline translation

Story and coverage titles, repository descriptions and stream titles get a
Vietnamese machine translation from [an optional step](../radar/translate.py)
that runs after `build.py`, with libraries pinned in
[requirements-translate.txt](../requirements-translate.txt). The core pipeline
stays stdlib-only. Translations sit beside the original as `title_vi` /
`description_vi`; the page shows the Vietnamese first and the original underneath,
labelled "dịch máy". Names, ids, event titles and strings the model returned in
English keep only the original. A translation that drops or adds a number, loses
a name, repeats itself or shrinks too far is refused, and post-translation term
fixes ("agent", "khung chạy", "tiên phong", "tinh chỉnh", "bài đo chuẩn") fire
only when the English uses the term. The snapshot's `translation` record says
what happened: status, counts, pending strings, refused examples and a reason in
`error` / `error_vi`.

The step can never cost the page: a missing library, failed download, error or
the 600-second budget (`RADAR_TRANSLATE_BUDGET`) leaves the original titles, and
what was not translated waits for the next run. Each English segment is
translated once; the workflow keeps the translation cache
(`data/translations-vi.json`) and the model (`HF_HOME`, safetensors, JSON and
tokenizer only) in `actions/cache` between runs.

The [README attribution and license notice](../README.md#optional-translation-and-attribution)
owns the noncommercial constraint. The pinned model revision belongs to
[the translator](../radar/translate.py). DeepL Free remains a previously noted
replacement option, not an active integration; no service switch was made.
Protected identities come from
[collector/catalog metadata, the model classifier and snapshot context](../radar/translation_names.py);
unfaithful cached output also falls back to the original. Names are not guessed
from every capitalized English word. [Translation tests](../tests/test_translate.py),
[name regressions](../tests/test_translation_names.py), and
[display tests](../tests/test_translation_display.py) are the proof.

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
two-thirds source quorum and freshness checks still reject the whole attempt,
leaving output, publication cache, measurement baseline and sitemap unchanged.
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

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
- [Detailed consumer contract](../plans/261002-1630-ai-radar-v2/hop-dong-du-lieu-v2.md).

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

Follow the [README](../README.md) for local commands and the workflow for runner
steps. A green build or test suite alone does not establish live coverage.
Inspect the collected artifact's per-source errors and HTTP evidence, then
review actual clusters. Branch verification and production deployment have
different authority; inspect the workflow's branch guards before dispatching.

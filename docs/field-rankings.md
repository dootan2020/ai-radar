# Repository field rankings

A separate, bounded catalogue of repositories with publisher-declared open-source
license metadata and independent task evidence. It is not a global leaderboard,
quality benchmark, installation recommendation, or manual classification audit.
News and Trending publication rules are unchanged.

## Fields and membership

[field_config.py](../radar/field_config.py) owns the 17 fields: Coding, Video,
Images, Audio / voice, Animation, Translation, Agents & automation, MCP & agent
tooling, RAG & search, Model evaluation, Local model running, Training &
fine-tuning, Music, OCR & documents, Robotics & embodied AI, Trading & finance,
and Games & game AI. All discovery topics come from the
[measured topic table](../plans/nhap/topic-counts-2026-10-03.md).

Topics nominate candidates; a separate task statement in the description must
admit each field. Broad game-development/reinforcement-learning tags do not admit
generic engines or learning libraries. Trading and games require an independent
AI signal in the description. Robotics requires learning, embodied intelligence,
or another explicit AI task. Agents includes RPA, Android, browser and workflow
automation; animation also accepts programmatic animation. These exceptions are
intentional. Fields are independent and a repository can qualify for several.
Music has its own field instead of being counted solely as voice/audio.

Repositories must have at least 100 stars, have been pushed within 30 days, and
not be archived or forks. A conservative SPDX allow-list excludes unknown,
custom, restricted and noncommercial licenses. Rows retain the declaration and
`open_source_verified: false`: this is not a legal/source audit. Awesome lists,
collections of tools/skills/prompts, tutorials, courses, books and surveys are
excluded by generic rules. Ordinary prose such as 'of course' is not a course.
No repository or organization name is a special classification rule.

Discovery queries one topic per Search request, without OR operators, to
stay within GitHub repository search limits. Each query fetches one Search page of up
to 100 rows sorted by total stars. Diagnostics report each topic's actual
`total_count`, `topics` and `count_scope: query_group`. This bounded sample can miss projects. Thin fields stay
empty, tracking or partial; data is never padded.

Every eligible candidate competes by total stars then numeric repository ID;
incumbency gives no priority. Up to 20 fresh rows are selected per field.
Observed counters for all admitted discovery results are saved, including rows
outside the visible selection, so a later entrant can have a real baseline.
Tracked IDs absent from discovery receive bounded direct `/repositories/{id}`
refreshes, oldest attempt first. Deferred/failed refreshes are explicit and make
collection incomplete. Names may change; history uses immutable numeric IDs.

## Public schema 1

`python -m radar.field_publish prepare --remote <repository-git-url>` writes
`site/data/field-rankings.json`, separate from the news artifacts. Tests use
isolated temporary outputs. Public schema remains 1 with additive provenance.

| Property | Meaning |
| --- | --- |
| `generated_at` | UTC collection timestamp; reuse/fallback never advances it. |
| `metric`, `scope` | `stars_net_7d`, `bounded_topic_catalogue`. |
| `stale_after_seconds` | 129600 (36 hours); row timestamps matter too. |
| `complete` | Every discovery group and eligible tracked refresh succeeded. |
| `config_fingerprint` | SHA-256 of field definitions, classification gates and selection settings. |
| `fields` | 17 entries in current configuration order after fresh collection; historical output may differ. |
| `requests` | Actual aggregate endpoint URLs/statuses; no tokens, bodies, or stargazer identities. |
| `refresh_diagnostics` | Actual failures and explicitly deferred IDs. |
| `limits` | Page size, API budgets, minimum rank count, and window tolerance. |

Field rows retain description evidence, matching topics, license provenance,
tracking/observation timestamps, stars and measurement endpoints. `ranked` sorts
by signed seven-day net growth, then total stars, then ID. Zero and negative
values are real measurements. `tracking` has no rank; it includes insufficient
history and retained stale evidence. Up to 20 fresh rows plus 20 stale rows can
appear there. Consumers must not imply a tracking delta is current.

Statuses remain `ready`, `tracking`, `empty`, `partial`, `stale`, `unavailable`.
Ready requires at least five measured ranked rows and no source failure. One to
four ranked rows remain visible with `partial` and
`status_reason: insufficient_ranked_rows`; source failures use
`status_reason: source_incomplete`. Zero ranked rows with fresh candidates are
tracking. Preparation failure retains prior evidence unranked with stale flags,
original timestamps, and `preparation_status: failed_retained`.

## Exactly what is measured

Net growth is current observed total minus an earlier observed total. The earlier
point must be within three hours of current time minus seven days. Actual
`window_start`, `window_end` and `window_seconds` are exported. Exactly 604800
seconds has `approximate: false`; other admitted durations are approximate.
Nearest baseline wins, earlier timestamp breaks ties. Missing observations are
never interpolated, estimated from total stars, or substituted from another
metric. Failed/rotating refreshes can leave gaps and unranked repositories.

The collector makes **zero** `/stargazers/history` calls. GitHub's native history
counts calendar-week added-star events, not rolling net growth, so it cannot
supply this metric. The legacy parser remains for compatibility/tests; new rows
use `native_history: {status: not_requested, usable_for_net: false}`.
See [GitHub's starring API](https://docs.github.com/en/rest/activity/starring#get-repository-star-history).

## History, compatibility and failure recovery

The isolated `radar-field-history` branch contains exactly one plain file:
`field-history.json`. State schema 1 keeps snapshots, catalogue, first_seen and
last_output. First successful ID/date counters are immutable. Keep 35 dates;
first_seen survives retention and catalogue eviction. Normal push, exact base
commit comparison and remote read-back prevent overwriting concurrent history.
A failed restore is never treated as a cold start.

Historical validation accepts safe unique field IDs in any order and former
field sets. It is independent of today's FIELDS list. Safety ceilings remain:
64 fields, 2000 catalogue IDs, 10000 points/date, 100000 first_seen IDs, 100 ranked
or 200 tracking rows per historical field, and a 64 MiB state file. The daily
point bound covers four attempts with up to 2080 admitted observations each.
Malformed counters, identities, URLs, dates, duplicate field IDs, future snapshot
evidence and unexpected branch paths/types still fail validation. Current output
and catalogue retain the tighter configured limits.

Same-day output reuse requires matching config_fingerprint. A complete matching
collection is reused for the UTC day; incomplete matching output is reused for
six hours. Changing field order, definitions, classifier or selection settings
invalidates that cache while retaining measured history.

The workflow restores a separately cached validated last-good public output
**before** Git restore/collection. Preparation preserves the newest valid output
from cache, existing output and the history branch before risky work. Exceptions
restore that prior evidence with stale flags. Process timeout leaves the earlier
artifact available with its original timestamp; it cannot invent freshness.
Candidate validation/read-back happens before publishing replacement output.
Cached output is separate from the data branch, so failed pushes do not erase
reader evidence. Preparation seeds the cache file from retained validated history
before collection; the workflow saves it after either successful or failed
preparation. Thus a cold output cache plus a failed collection can still carry
the restored history to the next fresh runner.

## Independent retry checkpoint

The [workflow](../.github/workflows/update.yml) uses `radar.field_checkpoint` to
prepare a fixed six-hour UTC slot key. Before collection, it checks the exact
Actions cache key and saves a unique attempt claim on a miss. It removes the
local marker, restores the exact cache key, and verifies that the restored claim
belongs to this attempt. An older reservation cannot authorize a new attempt,
even if cache lookup/save return misleading success outcomes with warnings.
Only this successful verified save admits work. Cache restore
errors, save failures or missing read-back skip optional collection. A successful
cache/save action outcome alone is insufficient because the action can warn
without saving. Manual reruns use the same guard. Data-branch failure therefore
does not trigger another collection every half hour on a fresh runner.

There are at most four admitted slots per UTC day, assuming retained Actions
cache entries. Slots are fixed, not a rolling six-hour delay: a failed-state
attempt near 05:37 and another at 06:07 can both be admitted, but subsequent runs
in that slot are skipped. Cache eviction/loss remains an infrastructure limit;
this checkpoint is independent of Git persistence, not permanent storage.

## API and runtime budgets

The current configuration uses 59 single-topic Search queries. Hard ceilings per
attempt: 60 Search, 80 core refresh, 140 total requests; current configuration
therefore permits at most 139 calls. No retries or native-history probes run.
Search starts are at least 2.5 seconds apart (24/minute), leaving headroom below
the authenticated 30/minute limit for existing news Search. All requests share
a 210-second hard fetch deadline. Slow networking can yield partial output before
any call cap is reached; these are ceilings, not completeness promises.

Core requests stop when GitHub reports at most 500 remaining, reserving quota for
news and other workflow traffic. The normal repository GITHUB_TOKEN allowance is
1000 requests/hour, shared with news. Two boundary-slot attempts could use up to
160 core requests/hour; the quota reserve still applies. Search has its own
bucket. Primary exhaustion stops its bucket; secondary rate limits, Retry-After
and 429 stop both. Redirects are refused; tokens never leave api.github.com.
See [Search limits](https://docs.github.com/en/rest/search/search) and
[REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

Field preparation, fallback/checkpoint actions and uploads are optional and
individually time-bounded. Preparation remains a six-minute step, containing the
210-second API budget plus isolated Git validation. The existing update job is
49 minutes, preserving the original 30-minute allowance plus 19 explicitly bounded
field-step minutes. Persistence is a separate five-minute main-only optional job with
contents:write; deploy depends only on update. No field result changes news quorum.

## Remaining live proof

Offline tests prove logic, not hosted-runner access, cache service persistence or
real topic coverage. Before claiming live operation, inspect field diagnostics
from an authorized run: actual Search HTTP results/group counts, observed budget
stops, exact attempt-key read-back, last-output recovery, and the data branch head.
Later inspect a real seven-day counter pair. No synthetic rows substitute for
that proof. Missing GITHUB_TOKEN is diagnostic, never a request for a new PAT or
paid model/API usage.

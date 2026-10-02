# Source repair progress

## Session Intent

Resolve the five failed sources from runner 36992692119 through verified
legitimate same-publisher alternatives or explicit disabling with reasons.
Never impersonate a browser, bypass a host block, or claim local evidence proves
runner availability. Keep disabled sources visible and never request them.

## Files Modified

- `docs/p1-r2-sources-progress.md`: intent and investigation evidence.
- `radar/catalog.py`: official VnExpress latest-feed replacement; explicit
  disabled policy for three Substack endpoints.
- `radar/feeds.py`: disabled policy for the invalid DeepMind RSS endpoint.
- `radar/pipeline.py`: record disabled sources before scheduling active jobs.
- `tests/test_source_replacements.py`: five synthetic policy/parse regressions.
- `docs/p1-r2-source-status.md`: per-source primary evidence and policy contract.

## Decisions Made

- The current collector requests every configured source. Disabled sources need
  a distinct policy record before request scheduling, not a fabricated empty feed.
- The existing honest `AI-Radar/1.0` User-Agent remains unchanged.
- Official pages establish publisher ownership; they do not establish that a feed
  can be fetched or parsed on the hosted runner.
- VnExpress alternate is its official latest-news RSS, with the existing AI
  filter preserved. Four sources disabled pending runner evidence. Coordinator
  confirmed this selection; Import AI author's current site stays a candidate.

## Current State

- Read README, review, data-pipeline documentation, affected collectors, transport,
  pipeline and related offline tests. Stdlib Python, RSS/Atom via ElementTree;
  initial v2 endpoints introduced in commit `3b7457e`.
- Supplied runner evidence: three Substack feeds HTTP 403; DeepMind HTTP 200 with
  `ParseError: not well-formed (invalid token): line 1, column 0`; VnExpress 404.
- Local direct HTTP attempts all fail with `URLError` / `WinError 10013` before
  receiving a response. No live feed captures are available from this environment.
- Opened official Dwarkesh, Latent Space, Import AI, Jack Clark, DeepMind, and
  VnExpress RSS pages using the web tool. Final decisions in source-status doc.
- Five focused regression tests pass. The in-memory negative control removed
  the disabled scheduling branch and produced three expected failing/error
  cases, including detection of requests to all four disabled endpoints.
- `python -m unittest discover -s tests`: all 181 current tests pass in 2.179s.
  This total includes concurrently added tests from the core/cache workers.
- Implementation and source-status report complete. No live build, push or
  deploy performed; no transport/parser behavior or User-Agent changed.

## Next Steps

- Coordinator reviews the diff and verifies the branch runner artifact before
  claiming the new VnExpress endpoint is operational.

## Câu hỏi

- No owner decision needed. Hosted-runner availability remains unverified.

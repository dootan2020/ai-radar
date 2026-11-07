# Progress: parallel writer batches

## Session Intent
Halcyon newsroom: write in parallel so every cycle has time to fix and score. Run the writer's batches
concurrently so each cycle has time to rewrite and rescore (captain, 2026-11-07 08:55, "Làm đi em"), without
changing what passes, failing closed exactly as today, and staying inside the writer and run budgets.

## Files Modified
- `phong_bao/newsroom.py`: `_agent_desk` runs up to `desk_concurrency()` first-lane batches at once
  (`PHONG_BAO_DESK_CONCURRENCY`, default 3); each batch's fallbacks and splits stay in its own turn; a per-lane
  semaphore honours a profile's `max_concurrent_calls`; results, raw files and events are committed in batch order
  from the main thread (`_Sink`); an admission stop records the batches before it and starts none after it.
- `phong_bao/registry.py`: validates the optional `max_concurrent_calls` (positive int).
- `phong-bao/cong-cu/codex.toml`: `max_concurrent_calls = 1` (outside the brief's declared scope; reported).
- `docs/may-rieng.md`: one sentence on the new setting (outside the declared scope; docs impact of a new setting).
- `tests/test_phong_bao_song_song.py`: 10 tests (overlap, serial equivalence incl. raw files, slow/failing
  batch isolation, queued deadline, admission stop, lane cap, setting parsing, registry validation).

## Decisions Made
- Premises checked against `C:/Users/Admin/ai-radar-phong-bao-chay/phong-bao/cycles/20261106T190008Z/job/raw`:
  7 agy writer batches 02:24:20-02:54:51 (1, 2, 2, 4, 2, 2, 2 stories), 3 rewrite-writer batches to 03:08:27,
  4 codex scorer batches 03:09-03:11:51, 6 review-writer batches all `budget_exhausted` at 03:14:20
  (= writer start 02:24:20 + 3000 s). Confirmed.
- Parallelise inside `_agent_desk`, so every desk benefits (writer, rewrite-writer, review-writer, scorer, and the
  reporter/editor/checker desks too) with one implementation and one setting. The unit of concurrency is a
  first-lane part (after the agy argument-length split), not the 60k top-level batch, otherwise agy parts inside a
  top-level batch would still run in turn.
- Default 3: the PC stalls at about 5 heavy jobs; agy calls are mostly remote-model wait. Setting 1 = old path.
- Codex capped at 1 call: ai-radar's runner uses the owner's real `~/.codex`, so concurrent calls could race on a
  rotating-refresh-token login refresh. Scorer calls take about a minute, so serial codex costs little.
- Budgets unchanged: the 02:00 replay fits in about 31 of the 50 writer minutes (see PR).
- Ordered commit (in-order prefix as futures complete) keeps raw numbering and event order deterministic.

## Current State
- Implementation and tests done; newsroom suite green at concurrency 3 and at 1. Mutation checks: serial-only
  path fails 3 new tests; completion-order commit fails 4.
- Live smoke 09:10-09:15 (scratch dir only): two real agy writer calls through `CLIRunner` on stories
  `3d9b443646b89253ccd6` and `2563b3e6ff404ee380cc` of the 02:00 cycle, `concurrency=2`, `batch_size=1`.
  Both started at 0.0 s (two agy.exe children of one python, created 09:10:26), 290.4 s and 295.3 s, both exit 0
  with one valid row each; wall 295.3 s; raw files writer-1, writer-2; no agy process or temp dir left behind.
- Full suite `python -B -m unittest discover -s tests -p "test_*.py"`: 1752 tests OK (8 skipped), 289 s.
  CI steps: `node --version` v22.14.0; newsroom tests under `py -3.11` (CI's Python): 221 OK.

## Next Steps
- Commit, push, draft PR; coordinator merges and watches the first real cycle (writer desk seconds, review-writer
  and rescorer events, viet-bu `sent` vs `budget_cut`).

# Progress: covers-flake

## Session Intent

Halcyon's publish job stops failing on a headless-Chrome start-up flake. Success: a slow or failed Chrome start-up on a CI runner no longer fails the test or the publish; a real rendering regression still fails it. Brief: `firstmate-control/.claude/worktrees/inspiring-payne-d3f969/plans/reports/su-kien/brief-covers-flake.md`. Scope: `radar/covers.py`, `tests/test_covers.py`, this file. Branch `fix/covers-flake`.

## Files Modified

- `radar/covers.py`: `render()` now tells a browser that did not start from a drawing that failed. A start-up failure (every reported failure starts with `Chrome did not start`, nothing rendered) runs the renderer up to `START_ATTEMPTS = 4` times, pausing `START_PAUSES = (5, 15, 30)` s between runs, and never pauses past the 600 s deadline. A drawing failure keeps `DRAW_ATTEMPTS = 2` (unchanged behaviour).
- `tests/test_covers.py`:
  - `RendererFailureTest` has three new tests. The first reproduces the CI failure: start-up fails on attempts 1 and 2, then succeeds on 3. It failed on the old code with `AssertionError: 2 != 3`. The second: a browser that never starts is reported in `failed`, not raised. The third: the pauses stay inside the deadline.
  - `RenderTest` asserts `(attached, failed) == (1, 0)` and prints the renderer's own log, before reading `image`. The old test raised `KeyError: 'image'` instead.

## Decisions Made

- **Root cause, as far as the scope can see it.** The launch is not in `radar/covers.py`; it is in `covers/lib/cdp.mjs`, which is outside this brief's scope:
  - `cdp.mjs:21-27`: one Chrome per launch, `--remote-debugging-port=0`, a fresh `mkdtempSync` profile, and `--no-sandbox` when `CI` is set. There is no fixed port and no shared profile, and the test suite runs sequentially (`update.yml:108`, `ci.yml:29`: `python -m unittest discover -s tests`). The brief's port, profile and parallel-clash hypotheses are therefore ruled out.
  - `cdp.mjs:28-29`: `for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100); if (!existsSync(portFile)) { proc.kill(); throw new Error('Chrome did not start: no DevToolsActivePort'); }`. This is a fixed 10 s wait. It does not watch the process exit, and `stdio: 'ignore'` (line 27) throws away Chrome's stderr, so the CI log cannot say *why* Chrome did not start. Measured here: a real Chrome writes the file in 331 ms. A `CHROME` that exits at once (`whoami.exe`) still costs the full 10 749 ms and reports only `no DevToolsActivePort`.
  - `radar/covers.py:94` (old): `for attempt in range(2)` treats a browser start-up failure like a drawing failure. On run 42846743763 (2026-11-10 15:40Z) both attempts failed the same way. The render returned `covers: {}`, `apply_covers` correctly left the story without an image, and the test then read `payload["stories"][0]["image"]` at `tests/test_covers.py:233`, which raised `KeyError: 'image'`.
- **Why retry with pauses instead of skipping:** the brief forbids skipping or weakening the test. A start-up failure drew nothing, so running again cannot hide a drawing regression. A drawing failure still gets only one more run, and `RenderTest` still fails if no cover is drawn.
- **Why not change `cdp.mjs`:** the coordinator limited this slice to two files. The fix for the actual cause belongs there, and is recommended below.

## Current State

- `python -m unittest tests.test_covers -v`: 14 tests OK, exit 0, with real Chrome on this machine (RenderTest ran, did not skip).
- With `CHROME=C:/Windows/System32/whoami.exe` (a Chrome that never writes DevToolsActivePort), RenderTest fails in 93 s with `(0, 1) != (1, 0) : r1 was not drawn:` followed by the four attempts' reasons. There is no `KeyError`.
- Chrome processes whose command line holds `covers-chrome-`: 0 before and 0 after each run.
- Committed on `fix/covers-flake`, not pushed.

## Next Steps

- **Needed for the real cause (out of this scope, coordinator's call):** change `covers/lib/cdp.mjs` `launch()` so that it:
  1. stops waiting as soon as `proc.exitCode !== null` and puts the exit code plus the last stderr lines in the error (needs `stdio: ['ignore', 'ignore', 'pipe']`);
  2. raises the DevToolsActivePort wait from 10 s to about 30 s, puppeteer's default launch timeout;
  3. adds `--disable-dev-shm-usage` on Linux.

  The next CI failure would then name its cause, and a cold-disk start that takes longer than 10 s would pass on the first attempt.
- Watch the next runs of `Update AI Radar` for `Covers: Chrome did not start; trying again`. If it appears and attempt 3 or 4 succeeds, the retry is doing its job. If all four attempts fail, the cause is not transient, and the `cdp.mjs` change above is required.

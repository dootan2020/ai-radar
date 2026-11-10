# Progress: covers-flake

## Session Intent

Halcyon's publish job stops failing on a headless-Chrome start-up flake. Success: a slow or failed Chrome start-up on a CI runner no longer fails the test or the publish; a real rendering regression still fails it. Brief: `firstmate-control/.claude/worktrees/inspiring-payne-d3f969/plans/reports/su-kien/brief-covers-flake.md`. Scope: `radar/covers.py`, `tests/test_covers.py`, this file. Branch `fix/covers-flake`.

## Files Modified

- `radar/covers.py`: `render()` now tells a browser that did not start from a drawing that failed. A start-up failure (every reported failure starts with `Chrome did not start`, nothing rendered) runs the renderer up to `START_ATTEMPTS = 4` times, pausing `START_PAUSES = (5, 15, 30)` s between runs, and never pauses past the 600 s deadline. A drawing failure keeps `DRAW_ATTEMPTS = 2` (unchanged behaviour).
- `tests/test_covers.py`:
  - `RendererFailureTest` has three new tests. The first reproduces the CI failure: start-up fails on attempts 1 and 2, then succeeds on 3. It failed on the old code with `AssertionError: 2 != 3`. The second: a browser that never starts is reported in `failed`, not raised. The third: the pauses stay inside the deadline.
  - `RenderTest` asserts `(attached, failed) == (1, 0)` and prints the renderer's own log, before reading `image`. The old test raised `KeyError: 'image'` instead.

- Second commit (the coordinator widened the scope to `covers/lib/cdp.mjs`):
  - `covers/lib/cdp.mjs` `launch()`:
    - Captures Chrome's stderr through a pipe that is drained for Chrome's whole life, keeping its last 16 384 characters.
    - Stops waiting as soon as Chrome exits (`exit` or `error` event). The error then carries the exit code or signal and the last 20 stderr lines.
    - Waits up to 30 s for DevToolsActivePort instead of 10 s.
    - Adds `--disable-dev-shm-usage` on Linux.
    - Removes the profile of a Chrome that exited.
    - Every message still starts with `Chrome did not start`, so the retry in `covers.py` still recognises it.
  - `radar/covers.py`: a per-story reason is logged up to 2 000 characters instead of 400, so the stderr tail reaches the CI log.
  - `tests/test_covers.py`: new `BrowserStartTest`. It runs `launch()` with `CHROME` set to Node itself. Node rejects Chrome's flags on stderr and exits with code 9. The test asserts the message has `exited with code 9` and `bad option: --headless=new`, and that it arrived in under 5 s. On the old `cdp.mjs` it failed after 10.7 s with `'exited with code 9' not found in 'Chrome did not start: no DevToolsActivePort'`.

## Decisions Made

- **Root cause, as far as the scope can see it.** The launch is not in `radar/covers.py`; it is in `covers/lib/cdp.mjs`, which is outside this brief's scope:
  - `cdp.mjs:21-27`: one Chrome per launch, `--remote-debugging-port=0`, a fresh `mkdtempSync` profile, and `--no-sandbox` when `CI` is set. There is no fixed port and no shared profile, and the test suite runs sequentially (`update.yml:108`, `ci.yml:29`: `python -m unittest discover -s tests`). The brief's port, profile and parallel-clash hypotheses are therefore ruled out.
  - `cdp.mjs:28-29`: `for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100); if (!existsSync(portFile)) { proc.kill(); throw new Error('Chrome did not start: no DevToolsActivePort'); }`. This is a fixed 10 s wait. It does not watch the process exit, and `stdio: 'ignore'` (line 27) throws away Chrome's stderr, so the CI log cannot say *why* Chrome did not start. Measured here: a real Chrome writes the file in 331 ms. A `CHROME` that exits at once (`whoami.exe`) still costs the full 10 749 ms and reports only `no DevToolsActivePort`.
  - `radar/covers.py:94` (old): `for attempt in range(2)` treats a browser start-up failure like a drawing failure. On run 42846743763 (2026-11-10 15:40Z) both attempts failed the same way. The render returned `covers: {}`, `apply_covers` correctly left the story without an image, and the test then read `payload["stories"][0]["image"]` at `tests/test_covers.py:233`, which raised `KeyError: 'image'`.
- **Why retry with pauses instead of skipping:** the brief forbids skipping or weakening the test. A start-up failure drew nothing, so running again cannot hide a drawing regression. A drawing failure still gets only one more run, and `RenderTest` still fails if no cover is drawn.
- **`cdp.mjs`:** the first commit stayed inside two files, as the coordinator first limited it. The coordinator then approved the `cdp.mjs` change, which is in the second commit.
- **Why Node stands in for a broken Chrome in the test:** it is on every machine that runs these tests, it writes to stderr and exits with a known code (9), and it never writes DevToolsActivePort. `whoami.exe` exists only on Windows.

## Current State

- `python -m unittest tests.test_covers -v`: 14 tests OK, exit 0, with real Chrome on this machine (RenderTest ran, did not skip).
- With `CHROME=C:/Windows/System32/whoami.exe` (a Chrome that never writes DevToolsActivePort), RenderTest fails in 93 s with `(0, 1) != (1, 0) : r1 was not drawn:` followed by the four attempts' reasons. There is no `KeyError`.
- Chrome processes whose command line holds `covers-chrome-`: 0 before and 0 after each run.
- Committed on `fix/covers-flake`, not pushed.
- After the `cdp.mjs` change:
  - Fail-fast time for a Chrome that exits: before, 10 240 ms (`CHROME`=node) and 10 376 ms (`whoami.exe`); after, 115 ms (`exited with code 9` plus stderr) and 124 ms (`exited with code 1` plus stderr). A missing executable fails in 116 ms with `exited with error ENOENT`.
  - A real Chrome still starts in 327–359 ms.
  - `python -m unittest tests.test_covers -v`: 15 tests OK, exit 0. No other test imports `covers/lib`.
  - Chrome and Node processes with `covers-chrome-` in their command line: 0 after the run.
- Not fixed, and older than this change: `close()` can leave the profile directory behind when Chrome still holds a file.

## Next Steps

- Watch the next runs of `Update AI Radar` for `Covers: Chrome did not start; trying again`. If it appears and attempt 3 or 4 succeeds, the retry is doing its job. If all four attempts fail, the logged exit code and stderr now name the cause.

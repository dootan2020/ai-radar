# Measurement baseline and workflow repair

## Session Intent
Keep sane measurement baselines across branches; failed/degraded builds must not replace a good baseline. Validate schema/age, preserve fresh error evidence and main-only deployment. Verify newest compatible action majors. Allow `python build.py` to write only beneath an overridden output directory.

## Files Modified
- `build.py`: dedicated validated baseline, quality-gated atomic promotion, `baseline_updated` Actions output, output path overrides.
- `radar/measurement_cache.py`: schema/time validation and cache retention policy.
- `.github/workflows/update.yml`: branch/main restore fallback, isolated baseline file, conditional save, unique rerun keys, per-ref concurrency, current action majors.
- `tests/test_measurement_cache.py`: 17 synthetic offline regressions for malformed/expired/empty/degraded baselines, per-source measurement retention and build file effects.
- `tests/test_workflow.py`: four workflow contract checks.
- This progress record.

## Decisions Made
- Root cause: `build.py` uses the displayed snapshot as its prior measurement file, then overwrites it unconditionally; the workflow caches it unconditionally. Branch restore prefixes omit main. Introduced with `3b7457e`.
- Separate baseline from current displayed data. Baseline promotion requires schema/age validity, actual ranking measurements, at least 80% active remote source success and no fall below half the prior measured observations **for each previously measured source**. Previously measured sources must remain successful. These thresholds are conservative cache-retention policy, not measurements or ranking claims: the quorum rejects broad outages, while per-source retention catches parser/response truncation that an overall healthy source majority can hide. Zero is a valid measurement; missing, boolean, negative and nonfinite values are not.
- Thresholds are inclusive. They can withhold a legitimate smaller feed; the trade-off favors preserving the last usable measurement over losing continuity. After 48 hours the baseline is ignored, never retimestamped. A subsequent valid run can seed a new baseline. Identical observations are counted once; IDs may rotate naturally between collections without making fresh observations fake.
- Explicitly disabled sources and the local curated calendar do not count as active remote requests. Actual failed sources remain in the denominator.
- The default baseline is `data/measurement-baseline.json`, outside published `site/`. Current UI output remains `site/data/radar.json`. `RADAR_OUTPUT` overrides only current evidence and `RADAR_BASELINE` optionally overrides the independent baseline. Equal resolved paths are rejected before collection. A displayed snapshot is never silently adopted as a baseline.
- Cache keys use a new `radar-measurements-v2-` namespace, current branch then main prefixes, and both run ID and run attempt. Old unsafe UI-snapshot caches cannot seed the new policy; the first qualified main run seeds cross-branch restoration. Per-ref concurrency serializes main deployments while independent feature branches cannot replace queued main work. No fallback to arbitrary other feature branches.
- Do not modify ranking, source collection, or UI behavior; other workers own those files.

## Current State
Implementation complete; no commit, push or deployment. No real network build was run by this worker; coordinator owns final live collection/evidence. Static workflow tests establish configuration contracts, not hosted runner execution.

Verification:
- Before implementation: `python -m unittest tests.test_measurement_cache tests.test_workflow` returned four workflow assertion failures and missing baseline module. The failures exposed missing main fallback, unconditional UI-file caching, old majors and rerun/concurrency issues.
- Added source-specific regression while total-count policy still existed: `test_successful_but_empty_measured_source_cannot_hide_behind_another` failed with `AssertionError: unexpectedly None`; per-source retention made it pass.
- After implementation: focused suite **21 passed**; `python -m unittest discover -s tests` **181 passed**, including all prior tests and concurrently added regressions (Python 3.13).
- Build integration checks read back exact unchanged baseline bytes after failure, newly written failed-source evidence, and false/true `baseline_updated` outputs across recovery. First bad run leaves no baseline file. Good zero-valued measurement can seed one. Old/schema-invalid/future cache is ignored.
- Read back modified implementation/workflow. `git diff --check` reports no whitespace errors; Git emits existing Windows LF/CRLF warnings and inaccessible global ignore warnings.

Official sources opened 2026-10-02:
- [Cache latest release v6.1.0](https://github.com/actions/cache/releases/tag/v6.1.0): select `actions/cache/restore@v6` and `actions/cache/save@v6`.
- [Cache restore manifest](https://raw.githubusercontent.com/actions/cache/v6/restore/action.yml): same path/key/prefix inputs, Node 24 runtime.
- [Cache scope documentation](https://github.com/actions/cache/blob/main/README.md#cache-scopes): default-branch caches are available to other branches; matching prefix is still necessary.
- [Upload-artifact latest release v7.0.1](https://github.com/actions/upload-artifact/releases/tag/v7.0.1): select `actions/upload-artifact@v7`.
- [Upload-artifact manifest](https://raw.githubusercontent.com/actions/upload-artifact/v7/action.yml): existing name/path inputs and zipped default preserved, Node 24 runtime.
- Existing GitHub-hosted `ubuntu-26.04` is unchanged. Main-only Pages artifact/deploy guards are unchanged. Actual hosted-runner service compatibility must still be observed on a branch run.

Local build with writes confined to data (PowerShell):
```powershell
$env:RADAR_OUTPUT = 'data/p1-r2-build.json'
python build.py
Remove-Item Env:RADAR_OUTPUT
```
This writes current evidence there, and writes `data/measurement-baseline.json` only after qualification. For isolated concurrent local runs, also set `RADAR_BASELINE` to a distinct file under `data/`.

## Next Steps
Coordinator reviews artifact, runs the real build with the output override, and integrates smallest owning README/data-pipeline documentation update. Runner cache hit/promotion behavior awaits an authorized branch workflow run; no hosted success is claimed from offline tests.

## Câu hỏi
None.

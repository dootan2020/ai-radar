# Core fixes progress

## Session Intent
Fix review findings 1, 4, 5, 6, 7: Vietnamese cross-URL clustering, readable hot reasons, arXiv HTML identity, loop imports, individual v2 test invocation. Preserve numeric/version/time guards and ranking metrics; no network build, commits, pushes, or dependencies.

## Files Modified
- `radar/clustering.py`: Unicode NFC word tokens; arXiv HTML canonical identity.
- `radar/ranking.py`: decimal measurement display with thousands separators, preserving fractional values.
- `radar/assembly.py`, `radar/discovery.py`: move the review-named imports out of item loops.
- `tests/test_v2_clustering.py`, `tests/test_v2_collectors.py`, `tests/test_v2_events.py`, `tests/test_v2_hf_dates.py`, `tests/test_v2_pipeline.py`, `tests/test_v2_ranking.py`, `tests/test_v2_transport.py`: package-aware support imports; pipeline event helper follows the same pattern.
- `tests/test_v2_core_regressions.py`: nine regression methods covering Unicode, identity/version guards and measurement display.
- `docs/p1-r2-core-progress.md`: intent, decisions and verification evidence.

## Decisions Made
- Root causes verified in the initial v2 commit: ASCII token regex; general numeric formatting; incomplete arXiv format alternatives; imports inside loops; test helpers imported as top-level modules only.
- Use NFC Unicode alphanumeric tokens, preserving the existing minimum length, overlap, Jaccard, numeric and time checks. Do not strip accents or transliterate.
- Use package-aware sibling imports for unittest module invocation and retain top-level imports for discovery mode.
- Keep changes to the delegated core modules and v2 tests. Other workers own source and cache/workflow changes.
- Finding 1: the review's empty-set example was inaccurate; actual pre-fix token set was `{'nghi'}`. The underlying ASCII fragmentation defect was real. NFC preserves accents; Unicode alphanumeric matching excludes underscores and preserves compound numeric versions.
- Finding 4: hoisted `web_url` and `CHANNELS` to module imports. Existing collector/pipeline tests prove behavior retained.
- Finding 5: conditional relative imports avoid changing `sys.path` and support both module and discovery execution. The pipeline also needed its sibling event helper import updated.
- Finding 6: HTML now shares abs/pdf identity for the same explicit paper version. Tests also proved that HTML previously bypassed the existing distinct-version veto; normalization fixes that without changing the veto.
- Finding 7: integers use grouping; fractional values use fixed-point formatting of `Decimal(str(value))`, avoiding the six-significant-digit rounding and exponent behavior of `:g`. Actual measurement values and ranking metric selection stay unchanged.

## Current State
Implemented and inspected scoped diff. No network build, commit, push, dependency, production data, or other worker files changed.

Red evidence:
- `python -m unittest discover -s tests -p test_v2_core_regressions.py`: nine methods, 14 failures/subtest failures before implementation (Unicode fragmentation/cross-URL mismatch, HTML identity/version mismatches, exponent/rounded reasons).
- `python -m unittest tests/test_v2_clustering.py`: failed with `ModuleNotFoundError: No module named 'test_v2_support'` before import repair.

Green evidence, Python 3.13:
- Same new regression command: nine tests pass.
- `python -m unittest discover -s tests -p test_v2_*.py`: 80 tests pass.
- Each individual module through `python -m unittest tests/test_v2_<name>.py`, separate subprocesses with 45-second deadlines: clustering 15, collectors 16, events 10, hf_dates 1, pipeline 12, ranking 16, transport 1, core_regressions 9; all pass.
- `git diff --check`: clean; only repository autocrlf notices.

## Next Steps
Coordinator independently reviews scoped diff and integrates with other workers. Full-build and live-source acceptance remain outside this slice.

## Câu hỏi
None.

# Daily editions

A daily edition is a finite morning reading list, separate from the continuously
updated source snapshot. It selects from the first eligible collection after the
06:00 Vietnam cutoff, using the preceding 24 hours. Once saved in durable history,
a later run cannot rewrite that day's choices or translations. An empty edition
is meaningful: collection passed publication checks but no story met the
editorial selection policy.
Missing days stay missing; old observations are not backfilled as a new issue.

The [edition selector](../radar/editions.py) owns the window, finite limit,
evidence selection, ordering and explanatory policy. The
[archive](../radar/edition_archive.py) owns validation, immutable daily files,
and `index.json` metadata, including the latest available date and relative
JSON path. These files are data contracts for a later reader UI; this pipeline
change does not add a rendered archive page.

## Editorial evidence and morning calibration

Fewer than three stories, including zero, is an honest result; there is no
filler tier. A discussion link is attention evidence, not another reporting
publisher. Ordinary measured attention needs eligible non-forum coverage. The
exception for forum-only stories is deliberately narrow: percentile at least
0.97 and at least 100 comments on the measured forum observation, at most one
story per issue. Attention-only picks follow primary-release or publisher-coverage
evidence. These heuristics do not prove importance or independent reporting.
The selector owns the exact thresholds and exported policy metadata.

New editions identify their policy as `daily-evidence-v2`. Existing
`daily-evidence-v1` editions remain readable under their original evidence rules;
changing selection policy must not invalidate or rewrite frozen history. Consumers
must read the stored policy when interpreting publisher counts: v2 excludes
forum identities, so a forum-only exception has a publisher count of zero.

Threshold calibration needs a week of real morning observations before making
claims about morning quality. Retain each original first-after-cutoff snapshot
(normally from the 06:07 ICT scheduled run), matching publication diagnostics,
actual workflow and snapshot times, source health, candidate/rejection reasons
and final selections. Existing collected-source and publish-diagnostics Actions
artifacts provide the inputs; retain them before expiry and replay at the actual
snapshot time, recording the policy version. Report zero-, one- and two-pick days,
outages and delayed or missed runs separately. Afternoon engagement cannot stand in for morning
engagement. Any agreed policy/cutoff adjustment applies to future editions only;
never fabricate a missing morning or rewrite archived editions.

## Durable history

The dedicated `radar-editions` Git branch is the durable source of truth, with
only an `editions/` data tree. The public copy lives under `site/data/editions/`.
Actions caches and expiring workflow artifacts are transport or acceleration,
not the archive. No account, paid API, model inference, or new secret is needed.

[The publication CLI](../radar/edition_publish.py) runs after optional headline
translation and requires matching successful `publish-status.json` evidence.
[Git persistence](../radar/edition_history.py) owns strict restore, base-commit
comparison, immutable-byte checks and normal fast-forward pushes. Authentication
uses the existing `GITHUB_TOKEN` in the process environment; credentials are
not written into remote URLs or diagnostics.

[The workflow](../.github/workflows/update.yml) owns the exact commands, pinned
actions, permissions and dependencies. Only its main-branch persistence job has
contents-write permission. The existing branch concurrency group covers the
whole update, persistence and deployment sequence. GitHub documents the
[scope and queue behavior of concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
and [job token permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idpermissions).
Repository rules may prohibit the data-branch push even with this permission;
that failure must be investigated rather than bypassed with another token.

Pages deployment and history persistence are independent consumers of a successful
update. Keeping healthy snapshot publication available takes precedence over
waiting for the archive write. An archived edition means **accepted for
publication**, not proof that readers received it. A failed deploy leaves an
already-persisted issue available for the next successful deployment.
The independent last-published snapshot cache still advances only after Pages
succeeds; see [operations](operations.md) for deployment verification and rollback.

The Pages artifact can contain a prepared issue that is not yet durable. If its
history write fails, a later runner can prepare that date from a later snapshot
and change that provisional public issue. Cross-run immutability is guaranteed
by `radar-editions`, not merely by a prepared or deployed copy.

## Failure and recovery decisions

- A rejected or mismatched publication attempt leaves edition files and remote
  history untouched. Fix the source/publication failure before retrying.
- Only an absent exact `radar-editions` ref permits bootstrap. An authentication
  error, network failure, corrupt archive or unexpected branch tree fails archive
  preparation closed. Preparation and candidate upload are optional to snapshot
  deployment; persistence skips without a successfully uploaded candidate.
  Do not delete the branch to silence the error: restore the verified history
  through an owner-approved recovery.
- If another writer advances history after preparation, collect and prepare
  again against the new head. Do not force-push a stale candidate. An identical
  already-persisted candidate is safe to retry.
- Persistence failure or timeout does not gate Pages. It still fails its own job
  and can produce a failed overall workflow even if Pages succeeds. Optional
  preparation/upload failure can leave the workflow green, so inspect those step
  outcomes and diagnostics when investigating missing history; an overall-failure
  alert alone does not cover them.
- When only deployment fails, rerun that deployment using its retained artifact
  as described in the operations guide; do not regenerate a frozen issue.

Use `python -m radar.edition_publish --help` and each subcommand's `--help` for
local paths and options. `prepare` reads the remote but does not push; `persist`
writes only the dedicated data branch. For offline verification, use a disposable
bare Git repository as `--remote`, plus an eligible snapshot and its matching
diagnostic file. Never use a live remote merely to test persistence.

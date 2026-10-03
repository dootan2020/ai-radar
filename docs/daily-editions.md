# Daily editions

A daily edition is a finite morning reading list, separate from the continuously
updated source snapshot. It freezes the first eligible collection after the
06:00 Vietnam cutoff, using the preceding 24 hours. A later run cannot rewrite
that day's choices or translations. An empty edition is meaningful: collection
passed publication checks but no story met the editorial selection policy.
Missing days stay missing; old observations are not backfilled as a new issue.

The [edition selector](../radar/editions.py) owns the window, finite limit,
evidence selection, ordering and explanatory policy. The
[archive](../radar/edition_archive.py) owns validation, immutable daily files,
and `index.json` metadata, including the latest available date and relative
JSON path. These files are data contracts for a later reader UI; this pipeline
change does not add a rendered archive page.

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

History is persisted before Pages deployment. An archived edition therefore
means **accepted for publication**, not proof that readers received it. A failed
deploy leaves that accepted issue available for the next successful deployment.
The independent last-published snapshot cache still advances only after Pages
succeeds; see [operations](operations.md) for deployment verification and rollback.

## Failure and recovery decisions

- A rejected or mismatched publication attempt leaves edition files and remote
  history untouched. Fix the source/publication failure before retrying.
- Only an absent exact `radar-editions` ref permits bootstrap. An authentication
  error, network failure, corrupt archive or unexpected branch tree stops the
  run before replacing the public archive. Do not delete the branch to silence
  the error: restore the verified history through an owner-approved recovery.
- If another writer advances history after preparation, collect and prepare
  again against the new head. Do not force-push a stale candidate. An identical
  already-persisted candidate is safe to retry.
- When persistence fails, Pages waits and the previous deployment remains live.
  When only deployment fails, rerun that deployment using its retained artifact
  as described in the operations guide; do not regenerate a frozen issue.

Use `python -m radar.edition_publish --help` and each subcommand's `--help` for
local paths and options. `prepare` reads the remote but does not push; `persist`
writes only the dedicated data branch. For offline verification, use a disposable
bare Git repository as `--remote`, plus an eligible snapshot and its matching
diagnostic file. Never use a live remote merely to test persistence.

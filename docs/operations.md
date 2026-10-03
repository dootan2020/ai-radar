# Operations and rollback

Use this runbook to distinguish collection failures, rejected publication,
deployment failures, and an absent scheduled run. The source of commands and
permissions is [the update workflow](../.github/workflows/update.yml);
[Offline CI](../.github/workflows/ci.yml) checks pushes to `main` and pull requests;
feature-branch pushes with an open PR therefore run the suite once. Production
changes and pushes to `main` require owner approval.

## When the page looks old

1. Compare the served `data/radar.json` timestamp with the latest successful
   **deployment**, then inspect the update workflow's run history and logs.
   A green test run or a collected artifact is not a deployed page.
2. Open the run's publication diagnostic artifact and the collected source
   evidence when present. Follow `reason`, failed source IDs, and actual HTTP
   evidence back to [publication policy](../radar/publication.py) and
   [source inventory](../radar/catalog.py). Inspect the first failed step if
   no diagnostic was created; failure can precede collection.
3. If publication was rejected, retain the last good site and diagnose the
   source or contract failure. Do not copy an old snapshot under a new timestamp
   to make the freshness indicator green.
4. If collection succeeded but deployment failed, inspect the `deploy` job and
   Pages environment. Diagnose that failure before collecting again. A manual
   update on `main` can publish and therefore needs owner approval.

GitHub documents that scheduled runs may be delayed or dropped under load, and
public-repository schedules can be disabled after 60 days without activity.
These are possible explanations to investigate, not proof of a particular
incident. The cron is an intended cadence, not an exact-time SLA.
[GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
is the provider authority. Snapshot age and `scheduler_gap` reveal missing
freshness, not the cause of the gap.

Failed workflow runs become visible in Actions. Delivery of email/web
notifications also depends on each maintainer's GitHub notification settings;
workflow code alone does not establish that anyone received an alert. The owner
should enable the relevant Actions notifications and verify them on an actual
failed run. Offline CI should be made a required branch check in repository
rules. These settings have not been changed or verified by this code update.

The [failure-alert workflow](../.github/workflows/failure-alert.yml) and
[issue reporter](../radar/failure_alert.py) provide a separate investigation
entry point for failed update runs. The first issue mentions the repository
owner. Repeat failures update the same open issue with `PATCH`, without new
comments; editing an issue may not notify subscribers again. Repository Issues
must be enabled, and the built-in `GITHUB_TOKEN` needs the workflow's declared
Actions-read and Issues-write permissions. No extra personal token is required.
Check the alert workflow itself if an expected issue is missing; an issue alone
does not prove notification delivery. Closing an investigated issue allows a
later failure to create a new one.

Only `failure`, `timed_out`, `action_required`, and `startup_failure` open or
update incidents. `cancelled` (including superseded queued runs), `stale`,
`neutral`, and `skipped` are ignored. A later successful Update AI Radar run
closes bot-owned open incidents for that same branch, with a recovery run link
and no extra comment. A successful feature-branch update means that branch's
workflow recovered; it does not imply a Pages deployment.

Ordering uses the workflow's `run_number`, then `run_attempt`, rather than
webhook arrival or finish time. Before writing, the observer checks completed
runs of `update.yml` on the same branch created at or after the event's run;
newer actionable failures or successes supersede delayed events. It also keeps
the latest handled run in incident bodies, including closed incidents, so an
older event cannot reopen or overwrite a recovered incident. Cancelled runs
do not resolve an outstanding failure. The first encounter with an older issue
resolves its existing run link through Actions to obtain ordering metadata.
Missing metadata, unreadable history, or a 1,000-item pagination bound fails
the observer visibly without guessing or creating a duplicate. Retry the
observer after resolving that error. Issue ownership and branch markers keep
human issues, pull requests, and other branches outside this lifecycle.

## Live website health

The independent [health monitor workflow](../.github/workflows/health-monitor.yml)
checks the deployed site on a GitHub-hosted runner at minutes 13 and 43 of every
hour (UTC). Use its **Run workflow** action for a manual observation. It does
not collect data or deploy the site. The [monitor CLI](../radar/health_monitor.py)
and [probe](../radar/health_probe.py) own the checks: homepage HTTP 200 and app
markers, `data/radar.json` HTTP 200 with parseable JSON and the minimum UI shape,
and availability of the main CSS/JavaScript files and local module dependencies.
The snapshot's timezone-aware `generated_at` must not be in the future or more
than three hours old; exactly three hours remains valid. The threshold comes
from [publication policy](../radar/publication.py), not the remote snapshot.
These are availability and snapshot checks; they do not execute JavaScript or
guarantee that the page renders correctly in a browser.

The asset inventory comes from the homepage's script, stylesheet and modulepreload
references, then recursively follows quoted static imports, re-exports and literal
`import()` calls in fetched JavaScript. Cycles and shared dependencies are checked
once; the probe fails visibly if discovery exceeds 30 assets. It retains the
60-second probe deadline and 8 MiB per-response limit. Discovery is a small lexical
scan for the site's module syntax, not a full JavaScript parser: computed imports,
template expressions, import maps and CSS/font/image dependencies are outside its
scope. External references are ignored. Local references must stay within the
HTTPS Pages project and use plain paths without credentials, percent escapes,
query strings (including cache-busting parameters) or fragments; invalid references
fail their referring page/module check without exposing the reference in reports.

For a read-only check from the repository root, run:

```sh
python -m radar.health_monitor
```

It prints the measured checks and timestamps without requiring a token or
changing issues. Exit `0` means healthy; exit `1` means confirmed failure,
inconclusive probes, or a monitor/reporting error. The workflow adds `--report`
to reconcile issues; an API failure in that mode also exits `1`. Keep that flag
in the authorized workflow rather than adding it to a local diagnostic command.

A failed probe is repeated after 30 seconds. Only check IDs that fail in both
observations confirm an incident. An isolated transient does not open an issue;
different failures with no shared failing ID are inconclusive and cannot close
an existing incident. A wholly healthy observation establishes recovery.

The [health reporter](../radar/health_alert.py) maintains a separate bot-owned
live-health issue, independent of update-workflow failure issues. Confirmed
failures create or update that issue without repeated comments; the issue body
mentions the repository owner with `@`. Recovery closes matching bot-owned open
health issues. Human issues and pull requests are outside
this lifecycle. The workflow uses only the built-in `GITHUB_TOKEN`, with
`contents: read` and `issues: write`; no personal token or additional secret is
needed. Repository Issues must be enabled. Read the health workflow's own logs
if issue reporting fails, and inspect the recorded failing checks and observation
time before investigating collection or deployment.

The operating target is an alert within about an hour of an outage, or within
about an hour after snapshot age exceeds three hours. This is not an SLA:
GitHub schedules can be delayed, dropped, or disabled, as described above. A
monitor on the same provider cannot reliably detect its own absent scheduled
runs or provider-wide unavailability. Issue creation does not prove notification
delivery; maintainers' GitHub notification settings still apply, and issue edits
may not generate another notification. Verify both a hosted observation and
notification delivery before relying on the monitor operationally.

## Restore a previously deployed artifact

This is a production action: obtain owner approval for the target run and the
temporary interruption of automatic updates before executing it.

1. Disable the update workflow's schedule and settle or cancel in-progress and
   queued deployments. Confirm no newer run can overwrite the restored site.
   Disabling future scheduling alone does not stop a run already in progress.
2. Select a previously successful **main-branch** update run and record its
   commit, run ID, deployment URL, and snapshot timestamp. Confirm that run's
   `github-pages` artifact still exists and is downloadable. The upload action's
   default retention is one day; use the actual `retention-days` setting in that
   run's workflow and its artifact expiry, not the age of the Git commit.
3. Re-run only that run's `deploy` job, so it consumes the retained artifact.
   Do not re-run `update` or the whole workflow: collection would fetch today's
   data and replace the artifact rather than restore the historical snapshot.
   A rerun uses the original run's SHA/ref, so the selected run must satisfy the
   main-branch deployment guard. If GitHub requires the workflow to be enabled
   to rerun the job, keep scheduling suspended and settle other runs first.

   For an authorized operator using GitHub CLI, replace `RUN_ID` with that
   successful run's ID and `JOB_ID` with its `deploy` job's database ID from
   the first command. These are examples; they were not executed here:

   ```sh
   gh run view RUN_ID --json jobs
   gh run rerun RUN_ID --job JOB_ID
   gh run watch RUN_ID
   ```

4. Wait for the deployment to finish, open the served page and JSON, and compare
   the visible content and snapshot timestamp against the selected artifact.
   A rollback intentionally restores older data; do not change its timestamp.
5. Correct or revert the offending `main` change with owner approval before
   resuming automatic updates. Re-enabling the workflow while bad code remains
   on `main` can immediately replace the rollback at its next run. Verify the
   first successful deployment after normal scheduling resumes.

GitHub's [rerun documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
describes job reruns and original SHA/ref behavior; the
[Pages artifact action](https://github.com/actions/upload-pages-artifact/blob/main/action.yml)
owns retention defaults. Artifact availability is a prerequisite, not a promise.
This procedure has been checked against workflow structure and provider docs;
no production rollback or deployment was executed during this change.

## When the historical artifact has expired

Create a branch that reverts the offending change, run the normal offline CI,
review the diff, and obtain owner approval before pushing the correction to
`main`. With the corrected code present, enable/manual-run the update workflow
on `main` and inspect its deployment to completion. This rebuilds fresh source
data using the corrected code; it does not recover the exact historical snapshot.
Keep the schedule suspended while resolving a reproducible publication failure.

## Verification limits for the reported long gap

During the 2026-10-03 investigation, the coordinator's `gh run list` could not
read the local GitHub CLI configuration (`Access denied`), so it could not
establish the historical cause of the reported six-hour gap. No delayed-run,
disabled-workflow, or failed-deploy explanation is confirmed. Inspect authorized
Actions run history to close that question; do not infer a cause from cron or
from offline tests. The [dated source check](source-feed-check-2026-10-03.md)
records the separate network-verification limits.

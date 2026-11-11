# Operations and rollback

Use this runbook to distinguish collection failures, rejected publication,
deployment failures, and an absent scheduled run. The source of commands and
permissions is [the update workflow](../.github/workflows/update.yml);
[Offline CI](../.github/workflows/ci.yml) checks pushes to `main` and pull requests;
feature-branch pushes with an open PR therefore run the suite once. Production
changes and pushes to `main` require owner approval.

Arena model rankings have an independent daily refresh and last-good cache; see
[the Arena rankings runbook](arena-rankings.md) for source licensing, weekly
comparison, failures and first-run verification.

Newsroom story reviews score each Vietnamese summary against the ten-item
[story scorecard](bang-cham-ban-tin.md) (pass at 9/10) instead of a feel score. Every newsroom desk (reporter, editor, checker, writer) tries Antigravity (`agy`) first and falls back to Codex only when `agy` is unavailable; the lane order lives in `[desk_priority]` of `phong-bao/cong-cu/agy.toml`.

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
   Cloudflare Pages project. Diagnose that failure before collecting again. A manual
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
checks the deployed site on a GitHub-hosted runner every 15 minutes, at minutes
13, 28, 43 and 58 of every hour (UTC). Use its **Run workflow** action for a
manual observation. It does not collect data or deploy the site.
The [monitor CLI](../radar/health_monitor.py)
and [probe](../radar/health_probe.py) own the checks: homepage HTTP 200 and app
markers, both `data/radar.json` and `data/radar-ui.json` HTTP 200 with parseable
JSON and the minimum UI shape, and availability of the main CSS/JavaScript files
and local module dependencies.
Each snapshot's timezone-aware `generated_at` must not be in the future or more
than three hours old; exactly three hours remains valid. The threshold comes
from [publication policy](../radar/publication.py), not the remote snapshot.
The reader projection has its own `snapshot-ui` check and must have the same
`generated_at` string as the full snapshot. A missing, invalid, stale or mismatched
projection fails the probe even when the full snapshot is healthy. Reports retain
only the normalized full-snapshot timestamp and fixed diagnostic text, never raw
remote timestamp values.
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
HTTPS Pages hostname and use plain paths without credentials, percent escapes,
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

A failed probe is repeated after 30 seconds within the same workflow run. Only
check IDs that fail in both observations confirm an incident. An isolated
transient does not open an issue;
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

With an on-time schedule, detection waits up to about 15 minutes for the next
run, plus a 30-second confirmation delay and request/runner queue time. Allow
roughly 30 minutes as a conservative nominal operating target after an outage
or after snapshot age exceeds three hours; confirmation does not wait for a
second scheduled run. This is not an SLA or a guaranteed 60-minute bound:
GitHub schedules can be delayed, dropped, or disabled, as described above. A
monitor on the same provider cannot reliably detect its own absent scheduled
runs or provider-wide unavailability. Issue creation does not prove notification
delivery; maintainers' GitHub notification settings still apply, and issue edits
may not generate another notification. Verify both a hosted observation and
notification delivery before relying on the monitor operationally.

## Reader loading and recovery

The [page HTML](../site/index.html) includes a visible initial loading status and
a native reload link, so a missing app or imported module does not leave an empty
screen. With JavaScript disabled, a separate instruction explains how to enable
it and reload. Successful rendering replaces this fallback without changing the
normal reader layout.

The [snapshot loader](../site/snapshot.js) allows 10 seconds per attempt, including
both receiving headers and consuming the JSON body. If the compact
`data/radar-ui.json` request fails or times out, it tries `data/radar.json` with
its own 10-second deadline. If both fail, the existing error state offers retry;
browser timer suspension can delay when that state appears. A maintainer's explicit
`?data=data/<file>.json` has the same deadline but no implicit fallback. Failed
background polls keep the last displayed snapshot and retry on the next poll.

## Reader traffic and performance

Cloudflare Web Analytics runs on `hco.news` through Cloudflare's automatic setup:
Cloudflare injects the beacon into the served pages, and no page carries a snippet
of its own (two beacons once counted every view twice). The reader pages' CSP
admits only the injected beacon path under `https://static.cloudflareinsights.com/beacon.min.js/`
and the `https://cloudflareinsights.com` reporting origin; the page-head tests
([test_page_head.py](../tests/test_page_head.py), [test_hieu_nang.py](../tests/test_hieu_nang.py))
hold both rules. The extension's new tab never loads the beacon: its pages are
packaged files served from the extension origin, and
[sync-site.py](../extension/sync-site.py) refuses any remote script. Cloudflare
documents that usage metrics do not use cookies or localStorage and do not collect
personal data: [privacy](https://developers.cloudflare.com/web-analytics/about/) and
[Core Web Vitals](https://developers.cloudflare.com/web-analytics/data-metrics/core-web-vitals/).
The [privacy page](../site/chinh-sach-rieng-tu.html) discloses it; change both together.

In Cloudflare, open **Web Analytics** for `hco.news` and inspect traffic,
**Page load time**, and **Core Web Vitals**. Traffic measures visits/page views;
performance metrics describe observed browser loads, not the collection schedule.
See [dashboard setup](https://developers.cloudflare.com/web-analytics/get-started/).

## Cloudflare Pages migration

The update workflow deploys the complete `site/` snapshot to the Cloudflare Pages
project `radar-ai-vn`, then deploys a small compatibility artifact to GitHub Pages.
That artifact redirects `/` and every generated `/tin/<slug>/` route to the
matching canonical URL on Cloudflare. A failed Cloudflare deployment prevents
the GitHub Pages redirect deployment, so the existing GitHub Pages site remains
available while the new host is repaired.

Create a GitHub Actions secret named `CLOUDFLARE_PAGES_API_TOKEN` for the first
Cloudflare deployment. Scope the Cloudflare token to **Account > Cloudflare
Pages Edit permission at account scope for this account only; the workflow also uses the existing
`CLOUDFLARE_ACCOUNT_ID` secret. The Pages project `radar-ai-vn` must exist before
the first deployment. The workflow fails at the Cloudflare deploy step when the
API token is missing.

For the first release, create the Pages project, save the API token as the
repository secret, merge the migration, and run **Update AI Radar** on `main`.
Watch the Cloudflare deploy job and then the GitHub Pages redirect deploy job.
Open `https://hco.news/` and an existing `/tin/<slug>/` page at mobile
and desktop widths; open the corresponding legacy URLs and verify they redirect.
Confirm the health monitor stays green for 24 hours. Configure Cloudflare Web
Analytics for `hco.news` and verify visits appear there.

After an approved deployment, open the reader with browser Network and Console
panels. Confirm the beacon script loads without a CSP error and a report reaches
`https://cloudflareinsights.com/cdn-cgi/rum`; switch tabs after loading to trigger
the first hidden-state Core Web Vitals report. Then check the dashboard with the
matching time/path filter. Ad blockers or network failures can prevent reports;
a successful script request alone does not prove dashboard ingestion. The health
monitor ignores external assets and cannot verify analytics. Provider details:
[CSP](https://developers.cloudflare.com/web-analytics/faq/#what-do-i-need-to-add-to-my-content-security-policy-csp)
and [collection timing](https://developers.cloudflare.com/web-analytics/data-metrics/data-origin-and-collection/).

To remove analytics, turn off the automatic setup for `hco.news` in Cloudflare,
then remove the two CSP allowances, update the head tests and the privacy page,
run offline CI, and obtain approval before publishing.

## Roll back a bad deployment

Production is the Cloudflare Pages project `radar-ai-vn` (public address
`https://hco.news/`), deployed by the `deploy` job of
[update.yml](../.github/workflows/update.yml) with
`wrangler pages deploy ... --project-name radar-ai-vn --branch main`. Cloudflare
keeps earlier deployments, so a rollback re-points production at one of them
without rebuilding. This is a production action: obtain owner approval for the
target deployment first.

1. Stop the next update from overwriting the rollback. Disable the **Update AI
   Radar** schedule (it runs at minutes 7 and 37) and cancel or settle any
   in-progress run; disabling the schedule alone does not stop a run already
   in progress.
2. List deployments and pick the last good production one. Record its ID, commit
   and age:

   ```sh
   npx wrangler pages deployment list --project-name radar-ai-vn
   ```

3. Roll back, by either route:
   - Dashboard: **Workers & Pages → radar-ai-vn → Deployments → ⋯ → Rollback**
     on the chosen production deployment.
   - API, with a token that has Pages edit permission (`ACCOUNT_ID` and
     `DEPLOYMENT_ID` are placeholders):

     ```sh
     curl -X POST -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
       "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/pages/projects/radar-ai-vn/deployments/$DEPLOYMENT_ID/rollback"
     ```

4. Verify with the health probe, then by eye:

   ```sh
   python -m radar.health_monitor
   ```

   A rollback restores an older snapshot on purpose, so its `generated_at` ages.
   If it passes the three-hour freshness limit, the probe fails stale although
   the rollback worked; judge that result against the age of the target.
   Then open `https://hco.news/` and one `/tin/<slug>/` page.
5. Roll forward. Revert or fix the offending change on a branch, run the offline
   CI, merge it with owner approval, then re-enable the schedule and run **Update
   AI Radar** on `main`. Its `deploy` job publishes a new deployment that
   supersedes the rollback. Do not re-enable the schedule while the bad code
   remains on `main`, because the next run would replace the rollback with it.
   Confirm the first successful run's deployment is the one now live.

The deployment commands are checked against the workflow and the Cloudflare Pages
documentation; no production rollback was executed while writing this section.
The legacy GitHub Pages redirect site is a separate deployment
(`deploy-legacy-redirects`) and needs no rollback: it only redirects to Cloudflare.

## Verification limits for the reported long gap

During the 2026-10-03 investigation, the coordinator's `gh run list` could not
read the local GitHub CLI configuration (`Access denied`), so it could not
establish the historical cause of the reported six-hour gap. No delayed-run,
disabled-workflow, or failed-deploy explanation is confirmed. Inspect authorized
Actions run history to close that question; do not infer a cause from cron or
from offline tests. The [dated source check](source-feed-check-2026-10-03.md)
records the separate network-verification limits.

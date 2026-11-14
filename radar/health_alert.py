"""Keep live-site incidents independent from update workflow incidents."""

from datetime import timedelta, timezone
import json
import re

from radar.failure_alert import AlertError, plain
from radar.health_probe import SITE_URL
from radar.items import instant

HEALTH_MARKER = "<!-- radar-live-health -->"
OBSERVATION_PATTERN = r"<!-- radar-health-observation:(\{[^\n]+\}) -->"


def issue_observation(issue, pattern=OBSERVATION_PATTERN):
    match = re.search(pattern, issue.get("body") or "")
    try:
        value = json.loads(match[1]) if match else {}
        stamp = instant(value.get("checked_at"))
    except (TypeError, ValueError):
        stamp = None
    if stamp is None:
        raise AlertError("Health issue has invalid observation metadata; inspect it before retrying.")
    return stamp


def valid_run(repository, run_id, run_attempt):
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                and re.fullmatch(r"[1-9][0-9]*", str(run_id)) and re.fullmatch(r"[1-9][0-9]*", str(run_attempt)))


def bot_issues(api, marker, pattern):
    """The workflow bot's issues carrying marker, each with the observation time recorded in its body."""
    issues = [issue for issue in api.pages("/issues?state=all&creator=github-actions%5Bbot%5D")
              if "pull_request" not in issue and marker in (issue.get("body") or "")
              and issue.get("user", {}).get("login") == "github-actions[bot]"]
    return [(issue_observation(issue, pattern), issue) for issue in issues]


def reconcile_report(report, api, repository, run_id, run_attempt, owner):
    if report.get("status") == "inconclusive":
        return "unchanged"
    stamp = instant(report.get("checked_at"))
    status = report.get("status")
    confirmed = report.get("confirmed_failures")
    if (stamp is None or status not in ("healthy", "failed") or not isinstance(confirmed, list)
            or (status == "failed" and not confirmed) or (status == "healthy" and confirmed)
            or not valid_run(repository, run_id, run_attempt)):
        raise AlertError("Invalid health report or workflow metadata; refusing to change an issue.")
    ordered = bot_issues(api, HEALTH_MARKER, OBSERVATION_PATTERN)
    if any(prior > stamp or (prior == stamp and status == "failed" and issue.get("state") == "closed")
           for prior, issue in ordered):
        return "superseded"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    observation = "<!-- radar-health-observation:" + json.dumps({"checked_at": report["checked_at"]}, sort_keys=True) + " -->"
    open_issues = [issue for _, issue in sorted(ordered, key=lambda pair: pair[0], reverse=True)
                   if issue.get("state") == "open"]
    if status == "healthy":
        for issue in open_issues:
            body = re.sub(OBSERVATION_PATTERN + r"\s*", "", issue["body"])
            body += (f"\n\nRecovered: all live checks passed at {plain(report['checked_at'])}. "
                     f"[Monitor run and logs]({run_url}).\n\n{observation}")
            api.request("PATCH", f"/issues/{int(issue['number'])}",
                        {"body": body, "state": "closed", "state_reason": "completed"})
        return "resolved" if open_issues else "unchanged"
    body = [HEALTH_MARKER, observation, f"Confirmed live health failure: [{SITE_URL}]({SITE_URL}).",
            f"Observed at: {plain(report['checked_at'])}.",
            f"Snapshot generated_at: {plain(report.get('generated_at') or 'unavailable')}.",
            f"[Monitor run and logs]({run_url}).", "These checks failed in both probes, 30 seconds apart:"]
    for row in confirmed:
        body.append(f"- {plain(row['id'])}: {plain(row['detail'])}")
    body.append("Repeated failures update this issue without comments. A healthy live probe closes it. "
                "This incident does not represent update workflow status or diagnose the cause of stale data.")
    if re.fullmatch(r"[A-Za-z0-9-]+", owner):
        body.append(f"Owner: @{owner}. Notification delivery depends on GitHub account/repository settings.")
    payload = {"title": "AI Radar live health check failed", "body": "\n\n".join(body)}
    if open_issues:
        issue = open_issues[0]
        if issue.get("body") == payload["body"] and issue.get("title") == payload["title"]:
            return "unchanged"
        api.request("PATCH", f"/issues/{int(issue['number'])}", payload)
        return "updated"
    api.request("POST", "/issues", payload)
    return "created"


QUIET_MARKER = "<!-- radar-quiet-feed -->"
QUIET_OBSERVATION_PATTERN = r"<!-- radar-quiet-observation:(\{[^\n]+\}) -->"
DIAGNOSIS_LABELS = {"quiet-news": "looks like quiet news", "pipeline": "looks like a pipeline problem",
                    "unknown": "diagnosis unknown"}
DISPLAY_TZ = timezone(timedelta(hours=7))


def duration(seconds):
    minutes = int(seconds) // 60
    return f"{minutes // 60}h {minutes % 60:02d}m"


def local_time(value):
    stamp = instant(value)
    return stamp.astimezone(DISPLAY_TZ).strftime("%d/%m %H:%M (+07:00)") if stamp else "unknown"


def age(seconds):
    return f"{duration(seconds)} ago" if isinstance(seconds, int) else "age unknown"


def quiet_body(report, run_url, owner):
    """The quiet-feed issue: how long, the last new story, and the measured signals behind the diagnosis."""
    signals = report["signals"]
    plus = "+" if report["quiet_at_least"] else ""
    lines = [QUIET_MARKER, "<!-- radar-quiet-observation:" + json.dumps({"checked_at": report["checked_at"]},
                                                                        sort_keys=True) + " -->",
             f"No new story on [{SITE_URL}]({SITE_URL}) for **{duration(report['quiet_seconds'])}{plus}** "
             f"(this alert opens after {duration(report['threshold_seconds'])}).",
             f"Checked at {local_time(report['checked_at'])}. [Monitor run and logs]({run_url})."]
    last = report.get("last_new_story")
    if last:
        lines.append(f"Last new story: {plain(last.get('title') or last['id'], 300)} (id {plain(last['id'], 40)}), "
                     f"first published by the build at {local_time(last['appeared_at'])}.")
    else:
        lines.append("No story in the fetched story history (about a week) is newer than its start, "
                     "so the quiet time is a lower bound.")
    label = DIAGNOSIS_LABELS[report["diagnosis"]]
    lines.append(f"Diagnosis: **{label}**.")
    for text in report["problems"]:
        lines.append(f"- Problem: {plain(text, 300)}")
    for text in report["unknowns"]:
        lines.append(f"- Unknown: {plain(text, 300)}")
    build, newsroom = signals["build"], signals["newsroom"]
    sources, intake = signals["sources"], signals["intake"]
    interval = build.get("expected_interval_seconds")
    since = newsroom.get("dispatches_since_last_story")
    lines += ["Measured signals:",
              f"- Last site build: {local_time(build.get('generated_at'))}, {age(build.get('age_seconds'))}"
              + (f"; expected every {duration(interval)}." if interval else "."),
              f"- Last newsroom dispatch: {local_time(newsroom.get('last_dispatch_at'))}, "
              f"{age(newsroom.get('age_seconds'))}; dispatches since the last new story: "
              + (f"{since}{'+' if newsroom.get('dispatches_at_least') else ''}." if since is not None else "unknown."),
              f"- Sources: {sources['failing']} of {sources['enabled']} enabled sources failing"
              + (f" ({plain(', '.join(sources['failing_ids'][:10]), 300)})." if sources["failing_ids"] else "."),
              "- Intake: " + (f"{intake['stories_in_window']} intake stories with a source time since the last new "
                              "story (candidates the newsroom could publish)."
                              if intake.get("stories_in_window") is not None else "unknown.")]
    lines.append("Updates edit this issue without comments. The next new story on the site closes it. "
                 "This alert is separate from the live health incident and the update failure alert.")
    if re.fullmatch(r"[A-Za-z0-9-]+", owner):
        lines.append(f"Owner: @{owner}. Notification delivery depends on GitHub account/repository settings.")
    title = f"Halcyon: no new story for {duration(report['quiet_seconds'])}{plus} ({label})"
    return {"title": title, "body": "\n\n".join(lines)}


def reconcile_quiet(report, api, repository, run_id, run_attempt, owner):
    """Open or update one issue while the feed is quiet; close it when a new story appears. Unknown changes nothing."""
    status = report.get("status")
    if status not in ("quiet", "fresh"):
        return "unchanged"
    stamp = instant(report.get("checked_at"))
    quiet = report.get("quiet_seconds")
    if (stamp is None or isinstance(quiet, bool) or not isinstance(quiet, int) or quiet < 0
            or report.get("diagnosis") not in DIAGNOSIS_LABELS or not valid_run(repository, run_id, run_attempt)):
        raise AlertError("Invalid quiet-feed report or workflow metadata; refusing to change an issue.")
    ordered = bot_issues(api, QUIET_MARKER, QUIET_OBSERVATION_PATTERN)
    if any(prior > stamp or (prior == stamp and status == "quiet" and issue.get("state") == "closed")
           for prior, issue in ordered):
        return "superseded"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    observation = ("<!-- radar-quiet-observation:" + json.dumps({"checked_at": report["checked_at"]}, sort_keys=True)
                   + " -->")
    open_issues = [issue for _, issue in sorted(ordered, key=lambda pair: pair[0], reverse=True)
                   if issue.get("state") == "open"]
    if status == "fresh":
        last = report.get("last_new_story") or {}
        for issue in open_issues:
            body = re.sub(QUIET_OBSERVATION_PATTERN + r"\s*", "", issue["body"])
            body += (f"\n\nNew story on the site: {plain(last.get('title') or last.get('id') or 'unknown', 300)}, "
                     f"first published at {local_time(last.get('appeared_at'))}. Closed at "
                     f"{local_time(report['checked_at'])}. [Monitor run and logs]({run_url}).\n\n{observation}")
            api.request("PATCH", f"/issues/{int(issue['number'])}",
                        {"body": body, "state": "closed", "state_reason": "completed"})
        return "resolved" if open_issues else "unchanged"
    payload = quiet_body(report, run_url, owner)
    if open_issues:
        issue = open_issues[0]
        if issue.get("body") == payload["body"] and issue.get("title") == payload["title"]:
            return "unchanged"
        api.request("PATCH", f"/issues/{int(issue['number'])}", payload)
        return "updated"
    api.request("POST", "/issues", payload)
    return "created"

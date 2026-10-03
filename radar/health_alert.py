"""Keep live-site incidents independent from update workflow incidents."""

import json
import re

from radar.failure_alert import AlertError, plain
from radar.health_probe import SITE_URL
from radar.items import instant

HEALTH_MARKER = "<!-- radar-live-health -->"
OBSERVATION_PATTERN = r"<!-- radar-health-observation:(\{[^\n]+\}) -->"


def issue_observation(issue):
    match = re.search(OBSERVATION_PATTERN, issue.get("body") or "")
    try:
        value = json.loads(match[1]) if match else {}
        stamp = instant(value.get("checked_at"))
    except (TypeError, ValueError):
        stamp = None
    if stamp is None:
        raise AlertError("Health issue has invalid observation metadata; inspect it before retrying.")
    return stamp


def reconcile_report(report, api, repository, run_id, run_attempt, owner):
    if report.get("status") == "inconclusive":
        return "unchanged"
    stamp = instant(report.get("checked_at"))
    status = report.get("status")
    confirmed = report.get("confirmed_failures")
    if (stamp is None or status not in ("healthy", "failed") or not isinstance(confirmed, list)
            or (status == "failed" and not confirmed) or (status == "healthy" and confirmed)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[1-9][0-9]*", str(run_id))
            or not re.fullmatch(r"[1-9][0-9]*", str(run_attempt))):
        raise AlertError("Invalid health report or workflow metadata; refusing to change an issue.")
    issues = [issue for issue in api.pages("/issues?state=all&creator=github-actions%5Bbot%5D")
              if "pull_request" not in issue and HEALTH_MARKER in (issue.get("body") or "")
              and issue.get("user", {}).get("login") == "github-actions[bot]"]
    ordered = [(issue_observation(issue), issue) for issue in issues]
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

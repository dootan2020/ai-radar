"""Consolidate failed update runs into one open GitHub issue per branch."""

import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FAILURES = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}


class AlertError(RuntimeError):
    """Safe-to-log error; never include tokens, response bodies or request headers."""


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise AlertError("Invalid GITHUB_REPOSITORY.")
        if not token:
            raise AlertError("Missing GITHUB_TOKEN; use the workflow's built-in token.")
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token

    def request(self, method, path, payload=None):
        request = Request(self.base + path, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-radar-failure-alert",
            "Content-Type": "application/json",
        }, data=None if payload is None else json.dumps(payload).encode("utf-8"))
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            raise AlertError(f"GitHub API HTTP {error.code}; check Actions/Issues permissions and repository Issues settings.") from None
        except (URLError, OSError, ValueError):
            raise AlertError("GitHub API unavailable or invalid JSON; inspect Actions logs and retry the alert workflow.") from None

    def pages(self, path, key=None):
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            data = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            items = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(items, list):
                raise AlertError("Unexpected GitHub API list; refusing to create a duplicate alert.")
            yield from items
            if len(items) < 100:
                return
        raise AlertError("GitHub pagination limit reached; refusing to create a duplicate alert.")


def plain(value, limit=1500):
    """Treat event and artifact text as prose, never mentions, HTML or Markdown."""
    text = " ".join(str(value).split())[:limit]
    return html.escape(text).replace("@", "@\u200b").replace("`", "'")


def publish_reason(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized diagnostic")
        status = json.loads(raw)
        if not isinstance(status, dict):
            raise ValueError("invalid diagnostic")
        if isinstance(status.get("reason"), str) and status["reason"]:
            return plain(status["reason"])
        if status.get("published") is True:
            return "Collection passed the publish gate; inspect the failed job below."
    except (OSError, ValueError):
        pass
    return "Publish diagnostics unavailable (the run may have stopped before collection). Inspect the run logs."


def report_failure(event, api, status_path):
    run = event["workflow_run"]
    repository = event["repository"]["full_name"]
    branch = run.get("head_branch") or "unknown"
    run_id, attempt = int(run["id"]), int(run.get("run_attempt", 1))
    marker = "<!-- radar-update-failure:" + hashlib.sha256(branch.encode()).hexdigest()[:20] + " -->"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{attempt}"
    body = [marker, f"Latest update result: **{plain(run['conclusion'])}**.",
            f"Branch: `{plain(branch)}`; commit: `{plain(run.get('head_sha', 'unknown'))}`.",
            f"[Open failed run and logs]({run_url}).",
            f"Publish reason: {publish_reason(status_path)}",
            f"Diagnostic: `data/publish-status.json` in artifact `radar-publish-status-{run_id}-{attempt}`."]
    try:
        jobs = api.pages(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
        for job in jobs:
            if job.get("conclusion") in FAILURES:
                body.append(f"- {plain(job['name'])}: {plain(job['conclusion'])}")
                for step in job.get("steps", []):
                    if step.get("conclusion") in FAILURES:
                        body.append(f"  - {plain(step['name'])}: {plain(step['conclusion'])}")
    except AlertError:
        body.append("Job details unavailable; use the run link above.")
    body.append("The last deployed site remains in place if collection or deployment failed. "
                "This issue is updated for repeated failures without adding comments. Close after investigating.")
    issues = api.pages("/issues?state=open&creator=github-actions%5Bbot%5D")
    existing = next((issue for issue in issues if "pull_request" not in issue
                     and marker in (issue.get("body") or "")
                     and issue.get("user", {}).get("login") == "github-actions[bot]"), None)
    # Mention the owner on creation. Later edits intentionally avoid notification spam.
    owner = event["repository"].get("owner", {}).get("login", "")
    if re.fullmatch(r"[A-Za-z0-9-]+", owner):
        body.append(f"Owner: @{owner}. GitHub notification delivery depends on account/repository settings.")
    payload = {"title": f"AI Radar update failed ({plain(branch, 100)})", "body": "\n\n".join(body)}
    if existing:
        if existing.get("body") == payload["body"] and existing.get("title") == payload["title"]:
            return "unchanged"
        api.request("PATCH", f"/issues/{int(existing['number'])}", payload)
        return "updated"
    api.request("POST", "/issues", payload)
    return "created"


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        run = event["workflow_run"]
        if event.get("action") != "completed" or run.get("conclusion") not in FAILURES:
            return 0
        repository = os.environ["GITHUB_REPOSITORY"]
        if (run.get("name") != "Update AI Radar"
                or event["repository"]["full_name"] != repository
                or run.get("head_repository", {}).get("full_name") != repository):
            raise AlertError("Unexpected workflow or repository; refusing to post an issue.")
        api = GitHub(repository, os.environ.get("GITHUB_TOKEN", ""))
        result = report_failure(event, api, os.environ.get("RADAR_PUBLISH_STATUS", "data/publish-status.json"))
        print(f"Failure alert {result}.")
        return 0
    except AlertError as error:
        print(f"Failure alert failed: {error}", file=sys.stderr)
    except (KeyError, TypeError, ValueError, OSError):
        print("Failure alert failed: invalid workflow event or missing environment. Check GITHUB_EVENT_PATH and GITHUB_REPOSITORY.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

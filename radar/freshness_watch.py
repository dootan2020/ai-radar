"""Measure how long hco.news has shown no new story; --report opens or closes the quiet-feed issue.

"New" means the first build that published a story. The site keeps no such time: a story's published_at is the
source's own time (13/11 22:00 for a story that went live 14/11 14:27). The durable record is the story archive on
branch radar-story-pages (radar/story_pages.py): every build appends the stories of the gated reader snapshot
site/data/radar-ui.json, one file per story ID, so the commit that adds stories/<id>.json is the build that first
published it. A story renamed by clustering keeps its old IDs as aliases, so it keeps its first appearance.

This runs on GitHub, independent of the machine that runs the newsroom: it still fires when that machine sleeps.
Every measurement it cannot make is reported as unknown, never as a healthy value.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic
from urllib.parse import urlsplit

from radar.failure_alert import AlertError, GitHub
from radar.health_alert import duration, reconcile_quiet
from radar.health_probe import MAX_BYTES, ProbeError, fetch, parse_snapshot
from radar.items import instant
from radar.publication import EXPECTED_INTERVAL_SECONDS
from radar.site_config import SITE_URL

# Measured over 7 days of radar-story-pages history (07/11-14/11): new stories arrive with the newsroom's cycles,
# and the normal rhythm leaves gaps up to 4.4 h. 4 h would have alerted 14 times that week, 10 of them on that
# rhythm; 5 h alerts 4 times, each a stretch in which the newsroom missed cycles (longest 19.7 h, 12-13/11).
QUIET_AFTER_SECONDS = 5 * 3600
STORY_BRANCH = "radar-story-pages"  # radar.story_pages.BRANCH
DECISIONS_BRANCH = "newsroom-decisions"  # the newsroom publishes decisions.json here (update.yml fetches it)
HISTORY_DEPTH = 400  # one archive commit per build, about 60 a day: roughly a week
NEWSROOM_DEPTH = 30  # the newsroom runs every 2 hours (phong-bao/cong-cu/register-newsroom-cycle.ps1)
NEWSROOM_LATE_AFTER_SECONDS = 3 * 3600  # one missed cycle plus an hour of run time
BUILD_LATE_FACTOR = 3  # a build older than three expected intervals is late
HISTORY_LAG_SECONDS = 3 * EXPECTED_INTERVAL_SECONDS  # archive persisting behind the live build: cannot measure
SOURCE_FAILURE_SHARE = 0.25
INTAKE_MAX_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT = 90
GIT_TIMEOUT = 120


class WatchError(RuntimeError):
    """A bounded diagnostic safe to print: never remote text or credentials."""


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _git_environment(remote):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    parsed = urlsplit(remote)
    if parsed.username or parsed.password:
        raise WatchError("Remote URLs must not contain credentials.")
    token = env.get("GITHUB_TOKEN")
    server = env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if token and remote.startswith(server + "/"):
        import base64
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env[f"GIT_CONFIG_KEY_{count}"] = f"http.{server}/.extraheader"
        env[f"GIT_CONFIG_VALUE_{count}"] = "AUTHORIZATION: basic " + authorization
        env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def _git(env, *args):
    try:
        result = subprocess.run(["git", *args], env=env, capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        raise WatchError(f"History git {args[2] if args[0] == '-C' else args[0]} could not run.") from None
    if result.returncode:
        raise WatchError(f"History git {args[2] if args[0] == '-C' else args[0]} failed (exit {result.returncode}).")
    return result.stdout.decode("utf-8")


def _shallow_fetch(env, remote, directory, branch, depth):
    """A tree-only (no file contents) shallow copy of one branch; returns its boundary commits."""
    _git(env, "init", "-q", "--bare", str(directory))
    _git(env, "-C", str(directory), "fetch", "-q", "--no-tags", "--filter=blob:none", f"--depth={depth}",
         remote, f"+refs/heads/{branch}:refs/heads/watch")
    shallow = directory / "shallow"
    return set(shallow.read_text(encoding="utf-8").split()) if shallow.is_file() else set()


def _commit_times(env, directory):
    rows = []
    for line in _git(env, "-C", str(directory), "log", "--format=%H %cI", "watch").splitlines():
        sha, stamp = line.split(" ")
        rows.append((sha, instant(stamp)))
    if not rows or any(stamp is None for _, stamp in rows):
        raise WatchError("History commits have no readable time.")
    return rows


def parse_additions(log_text, boundaries):
    """Story ID -> time of the commit that added stories/<id>.json, skipping shallow boundary commits.

    A boundary commit has no parent in a shallow copy, so git shows every file it holds as added there.
    """
    additions, skip, stamp = {}, False, None
    for line in log_text.splitlines():
        if line.startswith("@@"):
            sha, value = line[2:].split(" ")
            skip, stamp = sha in boundaries, instant(value)
            if stamp is None:
                raise WatchError("History commit has no readable time.")
        elif line.startswith("stories/") and line.endswith(".json") and not skip:
            story_id = line[len("stories/"):-len(".json")]
            additions[story_id] = min(stamp, additions.get(story_id, stamp))
    return additions


def read_history(remote):
    """The story archive's additions and the newsroom's dispatch times, from GitHub without file contents."""
    env = _git_environment(remote)
    with tempfile.TemporaryDirectory(prefix="radar-quiet-") as temporary:
        stories, decisions = Path(temporary) / "stories.git", Path(temporary) / "decisions.git"
        boundaries = _shallow_fetch(env, remote, stories, STORY_BRANCH, HISTORY_DEPTH)
        commits = _commit_times(env, stories)
        log = _git(env, "-C", str(stories), "log", "--diff-filter=A", "--name-only", "--format=@@%H %cI",
                   "watch", "--", "stories/")
        listed = _git(env, "-C", str(stories), "ls-tree", "--name-only", "watch", "stories/").splitlines()
        archived = {name[len("stories/"):-len(".json")] for name in listed
                    if name.startswith("stories/") and name.endswith(".json")}
        newsroom_boundaries = _shallow_fetch(env, remote, decisions, DECISIONS_BRANCH, NEWSROOM_DEPTH)
        newsroom = _commit_times(env, decisions)
    return {"additions": parse_additions(log, boundaries), "archived": archived,
            "history_start": commits[-1][1], "head_at": commits[0][1],
            "newsroom": [stamp for _, stamp in newsroom],
            "newsroom_complete": not any(sha in newsroom_boundaries for sha, _ in newsroom)}


def _valid_story(story):
    return isinstance(story, dict) and isinstance(story.get("id"), str) and story["id"]


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def assess(now, ui, feed, past):
    """The quiet-feed report from the live snapshot, the intake snapshot and the archive history."""
    unknowns, problems = [], []
    report = {"checked_at": iso(now), "status": "unknown", "threshold_seconds": QUIET_AFTER_SECONDS,
              "quiet_seconds": None, "quiet_at_least": False, "last_new_story": None, "diagnosis": "unknown",
              "problems": problems, "unknowns": unknowns, "signals": {}}
    signals = report["signals"]

    ui = ui if isinstance(ui, dict) else {}
    generated = instant(ui.get("generated_at"))
    stories = ui.get("stories")
    if generated is None or not isinstance(stories, list) or not all(_valid_story(story) for story in stories):
        unknowns.append("Live snapshot data/radar-ui.json is unavailable or has no generated_at or stories.")
        generated, stories = None, None

    freshness = ui.get("freshness") if isinstance(ui.get("freshness"), dict) else {}
    interval = _number(freshness.get("expected_interval_seconds"))
    build = signals["build"] = {"generated_at": iso(generated), "age_seconds": None,
                                "expected_interval_seconds": interval, "late": None}
    if generated is not None:
        build["age_seconds"] = int((now - generated).total_seconds())
        if interval is None:
            unknowns.append("The live snapshot does not state its expected build interval.")
        else:
            build["late"] = build["age_seconds"] > BUILD_LATE_FACTOR * interval
            if build["late"]:
                problems.append(f"Last site build is {duration(build['age_seconds'])} old; "
                                f"builds are expected every {duration(interval)}.")

    if not isinstance(past, dict):
        unknowns.append(f"Story history (branch {STORY_BRANCH}) could not be read.")
        past = None
    archive = past
    history = signals["story_history"] = {"head_at": iso(past["head_at"]) if past else None, "lag_seconds": None}
    if past and generated is not None:
        history["lag_seconds"] = int((generated - past["head_at"]).total_seconds())
        if history["lag_seconds"] > HISTORY_LAG_SECONDS:
            unknowns.append(f"Story history stopped {duration(history['lag_seconds'])} before the live build; "
                            "new stories cannot be seen until it catches up.")
            archive = None

    window_start = None
    if archive and stories is not None:
        additions, archived = archive["additions"], archive["archived"]
        seen = []
        for story in stories:
            names = [story["id"]] + [alias for alias in story.get("aliases") or [] if isinstance(alias, str)]
            known = [name for name in names if name in archived]
            if not known:
                first = generated  # live now, not yet persisted: published by the current build
            elif all(name in additions for name in known):
                first = min(additions[name] for name in known)
            else:
                continue  # archived before the fetched history began
            seen.append((first, story))
        if seen:
            first, story = max(seen, key=lambda pair: (pair[0], pair[1]["id"]))
            window_start = first
            report["last_new_story"] = {"id": story["id"], "appeared_at": iso(first),
                                        "title": story.get("editorial_headline_vi") or story.get("title")}
        else:
            window_start = archive["history_start"]
            report["quiet_at_least"] = True
        report["quiet_seconds"] = max(0, int((now - window_start).total_seconds()))
        report["status"] = "quiet" if report["quiet_seconds"] >= QUIET_AFTER_SECONDS else "fresh"

    newsroom = signals["newsroom"] = {"last_dispatch_at": None, "age_seconds": None, "late": None,
                                      "dispatches_since_last_story": None, "dispatches_at_least": False}
    times = past and past.get("newsroom")
    if not times:
        unknowns.append(f"Newsroom dispatch history (branch {DECISIONS_BRANCH}) is unavailable.")
    else:
        newsroom["last_dispatch_at"] = iso(times[0])
        newsroom["age_seconds"] = int((now - times[0]).total_seconds())
        newsroom["late"] = newsroom["age_seconds"] > NEWSROOM_LATE_AFTER_SECONDS
        if newsroom["late"]:
            problems.append(f"Last newsroom dispatch was {duration(newsroom['age_seconds'])} ago; "
                            "the newsroom runs every 2 hours.")
        if window_start is not None:
            newsroom["dispatches_since_last_story"] = sum(1 for stamp in times if stamp > window_start)
            newsroom["dispatches_at_least"] = (not past["newsroom_complete"]
                                               and all(stamp > window_start for stamp in times))

    sources = ui.get("sources") if isinstance(ui.get("sources"), list) else []
    enabled = [row for row in sources if isinstance(row, dict) and not row.get("disabled")]
    failing = sorted(str(row.get("id")) for row in enabled if row.get("ok") is not True)
    signals["sources"] = {"enabled": len(enabled), "failing": len(failing), "failing_ids": failing[:20],
                          "late": None}
    if not enabled:
        unknowns.append("The live snapshot lists no enabled sources.")
    else:
        signals["sources"]["late"] = len(failing) > SOURCE_FAILURE_SHARE * len(enabled)
        if signals["sources"]["late"]:
            problems.append(f"{len(failing)} of {len(enabled)} enabled sources failed their last fetch.")

    intake = signals["intake"] = {"generated_at": None, "stories_in_window": None}
    feed_stories = feed.get("stories") if isinstance(feed, dict) else None
    if not isinstance(feed_stories, list):
        unknowns.append("Intake snapshot data/radar-intake.json is unavailable.")
    else:
        intake["generated_at"] = iso(instant(feed.get("generated_at")))
        if window_start is not None:
            stamps = [instant(row.get("published_at")) for row in feed_stories if isinstance(row, dict)]
            intake["stories_in_window"] = sum(1 for stamp in stamps if stamp and window_start <= stamp <= now)

    if report["status"] == "unknown":
        report["diagnosis"] = "unknown"
    elif problems:
        report["diagnosis"] = "pipeline"
    elif unknowns:
        report["diagnosis"] = "unknown"
    else:
        report["diagnosis"] = "quiet-news"
    return report


def _json(url, deadline, limit):
    try:
        return parse_snapshot(fetch(url, deadline, limit))
    except ProbeError:
        return None


def collect_report(remote):
    deadline = monotonic() + FETCH_TIMEOUT
    ui = _json(SITE_URL + "data/radar-ui.json", deadline, MAX_BYTES)
    feed = _json(SITE_URL + "data/radar-intake.json", deadline, INTAKE_MAX_BYTES)
    error = None
    try:
        past = read_history(remote)
    except WatchError as failure:
        past, error = None, str(failure)
    report = assess(datetime.now(timezone.utc), ui, feed, past)
    if error:
        report["unknowns"].append(error)
    return report


def summary(report):
    if report["quiet_seconds"] is None:
        return f"hco.news quiet time unknown; status {report['status']}; " + " ".join(report["unknowns"])
    plus = "+" if report["quiet_at_least"] else ""
    last = report["last_new_story"]
    since = f"last new story {last['id']} at {last['appeared_at']}" if last else "no new story in fetched history"
    return (f"hco.news quiet for {duration(report['quiet_seconds'])}{plus} ({since}); "
            f"threshold {duration(report['threshold_seconds'])}; status {report['status']}; "
            f"diagnosis {report['diagnosis']}.")


def default_remote():
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise WatchError("Pass --remote or set GITHUB_REPOSITORY.")
    return os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/") + f"/{repository}.git"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="Reconcile the quiet-feed issue using the workflow token")
    parser.add_argument("--remote", help="Git URL of the repository holding the story archive")
    options = parser.parse_args(argv)
    try:
        report = collect_report(options.remote or default_remote())
        print(summary(report))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if report["status"] == "unknown":
            print("Quiet-feed watch could not measure the quiet time; the alert is left unchanged.", file=sys.stderr)
            return 1
        if options.report:
            repository = os.environ["GITHUB_REPOSITORY"]
            api = GitHub(repository, os.environ.get("GITHUB_TOKEN", ""))
            result = reconcile_quiet(report, api, repository, os.environ["GITHUB_RUN_ID"],
                                     os.environ["GITHUB_RUN_ATTEMPT"], os.environ["GITHUB_REPOSITORY_OWNER"])
            print(f"Quiet-feed alert {result}.")
        return 0
    except (AlertError, WatchError) as error:
        print(f"Quiet-feed watch failed: {error}", file=sys.stderr)
    except (KeyError, TypeError, ValueError, OSError):
        print("Quiet-feed watch failed: invalid report or missing workflow environment.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

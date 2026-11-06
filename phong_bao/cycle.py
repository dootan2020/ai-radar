"""Scheduled, incremental local newsroom cycle."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from radar.items import instant
from radar.newsroom_decisions import SCORE_THRESHOLD, SCORER_VERSION, prose_digest, score_passed, weighted_score

from .discovery import discover_raw
from .newsroom import (DEFAULT_CALL_TIMEOUT_SECONDS, DEFAULT_DESK_BUDGET_SECONDS, DEFAULT_RUN_BUDGET_SECONDS,
                       DEFAULT_SCORER_BUDGET_SECONDS, DEFAULT_WRITER_BUDGET_SECONDS, Articles, _score_prose,
                       _write_json, _writer, run, writer_window_hours, written_fields)
from .registry import load_registry, providers
from .runner import CLIRunner
from .scoring import review_request, scorer_packet


SNAPSHOT_URL = "https://radar-ai-vn.pages.dev/data/radar-intake.json"
USER_AGENT = "Mozilla/5.0 (compatible; AIRadarNewsroom/1.0)"
ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = ROOT / "phong-bao" / "decisions.json"
CYCLES_DIR = ROOT / "phong-bao" / "cycles"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# A published story whose writer step failed (a hung or timed-out call, a model failure, the writer budget running
# out, or its one rewrite failing that way) gets another full writer pass in a later cycle while it is inside the
# writer window, built from the desk outputs its own cycle stored; no other desk runs again. Measured 06/11: one
# hung agy call left 20 checked stories of the 06:00 cycle on a 300-character machine-translated snippet for good.
# New stories always go first: retries run after the cycle's own writer, only on the writer budget it left, and at
# most WRITER_RETRY_LIMIT stories, newest first. Twelve is four writer calls of three stories (median 3.7 minutes
# each), so a backlog drains over a few cycles instead of stretching one past its budget.
WRITER_RETRY_LIMIT = 12
# A story sent to the writer twice by retries without prose stops being retried; a retry cut by the budget before
# its call does not count as an attempt.
WRITER_RETRY_ATTEMPTS = 2
# Written prose the scoring desk has not passed is hidden until it does (captain 06/11: no story that misses the bar
# reaches readers). Inside the writer window a retry either scores prose that has no verdict (a failed, refused or
# timed-out scorer call, or prose written before the desk existed), using the source paragraphs its writer row
# stored, or writes a story again with the scorer's findings when its verdict failed. A re-score is one scorer
# call per four stories, so more of them fit a cycle; each kind of attempt has its own limit of two.
RESCORE_LIMIT = 24
# A one-off backfill can raise the limit for one run (the scheduled script passes its environment to the cycle);
# whatever the scorer budget does not reach is cut, which is not an attempt, and the next cycle continues.
RESCORE_LIMIT_ENV = "PHONG_BAO_RESCORE_LIMIT"
SCORE_ATTEMPTS = 2
RETRY_DIR = "viet-bu"


@contextmanager
def cycle_lock(path):
    """Keep an OS lock for the complete cycle; the lock file itself is reusable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("newsroom cycle already running") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def fetch_snapshot(url=SNAPSHOT_URL):
    def read(address):
        with urlopen(Request(address, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
            headers = getattr(response, "headers", {})
            content_type = headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type in {"text/html", "application/xhtml+xml"}:
                raise ValueError("snapshot response is not JSON")
            try:
                return json.loads(response.read())
            except json.JSONDecodeError as error:
                raise ValueError("snapshot response is not JSON") from error

    try:
        return read(url)
    except (HTTPError, ValueError) as error:
        fallbackable = isinstance(error, ValueError) or error.code == 404
        if not fallbackable or not url.endswith("/radar-intake.json"):
            raise
        return read(url.removesuffix("radar-intake.json") + "radar.json")


def _read_history(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("decisions") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(rows, list) or any(
            not isinstance(row, dict) or not row.get("id") or row.get("decision") not in {"hold", "publish"}
            for row in rows):
        raise ValueError("invalid newsroom decision history")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate newsroom decision IDs")
    return rows


def _lanes_available(tools, discovery):
    editors = [tool for tool in providers("bien-tap", tools, discovery)
               if tool.get("runner") == "batch-cli" and tool.get("cost_class") == "subscription"]
    checkers = [tool for tool in providers("kiem-chung", tools, discovery)
                if tool.get("runner") == "batch-cli" and tool.get("cost_class") == "subscription"]
    return any(editor.get("boat") != checker.get("boat") for editor in editors for checker in checkers)


def _story_timestamp(story):
    values = []
    for key in ("published_at", "latest_coverage_at"):
        value = story.get(key)
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                continue
            values.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc))
    return max(values) if values else None


def _json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _writer_failed(row):
    """The writer took the story but no reply came back: a failed, hung or timed-out call, or one cut by the budget."""
    rewrite = row.get("rewrite") if isinstance(row, dict) else None
    return bool(isinstance(row, dict) and not row.get("written") and "writer_sources" in row
                and (row.get("reason") == "writer_model_failure"
                     or isinstance(rewrite, dict) and rewrite.get("result") == "rewrite_model_failure"))


def _stored_cycles(cycles_dir, since, current=None):
    found = []
    for path in (Path(cycles_dir).iterdir() if Path(cycles_dir).is_dir() else ()):
        try:
            stamp = datetime.strptime(path.name, STAMP_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if path.is_dir() and stamp >= since and (current is None or path.resolve() != Path(current).resolve()):
            found.append((stamp, path))
    return [path for _, path in sorted(found)]


def rescore_limit(env=None):
    raw = (os.environ if env is None else env).get(RESCORE_LIMIT_ENV)
    try:
        return max(0, int(raw)) if raw is not None and str(raw).strip() else RESCORE_LIMIT
    except ValueError:
        return RESCORE_LIMIT


def _failed_verdict(row):
    """A current verdict on the row's own prose that failed it (below the bar or a hard error), so its findings can
    guide a rewrite. Any other unpassed prose (no verdict, an old version, other text) is scored again instead."""
    score = row.get("score")
    if (not isinstance(score, dict) or score.get("version") != SCORER_VERSION
            or not isinstance(score.get("hard_errors"), list) or not isinstance(score.get("findings"), list)
            or score.get("prose_sha256") != prose_digest(row.get("editorial_headline_vi"), row.get("key_points"))):
        return False
    value = weighted_score(score.get("answers"))
    return value is not None and (bool(score["hard_errors"]) or value < SCORE_THRESHOLD)


def _rewrite_boats(folder, sid, tools):
    """Boats of the paragraph rewrites stored for a story in one writer folder (raw/rewrite-writer-*.json)."""
    boat_of = {tool["id"]: tool.get("boat") for tool in tools or ()}
    boats = set()
    for path in sorted((Path(folder) / "raw").glob("rewrite-writer-*.json")):
        raw = _json_file(path)
        if (isinstance(raw, dict) and isinstance(raw.get("stories"), list)
                and any(isinstance(row, dict) and row.get("id") == sid for row in raw["stories"])):
            boats.add(boat_of.get(raw.get("provider"), raw.get("provider")))
    return boats


def _stored_prose(row, folder, sid, tools):
    """(writer boats, source paragraphs) of a stored writer row, or None when it lacks what a scorer needs."""
    if not isinstance(row, dict) or not row.get("written") or not isinstance(row.get("writer_sources"), list):
        return None
    if isinstance(row.get("writer_boats"), list):
        boats = set(row["writer_boats"])
    else:
        # Prose written before the scoring desk existed: the draft's boat, the source editor's and, when the
        # published text took a paragraph rewrite, the boats that rewrite ran on.
        boats = {row.get("boat"), row.get("editor_boat")}
        if str(row.get("sheet_path")).endswith("_after_rewrite") or isinstance(row.get("rewrite"), dict):
            boats |= _rewrite_boats(folder, sid, tools)
    boats = {boat for boat in boats if isinstance(boat, str) and boat}
    return (boats, row["writer_sources"]) if boats else None


def writer_retries(old, stories, cycles_dir, now, *, current=None, limit=WRITER_RETRY_LIMIT, tools=None,
                   rescore_limit=RESCORE_LIMIT):
    """Published stories inside the writer window that are not yet shown and may be now, newest first.

    Each candidate has a mode. "write": a checked story ("claims" summary) whose writer step failed. "rewrite": desk
    prose whose verdict failed, written again with that verdict's findings. "score": desk prose with no current
    verdict, scored from the source paragraphs its stored writer row kept. A held story never comes back. Write
    candidates carry the intake, reporter and editor rows their own cycle stored, so the writer runs as it did there.
    """
    hours = writer_window_hours()
    if hours <= 0:
        return []
    since = now - timedelta(hours=hours)
    rows_by_id = {row["id"]: row for row in old if row.get("decision") == "publish"
                  and (row.get("summary") == "claims"
                       or row.get("summary") == "written" and not score_passed(row))}
    if not rows_by_id:
        return []
    origin, failed, prose = {}, {}, {}
    attempts, score_attempts = Counter(), Counter()
    for path in _stored_cycles(cycles_dir, since, current):
        for folder in (path / "job", path / RETRY_DIR):
            writer = _json_file(folder / "writer.json")
            if not isinstance(writer, dict):
                continue
            for sid in rows_by_id.keys() & writer.keys():
                if folder.name == "job":
                    origin[sid], failed[sid] = path, _writer_failed(writer[sid])
                row = rows_by_id[sid]
                stored = writer[sid]
                if (isinstance(stored, dict) and stored.get("key_points") == row.get("key_points")
                        and stored.get("editorial_headline_vi") == row.get("editorial_headline_vi")):
                    found = _stored_prose(stored, folder, sid, tools)
                    if found:
                        prose[sid] = found
        retry = _json_file(path / RETRY_DIR / "status.json")
        if isinstance(retry, dict):
            if isinstance(retry.get("sent"), list):
                attempts.update(sid for sid in retry["sent"] if sid in rows_by_id)
            if isinstance(retry.get("scored"), list):
                score_attempts.update(sid for sid in retry["scored"] if sid in rows_by_id)
    by_id = {row["id"]: row for row in stories}
    desks = {}
    writes, scores = [], []
    for sid, row in rows_by_id.items():
        story = by_id.get(sid)
        published = instant(story.get("published_at")) if story else None
        if not published or published < since:
            continue
        if row["summary"] == "written" and not _failed_verdict(row):
            if sid in prose and score_attempts[sid] < SCORE_ATTEMPTS:
                boats, sources = prose[sid]
                scores.append({"id": sid, "mode": "score", "published": published, "writer_boats": sorted(boats),
                               "packet": scorer_packet(sid, sources, row["editorial_headline_vi"], row["key_points"])})
            continue
        path = origin.get(sid)
        if path is None or attempts[sid] >= WRITER_RETRY_ATTEMPTS:
            continue
        if row["summary"] == "claims" and not failed.get(sid):
            continue
        if path not in desks:
            desks[path] = {desk: _json_file(path / "job" / f"{desk}.json") for desk in ("intake", "reporter", "editor")}
        rows = {desk: value.get(sid) if isinstance(value, dict) else None for desk, value in desks[path].items()}
        if any(not isinstance(value, dict) for value in rows.values()):
            continue
        candidate = {"id": sid, "mode": "write", "story": story, "cycle": path.name, "published": published, **rows}
        if row["summary"] == "written":
            candidate.update(mode="rewrite", review=review_request(row["score"], row["editorial_headline_vi"],
                                                                    row["key_points"]))
        writes.append(candidate)
    newest = lambda row: (row["published"], row["id"])  # noqa: E731
    writes.sort(key=newest, reverse=True)
    scores.sort(key=newest, reverse=True)
    return writes[:limit] + scores[:rescore_limit]


def _retry_writer(candidates, decisions, job_dir, tools, discovery, runner, articles, now, deadline, call_timeout,
                  *, run_deadline=None, scorer_budget_seconds=DEFAULT_SCORER_BUDGET_SECONDS):
    """Write, rewrite or score the candidates once more and update their decisions; nothing else changes.

    New prose replaces a decision's summary with its verdict (None when it could not be scored); a score-only
    candidate gets the verdict on its existing prose. Only a passing verdict makes a story visible.
    """
    retry_dir = job_dir / RETRY_DIR
    writes = [row for row in candidates if row["mode"] in {"write", "rewrite"}]
    scores = [row for row in candidates if row["mode"] == "score"]
    ids = [row["id"] for row in writes]
    output, usage = {}, []
    if writes and time.monotonic() >= deadline:
        usage = [{"event": "budget_exhausted", "ids": ids}]
    elif writes:
        output, usage = _writer([row["story"] for row in writes],
                                {row["id"]: row["intake"] for row in writes},
                                {row["id"]: row["reporter"] for row in writes},
                                {row["id"]: row["editor"] for row in writes},
                                articles or Articles(), tools, discovery, runner, now, retry_dir / "raw", deadline,
                                call_timeout=call_timeout,
                                reviews={row["id"]: row["review"] for row in writes if row["mode"] == "rewrite"},
                                scorer_budget_seconds=scorer_budget_seconds, run_deadline=run_deadline)
    # Only the first writer pass decides whether a story reached a model; later passes record their own desk.
    cut = {sid for row in usage if "desk" not in row and row.get("event") in {"budget_exhausted", "writer_unavailable"}
           for sid in row["ids"]}
    sent = [sid for sid in ids if sid not in cut and "writer_sources" in output.get(sid, {})]
    by_id = {row["id"]: row for row in decisions}
    written = []
    for sid in ids:
        row, prose = by_id.get(sid), output.get(sid)
        if (row and row.get("decision") == "publish" and row.get("summary") in {"claims", "written"}
                and prose and prose["written"]):
            row.update(written_fields(prose))
            written.append(sid)
    score_ids, scored, verdicts = [row["id"] for row in scores], [], {}
    if scores:
        score_deadline = time.monotonic() + scorer_budget_seconds
        if run_deadline is not None:
            score_deadline = min(score_deadline, run_deadline)
        verdicts, events = _score_prose({row["id"]: row["packet"] for row in scores},
                                        {row["id"]: row["writer_boats"] for row in scores}, tools, discovery, runner,
                                        raw_dir=retry_dir / "raw", deadline=score_deadline, call_timeout=call_timeout,
                                        record_as="rescorer")
        usage.extend(events)
        # A score attempt counts once a scorer call was made for the story; no lane or no time does not count.
        unreached = {sid for row in events if row.get("event") in {"budget_exhausted", "scorer_unavailable"}
                     for sid in row["ids"]}
        scored = [sid for sid in score_ids if sid not in unreached]
        for sid, result in verdicts.items():
            row = by_id.get(sid)
            if row is not None and result["score"] is not None:
                row["score"] = result["score"]
    passed = [sid for sid in ids + score_ids if score_passed(by_id.get(sid))]
    result = {"candidates": ids, "cycles": {row["id"]: row["cycle"] for row in writes},
              "modes": {row["id"]: row["mode"] for row in candidates}, "sent": sent,
              "budget_cut": [sid for sid in ids if sid in cut], "written": written,
              "score_candidates": score_ids, "scored": scored,
              "score_results": {sid: verdicts[sid]["state"] for sid in verdicts}, "passed": passed,
              "events": [row for row in usage if row.get("event")]}
    if output:
        _write_json(retry_dir / "writer.json", output)
    _write_json(retry_dir / "status.json", result)
    return {"candidates": len(ids), "sent": len(sent), "budget_cut": len(result["budget_cut"]), "written": len(written),
            "score_candidates": len(score_ids), "scored": len(scored), "passed": len(passed)}


def cycle(*, snapshot_url=SNAPSHOT_URL, snapshot_fetcher=None, decisions_path=DECISIONS_PATH, cycles_dir=CYCLES_DIR,
          discovery=None, runner=None, articles=None, tools=None,
          desk_budget_seconds=DEFAULT_DESK_BUDGET_SECONDS, writer_budget_seconds=DEFAULT_WRITER_BUDGET_SECONDS,
          run_budget_seconds=DEFAULT_RUN_BUDGET_SECONDS, call_timeout_seconds=DEFAULT_CALL_TIMEOUT_SECONDS,
          since_hours=36, now=None):
    """Review new story IDs and keep every earlier decision, including holds; retry writer failures after them."""
    decisions_path, cycles_dir = Path(decisions_path), Path(cycles_dir)
    with cycle_lock(cycles_dir / "cycle.lock"):
        clock_started = time.monotonic()
        started = now or datetime.now(timezone.utc)
        stamp = started.strftime("%Y%m%dT%H%M%SZ")
        job_dir = cycles_dir / stamp
        if job_dir.exists():
            raise ValueError("cycle timestamp already exists")
        job_dir.mkdir(parents=True)
        old = _read_history(decisions_path)
        known = {row["id"] for row in old}
        snapshot = snapshot_fetcher() if snapshot_fetcher is not None else fetch_snapshot(snapshot_url)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("stories"), list):
            raise ValueError("published snapshot has no stories")
        stories = snapshot["stories"]
        if any(not isinstance(row, dict) or not row.get("id") for row in stories):
            raise ValueError("published snapshot contains invalid stories")
        if len({row["id"] for row in stories}) != len(stories):
            raise ValueError("published snapshot contains duplicate story IDs")
        cutoff = started - timedelta(hours=since_hours)
        recent = [row for row in stories if (timestamp := _story_timestamp(row)) is not None and timestamp >= cutoff]
        new = [row for row in recent if row["id"] not in known]
        # The writer judges its window against the snapshot time, as run() does.
        writer_now = instant(snapshot.get("generated_at")) or started
        retries = writer_retries(old, stories, cycles_dir, writer_now, current=job_dir,
                                 tools=tools if tools is not None else load_registry(), rescore_limit=rescore_limit())
        _write_json(job_dir / "status.json", {"started_at": started.isoformat(), "considered_count": len(recent), "new_count": len(new),
                                              "writer_retry_count": len(retries), "state": "running"})
        fresh, writer_used, retried = [], 0.0, None
        if new or retries:
            tools = [tool for tool in (tools if tools is not None else load_registry())
                     if tool.get("cost_class") != "paid"]
            discovery = discovery if discovery is not None else discover_raw()
            runner = runner or CLIRunner()
        if not new:
            state = "no_new_stories"
        elif not _lanes_available(tools, discovery):
            state = "dry_lane"
        else:
            state = "decided"
            with tempfile.TemporaryDirectory() as temp:
                input_path = Path(temp) / "input.json"
                corpus_path = Path(temp) / "corpus.json"
                _write_json(input_path, {"generated_at": snapshot.get("generated_at"), "stories": new})
                _write_json(corpus_path, snapshot)
                job_status = run(input_path, job_dir / "job", tools, discovery, runner,
                                 articles=articles, corpus_path=corpus_path,
                                 desk_budget_seconds=desk_budget_seconds, writer_budget_seconds=writer_budget_seconds,
                                 run_budget_seconds=run_budget_seconds, call_timeout_seconds=call_timeout_seconds)
                fresh = json.loads((job_dir / "job" / "quyet-dinh.json").read_text(encoding="utf-8"))["decisions"]
            if {row["id"] for row in fresh} != {row["id"] for row in new}:
                raise ValueError("newsroom did not decide every new story")
            writer_used = job_status["desks"].get("writer", {}).get("seconds", 0.0)
        if retries and state != "dry_lane":
            deadline = min(clock_started + run_budget_seconds,
                           time.monotonic() + max(0.0, writer_budget_seconds - writer_used))
            try:
                retried = _retry_writer(retries, old, job_dir, tools, discovery, runner, articles, writer_now,
                                        deadline, call_timeout_seconds, run_deadline=clock_started + run_budget_seconds)
            except Exception as error:
                # Retries are an addition: a failure here must not lose this cycle's own decisions.
                retried = {"candidates": len(retries), "error": str(error)[:300]}
        status = {"started_at": started.isoformat(), "state": state, "considered_count": len(recent), "new_count": len(new),
                  "decided_count": len(fresh), "total_decisions": len(old) + len(fresh)}
        if retried is not None:
            status["writer_retry"] = retried
        if state != "dry_lane":
            value = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                     "input_generated_at": snapshot.get("generated_at"), "decisions": old + fresh}
            _write_json(job_dir / "quyet-dinh.json", {**value, "decisions": fresh})
            _write_json(decisions_path, value)
        _write_json(job_dir / "status.json", status)
        return status

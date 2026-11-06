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

from .discovery import discover_raw
from .newsroom import (DEFAULT_CALL_TIMEOUT_SECONDS, DEFAULT_DESK_BUDGET_SECONDS, DEFAULT_RUN_BUDGET_SECONDS,
                       DEFAULT_WRITER_BUDGET_SECONDS, Articles, _write_json, _writer, run, writer_window_hours,
                       written_fields)
from .registry import load_registry, providers
from .runner import CLIRunner


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


def writer_retries(old, stories, cycles_dir, now, *, current=None, limit=WRITER_RETRY_LIMIT):
    """Published, checked stories whose writer step failed and may be written now, newest first.

    Only a "publish" decision with a "claims" summary qualifies: a written, held or summary-less story never goes
    back to the writer. Each candidate carries the snapshot story and the intake, reporter and editor rows its own
    cycle stored, so the writer runs exactly as it did there.
    """
    hours = writer_window_hours()
    if hours <= 0:
        return []
    since = now - timedelta(hours=hours)
    open_ids = {row["id"] for row in old if row.get("decision") == "publish" and row.get("summary") == "claims"}
    if not open_ids:
        return []
    failed, attempts = {}, Counter()
    for path in _stored_cycles(cycles_dir, since, current):
        writer = _json_file(path / "job" / "writer.json")
        if isinstance(writer, dict):
            for sid in open_ids.intersection(writer):
                failed[sid] = path if _writer_failed(writer[sid]) else None
        retry = _json_file(path / RETRY_DIR / "status.json")
        if isinstance(retry, dict) and isinstance(retry.get("sent"), list):
            attempts.update(sid for sid in retry["sent"] if sid in open_ids)
    by_id = {row["id"]: row for row in stories}
    desks = {}
    candidates = []
    for sid, path in failed.items():
        story = by_id.get(sid)
        published = instant(story.get("published_at")) if story else None
        if path is None or attempts[sid] >= WRITER_RETRY_ATTEMPTS or not published or published < since:
            continue
        if path not in desks:
            desks[path] = {desk: _json_file(path / "job" / f"{desk}.json") for desk in ("intake", "reporter", "editor")}
        rows = {desk: value.get(sid) if isinstance(value, dict) else None for desk, value in desks[path].items()}
        if any(not isinstance(row, dict) for row in rows.values()):
            continue
        candidates.append({"id": sid, "story": story, "cycle": path.name, "published": published, **rows})
    candidates.sort(key=lambda row: (row["published"], row["id"]), reverse=True)
    return candidates[:limit]


def _retry_writer(candidates, decisions, job_dir, tools, discovery, runner, articles, now, deadline, call_timeout):
    """Run the writer once more for the candidates and add their prose to the decisions; nothing else changes."""
    retry_dir = job_dir / RETRY_DIR
    ids = [row["id"] for row in candidates]
    if time.monotonic() >= deadline:
        output, usage = {}, [{"event": "budget_exhausted", "ids": ids}]
    else:
        output, usage = _writer([row["story"] for row in candidates],
                                {row["id"]: row["intake"] for row in candidates},
                                {row["id"]: row["reporter"] for row in candidates},
                                {row["id"]: row["editor"] for row in candidates},
                                articles or Articles(), tools, discovery, runner, now, retry_dir / "raw", deadline,
                                call_timeout=call_timeout)
    # Only the first writer pass decides whether a story reached a model; the rewrite pass records its own desk.
    cut = {sid for row in usage if "desk" not in row and row.get("event") in {"budget_exhausted", "writer_unavailable"}
           for sid in row["ids"]}
    sent = [sid for sid in ids if sid not in cut and "writer_sources" in output.get(sid, {})]
    by_id = {row["id"]: row for row in decisions}
    written = []
    for sid in ids:
        row, prose = by_id.get(sid), output.get(sid)
        if row and row.get("decision") == "publish" and row.get("summary") == "claims" and prose and prose["written"]:
            row.update(written_fields(prose))
            written.append(sid)
    result = {"candidates": ids, "cycles": {row["id"]: row["cycle"] for row in candidates}, "sent": sent,
              "budget_cut": [sid for sid in ids if sid in cut], "written": written,
              "events": [row for row in usage if row.get("event")]}
    if output:
        _write_json(retry_dir / "writer.json", output)
    _write_json(retry_dir / "status.json", result)
    return {"candidates": len(ids), "sent": len(sent), "budget_cut": len(result["budget_cut"]), "written": len(written)}


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
        retries = writer_retries(old, stories, cycles_dir, writer_now, current=job_dir)
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
                                        deadline, call_timeout_seconds)
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

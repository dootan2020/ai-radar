"""Scheduled, incremental local newsroom cycle."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .discovery import discover_raw
from .newsroom import DEFAULT_DESK_BUDGET_SECONDS, _write_json, run
from .registry import load_registry, providers
from .runner import CLIRunner


SNAPSHOT_URL = "https://radar-ai-vn.pages.dev/data/radar-intake.json"
USER_AGENT = "Mozilla/5.0 (compatible; AIRadarNewsroom/1.0)"
ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = ROOT / "phong-bao" / "decisions.json"
CYCLES_DIR = ROOT / "phong-bao" / "cycles"


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
            return json.load(response)

    try:
        return read(url)
    except HTTPError as error:
        if error.code != 404 or not url.endswith("/radar-intake.json"):
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


def cycle(*, snapshot_url=SNAPSHOT_URL, snapshot_fetcher=None, decisions_path=DECISIONS_PATH, cycles_dir=CYCLES_DIR,
          discovery=None, runner=None, articles=None, tools=None,
          desk_budget_seconds=DEFAULT_DESK_BUDGET_SECONDS, since_hours=36, now=None):
    """Review new story IDs and keep every earlier decision, including holds."""
    decisions_path, cycles_dir = Path(decisions_path), Path(cycles_dir)
    with cycle_lock(cycles_dir / "cycle.lock"):
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
        _write_json(job_dir / "status.json", {"started_at": started.isoformat(), "considered_count": len(recent), "new_count": len(new),
                                              "state": "running"})
        if not new:
            state = "no_new_stories"
            fresh = []
        else:
            tools = [tool for tool in (tools if tools is not None else load_registry())
                     if tool.get("cost_class") != "paid"]
            discovery = discovery if discovery is not None else discover_raw()
            if not _lanes_available(tools, discovery):
                state = "dry_lane"
                fresh = []
            else:
                state = "decided"
                with tempfile.TemporaryDirectory() as temp:
                    input_path = Path(temp) / "input.json"
                    corpus_path = Path(temp) / "corpus.json"
                    _write_json(input_path, {"generated_at": snapshot.get("generated_at"), "stories": new})
                    _write_json(corpus_path, snapshot)
                    run(input_path, job_dir / "job", tools, discovery, runner or CLIRunner(),
                        articles=articles, corpus_path=corpus_path,
                        desk_budget_seconds=desk_budget_seconds)
                    fresh = json.loads((job_dir / "job" / "quyet-dinh.json").read_text(encoding="utf-8"))["decisions"]
                if {row["id"] for row in fresh} != {row["id"] for row in new}:
                    raise ValueError("newsroom did not decide every new story")
        status = {"started_at": started.isoformat(), "state": state, "considered_count": len(recent), "new_count": len(new),
                  "decided_count": len(fresh), "total_decisions": len(old) + len(fresh)}
        if state != "dry_lane":
            value = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                     "input_generated_at": snapshot.get("generated_at"), "decisions": old + fresh}
            _write_json(job_dir / "quyet-dinh.json", {**value, "decisions": fresh})
            _write_json(decisions_path, value)
        _write_json(job_dir / "status.json", status)
        return status

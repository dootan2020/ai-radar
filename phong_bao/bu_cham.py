"""One-off retry of published stories left without a reader-visible desk summary."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import time

from radar.newsroom_decisions import desk_summary

from .cycle import (_json_file, _read_history, _retry_writer, _stored_cycles, cycle_lock,
                    STAMP_FORMAT, writer_retries)
from .discovery import discover_raw
from .newsroom import (Articles, DEFAULT_CALL_TIMEOUT_SECONDS, DEFAULT_SCORER_BUDGET_SECONDS,
                       WRITER_WINDOW_ENV, _write_json)
from .registry import load_registry
from .runner import CLIRunner


def _oldest_cycle(cycles_dir):
    cycles = _stored_cycles(cycles_dir, datetime.min.replace(tzinfo=timezone.utc))
    if not cycles:
        raise ValueError("no stored cycles")
    return datetime.strptime(cycles[0].name, STAMP_FORMAT).replace(tzinfo=timezone.utc)


def _stored_stories(cycles_dir, since, decisions):
    """Rebuild only the story fields the writer uses from its original cycle's desk evidence."""
    wanted = {row["id"]: row for row in decisions if row.get("decision") == "publish"
              and row.get("summary") in {"claims", "written"} and desk_summary(row) is None}
    stories, article_text = {}, {}
    for cycle in _stored_cycles(cycles_dir, since):
        job = cycle / "job"
        writer = _json_file(job / "writer.json")
        reporter = _json_file(job / "reporter.json")
        editor = _json_file(job / "editor.json")
        if not isinstance(writer, dict):
            continue
        stamped = datetime.strptime(cycle.name, STAMP_FORMAT).replace(tzinfo=timezone.utc)
        for sid in wanted.keys() & writer.keys():
            stories[sid] = {"id": sid, "published_at": stamped.isoformat()}
            report = reporter.get(sid) if isinstance(reporter, dict) else None
            edit = editor.get(sid) if isinstance(editor, dict) else None
            if not isinstance(report, dict) or not isinstance(edit, dict):
                continue
            url = report.get("selected_url")
            if not isinstance(url, str) or not url or not isinstance(report.get("source_text"), str) or not report["source_text"].strip():
                continue
            title = edit.get("subject") or report["source_text"].split("\n", 1)[0]
            stories[sid] = {"id": sid, "published_at": stamped.isoformat(), "url": url,
                            "title": title, "coverage": [{"url": url, "publisher": ""}]}
            article_text[url] = report["source_text"]
    return list(stories.values()), article_text, wanted


def _selection(decisions, cycles_dir, since, modes, limit, tools):
    stories, texts, wanted = _stored_stories(cycles_dir, since, decisions)
    reasons = {}
    candidates = writer_retries(decisions, stories, cycles_dir, datetime.now(timezone.utc), since=since,
                                limit=len(wanted), rescore_limit=len(wanted), tools=tools, reasons=reasons,
                                retry_unwritten=True)
    candidates = [row for row in candidates if row["mode"] != "rewrite"]
    usable = []
    for row in candidates:
        if row["mode"] == "write" and (not row["story"].get("url") or row["story"]["url"] not in texts):
            reasons[row["id"]] = "no stored source text"
        else:
            usable.append(row)
    candidates = usable
    selected = [row for row in candidates if ("score" if row["mode"] == "score" else "write") in modes]
    selected.sort(key=lambda row: (row["mode"] != "score", -row["published"].timestamp(), row["id"]))
    if limit is not None:
        selected = selected[:limit]
    counts = Counter("write" if row["mode"] == "rewrite" else row["mode"] for row in candidates)
    candidate_ids = {item["id"] for item in candidates}
    for row in wanted.values():
        if row["id"] not in reasons and row["id"] not in candidate_ids:
            reasons[row["id"]] = "already scored and failed" if row.get("score") else "no stored writer row or source paragraphs"
    for row in decisions:
        if row.get("decision") == "hold":
            reasons[row["id"]] = "held"
        elif row.get("decision") == "publish" and row.get("summary") == "none":
            reasons[row["id"]] = "summary none"
        elif row.get("decision") == "publish" and desk_summary(row) is not None:
            reasons[row["id"]] = "already shown"
        elif row.get("decision") == "publish" and row.get("summary") not in {"claims", "written"}:
            reasons[row["id"]] = "no supported summary"
    dates = [row["published"].date().isoformat() for row in candidates]
    return selected, texts, {"candidates": dict(counts), "selected": len(selected),
                             "excluded": dict(sorted(Counter(reasons.values()).items())),
                             "newest": max(dates) if dates else None, "oldest": min(dates) if dates else None}


def _save_history(path, original, decisions):
    _write_json(path, {**original, "generated_at": datetime.now(timezone.utc).isoformat(), "decisions": decisions})


def bu_cham(decisions_path, cycles_dir, *, since=None, modes=("score", "write"), limit=None, execute=False,
            tools=None, discovery=None, runner=None, now=None):
    decisions_path, cycles_dir = Path(decisions_path), Path(cycles_dir)
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    since = datetime.combine(date.fromisoformat(since), datetime.min.time(), tzinfo=timezone.utc) if since else _oldest_cycle(cycles_dir)
    decisions = _read_history(decisions_path)
    tools = [tool for tool in (tools if tools is not None else load_registry()) if tool.get("cost_class") != "paid"]
    if not execute:
        return _selection(decisions, cycles_dir, since, modes, limit, tools)[2]
    with cycle_lock(cycles_dir / "cycle.lock"):
        original = _json_file(decisions_path)
        decisions = _read_history(decisions_path)
        selected, texts, summary = _selection(decisions, cycles_dir, since, modes, limit, tools)
        if not selected:
            return {**summary, "results": []}
        discovery = discovery if discovery is not None else discover_raw()
        runner = runner or CLIRunner()
        articles = Articles()
        for url, text in texts.items():
            articles.remember(url, text)
        started = now or datetime.now(timezone.utc)
        results = []
        for offset, mode in enumerate(("score", "write")):
            batch = [row for row in selected if ("score" if row["mode"] == "score" else "write") == mode]
            if not batch:
                continue
            stamp = (started + timedelta(seconds=offset)).strftime(STAMP_FORMAT)
            job_dir = cycles_dir / stamp
            if job_dir.exists():
                raise ValueError("cycle timestamp already exists")
            job_dir.mkdir(parents=True)
            deadline = time.monotonic() + 3600
            previous = os.environ.get(WRITER_WINDOW_ENV)
            os.environ[WRITER_WINDOW_ENV] = str(max(48, (started - since).total_seconds() / 3600 + 24))
            try:
                result = _retry_writer(batch, decisions, job_dir, tools, discovery, runner, articles, started,
                                       deadline, DEFAULT_CALL_TIMEOUT_SECONDS,
                                       scorer_budget_seconds=DEFAULT_SCORER_BUDGET_SECONDS)
            finally:
                if previous is None:
                    os.environ.pop(WRITER_WINDOW_ENV, None)
                else:
                    os.environ[WRITER_WINDOW_ENV] = previous
            _write_json(job_dir / "status.json", {"state": "backfill", "started_at": started.isoformat(),
                                                   "writer_retry": result})
            _save_history(decisions_path, original, decisions)
            results.append({"mode": mode, **result})
        return {**summary, "results": results}

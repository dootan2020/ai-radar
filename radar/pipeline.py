"""Concurrent collection and atomic publication of the UI's JSON contract."""

import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from datetime import datetime, timezone

from radar import feeds, github, huggingface
from radar.common import iso_date, source_result
from radar.transport import Fetcher

BUILD_TIMEOUT = 100


def _jobs():
    jobs = []
    for source in feeds.SOURCES:
        jobs.append((source, "updates", lambda text, source=source: feeds.parse_feed(text, source)))
    for source in huggingface.SOURCES:
        jobs.append((source, "hf_releases", lambda text, source=source: huggingface.parse_releases(text, source["lab"])))
    jobs.append((github.SOURCE, "github", github.parse_trending))
    jobs.append((huggingface.TRENDING_SOURCE, "huggingface", huggingface.parse_trending))
    return jobs


def build(fetch=None, now=None, timeout=BUILD_TIMEOUT):
    """Return only fresh observations; failures are explicit source records.

    `fetch` is an injectable `(url) -> text` transport for offline verification.
    Previous JSON is never silently mixed into a newly timestamped snapshot.
    """
    from radar import youtube

    if timeout <= 0:
        raise ValueError("Build timeout must be positive")
    now = now or datetime.now(timezone.utc)
    deadline = time.monotonic() + timeout
    fetcher = Fetcher(deadline, fetch)
    payload = dict(generated_at=iso_date(now), sources=[], updates=[], hf_releases=[], live=[],
                   trending={"github": [], "huggingface": []})
    jobs = _jobs()
    pending, completed = queue.Queue(), queue.Queue()
    for job in jobs:
        pending.put(job)

    def worker():
        while time.monotonic() < deadline:
            try:
                source, section, parse = pending.get_nowait()
            except queue.Empty:
                return
            try:
                items = parse(fetcher(source["url"]))
                record = source_result(source, len(items))
            except Exception as error:
                items, record = [], source_result(source, error=f"{type(error).__name__}: {error}")
            completed.put((source["id"], section, items, [record]))

    def collect_youtube():
        try:
            items, records = youtube.collect(fetcher, now)
        except Exception as error:
            items = []
            records = [source_result(source, error=f"{type(error).__name__}: {error}") for source in youtube.SOURCES]
        completed.put(("youtube", "live", items, records))

    for _ in range(min(8, len(jobs))):
        threading.Thread(target=worker, daemon=True, name="radar-source").start()
    threading.Thread(target=collect_youtube, daemon=True, name="radar-youtube").start()
    received = set()
    while len(received) < len(jobs) + 1:
        try:
            source_id, section, items, records = completed.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            break
        received.add(source_id)
        payload["sources"].extend(records)
        target = payload["trending"] if section in {"github", "huggingface"} else payload
        target[section].extend(items)
    for source, _, _ in jobs:
        if source["id"] not in received:
            payload["sources"].append(source_result(source, error="Build deadline exceeded"))
    if "youtube" not in received:
        payload["sources"].extend(source_result(source, error="Build deadline exceeded") for source in youtube.SOURCES)

    # Source counts describe parsed entries; cross-feed URL dedupe happens here.
    updates = sorted(payload["updates"], key=lambda item: (item["published_at"] or "", item["source"]), reverse=True)
    seen = set()
    payload["updates"] = []
    for item in updates:
        if item["url"] not in seen:
            payload["updates"].append(item)
            seen.add(item["url"])
    payload["hf_releases"].sort(key=lambda item: item["created_at"] or "", reverse=True)
    payload["sources"].sort(key=lambda source: source["id"])
    return payload


def write_atomic(payload, path):
    """Replace the snapshot only after complete JSON is flushed to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=".radar-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

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
from radar.common import iso_date, source_result, stable_id
from radar.transport import Fetcher

BUILD_TIMEOUT = 100


def _jobs(v2=False, now=None):
    jobs = []
    for source in feeds.SOURCES:
        if v2:
            from radar.v2feeds import parse_feed
            source = dict(source, group="lab", publisher=source["lab"], first_wave=False)
            jobs.append((source, "coverage", lambda text, source=source: parse_feed(text, source, now)))
        else:
            jobs.append((source, "updates", lambda text, source=source: feeds.parse_feed(text, source)))
    for source in huggingface.SOURCES:
        if v2:
            from radar.discovery import parse_hf_trending
            source = dict(source, group="repository", publisher="huggingface", repo_type="model")
            jobs.append((source, "hf_observations", lambda text, source=source: parse_hf_trending(text, source, now)[:8]))
        else:
            jobs.append((source, "hf_releases", lambda text, source=source: huggingface.parse_releases(text, source["lab"])))
    jobs.append((github.SOURCE, "github", github.parse_trending))
    jobs.append((huggingface.TRENDING_SOURCE, "huggingface", huggingface.parse_trending))
    if v2:
        from radar import catalog, community, discovery, v2feeds
        parsers = dict(feed=v2feeds.parse_feed, hn=community.parse_hn, lobsters=community.parse_lobsters,
                       papers=discovery.parse_papers, hf_trending=discovery.parse_hf_trending, github=discovery.parse_github)
        for source in catalog.sources(now):
            parser = parsers[source["parser"]]
            jobs.append((source, "coverage", lambda text, source=source, parser=parser: parser(text, source, now)))
    return jobs


def build(fetch=None, now=None, timeout=BUILD_TIMEOUT):
    """Return only fresh observations; failures are explicit source records.

    `fetch` is an injectable `(url) -> text` transport for offline verification.
    Previous JSON is never silently mixed into a newly timestamped snapshot.
    """
    return _build(fetch, now, timeout)


def build_v2(fetch=None, now=None, timeout=BUILD_TIMEOUT, previous=None, events_path=None):
    """Collect the v2 contract; old content is never reused as fresh coverage."""
    return _build(fetch, now, timeout, v2=True, previous=previous, events_path=events_path)


def _build(fetch, now, timeout, v2=False, previous=None, events_path=None):
    from radar import youtube

    if timeout <= 0:
        raise ValueError("Build timeout must be positive")
    now = now or datetime.now(timezone.utc)
    deadline = time.monotonic() + timeout
    fetcher = Fetcher(deadline, fetch)
    payload = dict(generated_at=iso_date(now), sources=[], updates=[], hf_releases=[], live=[],
                   trending={"github": [], "huggingface": []})
    all_jobs = _jobs(v2, now)
    jobs = []
    for source, section, parse in all_jobs:
        if source.get("disabled") is True:
            reason = source.get("disabled_reason") or "Source disabled by catalog policy"
            record = source_result(source, error="Disabled: " + reason)
            record.update(disabled=True, disabled_reason=reason)
            payload["sources"].append(record)
        else:
            jobs.append((source, section, parse))
    coverage = []
    channels = youtube.CHANNELS
    youtube_sources = youtube.SOURCES
    if v2:
        from radar import catalog
        channels += (catalog.NVIDIA_CHANNEL,)
        youtube_sources = [dict(id=c[0], name=c[2] + " YouTube", lab=c[1], kind="youtube",
                                url="https://www.youtube.com/@" + c[3] + "/streams?hl=en", group="lab",
                                publisher=c[1], first_wave=c[0] == "nvidia-youtube") for c in channels]
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
                items = parse(fetcher(source["url"], source_id=source["id"]))
                record = source_result(source, len(items))
            except Exception as error:
                items, record = [], source_result(source, error=f"{type(error).__name__}: {error}")
            completed.put((source["id"], section, items, [record]))

    def collect_youtube():
        try:
            items, records = youtube.collect(fetcher, now, channels=channels) if v2 else youtube.collect(fetcher, now)
        except Exception as error:
            items = []
            records = [source_result(source, error=f"{type(error).__name__}: {error}") for source in youtube_sources]
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
        if section == "coverage":
            coverage.extend(items)
        elif section == "hf_observations":
            coverage.extend(items)
            payload["hf_releases"].extend(dict(id=item["title"], lab=item["lab"], url=item["url"], created_at=item["published_at"],
                                               likes=item["metrics"].get("likes"), downloads=item["metrics"].get("downloads"),
                                               pipeline_tag=item.get("pipeline_tag")) for item in items)
        else:
            target = payload["trending"] if section in {"github", "huggingface"} else payload
            target[section].extend(items)
    for source, _, _ in jobs:
        if source["id"] not in received:
            payload["sources"].append(source_result(source, error="Build deadline exceeded"))
    if "youtube" not in received:
        payload["sources"].extend(source_result(source, error="Build deadline exceeded") for source in youtube_sources)

    if v2:
        payload["updates"] = [dict(id=stable_id(item["url"]), lab=item["lab"], source=item["source"], title=item["title"],
                                   url=item["url"], published_at=item["published_at"], summary=item["summary"], kind=item["kind"])
                              for item in coverage if item["group"] not in {"forum", "paper", "repository"}]

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
    if v2:
        from radar import assembly, events
        known = {source["id"]: source for source, _, _ in all_jobs}
        known.update({source["id"]: source for source in youtube_sources})
        for record in payload["sources"]:
            source = known[record["id"]]
            evidence = fetcher.evidence(record["id"])
            statuses = [row["http_status"] for row in evidence if row["url"] == source.get("url")]
            record.update(url=source.get("url"), group=source.get("group", "repository" if source["kind"] in {"hf", "github"} else "lab"),
                          publisher=source.get("publisher") or ("huggingface" if source["kind"] == "hf" else source.get("lab") or "github"),
                          checked_at=iso_date(now), http_status=statuses[-1] if statuses else None,
                          http_requests=evidence, first_wave=source.get("first_wave", False))
        try:
            curated = events.load_events(events_path or Path(__file__).resolve().parent.parent / "data/events.json", now)
            record = source_result(events.SOURCE, len(curated))
        except Exception as error:
            curated, record = [], source_result(events.SOURCE, error=f"{type(error).__name__}: {error}")
        record.update(url=None, group="event", publisher="curated-events", checked_at=iso_date(now),
                      http_status=None, http_requests=[], first_wave=True)
        payload["sources"].append(record)
        payload["sources"].sort(key=lambda source: source["id"])
        return assembly.finish(payload, coverage, curated, now, previous, fetcher=fetcher)
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

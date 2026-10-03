"""Publication eligibility, independent of the ranking measurement baseline."""

import json
from datetime import date
from pathlib import Path

from radar.common import iso_date, web_url
from radar.items import instant

STALE_AFTER_SECONDS = 3 * 3600
EXPECTED_INTERVAL_SECONDS = 30 * 60
SECTIONS = ("today", "hot", "models", "papers", "listen", "voices", "community", "upcoming")


def inspect_times(row):
    for key in ("published_at", "start_at", "end_at"):
        if row.get(key) is not None and instant(row[key]) is None:
            raise ValueError(f"invalid {key} timestamp")


def inspect_projections(payload):
    for key in ("updates", "hf_releases", "live", "events", "repos"):
        rows = payload.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"invalid {key} records")
        for row in rows:
            inspect_times(row)
    for row in payload["live"] + payload["events"]:
        if not isinstance(row.get("title"), str) or not row["title"].strip() or not web_url(row.get("url")):
            raise ValueError("invalid live or event title/URL")
    for row in payload["live"]:
        if row.get("status") not in {"live", "upcoming", "ended"}:
            raise ValueError("invalid live status")
    for row in payload["events"]:
        if not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("invalid event identity")
        for key in ("start_date", "end_date"):
            value = row.get(key)
            if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError(f"invalid event {key}")
        if row["end_date"] < row["start_date"]:
            raise ValueError("event end precedes start")
        precision = row.get("time_precision")
        if precision not in {"date", "exact"} or precision == "exact" and instant(row.get("start_at")) is None:
            raise ValueError("invalid event time precision")
        if precision == "date" and (row.get("start_at") is not None or row.get("end_at") is not None):
            raise ValueError("date-only event contains exact timestamps")


def inspect_snapshot(payload):
    """Validate the renderable v2 contract and return active remote statuses.

    Age is deliberately checked by the caller: an old publication is useful
    diagnostic evidence even after it is too old for ranking measurements.
    """
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 2:
        raise ValueError("incompatible snapshot schema")
    if instant(payload.get("generated_at")) is None:
        raise ValueError("invalid snapshot timestamp")
    for key in ("sources", "stories", "updates", "hf_releases", "live", "events"):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"{key} must be an array")
    trending = payload.get("trending")
    if not isinstance(trending, dict) or any(not isinstance(trending.get(key), list) for key in ("github", "huggingface")):
        raise ValueError("invalid trending sections")
    inspect_projections(payload)
    identities, active = set(), {}
    for row in payload["sources"]:
        if not isinstance(row, dict):
            raise ValueError("invalid source record")
        id_ = row.get("id")
        if not isinstance(id_, str) or not id_ or id_ in identities:
            raise ValueError("missing or duplicate source identity")
        identities.add(id_)
        if type(row.get("ok")) is not bool or type(row.get("count")) is not int or row["count"] < 0:
            raise ValueError("invalid source status or count")
        if "disabled" in row and type(row["disabled"]) is not bool:
            raise ValueError("invalid disabled status")
        if row.get("disabled") is True or id_ == "curated-events":
            continue
        if not web_url(row.get("url")):
            raise ValueError("active remote source missing URL")
        active[id_] = row["ok"]
    story_ids = set()
    for story in payload["stories"]:
        if not isinstance(story, dict):
            raise ValueError("invalid story record")
        inspect_times(story)
        id_ = story.get("id")
        if not isinstance(id_, str) or not id_ or id_ in story_ids:
            raise ValueError("missing or duplicate story identity")
        story_ids.add(id_)
        if not isinstance(story.get("title"), str) or not story["title"].strip() or not web_url(story.get("url")):
            raise ValueError("invalid story title or URL")
        coverage = story.get("coverage")
        if not isinstance(coverage, list) or not coverage:
            raise ValueError("empty or invalid story coverage")
        if type(story.get("source_count")) is not int or story["source_count"] < 1:
            raise ValueError("invalid story source count")
        for item in coverage:
            if not isinstance(item, dict) or not isinstance(item.get("source"), str) or item["source"] not in identities:
                raise ValueError("invalid observation source")
            inspect_times(item)
            if (not isinstance(item.get("id"), str) or not item["id"]
                    or not isinstance(item.get("title"), str) or not item["title"].strip()
                    or not web_url(item.get("url")) or not isinstance(item.get("metrics"), dict)
                    or instant(item.get("observed_at")) is None):
                raise ValueError("invalid observation identity, content or timestamp")
            if instant(item["observed_at"]) > instant(payload["generated_at"]):
                raise ValueError("observation newer than snapshot")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or any(key not in sections for key in SECTIONS):
        raise ValueError("missing v2 sections")
    for ids in sections.values():
        if not isinstance(ids, list) or any(not isinstance(id_, str) or id_ not in story_ids for id_ in ids):
            raise ValueError("invalid section story reference")
    # Reject unsupported objects and NaN before any published file is replaced.
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("snapshot contains non-JSON values") from error
    return active


def rejection_reason(payload):
    active = inspect_snapshot(payload)
    if not active:
        return "no active remote sources", active
    # Two thirds is a publication retention policy. No single source has a veto.
    if sum(active.values()) * 3 < len(active) * 2:
        return "fewer than two thirds of active remote sources succeeded", active
    if not payload["stories"]:
        return "no stories to publish", active
    if not any(active.get(item["source"]) for story in payload["stories"] for item in story["coverage"]):
        return "no observations from successful active remote sources", active
    return None, active


def load_published(path, now):
    """Load prior publication evidence without expiring or retimestamping it."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        reason, _ = rejection_reason(payload)
        if reason or instant(payload["generated_at"]) > instant(now):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def assess_publication(payload, previous, now):
    """Return machine-readable diagnostics for either acceptance or rejection."""
    current = instant(payload.get("generated_at")) if isinstance(payload, dict) else None
    prior = instant(previous.get("generated_at")) if isinstance(previous, dict) else None
    now = instant(now)
    active = {}
    try:
        reason, active = rejection_reason(payload)
        if reason is None and not 0 <= (now - current).total_seconds() <= STALE_AFTER_SECONDS:
            reason = "candidate snapshot is future-dated or older than three hours"
        if reason is None and prior and current <= prior:
            reason = "candidate snapshot is not newer than previous publication"
    except (ValueError, TypeError) as error:
        reason = str(error)
    gap = (current - prior).total_seconds() if current and prior else None
    age = (now - prior).total_seconds() if prior else None
    freshness = dict(generated_at=iso_date(current), expected_interval_seconds=EXPECTED_INTERVAL_SECONDS,
                     stale_after_seconds=STALE_AFTER_SECONDS, previous_generated_at=iso_date(prior),
                     previous_age_seconds=age, previous_stale=age is not None and age > STALE_AFTER_SECONDS,
                     gap_seconds=gap, scheduler_gap=gap is not None and gap > STALE_AFTER_SECONDS)
    return dict(published=reason is None, reason=reason, attempted_at=iso_date(now),
                active_remote_sources=len(active), successful_remote_sources=sum(active.values()),
                failed_remote_sources=[id_ for id_, ok in active.items() if not ok],
                required_successful_sources=(2 * len(active) + 2) // 3,
                freshness=freshness)

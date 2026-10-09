"""Deterministic daily reading cuts from observed evidence, without generated prose."""

from copy import deepcopy
from datetime import timedelta, timezone
import re

from radar.clustering import canonical_url
from radar.common import iso_date
from radar.items import instant, measured, publisher_identity

TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
# Modern Vietnamese dates use UTC+07 year-round; Windows need not install tzdata.
VIETNAM = timezone(timedelta(hours=7), TIMEZONE_NAME)
MORNING_HOUR = 6
MAX_STORIES = 5
POLICY_METHOD = "daily-evidence-v2"
FORUM_PERCENTILE_MIN = .97
FORUM_COMMENTS_MIN = 100
MAX_FORUM_STORIES = 1
ACTION = re.compile(r"\b(?:introducing|introduces|launch(?:es|ed|ing)?|releas(?:e|es|ed|ing)|available|open[- ]sourc(?:e|es|ed|ing))\b", re.I)
PRODUCT = re.compile(r"\b(?:models?|products?|agents?|assistants?|APIs?|tools?|platforms?)\b", re.I)
STORY_FIELDS = ("id", "title", "title_vi", "headline", "headline_vi", "url", "published_at", "kind", "time_basis")
COVERAGE_FIELDS = STORY_FIELDS + ("source", "publisher", "entity", "group", "observed_at", "discussion_url", "metrics")


def edition_window(now):
    """Return today's fixed morning cut; never backfill a previous date."""
    now = instant(now)
    if now is None:
        raise ValueError("edition time must have a timezone")
    local = now.astimezone(VIETNAM)
    cutoff = local.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    return now, cutoff - timedelta(days=1), cutoff


def _project(row, fields):
    return {key: deepcopy(row[key]) for key in fields if key in row}


def nonforum_publishers(coverage):
    return sorted({publisher_identity(row) for row in coverage
                   if row.get("group") != "forum" and publisher_identity(row)})


def forum_attention_exception(percentile, measured_rows):
    """Comments must belong to the forum observation carrying the measurement."""
    return (percentile is not None and FORUM_PERCENTILE_MIN <= percentile <= 1
            and any(row.get("group") == "forum"
                    and (measured(row.get("metrics", {}).get("comments")) or 0) >= FORUM_COMMENTS_MIN
                    for row in measured_rows))


def _candidate(story, sources, start, cutoff):
    published = instant(story.get("published_at"))
    if (story.get("time_basis") != "published" or published is None
            or not start <= published < cutoff or story.get("kind") == "event" or story.get("status") == "upcoming"):
        return None
    coverage = []
    for row in story.get("coverage", []):
        timestamp = instant(row.get("published_at"))
        if (sources.get(row.get("source")) and row.get("time_basis") == "published"
                and timestamp and start <= timestamp < cutoff and row.get("kind") != "event"
                and row.get("status") != "upcoming"):
            coverage.append(row)
    if not coverage:
        return None
    coverage.sort(key=lambda row: (row.get("source", ""), row.get("id", "")))
    publishers = nonforum_publishers(coverage)
    corroborated = any(row.get("group") != "forum" for row in coverage)
    launches = [row for row in coverage if row.get("group") == "lab" and ACTION.search(row["title"])
                and (row.get("kind") in {"model", "product"} or PRODUCT.search(row["title"]))]
    hot = story.get("hot_signals") or {}
    if not isinstance(hot, dict):
        raise ValueError("edition hot_signals must be an object")
    percentile = measured(hot.get("engagement_percentile"))
    measurement = hot.get("measurement") or {}
    if not isinstance(measurement, dict):
        raise ValueError("edition measurement must be an object")
    value = measured(measurement.get("value"))
    measured_rows = [row for row in coverage if row.get("source") == measurement.get("source")
                     and measured(row.get("metrics", {}).get(measurement.get("metric"))) == value]
    engaged = percentile is not None and .8 <= percentile <= 1 and value is not None and value > 0 and measured_rows
    engaged = engaged and (corroborated or forum_attention_exception(percentile, measured_rows))
    reasons = []
    if launches:
        reasons.append(dict(code="primary_release", text="Tiêu đề nguồn gốc có dấu hiệu công bố model hoặc sản phẩm",
                            observation_ids=[row["id"] for row in launches]))
    if len(publishers) >= 2:
        reasons.append(dict(code="publisher_coverage", text=f"{len(publishers)} định danh nhà xuất bản cùng đưa tin",
                            publishers=publishers))
    if engaged:
        attention_text = ("Tương tác thuộc nhóm 20% cao nhất trong nguồn đo, có nguồn ngoài diễn đàn"
                          if corroborated else "Ngoại lệ diễn đàn: tương tác thuộc nhóm 3% cao nhất và ít nhất 100 bình luận")
        reasons.append(dict(code="measured_attention", text=attention_text,
                            percentile=percentile, measurement=deepcopy(measurement)))
    if not reasons:
        return None
    score = measured(story.get("hot_score"))
    result = _project(story, STORY_FIELDS)
    result.update(source_count=len(publishers), coverage=[_project(row, COVERAGE_FIELDS) for row in coverage],
                  selection=dict(reasons=reasons, signals=dict(publishers=publishers,
                      age_hours_at_cutoff=round((cutoff - published).total_seconds() / 3600, 4),
                      hot_score=score, engagement_percentile=percentile)))
    attention_only = not launches and len(publishers) < 2
    order = (attention_only, -bool(launches), -len(publishers), -(score or 0), -published.timestamp(), story["id"])
    return order, result


def build_edition(payload, now):
    """Build a pure snapshot projection; archive publication checks live separately.

    Attention and release-title rules are editorial heuristics, not independent
    fact checking or proof of importance. Snapshot scores retain their own time.
    """
    now, start, cutoff = edition_window(now)
    if now < cutoff:
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("editions require a v2 snapshot")
    generated = instant(payload.get("generated_at"))
    if generated is None or generated > now:
        raise ValueError("edition snapshot timestamp is invalid or future-dated")
    if generated < cutoff:
        return None
    sources = {row["id"]: row.get("ok") is True and not row.get("disabled")
               for row in payload["sources"]}
    candidates = [_candidate(story, sources, start, cutoff) for story in payload["stories"]]
    candidates = sorted(row for row in candidates if row is not None)
    selected, seen, forum_count = [], set(), 0
    for _, story in candidates:
        forum_only = all(row.get("group") == "forum" for row in story["coverage"])
        if forum_only and forum_count >= MAX_FORUM_STORIES:
            continue
        urls = {canonical_url(row["url"]) for row in story["coverage"]} | {canonical_url(story["url"])}
        urls.discard(None)
        if urls & seen:
            continue
        selected.append(story)
        forum_count += forum_only
        seen.update(urls)
        if len(selected) == MAX_STORIES:
            break
    active = sorted(row["id"] for row in payload["sources"]
                    if not row.get("disabled") and row["id"] != "curated-events")
    return dict(schema_version=1, date=cutoff.date().isoformat(), timezone=TIMEZONE_NAME,
                window_start_at=iso_date(start), cutoff_at=iso_date(cutoff), created_at=iso_date(now),
                snapshot_generated_at=payload["generated_at"],
                policy=dict(method=POLICY_METHOD, max_stories=MAX_STORIES, window_hours=24,
                            cutoff_hour=MORNING_HOUR, engagement_percentile_min=.8,
                            publisher_coverage_excludes_forums=True, attention_requires_nonforum=True,
                            forum_exception_percentile_min=FORUM_PERCENTILE_MIN,
                            forum_exception_comments_min=FORUM_COMMENTS_MIN,
                            max_forum_only_stories=MAX_FORUM_STORIES,
                            score_measured_at=payload["generated_at"],
                            description="Lọc theo dấu hiệu công bố, số nhà xuất bản và tương tác đo được; không khẳng định tầm quan trọng khách quan"),
                stories=selected, source_health=dict(active_remote_sources=len(active),
                    successful_remote_sources=sum(sources[id_] for id_ in active),
                    failed_remote_sources=[id_ for id_ in active if not sources[id_]]))

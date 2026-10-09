"""7-day story retention across build snapshots."""

from copy import deepcopy
from datetime import datetime, timezone
from radar.clustering import canonical_url
from radar.items import instant

RETENTION_SECONDS = 7 * 86400  # 7 days = 604,800 seconds (168 hours)
DEFAULT_POOL_CAP = 2000


def _story_age_seconds(story, now_dt, fallback_dt=None):
    """Return story age in seconds from published_at, or fallback to coverage/snapshot timestamp."""
    pub = instant(story.get("published_at"))
    if pub is None:
        cov_times = []
        for item in story.get("coverage", []) if isinstance(story.get("coverage"), list) else []:
            if isinstance(item, dict):
                t = instant(item.get("published_at") or item.get("observed_at"))
                if t is not None:
                    cov_times.append(t)
        if cov_times:
            pub = min(cov_times)
        elif fallback_dt is not None:
            pub = fallback_dt

    if pub is None:
        return None
    return (now_dt - pub).total_seconds()


def _normalize_url(url):
    if not isinstance(url, str) or not url.strip():
        return None
    canonical = canonical_url(url)
    return canonical if canonical else url.strip().rstrip("/")


def _preserve_published_coverage(fresh_story, old_story):
    """Keep each still-retained published observation when fresh data overlaps it."""
    coverage = fresh_story.get("coverage")
    old_coverage = old_story.get("coverage")
    if not isinstance(coverage, list) or not isinstance(old_coverage, list):
        return
    fresh_ids = {item.get("id") for item in coverage if isinstance(item, dict) and item.get("id")}
    for item in old_coverage:
        if isinstance(item, dict) and item.get("id") and item["id"] not in fresh_ids:
            coverage.append(deepcopy(item))
            fresh_ids.add(item["id"])
    publishers = {item.get("publisher") or item.get("source") for item in coverage
                  if isinstance(item, dict) and (item.get("publisher") or item.get("source"))}
    fresh_story["source_count"] = len(publishers)

    # Fail at the retention boundary if a future change drops a non-expired member.
    old_ids = {item.get("id") for item in old_coverage if isinstance(item, dict) and item.get("id")}
    if not old_ids.issubset(fresh_ids):
        raise RuntimeError("Published story coverage was lost while reconciling fresh coverage")


def retain_stories(fresh_stories, published, now, max_stories=DEFAULT_POOL_CAP):
    """Carry forward stories from published snapshot up to 7 days old.

    - Fresh stories from current feed take absolute precedence.
    - Missing or malformed published snapshot degrades gracefully (returns fresh stories only).
    - Stories older than 7 days from published_at are pruned.
    - Duplicate stories (matching ID, story URL, or coverage URLs) are deduplicated,
      while preserving Vietnamese translations if the fresh story lacks them.
    - Carried stories retain their original coverage and published_at, with carried=True.
    - Combined pool is bounded by max_stories, evicting oldest/lowest-priority carried stories first.
    """
    if not isinstance(fresh_stories, list):
        fresh_stories = []

    now_dt = instant(now) if now else datetime.now(timezone.utc)
    if not now_dt:
        now_dt = datetime.now(timezone.utc)

    # Validate published snapshot
    if not isinstance(published, dict) or published.get("schema_version") != 2:
        return list(fresh_stories)

    published_stories = published.get("stories")
    if not isinstance(published_stories, list) or not published_stories:
        return list(fresh_stories)

    published_generated_at = instant(published.get("generated_at"))

    # Index fresh stories for deduplication
    fresh_by_id = {}
    fresh_by_url = {}
    fresh_by_cov_url = {}
    seen_ids = set()
    seen_urls = set()
    seen_coverage_urls = set()

    for story in fresh_stories:
        if not isinstance(story, dict):
            continue
        sid = story.get("id")
        if sid:
            seen_ids.add(sid)
            fresh_by_id[sid] = story
        s_url = _normalize_url(story.get("url"))
        if s_url:
            seen_urls.add(s_url)
            fresh_by_url[s_url] = story
        for item in story.get("coverage", []) if isinstance(story.get("coverage"), list) else []:
            if isinstance(item, dict) and item.get("url"):
                c_url = _normalize_url(item["url"])
                if c_url:
                    seen_coverage_urls.add(c_url)
                    fresh_by_cov_url[c_url] = story

    carried_stories = []

    for old_story in published_stories:
        if not isinstance(old_story, dict):
            continue
        old_id = old_story.get("id")
        if not old_id or not isinstance(old_id, str):
            continue

        old_url = _normalize_url(old_story.get("url"))
        age_seconds = _story_age_seconds(old_story, now_dt, published_generated_at)
        eligible_coverage = (age_seconds is not None and age_seconds <= RETENTION_SECONDS
                             and not (age_seconds < -86400 and old_story.get("kind") != "event"
                                      and old_story.get("time_basis") != "scheduled"))
        old_cov_urls = set()
        for item in old_story.get("coverage", []) if isinstance(old_story.get("coverage"), list) else []:
            if isinstance(item, dict) and item.get("url"):
                c_url = _normalize_url(item["url"])
                if c_url:
                    old_cov_urls.add(c_url)

        # Check for duplication with fresh stories
        is_duplicate = False
        matching_fresh_story = None

        if old_id in fresh_by_id:
            is_duplicate = True
            matching_fresh_story = fresh_by_id[old_id]
        elif old_url and old_url in fresh_by_url:
            is_duplicate = True
            matching_fresh_story = fresh_by_url[old_url]
        elif old_cov_urls and (old_cov_urls & seen_coverage_urls):
            is_duplicate = True
            for c_url in old_cov_urls:
                if c_url in fresh_by_cov_url:
                    matching_fresh_story = fresh_by_cov_url[c_url]
                    break
        elif any(old_id in (s.get("aliases") or []) for s in fresh_stories if isinstance(s, dict)):
            is_duplicate = True
            matching_fresh_story = next((s for s in fresh_stories if isinstance(s, dict) and old_id in (s.get("aliases") or [])), None)

        if is_duplicate:
            # Preserve existing Vietnamese translations onto fresh story if missing
            if matching_fresh_story is not None:
                if eligible_coverage:
                    matching_fresh_stories = [story for story in fresh_stories
                                              if story is matching_fresh_story or
                                              (old_cov_urls & {
                                                  _normalize_url(item.get("url"))
                                                  for item in story.get("coverage", [])
                                                  if isinstance(item, dict)
                                              })]
                    for duplicate_story in matching_fresh_stories:
                        if duplicate_story is matching_fresh_story:
                            continue
                        _preserve_published_coverage(matching_fresh_story, duplicate_story)
                        matching_fresh_story["aliases"] = sorted(
                            (set(matching_fresh_story.get("aliases") or [])
                             | set(duplicate_story.get("aliases") or [])
                             | {duplicate_story["id"]}) - {matching_fresh_story.get("id")})
                        fresh_stories.remove(duplicate_story)
                    _preserve_published_coverage(matching_fresh_story, old_story)
                if "title_vi" in old_story and "title_vi" not in matching_fresh_story:
                    matching_fresh_story["title_vi"] = old_story["title_vi"]
                if "summary_vi" in old_story and "summary_vi" not in matching_fresh_story:
                    matching_fresh_story["summary_vi"] = old_story["summary_vi"]

                # Preserve aliases from old_story and record old_id as alias
                combined_aliases = set(matching_fresh_story.get("aliases") or [])
                combined_aliases.update(old_story.get("aliases") or [])
                if old_id != matching_fresh_story.get("id"):
                    combined_aliases.add(old_id)
                combined_aliases.discard(matching_fresh_story.get("id"))
                matching_fresh_story["aliases"] = sorted(combined_aliases)
            continue

        # 7-day retention cutoff check
        if age_seconds is None:
            continue
        if age_seconds > RETENTION_SECONDS:
            # Expired: older than 7 days (604,800s)
            continue
        # Allow up to 1 day clock skew or scheduled events; reject absurd future dates
        if age_seconds < -86400 and old_story.get("kind") != "event" and old_story.get("time_basis") != "scheduled":
            continue

        # Valid carried story: deepcopy to prevent mutation of published snapshot
        carried = deepcopy(old_story)
        carried["carried"] = True

        seen_ids.add(old_id)
        if old_url:
            seen_urls.add(old_url)
        seen_coverage_urls.update(old_cov_urls)
        carried_stories.append(carried)

    # Pool cap enforcement
    capacity = max(0, max_stories - len(fresh_stories))
    if len(carried_stories) > capacity:
        def priority_key(story):
            is_multi = 1 if story.get("source_count", 1) >= 2 else 0
            has_section = 1 if story.get("primary_section") in {"models", "papers", "listen", "voices", "upcoming"} else 0
            has_translation = 1 if story.get("title_vi") else 0
            pub = story.get("published_at") or ""
            return (is_multi, has_section, has_translation, pub, story.get("id", ""))

        carried_stories.sort(key=priority_key, reverse=True)
        carried_stories = carried_stories[:capacity]

    combined = list(fresh_stories) + carried_stories
    combined.sort(key=lambda s: (s.get("published_at") or "", s.get("id") or ""), reverse=True)
    return combined

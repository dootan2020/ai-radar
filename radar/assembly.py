"""V1 projections and unified v2 observations share one collection pass."""

from radar import catalog, feeds, github, huggingface
from radar.common import iso_date, stable_id
from radar.items import instant, observation, relevant
from radar.youtube import CHANNELS


def legacy_items(payload, now):
    """Adapt frozen v1 snapshots too, so calibration uses production normalization."""
    sources = {source["id"]: source for source in feeds.SOURCES + huggingface.SOURCES +
               [github.SOURCE, huggingface.TRENDING_SOURCE] + catalog.sources(now)}
    result = []
    for row in payload.get("updates", []):
        source = sources.get(row["source"], dict(id=row["source"], lab=row.get("lab", "")))
        result.append(observation(source, row["title"], row["url"], row.get("published_at"), now,
                                  kind=row.get("kind", "other"), summary=row.get("summary", "")))
    for row in payload.get("hf_releases", []):
        source = dict(id=row["lab"] + "-hf", lab=row["lab"], publisher="huggingface", group="repository")
        result.append(observation(source, row["id"], row["url"], row.get("created_at"), now,
                                  kind="model", time_basis="repository_created",
                                  metrics={"likes": row.get("likes"), "downloads": row.get("downloads")}))
    for row in payload.get("live", []):
        channel = next((c for c in CHANNELS + (catalog.NVIDIA_CHANNEL,) if c[2] == row.get("channel")), None)
        source = dict(id=channel[0] if channel else row.get("lab", "") + "-youtube",
                      publisher=row.get("lab") or row.get("channel", "youtube"), lab=row.get("lab", ""), group="lab")
        media = [dict(url=row["url"], type="video", mime_type=None)]
        if row.get("thumbnail"):
            media.append(dict(url=row["thumbnail"], type="image", mime_type=None))
        extra = {key: row[key] for key in ("status", "start_at", "end_at", "time_text", "time_precision", "status_source") if key in row}
        result.append(observation(source, row["title"], row["url"], row.get("start_at"), now, kind="video", media=media,
                                  time_basis="scheduled" if row.get("status") == "upcoming" else "published", **extra))
    for row in payload.get("trending", {}).get("github", []):
        if relevant(row["repo"], row.get("description", "")):
            result.append(observation(dict(id="github-trending", group="repository", publisher="github"), row["repo"], row["url"],
                                      None, now, kind="repository", summary=row.get("description", ""),
                                      metrics={"stars": row.get("stars"), "stars_today": row.get("stars_today")}))
    for row in payload.get("trending", {}).get("huggingface", []):
        result.append(observation(dict(id="hf-trending", group="repository", publisher="huggingface"), row["id"], row["url"], None, now,
                                  kind="model" if row.get("type") == "model" else "repository",
                                  metrics={"likes": row.get("likes"), "downloads": row.get("downloads")}))
    return [item for item in result if item]


def event_items(events, now):
    from radar.events import SOURCE

    result = []
    for row in events:
        item = observation(SOURCE, row["title"], row["url"], row.get("start_at"), now, kind="event", time_basis="scheduled",
                           event_id=row["id"], start_date=row["start_date"], end_date=row["end_date"],
                           start_at=row.get("start_at"), end_at=row.get("end_at"), time_precision=row["time_precision"],
                           location=row.get("location"), verified_at=row["verified_at"], source_url=row["source_url"])
        if item:
            item["id"] = stable_id(SOURCE["id"] + "|" + row["id"])
            result.append(item)
    return result


def sections(stories, now):
    from radar.ranking import hot_eligible

    result = {key: [] for key in ("today", "hot", "models", "papers", "listen", "voices", "community", "upcoming")}
    for story in stories:
        id_, coverage = story["id"], story["coverage"]
        timestamp = instant(story.get("published_at"))
        if timestamp and 0 <= (now - timestamp).total_seconds() <= 86400:
            result["today"].append(id_)
        if hot_eligible(story):
            result["hot"].append(id_)
        for section, kinds in (("models", {"model"}), ("papers", {"paper"}), ("listen", {"podcast", "video"})):
            if any(item["kind"] in kinds for item in coverage):
                result[section].append(id_)
        if any(item["group"] in {"research", "newsletter"} for item in coverage):
            result["voices"].append(id_)
        if any(item["group"] == "forum" for item in coverage):
            result["community"].append(id_)
        if any(item["kind"] == "event" or item.get("status") == "upcoming" for item in coverage):
            result["upcoming"].append(id_)
    by_id = {story["id"]: story for story in stories}
    result["hot"].sort(key=lambda id_: (-by_id[id_]["hot_score"], id_))
    result["upcoming"].sort(key=lambda id_: (
        min((item.get("start_date") or item.get("start_at") or "9999")
            for item in by_id[id_]["coverage"] if item["kind"] == "event" or item.get("status") == "upcoming"), id_))
    return result


def finish(payload, coverage, events, now, previous, published=None, fetcher=None, image_transport=None,
           resolve_images=None, ai_transport=None):
    from radar.clustering import cluster_items
    from radar.curation import curate_repos
    from radar.ranking import rank_stories
    from radar.retention import retain_stories

    # The full RSS observations, before v1 URL dedupe, retain media and coverage.
    legacy_payload = dict(payload, updates=[], hf_releases=[])
    items = coverage + legacy_items(legacy_payload, now) + event_items(events, now)
    fresh_stories = cluster_items(items, now)
    stories = rank_stories(retain_stories(fresh_stories, published, now), now, previous)
    # Worth and images run after retention so carried stories are re-scored at `now` and can be illustrated.
    sources_map = {s["id"]: s for s in payload.get("sources", [])}
    from radar.worth import annotate_story_worth
    for story in stories:
        annotate_story_worth(story, now, sources_map)
    if resolve_images is None:
        # Only a live fetcher or an explicit image transport may reach the network; a bare call stays offline.
        from radar.transport import read_url
        resolve_images = (image_transport is not None
                          or (fetcher is not None and getattr(fetcher, "transport", None) == read_url))
    if resolve_images:
        import time
        from radar.images import resolve_images_for_stories
        build_deadline = getattr(fetcher, "deadline", None)
        t_img = time.monotonic()
        resolve_images_for_stories(stories, transport=image_transport, deadline=build_deadline, ai_transport=ai_transport)
        img_elapsed = time.monotonic() - t_img
        img_count = sum(1 for st in stories if st.get("image"))
        print(f"Images: {img_count}/{len(stories)} stories resolved with image in {img_elapsed:.2f}s")
    baseline = instant(previous.get("generated_at")) if isinstance(previous, dict) else None
    if (not baseline or previous.get("schema_version") != 2 or not isinstance(previous.get("stories"), list)
            or not 0 < (now - baseline).total_seconds() <= 48 * 3600):
        baseline = None
    repos_meta = {}
    curation_fetcher = fetcher
    if fetcher is not None and hasattr(fetcher, "transport"):
        import time
        from radar.transport import Fetcher
        curation_fetcher = Fetcher(time.monotonic() + 60, transport=fetcher.transport)
    repos = curate_repos(payload.get("trending", {}).get("github", []),
                         payload.get("trending", {}).get("huggingface", []),
                         fetcher=curation_fetcher, now=now, meta=repos_meta)
    payload.update(schema_version=2, stories=stories, sections=sections(stories, now), events=events,
                   repos=repos, repos_meta=repos_meta,
                   ranking=dict(method="source-percentile-freshness-v1", window_hours=72,
                                description="bách phân vị số đo trong từng nguồn, nhân với độ mới của tin",
                                baseline_at=iso_date(baseline), calibration="tạm thời, đang đánh giá bằng báo cáo gom cụm"))
    return payload

"""A complete reader projection alongside the full collection/evidence snapshot."""

from copy import deepcopy
from pathlib import Path

from radar.pipeline import write_atomic


PAGE_FIELDS = (
    "schema_version", "generated_at", "freshness", "stories", "sections", "sources",
    "repos", "repos_meta", "events", "live", "ranking", "translation", "views",
)


def page_payload(payload):
    """Keep every story and reader field; omit collection-only duplicated evidence.

    Full originals, including coverage summaries, remain in radar.json. This
    projection is not an input to collection, ranking, editions or translation.
    """
    result = deepcopy({key: payload[key] for key in PAGE_FIELDS if key in payload})
    for story in result.get("stories", []):
        for key in ("primary_section", "groups"):
            story.pop(key, None)
        signals = story.get("hot_signals")
        if isinstance(signals, dict):
            story["hot_signals"] = {key: signals[key] for key in ("measurement",) if key in signals}
        for item in story.get("coverage", []):
            for key in ("canonical_url", "observed_at", "group", "kind", "summary", "summary_vi", "time_basis"):
                item.pop(key, None)
    for source in result.get("sources", []):
        for key in ("http_requests", "http_status", "checked_at", "first_wave", "kind", "group"):
            source.pop(key, None)
    return result


def page_path(path):
    """Companion follows custom output paths too, never the default site directory."""
    path = Path(path)
    return path.with_name(f"{path.stem}-ui{path.suffix}")


def write_site_snapshot(payload, path):
    """Write full evidence, then its page projection without leaving a stale copy.

    Each file is atomic. If projection generation/publication fails after the
    full snapshot was replaced, remove the old companion so the page's fallback
    reads the new complete snapshot instead of old translations or timestamps.
    """
    write_atomic(payload, path)
    companion = page_path(path)
    try:
        write_atomic(page_payload(payload), companion, compact=True)
    except Exception:
        companion.unlink(missing_ok=True)
        raise

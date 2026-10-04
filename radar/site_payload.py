"""A complete reader projection alongside the full collection/evidence snapshot."""

from copy import deepcopy
from pathlib import Path
import re

from radar.pipeline import write_atomic
from radar.search_index import search_payload, search_path


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


def head_path(path):
    """Companion first-screen projection path, e.g. radar-head.json."""
    path = Path(path)
    return path.with_name(f"{path.stem}-head{path.suffix}")


def yt_id_from_url(url):
    match = re.search(r'(?:v=|youtu\.be/|/embed/|/live/)([\w-]{11})', url or '')
    return match.group(1) if match else None


def yt_id_of_story(story):
    if not story:
        return None
    for c in story.get("coverage", []):
        for m in c.get("media", []):
            if m.get("type") == "video" and m.get("url"):
                vid = yt_id_from_url(m["url"])
                if vid:
                    return vid
        if c.get("url"):
            vid = yt_id_from_url(c["url"])
            if vid:
                return vid
    return yt_id_from_url(story.get("url"))


def first_screen_thumbnail(payload):
    """Detect the YouTube thumbnail URL on the first screen (LCP candidate) if any."""
    live_now = []
    for s in payload.get("stories", []):
        if any(c.get("status") == "live" for c in s.get("coverage", [])):
            live_now.append(s)
    for v in payload.get("live", []):
        if v.get("status") == "live" and not live_now:
            live_now.append(v)
    if live_now:
        return None

    ended = []
    for s in payload.get("stories", []):
        for c in s.get("coverage", []):
            if c.get("status") == "ended":
                ended.append((s, c))
    if ended:
        ended.sort(key=lambda pair: pair[1].get("end_at") or "", reverse=True)
        s, c = ended[0]
        vid = yt_id_of_story(s) or (yt_id_from_url(c.get("url")) if c else None)
        if vid:
            return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

    ended_live = [v for v in payload.get("live", []) if v.get("status") == "ended"]
    if ended_live:
        ended_live.sort(key=lambda v: v.get("end_at") or "", reverse=True)
        vid = ended_live[0].get("video_id")
        if vid:
            return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    return None


def update_index_thumbnail(index_path, thumb_url):
    """Update or remove the LCP thumbnail preload in site/index.html."""
    index_path = Path(index_path)
    if not index_path.is_file():
        return
    text = index_path.read_text(encoding="utf-8")
    pattern = re.compile(r'<link rel="preload" as="image" href="[^"]*" fetchpriority="high">\n?')
    if thumb_url:
        new_tag = f'<link rel="preload" as="image" href="{thumb_url}" fetchpriority="high">\n'
        if pattern.search(text):
            new_text = pattern.sub(new_tag, text)
        else:
            target = '<link rel="stylesheet" href="tokens.css">'
            if target in text:
                new_text = text.replace(target, new_tag + target)
            else:
                new_text = text
    else:
        new_text = pattern.sub('', text)
    if new_text != text:
        index_path.write_text(new_text, encoding="utf-8", newline="\n")


def head_payload(payload):
    """Keep only first-screen board subset (~10KB gzipped) for fast initial paint.

    The first screen on mobile shows the lead tile and live tile; the remaining
    board tiles show the top entries of each key section. The full projection
    (radar-ui.json) loads immediately after first paint to populate chapters
    below the fold.
    """
    stories = payload.get("stories", [])
    multi = [s for s in stories if s.get("source_count", 0) >= 2]
    board_story_ids = set()
    if multi:
        multi_sorted = sorted(
            multi,
            key=lambda s: (s.get("source_count", 0), s.get("hot_score", 0) or 0),
            reverse=True,
        )
        board_story_ids.add(multi_sorted[0]["id"])
        for s in multi_sorted[1:3]:
            board_story_ids.add(s["id"])
    for sec in ("hot", "today", "listen", "models", "upcoming"):
        for sid in payload.get("sections", {}).get(sec, [])[:3]:
            board_story_ids.add(sid)
    for s in stories:
        for c in s.get("coverage", []):
            if c.get("status") in ("live", "ended"):
                board_story_ids.add(s["id"])
    if not board_story_ids and stories:
        board_story_ids.add(stories[0]["id"])

    base = page_payload(payload)
    board_stories = [s for s in base.get("stories", []) if s["id"] in board_story_ids]

    head = {
        "schema_version": base.get("schema_version", 2),
        "generated_at": base.get("generated_at"),
        "freshness": base.get("freshness"),
        "views": base.get("views"),
        "translation": base.get("translation"),
        "sections": {
            k: [sid for sid in v if sid in board_story_ids][:5]
            for k, v in base.get("sections", {}).items()
        },
        "sources": base.get("sources", []),
        "stories": board_stories,
        "live": base.get("live", []),
        "repos": base.get("repos", [])[:3] if base.get("repos") else [],
        "repos_meta": base.get("repos_meta", {}),
        "events": base.get("events", [])[:5] if base.get("events") else [],
    }
    return head


def write_site_snapshot(payload, path):
    """Write full evidence, then page and first-screen projections without leaving a stale copy.

    Each file is atomic. If projection generation/publication fails after the
    full snapshot was replaced, remove old companions so the page's fallback
    reads the new complete snapshot instead of old translations or timestamps.
    """
    write_atomic(payload, path)
    companion = page_path(path)
    head_file = head_path(path)
    search_file = search_path(path)
    try:
        write_atomic(page_payload(payload), companion, compact=True)
    except Exception:
        companion.unlink(missing_ok=True)
        head_file.unlink(missing_ok=True)
        search_file.unlink(missing_ok=True)
        raise
    try:
        write_atomic(head_payload(payload), head_file, compact=True)
    except Exception:
        head_file.unlink(missing_ok=True)
        search_file.unlink(missing_ok=True)
        raise
    try:
        write_atomic(search_payload(payload), search_file, compact=True)
    except Exception:
        search_file.unlink(missing_ok=True)
        raise
    site_root = Path(path).resolve().parents[1] if Path(path).parent.name == "data" else Path(path).resolve().parent
    index_file = site_root / "index.html"
    if index_file.is_file():
        update_index_thumbnail(index_file, first_screen_thumbnail(payload))

"""Identity-verified Live tab metadata; relative ages are never exact dates."""

from datetime import datetime, timezone
import html
import re
from urllib.parse import urlsplit


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def text(value):
    if not isinstance(value, dict):
        return ""
    return " ".join(html.unescape(str(value.get("simpleText") or value.get("content") or
                                      "".join(run.get("text", "") for run in value.get("runs", [])))).split())


def renderers(content):
    """Visit channel grid containers, never descend into renderer recommendations."""
    if isinstance(content, list):
        for child in content:
            yield from renderers(child)
    elif isinstance(content, dict):
        for key in ("videoRenderer", "gridVideoRenderer", "lockupViewModel"):
            if key in content:
                item = content[key]
                if key != "lockupViewModel" or item.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO":
                    yield item
                return
        for key in ("richGridRenderer", "gridRenderer", "sectionListRenderer", "itemSectionRenderer",
                    "richItemRenderer", "content", "contents", "items"):
            if key in content:
                yield from renderers(content[key])


def verified_content(data, channel):
    metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
    if metadata.get("externalId") != channel[4]:
        raise ValueError("Channel identity missing or mismatched")
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    for entry in tabs:
        tab = entry.get("tabRenderer", {})
        endpoint = tab.get("endpoint", {}).get("commandMetadata", {}).get("webCommandMetadata", {})
        path = urlsplit(endpoint.get("url", "")).path.rstrip("/")
        if tab.get("selected") is True and path.endswith("/streams") and isinstance(tab.get("content"), dict):
            return tab["content"]
    raise ValueError("Selected YouTube Live tab missing")


def _recent_streamed(label):
    match = re.fullmatch(r"Streamed (\d+)\s*(second|minute|hour|day|s|m|h|d)s? ago", label, re.I)
    if not match:
        return False
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match[2][0].lower()]
    # The displayed age is rounded down; admit only if its entire bucket is <=7d.
    return (int(match[1]) + 1) * unit <= 7 * 86400


def fallback_item(renderer, video_id, channel, now):
    metadata = renderer.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = text(renderer.get("title", {})) or text(metadata.get("title", {}))
    if not title:
        return None
    # Explicit owner links, if supplied by a legacy renderer, must agree too.
    for key in ("ownerText", "shortBylineText", "longBylineText"):
        for node in objects(renderer.get(key, {})):
            owner = node.get("browseEndpoint", {}).get("browseId")
            if owner and owner != channel[4]:
                return None
    badges = []
    for key in ("badges", "thumbnailOverlays", "contentImage"):
        badges.extend(objects(renderer.get(key, {})))
    labels = [node[key] for node in badges for key in ("text", "label") if isinstance(node.get(key), str)]
    styles = {node.get(key) for node in badges for key in ("style", "badgeStyle")
              if isinstance(node.get(key), str)}
    lines = [text(renderer.get("publishedTimeText", {}))]
    lines += [text(node.get("text", {})) for node in objects(metadata.get("metadata", {}))
              if isinstance(node.get("text"), dict)]
    evidence = " ".join(labels + lines)
    if re.search(r"\bpremier(?:e|es|ed|ing)\b", evidence, re.I):
        return None
    start, time_text = None, None
    if styles & {"LIVE", "BADGE_STYLE_TYPE_LIVE_NOW", "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE"}:
        status = "live"
    elif renderer.get("upcomingEventData") is not None or any(label.lower() == "upcoming" for label in labels):
        status = "upcoming"
        time_text = next((line for line in lines if line.startswith("Scheduled for ")), None)
        timestamp = renderer.get("upcomingEventData", {}).get("startTime")
        if timestamp is not None:
            try:
                scheduled = datetime.fromtimestamp(int(timestamp), timezone.utc)
            except (ValueError, TypeError, OverflowError, OSError):
                return None
            if scheduled <= now:
                return None
            start = scheduled.isoformat().replace("+00:00", "Z")
    else:
        time_text = next((line for line in lines if _recent_streamed(line)), None)
        if not time_text:
            return None
        status = "ended"
    return {"video_id": video_id, "lab": channel[1], "channel": channel[2], "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "status": status, "start_at": start, "end_at": None,
            "status_source": "channel_streams", "time_text": time_text,
            "time_precision": "exact" if start else "relative" if status == "ended" else "unknown"}

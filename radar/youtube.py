"""Bounded public YouTube discovery; watch metadata is the status authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
import json
import re
import xml.etree.ElementTree as ET


CHANNELS = (
    ("openai-youtube", "openai", "OpenAI", "OpenAI", "UCXZCJLdBC09xxGZ6gcdrc6A"),
    ("anthropic-youtube", "anthropic", "Anthropic", "anthropic-ai", "UCrDwWp7EBBv4NwvScIpBDOA"),
    ("google-youtube", "google", "Google", "Google", "UCK8sQmJBp8GCxrOtXWBpyEA"),
    ("deepmind-youtube", "google", "Google DeepMind", "GoogleDeepMind", "UCP7jMXSY2xbc3KCAE0MHQ-A"),
)
SOURCES = [{"id": channel[0], "name": channel[2] + " YouTube", "lab": channel[1], "kind": "youtube"}
           for channel in CHANNELS]
MAX_WATCH_PAGES = 24
WATCH_WORKERS = 4
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _embedded(text, variable):
    pattern = rf'(?:\b{variable}|window\["{variable}"\])\s*=\s*'
    for match in re.finditer(pattern, text):
        try:
            value = json.JSONDecoder().raw_decode(text[match.end():])[0]
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Missing or malformed {variable}; consent or page format changed")


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def parse_streams(text):
    """Extract renderer IDs, never unrelated navigation/recommendation IDs."""
    data = _embedded(text, "ytInitialData")
    if "contents" not in data:
        raise ValueError("YouTube channel contents missing")
    found = {}
    for obj in _objects(data["contents"]):
        item = obj.get("videoRenderer") or obj.get("gridVideoRenderer")
        if item:
            video_id = item.get("videoId", "")
        else:
            item = obj.get("lockupViewModel", {})
            if item.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
                continue
            video_id = item.get("contentId", "")
        if not VIDEO_ID.fullmatch(video_id):
            continue
        # These hints only order requests; they never determine a live status.
        urgent = any(
            node.get("upcomingEventData") is not None
            or any(marker in str(node.get(key, "")) for marker in ("LIVE", "UPCOMING"))
            for node in _objects(item)
            for key in ("style", "badgeStyle")
        )
        found.setdefault(video_id, 0 if urgent else 1)
    if not found and not any("messageRenderer" in obj for obj in _objects(data["contents"])):
        raise ValueError("No supported video renderers or explicit empty channel state")
    return sorted(found.items(), key=lambda pair: pair[1])


def parse_rss(text):
    root = ET.fromstring(text)
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("Expected YouTube Atom feed")
    return [node.text for node in root.findall(".//{http://www.youtube.com/xml/schemas/2015}videoId")
            if node.text and VIDEO_ID.fullmatch(node.text)]


def parse_watch(text, video_id, channel, now):
    """Return a verified broadcast, an ordinary/old video as None, or error."""
    data = _embedded(text, "ytInitialPlayerResponse")
    details = data.get("videoDetails", {})
    if details.get("videoId") != video_id or details.get("channelId") != channel[4]:
        raise ValueError("Video identity/channel missing or mismatched")
    broadcast = data.get("microformat", {}).get("playerMicroformatRenderer", {}).get("liveBroadcastDetails")
    if not broadcast:
        if details.get("isLiveContent"):
            raise ValueError("Broadcast metadata unavailable")
        return None
    start, end = _date(broadcast.get("startTimestamp")), _date(broadcast.get("endTimestamp"))
    if (broadcast.get("startTimestamp") and not start) or (broadcast.get("endTimestamp") and not end):
        raise ValueError("Invalid broadcast timestamps")
    if broadcast.get("isLiveNow") is True and (end or (start and start > now)):
        raise ValueError("Inconsistent live broadcast timestamps")
    if end:
        if end > now or (start and end < start):
            raise ValueError("Inconsistent broadcast timestamps")
        if end < now - timedelta(days=7):
            return None
        status = "ended"
    elif broadcast.get("isLiveNow") is True:
        status = "live"
    elif start and start > now:
        status = "upcoming"
    else:
        raise ValueError("Broadcast status indeterminate")
    title = " ".join(html.unescape(str(details.get("title", ""))).split())
    if not title:
        raise ValueError("Video title missing")
    return {"video_id": video_id, "lab": channel[1], "channel": channel[2],
            "title": title, "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "status": status, "start_at": _iso(start), "end_at": _iso(end)}


def _discover(fetch, channel):
    candidates, errors = [], []
    streams, rss = [], []
    for label, url, parser in (
        ("streams", f"https://www.youtube.com/@{channel[3]}/streams?hl=en", parse_streams),
        ("rss", f"https://www.youtube.com/feeds/videos.xml?channel_id={channel[4]}", parse_rss),
    ):
        try:
            parsed = parser(fetch(url))
            if label == "streams":
                streams = parsed
            else:
                rss = parsed
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:160]}")
    # Reserve early slots for RSS additions; urgent stream badges lead the queue.
    ordered = [v for v, priority in streams if priority == 0]
    ordered += [v for v, _ in streams[:4]] + rss[:2]
    ordered += [v for v, _ in streams] + rss
    for video_id in ordered:
        if video_id not in candidates:
            candidates.append(video_id)
    return candidates, errors


def collect(fetch, now):
    """fetch(url)->text must enforce a <=10s deadline and response size limit.

    Four channel tasks take at most 20s, then 24 watch requests in six waves
    take at most 60s. Failures keep successful items and mark the source partial.
    """
    now = now.astimezone(timezone.utc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        discovered = list(pool.map(lambda channel: _discover(fetch, channel), CHANNELS))
    work = []
    # Round-robin protects smaller channels from a busy channel's request load.
    for offset in range(MAX_WATCH_PAGES):
        for index, (candidates, _) in enumerate(discovered):
            if offset < len(candidates) and len(work) < MAX_WATCH_PAGES:
                work.append((index, candidates[offset]))

    def watch(job):
        index, video_id = job
        try:
            item = parse_watch(fetch(f"https://www.youtube.com/watch?v={video_id}"),
                               video_id, CHANNELS[index], now)
            return index, item, None
        except Exception as exc:
            return index, None, f"watch {video_id}: {type(exc).__name__}: {str(exc)[:160]}"

    items, counts = [], [0] * len(CHANNELS)
    with ThreadPoolExecutor(max_workers=WATCH_WORKERS) as pool:
        for index, item, error in pool.map(watch, work):
            if error:
                discovered[index][1].append(error)
            if item:
                counts[index] += 1
                items.append(item)
    sources = [{"id": channel[0], "name": channel[2] + " YouTube", "lab": channel[1],
                "kind": "youtube", "ok": not discovered[index][1], "count": counts[index],
                "error": "; ".join(discovered[index][1]) or None}
               for index, channel in enumerate(CHANNELS)]
    return items, sources

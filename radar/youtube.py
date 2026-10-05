"""YouTube Data API v3 collection with verified channel playlists and video details."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
import json
import os
import re

from radar.common import vi_error
from radar.transport import sanitize_secret


CHANNELS = (
    ("openai-youtube", "openai", "OpenAI", "OpenAI", "UCXZCJLdBC09xxGZ6gcdrc6A"),
    ("anthropic-youtube", "anthropic", "Anthropic", "anthropic-ai", "UCrDwWp7EBBv4NwvScIpBDOA"),
    ("google-youtube", "google", "Google", "Google", "UCK8sQmJBp8GCxrOtXWBpyEA"),
    ("deepmind-youtube", "google", "Google DeepMind", "GoogleDeepMind", "UCP7jMXSY2xbc3KCAE0MHQ-A"),
)
SOURCES = [{"id": channel[0], "name": channel[2] + " YouTube", "lab": channel[1], "kind": "youtube",
            "url": f"https://www.youtube.com/@{channel[3]}"}
           for channel in CHANNELS]
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


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


def uploads_playlist_id(channel_id):
    """Derive uploads playlist ID from channel ID (UC... -> UU...)."""
    if channel_id and channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


def fetch_channel_uploads_id(fetch, channel_id):
    """Query channels.list or derive uploads playlist ID."""
    if channel_id.startswith("UC"):
        return uploads_playlist_id(channel_id)
    url = f"https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id={channel_id}"
    text = fetch(url)
    data = json.loads(text)
    items = data.get("items", [])
    if items:
        return items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    raise ValueError(f"Channel not found: {channel_id}")


def parse_playlist_items(text):
    """Extract list of valid video IDs from playlistItems.list JSON."""
    data = json.loads(text)
    video_ids = []
    for item in data.get("items", []):
        vid = item.get("contentDetails", {}).get("videoId")
        if not vid:
            vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
        if vid and VIDEO_ID.fullmatch(vid) and vid not in video_ids:
            video_ids.append(vid)
    return video_ids


def parse_video_item(item, channel, now):
    """Parse a single video item from videos.list response.

    Returns a verified broadcast dict, None for ordinary/expired videos, or raises ValueError.
    """
    video_id = item.get("id", "")
    if not VIDEO_ID.fullmatch(video_id):
        return None
    snippet = item.get("snippet", {})
    title = " ".join(html.unescape(snippet.get("title", "")).split())
    if not title:
        return None

    live_details = item.get("liveStreamingDetails")
    broadcast_content = snippet.get("liveBroadcastContent", "none")

    # Only broadcasts (live, upcoming, or ended livestream) are emitted.
    # Ordinary uploaded videos return None.
    if live_details is None and broadcast_content not in ("live", "upcoming"):
        return None

    actual_start_raw = live_details.get("actualStartTime") if live_details else None
    actual_end_raw = live_details.get("actualEndTime") if live_details else None
    scheduled_start_raw = live_details.get("scheduledStartTime") if live_details else None

    actual_start = _date(actual_start_raw)
    actual_end = _date(actual_end_raw)
    scheduled_start = _date(scheduled_start_raw)

    if ((actual_start_raw and not actual_start) or
        (actual_end_raw and not actual_end) or
        (scheduled_start_raw and not scheduled_start)):
        raise ValueError("Invalid broadcast timestamps")

    if actual_end:
        if actual_end > now or (actual_start and actual_end < actual_start):
            raise ValueError("Inconsistent broadcast timestamps")
        if actual_end < now - timedelta(days=7):
            return None
        status = "ended"
        start = actual_start or scheduled_start
        end = actual_end
    elif broadcast_content == "live" or actual_start:
        if actual_start and actual_start > now:
            raise ValueError("Inconsistent live broadcast timestamps")
        status = "live"
        start = actual_start or scheduled_start or (_date(snippet.get("publishedAt")) if broadcast_content == "live" else None)
        end = None
    elif (scheduled_start and scheduled_start > now) or (broadcast_content == "upcoming" and _date(snippet.get("publishedAt")) and _date(snippet.get("publishedAt")) > now):
        status = "upcoming"
        start = scheduled_start or _date(snippet.get("publishedAt"))
        end = None
    else:
        raise ValueError("Broadcast status indeterminate")

    thumbnails = snippet.get("thumbnails", {})
    thumbnail = (thumbnails.get("high") or thumbnails.get("medium") or
                 thumbnails.get("default") or {}).get("url") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    published_at = snippet.get("publishedAt")
    url = f"https://www.youtube.com/watch?v={video_id}"

    return {
        "video_id": video_id,
        "lab": channel[1],
        "channel": channel[2],
        "title": title,
        "url": url,
        "thumbnail": thumbnail,
        "published_at": published_at,
        "status": status,
        "start_at": _iso(start),
        "end_at": _iso(end),
    }


def parse_videos_response(text, channel, now, diagnostics=None):
    """Parse videos.list JSON response into observation entries."""
    data = json.loads(text)
    items = []
    for item in data.get("items", []):
        try:
            entry = parse_video_item(item, channel, now)
            if entry:
                items.append(entry)
        except Exception as exc:
            vid = item.get("id", "unknown")
            msg = sanitize_secret(f"video {vid}: {type(exc).__name__}: {exc}")[:160]
            if diagnostics is not None:
                diagnostics.append(msg)
    return items


def collect_channel(fetch, channel, now):
    """Fetch video metadata for one channel via Data API v3."""
    diagnostics = []
    channel_id = channel[4]
    playlist_id = uploads_playlist_id(channel_id)
    playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={playlist_id}&maxResults=5"
    try:
        playlist_text = fetch(playlist_url)
        video_ids = parse_playlist_items(playlist_text)
    except Exception as exc:
        error_text = sanitize_secret(f"{type(exc).__name__}: {exc}")[:160]
        return [], error_text, diagnostics

    if not video_ids:
        return [], None, diagnostics

    videos_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,liveStreamingDetails&id={','.join(video_ids)}"
    try:
        videos_text = fetch(videos_url)
        items = parse_videos_response(videos_text, channel, now, diagnostics=diagnostics)
        return items, None, diagnostics
    except Exception as exc:
        error_text = sanitize_secret(f"{type(exc).__name__}: {exc}")[:160]
        return [], error_text, diagnostics


def collect(fetch, now, channels=None):
    """Collect YouTube channel videos using YouTube Data API v3.

    Enforces boundaries:
    - Never uses channel RSS or scraping fallback.
    - Requires YOUTUBE_API_KEY environment variable.
    - Honest source error on missing key or API failure.
    """
    now = now.astimezone(timezone.utc)
    channels = CHANNELS if channels is None else channels

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        error_msg = "Missing YOUTUBE_API_KEY environment variable"
        sources = [{"id": channel[0], "name": channel[2] + " YouTube", "lab": channel[1],
                    "kind": "youtube", "ok": False, "count": 0, "error": error_msg,
                    "error_vi": vi_error(error_msg)}
                   for channel in channels]
        return [], sources

    fetches = [fetch.scoped(channel[0]) if hasattr(fetch, "scoped") else fetch for channel in channels]
    with ThreadPoolExecutor(max_workers=min(4, len(channels))) as pool:
        results = list(pool.map(lambda pair: collect_channel(pair[0], pair[1], now), zip(fetches, channels)))

    all_items = []
    sources = []
    for channel, (items, error, diagnostics) in zip(channels, results):
        all_items.extend(items)
        source_record = {
            "id": channel[0],
            "name": channel[2] + " YouTube",
            "lab": channel[1],
            "kind": "youtube",
            "ok": error is None,
            "count": len(items),
            "error": error,
            "error_vi": vi_error(error),
        }
        if diagnostics:
            source_record["diagnostics"] = diagnostics
        sources.append(source_record)

    return all_items, sources

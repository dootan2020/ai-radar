"""RSS/Atom observations with actual podcast enclosure and image links."""

import xml.etree.ElementTree as ET

from radar.common import classify, clean_text, web_url
from radar.feeds import _field, _local, _research_copy
from radar.items import observation, relevant


def parse_feed(text, source, observed_at):
    root = ET.fromstring(text)
    if _local(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("Expected RSS or Atom")
    entries = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    result, seen, usable = [], set(), 0
    for entry in entries:
        title = clean_text(_field(entry, "title"), 500)
        url = _field(entry, "link").strip()
        media = []
        for child in entry.iter():
            local = _local(child.tag)
            if local == "link" and child.get("href") and child.get("rel", "alternate") == "alternate":
                url = child.get("href")
            enclosure = local == "enclosure" or local == "link" and child.get("rel") == "enclosure"
            media_namespace = "search.yahoo.com/mrss" in child.tag
            if enclosure or media_namespace and local in {"content", "thumbnail"} or local == "image" and child.get("href"):
                target = web_url(child.get("url") or child.get("href"))
                mime = child.get("type")
                medium = child.get("medium") or (mime or "").split("/")[0]
                if local in {"thumbnail", "image"}:
                    medium = "image"
                if enclosure and not medium and source.get("group") == "podcast":
                    medium = "audio"
                if target and medium in {"audio", "video", "image"}:
                    media.append(dict(url=target, type=medium, mime_type=mime))
        if not web_url(url) or not title:
            continue
        usable += 1
        if url in seen:
            continue
        seen.add(url)
        summary = clean_text(_field(entry, "description", "summary", "encoded", "content"))
        if source["id"] == "anthropic-research":
            title, summary = _research_copy(title, summary)
        if source.get("filter_ai") and not relevant(title, summary):
            continue
        kind = "podcast" if source.get("group") == "podcast" else classify(title, summary)
        if source["id"] == "anthropic-research":
            kind = "research"
        if "youtube.com/feeds/" in source.get("url", ""):
            kind = "video"
            media.append(dict(url=url, type="video", mime_type=None))
        date = _field(entry, "pubDate", "published", "date", "updated")
        item = observation(source, title, url, date, observed_at, kind=kind, summary=summary, media=media)
        if item:
            result.append(item)
    if entries and not usable:
        raise ValueError("Feed entries have no usable title and URL")
    return sorted(result, key=lambda item: item["published_at"] or "", reverse=True)[:50]

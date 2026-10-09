"""Public community observations preserve both target and discussion URLs."""

import json
import xml.etree.ElementTree as ET

from radar.common import clean_text, web_url
from radar.items import observation, relevant


def parse_reddit(text, source, observed_at):
    """Parse Reddit's public top-post Atom feed; retain only its highest ranks."""
    root = ET.fromstring(text)
    if root.tag.rsplit("}", 1)[-1] != "feed":
        raise ValueError("Expected Reddit Atom feed")
    entries = [node for node in root if node.tag.rsplit("}", 1)[-1] == "entry"]
    result, usable = [], 0
    limit = source.get("rank_limit", 10)
    for rank, entry in enumerate(entries, 1):
        title = ""; url = ""; summary = ""; published = ""
        for child in entry:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "title": title = clean_text("".join(child.itertext()), 500)
            elif name == "link" and child.get("rel", "alternate") == "alternate": url = child.get("href", "")
            elif name == "content": summary = clean_text("".join(child.itertext()))
            elif name == "published": published = "".join(child.itertext())
        if not title or not web_url(url):
            continue
        usable += 1
        if rank > limit or not relevant(title, summary):
            continue
        item = observation(source, title, url, published, observed_at, kind="forum", summary=summary,
                           discussion_url=url, metrics={"rank": rank})
        if item:
            result.append(item)
    if entries and not usable:
        raise ValueError("Reddit Atom entries have no usable post title and URL")
    return result


def parse_hn(text, source, observed_at):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
        raise ValueError("Expected HN hits array")
    result, usable = [], 0
    for row in data["hits"]:
        if not isinstance(row, dict) or not str(row.get("objectID", "")).isdigit() or not clean_text(row.get("title")):
            continue
        usable += 1
        title, summary = clean_text(row["title"], 500), clean_text(row.get("story_text"))
        if not relevant(title, summary):
            continue
        discussion = "https://news.ycombinator.com/item?id=" + str(row["objectID"])
        item = observation(source, title, web_url(row.get("url")) or discussion, row.get("created_at"),
                           observed_at, kind="forum", summary=summary, discussion_url=discussion,
                           metrics={"points": row.get("points"), "comments": row.get("num_comments")})
        if item:
            result.append(item)
    if data["hits"] and not usable:
        raise ValueError("HN hits have no usable stories")
    return result


def parse_lobsters(text, source, observed_at):
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Expected Lobsters story array")
    result, usable = [], 0
    for row in data:
        if not isinstance(row, dict) or not row.get("title") or not web_url(row.get("url") or row.get("comments_url")):
            continue
        usable += 1
        if "ai" not in (row.get("tags") or []) and not relevant(row["title"], clean_text(row.get("description"))):
            continue
        item = observation(source, row["title"], row.get("url") or row.get("comments_url"), row.get("created_at"),
                           observed_at, kind="forum", summary=row.get("description", ""), discussion_url=row.get("comments_url"),
                           metrics={"score": row.get("score"), "comments": row.get("comment_count")})
        if item:
            result.append(item)
    if data and not usable:
        raise ValueError("Lobsters array has no usable stories")
    return result

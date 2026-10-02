"""Public community observations preserve both target and discussion URLs."""

import json

from radar.common import clean_text, web_url
from radar.items import observation, relevant


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

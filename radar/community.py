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

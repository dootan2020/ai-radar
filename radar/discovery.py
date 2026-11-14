"""Anonymous paper and repository APIs; original counters only."""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote

from radar.common import web_url
from radar.huggingface import _repo_id
from radar.items import observation
from radar.items import relevant


GITHUB_AI_MAX_REPOSITORIES = 20


def _github_flood_signatures(rows):
    """Find repeated names and descriptions created by five owners within ten minutes."""
    groups = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or not _repo_id(row.get("full_name")):
            continue
        description = row.get("description")
        if not isinstance(description, str) or not description.strip():
            continue
        created = row.get("created_at")
        if not isinstance(created, str):
            continue
        try:
            instant = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if instant.tzinfo is None:
            continue
        owner, name = row["full_name"].split("/", 1)
        groups[(name.casefold(), description.strip().casefold())].append((instant, owner.casefold()))

    floods = set()
    for signature, entries in groups.items():
        entries.sort()
        for start, (begin, _) in enumerate(entries):
            owners = {owner for instant, owner in entries[start:]
                      if instant - begin <= timedelta(minutes=10)}
            if len(owners) >= 5:
                floods.add(signature)
                break
    return floods


def parse_papers(text, source, observed_at):
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Expected daily papers array")
    result = []
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("paper"), dict):
            continue
        paper = row["paper"]
        id_ = paper.get("id")
        if not isinstance(id_, str) or not re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", id_):
            continue
        media = []
        image = row.get("thumbnail")
        if web_url(image):
            media.append(dict(url=image, type="image", mime_type=None))
        item = observation(source, row.get("title") or paper.get("title"), "https://arxiv.org/abs/" + id_,
                           paper.get("publishedAt") or row.get("publishedAt"), observed_at, kind="paper",
                           summary=row.get("summary") or paper.get("summary", ""), media=media,
                           discussion_url="https://huggingface.co/papers/" + id_,
                           metrics={"upvotes": paper.get("upvotes"), "comments": row.get("numComments")})
        if item:
            result.append(item)
    if data and not result:
        raise ValueError("Daily papers array has no usable papers")
    return result


def parse_hf_trending(text, source, observed_at):
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Expected ranked HF repository array")
    result = []
    kind = source.get("repo_type", "model")
    for row in data:
        if not isinstance(row, dict) or not _repo_id(row.get("id")):
            continue
        repo = row["id"]
        prefix = "spaces/" if kind == "space" else ""
        item = observation(source, repo, "https://huggingface.co/" + prefix + quote(repo, safe="/"),
                           row.get("createdAt"), observed_at, kind="model" if kind == "model" else "repository",
                           metrics={"trending_score": row.get("trendingScore"), "likes": row.get("likes"), "downloads": row.get("downloads")},
                           time_basis="repository_created", pipeline_tag=row.get("pipeline_tag"))
        if item:
            result.append(item)
    if data and not result:
        raise ValueError("Ranked HF array has no usable repositories")
    return result


def parse_github(text, source, observed_at):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Expected GitHub search items array")
    floods = _github_flood_signatures(data["items"]) if source.get("id") == "github-ai" else set()
    result = []
    usable = 0
    dropped = 0
    for row in data["items"]:
        if not isinstance(row, dict) or not _repo_id(row.get("full_name")):
            continue
        usable += 1
        description = row.get("description")
        signature = (row["full_name"].split("/", 1)[1].casefold(),
                     description.strip().casefold() if isinstance(description, str) else "")
        if signature in floods:
            dropped += 1
            continue
        item = observation(source, row["full_name"], row.get("html_url"), row.get("created_at"), observed_at,
                           kind="repository", summary=row.get("description", ""), time_basis="repository_created",
                           metrics={"stars": row.get("stargazers_count"), "forks": row.get("forks_count")})
        if item:
            result.append(item)
    if dropped:
        logging.getLogger(__name__).warning("github-ai filtered %d coordinated repository copies", dropped)
    if data["items"] and not result and not (dropped and dropped == usable):
        raise ValueError("GitHub search has no usable repositories")
    if source.get("id") == "github-ai":
        result = result[:GITHUB_AI_MAX_REPOSITORIES]
    return result


def parse_bluesky(text, source, observed_at):
    """Parse the anonymous Bluesky author-feed API, retaining AI-related posts."""
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("feed"), list):
        raise ValueError("Expected Bluesky author feed")
    result, usable = [], 0
    handle = source.get("handle", "")
    for row in data["feed"]:
        post = row.get("post", {}) if isinstance(row, dict) else {}
        record = post.get("record", {}) if isinstance(post, dict) else {}
        text_value = record.get("text", "")
        uri = post.get("uri", "")
        rkey = uri.rsplit("/", 1)[-1] if isinstance(uri, str) else ""
        author = post.get("author", {})
        if not text_value or not rkey or author.get("handle") != handle:
            continue
        usable += 1
        if source.get("filter_ai", True) and not relevant(text_value):
            continue
        url = "https://bsky.app/profile/" + handle + "/post/" + rkey
        item = observation(source, text_value, url, record.get("createdAt") or post.get("indexedAt"),
                           observed_at, kind="social", summary=text_value,
                           metrics={"likes": post.get("likeCount"), "reposts": post.get("repostCount"),
                                    "replies": post.get("replyCount")})
        if item:
            result.append(item)
    if data["feed"] and not usable:
        raise ValueError("Bluesky feed has no usable posts for configured author")
    return result

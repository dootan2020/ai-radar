"""Hand-written "Hướng dẫn" guides: loaded from data/huong-dan/*.json into the news stream.

A guide is Vietnamese prose the team wrote itself, so it never goes through the newsroom's writer and scoring desk,
the translation step or the summary step. What stands in for the scoring desk is the owner's approval, recorded in
the file (who, when, in his own words). A file without a complete approval is refused with a message that names the
file and the missing field, and nothing of it reaches a reader. `is_guide` is the one test the narrow bypasses in
the decision gate, the story pages and the search index share; it needs both the guide kind and a valid approval.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from radar.site_config import SITE_BASE_URL

KIND = "huong-dan"
LABEL = "Hướng dẫn"
SOURCE_ID = "hco-huong-dan"
PUBLISHER = "Halcyon"
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "huong-dan"
ID_PATTERN = re.compile(r"hd-[a-z0-9][a-z0-9_-]*\Z")
IMAGE_PATTERN = re.compile(r"(https://\S+|assets/huong-dan/[\w.-]+\.(?:png|jpe?g|webp|svg))\Z")
DESK_PROMPT_VERSION = "summary-vi-7-bullets"
FILE_KEYS = {"id", "title", "published_at", "key_points", "summary_sources", "body", "approval", "image"}
APPROVAL_KEYS = {"approved_by", "approved_at", "words"}
BLOCK_KEYS = {
    "heading": {"type", "text"},
    "paragraph": {"type", "text"},
    "steps": {"type", "items"},
    "list": {"type", "items"},
    "code": {"type", "text", "language", "caption"},
    "image": {"type", "src", "alt", "caption"},
}


class GuideError(ValueError):
    """A guide file that must not be published; the message names the file and the field."""


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _text(value, limit=2000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _http(value):
    return isinstance(value, str) and value.startswith(("https://", "http://")) and " " not in value


def approval_valid(approval, now=None):
    """Who approved, when, and the owner's words: all three present, the time readable and not in the future."""
    if not isinstance(approval, dict) or set(approval) != APPROVAL_KEYS:
        return False
    moment = _instant(approval.get("approved_at"))
    if moment is None or (now is not None and moment > now):
        return False
    return _text(approval.get("approved_by"), 120) and _text(approval.get("words"), 500)


def is_guide(story):
    """The only thing that lets a story skip the scoring desk: the guide kind plus a valid owner approval."""
    return bool(isinstance(story, dict) and story.get("kind") == KIND and story.get("source_id") == SOURCE_ID
                and approval_valid(story.get("approval")))


def _check_block(index, block):
    where = f"body[{index}]"
    kind = block.get("type") if isinstance(block, dict) else None
    if kind not in BLOCK_KEYS:
        raise GuideError(f"{where}: type must be one of {', '.join(sorted(BLOCK_KEYS))}")
    extra = set(block) - BLOCK_KEYS[kind]
    if extra:
        raise GuideError(f"{where}: unknown field {', '.join(sorted(extra))}")
    if kind in ("heading", "paragraph", "code") and not _text(block.get("text"), 8000):
        raise GuideError(f"{where}: text is required")
    if kind in ("steps", "list"):
        items = block.get("items")
        if not (isinstance(items, list) and items and all(_text(item, 1500) for item in items)):
            raise GuideError(f"{where}: items must be a non-empty list of text")
    if kind == "code":
        for field in ("language", "caption"):
            if field in block and not _text(block[field], 200):
                raise GuideError(f"{where}: {field} must be text")
    if kind == "image":
        if not (isinstance(block.get("src"), str) and IMAGE_PATTERN.fullmatch(block["src"])):
            raise GuideError(f"{where}: src must be an https URL or assets/huong-dan/<file>")
        if not _text(block.get("alt"), 300):
            raise GuideError(f"{where}: alt text is required")
        if "caption" in block and not _text(block["caption"], 300):
            raise GuideError(f"{where}: caption must be text")


def validate(row, name, now):
    """Raise GuideError unless the file is a complete, approved guide; return the row."""
    if not isinstance(row, dict):
        raise GuideError("the file must hold one JSON object")
    missing = [key for key in ("id", "title", "published_at", "key_points", "summary_sources", "body", "approval")
               if key not in row]
    if "approval" in missing:
        raise GuideError("approval is missing: a guide is published only with the owner's approval "
                         "(approved_by, approved_at, words)")
    if missing:
        raise GuideError(f"missing field {', '.join(missing)}")
    if set(row) - FILE_KEYS:
        raise GuideError(f"unknown field {', '.join(sorted(set(row) - FILE_KEYS))}")
    if not approval_valid(row["approval"], now):
        raise GuideError("approval is incomplete: approved_by, approved_at (ISO time with zone, not in the future) "
                         "and words (the owner's words) are all required and nothing else")
    if not (isinstance(row["id"], str) and ID_PATTERN.fullmatch(row["id"])) or row["id"] != name:
        raise GuideError(f"id must match the file name and look like hd-<slug> (got {row['id']!r})")
    if not _text(row["title"], 200):
        raise GuideError("title is required (200 characters at most)")
    published = _instant(row["published_at"])
    if published is None or published > now:
        raise GuideError("published_at must be an ISO time with a zone, not in the future")
    points = row["key_points"]
    if not (isinstance(points, list) and 3 <= len(points) <= 4 and all(_text(p, 600) for p in points)):
        raise GuideError("key_points must be 3 or 4 short paragraphs")
    sources = row["summary_sources"]
    if not (isinstance(sources, list) and sources and all(
            isinstance(s, dict) and _text(s.get("name"), 120) and _http(s.get("url"))
            and set(s) <= {"name", "url", "role"} for s in sources)):
        raise GuideError("summary_sources must list the pages the steps were checked against (name and https url)")
    body = row["body"]
    if not (isinstance(body, list) and body):
        raise GuideError("body must be a non-empty list of blocks")
    for index, block in enumerate(body):
        _check_block(index, block)
    image = row.get("image")
    if image is not None and not (isinstance(image, str) and image.startswith("https://") and " " not in image):
        raise GuideError("image (the card's picture) must be an https URL; leave it out for a drawn cover")
    return row


def guide_story(row):
    """The stream story for a validated guide, shaped like a desk-written story so the readers need no special path."""
    url = f"{SITE_BASE_URL}/tin/{row['id']}/"
    published = row["published_at"]
    points = [point.strip() for point in row["key_points"]]
    story = {
        "id": row["id"], "title": row["title"].strip(), "url": url, "published_at": published,
        "appeared_at": published, "latest_coverage_at": published, "time_basis": "published",
        "kind": KIND, "source_id": SOURCE_ID, "source_count": 1, "aliases": [],
        "editorial_headline_vi": row["title"].strip(),
        "key_points": points, "key_points_source": "nguoi-viet", "key_points_machine": False,
        "key_points_prompt_version": DESK_PROMPT_VERSION,
        "summary_sources": [dict(s) for s in row["summary_sources"]], "summary_limitations": [],
        "body": [dict(block) for block in row["body"]], "approval": dict(row["approval"]),
        "coverage": [{"id": row["id"], "source": SOURCE_ID, "publisher": PUBLISHER, "title": row["title"].strip(),
                      "url": url, "published_at": published, "time_basis": "published", "metrics": {}}],
    }
    if row.get("image"):
        story["image"] = {"src": row["image"], "via": "guide", "kind": "guide"}
    return story


def load_guides(directory=DEFAULT_DIR, now=None):
    """(stories, errors): every approved guide, and one "file: reason" line per file that was refused."""
    now = now or datetime.now(timezone.utc)
    stories, errors = [], []
    directory = Path(directory)
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            row = validate(json.loads(path.read_text(encoding="utf-8")), path.stem, now)
            stories.append(guide_story(row))
        except (GuideError, ValueError) as error:
            errors.append(f"{path.name}: {error}")
    return stories, errors


def inject(payload, stories):
    """Make the payload's guides exactly the given ones.

    A guide carried over from the previous publication is dropped unless its file still loads, so deleting or breaking
    a file withdraws the guide at the next build, and a rerun never doubles one.
    """
    kept = [story for story in payload.get("stories", [])
            if story.get("kind") != KIND and story.get("id") not in {s["id"] for s in stories}]
    payload["stories"] = kept + list(stories)
    return payload

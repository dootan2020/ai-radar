"""Apply recent local newsroom decisions to the published site snapshot."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "phong-bao" / "decisions.json"
DEFAULT_MAX_AGE_HOURS = 12
# Provenance of summaries written by the newsroom's "Người viết" desk. The paid
# summary step leaves such stories alone; the API only fills the rest. The desk
# writes 3-4 short paragraphs (contract DESK_PROMPT_VERSION), carried in
# `key_points` so retention, search and video scripts keep working unchanged.
DESK_SUMMARY_SOURCE = "nguoi-viet"
DESK_PROMPT_VERSION = "summary-vi-6-prose"
DESK_SUMMARY_FIELDS = ("key_points", "editorial_headline_vi", "summary_sources",
                       "summary_limitations", "key_points_prompt_version")


def _http(value):
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def desk_fields_valid(row):
    """Desk prose: 3-4 non-empty paragraphs, a headline and at least one web source."""
    if not isinstance(row, dict):
        return False
    points, sources = row.get("key_points"), row.get("summary_sources")
    return bool(isinstance(points, list) and 3 <= len(points) <= 4
                and all(isinstance(p, str) and p.strip() for p in points)
                and row.get("key_points_prompt_version") == DESK_PROMPT_VERSION
                and isinstance(row.get("editorial_headline_vi"), str) and row["editorial_headline_vi"].strip()
                and isinstance(row.get("summary_limitations"), list)
                and isinstance(sources, list)
                and any(isinstance(s, dict) and _http(s.get("url")) for s in sources))


def desk_summary(row):
    """Return the public summary fields of a desk-written decision, or None."""
    if (not isinstance(row, dict) or row.get("decision") != "publish"
            or row.get("written_by") != DESK_SUMMARY_SOURCE or not desk_fields_valid(row)):
        return None
    fields = {key: deepcopy(row[key]) for key in DESK_SUMMARY_FIELDS}
    fields.update(key_points_machine=True, key_points_source=DESK_SUMMARY_SOURCE)
    return fields


def is_desk_summary(story):
    """A story already carrying desk-written prose for the current desk contract."""
    return bool(isinstance(story, dict) and story.get("key_points_source") == DESK_SUMMARY_SOURCE
                and desk_fields_valid(story))


def load_decisions(path=None, *, now=None, max_age_hours=None):
    """An absent, malformed, future or stale file means the existing site behavior."""
    path = Path(path or os.environ.get("RADAR_NEWSROOM_DECISIONS", DEFAULT_PATH))
    try:
        hours = float(max_age_hours if max_age_hours is not None else
                      os.environ.get("RADAR_NEWSROOM_MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS))
        if hours <= 0:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("generated_at"), str):
            return None
        stamp = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if (stamp.tzinfo is None or data.get("schema_version") != 1 or
                not isinstance(data.get("decisions"), list) or
                not timedelta(0) <= current - stamp <= timedelta(hours=hours)):
            return None
        ids = set()
        for row in data["decisions"]:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or
                    not row["id"] or row.get("decision") not in {"hold", "publish"} or row["id"] in ids):
                return None
            ids.add(row["id"])
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def apply_decisions(payload, decisions):
    """Hide held stories, publish desk-written key points, and optionally cap tiers while the desk is fresh."""
    if decisions is None:
        return payload
    cap_tiers = os.environ.get("RADAR_NEWSROOM_CAP_TIERS", "").strip().lower() in {"1", "true", "yes", "on"}
    result = deepcopy(payload)
    reviewed = {row["id"]: row for row in decisions["decisions"]}
    stories = []
    for story in result.get("stories", []):
        row = reviewed.get(story.get("id"))
        if row is not None and row["decision"] == "hold":
            continue
        if cap_tiers and row is not None and (row.get("content_kind") == "analysis" or row.get("tier_capped")
                                or row.get("importance_tier") == "standard"):
            story["importance_tier"] = "standard"
            story["importance_weight"] = min(story.get("importance_weight", 0) or 0, 29.99)
            story["importance_reason"] = "newsroom standard tier"
        written = desk_summary(row)
        if written is not None:
            story.update(written)
        stories.append(story)
    result["stories"] = stories
    visible = {story["id"] for story in stories}
    if isinstance(result.get("sections"), dict):
        result["sections"] = {name: [sid for sid in ids if sid in visible]
                              for name, ids in result["sections"].items()}
    return result

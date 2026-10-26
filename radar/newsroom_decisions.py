"""Apply recent local newsroom decisions to the published site snapshot."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "phong-bao" / "decisions.json"
DEFAULT_MAX_AGE_HOURS = 12


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
    """Only approved stories enter public projections while the desk is fresh."""
    if decisions is None:
        return payload
    result = deepcopy(payload)
    approved = {row["id"]: row for row in decisions["decisions"] if row["decision"] == "publish"}
    stories = []
    for story in result.get("stories", []):
        row = approved.get(story.get("id"))
        if row is None:
            continue
        if row.get("content_kind") == "analysis" or row.get("tier_capped") or row.get("importance_tier") == "standard":
            story["importance_tier"] = "standard"
            story["importance_weight"] = min(story.get("importance_weight", 0) or 0, 29.99)
            story["importance_reason"] = "newsroom standard tier"
        points = row.get("key_points")
        if row.get("summary") == "claims" and isinstance(points, list) and len(points) >= 2 \
                and all(isinstance(point, str) and point.strip() for point in points):
            story["summary"] = " ".join(point.strip() for point in points)
            story.pop("summary_vi", None)
            for key in ("key_points_machine", "key_points_source", "key_points_prompt_version",
                        "editorial_headline_vi", "editorial_headline_verified"):
                story.pop(key, None)
            story["key_points"] = points
        stories.append(story)
    result["stories"] = stories
    visible = {story["id"] for story in stories}
    if isinstance(result.get("sections"), dict):
        result["sections"] = {name: [sid for sid in ids if sid in visible]
                              for name, ids in result["sections"].items()}
    return result

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
    """Hide held stories and cap published tiers while the desk is fresh."""
    if decisions is None:
        return payload
    result = deepcopy(payload)
    reviewed = {row["id"]: row for row in decisions["decisions"]}
    stories = []
    for story in result.get("stories", []):
        row = reviewed.get(story.get("id"))
        if row is not None and row["decision"] == "hold":
            continue
        if row is not None and (row.get("content_kind") == "analysis" or row.get("tier_capped")
                                or row.get("importance_tier") == "standard"):
            story["importance_tier"] = "standard"
            story["importance_weight"] = min(story.get("importance_weight", 0) or 0, 29.99)
            story["importance_reason"] = "newsroom standard tier"
        stories.append(story)
    result["stories"] = stories
    visible = {story["id"] for story in stories}
    if isinstance(result.get("sections"), dict):
        result["sections"] = {name: [sid for sid in ids if sid in visible]
                              for name, ids in result["sections"].items()}
    return result

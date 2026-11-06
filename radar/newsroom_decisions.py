"""Show readers only the stories whose newsroom prose passed the scoring desk."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "phong-bao" / "decisions.json"
# The scoring desk ("bàn chấm") reads each story's Vietnamese headline and paragraphs against the article and
# answers the captain's four questions (2026-10-27): what happened, why, what is notable, what it means. A story
# reaches readers only with a weighted score of at least SCORE_THRESHOLD out of 10 and no hard error (a fact,
# cause, number, name, role or quote the source does not support, or the main event missing). The weights are
# the ones the captain accepted from the 06/11 review of nine published stories; a source that gives no cause
# costs nothing. Change SCORE_THRESHOLD to move the bar; the site recomputes every verdict on each build.
SCORE_THRESHOLD = 8.0
SCORE_WEIGHTS = {"what": 0.35, "why": 0.20, "notable": 0.30, "meaning": 0.15}
SCORER_VERSION = "cham-4-cau-1"
HARD_ERROR_KINDS = ("fact", "cause", "number", "name", "role", "quote", "main_event_missing")
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


def prose_digest(headline, paragraphs):
    """Fingerprint of the exact headline and paragraphs a verdict was given for."""
    text = json.dumps([headline, *paragraphs], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def weighted_score(answers):
    """Overall score out of 10 from the four question scores, or None when any is missing or out of range."""
    if not isinstance(answers, dict) or set(answers) != set(SCORE_WEIGHTS):
        return None
    total = 0.0
    for name, weight in SCORE_WEIGHTS.items():
        value = answers[name]
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not 0 <= value <= 10):
            return None
        total += weight * value
    return round(total, 2)


def score_passed(row):
    """True only for desk prose whose current headline and paragraphs a scorer on another boat passed."""
    score = row.get("score") if isinstance(row, dict) else None
    if not isinstance(score, dict) or score.get("version") != SCORER_VERSION:
        return False
    value = weighted_score(score.get("answers"))
    writers, scorer = score.get("writer_boats"), score.get("scorer_boat")
    return bool(value is not None and value >= SCORE_THRESHOLD and score.get("value") == value
                and score.get("hard_errors") == []
                and isinstance(writers, list) and writers and all(isinstance(boat, str) and boat for boat in writers)
                and isinstance(scorer, str) and scorer and scorer not in writers
                and isinstance(row.get("key_points"), list)
                and score.get("prose_sha256") == prose_digest(row.get("editorial_headline_vi"), row["key_points"]))


def desk_summary(row):
    """Return the public summary fields of a desk-written decision that passed the scoring desk, or None."""
    if (not isinstance(row, dict) or row.get("decision") != "publish"
            or row.get("written_by") != DESK_SUMMARY_SOURCE or not desk_fields_valid(row)
            or not score_passed(row)):
        return None
    fields = {key: deepcopy(row[key]) for key in DESK_SUMMARY_FIELDS}
    fields.update(key_points_machine=True, key_points_source=DESK_SUMMARY_SOURCE)
    return fields


def is_desk_summary(story):
    """A story already carrying desk-written prose for the current desk contract."""
    return bool(isinstance(story, dict) and story.get("key_points_source") == DESK_SUMMARY_SOURCE
                and desk_fields_valid(story))


def load_decisions(path=None, *, now=None):
    """The decisions file, or None when it is absent, malformed or dated in the future.

    A file of any age is still read: it can only show stories its scoring desk passed, so an old file never shows
    an unchecked story, and hiding passed stories when the newsroom misses a cycle would gain no safety.
    """
    path = Path(path or os.environ.get("RADAR_NEWSROOM_DECISIONS", DEFAULT_PATH))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("generated_at"), str):
            return None
        stamp = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if (stamp.tzinfo is None or data.get("schema_version") != 1 or
                not isinstance(data.get("decisions"), list) or stamp - current > timedelta(minutes=10)):
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
    """Keep only stories whose desk prose passed the scoring desk, with that prose; optionally cap their tiers.

    Fail closed: a held story, a story the newsroom has not decided, one without desk prose, one whose prose was
    not scored, scored below SCORE_THRESHOLD or with a hard error, and every story when there are no decisions
    (None) are all left out of the snapshot and of every section and projection built from it.
    """
    cap_tiers = os.environ.get("RADAR_NEWSROOM_CAP_TIERS", "").strip().lower() in {"1", "true", "yes", "on"}
    result = deepcopy(payload)
    reviewed = {row["id"]: row for row in decisions["decisions"]} if decisions is not None else {}
    stories = []
    for story in result.get("stories", []):
        row = reviewed.get(story.get("id"))
        written = desk_summary(row)
        if written is None:
            continue
        if cap_tiers and (row.get("content_kind") == "analysis" or row.get("tier_capped")
                          or row.get("importance_tier") == "standard"):
            story["importance_tier"] = "standard"
            story["importance_weight"] = min(story.get("importance_weight", 0) or 0, 29.99)
            story["importance_reason"] = "newsroom standard tier"
        story.update(written)
        stories.append(story)
    result["stories"] = stories
    visible = {story["id"] for story in stories}
    if isinstance(result.get("sections"), dict):
        result["sections"] = {name: [sid for sid in ids if sid in visible]
                              for name, ids in result["sections"].items()}
    return result

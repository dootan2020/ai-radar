"""Shared spending order for stories promoted on the reader home page."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from radar.items import instant
from radar.worth import calculate_worth


def ordered_stories(payload, editor_picks=None):
    stories = [s for s in payload.get("stories", []) if isinstance(s, dict)]
    generated = instant(payload.get("generated_at")) or datetime.now(timezone.utc)
    try:
        hours = float((payload.get("ranking") or {}).get("window_hours", 72))
        if not 0 < hours < float("inf"):
            hours = 72
    except (ValueError, TypeError):
        hours = 72
    active = [s for s in stories if instant(s.get("published_at"))
              and generated - timedelta(hours=hours) <= instant(s["published_at"]) <= generated + timedelta(minutes=5)]
    if editor_picks is None:
        editor_picks = payload.get("editor_picks", [])
    pins = []
    for pick in editor_picks:
        if not isinstance(pick, dict):
            continue
        if pick.get("until") and (not instant(pick["until"]) or instant(pick["until"]) <= generated):
            continue
        match = next((s for s in active if (pick.get("id") and s.get("id") == pick["id"])
                      or (pick.get("url") and (s.get("url") == pick["url"] or any(
                          isinstance(item, dict) and item.get("url") == pick["url"]
                          for item in s.get("coverage", []))))), None)
        if match and match not in pins:
            pins.append(match)
        if len(pins) == 3:
            break
    from radar.video_script import choose_picks, same_event
    sources = {source["id"]: source for source in payload.get("sources", [])
               if isinstance(source, dict) and source.get("id")}
    promoted = choose_picks(active, sources_map=sources, now_dt=generated,
                            editor_picks=[{"id": story["id"]} for story in pins],
                            require_translation=False)
    # Home uses five hot-score leaders outside the promoted events, not the
    # much larger sections.hot list prepared for other navigation surfaces.
    hot = sorted((story for story in active if (story.get("hot_score") or 0) > 0
                  and story not in promoted and not any(same_event(pick, story) for pick in promoted)),
                 key=lambda story: story["hot_score"], reverse=True)[:5]
    def score(story):
        value = story.get("worth_score")
        if not isinstance(value, (int, float)):
            value = calculate_worth(story, generated).get("score", 0)
        return (value, (instant(story.get("published_at")) or generated).timestamp())
    ranked = sorted(active, key=score, reverse=True)
    out = pins + [s for s in promoted if s not in pins]
    out += [s for s in hot if s not in out]
    out += [s for s in ranked if s not in out]
    out += [s for s in stories if s not in out]
    return out, {id(s) for s in active}


def load_editor_picks(path="site/editor-picks.json"):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("picks", []) if isinstance(data, dict) and isinstance(data.get("picks"), list) else []
    except (OSError, ValueError):
        return []

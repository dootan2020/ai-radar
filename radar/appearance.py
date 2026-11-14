"""When each story first reached readers: `appeared_at`, carried from build to build.

A story's published_at is its source's own time. "Ra mắt ChatGPT Wallet" was posted by OpenAI on 13/11 at 15:00Z and
first shown on hco.news by the build of 14/11 07:27Z; the feed measured "Mới" and ordered "Vừa đăng" by the source
time, so the story read as a day old the moment it arrived (captain, 14/11 15:45: "Sửa luôn").

`appeared_at` is the generated_at of the first published build whose reader snapshot (the newsroom gate,
radar.newsroom_decisions.apply_decisions) held the story. The full collection carries it to the next build through
the published snapshot (data/published-snapshot.json, saved only after Cloudflare accepted the deploy). A story whose
cluster ID changed keeps its old IDs as `aliases`, so it keeps the earliest appearance of any of its names.

Only a continuous record may say "this build is the first to show it". The record is continuous when the prior
snapshot itself carried the field (`appeared_at_since`) and is at most RECORD_GAP_HOURS older than this build. Without
one (the first deploy, a lost cache, a long outage) a visible story without an appearance takes its source time: an
old value that never makes an old story read as new. A story with no readable source time is left without one.
"""

from radar.items import instant
from radar.newsroom_decisions import apply_decisions

RECORD_GAP_HOURS = 48


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _names(story):
    names = [story.get("id")] + list(story.get("aliases") or [])
    return [name for name in names if isinstance(name, str) and name]


def visible_story_ids(payload, decisions):
    """IDs of the stories the reader snapshot shows, by the same gate write_site_snapshot applies."""
    return {story.get("id") for story in apply_decisions(payload, decisions).get("stories", [])}


def continuous_record(now, prior):
    """The prior snapshot's tracking start when it is a continuous appearance record for a build at `now`, else None."""
    if not isinstance(prior, dict):
        return None
    since, before = instant(prior.get("appeared_at_since")), instant(prior.get("generated_at"))
    if since is None or before is None:
        return None
    if not 0 < (now - before).total_seconds() <= RECORD_GAP_HOURS * 3600:
        return None
    return _iso(since)


def stamp_appearance(payload, prior, visible_ids, now=None):
    """Set `appeared_at` on the payload's stories in place; returns the payload.

    `now` is the build's time (radar.pipeline sets generated_at from it); without it, the payload's generated_at.
    """
    generated = instant(now) or instant(payload.get("generated_at"))
    if generated is None:
        raise ValueError("no readable build time")
    known = {}
    stories = prior.get("stories") if isinstance(prior, dict) else None
    for old in stories if isinstance(stories, list) else []:
        if not isinstance(old, dict) or instant(old.get("appeared_at")) is None:
            continue
        at = instant(old["appeared_at"])
        for name in _names(old):
            known[name] = min(at, known.get(name, at))
    since = continuous_record(generated, prior)
    for story in payload.get("stories", []):
        if not isinstance(story, dict):
            continue
        found = [known[name] for name in _names(story) if name in known]
        own = instant(story.get("appeared_at"))
        if own is not None:
            found.append(own)
        if found:
            story["appeared_at"] = _iso(min(found))
        elif story.get("id") in visible_ids:
            source = instant(story.get("published_at"))
            if since is not None:
                story["appeared_at"] = _iso(generated)
            elif source is not None:
                story["appeared_at"] = _iso(source)
            else:
                story.pop("appeared_at", None)
        else:
            story.pop("appeared_at", None)
    payload["appeared_at_since"] = since or _iso(generated)
    return payload

"""When each story first reached readers: `appeared_at`, carried from build to build.

A story's published_at is its source's own time. "Ra mắt ChatGPT Wallet" was posted by OpenAI on 13/11 at 15:00Z and
first shown on hco.news by the build of 14/11 07:27Z; the feed measured "Mới" and ordered "Vừa đăng" by the source
time, so the story read as a day old the moment it arrived (captain, 14/11 15:45: "Sửa luôn").

`appeared_at` is the generated_at of the first published build whose reader snapshot (the newsroom gate,
radar.newsroom_decisions.apply_decisions) held the story. The full collection carries it to the next build through
the published snapshot (data/published-snapshot.json, saved only after Cloudflare accepted the deploy). A story whose
cluster ID changed keeps its old IDs as `aliases`, so it keeps the earliest appearance of any of its names.

The carried collection alone is not a complete record of what Halcyon has shown. It prunes stories after 7 days and
caps the pool at 2,000, and each build rebuilds carried stories whose coverage no longer forms one cluster
(radar.press_relevance.filter_published_stories): the rebuilt pieces are new dicts without the field, and a piece
split off under a new ID does not keep the old one. Measured on 14/11: the 10:25Z build lost the record of 46 names
that way, and stories first shown on 10-12/11 came back stamped with that build's time and led "Vừa đăng" as "Mới".
So the record is read from the prior snapshot as published, before any rebuild, by name and by coverage URL, and from
the story archive (branch radar-story-pages, radar.freshness_watch): the commit that first added stories/<id>.json
is the build that first published that ID, and the archive also lists IDs added before its fetched history began.

Only a continuous record may say "this build is the first to show it". The record is continuous when the prior
snapshot itself carried the field (`appeared_at_since`), is at most RECORD_GAP_HOURS older than this build, and the
story archive was read and holds none of the story's names. Otherwise (the first deploy, a lost cache, a long outage,
an unreadable archive, a name archived before its fetched history) a visible story without an appearance takes its
source time: an old value that never makes an old story read as new. A story with no readable source time is left
without one.
"""

from radar.items import instant
from radar.newsroom_decisions import apply_decisions

RECORD_GAP_HOURS = 48


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _names(story):
    names = [story.get("id")] + list(story.get("aliases") or [])
    return [name for name in names if isinstance(name, str) and name]


def _urls(story):
    coverage = story.get("coverage") if isinstance(story.get("coverage"), list) else []
    urls = [story.get("url")] + [item.get("url") for item in coverage if isinstance(item, dict)]
    return [url for url in urls if isinstance(url, str) and url]


def read_archive(remote=None):
    """IDs the story archive has published: {"additions": {id: first commit time}, "archived": {id, ...}}.

    None when the history cannot be read; the build then stamps no story with its own time.
    """
    from radar import freshness_watch
    try:
        history = freshness_watch.read_history(remote or freshness_watch.default_remote())
    except (freshness_watch.WatchError, OSError, ValueError) as error:
        print(f"Appearance: story archive unavailable ({type(error).__name__}: {error}); no story is stamped now.")
        return None
    return {"additions": history["additions"], "archived": history["archived"]}


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


def stamp_appearance(payload, prior, visible_ids, now=None, archive=None):
    """Set `appeared_at` on the payload's stories in place; returns the payload.

    `prior` is the published snapshot as it was saved, before the build rebuilt any carried story. `archive` is
    read_archive()'s result, or None when the story archive was not read. `now` is the build's time (radar.pipeline
    sets generated_at from it); without it, the payload's generated_at.
    """
    generated = instant(now) or instant(payload.get("generated_at"))
    if generated is None:
        raise ValueError("no readable build time")
    known, known_urls = {}, {}
    stories = prior.get("stories") if isinstance(prior, dict) else None
    for old in stories if isinstance(stories, list) else []:
        if not isinstance(old, dict) or instant(old.get("appeared_at")) is None:
            continue
        at = instant(old["appeared_at"])
        for name in _names(old):
            known[name] = min(at, known.get(name, at))
        for url in _urls(old):
            known_urls[url] = min(at, known_urls.get(url, at))
    archived = set()
    if isinstance(archive, dict):
        for name, value in (archive.get("additions") or {}).items():
            at = instant(value)
            if at is not None:
                known[name] = min(at, known.get(name, at))
        archived = set(archive.get("archived") or ()) | set(archive.get("additions") or {})
    since = continuous_record(generated, prior) if isinstance(archive, dict) else None
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
            shown = [known_urls[url] for url in _urls(story) if url in known_urls]
            source = instant(story.get("published_at"))
            if shown:
                story["appeared_at"] = _iso(min(shown))  # coverage readers already saw under another story
            elif since is not None and not any(name in archived for name in _names(story)):
                story["appeared_at"] = _iso(generated)
            elif source is not None:
                story["appeared_at"] = _iso(source)
            else:
                story.pop("appeared_at", None)
        else:
            story.pop("appeared_at", None)
    payload["appeared_at_since"] = continuous_record(generated, prior) or _iso(generated)
    return payload

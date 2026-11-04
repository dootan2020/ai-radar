"""Find the same event at another outlet when a story's own article cannot be read.

The reporter desk calls this only for stories whose representative article is unreadable.
It returns ranked candidate links; reading them and judging ``same_event`` stay with the
reporter (``_candidate`` and the reporter model). Every source here is free, needs no key or
account, and is reached through its published JSON API after a robots.txt check:

- ``hn-algolia``: Hacker News Search API (https://hn.algolia.com/api). Measured 2026-11-05 on the
  74 approved stories of 02-04/11 whose article was unreadable: the old full-title query (every
  word required, no date filter) gave no readable same-event article for any of them; title words
  as optional words inside the event window gave one for 4 of the 26 Bloomberg articles and 11 of
  the 67 stories still unreadable.

GDELT's DOC 2.0 API (free, open terms) was measured the same day on the 26 Bloomberg articles and
left out: of 26 requests spaced 45 s apart, 18 answered 429, each took 9-22 s, and the six answers
held one unrelated article in total.

A search failure returns no candidates, which is the reporter's behaviour without search.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import timedelta
from urllib.parse import urlsplit

from radar import shadow_collector, transport
from radar.clustering import canonical_url
from radar.items import instant

HN_ALGOLIA = "https://hn.algolia.com/api/v1/search"
# Coverage of one event appears from a day before the story (time zones, early wires) to two after.
WINDOW_BEFORE, WINDOW_AFTER = timedelta(days=1), timedelta(days=2)
HITS_PER_QUERY = 20
# A candidate must share this many distinctive title words with the story before it is read.
MIN_SHARED_WORDS = 2
# Per story: search results read at most, and readable ones kept at most (many top hits are
# outlets that refuse automated readers). Per cycle: search requests sent.
READS_PER_STORY = 6
READABLE_PER_STORY = 3
QUERIES_PER_CYCLE = 24
# The whole search phase of one reporter run may use this long, and never more than this share of
# the time left before the desk deadline, so the reporter model keeps its time when searching is slow.
SEARCH_SECONDS = 300
DEADLINE_SHARE = 0.5
REQUEST_SECONDS = 10

STOP_WORDS = frozenset("""a an the and or of for to in on at by with from as is are was were be been being it its this
that these those into over under after before amid about than then so not no new says say said sees see shows show
makes making make will would could can may might should just more most some all any one two how why what when where
who which while up down out off via per vs plus also amp""".split())
# Headline words that name no actor or object; two stories sharing only these are not the same event.
GENERIC_WORDS = frozenset("""ai deal deals plans plan data report reports year years day days week weeks billion
million trillion percent ceo chief chiefs executive investors company companies firm firms market markets business
news reaches signs tells trims trim taps hits gets get boosts boosted urges steps stokes spark fail fails restricts
debate divided split exceeds soars kicks spend spends sell sells files reveals targets face faces outlook signals look
looks strong record big massive broad global another other nearly""".split())


def title_words(title):
    """Lower-case title words without stop words, in title order, each once.

    Hyphenated words count as their parts ("Mega-IPO" shares "ipo" with "IPO"), and an amount keeps
    its number ("$20B" and "$20 Billion" both give "20").
    """
    words = []
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9&.]*", str(title or "").replace("’", "'")):
        word = raw.strip(".").casefold()
        word = re.sub(r"^(\d+(?:\.\d+)?)(?:k|m|b|bn|t|tn)$", r"\1", word)
        if word and word not in STOP_WORDS and (len(word) >= 3 or word.isdigit()) and word not in words:
            words.append(word)
    return words


def distinctive_words(title):
    return [word for word in title_words(title) if word not in GENERIC_WORDS]


def _publisher(url):
    host = (urlsplit(url or "").hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def rank(story, hits, limit=READS_PER_STORY):
    """Hits worth reading, best first: another publisher, inside the window, sharing enough words."""
    own = set(distinctive_words(story.get("title")))
    published = instant(story.get("published_at"))
    ranked, seen = [], {canonical_url(story.get("url"))}
    for hit in hits:
        url = hit.get("url")
        if not isinstance(url, str) or not url.startswith("https://") or not canonical_url(url):
            continue
        if canonical_url(url) in seen or _publisher(url) == _publisher(story.get("url")):
            continue
        when = instant(hit.get("published_at"))
        if published and when and not published - WINDOW_BEFORE <= when <= published + WINDOW_AFTER:
            continue
        shared = len(own & set(distinctive_words(hit.get("title"))))
        if shared < MIN_SHARED_WORDS:
            continue
        seen.add(canonical_url(url))
        gap = abs((when - published).total_seconds()) if published and when else float("inf")
        ranked.append((-shared / max(1, len(own)), gap, len(ranked), {**hit, "shared_words": shared}))
    return [item for *_, item in sorted(ranked, key=lambda row: row[:3])][:limit]


class SearchBudget:
    """Caps one reporter run's searching by requests and by wall-clock time."""

    def __init__(self, deadline=None, *, queries=QUERIES_PER_CYCLE, seconds=SEARCH_SECONDS, clock=time.monotonic):
        self.clock = clock
        start = clock()
        self.end = start + seconds
        if deadline is not None:
            self.end = min(self.end, start + (deadline - start) * DEADLINE_SHARE)
        self.queries = queries
        self.events = []

    def left(self):
        return self.end - self.clock()

    def take_query(self):
        if self.queries <= 0 or self.left() <= 0:
            return False
        self.queries -= 1
        return True


def hn_algolia_url(story):
    """All distinctive-or-not title words, each optional, so hits rank by how many they match."""
    query = " ".join(title_words(story.get("title"))[:12])
    if not query:
        return None
    params = {"query": query, "optionalWords": query, "tags": "story", "hitsPerPage": HITS_PER_QUERY}
    published = instant(story.get("published_at"))
    if published:
        params["numericFilters"] = (f"created_at_i>={int((published - WINDOW_BEFORE).timestamp())},"
                                    f"created_at_i<={int((published + WINDOW_AFTER).timestamp())}")
    return HN_ALGOLIA + "?" + urllib.parse.urlencode(params)


def parse_hn_algolia(body):
    hits = json.loads(body).get("hits", [])
    return [{"title": hit.get("title") or "", "url": hit.get("url") or "",
             "published_at": hit.get("created_at") or "", "publisher": ""}
            for hit in hits if isinstance(hit, dict) and hit.get("url")]


RUNNERS = {"hn-algolia": (hn_algolia_url, parse_hn_algolia)}


def search(story, runners, budget, robots_cache, fetch=None):
    """Ranked candidates from every configured runner; never raises, never exceeds the budget."""
    hits = []
    for runner in runners:
        build, parse = RUNNERS[runner]
        url = build(story)
        if not url:
            continue
        if not budget.take_query():
            budget.events.append({"runner": runner, "id": story.get("id"), "event": "budget_exhausted"})
            break
        started = budget.clock()
        status = None
        try:
            request = fetch or transport.Fetcher(budget.end, transport=lambda target: transport.read_url(
                target, allow_redirects=False), timeout=REQUEST_SECONDS)
            robots = shadow_collector.check_robots(url, fetch_fn=request, robots_cache=robots_cache)
            if robots["robots_status"] not in (200, 404) or robots["disallowed"]:
                status = "robots"
            else:
                response = request(url)
                status = getattr(response, "status", None)
                if status == 200 and getattr(response, "url", url) == url:
                    found = parse(str(response))
                    hits.extend(found)
                    status = f"200:{len(found)}"
        except (OSError, ValueError, AttributeError, TypeError, TimeoutError) as error:
            status = type(error).__name__
        budget.events.append({"runner": runner, "id": story.get("id"), "status": status,
                              "seconds": round(budget.clock() - started, 2)})
    return rank(story, hits)

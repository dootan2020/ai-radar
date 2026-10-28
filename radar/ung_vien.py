"""News agency: hand the newsroom every fresh, readable, unsummarised story.

Reads the published site snapshot, keeps stories inside a time window that
carry no summary yet, fetches each representative article with the existing
robots- and paywall-aware reader, and writes one JSON file following
`docs/hop-dong-ung-vien.md` (schema_version 1). No model is called.

Offline: `--snapshot <file>` replaces only the snapshot download; articles are
still fetched over the network unless `--articles <fixture.json>` (url ->
{text, reason, fetched_at}) is given too. `--now` anchors the window for replays.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from radar.clustering import canonical_url
from radar.items import instant
from radar.summary_pipeline import fetch_article_result

SCHEMA_VERSION = 1
TEXT_LIMIT = 24_000
MIN_TEXT_CHARS = 600
# A paper page longer than this is the paper itself (arXiv HTML), not its abstract page.
ABSTRACT_MAX_CHARS = 6_000
FETCH_WORKERS = 8

PAPER_HOSTS = ("arxiv.org", "openreview.net", "biorxiv.org", "medrxiv.org", "doi.org",
               "aclanthology.org", "ssrn.com", "papers.ssrn.com", "proceedings.neurips.cc",
               "proceedings.mlr.press")
REGULATOR_HOSTS = ("europa.eu", "gov.uk", "ftc.gov", "nist.gov", "whitehouse.gov", "sec.gov",
                   "fcc.gov", "ico.org.uk", "cnil.fr", "oecd.org", "un.org")
LAB_HOSTS = ("openai.com", "anthropic.com", "deepmind.google", "deepmind.com", "ai.google",
             "blog.google", "research.google", "ai.meta.com", "about.fb.com", "mistral.ai", "x.ai",
             "huggingface.co", "nvidia.com", "microsoft.com", "qwenlm.github.io", "deepseek.com",
             "cohere.com", "stability.ai", "metr.org", "allenai.org", "apple.com")
GROUP_KIND = {"lab": "lab", "press": "outlet", "paper": "paper", "research": "blog",
              "newsletter": "blog", "podcast": "other", "repository": "other", "forum": "other",
              "event": "other"}
# The reader has no truncation flag of its own (it only rejects hard paywalls), so a
# teaser is recognised by the publisher's own cut-off line standing as a paragraph,
# e.g. Substack's "Subscribe for free to continue reading" after an ellipsis.
PARTIAL_LINE = re.compile(
    r"^(?:subscribe(?: for free| now)? to (?:continue|keep) reading.*|continue reading.*|"
    r"keep reading with .*|read (?:the )?(?:full|rest of the) (?:story|article).*|"
    r"this (?:post|article|story) is (?:for|available to|only for) (?:paid )?(?:subscribers|members).*|"
    r"to read this (?:article|story) in full.*)$",
    re.IGNORECASE,
)
PARTIAL_LINE_MAX = 120
# An outlet page this short after cleaning is a teaser or excerpt, not the whole story.
OUTLET_FULL_MIN_CHARS = 1_500
# Page furniture, all in one place. FURNITURE lines are dropped wherever they stand.
FURNITURE = re.compile(
    r"^(?:ad|advertisement|close ad|listen|select voice|select speed|ai-generated voice|1x|"
    r"[\d.]+x(?:[\d.]+x)*|\d\d:\d\d(?:\d\d:\d\d)?|press enter to search.*|\d+-min read.*|"
    r"view pdf(?: html \(experimental\))?|view a pdf of the paper titled .*)$",
    re.IGNORECASE,
)
# A paper page's footer (arXiv) starts here; it and everything after it are dropped.
PAPER_FOOTER = re.compile(r"^(?:subjects:|full-text links:|submission history|about arxivlabs|bibliographic tools)",
                          re.IGNORECASE)
# The publisher's cut-off near the end of the raw page: an audio player or a sign-up wall
# after a few paragraphs (SCMP, Substack) means the reader got an excerpt.
CUTOFF_TAIL = re.compile(r"^(?:select voice|ai-generated voice|subscribe(?: for free| now)? to (?:continue|keep) reading.*|"
                         r"already have an account\? sign in)$", re.IGNORECASE)
CUTOFF_TAIL_LINES = 12
FUTURE_TOLERANCE = timedelta(hours=1)


def _iso(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _host(url):
    host = (urlsplit(url or "").hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _on(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def load_snapshot(source):
    """Read the snapshot from a local file (optionally .gz) or a URL."""
    if source is None or str(source).startswith(("https://", "http://")):
        from phong_bao.cycle import SNAPSHOT_URL, fetch_snapshot
        data = fetch_snapshot(source or SNAPSHOT_URL)
    else:
        path = Path(source)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
    stories = data.get("stories") if isinstance(data, dict) else None
    if not isinstance(stories, list) or any(not isinstance(s, dict) or not s.get("id") for s in stories):
        raise ValueError("snapshot must contain stories with IDs")
    return data


def published_decision_ids(path):
    """IDs the newsroom already published; an unreadable file counts as none."""
    if not path:
        return set()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"ung_vien: decisions ignored: {error}", file=sys.stderr)
        return set()
    rows = data.get("decisions") if isinstance(data, dict) else None
    return {row["id"] for row in rows or [] if isinstance(row, dict) and row.get("id")
            and row.get("decision") == "publish"}


def representative(story):
    """The coverage item behind the story's own URL, else the first one."""
    coverage = [c for c in story.get("coverage") or [] if isinstance(c, dict)]
    target = canonical_url(story.get("url"))
    return next((c for c in coverage if target and canonical_url(c.get("url")) == target),
                coverage[0] if coverage else {})


def source_of(story):
    item = representative(story)
    host = _host(story.get("url"))
    name = item.get("source") or item.get("publisher") or host or "unknown"
    group = item.get("group") or next(iter(story.get("groups") or []), "")
    if _on(host, PAPER_HOSTS) or group == "paper":
        kind = "paper"
    elif _on(host, REGULATOR_HOSTS) or host.endswith(".gov") or ".gov." in host:
        kind = "regulator"
    elif _on(host, LAB_HOSTS) and group in {"lab", "forum", ""}:
        kind = "lab"
    else:
        kind = GROUP_KIND.get(group, "other")
    return {"name": name, "kind": kind}


def _lines(text):
    return [line for line in (" ".join(raw.split()) for raw in (text or "").splitlines()) if line]


def clean_text(text, kind=None):
    """Paragraphs without page furniture; a paper page stops where its footer starts."""
    kept = []
    for line in _lines(text):
        if kind == "paper" and PAPER_FOOTER.match(line):
            break
        if not FURNITURE.match(line):
            kept.append(line)
    return "\n\n".join(kept)


def cut_off_by_publisher(raw_text):
    return any(CUTOFF_TAIL.match(line) for line in _lines(raw_text)[-CUTOFF_TAIL_LINES:])


def cut(text, limit=TEXT_LIMIT):
    """Cut at the last paragraph boundary within the limit; report whether it cut."""
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    boundary = head.rfind("\n\n")
    return (head[:boundary] if boundary > 0 else head).rstrip(), True


def text_source(text, kind, untruncated_chars, cut_off=False):
    """`partial` when the publisher cut the page (cut-off line, player/sign-up tail) or an
    outlet page is under OUTLET_FULL_MIN_CHARS; `abstract` for a short paper page."""
    if kind == "paper" and untruncated_chars < ABSTRACT_MAX_CHARS:
        return "abstract"
    if cut_off or (kind == "outlet" and untruncated_chars < OUTLET_FULL_MIN_CHARS) or any(
            len(line) <= PARTIAL_LINE_MAX and PARTIAL_LINE.match(line) for line in text.split("\n\n")):
        return "partial"
    return "full"


def _coverage(story):
    own = canonical_url(story.get("url"))
    return [{"id": c.get("id"), "title": c.get("title") or "", "url": c.get("url")}
            for c in story.get("coverage") or []
            if isinstance(c, dict) and c.get("id") and canonical_url(c.get("url")) != own]


def _urls(story):
    urls = {canonical_url(c.get("url")) for c in story.get("coverage") or [] if isinstance(c, dict)}
    urls.add(canonical_url(story.get("url")))
    return urls - {None}


def same_event_published(story, published):
    """Summarised stories of the same event: alias, release link or a shared article."""
    ids, aliases, urls = [], set(story.get("aliases") or []), _urls(story)
    for other in published:
        if other["id"] == story["id"]:
            continue
        linked = (other["id"] in aliases or story["id"] in (other.get("aliases") or [])
                  or story.get("related_story_id") == other["id"]
                  or other.get("related_story_id") == story["id"])
        if linked or urls & _urls(other):
            ids.append(other["id"])
    return ids


def _reject(story, reason, detail=""):
    return {"id": story["id"], "title": story.get("title") or "", "url": story.get("url") or "",
            "reason": reason, "detail": detail}


def _summary_detail(story):
    points = story.get("key_points") or []
    origin = story.get("key_points_source")
    return f"key_points x{len(points)}" + (f" ({origin})" if origin else "")


def _fetch(url, robots_cache):
    try:
        text, reason = fetch_article_result({"url": url}, robots_cache)
    except Exception as error:  # the reader must never sink the whole run
        text, reason = "", f"error: {type(error).__name__}"
    return text, reason, datetime.now(timezone.utc)


def network_reader():
    robots_cache = {}
    return lambda url: _fetch(url, robots_cache)


def fixture_reader(path):
    """Offline reader: {url: {text, reason, fetched_at}} captured from a real run."""
    articles = json.loads(Path(path).read_text(encoding="utf-8"))
    articles = articles.get("articles", articles)

    def read(url):
        item = articles.get(url) or {"text": "", "reason": "not_in_fixture"}
        fetched = instant(item.get("fetched_at")) or datetime.now(timezone.utc)
        return item.get("text") or "", item.get("reason") if not item.get("text") else None, fetched
    return read


def _candidate(story, text, fetched_at):
    source = source_of(story)
    cleaned = clean_text(text, source["kind"])
    body, truncated = cut(cleaned)
    row = {
        "id": story["id"],
        "title": story.get("title") or "",
        "title_vi": story.get("editorial_headline_vi") or story.get("title_vi") or story.get("headline_vi") or None,
        "url": story["url"],
        "source": source,
        "published_at": _iso(instant(story["published_at"])),
        "text": body,
        "text_chars": len(body),
        "text_source": text_source(body, source["kind"], len(cleaned), cut_off_by_publisher(text)),
        "text_fetched_at": _iso(fetched_at),
        "coverage": _coverage(story),
        "same_event_published": [],
    }
    if truncated:
        row["text_truncated"] = True
    return row


def build(snapshot, *, hours, limit, now, read, decided=frozenset(), keep_window=False, workers=FETCH_WORKERS):
    stories = snapshot["stories"]
    start = now - timedelta(hours=hours)
    published = [s for s in stories if s.get("key_points") or s["id"] in decided]
    in_window, rejected = [], []
    for story in stories:
        when = instant(story.get("published_at"))
        if when and start <= when <= now + FUTURE_TOLERANCE:
            in_window.append(story)
        elif keep_window:
            rejected.append(_reject(story, "outside_window",
                                    f"published_at {story.get('published_at') or 'missing'}"))

    queue = []
    for story in sorted(in_window, key=lambda s: instant(s["published_at"]), reverse=True):
        siblings = same_event_published(story, published)
        if story.get("key_points"):
            rejected.append(_reject(story, "already_summarised", _summary_detail(story)))
        elif story["id"] in decided:
            rejected.append(_reject(story, "already_summarised", "decisions.json publish"))
        elif siblings and _urls(story) <= set().union(*(_urls(s) for s in published if s["id"] in siblings)):
            rejected.append(_reject(story, "duplicate_published", "same event as " + ", ".join(siblings)))
        elif not canonical_url(story.get("url")):
            rejected.append(_reject(story, "unreadable", "no public URL"))
        elif not story["url"].lower().startswith("https://"):
            rejected.append(_reject(story, "unreadable", "not https"))
        else:
            queue.append((story, siblings))

    candidates = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        position = 0
        while position < len(queue) and len(candidates) < limit:
            # Fetch only as many as could still become candidates, newest first.
            batch = queue[position:position + limit - len(candidates)]
            position += len(batch)
            for (story, siblings), (text, reason, fetched_at) in zip(
                    batch, pool.map(lambda pair: read(pair[0]["url"]), batch)):
                if not text:
                    if reason == "too_short":
                        rejected.append(_reject(story, "too_short", "fetch_article_result: too_short (<300 chars)"))
                    else:
                        rejected.append(_reject(story, "unreadable", f"fetch_article_result: {reason or 'empty'}"))
                    continue
                row = _candidate(story, text, fetched_at)
                if row["text_chars"] < MIN_TEXT_CHARS and row["text_source"] != "abstract":
                    rejected.append(_reject(story, "too_short", f"text_chars {row['text_chars']}"))
                    continue
                row["same_event_published"] = siblings
                candidates.append(row)
    for story, _ in queue[position:]:
        rejected.append(_reject(story, "limit", f"beyond --limit {limit}"))

    candidates.sort(key=lambda row: row["published_at"], reverse=True)
    generated = instant(snapshot.get("generated_at"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "snapshot_generated_at": _iso(generated) if generated else None,
        "window_hours": hours,
        "limit": limit,
        "counts": {"in_window": len(in_window), "candidates": len(candidates), "rejected": len(rejected)},
        "candidates": candidates,
        "rejected": rejected,
    }


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    temporary.replace(path)


def _positive(kind):
    def parse(value):
        number = kind(value)
        if number <= 0:
            raise argparse.ArgumentTypeError("must be positive")
        return number
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m radar.ung_vien", description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=_positive(float), default=8)
    parser.add_argument("--limit", type=_positive(int), default=30)
    parser.add_argument("--out", required=True)
    parser.add_argument("--snapshot", help="local snapshot file or URL (default: the live site)")
    parser.add_argument("--decisions", help="phong-bao/decisions.json; published IDs count as summarised")
    parser.add_argument("--keep-rejected-window", action="store_true",
                        help="also list stories outside the window as outside_window")
    parser.add_argument("--articles", help="offline article fixture {url: {text, reason}} instead of the network")
    parser.add_argument("--now", help="ISO UTC instant to measure the window from (replays and tests)")
    args = parser.parse_args(argv)
    hours = int(args.hours) if float(args.hours).is_integer() else args.hours

    now = instant(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error("--now must be an ISO instant with a timezone")
    try:
        snapshot = load_snapshot(args.snapshot)
    except Exception as error:
        print(f"ung_vien: snapshot unavailable: {error}", file=sys.stderr)
        return 2
    read = fixture_reader(args.articles) if args.articles else network_reader()
    result = build(snapshot, hours=hours, limit=args.limit, now=now, read=read,
                   decided=published_decision_ids(args.decisions), keep_window=args.keep_rejected_window)
    try:
        write_json(args.out, result)
    except OSError as error:
        print(f"ung_vien: cannot write {args.out}: {error}", file=sys.stderr)
        return 3
    counts = result["counts"]
    print(f"in_window={counts['in_window']} candidates={counts['candidates']} rejected={counts['rejected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

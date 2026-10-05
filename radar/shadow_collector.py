"""Shadow Collector for AI-Radar candidate sources.

Fetches candidate sources on a schedule and records what was returned and when,
publishing NOTHING to site/ or pipeline.
Collects three kinds of candidate sources:
1. "fixed feed": Curated RSS/Atom/JSON feeds from labs, blogs, and policy offices.
2. "query": Dynamic Google News RSS queries for people and topics on the watchlist.
3. "signal": Numeric indicators (Wikipedia pageviews, OpenRouter model counts,
   Bluesky trending topics, Google Trends VN).

Boundaries enforced:
- Polite: honours robots.txt, at most one request per candidate per run,
  GDELT spaced at least 6 seconds apart.
- Free: no logins, no API keys, no paid endpoints, no scraping of X or mirrors.
- Offline-safe: supports injected fetch transport for tests without live network calls.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
from urllib.parse import quote_plus, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from radar.classification import classify
from radar.common import clean_text, iso_date, web_url
from radar.feeds import parse_feed
from radar.items import relevant
from radar.transport import MAX_BYTES, USER_AGENT, ResponseText

FETCH_TIMEOUT = 10
GDELT_MIN_INTERVAL = 6.0
VALID_KINDS = ("fixed feed", "query", "signal")


def format_iso_utc(dt=None):
    """Return ISO 8601 UTC timestamp string with Z suffix."""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_google_news_url(query, edition="en", time_window="1d"):
    """Construct a Google News RSS search URL for a watchlist query."""
    q_str = f"{query.strip()} when:{time_window}".strip()
    encoded_q = quote_plus(q_str)
    if edition == "vi":
        hl, gl, ceid = "vi", "VN", "VN:vi"
    else:
        hl, gl, ceid = "en-US", "US", "US:en"
    return f"https://news.google.com/rss/search?q={encoded_q}&hl={hl}&gl={gl}&ceid={ceid}"


def build_wikipedia_pageviews_url(base_url=None, article="Artificial_intelligence", now=None):
    """Build Wikipedia pageviews REST API URL for recent daily views."""
    current = now or datetime.now(timezone.utc)
    # Wikimedia pageviews data is typically available up to yesterday
    from datetime import timedelta
    today_dt = current
    yesterday_dt = current - timedelta(days=1)
    prev_dt = current - timedelta(days=4)
    start_str = prev_dt.strftime("%Y%m%d")
    end_str = yesterday_dt.strftime("%Y%m%d")

    if base_url and "{yesterday}" in base_url and "{today}" in base_url:
        return base_url.replace("{yesterday}", start_str).replace("{today}", end_str)

    return (
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"en.wikipedia.org/all-access/all-agents/{article}/daily/{start_str}/{end_str}"
    )


def default_fetch(url, timeout=FETCH_TIMEOUT):
    """Live HTTP fetch using standard urllib with honest User-Agent and MAX_BYTES limit."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "text/xml;q=0.9,application/rss+xml;q=0.9,application/atom+xml;q=0.9,"
            "application/json;q=0.8,*/*;q=0.7"
        ),
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Response exceeds max bytes limit")
            text = raw.decode(charset, errors="replace")
            res = ResponseText(text, status=status, url=final_url)
            res.content_type = content_type
            res.error = None
            return res
    except urllib.error.HTTPError as err:
        status = err.code
        final_url = err.geturl() if hasattr(err, "geturl") else url
        charset = err.headers.get_content_charset() or "utf-8" if hasattr(err, "headers") else "utf-8"
        try:
            raw = err.read(MAX_BYTES + 1)
            text = raw.decode(charset, errors="replace")
        except Exception:
            text = ""
        res = ResponseText(text, status=status, url=final_url)
        res.content_type = err.headers.get("Content-Type", "") if hasattr(err, "headers") else ""
        res.error = f"HTTP {status}"
        return res
    except Exception as err:
        res = ResponseText("", status=getattr(err, "code", None), url=url)
        res.content_type = ""
        res.error = f"{type(err).__name__}: {err}"
        return res


def check_robots(url, fetch_fn=None, user_agent=USER_AGENT, robots_cache=None):
    """Politely check robots.txt for a URL. Caches robots.txt per origin."""
    if robots_cache is None:
        robots_cache = {}
    fetch = fetch_fn or default_fetch

    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = f"{origin}/robots.txt"

    if origin not in robots_cache:
        try:
            resp = fetch(robots_url)
            status = getattr(resp, "status", 200)
            resp_str = str(resp) if resp is not None else ""
            if status == 200 and resp_str:
                rp = RobotFileParser()
                rp.parse(resp_str.splitlines())
                robots_cache[origin] = (200, rp)
            elif status == 404:
                robots_cache[origin] = (404, None)
            else:
                robots_cache[origin] = (status, None)
        except Exception as err:
            err_status = getattr(err, "code", getattr(err, "http_status", 0)) or "error"
            robots_cache[origin] = (err_status, None)

    status, rp = robots_cache.get(origin, (200, None))
    if rp is not None:
        allowed = rp.can_fetch(user_agent, url)
    else:
        allowed = True

    return {
        "robots_url": robots_url,
        "robots_status": status,
        "allowed": allowed,
        "disallowed": not allowed,
    }


def parse_date_safely(date_val):
    """Parse various date representations to ISO 8601 UTC string."""
    if not date_val:
        return None
    if isinstance(date_val, (int, float)):
        try:
            dt = datetime.fromtimestamp(date_val, tz=timezone.utc)
            return format_iso_utc(dt)
        except Exception:
            return None
    date_str = str(date_val).strip()
    # Try ISO
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return format_iso_utc(dt)
    except Exception:
        pass
    # Try RFC 822 / 2822
    try:
        dt = parsedate_to_datetime(date_str)
        return format_iso_utc(dt)
    except Exception:
        pass
    # Try GDELT seendate format (YYYYMMDDTHHMMSSZ or YYYYMMDDHHMMSS)
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T?(\d{2})(\d{2})(\d{2})Z?$", date_str)
    if m:
        try:
            dt = datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), int(m.group(6)),
                tzinfo=timezone.utc
            )
            return format_iso_utc(dt)
        except Exception:
            pass
    return None


def parse_google_news_rss(text, candidate):
    """Parse Google News RSS XML search output.

    Extracts:
    - title: article title
    - url: original publisher url from <source url="..."> if present; otherwise item link.
      Does not follow redirects over the network (satisfies boundary: 0 extra requests).
    - source_url: attribute from <source url="..."> if present
    - publisher: publisher name from <source> tag or title suffix
    - published_at: ISO 8601 UTC
    """
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        root = ET.fromstring(text)
    except Exception as err:
        return [], None, f"XML parse error: {err}"

    items = []
    ai_count = 0

    for item_elem in root.iter("item"):
        title_elem = item_elem.find("title")
        link_elem = item_elem.find("link")
        pubdate_elem = item_elem.find("pubDate")
        source_elem = item_elem.find("source")

        raw_title = clean_text(title_elem.text if title_elem is not None and title_elem.text else "")
        raw_link = web_url((link_elem.text or "").strip()) if link_elem is not None else ""
        published_at = parse_date_safely(pubdate_elem.text if pubdate_elem is not None else None)

        publisher_name = ""
        source_url = ""
        if source_elem is not None:
            publisher_name = clean_text(source_elem.text or "")
            source_url = web_url(source_elem.attrib.get("url", ""))

        if not publisher_name and " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            publisher_name = parts[-1].strip()

        # Item URL: prefer source_url if valid web URL and avoid Google redirect;
        # otherwise keep raw_link without issuing extra network requests.
        effective_url = source_url or raw_link

        if raw_title and (effective_url or raw_link):
            is_ai = relevant(raw_title)
            if is_ai:
                ai_count += 1
            item_record = {
                "title": raw_title,
                "url": effective_url,
                "publisher": publisher_name or candidate.get("name", "Google News"),
                "published_at": published_at,
            }
            if source_url:
                item_record["source_url"] = source_url
            items.append(item_record)

    numbers = {
        "item_count": len(items),
        "ai_count": ai_count,
        "ai_share": round(ai_count / len(items), 3) if items else 0.0,
    }
    return items, numbers, None


def parse_wikipedia_pageviews(text, candidate):
    """Parse Wikipedia pageviews REST API JSON response.

    Returns signals numbers:
    - views_latest
    - views_previous_day
    - spike_ratio (views_latest / views_previous_day)
    - daily_series
    """
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        data = json.loads(text)
    except Exception as err:
        return [], None, f"JSON parse error: {err}"

    raw_items = data.get("items", []) if isinstance(data, dict) else []
    if not raw_items:
        return [], {"views_latest": 0, "daily_series": []}, None

    series = []
    for entry in raw_items:
        ts = str(entry.get("timestamp", ""))
        views = entry.get("views", 0)
        formatted_date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ts
        series.append({"date": formatted_date, "views": views})

    views_latest = series[-1]["views"] if series else 0
    views_prev = series[-2]["views"] if len(series) >= 2 else views_latest
    spike_ratio = round(views_latest / views_prev, 3) if views_prev > 0 else 1.0

    numbers = {
        "article": candidate.get("article", "Artificial_intelligence"),
        "views_latest": views_latest,
        "views_previous_day": views_prev,
        "spike_ratio": spike_ratio,
        "daily_series": series,
    }
    return [], numbers, None


def parse_google_trends_rss(text, candidate):
    """Parse Google Trends RSS (e.g. trends.google.com/trending/rss?geo=VN)."""
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        root = ET.fromstring(text)
    except Exception as err:
        return [], None, f"XML parse error: {err}"

    items = []
    topics = []
    ai_count = 0

    # Handle XML namespaces often present in Google Trends RSS
    for item_elem in root.iter("item"):
        title_elem = item_elem.find("title")
        link_elem = item_elem.find("link")
        pubdate_elem = item_elem.find("pubDate")
        raw_title = clean_text(title_elem.text if title_elem is not None and title_elem.text else "")
        raw_link = web_url((link_elem.text or "").strip()) if link_elem is not None else ""
        published_at = parse_date_safely(pubdate_elem.text if pubdate_elem is not None else None)

        approx_traffic = ""
        for child in item_elem:
            if child.tag.endswith("approx_traffic") and child.text:
                approx_traffic = child.text.strip()
                break

        if raw_title:
            is_ai = relevant(raw_title)
            if is_ai:
                ai_count += 1
            topics.append({
                "title": raw_title,
                "approx_traffic": approx_traffic,
                "is_ai": is_ai,
            })
            items.append({
                "title": raw_title,
                "url": raw_link or candidate.get("url", ""),
                "publisher": "Google Trends VN",
                "published_at": published_at,
            })

    numbers = {
        "total_trends": len(topics),
        "ai_trend_count": ai_count,
        "topics": topics,
    }
    return items, numbers, None


def parse_openrouter_models(text, candidate):
    """Parse OpenRouter models catalog (openrouter.ai/api/v1/models).

    Returns:
    - items: list of models with id, title, created timestamp, publisher.
    - numbers: total_models, newest_created_timestamp, newest_model_id.
    """
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        data = json.loads(text)
    except Exception as err:
        return [], None, f"JSON parse error: {err}"

    models = data.get("data", []) if isinstance(data, dict) else []
    items = []
    newest_ts = 0
    newest_model_id = ""

    for m in models:
        if not isinstance(m, dict):
            continue
        mid = m.get("id", "")
        name = m.get("name") or mid
        created = m.get("created")
        if created and isinstance(created, (int, float)) and created > newest_ts:
            newest_ts = created
            newest_model_id = mid

        publisher = mid.split("/")[0] if "/" in mid else "OpenRouter"
        published_at = parse_date_safely(created) if created else None

        items.append({
            "title": name,
            "url": f"https://openrouter.ai/models/{mid}" if mid else "https://openrouter.ai/models",
            "publisher": publisher,
            "published_at": published_at,
        })

    numbers = {
        "total_models": len(items),
        "newest_created_timestamp": newest_ts,
        "newest_model_id": newest_model_id,
        "newest_published_at": parse_date_safely(newest_ts) if newest_ts else None,
    }
    return items, numbers, None


def parse_bluesky_trending(text, candidate):
    """Parse Bluesky trending topics (app.bsky.unspecced.getTrendingTopics)."""
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        data = json.loads(text)
    except Exception as err:
        return [], None, f"JSON parse error: {err}"

    raw_topics = data.get("topics", []) if isinstance(data, dict) else []
    topic_list = []
    ai_count = 0

    for t in raw_topics:
        if isinstance(t, dict):
            topic_str = t.get("topic") or t.get("displayName") or ""
            count = t.get("count", 0)
        else:
            topic_str = str(t)
            count = 0
        if topic_str:
            normalized_topic = re.sub(r"([a-z])([A-Z])", r"\1 \2", topic_str.replace("#", " "))
            is_ai = relevant(topic_str) or relevant(normalized_topic)
            if is_ai:
                ai_count += 1
            topic_list.append({
                "topic": topic_str,
                "count": count,
                "is_ai": is_ai,
            })

    numbers = {
        "total_topics": len(topic_list),
        "ai_topic_count": ai_count,
        "topics": topic_list,
    }
    return [], numbers, None


def parse_hn_algolia(text, candidate):
    """Parse Hacker News Algolia Show HN search results."""
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        data = json.loads(text)
    except Exception as err:
        return [], None, f"JSON parse error: {err}"

    hits = data.get("hits", []) if isinstance(data, dict) else []
    items = []
    ai_count = 0

    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = clean_text(hit.get("title") or "")
        url = web_url(hit.get("url") or "")
        object_id = hit.get("objectID")
        hn_url = f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
        target_url = url or hn_url
        author = hit.get("author") or "Hacker News"
        published_at = parse_date_safely(hit.get("created_at") or hit.get("created_at_i"))

        if title and target_url:
            if relevant(title):
                ai_count += 1
            items.append({
                "title": title,
                "url": target_url,
                "publisher": f"HN @{author}",
                "published_at": published_at,
            })

    numbers = {
        "total_hits": len(items),
        "ai_hits_count": ai_count,
    }
    return items, numbers, None


def parse_gdelt_doc(text, candidate):
    """Parse GDELT 2.0 DOC API JSON search results."""
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        data = json.loads(text)
    except Exception as err:
        return [], None, f"JSON parse error: {err}"

    articles = data.get("articles", []) if isinstance(data, dict) else []
    items = []

    for art in articles:
        if not isinstance(art, dict):
            continue
        title = clean_text(art.get("title") or "")
        url = web_url(art.get("url") or "")
        domain = art.get("domain") or art.get("sourcecountry") or "GDELT"
        published_at = parse_date_safely(art.get("seendate"))

        if title and url:
            items.append({
                "title": title,
                "url": url,
                "publisher": domain,
                "published_at": published_at,
            })

    numbers = {
        "article_count": len(items),
    }
    return items, numbers, None




def parse_federal_register(text, candidate):
    """Parse Federal Register API results."""
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        data = json.loads(text)
    except Exception as err:
        return [], None, f"JSON parse error: {err}"

    results = data.get("results", []) if isinstance(data, dict) else []
    items = []

    for raw in results:
        if not isinstance(raw, dict):
            continue
        title = clean_text(raw.get("title") or "")
        url = web_url(raw.get("html_url") or raw.get("pdf_url") or "")
        published_at = parse_date_safely(raw.get("publication_date") or raw.get("effective_on"))
        if title and url:
            items.append({
                "title": title,
                "url": url,
                "publisher": "Federal Register",
                "published_at": published_at,
            })

    numbers = {
        "document_count": len(items),
    }
    return items, numbers, None


def parse_generic_feed(text, candidate):
    """Fallback standard RSS/Atom parser."""
    if not text or not str(text).strip():
        return [], None, "Empty content"
    try:
        raw_items = parse_feed(text, {"id": candidate["id"], "lab": ""})
        if raw_items is not None:
            items = []
            for it in raw_items:
                title = clean_text(it.get("title") or "")
                url = web_url(it.get("url") or "")
                published_at = parse_date_safely(it.get("published_at"))
                if title and url:
                    items.append({
                        "title": title,
                        "url": url,
                        "publisher": candidate.get("name", candidate["id"]),
                        "published_at": published_at,
                    })
            return items, {"item_count": len(items)}, None
    except Exception as err:
        return [], None, f"Feed parse error: {err}"
    return [], None, "Unrecognized feed format"


PARSER_REGISTRY = {
    "google_news_rss": parse_google_news_rss,
    "wikipedia_pageviews": parse_wikipedia_pageviews,
    "google_trends_rss": parse_google_trends_rss,
    "openrouter_models": parse_openrouter_models,
    "bluesky_trending": parse_bluesky_trending,
    "hn_algolia": parse_hn_algolia,
    "gdelt_doc": parse_gdelt_doc,
    "federal_register": parse_federal_register,
    "rss": parse_generic_feed,
    "atom": parse_generic_feed,
    "html": parse_generic_feed,
}


def load_watchlist(path=None):
    """Load watchlist and convert people, topics, and vietnamese queries to candidate definitions."""
    root = Path(__file__).resolve().parent.parent
    file_path = Path(path) if path else root / "data" / "watchlist.json"
    if not file_path.is_file():
        return []

    data = json.loads(file_path.read_text(encoding="utf-8"))
    candidates = []

    # 1. People
    for p in data.get("people", []):
        cand_id = p.get("id") or f"wl-{p['name'].lower().replace(' ', '-')}"
        edition = p.get("edition", "en")
        url = build_google_news_url(p["query"], edition=edition)
        candidates.append({
            "id": cand_id,
            "name": f"{p['name']} (Google News)",
            "kind": "query",
            "url": url,
            "query": p["query"],
            "edition": edition,
            "parser": "google_news_rss",
            "category": "watchlist-people",
            "notes": p.get("notes", ""),
        })

    # 2. Topics
    for t in data.get("topics", []):
        cand_id = t.get("id") or f"wl-{t['name'].lower().replace(' ', '-')}"
        edition = t.get("edition", "en")
        url = build_google_news_url(t["query"], edition=edition)
        candidates.append({
            "id": cand_id,
            "name": f"{t['name']} (Google News)",
            "kind": "query",
            "url": url,
            "query": t["query"],
            "edition": edition,
            "parser": "google_news_rss",
            "category": "watchlist-topics",
            "notes": t.get("notes", ""),
        })

    # 3. Vietnamese
    for v in data.get("vietnamese", []):
        cand_id = v.get("id") or "wl-vietnamese-ai-news"
        edition = v.get("edition", "vi")
        url = build_google_news_url(v["query"], edition=edition)
        candidates.append({
            "id": cand_id,
            "name": f"{v['name']} (Google News VN)",
            "kind": "query",
            "url": url,
            "query": v["query"],
            "edition": edition,
            "parser": "google_news_rss",
            "category": "watchlist-vietnamese",
            "notes": v.get("notes", ""),
        })

    return candidates


def load_shadow_candidates(candidates_path=None, watchlist_path=None, include_watchlist=True):
    """Load full candidate set: healthy fixed feeds, dynamic signals, and watchlist queries."""
    root = Path(__file__).resolve().parent.parent
    file_path = Path(candidates_path) if candidates_path else root / "data" / "shadow-candidates.json"

    candidates = []
    if file_path.is_file():
        data = json.loads(file_path.read_text(encoding="utf-8"))
        for ff in data.get("fixed_feeds", []):
            ff["kind"] = ff.get("kind", "fixed feed")
            candidates.append(ff)
        for sig in data.get("signals", []):
            if sig.get("id") == "wikipedia-ai-pageviews":
                sig["url"] = build_wikipedia_pageviews_url(sig.get("url"))
            candidates.append(sig)

    if include_watchlist:
        wl_candidates = load_watchlist(watchlist_path)
        candidates.extend(wl_candidates)

    return candidates


def collect_candidate(candidate, fetch_fn=None, robots_cache=None, check_robots_policy=True):
    """Collect data from a single candidate source following politeness boundaries.

    Makes at most 1 HTTP request for candidate content (plus cached robots.txt if needed).
    Returns standardized record for scorecard consumption.
    """
    fetch = fetch_fn or default_fetch
    cand_id = candidate["id"]
    cand_name = candidate.get("name", cand_id)
    cand_kind = candidate.get("kind", "fixed feed")
    target_url = candidate["url"]
    req_time_iso = format_iso_utc()

    # Step 1: Check robots.txt politely
    if check_robots_policy:
        robots_info = check_robots(target_url, fetch_fn=fetch, robots_cache=robots_cache)
    else:
        robots_info = {"allowed": True, "disallowed": False}

    if robots_info["disallowed"]:
        return {
            "candidate_id": cand_id,
            "name": cand_name,
            "kind": cand_kind,
            "request_time": req_time_iso,
            "url": target_url,
            "http_status": None,
            "error": "Blocked by robots.txt",
            "item_count": 0,
            "items": [],
            "numbers": None,
        }

    # Step 2: Exactly 1 HTTP request for candidate URL
    try:
        resp = fetch(target_url)
        http_status = getattr(resp, "status", None)
        error = getattr(resp, "error", None)
        resp_text = str(resp) if resp is not None else ""
    except Exception as exc:
        resp = None
        http_status = getattr(exc, "code", getattr(exc, "http_status", None))
        error = f"{type(exc).__name__}: {exc}"
        resp_text = ""

    items = []
    numbers = None

    if (http_status is None or 200 <= http_status < 400) and resp_text:
        parser_name = candidate.get("parser")
        parser_func = PARSER_REGISTRY.get(parser_name)

        if not parser_func:
            # Fallback auto-detection based on content or url
            if "news.google.com" in target_url:
                parser_func = parse_google_news_rss
            elif "wikimedia.org" in target_url:
                parser_func = parse_wikipedia_pageviews
            elif "trends.google.com" in target_url:
                parser_func = parse_google_trends_rss
            elif "openrouter.ai" in target_url:
                parser_func = parse_openrouter_models
            elif "bsky.app" in target_url:
                parser_func = parse_bluesky_trending
            elif "hn.algolia.com" in target_url:
                parser_func = parse_hn_algolia
            elif "gdeltproject.org" in target_url:
                parser_func = parse_gdelt_doc
            elif "federalregister.gov" in target_url:
                parser_func = parse_federal_register
            else:
                parser_func = parse_generic_feed

        parsed_items, parsed_numbers, parse_err = parser_func(resp_text, candidate)
        items = parsed_items or []
        numbers = parsed_numbers
        if parse_err and not error:
            error = parse_err
    elif not error:
        error = f"HTTP {http_status}" if http_status else "No response"

    return {
        "candidate_id": cand_id,
        "name": cand_name,
        "kind": cand_kind,
        "request_time": req_time_iso,
        "url": target_url,
        "http_status": http_status,
        "error": error,
        "item_count": len(items),
        "items": items,
        "numbers": numbers,
    }


def collect_all(candidates, fetch_fn=None, delay=0.25, check_robots_policy=True):
    """Collect all candidate sources sequentially with polite delays and GDELT pacing."""
    robots_cache = {}
    records = []
    last_gdelt_time = 0.0

    started_at = format_iso_utc()
    total = len(candidates)

    for idx, cand in enumerate(candidates, 1):
        target_url = cand.get("url", "")

        # Boundary enforcement: GDELT spaced >= 6 seconds apart
        if "gdeltproject.org" in target_url:
            now_m = time.monotonic()
            elapsed = now_m - last_gdelt_time
            if last_gdelt_time > 0 and elapsed < GDELT_MIN_INTERVAL:
                time.sleep(GDELT_MIN_INTERVAL - elapsed)
            last_gdelt_time = time.monotonic()

        record = collect_candidate(
            cand,
            fetch_fn=fetch_fn,
            robots_cache=robots_cache,
            check_robots_policy=check_robots_policy,
        )
        records.append(record)

        if delay > 0 and idx < total:
            time.sleep(delay)

    completed_at = format_iso_utc()

    run_metadata = {
        "run_id": f"shadow-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "started_at": started_at,
        "completed_at": completed_at,
        "total_candidates": len(records),
        "successful_candidates": sum(1 for r in records if r["http_status"] == 200 and not r["error"]),
        "failed_candidates": sum(1 for r in records if r["error"] or r["http_status"] != 200),
        "total_items_collected": sum(r["item_count"] for r in records),
        "kinds_summary": {
            "fixed feed": sum(1 for r in records if r["kind"] == "fixed feed"),
            "query": sum(1 for r in records if r["kind"] == "query"),
            "signal": sum(1 for r in records if r["kind"] == "signal"),
        },
    }

    return run_metadata, records


def write_jsonl_records(records, output_path):
    """Write records as streaming JSON Lines format."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_json_snapshot(records, run_metadata, output_path):
    """Write complete run metadata and records as single JSON snapshot."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    snapshot = dict(run_metadata)
    snapshot["records"] = records
    p.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")


def render_markdown_summary(records, run_metadata):
    """Generate Markdown summary table for GitHub Actions step summary or inspection."""
    md = []
    md.append("# Báo cáo Shadow Collector (Nguồn bóng AI-Radar)")
    md.append("")
    md.append(f"- **Mã lượt chạy**: `{run_metadata.get('run_id')}`")
    md.append(f"- **Thời gian hoàn thành**: `{run_metadata.get('completed_at')}`")
    md.append(f"- **Tổng số ứng viên**: `{run_metadata.get('total_candidates')}`")
    md.append(f"- **Thành công (HTTP 200)**: `{run_metadata.get('successful_candidates')}`")
    md.append(f"- **Gặp lỗi / không kết nối**: `{run_metadata.get('failed_candidates')}`")
    md.append(f"- **Tổng số bài viết/mục thu thập**: `{run_metadata.get('total_items_collected')}`")
    kinds = run_metadata.get("kinds_summary", {})
    md.append(f"- **Phân loại**: Fixed feed: `{kinds.get('fixed feed', 0)}` | Query: `{kinds.get('query', 0)}` | Signal: `{kinds.get('signal', 0)}`")
    md.append("")

    md.append("## Bảng thống kê chi tiết từng ứng viên")
    md.append("")
    md.append("| ID Ứng viên | Tên | Phân loại (Kind) | HTTP | Số bài | Tín hiệu (Numbers) | Lỗi / Ghi chú |")
    md.append("|---|---|---|---|---|---|---|")

    for r in records:
        status_str = str(r["http_status"]) if r["http_status"] is not None else "-"
        num_str = "-"
        if r.get("numbers"):
            keys_preview = []
            for k, v in list(r["numbers"].items())[:3]:
                if not isinstance(v, (dict, list)):
                    keys_preview.append(f"{k}={v}")
                else:
                    keys_preview.append(f"{k}=({len(v)})")
            num_str = "; ".join(keys_preview) if keys_preview else "có"

        err_str = r.get("error") or "OK"
        if len(err_str) > 40:
            err_str = err_str[:37] + "..."

        md.append(
            f"| `{r['candidate_id']}` | {r['name']} | `{r['kind']}` | "
            f"`{status_str}` | {r['item_count']} | {num_str} | {err_str} |"
        )

    md.append("")
    return "\n".join(md)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="AI-Radar Shadow Collector")
    parser.add_argument("--candidates", default=None, help="Path to shadow-candidates.json")
    parser.add_argument("--watchlist", default=None, help="Path to watchlist.json")
    parser.add_argument("--output-json", default="shadow-records.json", help="Path for JSON snapshot output")
    parser.add_argument("--output-jsonl", default="shadow-records.jsonl", help="Path for JSONL records output")
    parser.add_argument("--output-summary", default="shadow-summary.md", help="Path for Markdown summary")
    parser.add_argument("--summary", action="store_true", help="Append summary to GITHUB_STEP_SUMMARY")
    parser.add_argument("--id", default=None, help="Collect only a single candidate ID")
    parser.add_argument("--kind", default=None, help="Filter by kind: 'fixed feed', 'query', or 'signal'")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between requests in seconds")
    parser.add_argument("--timeout", type=int, default=FETCH_TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument("--no-robots", action="store_true", help="Skip robots.txt check")

    args = parser.parse_args(argv)

    candidates = load_shadow_candidates(
        candidates_path=args.candidates,
        watchlist_path=args.watchlist,
    )

    if args.id:
        target_id = args.id.strip()
        matched = [c for c in candidates if c["id"] == target_id]
        if not matched:
            sys.stderr.write(f"Error: Candidate ID '{args.id}' not found.\n")
            return 1
        candidates = matched

    if args.kind:
        target_kind = args.kind.strip().lower()
        if target_kind not in VALID_KINDS:
            sys.stderr.write(
                f"Error: Unknown kind '{args.kind}'. Valid kinds are: {', '.join(repr(k) for k in VALID_KINDS)}.\n"
            )
            return 1
        matched_kind = [c for c in candidates if c.get("kind", "").lower() == target_kind]
        if not matched_kind:
            sys.stderr.write(f"Error: No candidates found with kind '{args.kind}'.\n")
            return 1
        candidates = matched_kind

    print(f"Shadow Collector: collecting from {len(candidates)} candidates...")
    metadata, records = collect_all(
        candidates,
        delay=args.delay,
        check_robots_policy=not args.no_robots,
    )

    if args.output_json:
        write_json_snapshot(records, metadata, args.output_json)
        print(f"Wrote snapshot JSON to {args.output_json}")

    if args.output_jsonl:
        write_jsonl_records(records, args.output_jsonl)
        print(f"Wrote stream JSONL to {args.output_jsonl}")

    summary_md = render_markdown_summary(records, metadata)
    if args.output_summary:
        Path(args.output_summary).write_text(summary_md, encoding="utf-8")
        print(f"Wrote summary Markdown to {args.output_summary}")

    if args.summary:
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(summary_md)
                f.write("\n")
            print("Appended summary to GITHUB_STEP_SUMMARY")

    print(f"Collection complete: {metadata['total_candidates']} candidates, {metadata['total_items_collected']} items.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

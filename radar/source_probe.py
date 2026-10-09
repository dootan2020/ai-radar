"""Probe candidate sources to verify availability, feeds, robots policy, freshness, and AI relevance.

Read-only, polite, offline-testable probe for evaluating candidate sources before inclusion in ai-radar.
Enforces boundaries:
- One request per candidate (+ robots.txt + at most one autodiscovered feed).
- Honest User-Agent from radar.transport.
- Reuses existing fetch, feed parsing, and AI classification logic.
- Offline-safe: supports injected fetch transport for unit tests without live network calls.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from radar.classification import classify
from radar.common import clean_text, iso_date, web_url
from radar.feeds import _local, parse_feed
from radar.items import relevant
from radar.transport import MAX_BYTES, USER_AGENT, ResponseText, SafeRedirectHandler

FETCH_TIMEOUT = 10


class AlternateFeedParser(HTMLParser):
    """Extract <link rel="alternate" ...> feed autodiscovery tags from HTML."""

    FEED_TYPES = {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
        "application/json",
        "application/feed+json",
    }

    def __init__(self):
        super().__init__()
        self.feed_links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "link":
            attr_dict = {k.lower(): v for k, v in attrs if v is not None}
            rel = attr_dict.get("rel", "").lower()
            typ = attr_dict.get("type", "").lower()
            href = attr_dict.get("href", "")
            rels = set(rel.split())
            if "alternate" in rels and typ in self.FEED_TYPES and href:
                self.feed_links.append({
                    "href": href,
                    "type": typ,
                    "title": attr_dict.get("title", ""),
                })


def normalize_url(url):
    """Normalize URL for comparison and deduplication."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if ":" in netloc:
            host, port = netloc.split(":", 1)
            if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
                netloc = host
        path = parts.path.rstrip("/")
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    except Exception:
        return str(url).strip()


def collect_existing_sources(now=None):
    """Gather all sources already registered across radar/ modules."""
    existing = []
    seen = set()

    def add(source_id, name, url, module):
        if not source_id:
            return
        key = (source_id, url)
        if key in seen:
            return
        seen.add(key)
        existing.append({
            "id": source_id,
            "name": name or source_id,
            "url": url or "",
            "normalized_url": normalize_url(url),
            "module": module,
        })

    # 1. radar.feeds.SOURCES
    try:
        from radar import feeds
        for s in getattr(feeds, "SOURCES", []):
            add(s.get("id"), s.get("name"), s.get("url"), "radar.feeds")
    except Exception:
        pass

    # 2. radar.catalog.sources
    try:
        from radar import catalog
        current_time = now or datetime.now(timezone.utc)
        for s in catalog.sources(current_time):
            add(s.get("id"), s.get("name"), s.get("url"), "radar.catalog")
    except Exception:
        pass

    # 3. radar.tool_sources.SOURCES
    try:
        from radar import tool_sources
        for s in getattr(tool_sources, "SOURCES", []):
            add(s.get("id"), s.get("name"), s.get("url"), "radar.tool_sources")
    except Exception:
        pass

    # 4. radar.youtube.SOURCES
    try:
        from radar import youtube
        for s in getattr(youtube, "SOURCES", []):
            add(s.get("id"), s.get("name"), s.get("url"), "radar.youtube")
    except Exception:
        pass

    return existing


def check_duplicate(candidate, existing_sources, autodiscovered_feed_url=None):
    """Check if candidate matches an existing radar source."""
    candidate_id = candidate.get("id", "")
    candidate_url = candidate.get("url", "")
    norm_url = normalize_url(candidate_url)
    norm_auto = normalize_url(autodiscovered_feed_url) if autodiscovered_feed_url else ""

    # Check exact URL match
    for s in existing_sources:
        if norm_url and s["normalized_url"] == norm_url:
            return {
                "is_duplicate": True,
                "match_type": "url",
                "existing_id": s["id"],
                "existing_name": s["name"],
                "existing_url": s["url"],
                "existing_module": s["module"],
            }

    # Check autodiscovered feed URL match
    if norm_auto:
        for s in existing_sources:
            if s["normalized_url"] == norm_auto:
                return {
                    "is_duplicate": True,
                    "match_type": "feed_url",
                    "existing_id": s["id"],
                    "existing_name": s["name"],
                    "existing_url": s["url"],
                    "existing_module": s["module"],
                }

    # Check exact ID match
    for s in existing_sources:
        if candidate_id and s["id"] == candidate_id:
            return {
                "is_duplicate": True,
                "match_type": "id",
                "existing_id": s["id"],
                "existing_name": s["name"],
                "existing_url": s["url"],
                "existing_module": s["module"],
            }

    return {
        "is_duplicate": False,
        "match_type": None,
        "existing_id": None,
        "existing_name": None,
        "existing_url": None,
        "existing_module": None,
    }


def default_fetch(url, timeout=FETCH_TIMEOUT):
    """Live HTTP fetch using standard urllib with honest User-Agent and max bytes limit."""
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
        res = ResponseText("", status=getattr(err, "code", 0), url=url)
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
                # No robots.txt -> crawl allowed
                robots_cache[origin] = (404, None)
            else:
                robots_cache[origin] = (status, None)
        except Exception as err:
            err_status = getattr(err, "code", getattr(err, "http_status", 0)) or "error"
            robots_cache[origin] = (err_status, None)

    status, rp = robots_cache[origin]
    if rp is not None:
        allowed = rp.can_fetch(user_agent, url)
    else:
        # Standard web protocol: if 404 or unreachable, default to allowed
        allowed = True

    return {
        "robots_url": robots_url,
        "robots_status": status,
        "allowed": allowed,
        "disallowed": not allowed,
    }


def find_autodiscovered_feeds(html_text, base_url):
    """Parse HTML and return list of absolute alternate feed URLs."""
    if not html_text:
        return []
    parser = AlternateFeedParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    results = []
    for link in parser.feed_links:
        href = link.get("href", "").strip()
        if href:
            abs_url = urljoin(base_url, href)
            results.append({
                "url": abs_url,
                "type": link.get("type", ""),
                "title": link.get("title", ""),
            })
    return results


def parse_json_feed(text, candidate):
    """Parse JSON feeds or public JSON APIs like Federal Register into normalized items."""
    try:
        data = json.loads(text)
    except Exception:
        return None

    items = []
    if isinstance(data, dict) and isinstance(data.get("feed"), list) and candidate.get("id", "").startswith("bluesky-"):
        for row in data["feed"]:
            post = row.get("post", {}) if isinstance(row, dict) else {}
            record = post.get("record", {}) if isinstance(post, dict) else {}
            author = post.get("author", {})
            handle = candidate.get("url", "").split("actor=", 1)[-1].split("&", 1)[0]
            rkey = str(post.get("uri", "")).rsplit("/", 1)[-1]
            title = clean_text(record.get("text") or "")
            if title and rkey and author.get("handle") == handle:
                items.append({"title": title, "url": "https://bsky.app/profile/" + handle + "/post/" + rkey,
                              "published_at": iso_date(record.get("createdAt") or post.get("indexedAt")),
                              "summary": title, "kind": classify(title, title)})
        return items

    # 1. Standard JSON Feed (https://jsonfeed.org/version/1.1)
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        for raw in data["items"]:
            if not isinstance(raw, dict):
                continue
            title = clean_text(raw.get("title") or "")
            url = web_url((raw.get("url") or raw.get("id") or "").strip())
            date = iso_date(raw.get("date_published") or raw.get("date_modified"))
            summary = clean_text(raw.get("summary") or raw.get("content_text") or "")
            if title and url:
                items.append({
                    "title": title,
                    "url": url,
                    "published_at": date,
                    "summary": summary,
                    "kind": classify(title, summary),
                })
        return items

    # 2. Federal Register API (results array)
    if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
        for raw in data["results"]:
            if not isinstance(raw, dict):
                continue
            title = clean_text(raw.get("title") or "")
            url = web_url((raw.get("html_url") or raw.get("pdf_url") or "").strip())
            date = iso_date(raw.get("publication_date") or raw.get("effective_on"))
            summary = clean_text(raw.get("abstract") or raw.get("description") or "")
            if title and url:
                items.append({
                    "title": title,
                    "url": url,
                    "published_at": date,
                    "summary": summary,
                    "kind": classify(title, summary),
                })
        return items

    return None


def extract_items_from_text(text, candidate):
    """Attempt to parse text as RSS/Atom XML feed or JSON feed."""
    if not text or not str(text).strip():
        return None, "Empty content"

    # Try RSS/Atom XML first
    try:
        items = parse_feed(text, {"id": candidate["id"], "lab": ""})
        if items is not None:
            return items, None
    except Exception as xml_err:
        pass

    # Try JSON feed
    json_items = parse_json_feed(text, candidate)
    if json_items is not None:
        return json_items, None

    return None, "Not a recognized feed format"


def probe_candidate(candidate, fetch=None, check_robots_policy=True, robots_cache=None, existing_sources=None):
    """Probe a single candidate source following politeness boundaries.

    Makes:
    1. Robots.txt check (at most 1 request per domain, cached)
    2. Primary candidate URL request (1 request)
    3. Autodiscovered feed request (at most 1 request if primary returned HTML with alternate links)
    Total live requests: 1 candidate request + robots.txt + at most 1 feed request.
    """
    fetch_fn = fetch or default_fetch
    cand_id = candidate["id"]
    cand_url = candidate["url"]
    cand_name = candidate.get("name", cand_id)

    # Step 1: Check robots.txt
    if check_robots_policy:
        robots_info = check_robots(cand_url, fetch_fn=fetch_fn, robots_cache=robots_cache)
    else:
        robots_info = {"allowed": True, "disallowed": False, "robots_status": "skipped", "robots_url": ""}

    feed_robots_disallowed = False

    if robots_info["disallowed"]:
        http_status = None
        final_url = cand_url
        reachable = False
        feed_found = False
        feed_type = None
        feed_url = None
        items = []
        feed_error = None
        autodiscovered_links = []
        error = "Blocked by robots.txt"
    else:
        # Step 2: Request 1 — Fetch candidate URL
        resp = fetch_fn(cand_url)
        http_status = getattr(resp, "status", 200)
        final_url = getattr(resp, "url", cand_url)
        resp_text = str(resp) if resp is not None else ""
        error = getattr(resp, "error", None)

        reachable = (200 <= http_status < 400) if isinstance(http_status, int) and http_status > 0 else False

        feed_found = False
        feed_type = None
        feed_url = None
        items = []
        feed_error = None
        autodiscovered_links = []

        if reachable and resp_text:
            # Check if direct feed (XML or JSON)
            parsed_items, parse_err = extract_items_from_text(resp_text, candidate)
            if parsed_items is not None:
                feed_found = True
                feed_type = "direct"
                feed_url = final_url
                items = parsed_items
            else:
                # Check for autodiscovery in HTML
                links = find_autodiscovered_feeds(resp_text, final_url)
                autodiscovered_links = links
                if links:
                    target_feed_url = links[0]["url"]
                    if check_robots_policy:
                        feed_robots = check_robots(target_feed_url, fetch_fn=fetch_fn, robots_cache=robots_cache)
                    else:
                        feed_robots = {"allowed": True, "disallowed": False, "robots_status": "skipped", "robots_url": ""}

                    if feed_robots["disallowed"]:
                        feed_robots_disallowed = True
                        feed_error = "Autodiscovered feed blocked by robots.txt"
                    else:
                        # Step 3: Request 2 — At most one autodiscovered feed request
                        feed_resp = fetch_fn(target_feed_url)
                        feed_status = getattr(feed_resp, "status", 200)
                        feed_text = str(feed_resp) if feed_resp is not None else ""
                        if 200 <= feed_status < 400 and feed_text:
                            parsed_auto, auto_err = extract_items_from_text(feed_text, candidate)
                            if parsed_auto is not None:
                                feed_found = True
                                feed_type = "autodiscovered"
                                feed_url = target_feed_url
                                items = parsed_auto
                            else:
                                feed_error = f"Autodiscovered feed parse failed: {auto_err}"
                        else:
                            feed_error = f"Autodiscovered feed returned HTTP {feed_status}"
                else:
                    feed_error = "No alternate feed links found in HTML"

    # Step 4: Check duplication against existing radar inventory
    if existing_sources is None:
        existing_sources = collect_existing_sources()
    dup = check_duplicate(candidate, existing_sources, autodiscovered_feed_url=feed_url)

    # Step 5: Calculate metrics
    item_count = len(items)
    newest_item_date = None
    if items:
        dates = [it["published_at"] for it in items if it.get("published_at")]
        if dates:
            newest_item_date = max(dates)
        elif items[0].get("published_at"):
            newest_item_date = items[0]["published_at"]

    ai_count = 0
    kinds = {"model": 0, "research": 0, "product": 0, "other": 0}
    for item in items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        if relevant(title):
            ai_count += 1
        kind = classify(title, summary)
        kinds[kind] = kinds.get(kind, 0) + 1

    ai_share = (ai_count / item_count) if item_count > 0 else 0.0

    # Step 6: Derive note and actionable recommendation
    notes_list = []
    if dup["is_duplicate"]:
        notes_list.append(f"Trùng lặp với nguồn đã có '{dup['existing_id']}' ({dup['existing_module']}) qua {dup['match_type']}")
    if robots_info["disallowed"]:
        notes_list.append("robots.txt chặn đường dẫn")
    elif feed_robots_disallowed:
        notes_list.append("robots.txt chặn feed")
    if not reachable and not robots_info["disallowed"]:
        notes_list.append(f"Không thể truy cập (HTTP {http_status}{f': {error}' if error else ''})")
    elif not feed_found and not robots_info["disallowed"]:
        if feed_robots_disallowed:
            notes_list.append("Feed tự động phát hiện bị robots.txt chặn")
        elif autodiscovered_links:
            notes_list.append(f"Có link feed nhưng tải/đọc không thành công ({feed_error})")
        else:
            notes_list.append("HTML hợp lệ nhưng không tìm thấy feed RSS/Atom")
    elif feed_found:
        notes_list.append(f"Tìm thấy feed ({feed_type}): {item_count} bài, {ai_count} bài AI ({ai_share*100:.0f}%)")

    recommendation = derive_recommendation(
        reachable=reachable,
        http_status=http_status,
        feed_found=feed_found,
        feed_type=feed_type,
        is_duplicate=dup["is_duplicate"],
        duplicate_id=dup["existing_id"],
        robots_disallowed=robots_info["disallowed"],
        item_count=item_count,
        ai_share=ai_share,
        feed_robots_disallowed=feed_robots_disallowed,
    )

    return {
        "id": cand_id,
        "name": cand_name,
        "circle_id": candidate.get("circle_id", ""),
        "circle_name": candidate.get("circle_name", ""),
        "proposed_label": candidate.get("label", ""),
        "url": cand_url,
        "final_url": final_url,
        "http_status": http_status,
        "reachable": reachable,
        "robots_allowed": robots_info["allowed"],
        "robots_disallowed": robots_info["disallowed"],
        "robots_status": robots_info["robots_status"],
        "feed_robots_disallowed": feed_robots_disallowed,
        "feed_found": feed_found,
        "feed_type": feed_type,
        "feed_url": feed_url,
        "item_count": item_count,
        "newest_item_date": newest_item_date,
        "ai_share": ai_share,
        "ai_count": ai_count,
        "kinds": kinds,
        "is_duplicate": dup["is_duplicate"],
        "duplicate_of": dup["existing_id"],
        "duplicate_match": dup["match_type"],
        "notes": "; ".join(notes_list),
        "recommendation": recommendation,
        "error": error or feed_error,
    }


def derive_recommendation(
    reachable,
    http_status,
    feed_found,
    feed_type,
    is_duplicate,
    duplicate_id,
    robots_disallowed,
    item_count,
    ai_share,
    feed_robots_disallowed=False,
):
    """Synthesize a clear verdict for the owner."""
    if is_duplicate:
        return f"BỎ QUA: Trùng nguồn đã có ({duplicate_id})"
    if robots_disallowed:
        return "CẨN TRỌNG: robots.txt cấm truy cập"
    if feed_robots_disallowed:
        return "CẨN TRỌNG: robots.txt cấm feed"
    if not reachable:
        if http_status == 403:
            return "CHẶN: HTTP 403 (Cloudflare/Substack chặn IP GitHub)"
        if http_status == 404:
            return "LỖI: HTTP 404 Not Found (URL đoán sai)"
        return f"LỖI: Không truy cập được (HTTP {http_status})"
    if not feed_found:
        return "CẦN TÌM FEED: Trang sống nhưng không có feed tự động"
    if item_count == 0:
        return "CẢNH BÁO: Feed rỗng"
    if ai_share == 0.0:
        return "CẨN TRỌNG: 0% bài về AI (cần bộ lọc filter_ai chặt)"
    if ai_share < 0.3:
        return f"DÙNG KÈM LỌC: Tỷ lệ AI thấp ({ai_share*100:.0f}%), cần filter_ai"
    return "SẴN SÀNG: Feed hoạt động tốt, tỷ lệ AI cao"


def probe_all(candidates, fetch=None, check_robots_policy=True, delay=0.2):
    """Probe all candidate sources sequentially with polite delay."""
    robots_cache = {}
    existing_sources = collect_existing_sources()
    results = []
    total = len(candidates)

    for idx, cand in enumerate(candidates, 1):
        res = probe_candidate(
            cand,
            fetch=fetch,
            check_robots_policy=check_robots_policy,
            robots_cache=robots_cache,
            existing_sources=existing_sources,
        )
        results.append(res)
        if delay > 0 and idx < total:
            time.sleep(delay)

    return results


def render_markdown_report(results, generated_at=None):
    """Generate Markdown report and comparison table from probe results."""
    now_str = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total = len(results)
    reachable_count = sum(1 for r in results if r["reachable"])
    feed_count = sum(1 for r in results if r["feed_found"])
    duplicate_count = sum(1 for r in results if r["is_duplicate"])
    robots_disallowed_count = sum(1 for r in results if r["robots_disallowed"] or r.get("feed_robots_disallowed"))
    ready_count = sum(1 for r in results if r["recommendation"].startswith("SẴN SÀNG"))

    md = []
    md.append("# Báo cáo kiểm tra nguồn ứng viên (Candidate Sources Probe)")
    md.append("")
    md.append(f"- **Thời gian chạy**: `{now_str}`")
    md.append(f"- **Tổng số nguồn kiểm tra**: `{total}`")
    md.append(f"- **Khả dụng (Reachable HTTP 200-399)**: `{reachable_count}/{total}`")
    md.append(f"- **Tìm thấy feed hợp lệ (RSS/Atom/JSON)**: `{feed_count}/{total}`")
    md.append(f"- **Trùng lặp với nguồn radar hiện có**: `{duplicate_count}/{total}`")
    md.append(f"- **Bị robots.txt chặn**: `{robots_disallowed_count}/{total}`")
    md.append(f"- **Sẵn sàng đưa vào (chưa trùng, có feed, AI cao)**: `{ready_count}/{total}`")
    md.append("")

    # Summary table
    md.append("## Bảng kết quả tổng hợp")
    md.append("")
    md.append("| Circle | ID | Nguồn | HTTP | Robots | Feed | Số bài | Mới nhất | Tỷ lệ AI | Trùng | Nhãn | Đánh giá |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    for r in results:
        circle_short = r.get("circle_id", "").replace("circle-", "C")
        if r["robots_disallowed"]:
            http_badge = "-"
            robots_badge = "CẤM"
        elif r.get("feed_robots_disallowed"):
            http_badge = f"{r['http_status']}" if r["http_status"] else "ERR"
            robots_badge = "Feed cấm"
        else:
            http_badge = f"{r['http_status']}" if r["http_status"] else "ERR"
            robots_badge = "OK"

        if r["feed_found"]:
            feed_badge = r["feed_type"]
        elif r.get("feed_robots_disallowed"):
            feed_badge = "CẤM (robots)"
        else:
            feed_badge = "Không"

        item_cnt = str(r["item_count"]) if r["feed_found"] else "-"
        newest = (r["newest_item_date"] or "")[:10] if r["newest_item_date"] else "-"
        ai_pct = f"{r['ai_share']*100:.0f}%" if r["feed_found"] else "-"
        dup_str = f"Trùng: {r['duplicate_of']}" if r["is_duplicate"] else "Không"
        label = r.get("proposed_label", "")
        recom = r.get("recommendation", "")

        md.append(
            f"| {circle_short} | `{r['id']}` | [{r['name']}]({r['url']}) | {http_badge} | "
            f"{robots_badge} | {feed_badge} | {item_cnt} | {newest} | {ai_pct} | "
            f"{dup_str} | `{label}` | {recom} |"
        )

    md.append("")

    # Detailed section by circle
    circles = {}
    for r in results:
        cname = r.get("circle_name") or r.get("circle_id") or "Khác"
        circles.setdefault(cname, []).append(r)

    md.append("## Chi tiết theo từng Circle")
    md.append("")
    for cname, items in circles.items():
        md.append(f"### {cname}")
        md.append("")
        for it in items:
            md.append(f"#### `{it['id']}`: {it['name']}")
            md.append(f"- **URL đề xuất**: `{it['url']}`")
            if it.get("final_url") and it["final_url"] != it["url"]:
                md.append(f"- **URL chuyển hướng**: `{it['final_url']}`")
            if it["robots_disallowed"]:
                md.append(f"- **HTTP status**: `Không có (bị robots.txt chặn)` | **Robots.txt**: `Disallowed`")
            elif it.get("feed_robots_disallowed"):
                md.append(f"- **HTTP status**: `{it['http_status']}` | **Robots.txt**: `Candidate allowed, feed disallowed`")
            else:
                md.append(f"- **HTTP status**: `{it['http_status']}` | **Robots.txt**: `{'Disallowed' if it['robots_disallowed'] else 'Allowed'}`")
            if it["feed_found"]:
                md.append(f"- **Feed URL**: `{it['feed_url']}` ({it['feed_type']})")
                md.append(f"- **Số lượng bài**: `{it['item_count']}` | **Bài mới nhất**: `{it['newest_item_date']}`")
                md.append(f"- **Tỷ lệ AI**: `{it['ai_count']}/{it['item_count']} ({it['ai_share']*100:.1f}%)`")
                kind_str = ", ".join(f"{k}: {v}" for k, v in it.get("kinds", {}).items() if v > 0)
                md.append(f"- **Phân loại kind**: `{kind_str or 'không có'}`")
            elif it.get("feed_robots_disallowed"):
                md.append("- **Feed**: Bị robots.txt chặn (không gửi HTTP request)")
            else:
                md.append("- **Feed**: Không tìm thấy feed hợp lệ")
            if it["is_duplicate"]:
                md.append(f"- **Trùng lặp**: Trùng nguồn `{it['duplicate_of']}` (khớp theo {it['duplicate_match']})")
            md.append(f"- **Nhãn đề xuất**: `{it['proposed_label']}`")
            md.append(f"- **Đánh giá**: **{it['recommendation']}**")
            if it.get("notes"):
                md.append(f"- **Ghi chú**: {it['notes']}")
            md.append("")

    return "\n".join(md)


def load_candidates(path=None):
    """Load candidates list from JSON file."""
    root = Path(__file__).resolve().parent.parent
    data_path = Path(path) if path else root / "data" / "candidate-sources.json"
    if not data_path.is_file():
        raise FileNotFoundError(f"Candidate file not found: {data_path}")
    return json.loads(data_path.read_text(encoding="utf-8"))


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Probe candidate sources for ai-radar")
    parser.add_argument("--candidates", default=None, help="Path to candidate-sources.json")
    parser.add_argument("--output", default=None, help="Output markdown file path")
    parser.add_argument("--json-output", default=None, help="Output JSON file path")
    parser.add_argument("--summary", action="store_true", help="Write to GITHUB_STEP_SUMMARY if available")
    parser.add_argument("--id", default=None, help="Probe only a single candidate ID")
    parser.add_argument("--timeout", type=int, default=FETCH_TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests in seconds")

    args = parser.parse_args(argv)

    candidates = load_candidates(args.candidates)
    if args.id:
        target_id = args.id.strip()
        matched = [c for c in candidates if c["id"] == target_id]
        if not matched:
            source_file = args.candidates or "data/candidate-sources.json"
            sys.stderr.write(f"Error: Candidate ID '{args.id}' not found in {source_file}.\n")
            return 1
        candidates = matched

    print(f"Starting probe for {len(candidates)} candidate sources...")
    results = probe_all(candidates, delay=args.delay)
    report_md = render_markdown_report(results)

    # Print summary to stdout
    print(f"\nProbe complete: {len(results)} sources checked.")
    reachable = sum(1 for r in results if r["reachable"])
    feed_found = sum(1 for r in results if r["feed_found"])
    duplicates = sum(1 for r in results if r["is_duplicate"])
    print(f"  Reachable: {reachable}/{len(results)}")
    print(f"  Feeds found: {feed_found}/{len(results)}")
    print(f"  Duplicates: {duplicates}/{len(results)}")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        print(f"Report written to {out_path}")

    if args.json_output:
        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON data written to {json_path}")

    if args.summary:
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(report_md)
                f.write("\n")
            print("Summary appended to GITHUB_STEP_SUMMARY")

    return 0


if __name__ == "__main__":
    sys.exit(main())

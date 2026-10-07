"""Collector and parser for official Claude announcements and articles on claude.com.

Extracts dated product announcements and engineering articles from claude.com,
filtering out non-news content (evergreen guides, webinars, video archives,
static program/marketplace pages, and localized duplicates).
"""

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from radar.classification import classify
from radar.common import clean_text, iso_date, stable_id, web_url
from radar.items import observation

LOCALES = {"de", "ja", "fr", "es", "it", "ko", "zh", "pt"}
DEFAULT_SOURCE = {
    "id": "anthropic-claude",
    "name": "Anthropic Claude Blog",
    "lab": "anthropic",
    "group": "lab",
    "url": "https://claude.com/resources/articles",
}


def is_claude_news_url(url):
    """Check if a URL is an English news/announcement article under /resources/articles/."""
    if not url:
        return False
    path = urlsplit(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return False
    if parts[0] in LOCALES:
        return False
    # Only individual articles under /resources/articles/<slug>
    if len(parts) >= 3 and parts[0] == "resources" and parts[1] == "articles":
        return True
    return False


def parse_claude_date(val):
    """Parse date from card text, JSON-LD, or meta tags into UTC ISO string with midnight."""
    if not val:
        return None
    val = str(val).strip()
    # Check YYYY-MM-DD or full ISO timestamp
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:T.*)?$", val)
    if m:
        if "T" in val:
            parsed = iso_date(val)
            if parsed:
                return parsed
        return m.group(1) + "T00:00:00Z"
    # Month day, year (e.g. Oct 6, 2026 or October 6, 2026)
    for fmt in ("%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y"):
        try:
            dt = datetime.strptime(re.sub(r"\s+", " ", val), fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        except (ValueError, TypeError):
            pass
    return iso_date(val, default_tz="UTC")


class _ClaudeCardParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.in_card = False
        self.card_data = {}
        self.in_title = False
        self.in_excerpt = False
        self.in_meta = False
        self.in_type = False

    def handle_starttag(self, tag, attrs):
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}
        cls = attr_dict.get("class", "").lower()
        if tag == "a" and "card" in cls and attr_dict.get("href"):
            self.in_card = True
            self.card_data = {
                "href": attr_dict.get("href"),
                "title": "",
                "excerpt": "",
                "meta": "",
                "type": "",
            }
        if self.in_card:
            if "title" in cls:
                self.in_title = True
            elif "excerpt" in cls:
                self.in_excerpt = True
            elif "meta" in cls:
                self.in_meta = True
            elif "type" in cls:
                self.in_type = True

    def handle_endtag(self, tag):
        if tag == "a" and self.in_card:
            self.in_card = False
            if self.card_data.get("href") and self.card_data.get("title"):
                self.cards.append(self.card_data)
            self.card_data = {}
            self.in_title = False
            self.in_excerpt = False
            self.in_meta = False
            self.in_type = False
        elif self.in_title and tag in ("h1", "h2", "h3", "h4", "div", "span"):
            self.in_title = False
        elif self.in_excerpt and tag in ("p", "div", "span"):
            self.in_excerpt = False
        elif self.in_meta and tag in ("span", "div"):
            self.in_meta = False
        elif self.in_type and tag in ("span", "div"):
            self.in_type = False

    def handle_data(self, data):
        if not self.in_card:
            return
        if self.in_title:
            self.card_data["title"] = (self.card_data.get("title", "") + data).strip()
        elif self.in_excerpt:
            self.card_data["excerpt"] = (self.card_data.get("excerpt", "") + data).strip()
        elif self.in_meta:
            self.card_data["meta"] = (self.card_data.get("meta", "") + " " + data).strip()
        elif self.in_type:
            clean = data.strip()
            if clean:
                self.card_data["type"] = (self.card_data.get("type", "") + " " + clean).strip()


def parse_claude_html(text, source=None, observed_at=None):
    """Parse claude.com listing HTML (e.g. /resources/articles or /blog) into observations."""
    source = source or DEFAULT_SOURCE
    parser = _ClaudeCardParser()
    parser.feed(text)
    items, seen = [], set()

    for card in parser.cards:
        href = card.get("href", "")
        full_url = urljoin("https://claude.com", href)
        if not is_claude_news_url(full_url):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)

        title = clean_text(card.get("title", ""), 500)
        if not title:
            continue

        raw_date = card.get("meta", "").strip()
        date = parse_claude_date(raw_date)

        summary = clean_text(card.get("excerpt", "") or title, 300)
        kind = classify(title, summary)

        if observed_at is not None:
            obs = observation(source, title, full_url, date, observed_at, kind=kind, summary=summary)
            if obs:
                items.append(obs)
        else:
            items.append(dict(
                id=stable_id(full_url),
                lab=source.get("lab", "anthropic"),
                source=source["id"],
                title=title,
                url=full_url,
                published_at=date,
                summary=summary,
                kind=kind,
            ))

    return sorted(items, key=lambda item: item["published_at"] or "", reverse=True)


def parse_claude_article_page(text, source=None, observed_at=None, page_url=None):
    """Parse a single claude.com article page HTML (extracting JSON-LD BlogPosting or meta tags)."""
    source = source or DEFAULT_SOURCE
    title, summary, date, url = None, None, None, page_url

    # 1. Search for JSON-LD BlogPosting
    ld_matches = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text, re.DOTALL)
    for raw_ld in ld_matches:
        try:
            data = json.loads(raw_ld)
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if isinstance(node, dict) and node.get("@type") in ("BlogPosting", "Article", "NewsArticle"):
                    title = title or node.get("headline") or node.get("name")
                    summary = summary or node.get("description")
                    date = date or node.get("datePublished") or node.get("dateCreated")
                    url = url or node.get("url") or node.get("mainEntityOfPage")
        except Exception:
            pass

    # 2. Fallback to OpenGraph / Meta tags
    if not title:
        m = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', text, re.I)
        if m:
            title = m.group(1)
    if not summary:
        m = re.search(r'<meta\s+(?:property=["\']og:description["\']|name=["\']description["\'])\s+content=["\']([^"\']+)["\']', text, re.I)
        if m:
            summary = m.group(1)
    if not date:
        m = re.search(r'<meta\s+property=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']', text, re.I)
        if m:
            date = m.group(1)
    if not url:
        m = re.search(r'<meta\s+property=["\']og:url["\']\s+content=["\']([^"\']+)["\']', text, re.I)
        if m:
            url = m.group(1)

    url = url or page_url
    if not url or not title:
        return []

    url = urljoin("https://claude.com", url)
    if not is_claude_news_url(url):
        return []

    title = clean_text(title, 500)
    summary = clean_text(summary or title, 300)
    date = parse_claude_date(date)
    kind = classify(title, summary)

    if observed_at is not None:
        obs = observation(source, title, url, date, observed_at, kind=kind, summary=summary)
        return [obs] if obs else []
    return [dict(
        id=stable_id(url),
        lab=source.get("lab", "anthropic"),
        source=source["id"],
        title=title,
        url=url,
        published_at=date,
        summary=summary,
        kind=kind,
    )]


def parse_claude_sitemap(text, source=None, observed_at=None):
    """Parse claude.com sitemap XML (<urlset>), extracting news articles."""
    source = source or DEFAULT_SOURCE
    try:
        root = ET.fromstring(text)
    except Exception as e:
        raise ValueError(f"Invalid sitemap XML: {e}")

    items, seen = [], set()
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "url":
            loc, lastmod = "", ""
            for child in node:
                ctag = child.tag.rsplit("}", 1)[-1]
                if ctag == "loc" and child.text:
                    loc = child.text.strip()
                elif ctag == "lastmod" and child.text:
                    lastmod = child.text.strip()
            if loc and is_claude_news_url(loc) and loc not in seen:
                seen.add(loc)
                date = parse_claude_date(lastmod)
                slug = urlsplit(loc).path.rstrip("/").split("/")[-1]
                # Default readable title from slug if sitemap only has loc
                title = clean_text(" ".join(slug.split("-")).capitalize(), 500)
                kind = classify(title, "")
                if observed_at is not None:
                    obs = observation(source, title, loc, date, observed_at, kind=kind, summary="")
                    if obs:
                        items.append(obs)
                else:
                    items.append(dict(
                        id=stable_id(loc),
                        lab=source.get("lab", "anthropic"),
                        source=source["id"],
                        title=title,
                        url=loc,
                        published_at=date,
                        summary="",
                        kind=kind,
                    ))

    return sorted(items, key=lambda item: item["published_at"] or "", reverse=True)


def parse_claude(text, source=None, observed_at=None):
    """Unified entry point for claude.com content (listing HTML, sitemap XML, or article page)."""
    stripped = text.lstrip()
    if stripped.startswith("<?xml") or ("<urlset" in text and "<loc>" in text):
        return parse_claude_sitemap(text, source, observed_at)
    # Check if single article page (has BlogPosting JSON-LD or og:type=article)
    if ('"@type":"BlogPosting"' in text or '"@type": "BlogPosting"' in text or 'property="og:type" content="article"' in text.lower()) and "ResourceCard" not in text:
        return parse_claude_article_page(text, source, observed_at)
    return parse_claude_html(text, source, observed_at)

"""Parse release evidence without inventing publication dates."""

import re
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from urllib.parse import unquote

from radar.common import stable_id, web_url
from radar.items import published_date

VERSION = re.compile(r"(?<![\w.])(?:v|rust-v)?(\d+\.\d+(?:\.\d+)*(?:-[\w.-]+)?)(?![\w.])", re.I)
PRERELEASE = re.compile(r"(?:alpha|beta|rc\d*|preview|nightly|canary|dev)(?:\b|[.-])", re.I)


class TextBlocks(HTMLParser):
    """Preserve rendered source words and block boundaries; ignore scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.blocks, self.hidden = [], [], 0

    def flush(self):
        value = " ".join("".join(self.parts).split())
        if value:
            self.blocks.append(value)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "pre", "br"}:
            self.flush()

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "pre"}:
            self.flush()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_blocks(text):
    parser = TextBlocks()
    parser.feed(text)
    parser.flush()
    return parser.blocks


def release_version(value):
    match = VERSION.search(value)
    return match[1] if match else None


def entry(source, title, url, version=None, **extra):
    return dict(id=stable_id(source["product"] + "|" + (version or url)),
                product=source["product"], product_name=source["product_name"],
                title=title, url=url, version=version, channel="stable",
                published_at=None, updated_at=None, published_date=None,
                time_precision="unknown", time_basis="unknown", sources=[source["id"]],
                highlights=[], **extra)


def highlights(blocks, source, url):
    # Keep source prose, not package-install commands, headings or contributor lists.
    excluded = re.compile(r"^(?:full changelog|what.s changed|new contributors|changelog|"
                          r"new features|bug fixes|improvements|what.s new|\$ |npm |pip |"
                          r"thanks |contributors|view details|full release on github)(?:\b|:)", re.I)
    values = []
    for text in blocks:
        if (len(text) < 20 or excluded.search(text) or text.startswith(("http://", "https://"))
                or re.match(r"^#\d+\s", text)):
            continue
        # A prefix is still an exact quote; ellipsis belongs to UI, not stored source text.
        excerpt = text if len(text) <= 240 else text[:240].rsplit(" ", 1)[0]
        if excerpt and not any(row["text"] == excerpt for row in values):
            values.append(dict(text=excerpt, source=source["id"], source_name=source["name"], url=url,
                               truncated=len(excerpt) < len(text)))
    return values


def parse_atom(text, source):
    root = ET.fromstring(text)
    ns = "{http://www.w3.org/2005/Atom}"
    if root.tag != ns + "feed":
        raise ValueError("Expected an Atom release feed")
    result, entries = [], root.findall(ns + "entry")
    for node in entries:
        title = " ".join((node.findtext(ns + "title") or "").split())
        links = [link.get("href", "") for link in node.findall(ns + "link")
                 if link.get("rel", "alternate") == "alternate"]
        url = next((link for link in links if web_url(link) and link.startswith(source["release_prefix"])), None)
        if not title or not url:
            continue
        tag = unquote(url.rsplit("/", 1)[-1])
        version = release_version(tag) or release_version(title)
        row = entry(source, title, url, version)
        row["channel"] = "prerelease" if PRERELEASE.search(tag + " " + title) else "stable"
        row["published_at"] = published_date(node.findtext(ns + "published"))
        row["updated_at"] = published_date(node.findtext(ns + "updated"))
        printed_date = node.findtext(ns + "published") or ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", printed_date):
            try:
                row["published_date"] = date.fromisoformat(printed_date).isoformat()
            except ValueError:
                pass
        stamp = row["published_at"] or (row["updated_at"] if not row["published_date"] else None)
        if stamp:
            row.update(time_precision="exact", time_basis="published" if row["published_at"] else "updated")
            row["published_date"] = row["published_at"][:10] if row["published_at"] else None
        elif row["published_date"]:
            row.update(time_precision="date", time_basis="published")
        content = node.find(ns + "content")
        if content is None:
            content = node.find(ns + "summary")
        body = "" if content is None else (content.text or "") + "".join(
            ET.tostring(child, encoding="unicode") for child in content)
        row["highlights"] = highlights(html_blocks(body), source, url)
        result.append(row)
    if entries and not result:
        raise ValueError("Atom entries contain no official release URLs")
    return result


def parse_markdown(text, source):
    # This intentionally supports only plain version headings. A full Markdown
    # renderer is needed to prove anchors for links, inline HTML or setext titles.
    # Exclude ambiguous documents rather than emit plausible but unverified URLs.
    matches = list(re.finditer(r"^##\s+(?:\[)?(v?\d+\.\d+(?:\.\d+)*(?:-[\w.-]+)?)(?:\])?[^\n]*$", text, re.M))
    if not matches:
        raise ValueError("CHANGELOG contains no version headings")
    if (re.search(r"^\s*(?:`{3,}|~{3,})", text, re.M)
            or re.search(r"^ {0,3}(?:=+|-+)\s*$", text, re.M)
            or re.search(r"^[ \t]*>|^[ \t]+#{1,6}[ \t]|^[ \t]*(?:[-+*]|\d+[.)])[ \t]+.*#[ \t]", text, re.M)
            or "<!--" in text or re.search(r"^ {0,3}<", text, re.M)
            or re.search(r"<\s*(?:h[1-6]\b|a\b)", text, re.I)):
        return []
    headings = list(re.finditer(r"^ {0,3}#{1,6}\s+([^\n]+)$", text, re.M))
    if any(not re.fullmatch(r"[A-Za-z0-9 ._-]+", heading[1].strip()) for heading in headings):
        return []
    anchors = [heading[1].strip().lower().replace(".", "").replace(" ", "-") for heading in headings]
    result = []
    for index, match in enumerate(matches):
        if not re.fullmatch(r"## +" + re.escape(match[1]) + r"\s*", match[0]):
            continue
        anchor = match[1].lower().replace(".", "")
        if anchors.count(anchor) != 1:
            continue
        version = release_version(match[1])
        url = source["entry_prefix"] + anchor
        row = entry(source, source["product_name"] + " " + match[1], url, version)
        row["channel"] = "prerelease" if PRERELEASE.search(match[1]) else "stable"
        body = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        # Markdown formatting remains in the exact quote rather than rewriting source words.
        blocks = [re.sub(r"^\s*[-*+]\s+", "", line).strip() for line in body.splitlines()
                  if line.strip() and not line.lstrip().startswith(("#", "```"))]
        row["highlights"] = highlights(blocks, source, url)
        result.append(row)
    return result

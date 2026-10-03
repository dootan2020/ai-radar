"""Official Codex changelog entries, matched by the publisher's DOM metadata."""

from datetime import date
from html.parser import HTMLParser
from urllib.parse import quote

from radar.common import web_url
from radar.tool_parsers import PRERELEASE, entry, highlights, release_version


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.walk(tag)

    def text(self):
        if self.tag in {"script", "style", "button", "svg"}:
            return ""
        return "".join(child.text() if isinstance(child, Node) else child for child in self.children)


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _text(node):
    return " ".join(node.text().split()) if node else ""


class ParsedEntries(list):
    """List-compatible parser result with partial-source failure evidence."""

    dropped_entries = 0


def parse_codex_html(text, source):
    document = Document()
    document.feed(text)
    result, recognized = ParsedEntries(), 0
    for node in document.root.walk("li"):
        attrs = node.attrs
        if not attrs.get("data-product") and not attrs.get("data-products"):
            continue
        products = (attrs.get("data-products") or attrs.get("data-product") or "").split()
        if "codex" not in products:
            continue
        recognized += 1
        title = _text(next(node.walk("h3"), None))
        printed_date = _text(next(node.walk("time"), None))
        article = next(node.walk("article"), None)
        anchor = attrs.get("id")
        if not title or article is None or not anchor:
            result.dropped_entries += 1
            continue
        try:
            day = date.fromisoformat(printed_date).isoformat()
        except (TypeError, ValueError):
            result.dropped_entries += 1
            continue
        topic_text = attrs.get("data-codex-topics", "")
        if not isinstance(topic_text, str):
            result.dropped_entries += 1
            continue
        topics = topic_text.split()
        product, name = ("codex-cli", "Codex CLI") if "codex-cli" in topics else (
            ("codex-desktop", "Codex desktop") if "codex-app" in topics else ("codex", "Codex"))
        spec = dict(source, product=product, product_name=name)
        evidence_url = source["entry_base"] + "#" + quote(anchor, safe="-_.")
        url = evidence_url
        release_url = attrs.get("data-release-url")
        if product == "codex-cli" and web_url(release_url) and release_url.startswith("https://github.com/openai/codex/releases/tag/"):
            url = release_url
        # Version numbers in a model name are not product release versions.
        version = release_version(title) if product in {"codex-cli", "codex-desktop"} else None
        row = entry(spec, title, url, version)
        row.update(published_date=day, time_precision="date", time_basis="published")
        row["channel"] = "prerelease" if version and PRERELEASE.search(version) else "stable"
        blocks = [_text(child) for child in article.walk("li")]
        blocks.extend(_text(child) for child in article.walk("p"))
        row["highlights"] = highlights(blocks, source, evidence_url)
        result.append(row)
    if not recognized:
        raise ValueError("Official changelog has no recognized product entries")
    if not result:
        raise ValueError(f"No valid Codex entries; skipped {result.dropped_entries} malformed entries")
    return result

"""Read the public GitHub Trending page without authenticated API calls."""

import re
from html.parser import HTMLParser

from radar.common import clean_text, number

SOURCE = dict(id="github-trending", name="GitHub Trending", lab="", kind="github",
              url="https://github.com/trending")


class _Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.heading = 0
        self.repo = None
        self.parts = {"description": [], "language": [], "stars": [], "stars_today": []}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = None
        if tag == "h2":
            self.heading += 1
        if tag == "a" and self.heading:
            href = attrs.get("href", "")
            if re.fullmatch(r"/[\w.-]+/[\w.-]+", href):
                self.repo = href[1:]
        if tag == "p":
            key = "description"
        elif attrs.get("itemprop") == "programmingLanguage":
            key = "language"
        elif tag == "a" and attrs.get("href", "").endswith("/stargazers"):
            key = "stars"
        elif "float-sm-right" in attrs.get("class", "").split():
            key = "stars_today"
        if tag not in {"img", "br", "hr", "input", "meta", "link", "wbr"}:
            self.stack.append((tag, key))

    def handle_endtag(self, tag):
        if tag == "h2":
            self.heading = max(0, self.heading - 1)
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for _, key in self.stack:
            if key:
                self.parts[key].append(data)


def parse_trending(text):
    result, seen = [], set()
    for article in re.findall(r"<article\b[^>]*>.*?</article>", text, flags=re.S | re.I):
        parser = _Article()
        parser.feed(article)
        if not parser.repo or parser.repo in seen:
            continue
        seen.add(parser.repo)
        fields = {key: clean_text("".join(value), 500) for key, value in parser.parts.items()}
        today = re.search(r"([\d,]+)\s+stars?\s+today", fields["stars_today"])
        result.append(dict(repo=parser.repo, url="https://github.com/" + parser.repo,
                           description=fields["description"], language=fields["language"] or None,
                           stars=number(fields["stars"]), stars_today=number(today[1]) if today else None))
    if not result:
        raise ValueError("GitHub Trending page contains no recognizable repository cards")
    return result[:25]

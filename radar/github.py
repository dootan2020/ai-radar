"""Read the public GitHub Trending pages without authenticated API calls."""

import re
from html.parser import HTMLParser

from radar.common import clean_text, number

SOURCE = dict(id="github-trending", name="Thịnh hành trên GitHub", lab="", kind="github",
              url="https://github.com/trending")

# The three windows GitHub Trending publishes. The phrase is the page's own wording for the stars a repository
# gained in that window; a page whose phrase belongs to another window does not measure this one.
WINDOWS = (
    ("day", "https://github.com/trending", "today"),
    ("week", "https://github.com/trending?since=weekly", "this week"),
    ("month", "https://github.com/trending?since=monthly", "this month"),
)
_PERIODS = {phrase: window for window, _, phrase in WINDOWS}


class _Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.heading = 0
        self.repo = None
        self.parts = {"description": [], "language": [], "stars": [], "forks": [], "stars_today": []}

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
        elif tag == "a" and attrs.get("href", "").endswith("/forks"):
            key = "forks"
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
    """Repositories in page order.

    `stars_gained` is the count GitHub prints for the page's own window and `gained_period` names that
    window ("day", "week" or "month"); a card without the phrase leaves both unknown. `forks` is the
    fork count printed on the card, a real GitHub measurement.
    """
    result, seen = [], set()
    for article in re.findall(r"<article\b[^>]*>.*?</article>", text, flags=re.S | re.I):
        parser = _Article()
        parser.feed(article)
        if not parser.repo or parser.repo in seen:
            continue
        seen.add(parser.repo)
        fields = {key: clean_text("".join(value), 500) for key, value in parser.parts.items()}
        phrase = r"([\d,]+)\s+stars?\s+(today|this week|this month)"
        # The count normally sits in the right-floated span; markup changes must not lose it.
        gained = re.search(phrase, fields["stars_today"], re.I) or re.search(phrase, clean_text(article, 20000), re.I)
        period = _PERIODS[gained[2].lower()] if gained else None
        stars_gained = number(gained[1]) if gained else None
        result.append(dict(repo=parser.repo, url="https://github.com/" + parser.repo,
                           description=fields["description"], language=fields["language"] or None,
                           stars=number(fields["stars"]), forks=number(fields["forks"]),
                           stars_today=stars_gained if period == "day" else None,
                           stars_gained=stars_gained, gained_period=period))
    if not result:
        raise ValueError("GitHub Trending page contains no recognizable repository cards")
    return result[:25]

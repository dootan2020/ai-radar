"""RSS/Atom lab news. Community feed attribution is explicit."""

from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET

from radar.common import classify, clean_text, iso_date, stable_id, web_url

_COMMUNITY = "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_{}.xml"
_FEEDS = [
    ("openai-news", "OpenAI News", "openai", "https://openai.com/news/rss.xml"),
    ("google-ai", "Google AI", "google", "https://blog.google/technology/ai/rss/"),
    ("google-deepmind", "Google DeepMind", "google", "https://deepmind.google/blog/rss.xml"),
    ("anthropic-news", "Anthropic News (nguồn cộng đồng)", "anthropic", _COMMUNITY.format("anthropic_news")),
    ("anthropic-gftdon", "Anthropic News (nguồn cộng đồng gftdon)", "anthropic", "https://gftdon.github.io/ai-news-rss/anthropic.xml"),
    ("anthropic-research", "Anthropic Research (nguồn cộng đồng)", "anthropic", _COMMUNITY.format("anthropic_research")),
    ("anthropic-engineering", "Anthropic Engineering (nguồn cộng đồng)", "anthropic", _COMMUNITY.format("anthropic_engineering")),
    ("xai-news", "xAI News (nguồn cộng đồng)", "xai", _COMMUNITY.format("xainews")),
    ("meta-news", "Meta AI (nguồn cộng đồng)", "meta", _COMMUNITY.format("meta_ai")),
    ("mistral-news", "Mistral News (nguồn cộng đồng)", "mistral", _COMMUNITY.format("mistral")),
    ("huggingface-blog", "Hugging Face Blog", "huggingface", "https://huggingface.co/blog/feed.xml"),
]
SOURCES = [dict(id=id_, name=name, lab=lab, kind="rss", url=url) for id_, name, lab, url in _FEEDS]
for _source in SOURCES:
    if _source["id"] == "google-deepmind":
        _source.update(disabled=True, disabled_reason=(
            "Địa chỉ RSS trả mã HTTP 200 nhưng XML hỏng trên máy dựng của GitHub; "
            "chưa kiểm được địa chỉ RSS thay thế. Google AI và kênh YouTube của DeepMind vẫn là nguồn riêng."
        ))


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _field(entry, *names):
    for name in names:
        for child in entry:
            if _local(child.tag) == name:
                return "".join(child.itertext())
    return ""


def _research_copy(title, summary):
    """Undo this feed's flattened date/category/title/teaser cards only."""
    category = r"(?:Frontier Red Team|Societal Impacts|Alignment|Interpretability|Economics|Science)"
    date = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}"
    prefix = rf"^(?:{date}\s*{category}|{category}\s*{date})\s*"
    cleaned, count = re.subn(prefix, "", title)
    if not count:
        return title, summary
    # Known card teaser sentence starts; do not split generic CamelCase words.
    parts = re.split(r"\s*(?=We (?:present|are sharing)\b)", cleaned, maxsplit=1)
    clean_title = parts[0].strip()
    if summary == title:
        summary = parts[1].strip() if len(parts) == 2 else clean_title
    return clean_title or title, summary


_VN_TZ = timezone(timedelta(hours=7))


def _genk_date(value):
    """Normalize GenK timestamps.
    GenK emits Vietnam local time (UTC+7) labeled as GMT/UTC (+0000) or naive.
    Interpret zero-offset or naive times as Asia/Ho_Chi_Minh (UTC+7).
    """
    if not value or not isinstance(value, (str, datetime)):
        return value
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return value

    if dt is None:
        return value

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_VN_TZ)
    elif dt.utcoffset() == timedelta(0):
        dt = dt.replace(tzinfo=None).replace(tzinfo=_VN_TZ)

    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_feed(text, source):
    root = ET.fromstring(text)
    if _local(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("Expected RSS or Atom, received another document")
    entries = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    items, seen = [], set()
    for entry in entries:
        url = _field(entry, "link")
        for link in entry:
            if _local(link.tag) == "link" and link.get("href") and link.get("rel", "alternate") == "alternate":
                url = link.get("href")
                break
        url = web_url(url.strip())
        title = clean_text(_field(entry, "title"), 500)
        date = _field(entry, "pubDate", "published", "date", "updated")
        if source.get("id") == "genk-ai" or source.get("publisher") == "genk":
            date = _genk_date(date)
        else:
            date = iso_date(date)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        summary = clean_text(_field(entry, "description", "summary", "encoded", "content"))
        if source["id"] == "anthropic-research":
            title, summary = _research_copy(title, summary)
        kind = "research" if source["id"] == "anthropic-research" else classify(title, summary)
        items.append(dict(id=stable_id(url), lab=source["lab"], source=source["id"],
                          title=title, url=url, published_at=date, summary=summary,
                          kind=kind))
    if entries and not items:
        raise ValueError("Feed entries have no usable title and URL")
    return sorted(items, key=lambda item: item["published_at"] or "", reverse=True)[:30]

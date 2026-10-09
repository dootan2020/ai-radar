"""Common v2 observation shape; missing measurements remain unknown."""

import json
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path

from radar.common import clean_text, iso_date, stable_id, web_url

AI_TERMS_CI = re.compile(
    r"\b(?:llms?|gpt|chatgpt|claude|gemini|deepseek|qwen|llama|anthropic|openai|"
    r"deepmind|hugging\s*face|neural|diffusion|inference|generative|machine learning|"
    r"artificial intelligence|language models?|agentic|copilot|cuda|nemotron|"
    r"chatbots?|deepfakes?|genai|gen-ai|xai|grok|mistral|midjourney|perplexity|"
    r"dall-e|dalle|sora|zhipu|chatglm|elevenlabs|multimodal|"
    r"trí tuệ nhân tạo|trí thông minh nhân tạo|siêu trí tuệ|học máy|mô hình ngôn ngữ|"
    r"trợ lý ảo|thị giác máy tính|mạng nơ-ron|mạng nơron|mạng thần kinh|vinai|nvidia)\b", re.I)
AI_EXACT = re.compile(r"\bAI\b")


def relevant(title, summary=""):
    text = (title or "") + " " + (summary or "")
    return bool(AI_EXACT.search(text) or AI_TERMS_CI.search(text))


def measured(value):
    """Accept JSON numeric values, never booleans, strings or nonfinite numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except (OverflowError, ValueError):
        return None


def is_x_item(item):
    source = item.get("source")
    publisher = item.get("publisher")
    return ((isinstance(source, str) and source.startswith("x-"))
            or (isinstance(publisher, str) and publisher.startswith("x:@")))


@lru_cache(maxsize=1)
def _source_entities():
    """Build stable owners for old items that only retain their source ID."""
    from radar import catalog, huggingface, youtube

    entities = {source["id"]: source.get("entity") or source.get("publisher")
                for source in catalog.sources(datetime.now(timezone.utc))}
    entities.update({source["id"]: source.get("lab") or "huggingface"
                     for source in huggingface.SOURCES + [huggingface.TRENDING_SOURCE]})
    entities.update({channel[0]: channel[1] for channel in youtube.CHANNELS})
    roster = Path(__file__).resolve().parents[1] / "data" / "x-accounts.json"
    try:
        accounts = json.loads(roster.read_text(encoding="utf-8"))["accounts"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        accounts = []
    entities.update({"x-" + account["handle"].casefold(): account["entity"]
                     for account in accounts
                     if isinstance(account, dict) and account.get("handle") and account.get("entity")})
    return entities


def publisher_identity(item):
    """Return the identity used for breadth while retaining each source publisher."""
    source = item.get("source")
    # Aggregators count the outlet linked by each observation, not the forum
    # or index that collected it. Preserve that attribution for stored items.
    if source in {"hn-front", "hn-ai", "lobsters-ai", "hf-models-ranked", "hf-spaces-ranked"}:
        return item.get("publisher") or item.get("publisher_group")
    if item.get("entity"):
        return item["entity"]
    publisher = item.get("publisher")
    if (publisher and not (publisher == "bluesky" or publisher == "huggingface"
                           or publisher.startswith(("x:@", "youtube:")))):
        return publisher
    entities = _source_entities()
    if source in entities:
        return entities[source]
    if is_x_item(item):
        return "x"
    return item.get("publisher_group") or item.get("publisher")


def instant(value):
    if not isinstance(value, (str, datetime)):
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def published_date(value, default_tz=None):
    """Source timestamps must carry a real timezone; date-only is not midnight."""
    if not value or not isinstance(value, (str, datetime)):
        return None
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value.strip()):
        return None
    return iso_date(value, default_tz=default_tz)


def observation(source, title, url, published_at, observed_at, *, kind="other", summary="",
                metrics=None, media=None, discussion_url=None, time_basis="published", **extra):
    from radar.clustering import canonical_url

    url = web_url(url)
    if not url or not canonical_url(url) or not clean_text(title, 500):
        return None
    default_tz = source.get("default_tz") or source.get("timezone") or source.get("tz")
    date = published_date(published_at, default_tz=default_tz)
    discussion_url = web_url(discussion_url)
    # Different forum threads can discuss the same target URL. Their votes and
    # baselines belong to the thread, while the target still anchors the story.
    identity = discussion_url or url
    return dict(id=stable_id(source["id"] + "|" + identity), source=source["id"],
                publisher=source.get("publisher") or source.get("lab") or source["id"],
                entity=source.get("entity") or source.get("publisher") or source.get("lab") or source["id"],
                group=source.get("group", "lab"), lab=source.get("lab", ""), kind=kind,
                title=clean_text(title, 500), url=url, canonical_url=canonical_url(url),
                published_at=date, summary=clean_text(summary), observed_at=iso_date(observed_at),
                metrics={key: measured(value) for key, value in (metrics or {}).items()},
                media=media or [], discussion_url=discussion_url,
                time_basis=time_basis if date or time_basis == "scheduled" else "unknown", **extra)

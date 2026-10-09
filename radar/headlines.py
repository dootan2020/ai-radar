"""Extractive card headlines; source titles and translations remain evidence."""

import re

HEADLINE_LIMIT = 140


def compact_headline(text, limit=HEADLINE_LIMIT):
    """Keep a complete first sentence when possible, otherwise a word prefix."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    # Require sentence-ending whitespace; decimals and model versions stay intact.
    for match in re.finditer(r'[.!?](?:[”’"\')\]]?)(?=\s|$)', text[:limit + 1]):
        prefix = text[:match.end()]
        if 35 <= len(prefix) <= limit and not re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|vs|etc)\.$", prefix, re.I):
            return prefix
    prefix = text[:limit - 1]
    boundary = prefix.rfind(" ")
    if boundary > 0:
        prefix = prefix[:boundary]
    return prefix.rstrip(" ,;:–—-") + "…"


def annotate_headlines(story):
    """Add display fields to a story and its separately attributed coverage."""
    for item in [story, *(story.get("coverage") or [])]:
        item["headline"] = compact_headline(item.get("title"))
        if item.get("title_vi"):
            item["headline_vi"] = compact_headline(item["title_vi"])
        else:
            item.pop("headline_vi", None)

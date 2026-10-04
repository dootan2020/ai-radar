"""Search index companion projection for 7-day story search on mobile devices."""

from pathlib import Path
import re
import unicodedata

SEARCH_STORY_FIELDS = (
    "id", "title", "title_vi", "url", "published_at", "publishers", "kind", "search_text"
)


def normalize_vietnamese(text):
    """Normalize text for Vietnamese and English diacritic-free, case-insensitive search.

    - Replaces Vietnamese đ/Đ with d/D.
    - Decomposes combining diacritical marks via NFD and removes all 'Mn' marks.
    - Converts to lowercase and normalizes to NFC.
    - Converts non-alphanumeric characters to whitespace.
    - Collapses multiple whitespace characters.
    """
    if not text or not isinstance(text, str):
        return ""
    text = text.replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    normalized = unicodedata.normalize("NFC", stripped).lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", normalized)
    return cleaned.strip()


def extract_publishers(story):
    """Extract distinct non-empty publisher names from story coverage and fallback.

    Never defaults or invents a publisher name.
    """
    publishers = []
    seen = set()
    coverage = story.get("coverage")
    if isinstance(coverage, list):
        for item in coverage:
            if isinstance(item, dict):
                pub = item.get("publisher")
                if isinstance(pub, str) and pub.strip():
                    p = pub.strip()
                    if p not in seen:
                        seen.add(p)
                        publishers.append(p)
    if not publishers:
        top_pub = story.get("publisher")
        if isinstance(top_pub, str) and top_pub.strip():
            publishers.append(top_pub.strip())
    return publishers


def make_search_text(title, title_vi=None, publishers=None):
    """Build normalized search text covering title, Vietnamese translation, and publishers.

    Avoids duplicate appending if title_vi is identical to title, or if publisher
    is already in the title text.
    """
    norm_title = normalize_vietnamese(title)
    norm_vi = normalize_vietnamese(title_vi) if title_vi else ""

    parts = []
    if norm_title:
        parts.append(norm_title)
    if norm_vi and norm_vi != norm_title:
        parts.append(norm_vi)

    search_base = " ".join(parts)

    if publishers:
        for pub in publishers:
            norm_p = normalize_vietnamese(pub)
            if norm_p and norm_p not in search_base:
                parts.append(norm_p)

    return " ".join(parts)


def search_story_row(story):
    """Transform a payload story dict into a lean search index record.

    Carries empty values for missing fields without inventing defaults.
    """
    sid = story.get("id") or ""
    title = story.get("title") or ""
    title_vi = story.get("title_vi") or ""
    if title_vi == title:
        title_vi = ""
    url = story.get("url") or ""
    published_at = story.get("published_at") or ""
    kind = story.get("kind") or ""
    publishers = extract_publishers(story)
    search_text = make_search_text(title, title_vi, publishers)

    return {
        "id": sid,
        "title": title,
        "title_vi": title_vi,
        "url": url,
        "published_at": published_at,
        "publishers": publishers,
        "kind": kind,
        "search_text": search_text,
    }


def search_payload(payload):
    """Project full or page payload into lean search index covering all retained stories."""
    stories = payload.get("stories", []) if isinstance(payload, dict) else []
    indexed_stories = [search_story_row(s) for s in stories if isinstance(s, dict)]

    raw_sources = payload.get("sources", []) if isinstance(payload, dict) else []
    sources = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "publisher": s.get("publisher"),
            "lab": s.get("lab", ""),
        }
        for s in raw_sources
        if isinstance(s, dict) and s.get("id")
    ]

    return {
        "schema_version": payload.get("schema_version", 2) if isinstance(payload, dict) else 2,
        "generated_at": payload.get("generated_at", "") if isinstance(payload, dict) else "",
        "story_count": len(indexed_stories),
        "sources": sources,
        "stories": indexed_stories,
    }


def search_path(path):
    """Companion search index projection path, e.g. radar-search.json."""
    path = Path(path)
    return path.with_name(f"{path.stem}-search{path.suffix}")


def audit_missing_fields(payload):
    """Count missing fields across all stories in a payload."""
    stories = payload.get("stories", []) if isinstance(payload, dict) else []
    counts = {
        "total_stories": len(stories),
        "missing_id": 0,
        "missing_title": 0,
        "missing_title_vi": 0,
        "missing_published_at": 0,
        "missing_url": 0,
        "missing_publisher": 0,
    }
    for s in stories:
        if not isinstance(s, dict):
            continue
        if not s.get("id"):
            counts["missing_id"] += 1
        if not s.get("title"):
            counts["missing_title"] += 1
        if not s.get("title_vi"):
            counts["missing_title_vi"] += 1
        if not s.get("published_at"):
            counts["missing_published_at"] += 1
        if not s.get("url"):
            counts["missing_url"] += 1
        pubs = extract_publishers(s)
        if not pubs:
            counts["missing_publisher"] += 1
    return counts

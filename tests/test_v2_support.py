"""Explicitly synthetic, offline coverage fixtures for v2 invariant tests."""

from datetime import datetime, timezone

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
OBSERVED = "2026-10-02T12:00:00Z"


def coverage(source="fixture-a", url="https://example.org/article", **changes):
    item = {
        "id": source + ":" + url, "source": source, "publisher": source,
        "group": "press", "lab": None, "kind": "other",
        "title": "Synthetic neural reasoning architecture released today",
        "url": url, "canonical_url": url, "published_at": "2026-10-02T11:00:00Z",
        "summary": "Synthetic offline fixture, never production data.",
        "observed_at": OBSERVED, "metrics": {}, "media": [],
        "discussion_url": None, "time_basis": "published",
    }
    item.update(changes)
    return item

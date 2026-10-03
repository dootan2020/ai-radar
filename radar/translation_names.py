"""Identity vocabulary for translation, drawn from collectors and snapshot metadata."""

import re

from radar import catalog, feeds, huggingface
from radar.classification import _NAME as MODEL_IDENTITY_PATTERN


# The classifier requires versions for these families and does not cover Sora.
# Other model identities come from its existing grammar, not a duplicate list.
BARE_MODEL_NAMES = frozenset(("Claude", "Gemini", "Grok", "Sora"))
MODEL_IDENTITY = re.compile(r"(?<!\w)" + MODEL_IDENTITY_PATTERN, re.IGNORECASE)


def name_pattern(name):
    """Whole identity, including Unicode boundaries; Grokking is not Grok."""
    return r"(?<!\w)" + re.escape(name) + r"(?!\w)"


def _source_names(rows):
    names = set()
    for row in rows:
        for key in ("name", "lab", "publisher"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                # Attribution parentheses are metadata, not part of an identity.
                names.add(value.split(" (", 1)[0].strip())
    return names


def _catalog_names():
    rows = [dict(name=row[1], publisher=row[3]) for row in catalog.RSS]
    names = _source_names([*rows, *feeds.SOURCES, *huggingface.SOURCES])
    names.update(huggingface.AUTHORS)
    names.update(huggingface.AUTHORS.values())
    return frozenset(names | BARE_MODEL_NAMES)


CATALOG_NAMES = _catalog_names()


def payload_names(payload):
    """Snapshot source identities extend the catalog without mutable global state."""
    rows = [row for row in payload.get("sources") or [] if isinstance(row, dict)]
    return CATALOG_NAMES | _source_names(rows)


def object_names(obj):
    """Repo identities stay local: 'requests' elsewhere may be an ordinary word."""
    names = _source_names([obj])
    for key in ("id", "full_name"):
        value = obj.get(key)
        if isinstance(value, str) and re.fullmatch(r"[^\s/]+/[^\s/]+", value):
            names.add(value)
            names.add(value.rsplit("/", 1)[1])
    return names


def names_in(source, candidates=CATALOG_NAMES):
    """Use the source spelling, including when the catalog uses lowercase IDs."""
    identities = {match.group() for name in candidates
                  for match in re.finditer(name_pattern(name), source, re.IGNORECASE)}
    # Qualifiers such as Small and Fast belong to this identity, not every
    # occurrence of the word. A standalone qualifier cannot replace a lost one.
    identities.update(match.group() for match in MODEL_IDENTITY.finditer(source))
    return identities

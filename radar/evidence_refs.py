"""Paragraph IDs ("outlet:p010") belong in a claim's evidence_refs, never in the words a reader sees.

The newsroom writer cites source paragraphs by ID (radar.summary_sources.source_record: "outlet:p001",
"primary:p012", "coverage2:p003", "outlet:publisher"). Measured 06/11: writer and review-writer replies also put
those IDs into the sentence text, "(outlet:p015)" or "[outlet:p008, outlet:p016]" before the full stop, and four
of 26 published stories showed them. strip_evidence_refs removes every such ID and the brackets or separators
left around it; it deletes characters only, never adds a word, and returns text without an ID unchanged.
"""

from __future__ import annotations

import re

# A source ID then a paragraph number or the publisher label. The lookarounds keep a URL, a file path or a time
# ("10:30") out: an ID starts at a word boundary not preceded by "/", "." or ":", and ends before a word character.
_ID = r"(?<![\w/.:-])[A-Za-z][A-Za-z0-9_-]{0,31}:(?:p\d{1,4}|publisher)(?![\w-])"
_SEP = r"\s*[,;]\s*"
# A bracket group holding only IDs, with the space before it: " (outlet:p010)", " [outlet:p008, outlet:p016]".
_GROUP = re.compile(rf"\s*[(\[]\s*{_ID}(?:(?:{_SEP}|\s+){_ID})*\s*[)\]]")
# An ID beside other words, with the separator that joined it to them.
_LEADING = re.compile(rf"{_ID}{_SEP}")
_TRAILING = re.compile(rf"{_SEP}{_ID}")
_BARE = re.compile(rf"\s*{_ID}")
_EMPTY = re.compile(r"\s*(?:\(\s*\)|\[\s*\])")
EVIDENCE_REF = re.compile(_ID)


def has_evidence_ref(text):
    """True when text holds a paragraph ID a reader should never see."""
    return isinstance(text, str) and EVIDENCE_REF.search(text) is not None


def unbracketed_evidence_ref(text):
    """True when an ID stands outside a citation bracket ("theo outlet:p010"): the writer used it as a word, so
    deleting it would leave a broken sentence, and the newsroom drops that sentence instead."""
    return isinstance(text, str) and EVIDENCE_REF.search(_GROUP.sub("", text)) is not None


def strip_evidence_refs(text):
    """text without paragraph IDs; text that holds none comes back unchanged."""
    if not has_evidence_ref(text):
        return text
    text = _GROUP.sub("", text)
    text = _LEADING.sub("", text)
    text = _TRAILING.sub("", text)
    text = _BARE.sub("", text)
    text = _EMPTY.sub("", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\].,;:!?])", r"\1", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()

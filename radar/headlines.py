"""Extractive card headlines; source titles and translations remain evidence."""

import re
import unicodedata
import urllib.parse

HEADLINE_LIMIT = 140

ABBREVIATIONS = {
    # English titles & honorifics
    "mr", "mrs", "ms", "dr", "prof", "jr", "sr", "rev", "hon", "gov", "sen",
    "rep", "pres", "gen", "col", "maj", "capt", "lt", "sgt", "st",
    # English corporate
    "inc", "corp", "co", "ltd", "llc", "plc", "gmbh", "ag", "sa",
    # Reference, editorial, Latin
    "vs", "etc", "al", "eg", "ie", "ca", "approx", "dept", "est", "fig",
    "figs", "min", "sec", "vol", "vols", "no", "nos", "pp", "p", "ed",
    "eds", "univ", "assoc", "bros",
    # Months
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec",
    # Vietnamese academic & professional titles
    "ts", "ths", "pgs", "gs", "bs", "ds", "cn", "ks", "th.s", "p.gs", "t.s",
    # Vietnamese administrative & political
    "tp", "tbt", "ttxvn", "tw", "ubnd", "hđnd", "bch", "đhqg", "kcs",
    "nxb", "tnhh", "cp", "vn", "tx", "tt", "q", "h", "p",
    # Vietnamese common
    "v.v", "đ/c", "đc", "k/g",
}


def split_graphemes(text):
    """Split string into extended grapheme clusters using pure Python."""
    if not text:
        return []
    clusters = []
    current = []
    ri_count = 0
    after_zwj = False

    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        is_ri = 0x1F1E6 <= cp <= 0x1F1FF
        is_vs = (0xFE00 <= cp <= 0xFE0F) or (0xE0100 <= cp <= 0xE01EF)
        is_modifier = 0x1F3FB <= cp <= 0x1F3FF
        is_tag = 0xE0020 <= cp <= 0xE007F
        is_extend = cat in ("Mn", "Mc", "Me") or is_vs or is_modifier or is_tag
        is_zwj = ch == "\u200d"

        if not current:
            should_break = False
        elif after_zwj:
            should_break = False
        elif is_zwj or is_extend:
            should_break = False
        elif is_ri and ri_count % 2 == 1:
            should_break = False
        else:
            should_break = True

        if should_break:
            clusters.append("".join(current))
            current = [ch]
        else:
            current.append(ch)

        if is_ri:
            ri_count += 1
        else:
            ri_count = 0
        after_zwj = is_zwj

    if current:
        clusters.append("".join(current))
    return clusters


def truncate_graphemes(text, max_len):
    """Truncate string to at most max_len codepoints without splitting grapheme clusters."""
    if len(text) <= max_len:
        return text
    clusters = split_graphemes(text)
    result = []
    cur_len = 0
    for cluster in clusters:
        if cur_len + len(cluster) > max_len:
            break
        result.append(cluster)
        cur_len += len(cluster)
    return "".join(result)


def ends_with_abbreviation_or_version(text):
    """Check if text ends with an abbreviation, initial, number, or version."""
    t = text.rstrip(" ”’\"')]} ,;:–—-")
    if not t:
        return False
    words = t.split()
    if not words:
        return False
    last_word = words[-1]
    cleaned = last_word.rstrip(".").lower()

    # 1. Exact match in curated English / Vietnamese abbreviations
    if cleaned in ABBREVIATIONS or last_word.lower() in ABBREVIATIONS:
        return True
    # 2. Single initials: e.g. "A.", "B.", "J.", "Đ."
    if re.search(r'(?:^|[\s(])([A-Za-zÀ-ỹĐđ])\.?$', last_word):
        return True
    # 3. Dotted initialisms: e.g. "U.S.", "U.K.", "E.U.", "A.I.", "Ph.D.", "v.v."
    if re.search(r'(?:^|[\s(])(?:[A-Za-zÀ-ỹĐđ]\.){2,}$', last_word) or re.search(r'\b(?:[A-Za-zÀ-ỹĐđ]\.)+[A-Za-zÀ-ỹĐđ]?\.?$', last_word):
        return True
    # 4. Version numbers: e.g. "v2.", "v1.0.", "ver. 2.", "v2"
    if re.search(r'\b[vV](?:er)?\.?\s*\d+(?:\.\d+)*\.?$', last_word):
        return True
    # 5. Standalone numbers / ordinals: e.g. "1.", "2.", "42.", "1"
    if re.search(r'^\d+\.?$', last_word):
        return True
    return False


def trim_trailing_abbreviations_and_numbers(prefix):
    """Strip trailing words while the prefix ends on an abbreviation, initial, number, or version."""
    while prefix and ends_with_abbreviation_or_version(prefix):
        parts = prefix.rstrip(" ,;:–—-").rsplit(None, 1)
        if len(parts) > 1:
            prefix = parts[0].rstrip(" ,;:–—-")
        else:
            break
    return prefix


def compact_headline(text, limit=HEADLINE_LIMIT):
    """Keep a complete first sentence when possible, otherwise a word prefix."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text

    # Sentence cut: look for true sentence-ending punctuation.
    for match in re.finditer(r'[.!?](?:[”’"\')\]]?)(?=\s|$)', text[:limit + 1]):
        prefix = text[:match.end()]
        if 35 <= len(prefix) <= limit and not ends_with_abbreviation_or_version(prefix):
            return prefix

    # Fallback cut: budget limit - 1 codepoints for prefix + 1 codepoint for ellipsis.
    max_prefix_len = limit - 1

    # Check if cut lands in a URL
    url_match = None
    for m in re.finditer(r'https?://\S+', text):
        if m.start() < max_prefix_len < m.end():
            url_match = m
            break

    if url_match:
        if url_match.start() > 0:
            prefix = text[:url_match.start()].rstrip(" ,;:–—-")
            prefix = trim_trailing_abbreviations_and_numbers(prefix)
            if prefix:
                return prefix + "…"
        else:
            parsed = urllib.parse.urlsplit(text)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin and len(origin) + 1 <= limit:
                return origin + "…"
            return truncate_graphemes(origin or text, max_prefix_len) + "…"

    # Check if title has no space before max_prefix_len (one long token)
    first_space = text.find(" ")
    if first_space == -1 or first_space > max_prefix_len:
        if text.startswith("http://") or text.startswith("https://"):
            parsed = urllib.parse.urlsplit(text)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin and len(origin) + 1 <= limit:
                return origin + "…"
        return truncate_graphemes(text, max_prefix_len) + "…"

    # Normal text with spaces
    safe_slice = truncate_graphemes(text, max_prefix_len)
    boundary = safe_slice.rfind(" ")
    if boundary > 0:
        prefix = safe_slice[:boundary]
    else:
        prefix = safe_slice

    prefix = prefix.rstrip(" ,;:–—-")
    prefix = trim_trailing_abbreviations_and_numbers(prefix)
    return prefix.rstrip(" ,;:–—-") + "…"


def annotate_headlines(story):
    """Add display fields to a story and its separately attributed coverage."""
    for item in [story, *(story.get("coverage") or [])]:
        item["headline"] = compact_headline(item.get("title"))
        if item.get("title_vi"):
            item["headline_vi"] = compact_headline(item["title_vi"])
        else:
            item.pop("headline_vi", None)

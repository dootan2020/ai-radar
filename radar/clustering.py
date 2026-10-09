"""Conservative complete-link story clusters; all publisher coverage survives."""

import re
import unicodedata
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from radar.common import stable_id, web_url
from radar.items import instant

STOPWORDS = set("a an the and or for to of in on with from by as at is are was were be been this that it its our your new now how what why when can will has have had about into more most first introducing announces announced releases released release launch launches launched over under after amid against due because part via says said report reports".split())
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "ref_url"}
ANNOUNCEMENT_RE = re.compile(r"\b(?:introduc\w*|debut\w*|unveil\w*|launch\w*|releas\w*|announc\w*)\b", re.I)


def canonical_url(url):
    if not isinstance(url, str) or not web_url(url):
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = "[" + host + "]"
    try:
        port = parts.port
    except ValueError:
        return None
    if port and not (parts.scheme.lower() == "https" and port == 443 or parts.scheme.lower() == "http" and port == 80):
        host += ":" + str(port)
    path = parts.path.rstrip("/")
    if host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(r"/(?:abs|pdf|html)/(\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?", path)
        if match:
            return "https://arxiv.org/abs/" + match[1]
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in TRACKING]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(sorted(query)), ""))


ENTITY_WORDS = {
    "openai", "anthropic", "google", "meta", "nvidia", "microsoft", "amazon", "apple", "xai", "mistral", "deepmind",
    "gpt", "claude", "gemini", "llama", "grok", "glm", "qwen"
}
TOPIC_WORDS = {
    "ai", "model", "models", "safety", "security", "concern", "concerns", "risk", "risks", "intelligence",
    "tech", "technology", "news", "update", "updates", "system", "systems", "agent", "agents", "release", "releases"
}
SUB_VARIANTS = {"sol", "luna", "astra", "opus", "sonnet", "haiku", "flash", "pro", "ultra", "lite", "turbo", "instruct", "scout", "maverick"}
GENERIC_CAPITALIZED_WORDS = {
    "america", "american", "americans", "asia", "asian", "canada", "canadian", "china", "chinese",
    "europe", "european", "france", "french", "germany", "german", "india", "indian", "japan",
    "japanese", "korea", "korean", "uk", "us", "usa", "western", "eastern", "global", "taking",
    "base", "first", "last", "new", "old", "open", "free", "big", "small", "best", "top", "today",
    "world", "why", "how", "what", "when", "where", "who", "can", "could", "would", "should",
}


def _stem(w):
    if len(w) >= 4 and w.endswith("s") and not w.endswith("ss"):
        if w.endswith("ies") and len(w) >= 5:
            return w[:-3] + "y"
        if w.endswith("es") and len(w) >= 5 and w[-3] in "shxz":
            return w[:-2]
        return w[:-1]
    return w


def _extract_versions(tokens):
    versions = set()
    for tok in tokens:
        if re.fullmatch(r"\d+\.\d+", tok):
            versions.add(tok)
        elif re.fullmatch(r"20\d{2}", tok):
            versions.add(tok)
        elif re.fullmatch(r"v\d+(?:\.\d+)*", tok):
            versions.add(tok)
    return versions


def _has_conflict(a_tokens, b_tokens):
    v_a = _extract_versions(a_tokens)
    v_b = _extract_versions(b_tokens)
    if v_a and v_b and not (v_a & v_b):
        return True
    
    var_a = a_tokens & SUB_VARIANTS
    var_b = b_tokens & SUB_VARIANTS
    if var_a and var_b and not (var_a & var_b):
        return True
        
    d_a = {tok for tok in a_tokens if re.fullmatch(r"\d+", tok)}
    d_b = {tok for tok in b_tokens if re.fullmatch(r"\d+", tok)}
    if len(d_a) == 1 and len(d_b) == 1 and d_a != d_b:
        if any(w in a_tokens & b_tokens for w in ENTITY_WORDS):
            return True
            
    return False


def _tokens(title):
    # Preserve accented words and normalize equivalent composed/decomposed text.
    title = unicodedata.normalize("NFC", title.lower())
    return set(token for token in re.findall(r"[^\W_]+(?:[.-][^\W_]+)*", title)
               if token not in STOPWORDS and (len(token) >= 3 or any(c.isdigit() for c in token)))


def _expand_tokens(title):
    base = _tokens(title)
    expanded = set(base)
    for tok in base:
        if "-" in tok:
            for part in tok.split("-"):
                if part not in STOPWORDS and (len(part) >= 3 or any(c.isdigit() for c in part)):
                    expanded.add(part)
    return expanded


def _sentence_case_entities(title):
    """Extract names from sentence-case titles, where interior capitals carry signal."""
    words = re.findall(r"[^\W_]+(?:[.-][^\W_]+)*", unicodedata.normalize("NFC", title))
    excluded = ENTITY_WORDS | TOPIC_WORDS | SUB_VARIANTS | STOPWORDS | GENERIC_CAPITALIZED_WORDS
    interior = words[1:]
    capitals = sum(bool(word[:1].isupper()) for word in interior)
    if interior and capitals / len(interior) > 0.4:
        return set()
    return {_stem(word.lower()) for word in words if word[:1].isupper()
            and _stem(word.lower()) not in excluded and len(word) >= 4
            and not any(char.isdigit() for char in word)}


def _capitalized_entities(title, named_entities):
    """Keep names identified in sentence-case coverage across outlet title styles."""
    words = re.findall(r"[^\W_]+(?:[.-][^\W_]+)*", unicodedata.normalize("NFC", title))
    return {_stem(word.lower()) for word in words if word[:1].isupper()
            and _stem(word.lower()) in named_entities}


def _adjacent_tokens(title):
    words = [_stem(word.lower()) for word in
             re.findall(r"[^\W_]+(?:[.-][^\W_]+)*", unicodedata.normalize("NFC", title))]
    return set(zip(words, words[1:]))


def _shared_entity_content_phrase(left_title, right_title, entities, content):
    """Require a shared adjacent entity/content pair, not an isolated keyword."""
    shared_pairs = _adjacent_tokens(left_title) & _adjacent_tokens(right_title)
    return any((entity, word) in shared_pairs or (word, entity) in shared_pairs
               for entity in entities for word in content if len(word) >= 4)


def _shared_entity_name_phrase(left_title, right_title, entities):
    return any(a in entities and b in entities
               for a, b in _adjacent_tokens(left_title) & _adjacent_tokens(right_title))


def _both_announce(title_a, title_b):
    return bool(ANNOUNCEMENT_RE.search(title_a) and ANNOUNCEMENT_RE.search(title_b))


def _cluster_entities(items):
    publishers = defaultdict(set)
    interior_uses = set()
    for item in items:
        publisher = item.get("publisher")
        if not isinstance(publisher, str) or not publisher:
            continue
        title = item.get("title", "")
        entities = _sentence_case_entities(title)
        words = re.findall(r"[^\W_]+(?:[.-][^\W_]+)*", unicodedata.normalize("NFC", title))
        interior_uses.update(_stem(word.lower()) for index, word in enumerate(words)
                             if index and word[:1].isupper())
        for index, word in enumerate(words):
            entity = _stem(word.lower())
            if entity not in entities:
                continue
            publishers[entity].add(publisher)
    return {entity for entity, sources in publishers.items()
            if len(sources) >= 2 and entity in interior_uses}


def titles_match(left, right, threshold=0.75, named_entities=None):
    a_date, b_date = instant(left.get("published_at")), instant(right.get("published_at"))
    if not a_date or not b_date or abs((a_date - b_date).total_seconds()) > 48 * 3600:
        return False
    a_raw = _expand_tokens(left.get("title", ""))
    b_raw = _expand_tokens(right.get("title", ""))
    if len(a_raw) < 2 or len(b_raw) < 2:
        return False

    if _has_conflict(a_raw, b_raw):
        return False

    # Whole-event recaps and keynotes often have very short, different titles.
    event_names = {token for token in a_raw & b_raw if len(token) >= 6 and re.search(r"(?:day|conf|con)$", token)}
    years = {token for token in _extract_versions(a_raw) & _extract_versions(b_raw) if re.fullmatch(r"20\d{2}", token)}
    formats = {"recap", "keynote", "highlights"}
    excluded = re.compile(r"\b(?:introduc\w*|releas\w*|launch\w*|announc\w*|session|workshop)\b", re.I)
    if (event_names and years and a_raw & formats and b_raw & formats
            and not excluded.search(left.get("title", "") + " " + right.get("title", ""))):
        return True

    if ((a_raw & formats and not b_raw & formats and excluded.search(right.get("title", ""))) or
        (b_raw & formats and not a_raw & formats and excluded.search(left.get("title", "")))):
        return False

    # Two papers or two repos from different canonical urls should not cross-merge on titles
    if left.get("kind") == "paper" and right.get("kind") == "paper":
        return False
    if left.get("kind") == "repository" and right.get("kind") == "repository":
        return False

    a_stem = {_stem(t) for t in a_raw}
    b_stem = {_stem(t) for t in b_raw}
    shared = a_stem & b_stem
    union = a_stem | b_stem
    if not union:
        return False

    jaccard = len(shared) / len(union)

    # Standard threshold (e.g. 0.75) applies to generic and same-publisher headlines
    if len(shared) >= 3 and jaccard >= threshold:
        return True

    # Same publisher requires standard threshold
    if left.get("publisher") and left.get("publisher") == right.get("publisher"):
        return False

    # Cross-publisher general matching rule from signals that exist for any story:
    shared_entities = {w for w in shared if _stem(w) in ENTITY_WORDS}
    if named_entities is None:
        named_entities = (_sentence_case_entities(left.get("title", "")) |
                          _sentence_case_entities(right.get("title", "")))
    shared_entities |= (_capitalized_entities(left.get("title", ""), named_entities) &
                        _capitalized_entities(right.get("title", ""), named_entities))
    shared_variants = {w for w in shared if _stem(w) in SUB_VARIANTS}
    shared_versions = _extract_versions(a_raw) & _extract_versions(b_raw)
    # An entity is the anchor, not independent evidence of an event. Counting
    # it as a specific word lets one shared name (or a capitalized common word)
    # satisfy both sides of the match rule.
    specific = {w for w in shared
                if _stem(w) not in (ENTITY_WORDS | TOPIC_WORDS | SUB_VARIANTS | shared_entities)
                and not any(c.isdigit() for c in w) and "-" not in w}

    # Signal 1: Shared entity + 2 or more shared specific tokens
    if len(shared_entities) >= 1 and len(specific) >= 2:
        return True

    if (len(shared_entities) >= 2 and specific and _shared_entity_name_phrase(
            left.get("title", ""), right.get("title", ""), shared_entities)):
        return True

    if _shared_entity_content_phrase(left.get("title", ""), right.get("title", ""),
                                     shared_entities, specific):
        return True

    # One shared content word can support a newly named product only when it
    # appears alongside an announcement in both headlines. A lone brand, common
    # verb or topic word is insufficient.
    if (shared_entities - ENTITY_WORDS and specific
            and _both_announce(left.get("title", ""), right.get("title", ""))):
        return True

    # Signal 2: Model variant launch: shared entity + shared model sub-variant + shared version
    if len(shared_entities) >= 1 and len(shared_variants) >= 1 and len(shared_versions) >= 1:
        return True

    return False


def _match(a, b, threshold, named_entities=None):
    if a.get("kind") == "event" or b.get("kind") == "event":
        return a.get("kind") == b.get("kind") and a.get("event_id", a["id"]) == b.get("event_id", b["id"])
    left = a.get("canonical_url") or canonical_url(a.get("url"))
    right = b.get("canonical_url") or canonical_url(b.get("url"))
    if left and right and left.startswith("https://arxiv.org/abs/") and right.startswith("https://arxiv.org/abs/"):
        if re.sub(r"v\d+$", "", left) == re.sub(r"v\d+$", "", right) and left != right:
            return False
    return bool(left and left == right) or titles_match(a, b, threshold, named_entities)


def primary_section(items):
    if any(item.get("kind") == "event" or item.get("status") == "upcoming" for item in items):
        return "upcoming"
    for kind, section in (("podcast", "listen"), ("video", "listen"), ("paper", "papers"), ("model", "models")):
        if any(item.get("kind") == kind for item in items):
            return section
    if any(item.get("group") in {"research", "newsletter"} for item in items):
        return "voices"
    if all(item.get("group") == "forum" for item in items):
        return "community"
    return "today"


def cluster_items(items, now, threshold=0.75):
    """Deterministic complete-link grouping, including exact-URL buckets first."""
    named_entities = _cluster_entities(items)
    buckets = {}
    for item in items:
        canonical = canonical_url(item.get("url"))
        if not canonical:
            continue
        normalized = dict(item, canonical_url=canonical)
        identity = "event:" + normalized.get("event_id", normalized["id"]) if normalized.get("kind") == "event" else canonical
        buckets.setdefault(identity, {})[normalized["id"]] = normalized
    groups = []
    for canonical in sorted(buckets):
        bucket = list(buckets[canonical].values())
        for group in groups:
            if all(_match(a, b, threshold, named_entities) for a in bucket for b in group):
                group.extend(bucket)
                break
        else:
            groups.append(bucket)
    stories = []
    for group in groups:
        group.sort(key=lambda item: (item.get("group") != "lab", item.get("group") == "forum",
                                     item.get("published_at") or "9999", item["source"], item["url"]))
        representative = group[0]
        anchor = min("event:" + item.get("event_id", item["id"]) if item.get("kind") == "event" else item["canonical_url"] for item in group)
        story_id = stable_id(anchor)
        coverage_ids = {stable_id("event:" + item.get("event_id", item["id"]) if item.get("kind") == "event" else item["canonical_url"]) for item in group}
        aliases = sorted(coverage_ids - {story_id})
        stories.append(dict(id=story_id, title=representative["title"], url=representative["url"],
                            summary=representative.get("summary", ""), published_at=representative.get("published_at"),
                            kind=representative.get("kind", "other"), time_basis=representative.get("time_basis", "unknown"),
                            primary_section=primary_section(group), groups=sorted({item.get("group", "lab") for item in group}),
                            coverage=group, source_count=len({item["publisher"] for item in group}),
                            aliases=aliases,
                            hot_score=None, hot_reason=None, hot_signals={}))
    return sorted(stories, key=lambda story: (story["published_at"] or "", story["id"]), reverse=True)

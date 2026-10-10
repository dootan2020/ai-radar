"""Conservative complete-link story clusters; all publisher coverage survives."""

import re
import unicodedata
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from radar.common import stable_id, web_url
from radar.items import instant, is_x_item, publisher_identity

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


def _is_paper_item(item):
    return item.get("kind") == "paper" or item.get("source") == "hf-papers"


def _same_x_post(left, right):
    left_ids = {left.get("id"), left.get("post_id")}
    right_ids = {right.get("id"), right.get("post_id")}
    if ((left.get("quoted_post_id") and left.get("quoted_post_id") in right_ids | {right.get("quoted_post_id")})
            or (right.get("quoted_post_id") and right.get("quoted_post_id") in left_ids)):
        return True
    left_text = left.get("summary") or left.get("title")
    right_text = right.get("summary") or right.get("title")
    return (isinstance(left_text, str) and isinstance(right_text, str)
            and " ".join(left_text.split()).casefold() == " ".join(right_text.split()).casefold())


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


FORUM_RESUBMISSION_SECONDS = 24 * 3600
CODE_HOSTS = {"github.com", "huggingface.co", "gitlab.com"}
NOT_REPOSITORY_PATHS = {"blog", "docs", "papers", "learn", "collections", "posts", "orgs", "organizations",
                        "topics", "features", "sponsors", "marketplace", "settings", "changelog", "events"}


def _outlet(item):
    """The outlet that wrote the headline.

    A forum post linking an article elsewhere carries that site's headline and
    is submitted by a different person each time, so two such posts are not one
    publisher rewording itself: they meet the cross-publisher rules.
    """
    if item.get("group") == "forum":
        url = item.get("canonical_url") or canonical_url(item.get("url"))
        host = (urlsplit(url).hostname or "") if url else ""
        discussion = canonical_url(item.get("discussion_url")) if item.get("discussion_url") else None
        if host and not (discussion and urlsplit(discussion).hostname == host):
            return "site:" + host.removeprefix("www.")
    return item.get("publisher")


def _is_commentary(item):
    """A post whose text is the author's own remark rather than a linked article's headline."""
    if item.get("kind") == "social":
        return True
    return item.get("group") == "forum" and _outlet(item) == item.get("publisher")


def _same_outlet(left, right, a_date, b_date):
    """Whether one outlet stands behind both headlines.

    Forum posts linking different sites count as different outlets only while they
    arrive together, as resubmissions of one piece of news do; a day apart, two
    posts that share a product name are usually different discussions.
    """
    if _outlet(left) and _outlet(left) == _outlet(right):
        return True
    return bool(left.get("group") == right.get("group") == "forum" and left.get("publisher")
                and left.get("publisher") == right.get("publisher")
                and abs((a_date - b_date).total_seconds()) > FORUM_RESUBMISSION_SECONDS)


def _repository_address(item):
    """The repository root an observation links to (owner/name), or None for any other page."""
    url = item.get("canonical_url") or canonical_url(item.get("url"))
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    segments = [segment for segment in parts.path.split("/") if segment]
    if segments and segments[0].lower() in NOT_REPOSITORY_PATHS:
        return None
    if host in CODE_HOSTS and (len(segments) == 2 or (
            host == "huggingface.co" and len(segments) == 3 and segments[0] in {"datasets", "spaces"})):
        return url
    return None


AMOUNT_WORDS = {"million", "billion", "trillion", "percent"}


def _same_outlet_retitle(a_stem, b_stem, shared, jaccard):
    """One outlet re-titling one report (an article and its video, or an updated headline).

    The figures survive the rewrite while the wording changes: both headlines carry
    exactly the same numbers (at least one that is not a year), at least two shared
    content words besides them, and close to half of all their words. A shared name
    alone never suffices.
    """
    a_figures = {w for w in a_stem if any(c.isdigit() for c in w)}
    b_figures = {w for w in b_stem if any(c.isdigit() for c in w)}
    if a_figures != b_figures or not any(not re.fullmatch(r"20\d{2}", w) for w in a_figures):
        return False
    parts = {_stem(part) for word in shared if "-" in word for part in word.split("-")}
    words = {w for w in shared if not any(c.isdigit() for c in w) and "-" not in w
             and w not in ENTITY_WORDS | TOPIC_WORDS | SUB_VARIANTS | AMOUNT_WORDS | parts}
    return len(words) >= 2 and jaccard >= 0.4


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

    # Research papers and non-paper coverage represent different item types;
    # title overlap alone cannot establish that they are the same story.
    if _is_paper_item(left) != _is_paper_item(right):
        return False

    # Two papers or two repos from different canonical urls should not cross-merge on titles
    if _is_paper_item(left) and _is_paper_item(right):
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

    # Below that bar, two different code or model repositories are two artifacts, however
    # alike their names ("…-Guard-2-22M" and "…-Guard-2-86M").
    if _repository_address(left) and _repository_address(right):
        return False

    # Same publisher: beyond the standard threshold, only its own re-title of one report
    if _same_outlet(left, right, a_date, b_date):
        return _same_outlet_retitle(a_stem, b_stem, shared, jaccard)

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
    # The halves of a shared hyphenated word repeat that one word; they are not
    # two more pieces of evidence ("open-source" must not also count "open" and "source").
    compound_parts = {_stem(part) for word in shared if "-" in word for part in word.split("-")}
    specific = {w for w in shared
                if _stem(w) not in (ENTITY_WORDS | TOPIC_WORDS | SUB_VARIANTS | shared_entities | compound_parts)
                and not any(c.isdigit() for c in w) and "-" not in w}

    # Signal 1: Shared entity + 2 or more shared specific tokens
    if len(shared_entities) >= 1 and len(specific) >= 2:
        return True

    if (len(shared_entities) >= 2 and specific and _shared_entity_name_phrase(
            left.get("title", ""), right.get("title", ""), shared_entities)):
        return True

    # A person's own post (a social post, or a forum self-post) is commentary in
    # free wording, not a headline: "the Claude team" in a remark is not the
    # "Claude Team" plan in a report. One shared name-plus-word phrase or one
    # announcement word is too little to attach it to an event; it needs the
    # two independent content words of the rule above.
    commentary = _is_commentary(left) or _is_commentary(right)

    if not commentary and _shared_entity_content_phrase(left.get("title", ""), right.get("title", ""),
                                                         shared_entities, specific):
        return True

    # One shared content word can support a newly named product only when it
    # appears alongside an announcement in both headlines. A lone brand, common
    # verb or topic word is insufficient.
    if (not commentary and shared_entities - ENTITY_WORDS and specific
            and _both_announce(left.get("title", ""), right.get("title", ""))):
        return True

    # Signal 2: Model variant launch: shared entity + shared model sub-variant + shared version
    if len(shared_entities) >= 1 and len(shared_variants) >= 1 and len(shared_versions) >= 1:
        return True

    return False


def _match(a, b, threshold, named_entities=None):
    if a.get("kind") == "event" or b.get("kind") == "event":
        return a.get("kind") == b.get("kind") and a.get("event_id", a["id"]) == b.get("event_id", b["id"])
    left = (canonical_url(a.get("linked_url")) if is_x_item(a) and a.get("linked_url")
            else a.get("canonical_url") or canonical_url(a.get("url")))
    right = (canonical_url(b.get("linked_url")) if is_x_item(b) and b.get("linked_url")
             else b.get("canonical_url") or canonical_url(b.get("url")))
    if left and right and left.startswith("https://arxiv.org/abs/") and right.startswith("https://arxiv.org/abs/"):
        if re.sub(r"v\d+$", "", left) == re.sub(r"v\d+$", "", right) and left != right:
            return False
    if left and left == right:
        return True
    if is_x_item(a) and is_x_item(b):
        return _same_x_post(a, b)
    return titles_match(a, b, threshold, named_entities)


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
        canonical = (canonical_url(item.get("linked_url")) if is_x_item(item) and item.get("linked_url")
                     else canonical_url(item.get("url")))
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
                            coverage=group, source_count=len({publisher_identity(item) for item in group}),
                            aliases=aliases,
                            hot_score=None, hot_reason=None, hot_signals={}))
    return sorted(stories, key=lambda story: (story["published_at"] or "", story["id"]), reverse=True)


def _story_words(story):
    return {_stem(token) for item in story.get("coverage", []) if isinstance(item, dict)
            for token in _expand_tokens(item.get("title", ""))}


def merge_repeated_events(stories, threshold=0.75):
    """Fold a carried story into the story that tells the same event.

    Retention carries a published story forward by id or URL alone, so an outlet
    re-titling an article under a new URL, or two stories split by an earlier
    build, would stay two cards. A carried story joins another when that story
    already lists it as an alias, or when every pair of their observations passes
    the same complete-link test that builds fresh clusters. Fresh stories are not
    compared with each other: `cluster_items` already decided those. The story
    kept is fresh before carried, then the one with more coverage; it keeps its
    headline, translation and summary and gains the other's coverage and id.
    """
    stories = [story for story in stories if isinstance(story, dict)]
    order = sorted(range(len(stories)), key=lambda index: (
        bool(stories[index].get("carried")), -len(stories[index].get("coverage") or []),
        stories[index].get("published_at") or "9999", str(stories[index].get("id"))))
    items = [item for story in stories for item in story.get("coverage", []) if isinstance(item, dict)]
    named_entities = _cluster_entities(items)
    alias_owner = {}                      # story id or alias -> position in `kept`
    kept, words, postings = [], [], defaultdict(list)
    for index in order:
        story = stories[index]
        if not story.get("carried") or story.get("kind") == "event":
            target = None
        else:
            target = alias_owner.get(story.get("id"))
        if target is None and story.get("carried") and story.get("kind") != "event":
            shared = defaultdict(int)
            for word in _story_words(story):
                for position in postings[word]:
                    shared[position] += 1
            for position in sorted(position for position, count in shared.items() if count >= 2):
                other = kept[position]
                if other.get("kind") != "event" and all(
                        _match(a, b, threshold, named_entities)
                        for a in story.get("coverage", []) for b in other.get("coverage", [])):
                    target = position
                    break
        if target is None:
            target = len(kept)
            kept.append(story)
            words.append(set())
            for alias in story.get("aliases") or []:
                alias_owner.setdefault(alias, target)
        else:
            _fold(kept[target], story)
            for alias in [story.get("id")] + list(story.get("aliases") or []):
                alias_owner.setdefault(alias, target)
        for word in _story_words(story) - words[target]:
            words[target].add(word)
            postings[word].append(target)
    kept_ids = {id(story) for story in kept}
    return [story for story in stories if id(story) in kept_ids]


def _fold(target, story):
    coverage = target.setdefault("coverage", [])
    present = {item.get("id") for item in coverage if isinstance(item, dict)}
    for item in story.get("coverage") or []:
        if isinstance(item, dict) and item.get("id") not in present:
            coverage.append(item)
            present.add(item.get("id"))
    target["aliases"] = sorted((set(target.get("aliases") or []) | set(story.get("aliases") or [])
                                | {story.get("id")}) - {target.get("id"), None})
    target["source_count"] = len({publisher_identity(item) for item in coverage if isinstance(item, dict)})
    target["groups"] = sorted({item.get("group", "lab") for item in coverage if isinstance(item, dict)})
    target["primary_section"] = primary_section(coverage)

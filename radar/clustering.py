"""Conservative complete-link story clusters; all publisher coverage survives."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from radar.common import stable_id, web_url
from radar.items import instant

STOPWORDS = set("a an the and or for to of in on with from by as at is are was were be been this that it its our your new now how what why when can will has have had about into more most first introducing announces announced releases released release launch launches launched".split())
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "ref_url"}


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
        match = re.fullmatch(r"/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?", path)
        if match:
            return "https://arxiv.org/abs/" + match[1]
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in TRACKING]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(sorted(query)), ""))


def _tokens(title):
    return set(token for token in re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", title.lower())
               if token not in STOPWORDS and (len(token) >= 3 or any(c.isdigit() for c in token)))


def titles_match(left, right, threshold=0.75):
    a_date, b_date = instant(left.get("published_at")), instant(right.get("published_at"))
    if not a_date or not b_date or abs((a_date - b_date).total_seconds()) > 48 * 3600:
        return False
    a, b = _tokens(left.get("title", "")), _tokens(right.get("title", ""))
    numbers_a = {token for token in a if any(c.isdigit() for c in token)}
    numbers_b = {token for token in b if any(c.isdigit() for c in token)}
    if numbers_a != numbers_b:
        return False
    # Whole-event recaps and keynotes often have very short, different titles.
    # Require a named compound event + year and explicit whole-event formats;
    # product launches and session titles must still pass normal title matching.
    event_names = {token for token in a & b if len(token) >= 6 and re.search(r"(?:day|conf|con)$", token)}
    years = {token for token in numbers_a if re.fullmatch(r"20\d{2}", token)}
    formats = {"recap", "keynote", "highlights"}
    excluded = re.compile(r"\b(?:introduc\w*|releas\w*|launch\w*|announc\w*|session|workshop)\b", re.I)
    if (event_names and years and a & formats and b & formats
            and not excluded.search(left.get("title", "") + " " + right.get("title", ""))):
        return True
    return len(a & b) >= 3 and len(a & b) / max(1, len(a | b)) >= threshold


def _match(a, b, threshold):
    if a.get("kind") == "event" or b.get("kind") == "event":
        return a.get("kind") == b.get("kind") and a.get("event_id", a["id"]) == b.get("event_id", b["id"])
    left = a.get("canonical_url") or canonical_url(a.get("url"))
    right = b.get("canonical_url") or canonical_url(b.get("url"))
    if left and right and left.startswith("https://arxiv.org/abs/") and right.startswith("https://arxiv.org/abs/"):
        if re.sub(r"v\d+$", "", left) == re.sub(r"v\d+$", "", right) and left != right:
            return False
    return bool(left and left == right) or titles_match(a, b, threshold)


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
            if all(_match(a, b, threshold) for a in bucket for b in group):
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
        stories.append(dict(id=stable_id(anchor), title=representative["title"], url=representative["url"],
                            summary=representative.get("summary", ""), published_at=representative.get("published_at"),
                            kind=representative.get("kind", "other"), time_basis=representative.get("time_basis", "unknown"),
                            primary_section=primary_section(group), groups=sorted({item.get("group", "lab") for item in group}),
                            coverage=group, source_count=len({item["publisher"] for item in group}),
                            hot_score=None, hot_reason=None, hot_signals={}))
    return sorted(stories, key=lambda story: (story["published_at"] or "", story["id"]), reverse=True)

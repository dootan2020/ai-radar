"""Bounded, labelled evidence selection; publisher bodies never enter public stories."""

from copy import deepcopy
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from radar.common import web_url

SELECTION_VERSION = "paragraphs-1"
MAX_SOURCE_CHARS = 16000
OFFICIAL_HOSTS = {
    "anthropic.com", "openai.com", "deepmind.google", "blog.google",
    "research.google", "ai.google", "ai.meta.com", "about.fb.com",
    "microsoft.com", "blogs.microsoft.com", "nvidia.com", "blogs.nvidia.com",
    "mistral.ai", "x.ai", "deepseek.com", "qwenlm.github.io", "huggingface.co",
    "typesafe.ai", "aws.amazon.com", "amazon.science",
}
DETAIL_PATH = re.compile(r"/(?:research|news|blog|blogs|index|publications|posts|announcements)/.+", re.I)
IMPORTANT = re.compile(
    r"\b(?:however|limit\w*|not|risk\w*|safety|incident\w*|evaluation\w*|"
    r"result\w*|conclu\w*|mitigat\w*|response|funding|valuation|million|billion)\b", re.I)


def primary_link(links, article_url, title, article_text):
    """Follow only a linked official post with a subject also named in the article."""
    article_host = urlsplit(article_url).hostname
    context = (title + " " + article_text).casefold()
    for href, label in links:
        target = web_url(urljoin(article_url, href))
        if not target:
            continue
        parts = urlsplit(target)
        host = (parts.hostname or "").removeprefix("www.")
        if (parts.scheme != "https" or host not in OFFICIAL_HOSTS
                or not DETAIL_PATH.search(parts.path) or parts.username or parts.password):
            continue
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        if target == article_url or host == (article_host or "").removeprefix("www."):
            continue
        subject = {"blog.google": "google", "deepmind.google": "deepmind",
                   "ai.meta.com": "meta", "about.fb.com": "meta",
                   "blogs.microsoft.com": "microsoft", "blogs.nvidia.com": "nvidia",
                   "aws.amazon.com": "amazon", "qwenlm.github.io": "qwen"}.get(host, host.split(".")[0])
        # A company in the body plus a relevant in-body anchor; navigation is excluded upstream.
        anchor_words = re.findall(r"[a-zA-Z][a-zA-Z-]{3,}", label.casefold())
        if subject in context and (subject in label.casefold() or any(word in title.casefold() for word in anchor_words)
                                   or re.search(r"report|research|study|post|paper|announc", label, re.I)):
            return target
    return None


def source_record(sid, role, url, title, publisher, text, *, fetched_at="", excerpt=False):
    paragraphs = [" ".join(p.split()) for p in text.splitlines() if p.strip()]
    return {
        "id": sid, "role": role, "url": url, "title": title[:400],
        "publisher": {"id": sid + ":publisher", "text": publisher or urlsplit(url).hostname or "Source"},
        "fetched_at": fetched_at, "body_complete": not excerpt,
        "excerpt_kind": "publisher_excerpt" if excerpt else None,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "paragraphs": [{"id": f"{sid}:p{i + 1:03}", "text": p} for i, p in enumerate(paragraphs)],
    }


def select_paragraphs(source, limit):
    """Keep whole paragraphs spread across the body, with limits/responses prioritized."""
    result = deepcopy(source)
    paragraphs = source["paragraphs"]
    if sum(len(p["text"]) for p in paragraphs) <= limit:
        return result
    count = len(paragraphs)
    anchors = [0, count - 1, count // 2, count // 3, 2 * count // 3]
    ranked = sorted(range(count), key=lambda i: (-len(IMPORTANT.findall(paragraphs[i]["text"])), i))
    chosen, used = set(), 0
    for index in dict.fromkeys(anchors + ranked):
        size = len(paragraphs[index]["text"])
        if size + used <= limit:
            chosen.add(index)
            used += size
    result["paragraphs"] = [p for i, p in enumerate(paragraphs) if i in chosen]
    result["omitted_paragraph_ids"] = [p["id"] for i, p in enumerate(paragraphs) if i not in chosen]
    result["body_complete"] = False
    return result


def fit_inputs(inputs, max_chars):
    fitted = {"id": inputs["id"], "selection_version": SELECTION_VERSION, "sources": [],
              "missing_primary": bool(inputs.get("missing_primary")),
              "linked_primary": deepcopy(inputs.get("linked_primary"))}
    if len(fitted["id"]) > 500:
        return None
    remaining = MAX_SOURCE_CHARS
    for source in inputs.get("sources", []):
        limit = {"outlet": 8000, "primary": 10000, "coverage": 1500}[source["role"]]
        selected = select_paragraphs(source, min(limit, remaining))
        if selected["paragraphs"]:
            fitted["sources"].append(selected)
            remaining -= sum(len(p["text"]) for p in selected["paragraphs"])
    # A smaller caller limit drops complete paragraphs, never clips a factual clause.
    while fitted["sources"] and len(json.dumps(fitted, ensure_ascii=False)) > max_chars:
        source = fitted["sources"][-1]
        removed = source["paragraphs"].pop()
        source["body_complete"] = False
        source.setdefault("omitted_paragraph_ids", []).append(removed["id"])
        if not source["paragraphs"]:
            fitted["sources"].pop()
    if not fitted["sources"] or fitted["sources"][0]["role"] != "outlet":
        return None
    if sum(len(p["text"]) for p in fitted["sources"][0]["paragraphs"]) < 300:
        return None
    if inputs.get("missing_primary") or any(s["role"] == "primary" for s in inputs.get("sources", [])):
        fitted["missing_primary"] = not any(s["role"] == "primary" for s in fitted["sources"])
    return fitted


PUBLIC_SUMMARY_FIELDS = (
    "key_points", "key_points_machine", "key_points_source", "key_points_prompt_version",
    "editorial_headline_vi", "short_vi", "takeaway_vi", "summary_sources", "summary_limitations",
)


def clear_summary(story):
    for key in PUBLIC_SUMMARY_FIELDS:
        story.pop(key, None)


def publish_summary(story, output, inputs, version):
    """Explicit projection: no paragraphs, generated URLs or evidence quotes can escape."""
    story.update(
        key_points=[point["text"] for point in output["key_points"]],
        key_points_machine=True, key_points_source="machine", key_points_prompt_version=version,
        editorial_headline_vi=output["title_vi"]["text"], summary_limitations=output["limitations"],
        summary_sources=[{"id": source["id"], "role": source["role"],
                          "name": source["publisher"]["text"], "url": source["url"]}
                         for source in inputs["sources"]
                         if source["role"] in {"outlet", "primary"} or source["id"] in output["used_source_ids"]],
    )
    linked = inputs.get("linked_primary")
    if linked and not any(s["url"] == linked["url"] for s in story["summary_sources"]):
        story["summary_sources"].append({"id": "primary", "role": "primary",
                                         "name": linked["name"], "url": linked["url"]})

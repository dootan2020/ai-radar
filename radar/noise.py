"""Observations that are not news for an AI reader, each refused with a one-line reason.

Refused observations are skipped, not deleted: they leave the live feed and the newsroom,
while the append-only story history and the immutable daily edition files keep what was
already published.
"""

import re
from urllib.parse import urlsplit

# Applicant-tracking and job-board hosts: a link here is a vacancy, whoever posts it.
JOB_HOSTS = {
    "jobs.ashbyhq.com", "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co",
    "apply.workable.com", "jobs.workable.com", "jobs.smartrecruiters.com", "workatastartup.com",
    "wellfound.com", "angel.co",
}
# Forum job ads and hiring threads ("X (YC W25) is hiring ...", "Ask HN: Who is hiring?").
# Press reporting that a company hires is news and is not matched: only forum posts are.
HIRING_TITLE = re.compile(
    r"\b(?:is|are|now|we(?:'|’)?re|we are)\s+hiring\b|\bwho\s+is\s+hiring\b"
    r"|\bwho\s+wants\s+to\s+be\s+hired\b|\bseeking\s+freelancer\b", re.I)
JOB_PATH = re.compile(r"^/(?:jobs?|careers?)(?:/|$)|/companies/[^/]+/jobs(?:/|$)", re.I)

# A social post's URL is the post itself: there is no article behind it to open. When its text
# is no more than its headline and fits in one short post, the story page would repeat one or two
# sentences as headline, excerpt and body, so the post is skipped (captain, 2026-10-28). The
# floor is about the item: a long post, or one whose text says more than its headline, stays.
HEADLINE_ONLY_MAX_CHARS = 300

REASONS = {
    "job-post": "tin tuyển dụng, không phải tin AI",
    "headline-only": "bài đăng ngắn chỉ có một câu tiêu đề, không có bài viết phía sau",
}


def _words(text):
    return re.sub(r"\W+", " ", text.casefold()).strip() if isinstance(text, str) else ""


def headline_only(item):
    """True when a social post's text adds nothing to its headline and is one short post."""
    if item.get("kind") != "social":
        return False
    title, text = item.get("title"), item.get("summary")
    longest = max((t for t in (title, text) if isinstance(t, str)), key=len, default="")
    if len(longest.strip()) > HEADLINE_ONLY_MAX_CHARS:
        return False
    title_words, text_words = _words(title), _words(text)
    # Headlines are cut with an ellipsis, so either may be a prefix of the other.
    return not text_words or not title_words or text_words.startswith(title_words) \
        or title_words.startswith(text_words)


def _host(url):
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.") if isinstance(url, str) else ""
    except ValueError:
        return ""


def noise_reason(item):
    """Return a reason code from REASONS when the observation is not news, else None."""
    url = item.get("url") if isinstance(item.get("url"), str) else ""
    host = _host(url)
    if host in JOB_HOSTS:
        return "job-post"
    if host == "ycombinator.com" and JOB_PATH.search(urlsplit(url).path):
        return "job-post"
    if item.get("group") == "forum" and HIRING_TITLE.search(item.get("title") or ""):
        return "job-post"
    if headline_only(item):
        return "headline-only"
    return None

"""Observations that are not news for an AI reader, each refused with a one-line reason."""

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

REASONS = {"job-post": "tin tuyển dụng, không phải tin AI"}


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
    return None

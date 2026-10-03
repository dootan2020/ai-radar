"""Bounded aggregate-only GitHub API calls; never collect stargazer identities."""

import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from radar.transport import Fetcher, MAX_BYTES, ResponseText, USER_AGENT

API = "https://api.github.com"
MAX_CALLS = 140
MAX_SEARCH_CALLS = 60
MAX_CORE_CALLS = 80
CORE_RESERVE = 500


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class APIError(Exception):
    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.status = status


class GitHubAPI:
    def __init__(self, transport=None, timeout=210, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + timeout
        self.next_search = 0
        self.stopped = set()
        self.requests = []
        self.calls = dict(search=0, core=0)
        self.fetch = Fetcher(time.monotonic() + timeout, transport or self._read)

    def _read(self, url):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise APIError("missing_GITHUB_TOKEN")
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json",
                          "Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2026-03-10"})
        try:
            with build_opener(NoRedirect).open(request, timeout=8) as response:
                self._quota(response.headers, url)
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise APIError("response_too_large", response.status)
                return ResponseText(body.decode("utf-8"), response.status, response.geturl())
        except HTTPError as error:
            self._quota(error.headers, url)
            bucket = "search" if "/search/" in url else "core"
            # A permissions refusal is local. Rate limiting stops the bucket without retry storms.
            body = error.read(8192).decode("utf-8", errors="replace").lower()
            secondary = error.code in (403, 429) and (any(term in body for term in ("secondary rate", "abuse"))
                        or "rate limit" in body and error.headers.get("X-RateLimit-Remaining") != "0")
            limited = secondary or error.code == 429 or error.headers.get("Retry-After") or error.headers.get("X-RateLimit-Remaining") == "0"
            if limited:
                self.stopped.add(bucket)
            if secondary or error.headers.get("Retry-After") or error.code == 429:
                self.stopped.update(("search", "core"))
            raise APIError("rate_limited" if limited else "http_refused", error.code) from None

    def _quota(self, headers, url):
        bucket = "search" if "/search/" in url else "core"
        remaining = headers.get("X-RateLimit-Remaining")
        if remaining is not None and remaining.isdigit() and int(remaining) <= (CORE_RESERVE if bucket == "core" else 0):
            self.stopped.add(bucket)

    def get(self, path, **params):
        bucket = "search" if path.startswith("/search/") else "core"
        url = API + path + ("?" + urlencode(params) if params else "")
        if (bucket in self.stopped or len(self.requests) >= MAX_CALLS
                or self.calls[bucket] >= (MAX_SEARCH_CALLS if bucket == "search" else MAX_CORE_CALLS)):
            raise APIError("budget_exhausted")
        if self.clock() >= self.deadline:
            raise APIError("deadline")
        if bucket == "search":
            delay = max(0, self.next_search - self.clock())
            if self.clock() + delay >= self.deadline:
                raise APIError("deadline")
            self.sleep(delay)
            self.next_search = self.clock() + 2.5
        record = dict(url=url, http_status=None, status="pending")
        self.requests.append(record)
        self.calls[bucket] += 1
        try:
            raw = self.fetch(url)
            record["http_status"] = getattr(raw, "status", None)
            parsed = json.loads(raw)
        except APIError as error:
            record.update(status=str(error), http_status=error.status)
            raise
        except (ValueError, OSError, TimeoutError):
            record["status"] = "invalid_or_unavailable"
            raise APIError("invalid_or_unavailable") from None
        record["status"] = "ok"
        return parsed


def native_history(api, full_name):
    """Calendar-week created events are evidence only, never seven-day net gains."""
    try:
        result = api.get(f"/repos/{full_name}/stargazers/history", per_page=2, page=1)
    except APIError as error:
        return dict(status=str(error), http_status=error.status, method="calendar_week_added", usable_for_net=False)
    valid = isinstance(result, list) and len(result) <= 2
    if valid:
        for week in result:
            valid = (isinstance(week, dict) and type(week.get("week")) is int and week["week"] >= 0
                     and type(week.get("total")) is int and week["total"] >= 0
                     and isinstance(week.get("days"), list) and len(week["days"]) == 7
                     and all(type(day) is int and day >= 0 for day in week["days"])
                     and sum(week["days"]) == week["total"])
            if not valid:
                break
    return dict(status=("ok" if result else "empty") if valid else "unknown_schema",
                method="calendar_week_added", usable_for_net=False,
                boundary="provider_calendar_non_utc", weeks=result if valid else [])

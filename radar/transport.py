"""Bound network resources even when DNS or a remote server stalls."""

import os
import queue
import threading
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, install_opener, urlopen

USER_AGENT = "AI-Radar/1.0 (public news reader; Python urllib; no inference)"
MAX_BYTES = 8 * 1024 * 1024
MAX_CONNECTIONS = 8
FETCH_TIMEOUT = 10


class SafeRedirectHandler(HTTPRedirectHandler):
    """Prevent sending credentials like GITHUB_TOKEN to untrusted hosts on redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req:
            target_host = urlparse(newurl).hostname
            if target_host != "api.github.com":
                if "Authorization" in new_req.headers:
                    del new_req.headers["Authorization"]
                if hasattr(new_req, "unredirected_hdrs") and "Authorization" in new_req.unredirected_hdrs:
                    del new_req.unredirected_hdrs["Authorization"]
        return new_req


class ResponseText(str):
    """Decoded response with observed HTTP metadata, still a normal string."""

    def __new__(cls, value, status=None, url=None):
        instance = super().__new__(cls, value)
        instance.status = status
        instance.url = url
        return instance


install_opener(build_opener(SafeRedirectHandler))


def read_url(url):
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    token = os.environ.get("GITHUB_TOKEN")
    host = urlparse(url).hostname
    if token and host == "api.github.com":
        headers["Authorization"] = f"token {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=8) as response:
        try:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("Source response exceeds 8 MiB limit")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Source response exceeds 8 MiB limit")
            return ResponseText(raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace"),
                                response.status, response.geturl())
        except Exception as error:
            # A response was received even if reading/decoding its body failed.
            error.http_status = response.status
            raise


class Fetcher:
    """A hard wall-clock deadline surrounds even injected transport functions.

    urllib's socket timeout alone cannot bound DNS lookup or trickling bodies.
    Daemon threads isolate those waits; a semaphore bounds actual open requests.
    """

    def __init__(self, deadline, transport=None, timeout=FETCH_TIMEOUT):
        self.deadline = deadline
        self.transport = transport or read_url
        self.timeout = timeout
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.requests = []
        self.lock = threading.Lock()

    def scoped(self, source_id):
        parent = self

        class Scoped:
            deadline = parent.deadline

            def __call__(self, url):
                return parent(url, source_id=source_id)

        return Scoped()

    def evidence(self, source_id):
        with self.lock:
            return [dict(record) for record in self.requests if record["source"] == source_id]

    def __call__(self, url, source_id=None):
        try:
            value = self._fetch(url)
        except Exception as error:
            record = dict(source=source_id, url=url, http_status=getattr(error, "http_status", getattr(error, "code", None)), error=f"{type(error).__name__}: {error}"[:300])
            with self.lock:
                self.requests.append(record)
            raise
        with self.lock:
            self.requests.append(dict(source=source_id, url=url, http_status=getattr(value, "status", None), error=None))
        return value

    def _fetch(self, url):
        deadline = min(time.monotonic() + self.timeout, self.deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self.slots.acquire(timeout=max(0, remaining)):
            raise TimeoutError("Fetch deadline reached waiting for connection slot")
        result = queue.Queue(maxsize=1)

        def request():
            try:
                result.put((True, self.transport(url)))
            except Exception as error:
                result.put((False, error))
            finally:
                self.slots.release()

        threading.Thread(target=request, daemon=True, name="radar-fetch").start()
        remaining = deadline - time.monotonic()
        try:
            ok, value = result.get(timeout=max(0, remaining))
        except queue.Empty as error:
            raise TimeoutError("Source exceeded fetch deadline") from error
        if not ok:
            raise value
        if not isinstance(value, str):
            raise ValueError("Transport must return decoded text")
        if len(value.encode("utf-8")) > MAX_BYTES:
            error = ValueError("Source response exceeds 8 MiB limit")
            error.http_status = getattr(value, "status", None)
            raise error
        return value

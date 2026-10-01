"""Bound network resources even when DNS or a remote server stalls."""

import queue
import threading
import time
from urllib.request import Request, urlopen

USER_AGENT = "AI-Radar/1.0 (public news reader; Python urllib; no inference)"
MAX_BYTES = 8 * 1024 * 1024
MAX_CONNECTIONS = 8
FETCH_TIMEOUT = 10


def read_url(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(request, timeout=8) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES:
            raise ValueError("Source response exceeds 8 MiB limit")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Source response exceeds 8 MiB limit")
        return raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")


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

    def __call__(self, url):
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
            raise ValueError("Source response exceeds 8 MiB limit")
        return value

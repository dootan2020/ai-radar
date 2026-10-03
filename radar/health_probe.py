"""Bounded, credential-free checks of the public Pages site."""

from datetime import datetime, timezone
from http.client import HTTPException
from html.parser import HTMLParser
import json
import re
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from radar.items import instant
from radar.publication import STALE_AFTER_SECONDS

SITE_URL = "https://dootan2020.github.io/ai-radar/"
PRIMARY_ASSETS = ("tokens.css", "styles.css", "app.js")
MAX_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = 10
PROBE_TIMEOUT = 60
MAX_ASSETS = 30


class ProbeError(ValueError):
    """A bounded diagnostic safe to publish without remote response text."""


def local_asset(reference, parent):
    """Only unambiguous, public URLs within the Pages project may be checked."""
    url = urljoin(parent, reference)
    parts, site = urlsplit(url), urlsplit(SITE_URL)
    if parts.hostname != site.hostname:
        return None
    if (parts.scheme != site.scheme or parts.netloc != site.netloc
            or parts.query or parts.fragment or "?" in reference or "#" in reference
            or not parts.path.startswith(site.path)
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", parts.path)
            or any(part in (".", "..") for part in parts.path.split("/"))):
        raise ProbeError("Invalid local asset reference.")
    return url


# Lex only enough to find literal module references without matching examples
# inside comments, strings or templates. This is not a JavaScript evaluator.
JS_TOKEN = re.compile(r'''//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`|[\w$]+|[^\s]''')


def module_references(source):
    tokens = (match[0] for match in JS_TOKEN.finditer(source)
              if not match[0].startswith(("//", "/*")))
    previous, pending = None, None
    while True:
        token, pending = pending or next(tokens, ""), None
        if not token:
            break
        if token in ("import", "export") and previous != ".":
            head = next(tokens, "")
            if token == "import" and head == "(":
                literal = next(tokens, "")
                if literal.startswith(("'", '"')) and next(tokens, "") in (")", ","):
                    yield literal[1:-1]
            elif token == "import" and head.startswith(("'", '"')):
                yield head[1:-1]
            elif head != "." and (token == "import" or head in ("*", "{")):
                for part in tokens:
                    if part == ";":
                        break
                    if part in ("import", "export"):
                        pending = part
                        break
                    if token == "export" and part == "}":
                        part = next(tokens, "")
                        if part != "from":
                            pending = part
                            break
                    if part == "from":
                        literal = next(tokens, "")
                        if literal.startswith(("'", '"')):
                            yield literal[1:-1]
                            break
        previous = token


class Homepage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.markers = set()
        self.assets = set()
        self.modules = set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "meta" and attrs.get("property") == "og:site_name" and attrs.get("content") == "ai·radar":
            self.markers.add("identity")
        if (tag, attrs.get("id")) in (("main", "top"), ("section", "board")):
            self.markers.add(attrs["id"])
        reference = attrs.get("src") if tag == "script" else None
        relations = (attrs.get("rel") or "").split()
        if tag == "link" and {"stylesheet", "modulepreload"}.intersection(relations):
            reference = attrs.get("href")
        if not reference:
            return
        url = local_asset(reference, SITE_URL)
        if url:
            self.assets.add(url)
            if tag == "script" or "modulepreload" in relations:
                self.modules.add(url)
            if len(self.assets) > MAX_ASSETS:
                raise ProbeError("Homepage asset inventory exceeds bounded probe capacity.")
        if tag == "script" and attrs.get("type") == "module" and url == urljoin(SITE_URL, "app.js"):
            self.markers.add("app")


def fetch(url, deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ProbeError("Probe deadline exceeded.")
    request = Request(url, headers={"User-Agent": "ai-radar-health-monitor", "Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=min(REQUEST_TIMEOUT, remaining)) as response:
            if response.status != 200:
                raise ProbeError(f"HTTP {response.status}; expected 200.")
            if response.geturl() != url:
                raise ProbeError("Unexpected redirect; expected the requested endpoint.")
            chunks, size = [], 0
            while True:
                if monotonic() >= deadline:
                    raise ProbeError("Probe deadline exceeded.")
                # One buffered/socket read lets us re-check the overall deadline
                # between chunks, even when a server drips a response slowly.
                block = response.read1(min(65536, MAX_BYTES + 1 - size))
                size += len(block)
                if size > MAX_BYTES:
                    raise ProbeError("Response exceeds size limit.")
                if not block:
                    break
                chunks.append(block)
            return b"".join(chunks)
    except HTTPError as error:
        raise ProbeError(f"HTTP {error.code}; expected 200.") from None
    except (URLError, OSError, TimeoutError, HTTPException):
        raise ProbeError("Network request failed or timed out.") from None


def parse_snapshot(raw):
    def reject_constant(value):
        raise ValueError("Non-JSON numeric constant")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ProbeError("Snapshot is not valid JSON.") from None


def snapshot_time(raw, now):
    value = parse_snapshot(raw)
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != 2 or not isinstance(value.get("stories"), list)
            or not isinstance(value.get("sources"), list) or not isinstance(value.get("sections"), dict)):
        raise ProbeError("Snapshot does not match the page's schema v2 containers.")
    stamp = instant(value.get("generated_at"))
    if stamp is None:
        raise ProbeError("Snapshot generated_at is missing, invalid or timezone-free.")
    age = (now - stamp).total_seconds()
    if age < 0:
        raise ProbeError("Snapshot generated_at is in the future.")
    if age > STALE_AFTER_SECONDS:
        raise ProbeError(f"Snapshot is stale: age {int(age)} seconds exceeds {STALE_AFTER_SECONDS} seconds.")
    return value["generated_at"]


def probe():
    now = datetime.now(timezone.utc)
    report = {"checked_at": now.isoformat(), "generated_at": None, "checks": []}
    deadline = monotonic() + PROBE_TIMEOUT
    assets = {urljoin(SITE_URL, path) for path in PRIMARY_ASSETS}
    modules = {urljoin(SITE_URL, "app.js")}

    def check(identifier, url, validate):
        try:
            validate(fetch(url, deadline))
            row = dict(id=identifier, url=url, ok=True, detail="HTTP 200; check passed.")
        except (ProbeError, UnicodeError, ValueError) as error:
            # Only our own messages can leave the HTTP boundary.
            detail = str(error) if isinstance(error, ProbeError) else "Invalid response encoding or content."
            row = dict(id=identifier, url=url, ok=False, detail=detail)
        report["checks"].append(row)

    def homepage(raw):
        page = Homepage()
        page.feed(raw.decode("utf-8"))
        if page.markers != {"identity", "top", "board", "app"}:
            raise ProbeError("Homepage identity or required page markers missing.")
        required = {urljoin(SITE_URL, path) for path in PRIMARY_ASSETS}
        if not required <= page.assets:
            raise ProbeError("Homepage is missing a primary stylesheet or script reference.")
        if len(assets | page.assets) > MAX_ASSETS:
            raise ProbeError("Homepage asset inventory exceeds bounded probe capacity.")
        assets.update(page.assets)
        modules.update(page.modules)

    def snapshot(raw):
        # Preserve the observed time even when its age subsequently fails policy.
        try:
            value = parse_snapshot(raw)
            stamp = instant(value.get("generated_at")) if isinstance(value, dict) else None
            if stamp is not None:
                report["generated_at"] = stamp.isoformat()
        except (ValueError, UnicodeError):
            pass
        snapshot_time(raw, datetime.now(timezone.utc))

    def asset(raw, url):
        if not raw.strip() or raw.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise ProbeError("Asset is empty or returned an HTML page.")
        if url in modules:
            for reference in module_references(raw.decode("utf-8")):
                dependency = local_asset(reference, url)
                if dependency is None:
                    continue
                if dependency not in assets and len(assets) >= MAX_ASSETS:
                    raise ProbeError("Module asset inventory exceeds bounded probe capacity.")
                assets.add(dependency)
                modules.add(dependency)

    check("homepage", SITE_URL, homepage)
    check("snapshot", urljoin(SITE_URL, "data/radar.json"), snapshot)
    checked = set()
    while assets - checked:
        url = min(assets - checked)
        checked.add(url)
        check("asset:" + url.removeprefix(SITE_URL), url, lambda raw: asset(raw, url))
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    return report

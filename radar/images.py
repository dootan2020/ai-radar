"""Image resolution and caching for stories.

Resolves story pictures strictly from source-published metadata in trust order:
1. Cached image (previously verified, disk cache or seed)
2. feed-media: publisher's own RSS/Atom media enclosure (verified https)
3. Predictable source addresses:
   - github-social: opengraph.githubassets.com/1/<owner>/<repo>
   - youtube: i.ytimg.com/vi/<id>/hqdefault.jpg
   - hf-thumbnail: Hugging Face social thumbnails
4. og:image / twitter:image from HTML (via = linked-article for discussions)

Every image candidate is verified with Range bytes=0-4095 and checked to be image/*.
Results are cached on disk to ensure each story/address is resolved once and
bounded per run with daemon threads and a wall-clock deadline so builds never stall on slow pages.
"""

from datetime import datetime, timezone
import html
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request

from radar.pipeline import write_atomic

DISCUSSION_HOSTS = ("news.ycombinator.com", "lobste.rs")
DISCUSSION_SOURCES = ("hn-", "lobsters")

KIND_OF_VIA = {
    "feed-media": "photo",
    "og:image": "photo",
    "linked-article": "photo",
    "youtube": "photo",
    "github-social": "graphic",
    "hf-thumbnail": "graphic",
    "ai": "photo",
}

GH_RE = re.compile(r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/?#].*)?$", re.I)
GH_RESERVED = {
    "orgs", "topics", "features", "sponsors", "marketplace", "apps", "settings",
    "collections", "trending", "search", "about", "pricing", "enterprise",
    "login", "users", "site", "readme", "events",
}

YT_RES = [re.compile(p, re.I) for p in (
    r"^https?://(?:www\.|m\.)?youtube\.com/watch\?(?:.*&)?v=([\w-]{6,})",
    r"^https?://youtu\.be/([\w-]{6,})",
    r"^https?://(?:www\.)?youtube\.com/(?:shorts|live|embed)/([\w-]{6,})",
)]

HF_RE = re.compile(r"^https?://huggingface\.co/(?:(datasets|spaces)/)?([\w.-]+)/([\w.-]+)/?$", re.I)
HF_PAPER_RE = re.compile(r"^https?://huggingface\.co/papers/([\w.-]+)/?$", re.I)
HF_RESERVED = {
    "papers", "blog", "docs", "api", "models", "collections", "organizations",
    "posts", "learn", "tasks", "settings", "join", "login", "new", "pricing",
    "enterprise", "changelog",
}

META_PATTERNS = [re.compile(p, re.I) for p in (
    r'<meta[^>]+property=["\']og:image(?::secure_url|:url)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url|:url)?["\']',
    r'<meta[^>]+name=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']og:image["\']',
    r'<meta[^>]+(?:name|property)=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']twitter:image(?::src)?["\']',
)]

UA_BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_PREVIEW = "Mozilla/5.0 (compatible; ai-radar-linkpreview/1.0; +https://dootan2020.github.io/ai-radar/)"
ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"

# Default SSL context with full certificate and hostname verification
_ssl_ctx = ssl.create_default_context()

# In-memory verification cache for the current process (only for real network calls)
_verified_cache = {}


def clear_verification_cache():
    """Clear the in-memory verification cache (for test isolation)."""
    _verified_cache.clear()


RESERVED_TLDS = (".invalid", ".test", ".example", ".localhost", ".local", ".internal")


def is_blocked_host(host):
    """Reject IP-literal, loopback, private, and reserved test hosts."""
    if not host:
        return True
    host = (host or "").lower().split(":")[0].strip("[]")
    if any(host == tld[1:] or host.endswith(tld) for tld in RESERVED_TLDS):
        return True
    if host in ("localhost", "loopback"):
        return True
    try:
        ipaddress.ip_address(host)
        return True  # Reject IP-literal hosts
    except ValueError:
        pass
    if host.replace(".", "").isdigit():
        return True
    return False


def is_safe_https_url(url):
    """Ensure URL is https only and does not point to blocked or internal hosts."""
    if not url or not isinstance(url, str) or not url.startswith("https://"):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            return False
        return not is_blocked_host(parsed.hostname)
    except Exception:
        return False


def _get_bytes(url, ua=UA_BROWSER, limit=4096, timeout=5, extra=None, transport=None):
    """Fetch bytes from URL with optional transport override for tests. Read in chunks with timeout."""
    if transport is not None:
        raw = transport(url)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        raw = raw or b""
        return 200, "text/html", raw[:limit], url
    if not is_safe_https_url(url):
        raise ValueError(f"Blocked or non-https URL: {url}")
    headers = {
        "User-Agent": ua,
        "Accept": ACCEPT,
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    }
    if extra:
        headers.update(extra)
    req = urllib.request.Request(url, headers=headers)
    req_deadline = time.monotonic() + timeout
    chunks = []
    received = 0
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as resp:
        while received < limit:
            if time.monotonic() > req_deadline:
                raise TimeoutError("Request deadline exceeded while reading chunks")
            chunk_size = min(4096, limit - received)
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        return resp.status, resp.headers.get("Content-Type", ""), b"".join(chunks), resp.geturl()


def verify_image(src, timeout=5, transport=None):
    """Verify that an address answers with image/* content or image magic bytes."""
    if not is_safe_https_url(src):
        return False
    if transport is None and src in _verified_cache:
        return _verified_cache[src]

    if transport is not None:
        try:
            status, ct, raw, _ = _get_bytes(src, limit=4096, timeout=timeout, transport=transport)
            ct = (ct or "").lower()
            sniff = raw[:12]
            looks = sniff.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")) or b"ftypavif" in raw[:32]
            return bool(status in (200, 206) and (ct.startswith("image/") or looks))
        except Exception:
            return False

    ok = False
    for ua in (UA_BROWSER, UA_PREVIEW):
        try:
            status, ct, raw, _ = _get_bytes(
                src, ua=ua, limit=4096, timeout=timeout,
                extra={"Range": "bytes=0-4095", "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
            )
            ct = (ct or "").lower()
            sniff = raw[:12]
            looks = sniff.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")) or b"ftypavif" in raw[:32]
            if status in (200, 206) and (ct.startswith("image/") or looks):
                ok = True
                break
        except Exception:
            continue
    _verified_cache[src] = ok
    return ok


def extract_meta_image(page_text, page_url):
    """Extract og:image or twitter:image from HTML text, resolving relative URLs."""
    if not page_text:
        return None
    for pat in META_PATTERNS:
        m = pat.search(page_text)
        if m:
            img = urllib.parse.urljoin(page_url, html.unescape(m.group(1).strip()))
            if is_safe_https_url(img):
                return img
    return None


def pattern_image(url):
    """Return (src, via) for addresses with predictable images, else None."""
    m = GH_RE.match(url or "")
    if m and m.group(1).lower() not in GH_RESERVED:
        return f"https://opengraph.githubassets.com/1/{m.group(1)}/{m.group(2)}", "github-social"
    for r in YT_RES:
        m = r.match(url or "")
        if m:
            return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg", "youtube"
    return None


def hf_thumbnail_path(url):
    """Predictable social thumbnail URL for Hugging Face repos and papers."""
    m = HF_PAPER_RE.match(url or "")
    if m:
        return f"https://cdn-thumbnails.huggingface.co/social-thumbnails/papers/{m.group(1)}.png"
    m = HF_RE.match(url or "")
    if m and m.group(2).lower() not in HF_RESERVED:
        kind = m.group(1) or "models"
        return f"https://cdn-thumbnails.huggingface.co/social-thumbnails/{kind}/{m.group(2)}/{m.group(3)}.png"
    return None


def page_meta_image(url, timeout=5, transport=None):
    """Fetch HTML and extract og:image or twitter:image."""
    if not is_safe_https_url(url):
        return None
    host = urllib.parse.urlparse(url).netloc
    if host in DISCUSSION_HOSTS or is_blocked_host(host):
        return None
    for ua in (UA_BROWSER, UA_PREVIEW):
        try:
            status, ct, raw, final_url = _get_bytes(url, ua=ua, limit=300 * 1024, timeout=timeout, transport=transport)
        except Exception:
            continue
        if "html" not in ct and "xml" not in ct and transport is None:
            return None
        enc = "utf-8"
        m = re.search(r"charset=([\w-]+)", ct)
        if m:
            enc = m.group(1)
        try:
            text = raw.decode(enc, errors="ignore")
        except LookupError:
            text = raw.decode("utf-8", errors="ignore")
        img = extract_meta_image(text, final_url)
        if img:
            return img
    return None


def story_urls(story):
    """Unique HTTPS URLs associated with a story in discovery order, capped at 2."""
    seen, out = set(), []
    for u in [story.get("url")] + [c.get("url") for c in story.get("coverage") or []]:
        if u and u not in seen and is_safe_https_url(u):
            seen.add(u)
            out.append(u)
            if len(out) >= 2:
                break
    return out


def resolve_url_image(url, is_discussion=False, timeout=5, transport=None):
    """Resolve image metadata for a single URL using pattern or og:image."""
    pat = pattern_image(url)
    if pat and verify_image(pat[0], timeout=timeout, transport=transport):
        return {"src": pat[0], "via": pat[1]}

    is_hf = "huggingface.co/" in (url or "")
    og = page_meta_image(url, timeout=timeout, transport=transport)
    if og and verify_image(og, timeout=timeout, transport=transport):
        via = "linked-article" if is_discussion else ("hf-thumbnail" if is_hf else "og:image")
        return {"src": og, "via": via}

    if is_hf:
        hf_thumb = hf_thumbnail_path(url)
        if hf_thumb and verify_image(hf_thumb, timeout=timeout, transport=transport):
            return {"src": hf_thumb, "via": "hf-thumbnail"}

    return None


NEGATIVE_TTL = 86400 * 2  # 48 hours for negative caching


class ImageCache:
    """Persistent disk cache for resolved image metadata."""

    def __init__(self, cache_path=None, seed_path=None):
        root = Path(__file__).resolve().parent.parent
        self.cache_path = Path(cache_path) if cache_path else root / "data" / "image-cache.json"
        self.seed_path = Path(seed_path) if seed_path else root / "site" / "feed-images.json"
        self.images = {}
        self.load()

    def load(self):
        # Prefer dedicated data/image-cache.json
        if self.cache_path.is_file():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self.images = data.get("images", {})
                return
            except Exception:
                self.images = {}
        # Seed from site/feed-images.json if available
        if self.seed_path.is_file():
            try:
                data = json.loads(self.seed_path.read_text(encoding="utf-8"))
                raw_images = data.get("images", {}) if "images" in data else data
                for u, v in raw_images.items():
                    if u.startswith("_"):
                        continue
                    if isinstance(v, str):
                        self.images[u] = {"src": v, "via": "og:image", "verified": True}
                    elif isinstance(v, dict) and v.get("src"):
                        self.images[u] = {"src": v["src"], "via": v.get("via", "og:image"), "verified": True}
            except Exception:
                pass

    def get(self, url):
        return self.images.get(url)

    def set(self, url, entry):
        self.images[url] = entry

    def is_negative_active(self, url, now_ts=None):
        entry = self.images.get(url)
        if entry and entry.get("src") is None:
            cached_at = entry.get("cached_at", 0)
            now_ts = now_ts or time.time()
            if now_ts - cached_at < NEGATIVE_TTL:
                return True
        return False

    def save(self, keep_urls=None):
        if keep_urls is not None:
            self.images = {u: v for u, v in self.images.items() if u in keep_urls}
        out = {
            "_meta": {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "total_cached": len(self.images),
            },
            "images": self.images,
        }
        write_atomic(out, self.cache_path)


def resolve_story_image(story, cache=None, timeout=5, transport=None, allow_network=True):
    """Pick image for a story in strict trust order:

    1. cached url image (fast, 0 network, verified)
    2. feed-media (coverage[].media)
    3. predictable addresses (github, youtube, hf)
    4. live og:image / twitter:image lookup (only if allow_network=True)
    """
    coverage = story.get("coverage") or []
    first = coverage[0] if coverage else {}
    first_src = str(first.get("source", ""))
    is_discussion = any(first_src.startswith(prefix) for prefix in DISCUSSION_SOURCES)

    urls = story_urls(story)

    # 1. Check cache (fast, 0 network, already verified)
    if cache is not None:
        for u in urls:
            cached = cache.get(u)
            if cached and cached.get("src"):
                via = cached.get("via", "og:image")
                if is_discussion and via == "og:image":
                    via = "linked-article"
                return {"src": cached["src"], "via": via, "kind": KIND_OF_VIA.get(via, "photo"), "verified": True}

    # 2. feed-media (coverage[].media)
    for c in coverage:
        for md in c.get("media") or []:
            u = md.get("url") or ""
            if (md.get("type") in (None, "image") or str(md.get("mime_type", "")).startswith("image/")) and is_safe_https_url(u):
                if not allow_network:
                    continue
                if verify_image(u, timeout=timeout, transport=transport):
                    return {"src": u, "via": "feed-media", "kind": "photo", "verified": True}

    # 3. Predictable address (YouTube, GitHub, HF)
    for u in urls:
        pat = pattern_image(u)
        if pat:
            src, via = pat
            if not allow_network:
                continue
            if verify_image(src, timeout=timeout, transport=transport):
                return {"src": src, "via": via, "kind": KIND_OF_VIA.get(via, "photo"), "verified": True}
        if "huggingface.co/" in u:
            hf_path = hf_thumbnail_path(u)
            if hf_path:
                if not allow_network:
                    continue
                if verify_image(hf_path, timeout=timeout, transport=transport):
                    return {"src": hf_path, "via": "hf-thumbnail", "kind": "graphic", "verified": True}

    # 4. Cached AI illustration (0 network, generated in previous run)
    if cache is not None and story.get("id"):
        cached_ai = cache.get(f"ai:{story.get('id')}")
        if cached_ai and cached_ai.get("src"):
            return {"src": cached_ai["src"], "via": "ai", "kind": "photo", "verified": True}

    # 5. Live page resolution (only if network is allowed)
    if not allow_network:
        return None

    for u in urls:
        if cache is not None and cache.is_negative_active(u):
            continue
        res = resolve_url_image(u, is_discussion=is_discussion, timeout=timeout, transport=transport)
        if res:
            res["verified"] = True
            if cache is not None:
                cache.set(u, res)
            return {"src": res["src"], "via": res["via"], "kind": KIND_OF_VIA.get(res["via"], "photo"), "verified": True}
        elif cache is not None:
            # Cache negative result so dead URLs aren't retried repeatedly
            cache.set(u, {"src": None, "via": None, "cached_at": time.time()})

    return None


def resolve_images_for_stories(stories, cache_path=None, seed_path=None, budget_seconds=20,
                               max_workers=16, timeout=4, transport=None, deadline=None,
                               ai_transport=None, ledger_path=None, site_root=None):
    """Resolve and attach images to stories in place with bounded concurrency and time."""
    # Finding 2: avoid loading/saving to repo cache during offline transport tests
    cache = ImageCache(cache_path=cache_path, seed_path=seed_path) if (transport is None or cache_path is not None) else None

    wall_deadline = time.monotonic() + budget_seconds
    if deadline is not None:
        wall_deadline = min(wall_deadline, deadline)

    unresolved_stories = []

    # First pass: resolve from cache (0 network)
    for st in stories:
        img = resolve_story_image(st, cache=cache, timeout=timeout, transport=transport,
                                  allow_network=(transport is not None))
        if img:
            st["image"] = img
        else:
            unresolved_stories.append(st)

    # Second pass: concurrent live resolution with daemon threads and hard wall-clock deadline
    time_left = wall_deadline - time.monotonic()
    if unresolved_stories and time_left > 0.5 and transport is None:
        pending, completed = queue.Queue(), queue.Queue()
        for st in unresolved_stories:
            pending.put(st)

        def worker():
            while time.monotonic() < wall_deadline:
                try:
                    st = pending.get_nowait()
                except queue.Empty:
                    return
                try:
                    img = resolve_story_image(st, cache=cache, timeout=timeout, transport=None, allow_network=True)
                except Exception:
                    img = None
                completed.put((st, img))

        num_workers = min(max_workers, len(unresolved_stories))
        for _ in range(num_workers):
            threading.Thread(target=worker, daemon=True, name="radar-image").start()

        received = 0
        while received < len(unresolved_stories):
            timeout_wait = max(0.0, wall_deadline - time.monotonic())
            if timeout_wait <= 0:
                break
            try:
                st, img = completed.get(timeout=timeout_wait)
            except queue.Empty:
                break
            received += 1
            if img:
                st["image"] = img

    # Third pass: AI illustration generation for stories without source-published image
    from radar import ai_images
    still_unresolved = [st for st in stories if not st.get("image")]
    time_left = wall_deadline - time.monotonic()
    if still_unresolved and time_left > 0.5:
        has_env = bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_AI_API_TOKEN"))
        if has_env or ai_transport is not None:
            ai_ledger = ai_images.AIImageLedger(ledger_path=ledger_path)
            # Serve newest stories first so daily neuron budget prioritizes fresh content
            still_unresolved.sort(key=ai_images.story_recency_key, reverse=True)
            for st in still_unresolved:
                if time.monotonic() >= wall_deadline:
                    break
                ai_img = ai_images.generate_ai_illustration(
                    st,
                    site_root=site_root,
                    ledger=ai_ledger,
                    transport=ai_transport,
                    timeout=min(timeout, max(1.0, wall_deadline - time.monotonic())),
                )
                if ai_img:
                    st["image"] = ai_img
                    if cache is not None:
                        cache.set(f"ai:{st['id']}", ai_img)

    # Save updated cache (only when real run or explicit cache_path provided)
    if cache is not None and (transport is None or cache_path is not None):
        try:
            all_urls = {u for st in stories for u in story_urls(st)}
            ai_keys = {f"ai:{st['id']}" for st in stories if st.get("image", {}).get("via") == "ai"}
            cache.save(keep_urls=(all_urls | ai_keys))
        except Exception:
            pass

    return stories

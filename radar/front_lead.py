"""The front page's lead picture, written into site/index.html when a snapshot is published.

The lead carousel's first picture is the page's largest element (Lighthouse's LCP on a phone). Drawn by feed.js alone,
the browser learns its address only after the modules and the snapshot arrive, then opens a connection to the
publisher's image host. Here the build picks the same story feed.js puts first and writes three things into the page:
a preconnect to the picture's host, an image preload with the same srcset and sizes, and the picture itself in the
loading placeholder, in the lead's own place. feed.js adopts that picture when its first story is the same one
(adoptEarlyLead), so the picture is never fetched or drawn twice.

The choice mirrors site/feed.js line for line: ingest (the ranking window), matchPicks (editor picks), chooseFront
(the first story with a photograph, by pinFirst, frontScore, rankTime) and mediaHTML/srcsetAttrs (the markup). When a
story in the window lacks a field that choice reads (the screened picture, the worth score), the page keeps its plain
placeholder: a guess could put the wrong picture first. tests/test_front_lead.py runs the real feed.js on the same
snapshot and checks both pick the same story.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlsplit
import base64
import hashlib
import json
import re
import time

from radar.site_config import SITE_URL

TIER = {"top": 3, "notable": 2}                      # feed.js TIER
PICKS_MAX = 5                                         # worth-score.js WORTH.picksMax
KIND_OF_VIA = {"feed-media": "photo", "og:image": "photo", "linked-article": "photo", "youtube": "photo",
               "github-social": "graphic", "hf-thumbnail": "graphic", "ai": "photo"}
LEAD_WIDTHS = (480, 828, 1280)                        # feed.js WIDTHS.lead
LEAD_SIZES = "(max-width: 1023px) 100vw, 50vw"        # feed.js SIZES.lead

HEAD_OPEN = "<!-- lead picture: the build writes the lead's preconnect and image preload here (radar/front_lead.py) -->\n"
HEAD_CLOSE = "<!-- /lead picture -->\n"
BODY_OPEN = "  <!-- lead slide: the build draws the lead's picture here (radar/front_lead.py); feed.js adopts it -->\n"
BODY_CLOSE = "  <!-- /lead slide -->\n"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
SITE_HOSTS = {urlsplit(SITE_URL).hostname, "radar-ai-vn.pages.dev"}   # the site's own hosts: no preconnect
SKELETON_LEAD = '  <div class="msn-card msn-sk msn-lead"></div>\n'


class Unknown(Exception):
    """A field the browser's choice depends on is missing: the build cannot know the lead for sure."""


def _ms(value):
    """new Date(iso).getTime() || 0, to the millisecond."""
    if not isinstance(value, str) or not value:
        return 0
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Unknown(f"unreadable time {value!r}")
    if moment.tzinfo is None:
        raise Unknown(f"time without zone {value!r}")   # a browser reads it as local time
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _rank_time(story):
    return _ms(story.get("latest_coverage_at") or story.get("published_at"))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _truthy(value):
    return value is not None and value is not False and value != 0 and value != ""


def window_stories(page):
    """feed.js ingest: stories whose rank time is inside the ranking window, newest first (a stable sort)."""
    try:
        hours = float((page.get("ranking") or {}).get("window_hours"))
    except (TypeError, ValueError):
        hours = 0
    if not hours > 0:
        hours = 72
    generated = _ms(page.get("generated_at"))
    start = generated - hours * 36e5
    stories = [st for st in page.get("stories") or [] if isinstance(st, dict)]
    inside = [st for st in stories if _rank_time(st) and start <= _rank_time(st) <= generated + 3e5]
    return sorted(inside, key=lambda st: -_rank_time(st))


def picked_ids(stories, picks, now_ms):
    """feed.js matchPicks: the editor's picks found in the window, at most PICKS_MAX."""
    ids = []
    for pick in picks:
        if len(ids) >= PICKS_MAX:
            break
        if not isinstance(pick, dict) or (not pick.get("id") and not pick.get("url")):
            continue
        if pick.get("until") is not None and not _ms(pick["until"]) > now_ms:
            continue
        for st in stories:
            if ((pick.get("id") and st.get("id") == pick["id"])
                    or (pick.get("url") and (st.get("url") == pick["url"]
                                             or any(c.get("url") == pick["url"] for c in st.get("coverage") or [])))):
                if st["id"] not in ids:
                    ids.append(st["id"])
                break
    return ids


def lead_image(story):
    """feed.js pickImage for a screened story: its own picture, or none (the cover)."""
    image = story.get("image")
    if isinstance(image, dict) and image.get("src"):
        via = image.get("via")
        kind = "cover" if via == "cover" else image.get("kind") or KIND_OF_VIA.get(via) or "photo"
        return {"src": image["src"], "via": via, "kind": kind}
    if not story.get("image_screened"):
        raise Unknown(f"story {story.get('id')} has no screened picture")   # the browser asks other providers
    return None


def _worth(story):
    if _number(story.get("worth_score")) and _truthy(story.get("worth_parts")):
        return story["worth_score"]
    raise Unknown(f"story {story.get('id')} has no worth score")


def _front_score(story):
    hot = story.get("hot_score")
    return TIER.get(story.get("importance_tier"), 0) + (hot if _number(hot) and hot else 0) / 20 + min(_worth(story), 8) / 4


def lead_story(page, picks=(), now_ms=None):
    """The story feed.js puts first in the lead carousel, and its picture; None when there is none or it is unknown."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    try:
        stories = window_stories(page)
        pinned = set(picked_ids(stories, picks, now_ms))
        ranked = sorted(stories, key=lambda st: (st["id"] not in pinned, -_front_score(st), -_rank_time(st)))
        for story in ranked:
            image = lead_image(story)
            if image and image["kind"] == "photo":
                return story, image
    except Unknown:
        return None
    return None


def esc(value):
    """faces.js esc."""
    return re.sub(r"[&<>\"']", lambda m: {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[m.group(0)],
                  str(value if value is not None else ""))


def _form_encode(text):
    """URLSearchParams serialization (application/x-www-form-urlencoded)."""
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if (byte < 128 and char.isalnum()) or char in "*-._":
            out.append(char)
        elif char == " ":
            out.append("+")
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


def _form_decode(text):
    return unquote_to_bytes(text.replace("+", " ")).decode("utf-8", "replace")


def _set_param(url, name, value):
    """url.searchParams.set(name, value) and url.href, for an already normal absolute address."""
    head, _, fragment = url.partition("#")
    base, mark, query = head.partition("?")
    pairs = []
    for part in query.split("&") if mark else []:
        if part:
            key, _, val = part.partition("=")
            pairs.append([_form_decode(key), _form_decode(val)])
    found = [i for i, (key, _) in enumerate(pairs) if key == name]
    if found:
        pairs[found[0]][1] = value
        pairs = [p for i, p in enumerate(pairs) if i == found[0] or p[0] != name]
    else:
        pairs.append([name, value])
    serialized = "&".join(f"{_form_encode(k)}={_form_encode(v)}" for k, v in pairs)
    return base + ("?" + serialized if serialized else "") + ("#" + fragment if fragment else "")


def sized_src(src, width):
    """feed.js sizedSrc: the publisher's own image server at the slot's width, or None for any other host."""
    try:
        parts = urlsplit(src)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host, path = parts.hostname, parts.path
    if host in ("img.semafor.com", "cdn.sanity.io") or (host == "www-cdn.anthropic.com" and path.startswith("/images/")):
        return _set_param(src, "w", str(width))
    if re.fullmatch(r"i[0-3]\.wp\.com", host) or "/wp-content/uploads/" in path:
        return _set_param(src, "w", str(width))
    if host == "media.wired.com" and "/master/pass/" in path:
        head, mark, rest = src.partition(path)
        return head + path.replace("/master/pass/", f"/master/w_{width},c_limit/", 1) + rest
    return None


def lead_srcset(src):
    """(srcset, sizes, src) as feed.js srcsetAttrs writes them for the lead; srcset None when the host cannot resize."""
    candidates = [(sized_src(src, w), w) for w in LEAD_WIDTHS]
    if not candidates[0][0]:
        return None, None, src
    return ", ".join(f"{u} {w}w" for u, w in candidates), LEAD_SIZES, candidates[1][0]


AI_BADGE = ('<span class="ai-badge" title="Ảnh minh hoạ do AI tạo"><span class="sr">Loại ảnh: </span>'
            'Ảnh minh hoạ do AI tạo</span>')


def media_html(image):
    """feed.js mediaHTML(img, 'lead') for a photograph. The picture starts marked loaded, so feed.js's blur-up (which
    applies once the module runs) never blurs a picture already on screen."""
    srcset, sizes, src = lead_srcset(image["src"])
    attrs = f'srcset="{esc(srcset)}" sizes="{sizes}" src="{esc(src)}"' if srcset else f'src="{esc(src)}"'
    return (f'<img class="media-img nc-img is-loaded" {attrs} alt="" width="1280" height="720" loading="eager" '
            f'decoding="async" referrerpolicy="no-referrer" fetchpriority="high">'
            + (AI_BADGE if image.get("via") == "ai" else ""))


def preconnect_origin(src):
    """The picture's host when it is another site's (a relative or same-site picture needs no new connection)."""
    parts = urlsplit(src)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.hostname in SITE_HOSTS:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def head_html(image):
    srcset, sizes, src = lead_srcset(image["src"])
    origin = preconnect_origin(src)
    preload = (f'<link rel="preload" as="image" href="{esc(src)}" imagesrcset="{esc(srcset)}" imagesizes="{sizes}" '
               if srcset else f'<link rel="preload" as="image" href="{esc(src)}" ')
    return ((f'<link rel="preconnect" href="{esc(origin)}">\n' if origin else '')
            + preload + 'fetchpriority="high" referrerpolicy="no-referrer">\n')


def body_html(story, image):
    """The first band as feed.js draws it ("Hôm nay": the lead, then "Vừa đăng" and the weather), with the lead's
    picture in it and loading placeholders for the rest, so the picture sits where the drawn page puts it."""
    return ('  <section class="band band-today"><h2 class="band-title">Hôm nay</h2><div class="band-cells">'
            f'<section class="msn-card msn-lead"><article class="slide is-active" data-id="{esc(story["id"])}">'
            f'<div class="slide-media media">{media_html(image)}</div></article></section>'
            '<div class="msn-card msn-sk tile-fresh"></div><div class="msn-card msn-sk"></div></div></section>\n')


def _between(text, opening, closing, inner):
    start, end = text.find(opening), text.find(closing)
    if start < 0 or end < start or text.count(opening) != 1 or text.count(closing) != 1:
        raise ValueError(f"Expected one {opening.strip()[:40]} block")
    return text[:start + len(opening)] + inner + text[end:]


def render_index(text, lead):
    """site/index.html with the lead's head and body blocks filled for `lead` (story, image), or reset when None."""
    if lead is None:
        return _between(_between(text, HEAD_OPEN, HEAD_CLOSE, ""), BODY_OPEN, BODY_CLOSE, SKELETON_LEAD)
    story, image = lead
    return _between(_between(text, HEAD_OPEN, HEAD_CLOSE, head_html(image)), BODY_OPEN, BODY_CLOSE, body_html(story, image))


# Asset versions. The host lets a browser keep /feed.js and the stylesheets for hours (cache-control max-age=14400)
# while it asks for / every time, so after a deploy a phone could run the new page with the old scripts (captain,
# 11/11: the "Sự kiện" page did not show on his phone the morning after it shipped). Every script and stylesheet the
# page names carries ?v=<a hash of the file>, and an import map gives the modules those scripts import, and the
# stylesheets feed.js asks for (import.meta.resolve), the same versions: a changed file has a new address, an unchanged
# one keeps its cache. The import map is an inline script, so the page's policy allows it by its own hash.
ASSETS_OPEN = "<!-- asset versions: the build writes the import map that versions every module here (radar/front_lead.py) -->\n"
ASSETS_CLOSE = "<!-- /asset versions -->\n"
VERSION_LEN = 12
_ASSET_REF = re.compile(r'(<(?:script|link)\b[^>]*?\b(?:src|href)=")([A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:js|css))(?:\?v=[0-9a-f]*)?(")')
_SCRIPT_SRC = re.compile(r"(script-src 'self')((?: 'sha256-[A-Za-z0-9+/=]+')*)")


def asset_version(path):
    """The first hex digits of the file's SHA-256: the version its address carries."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:VERSION_LEN]


def csp_hash(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def import_map(site):
    """The import map for the site's top-level scripts and stylesheets: ./name -> ./name?v=<version>."""
    files = sorted(p for p in Path(site).iterdir() if p.is_file() and p.suffix in (".js", ".css"))
    return json.dumps({"imports": {f"./{p.name}": f"./{p.name}?v={asset_version(p)}" for p in files}},
                      separators=(",", ":"), ensure_ascii=False)


def stamp_assets(text, site):
    """index.html with every local script and stylesheet reference versioned by its file's content, and, between the
    asset markers, the import map that versions what those modules import, allowed by its hash in the page's policy.
    Running it again on its own output changes nothing; a file that is not there keeps its plain address."""
    site = Path(site)

    def versioned(m):
        path = site / m.group(2)
        if not path.is_file():
            return m.group(1) + m.group(2) + m.group(3)
        return f"{m.group(1)}{m.group(2)}?v={asset_version(path)}{m.group(3)}"

    start, end = text.find(ASSETS_OPEN), text.find(ASSETS_CLOSE)
    if start < 0 or end < start:
        return _ASSET_REF.sub(versioned, text)
    old = re.search(r'<script type="importmap">(.*?)</script>', text[start:end], re.S)
    mapping = import_map(site)
    block = f'<script type="importmap">{mapping}</script>\n'
    text = text[:start + len(ASSETS_OPEN)] + block + text[end:]
    stale = csp_hash(old.group(1)) if old else None

    def policy(m):
        hashes = [h for h in m.group(2).split() if h and h != stale]
        return m.group(1) + "".join(" " + h for h in hashes + [csp_hash(mapping)] if h)

    text = _SCRIPT_SRC.sub(policy, text, count=1)
    return _ASSET_REF.sub(versioned, text)


def load_picks(path):
    try:
        picks = json.loads(Path(path).read_text(encoding="utf-8")).get("picks")
    except (OSError, ValueError, AttributeError):
        return []
    return picks if isinstance(picks, list) else []


def update_index_lead(index_path, page, picks_path=None, now_ms=None):
    """Write the lead's preload and picture into index.html for this snapshot's reader projection."""
    index_path = Path(index_path)
    if not index_path.is_file():
        return None
    text = index_path.read_text(encoding="utf-8")
    if HEAD_OPEN not in text:
        return None
    picks = load_picks(picks_path or index_path.parent / "editor-picks.json")
    lead = lead_story(page, picks, now_ms)
    new_text = stamp_assets(render_index(text, lead), index_path.parent)
    if new_text != text:
        index_path.write_text(new_text, encoding="utf-8", newline="\n")
    return lead[0]["id"] if lead else None


def reset_index_lead(index_path):
    """index.html with the plain placeholder and no lead preload (the build's fallback when writing the lead failed)."""
    index_path = Path(index_path)
    text = index_path.read_text(encoding="utf-8")
    new_text = stamp_assets(render_index(text, None), index_path.parent)
    if new_text != text:
        index_path.write_text(new_text, encoding="utf-8", newline="\n")

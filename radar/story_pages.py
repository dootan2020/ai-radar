"""Prepare permanent static story pages and persist their source records."""

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from radar.clustering import canonical_url
from radar.common import stable_id
from radar.site_config import SITE_BASE_URL

BASE_URL = SITE_BASE_URL
SITE_NAME = "ai·radar"
BRANCH = "radar-story-pages"
REF = f"refs/heads/{BRANCH}"
STORY_ID = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
STORY_FILE = re.compile(r"[a-z0-9][a-z0-9_-]*\.json\Z")
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'sha256-jrWEGOojzbiKG0hVSa49bhxOv0fp+N41v7Y8Xjpx69c=' "
    "https://static.cloudflareinsights.com/beacon.min.js; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https:; font-src 'self'; connect-src 'self' https://hn.algolia.com "
    "https://huggingface.co https://cloudflareinsights.com; object-src 'none'; base-uri 'self'; form-action 'none';"
)
THEME_SCRIPT = "try { var t = JSON.parse(localStorage.getItem('air2:theme')); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch (e) {}"
TEMPLATE_PATH = Path(__file__).with_name("story_page_template.html")
NON_TERMINAL_ABBRS = {
    "e.g.", "i.e.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "no.", "vol.",
    "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec."
}


def trim_complete_sentences(text: str) -> str:
    """Trim an excerpt so it contains only complete sentences."""
    if not text or not isinstance(text, str):
        return ""
    text = text.strip()
    if not text:
        return ""

    pattern = re.compile(r'(?:\.{3}|…|[.!?。！？])[\'"”’\)\]]*(?=\s|$)')
    last_end = -1
    for m in pattern.finditer(text):
        start = m.start()
        end = m.end()
        punct = m.group(0)

        if punct.startswith('.') and not punct.startswith('..'):
            prefix = text[:start]
            tokens = prefix.split()
            if tokens:
                last_word = (tokens[-1] + punct).lower().strip('()[]{}""\'”’')
                if last_word in NON_TERMINAL_ABBRS and end < len(text):
                    continue
                if re.fullmatch(r'[a-zA-Z]\.', last_word) and end < len(text):
                    continue
                if re.search(r'\.(?:com|org|net|io|ai|vn|is|ph|co|html|json|cpp)\b', last_word):
                    continue

        last_end = end

    if last_end <= 0:
        return ""
    return text[:last_end].strip()



def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8") + b"\n"


def _write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _story_id(story):
    value = story.get("id") if isinstance(story, dict) else None
    if not isinstance(value, str) or not STORY_ID.fullmatch(value):
        raise ValueError("Story has a missing or unsafe id")
    return value


def _http_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value


def _text(value):
    return value if isinstance(value, str) else ""


def _key_points(story):
    values = story.get("key_points")
    if isinstance(values, str):
        return [values] if values.strip() else []
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        if isinstance(value, str) and value.strip():
            result.append(value)
        elif isinstance(value, dict):
            point = value.get("text") or value.get("point")
            if isinstance(point, str) and point.strip():
                result.append(point)
    return result


def _page_fields(story, base_url):
    coverage = story.get("coverage") if isinstance(story.get("coverage"), list) else []
    title = (_text(story.get("title_vi")) or _text(story.get("title")) or
             next((_text(item.get("title_vi")) or _text(item.get("title"))
                   for item in coverage if isinstance(item, dict)
                   and (_text(item.get("title_vi")) or _text(item.get("title")))), ""))
    if not title:
        if story.get("redirect_to"):
            title = "ai·radar"
        else:
            raise ValueError(f"Story {_story_id(story)} has no headline")
    first_coverage = next((item for item in coverage if isinstance(item, dict)), {})
    original_url = _http_url(story.get("url")) or _http_url(first_coverage.get("url"))
    if not original_url:
        if story.get("redirect_to"):
            original_url = f"{base_url}/tin/{story['redirect_to']}/"
        else:
            raise ValueError(f"Story {_story_id(story)} has no safe original URL")
    image = story.get("image")
    image_src = _text(image.get("src")) if isinstance(image, dict) else ""
    image_url = _http_url(image_src)
    if re.fullmatch(r"assets/ai/[\w-]+\.jpg", image_src):
        image_url = f"{base_url}/{image_src}"
    if not image_url and not story.get("image_screened"):
        image_url = f"{base_url}/og-image.png"
    publisher = (_text(first_coverage.get("publisher")) or _text(first_coverage.get("source")) or
                 urlsplit(original_url).hostname or "")
    summary_vi = trim_complete_sentences(_text(story.get("summary_vi")))
    summary_en = trim_complete_sentences(_text(story.get("summary")))
    clean_summary = summary_vi or summary_en
    description = clean_summary or title
    original_title = (_text(first_coverage.get("title")) or _text(story.get("title")) or title)
    story_id = _story_id(story)
    return {
        "canonical": f"{base_url}/tin/{story_id}/",
        "date_published": _text(story.get("published_at")) or None,
        "description": description,
        "image": image_url,
        "key_points": _key_points(story),
        "original_title": original_title,
        "original_url": original_url,
        "publisher": publisher,
        "summary": clean_summary,
        "title": title,
    }


def render_story_page(story, base_url=BASE_URL, sources=None):
    """Render crawler-readable HTML; publisher data is escaped in every context."""
    fields = _page_fields(story, base_url.rstrip("/"))
    esc = lambda value: html.escape(str(value), quote=True)
    story_data = dict(story)
    source_ids = {item.get("source") for item in story.get("coverage", [])
                  if isinstance(item, dict) and isinstance(item.get("source"), str)}
    if isinstance(story.get("source"), str):
        source_ids.add(story["source"])
    source_map = {item["id"]: item for item in (sources or [])
                  if isinstance(item, dict) and isinstance(item.get("id"), str)}
    story_data["source_records"] = [source_map[source_id] for source_id in sorted(source_ids)
                                    if source_id in source_map]
    encoded_story = json.dumps(story_data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    encoded_story = (encoded_story.replace("&", "\\u0026").replace("<", "\\u003c")
                     .replace(">", "\\u003e").replace("\u2028", "\\u2028")
                     .replace("\u2029", "\\u2029"))
    article_data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": fields["title"],
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }
    if fields["image"]:
        article_data["image"] = [fields["image"]]
    if fields["date_published"]:
        article_data["datePublished"] = fields["date_published"]
    encoded_article = json.dumps(article_data, ensure_ascii=False, separators=(",", ":"))
    encoded_article = (encoded_article.replace("&", "\\u0026").replace("<", "\\u003c")
                       .replace(">", "\\u003e").replace("\u2028", "\\u2028")
                       .replace("\u2029", "\\u2029"))
    points_html = "".join(f'<li class="story-point-item"><span class="story-point-text">{esc(point)}</span></li>'
                           for point in fields["key_points"])
    fallback_content = (f'<section class="story-keypoints-box" aria-label="Ý chính của câu chuyện">'
                        f'<h2 class="story-section-h2">Ý chính của câu chuyện</h2>'
                        f'<ol class="story-points-list">{points_html}</ol></section>'
                        if points_html else
                        f'<section class="story-summary-box" aria-label="Đoạn trích bài viết">'
                        f'<h2 class="story-section-h2">Đoạn trích bài viết</h2>'
                        f'<p class="story-summary-text">{esc(fields["summary"] or fields["title"])}</p></section>')
    gateway_desc = ('ai-radar tóm tắt ý chính để bạn nắm nhanh sự kiện. Mở bài gốc để xem trọn vẹn chi tiết và dẫn chứng.'
                    if fields["key_points"] else
                    'Mở bài gốc để xem trọn vẹn chi tiết và dẫn chứng.')
    publisher_html = f'<span class="story-pub-name">{esc(fields["publisher"])}</span>' if fields["publisher"] else ""
    document = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "{{TITLE}}": esc(fields["title"]), "{{DESCRIPTION}}": esc(fields["description"]),
        "{{CANONICAL}}": esc(fields["canonical"]),
        "{{IMAGE_META}}": (
            f'<meta property="og:image" content="{esc(fields["image"])}">\n'
            f'<meta property="og:image:alt" content="{esc(fields["title"])}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:image" content="{esc(fields["image"])}">'
            if fields["image"] else '<meta name="twitter:card" content="summary">'),
        "{{STORY_ID}}": esc(story["id"]), "{{PUBLISHER}}": publisher_html,
        "{{PUBLISHER_NAME}}": esc(fields["publisher"]),
        "{{ORIGINAL_TITLE}}": esc(fields["original_title"]), "{{ORIGINAL_URL}}": esc(fields["original_url"]),
        "{{CONTENT}}": fallback_content, "{{GATEWAY_DESC}}": esc(gateway_desc),
        "{{STORY_DATA}}": encoded_story,
        "{{JSONLD}}": encoded_article, "{{CSP}}": esc(CONTENT_SECURITY_POLICY),
        "{{THEME_SCRIPT}}": THEME_SCRIPT,
    }
    return re.sub(r"\{\{[A-Z_]+\}\}", lambda match: values[match.group(0)], document)


def render_redirect_page(target_url, title, base_url=BASE_URL):
    """Render a CSP-safe static redirect page pointing to canonical story page."""
    esc = lambda value: html.escape(str(value), quote=True)
    canonical = esc(target_url)
    safe_title = esc(title)
    csp = esc(CONTENT_SECURITY_POLICY)
    return (
        '<!doctype html>\n'
        '<html lang="vi">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'<title>{safe_title} · ai·radar</title>\n'
        '<meta name="robots" content="noindex, follow">\n'
        f'<meta http-equiv="refresh" content="0; url={canonical}">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        f'<script>{THEME_SCRIPT}</script>\n'
        '<link rel="stylesheet" href="../../tokens.css">\n'
        '<link rel="stylesheet" href="../../feed.css">\n'
        '<link rel="stylesheet" href="../../story.css">\n'
        '</head>\n'
        '<body>\n'
        '<main class="story-page-container">\n'
        '  <article class="story-article">\n'
        f'    <p class="story-summary-text">Đang chuyển hướng tới <a href="{canonical}">{safe_title}</a>...</p>\n'
        '  </article>\n'
        '</main>\n'
        '</body>\n'
        '</html>\n'
    )


def story_aliases(story):
    """Extract explicit and coverage-derived alias IDs for a story."""
    if not isinstance(story, dict):
        return set()
    current_id = story.get("id")
    aliases = set()
    for alias in story.get("aliases") or []:
        if isinstance(alias, str) and STORY_ID.fullmatch(alias) and alias != current_id:
            aliases.add(alias)
    for item in story.get("coverage") or []:
        if not isinstance(item, dict):
            continue
        anchor = None
        if item.get("kind") == "event":
            eid = item.get("event_id") or item.get("id")
            if eid:
                anchor = "event:" + str(eid)
        else:
            url = canonical_url(item.get("url")) or item.get("url")
            if url:
                anchor = canonical_url(url) or url
        if anchor:
            item_id = stable_id(anchor)
            if item_id != current_id:
                aliases.add(item_id)
    return aliases


def _validated_story_map(stories):
    result = {}
    for story in stories:
        if not isinstance(story, dict):
            raise ValueError("Snapshot contains a non-object story")
        story_id = _story_id(story)
        _page_fields(story, BASE_URL)
        if story_id in result:
            raise ValueError(f"Snapshot contains duplicate story id {story_id}")
        _json_bytes(story)
        result[story_id] = story
    return result


def render_site(stories, site, base_url=BASE_URL, sources=None):
    """Write exactly the archived story pages and matching sitemap."""
    site = Path(site)
    tin = site / "tin"
    if tin.is_symlink():
        raise ValueError("Story output directory cannot be a symlink")
    tin.mkdir(parents=True, exist_ok=True)
    for child in tin.iterdir():
        if child.name != "_sample" and STORY_ID.fullmatch(child.name):
            if child.is_symlink():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
            elif child.is_file():
                child.unlink()
    urls = []
    for story_id in sorted(stories):
        story = stories[story_id]
        if story.get("redirect_to"):
            continue
        path = tin / story_id / "index.html"
        _write_bytes(path, render_story_page(story, base_url, sources).encode("utf-8"))
        urls.append(f"{base_url.rstrip('/')}/tin/{story_id}/")

    alias_targets = {}
    for story_id in sorted(stories):
        story = stories[story_id]
        if story.get("redirect_to"):
            target_id = story["redirect_to"]
            if target_id in stories:
                target = stories[target_id]
                while target.get("redirect_to") and target["redirect_to"] in stories:
                    target = stories[target["redirect_to"]]
                alias_targets[story_id] = target
            continue
        for alias_id in sorted(story_aliases(story)):
            if alias_id not in stories and alias_id not in alias_targets:
                alias_targets[alias_id] = story

    for alias_id in sorted(alias_targets):
        target_story = alias_targets[alias_id]
        target_id = target_story["id"]
        target_url = f"{base_url.rstrip('/')}/tin/{target_id}/"
        title = (_text(target_story.get("title_vi")) or _text(target_story.get("title")) or "ai·radar")
        path = tin / alias_id / "index.html"
        _write_bytes(path, render_redirect_page(target_url, title, base_url).encode("utf-8"))

    entries = "".join(f"<url><loc>{html.escape(url)}</loc></url>" for url in urls)
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f"{entries}</urlset>\n")
    _write_bytes(site / "sitemap.xml", sitemap.encode("utf-8"))
    return len(urls)


def _archive_files(directory, allow_git=False):
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Missing or invalid story archive")
    stories_dir = directory / "stories"
    if not stories_dir.is_dir() or stories_dir.is_symlink():
        raise ValueError("Story archive has no stories directory")
    result = {}
    for path in stories_dir.iterdir():
        if path.is_symlink() or not path.is_file() or not STORY_FILE.fullmatch(path.name):
            raise ValueError("Story archive contains an unexpected file")
        story_id = path.stem
        story = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(story, dict) or _story_id(story) != story_id:
            raise ValueError("Story archive file does not match its id")
        _page_fields(story, BASE_URL)
        result[story_id] = _json_bytes(story)
    index_path = directory / "index.json"
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("Story archive has no index")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if (not isinstance(index, dict) or set(index) != {"schema_version", "story_ids"}
            or type(index["schema_version"]) is not int or index["schema_version"] != 1
            or index["story_ids"] != sorted(result)):
        raise ValueError("Story archive index does not match its records")
    unexpected = {path.name for path in directory.iterdir()} - {"index.json", "stories"}
    if allow_git and (directory / ".git").is_dir() and not (directory / ".git").is_symlink():
        unexpected.discard(".git")
    if unexpected:
        raise ValueError("Story archive contains an unexpected path")
    return result


def _write_archive(directory, records):
    directory = Path(directory)
    (directory / "stories").mkdir(parents=True, exist_ok=True)
    for story_id, content in records.items():
        _write_bytes(directory / "stories" / f"{story_id}.json", content)
    _write_bytes(directory / "index.json", _json_bytes({"schema_version": 1,
                                                         "story_ids": sorted(records)}))


def _git_environment(remote):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    parsed = urlsplit(remote)
    if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
        raise ValueError("Remote URLs must not contain credentials")
    token = env.get("GITHUB_TOKEN")
    server = env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if token and remote.startswith(server + "/"):
        import base64
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env[f"GIT_CONFIG_KEY_{count}"] = f"http.{server}/.extraheader"
        env[f"GIT_CONFIG_VALUE_{count}"] = "AUTHORIZATION: basic " + authorization
        env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def _git(repo, remote, *args, allowed=(0,)):
    result = subprocess.run(["git", "-C", str(repo), *args], env=_git_environment(remote),
                            capture_output=True, timeout=120)
    if result.returncode not in allowed:
        raise RuntimeError(f"Story history Git {args[0]} failed (exit {result.returncode})")
    return result


def _restore(remote, repo):
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    if any(repo.iterdir()):
        raise ValueError("Story history restore requires an empty temporary directory")
    _git(repo, remote, "init", "--quiet")
    _git(repo, remote, "config", "core.autocrlf", "false")
    result = _git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, REF, allowed=(0, 2))
    if result.returncode == 2:
        return None
    lines = result.stdout.decode("utf-8").splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != [REF]:
        raise ValueError("Unexpected story branch lookup result")
    advertised = lines[0].split()[0]
    _git(repo, remote, "fetch", "--quiet", "--no-tags", remote, REF)
    commit = _git(repo, remote, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if commit != advertised:
        raise ValueError("Story branch changed during restore; retry the run")
    records = _git(repo, remote, "ls-tree", "-r", "-z", commit).stdout.decode("utf-8")
    paths = []
    for record in records.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        if not metadata.startswith("100644 blob ") or not (path == "index.json" or
                path.startswith("stories/") and STORY_FILE.fullmatch(path.removeprefix("stories/"))):
            raise ValueError("Story branch contains an unexpected path or file type")
        paths.append(path)
    if "index.json" not in paths:
        raise ValueError("Existing story branch has no index")
    _git(repo, remote, "checkout", "--quiet", "--detach", commit)
    _archive_files(repo, allow_git=True)
    return commit


def prepare(remote, input_path, site, candidate, base_url=BASE_URL):
    """Merge the live stories with durable history and build pages plus candidate."""
    started = time.perf_counter()
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("stories"), list):
        raise ValueError("Story snapshot has no stories list")
    current = _validated_story_map(payload["stories"])
    source_records = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    site, candidate = Path(site).resolve(), Path(candidate).resolve()
    if site == candidate or site in candidate.parents or candidate in site.parents:
        raise ValueError("Story output and candidate must be separate directories")
    if candidate.exists() and any(candidate.iterdir()):
        raise ValueError("Story candidate directory is not empty")
    candidate.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="radar-stories-") as temporary:
        repo = Path(temporary) / "repo"
        base = _restore(remote, repo)
        records = _archive_files(repo, allow_git=True) if base else {}
        archived_stories = {sid: json.loads(content) for sid, content in records.items()}
        for story_id, story in current.items():
            for alias_id in story_aliases(story):
                if alias_id in archived_stories and alias_id != story_id and alias_id not in current:
                    archived = archived_stories[alias_id]
                    archived["redirect_to"] = story_id
                    records[alias_id] = _json_bytes(archived)
        records.update({story_id: _json_bytes(story) for story_id, story in current.items()})
        candidate_archive = candidate / "archive"
        _write_archive(candidate_archive, records)
        _write_bytes(candidate / "manifest.json", _json_bytes({"schema_version": 1,
                                                                "base_commit": base}))
        stories = {story_id: json.loads(content) for story_id, content in records.items()}
        count = render_site(stories, site, base_url, source_records)
        if _archive_files(candidate_archive) != records:
            raise RuntimeError("Story candidate read-back failed")
    return {"count": count, "elapsed_seconds": time.perf_counter() - started,
            "base_commit": base}


def persist(remote, candidate):
    """Append/update story records with a base check and ordinary fast-forward push."""
    candidate = Path(candidate)
    if candidate.is_symlink() or {path.name for path in candidate.iterdir()} != {"manifest.json", "archive"}:
        raise ValueError("Invalid story candidate layout")
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "base_commit"}
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["base_commit"] is not None
            and not re.fullmatch(r"[0-9a-f]{40,64}", str(manifest["base_commit"]))):
        raise ValueError("Invalid story candidate manifest")
    desired = _archive_files(candidate / "archive")
    with tempfile.TemporaryDirectory(prefix="radar-story-history-") as temporary:
        repo = Path(temporary)
        base = _restore(remote, repo)
        existing = _archive_files(repo, allow_git=True) if base else {}
        if existing == desired:
            return False
        if base != manifest["base_commit"]:
            raise ValueError("Story history advanced since preparation; prepare again")
        if any(desired.get(story_id) is None for story_id in existing):
            raise ValueError("Candidate removes an archived story")
        for story_id, content in desired.items():
            _write_bytes(repo / "stories" / f"{story_id}.json", content)
        _write_bytes(repo / "index.json", _json_bytes({"schema_version": 1,
                                                       "story_ids": sorted(desired)}))
        if _archive_files(repo, allow_git=True) != desired:
            raise RuntimeError("Story history write read-back failed")
        _git(repo, remote, "add", "--", "stories", "index.json")
        _git(repo, remote, "-c", "user.name=github-actions[bot]", "-c",
             "user.email=41898282+github-actions[bot]@users.noreply.github.com",
             "commit", "--quiet", "-m", "Update story page history")
        _git(repo, remote, "push", "--quiet", remote, f"HEAD:{REF}")
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare", help="Build pages and a candidate without pushing")
    build.add_argument("--remote", required=True)
    build.add_argument("--input", default="site/data/radar-ui.json")
    build.add_argument("--site", default="site")
    build.add_argument("--candidate", default="data/story-pages-candidate")
    build.add_argument("--base-url", default=BASE_URL)
    save = commands.add_parser("persist", help="Append the candidate to radar-story-pages")
    save.add_argument("--remote", required=True)
    save.add_argument("--candidate", default="data/story-pages-candidate")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.remote, args.input, args.site, args.candidate, base_url=args.base_url)
            print(f"Story pages prepared: {result['count']} URLs in {result['elapsed_seconds']:.2f}s")
        else:
            changed = persist(args.remote, args.candidate)
            print("Story history saved and read back" if changed else "Story history already saved")
    except subprocess.SubprocessError:
        print("Story operation failed: Git subprocess failed or timed out")
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Story operation failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

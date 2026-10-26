"""Copy the homepage into the extension and apply its small MV3 data adapter."""

from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
EXT = ROOT / 'extension'
LIVE = 'https://radar-ai-vn.pages.dev/'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Expected one source anchor: {old[:80]}')
    return source.replace(old, new)


def replace_count(source, old, new, expected):
    if source.count(old) != expected:
        raise ValueError(f'Expected {expected} source anchors: {old[:80]}')
    return source.replace(old, new)


def replace_pattern_once(source, pattern, replacement, flags=0):
    result, count = re.subn(pattern, replacement, source, count=1, flags=flags)
    if count != 1:
        raise ValueError(f'Expected one source pattern: {pattern[:80]}')
    return result


def validate_html(html):
    if re.search(r'<script\b(?![^>]*\bsrc=["\'](?:\./)?[\w./-]+\.js["\'])[^>]*>', html, re.I):
        raise ValueError('Inline or nonlocal script in generated newtab.html')
    if re.search(r'<script\b[^>]*\bsrc=["\']https?://', html, re.I):
        raise ValueError('Remote script in generated newtab.html')
    validate_urls(html)


def validate_urls(source):
    for match in re.finditer(r'(?:href|src)=["\']([^"\']+)["\']', source):
        url = match.group(1)
        if url.startswith(('tin/', 'data/')) or (
            not url.startswith(('https://', 'http://', '#', '/'))
            and re.search(r'\.html(?:[?#]|$)', url)
        ):
            raise ValueError(f'Relative page or data URL: {url[:80]}')
    if re.search(r'["\']data/', source):
        raise ValueError('Relative data URL in generated source')


def write(path, value):
    path.write_bytes(value.replace('\r\n', '\n').encode('utf-8'))


def adapt_html(html):
    html = replace_pattern_once(html, r'<!-- The site root since 05/10:.*?-->\n', '', re.S)
    html = replace_pattern_once(html, r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', '')
    html = replace_pattern_once(html, r'<script>try \{ var t = .*?</script>\n', '<script src="theme.js"></script>\n')
    html = replace_pattern_once(html, r'<!-- Cloudflare Web Analytics -->.*?<!-- End Cloudflare Web Analytics -->\n', '')
    html = replace_pattern_once(html, r'<!-- The snapshot is the page.s only content:.*?-->\n', '', re.S)
    html = replace_pattern_once(html, r'<link rel="preload" href="data/radar-window.json" as="fetch" crossorigin>\n', '')
    html = replace_once(html, '<script type="module" src="feed.js"></script>',
                        '<script type="module" src="feed.js"></script>\n<script type="module" src="newtab.js"></script>\n<link rel="stylesheet" href="newtab.css">')
    for name in ('ban-tin.html', 'tra-cuu.html'):
        html = replace_once(html, f'href="{name}"', f'href="{LIVE}{name}"')
    html = replace_once(html, '<main class="feed-main" id="top" tabindex="-1" aria-busy="true">',
                        '<main class="feed-main" id="top" tabindex="-1" aria-busy="true">\n'
                        '  <form id="web-search" role="search" aria-label="Tìm trên web">\n'
                        '    <label class="sr" for="web-query">Tìm trên web</label>\n'
                        '    <div class="web-search-field"><svg class="i" aria-hidden="true"><use href="#i-search"/></svg>'
                        '<input id="web-query" type="search" placeholder="Tìm trên web" autocomplete="off" required></div>\n'
                        '    <button type="submit">Tìm</button>\n'
                        '  </form>')
    validate_html(html)
    return html


def adapt_feed(feed):
    feed = replace_once(feed, "import { createArenaView } from './arena.js';",
                        "import { createArenaView } from './arena.js';\nimport { cachedSnapshot, normalizeSnapshot } from './snapshot.js';")
    feed = replace_once(feed, "const DATA_URL = customData ? qp : 'data/radar-ui.json';",
                        f"const DATA_URL = '{LIVE}data/radar-ui.json';")
    feed = replace_once(feed, "const SOURCES = customData ? [qp] : [DATA_URL, 'data/radar.json'];",
                        'const SOURCES = [DATA_URL];')
    feed = replace_once(feed, "const WINDOW_URL = customData ? null : 'data/radar-window.json';",
                        'const WINDOW_URL = null; // The worker supplies the first snapshot from chrome.storage.local.')
    feed = replace_once(feed, 'let complete = customData;', 'let complete = false;')
    feed = replace_once(feed, "const FIELD_RANKINGS_URL = 'data/field-rankings.json';",
                        f"const FIELD_RANKINGS_URL = '{LIVE}data/field-rankings.json';")
    feed = replace_once(feed, "const IMAGES_URL = 'feed-images.json';",
                        f"const IMAGES_URL = '{LIVE}feed-images.json';\nconst PACKAGED_IMAGES_URL = 'feed-images.json';")
    feed = replace_once(feed, "const PICKS_URL = 'editor-picks.json';",
                        f"const PICKS_URL = '{LIVE}editor-picks.json';\nconst PACKAGED_PICKS_URL = 'editor-picks.json';")
    start = feed.index('async function loadFirst() {')
    end = feed.index('\n/* ---------- small readers ---------- */', start)
    expected = """async function loadFirst() {
  if (WINDOW_URL && !needsComplete(true)) {
    try {
      const j = await fetchJSON(WINDOW_URL);
      if (j && j.schema_version === 2 && Array.isArray(j.stories)) return j;
      console.warn('radar-window.json is not a v2 snapshot; loading the complete snapshot');
    } catch (e) { console.warn('radar-window.json unavailable; loading the complete snapshot', e); }
  }
  complete = true;
  return loadData();
}
"""
    if feed[start:end].replace('\r\n', '\n') != expected:
        raise ValueError('Unexpected loadFirst source span')
    feed = feed[:start] + "async function loadFirst() {\n  const snapshot = await cachedSnapshot();\n  if (!snapshot) throw new Error('No saved radar window yet');\n  return snapshot;\n}\n" + feed[end:]
    feed = replace_once(feed, 'if (j && j.schema_version === 2 && Array.isArray(j.stories)) return j;',
                        'if (j && j.schema_version === 2 && Array.isArray(j.stories)) return normalizeSnapshot(j);')
    feed = replace_once(feed, "const [, data, picks, fieldData] = await Promise.all([loadImages(), loadFirst(), loadPicks(), loadFieldRankings()]);",
                        'const [, data, picks] = await Promise.all([loadImages(), loadFirst(), loadPicks()]);\n    const fieldData = null;')
    feed = replace_once(feed, '  whenIdle().then(loadComplete);',
                        "  whenIdle().then(async () => {\n    if (!navigator.onLine) return;\n    await loadComplete();\n    FIELD_DATA = await loadFieldRankings();\n    if (FIELD_DATA && Array.isArray(FIELD_DATA.fields)) {\n      FIELD_MAP = new Map(FIELD_DATA.fields.map(f => [f.id, f]));\n      mergeFieldRepos();\n      if (filter === 'rankings') renderFeed();\n    }\n  });")
    feed = replace_once(feed, '  if (complete || !D) return Promise.resolve();',
                        '  if (complete || !D || !navigator.onLine) return Promise.resolve();')
    feed = replace_once(feed, '  if (document.hidden || !D) return;',
                        '  if (document.hidden || !D || !navigator.onLine) return;')
    feed = replace_count(feed, 'href="tin/', f'href="{LIVE}tin/', 5)
    feed = replace_once(feed, 'const targetUrl = `tin/${encodeURIComponent(id)}/`;',
                        'const targetUrl = `#tin/${encodeURIComponent(id)}`;')
    feed = replace_once(feed, "const u = location.origin + (location.pathname.replace(/\\/tin\\/[^/]+\\/?$/, '/') || '/') + 'tin/' + encodeURIComponent(currentModalStoryId) + '/';",
                        f"const u = '{LIVE}tin/' + encodeURIComponent(currentModalStoryId) + '/';")
    feed = replace_once(feed, 'href="nguon.html"', f'href="{LIVE}nguon.html"')
    feed = replace_once(feed, "location.replace('nguon.html')", f"location.replace('{LIVE}nguon.html')")
    feed = replace_once(feed, "location.href = 'tra-cuu.html'", f"location.href = '{LIVE}tra-cuu.html'")
    feed = replace_once(feed, "fetchJSON(PICKS_URL, { cache: 'no-cache' })",
                        "fetchJSON(PICKS_URL, { cache: 'no-cache' }).catch(() => fetchJSON(PACKAGED_PICKS_URL))")
    feed = replace_once(feed, 'fetchJSON(IMAGES_URL)',
                        'fetchJSON(IMAGES_URL).catch(() => fetchJSON(PACKAGED_IMAGES_URL))')
    validate_urls(feed)
    return feed


def sync():
    html = adapt_html((SITE / 'index.html').read_text(encoding='utf-8'))
    feed = adapt_feed((SITE / 'feed.js').read_text(encoding='utf-8'))
    arena = replace_once((SITE / 'arena.js').read_text(encoding='utf-8'),
                         "fetch('data/arena.json'", f"fetch('{LIVE}data/arena.json'")
    story = replace_once((SITE / 'story.js').read_text(encoding='utf-8'),
                         'new URL(story.image.src, import.meta.url).href',
                         f"new URL(story.image.src, '{LIVE}').href")
    story = replace_once(story, 'href="../../index.html"', f'href="{LIVE}index.html"')
    validate_urls(arena)
    validate_urls(story)
    for name in ('tokens.css', 'feed.css', 'arena.css', 'story.css',
                 'faces.js', 'time-text.js', 'words.js', 'titles.js', 'editorial-headline.js',
                 'calendar.js', 'worth-score.js', 'live.js',
                 'feed-images.json', 'editor-picks.json',
                 'favicon.ico', 'apple-touch-icon.png', 'logo.svg'):
        shutil.copyfile(SITE / name, EXT / name)
    shutil.copytree(SITE / 'fonts', EXT / 'fonts', dirs_exist_ok=True)
    write(EXT / 'arena.js', arena)
    write(EXT / 'story.js', story)
    write(EXT / 'newtab.html', html)
    write(EXT / 'feed.js', feed)
    validate_html((EXT / 'newtab.html').read_text(encoding='utf-8'))
    for name in ('feed.js', 'arena.js', 'story.js'):
        validate_urls((EXT / name).read_text(encoding='utf-8'))


if __name__ == '__main__':
    sync()

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


def write(path, value):
    path.write_bytes(value.replace('\r\n', '\n').encode('utf-8'))


def sync():
    for name in ('tokens.css', 'feed.css', 'arena.css', 'story.css',
                 'faces.js', 'time-text.js', 'words.js', 'titles.js',
                 'calendar.js', 'arena.js', 'story.js', 'worth-score.js',
                 'live.js', 'feed-images.json', 'editor-picks.json',
                 'favicon.ico', 'apple-touch-icon.png'):
        shutil.copyfile(SITE / name, EXT / name)
    shutil.copytree(SITE / 'fonts', EXT / 'fonts', dirs_exist_ok=True)

    html = (SITE / 'index.html').read_text(encoding='utf-8')
    html = re.sub(r'<!-- The site root since 05/10:.*?-->\n', '', html, count=1, flags=re.S)
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', '', html, count=1)
    html = re.sub(r'<script>try \{ var t = .*?</script>\n', '<script src="theme.js"></script>\n', html, count=1)
    html = re.sub(r'<!-- Cloudflare Web Analytics -->.*?<!-- End Cloudflare Web Analytics -->\n', '', html, count=1)
    html = re.sub(r'<!-- The snapshot is the page.s only content:.*?-->\n', '', html, count=1, flags=re.S)
    html = re.sub(r'<link rel="preload" href="data/radar-window.json" as="fetch" crossorigin>\n', '', html, count=1)
    html = replace_once(html, '<script type="module" src="feed.js"></script>',
                        '<script type="module" src="feed.js"></script>\n<script type="module" src="newtab.js"></script>\n<link rel="stylesheet" href="newtab.css">')
    for name in ('ban-tin.html', 'tra-cuu.html'):
        html = html.replace(f'href="{name}"', f'href="{LIVE}{name}"')
    html = replace_once(html, '<main class="feed-main" id="top" tabindex="-1" aria-busy="true">',
                        '<main class="feed-main" id="top" tabindex="-1" aria-busy="true">\n'
                        '  <form id="web-search" role="search" aria-label="Tìm trên web">\n'
                        '    <label class="sr" for="web-query">Tìm trên web</label>\n'
                        '    <div class="web-search-field"><svg class="i" aria-hidden="true"><use href="#i-search"/></svg>'
                        '<input id="web-query" type="search" placeholder="Tìm trên web" autocomplete="off" required></div>\n'
                        '    <button type="submit">Tìm</button>\n'
                        '  </form>')
    write(EXT / 'newtab.html', html)

    feed = (SITE / 'feed.js').read_text(encoding='utf-8')
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
    start = feed.index('async function loadFirst() {')
    end = feed.index('\n/* ---------- small readers ---------- */', start)
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
    feed = feed.replace('href="tin/', f'href="{LIVE}tin/')
    feed = replace_once(feed, 'const targetUrl = `tin/${encodeURIComponent(id)}/`;',
                        'const targetUrl = `#tin/${encodeURIComponent(id)}`;')
    feed = replace_once(feed, "const u = location.origin + (location.pathname.replace(/\\/tin\\/[^/]+\\/?$/, '/') || '/') + 'tin/' + encodeURIComponent(currentModalStoryId) + '/';",
                        f"const u = '{LIVE}tin/' + encodeURIComponent(currentModalStoryId) + '/';")
    feed = feed.replace('href="nguon.html"', f'href="{LIVE}nguon.html"')
    feed = feed.replace("location.replace('nguon.html')", f"location.replace('{LIVE}nguon.html')")
    feed = feed.replace("location.href = 'tra-cuu.html'", f"location.href = '{LIVE}tra-cuu.html'")
    write(EXT / 'feed.js', feed)


if __name__ == '__main__':
    sync()

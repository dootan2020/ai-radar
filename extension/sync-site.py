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
    html = replace_pattern_once(html, r"<script>var d = document\.documentElement\.dataset;.*?</script>\n", '<script src="theme.js"></script>\n')
    html = replace_pattern_once(html, r'\n<!-- The stream player \(trinh-phat\.js\).*?</dialog>\n', '', re.S)
    # The extension ships its files together, so it carries no asset versions (radar/front_lead.py stamp_assets): no
    # import map (an inline script, which MV3 forbids) and plain file names, even when a local build stamped the page.
    html = replace_pattern_once(html, r'<!-- Every script and stylesheet below is named with \?v=.*?<!-- /asset versions -->\n', '', re.S)
    html = re.sub(r'((?:src|href)="[\w.-]+\.(?:js|css))\?v=[0-9a-f]*"', r'\1"', html)
    # The new tab draws from its own saved snapshot, so it carries no lead a site build baked in (radar/front_lead.py):
    # no picture preload, and the plain placeholder in the lead's place.
    html = replace_pattern_once(html, r'<!-- lead picture: .*?<!-- /lead picture -->\n', '', re.S)
    html = replace_pattern_once(html, r'  <!-- lead slide: .*?<!-- /lead slide -->\n',
                                '  <div class="msn-card msn-sk msn-lead"></div>\n', re.S)
    # The new tab reads its files from the disk and draws its own top row, so it keeps the stylesheets as plain blocking
    # links: no inline first-screen block (radar/critical_css.py) and no preloads for nap-kieu.js to apply.
    html = replace_pattern_once(html, r'<!-- No stylesheet holds the first paint .*?-->\n', '', re.S)
    html = replace_pattern_once(html, r'<!-- critical css: .*?<!-- /critical css -->\n', '', re.S)
    for sheet in ('tokens.css', 'feed.css', 'trang-nhat.css', 'trang-msn.css', 'menu-cong-cu.css'):
        html = replace_once(html, f'<link rel="preload" href="{sheet}" as="style">', f'<link rel="stylesheet" href="{sheet}">')
    html = replace_pattern_once(html, r'<!-- The snapshot is the page.s only content:.*?-->\n', '', re.S)
    html = replace_pattern_once(html, r'<link rel="preload" href="data/radar-window.json" as="fetch" crossorigin>\n', '')
    # The new tab reads the picture map from the live site first (adapt_feed), not from this file.
    html = replace_once(html, '<link rel="preload" href="feed-images.json" as="fetch" crossorigin>\n', '')
    html = replace_once(html, '<link rel="modulepreload" href="trinh-phat.js">\n', '')   # the new tab has no stream player
    html = replace_once(html, '<script type="module" src="feed.js"></script>',
                        '<script type="module" src="feed.js"></script>\n<script type="module" src="newtab.js"></script>\n'
                        '<link rel="stylesheet" href="newtab.css">')
    # The new tab's rows above the panel (captain, 07/11 18:03, mockup D chosen 18:26; Mẫu A 08/11 18:23): the web
    # search (the reader's default engine, newtab.js) with the 9 dots, in place of the site's top row. The site's news search moves
    # into the panel head beside the morning edition; the brand and the edition point at the live site.
    top = re.search(r'<!-- The top row \(Mẫu A.*?</header>\n', html, re.S)
    if not top:
        raise ValueError('Expected the site top row')
    search = re.search(r'\n    <div class="news-search" id="news-search">.*?<div class="ns-results" id="ns-results" hidden></div>\n    </div>', top.group(0), re.S)
    if not (search and top.group(0).count('<div class="tool-launcher"></div>') == 1
            and top.group(0).count('<div class="top-now" id="top-now"></div>') == 1 and 'id="tc-open"' in top.group(0)):
        raise ValueError('Unexpected top row source')
    html = html.replace(top.group(0), TOP_ZONE, 1)
    html = replace_once(html, '<a class="brand feed-brand" id="brand" href="/" aria-label="Halcyon, về đầu trang">',
                        f'<a class="brand feed-brand" id="brand" href="{LIVE}" aria-label="Halcyon, mở trang web">')
    html = replace_once(html, '\n    <div class="head-actions">', '\n    <div class="head-actions">' + search.group(0).replace('\n    ', '\n      '))
    html = replace_once(html, '<a class="ed-link" href="ban-tin.html"', f'<a class="ed-link" href="{LIVE}ban-tin.html"')
    validate_html(html)
    return html


# The extension's own top rows (captain, 07/11 18:03 and 18:26): they replace the site's top row (adapt_html);
# newtab.js drives the search.
TOP_ZONE = '''<!-- The top row (owner, 09/11): the web search with the 9 dots at its right, on the website's own top-row grid
     (.msn-top-in), so the row and the panel below it share their left and right edges. The seven Google shortcut icons
     are gone: the 9 dots open the same services. The weather and the calendar are cards in the panel's first row
     (thoi-tiet.js, the-lich.js); the weather and the day also sit at the top left and "Tùy chỉnh" beside the 9 dots,
     as on the website (captain, 10/11; thanh-tren.js). -->
<header class="masthead msn-top" id="masthead">
  <div class="msn-top-in">
    <div class="top-now" id="top-now"></div>
    <form id="web-search" class="web-search" role="search" aria-label="Tìm trên web">
      <label class="web-field">
        <svg class="i" aria-hidden="true"><use href="#i-search"/></svg>
        <span class="sr">Tìm trên web</span>
        <input id="web-query" name="q" type="search" placeholder="Tìm trên web" autocomplete="off" enterkeyhint="search">
        <button class="go-btn" type="submit" aria-label="Tìm trên web"><svg class="i" aria-hidden="true"><use href="#i-arrow"/></svg></button>
      </label>
    </form>
    <div class="masthead-actions">
      <button class="top-tile" id="tc-open" type="button" aria-label="Tùy chỉnh" title="Tùy chỉnh" aria-expanded="false" aria-controls="tuy-chinh"><svg class="i" aria-hidden="true"><use href="#i-tune"/></svg></button>
      <div class="tool-launcher"></div>
    </div>
  </div>
</header>
'''


def adapt_feed(feed):
    feed = replace_once(feed, "import { createNewsSearch } from './tim-tin.js';",
                        "import { createNewsSearch } from './tim-tin.js';\nimport { cachedSnapshot, normalizeSnapshot } from './snapshot.js';")
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
    # The new tab keeps loading the complete snapshot when idle, then the field rankings, and only when online: its
    # first snapshot comes from storage, not the network.
    # Its first draw never waits on the network either (the site waits for the field rankings when areas are saved).
    feed = replace_once(feed, "const needsFieldsFirst = () => filter === 'code' || areas.size > 0;",
                        "const needsFieldsFirst = () => false;   // the new tab draws from storage first")
    feed = replace_once(feed, "  whenReaderActs().then(loadComplete);\n  if (!FIELD_DATA) whenIdle().then(() => loadFieldRankings()).then(applyFieldRankings);",
                        "  whenIdle().then(async () => {\n    if (!navigator.onLine) return;\n    await loadComplete();\n    applyFieldRankings(await loadFieldRankings());\n  });")
    feed = replace_once(feed, '  if (complete || !D) return Promise.resolve();',
                        '  if (complete || !D || !navigator.onLine) return Promise.resolve();')
    feed = replace_once(feed, '  if (document.hidden || !D) return;',
                        '  if (document.hidden || !D || !navigator.onLine) return;')
    feed = replace_count(feed, 'href="tin/', f'href="{LIVE}tin/', 2)
    feed = replace_once(feed, 'const storyHref = st => `tin/${esc(st.id)}/`;', f'const storyHref = st => `{LIVE}tin/${{esc(st.id)}}/`;')
    feed = replace_once(feed, 'const targetUrl = `tin/${encodeURIComponent(id)}/`;',
                        'const targetUrl = `#tin/${encodeURIComponent(id)}`;')
    feed = replace_once(feed, "const u = location.origin + (location.pathname.replace(/\\/tin\\/[^/]+\\/?$/, '/') || '/') + 'tin/' + encodeURIComponent(currentModalStoryId) + '/';",
                        f"const u = '{LIVE}tin/' + encodeURIComponent(currentModalStoryId) + '/';")
    feed = replace_once(feed, "const EDITION_URL = 'ban-tin.html';", f"const EDITION_URL = '{LIVE}ban-tin.html';")
    # Measured 10/11: YouTube answers the new tab's embed with "Video player configuration error" (no referrer from a
    # chrome-extension:// page), so the new tab keeps its streams as links until the extension can send one, and
    # carries no player: no trinh-phat.js, no player dialog, no YouTube embed host.
    feed = replace_once(feed, 'const PLAYER_ON = true;', 'const PLAYER_ON = false;')
    feed = replace_once(feed, "import { createPlayer, playable, watchURL } from './trinh-phat.js';",
                        "const createPlayer = null, playable = () => false, watchURL = () => '#';  // no player in the new tab")
    feed = replace_once(feed, "location.replace('nguon.html')", f"location.replace('{LIVE}nguon.html')")
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
    # The header's Google apps launcher and phone navigation bar. The extension has no site pages, so the
    # phone bar's "Dòng tin" is this new tab and the other destinations open on the live site.
    menu = replace_once((SITE / 'menu-cong-cu.js').read_text(encoding='utf-8'),
                        "const current = story ? 'index.html' : page;", "const current = 'index.html';")
    menu = replace_once(menu, ': `${prefix}${file}`;',
                        f": file === 'index.html' ? '#top' : file.startsWith('index.html#') ? file.slice(10) : `{LIVE}${{file}}`;")
    if re.search(r"""\$\{prefix\}|href = ['"`](?!https://|#)""", menu):
        raise ValueError('Relative page link left in generated menu-cong-cu.js')
    # The news bar's search reads the live index; offline it searches the stories on the page.
    search = replace_once((SITE / 'tim-tin.js').read_text(encoding='utf-8'),
                          "const SEARCH_URL = 'data/radar-search.json';", f"const SEARCH_URL = '{LIVE}data/radar-search.json';")
    validate_urls(arena)
    validate_urls(story)
    validate_urls(search)
    for name in ('tokens.css', 'feed.css', 'arena.css', 'story.css', 'trang-nhat.css', 'trang-msn.css',
                 'thoi-tiet.js', 'the-lich.js', 'lich-am.js',
                 'faces.js', 'time-text.js', 'words.js', 'titles.js', 'editorial-headline.js',
                 'calendar.js', 'worth-score.js', 'live.js', 'menu-cong-cu.css', 'nen.js', 'thanh-tren.js', 'nap-kieu.js',
                 'feed-images.json', 'editor-picks.json',
                 'favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'logo.svg', 'wordmark.svg', 'wordmark-dark.svg'):
        shutil.copyfile(SITE / name, EXT / name)
    shutil.copytree(SITE / 'fonts', EXT / 'fonts', dirs_exist_ok=True)
    shutil.copytree(SITE / 'google-apps', EXT / 'google-apps', dirs_exist_ok=True)
    shutil.copytree(SITE / 'con-giap', EXT / 'con-giap', dirs_exist_ok=True)
    shutil.copytree(SITE / 'anh', EXT / 'anh', dirs_exist_ok=True)
    write(EXT / 'arena.js', arena)
    write(EXT / 'story.js', story)
    write(EXT / 'menu-cong-cu.js', menu)
    write(EXT / 'tim-tin.js', search)
    write(EXT / 'newtab.html', html)
    write(EXT / 'feed.js', feed)
    validate_html((EXT / 'newtab.html').read_text(encoding='utf-8'))
    for name in ('feed.js', 'arena.js', 'story.js', 'menu-cong-cu.js', 'tim-tin.js'):
        validate_urls((EXT / name).read_text(encoding='utf-8'))


if __name__ == '__main__':
    sync()

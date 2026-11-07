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
                        '<script type="module" src="feed.js"></script>\n<script type="module" src="newtab.js"></script>\n'
                        '<script type="module" src="vung-dau.js"></script>\n<link rel="stylesheet" href="newtab.css">')
    # The new tab's three rows above the news (captain, 07/11 18:03, mockup D "Dòng ngày" chosen 18:26): the Google
    # services with the 9 dots, the Google search with the day line under it, then the Halcyon bar. The site's masthead
    # becomes the first two rows; its brand (the wordmark alone, no tile and no tagline), the morning edition link and
    # the theme button move into the news bar, and the sort switch joins them so no line sits between the bar and the news.
    masthead = re.search(r'<!-- Masthead:.*?</header>\n', html, re.S)
    if not masthead:
        raise ValueError('Expected the site masthead')
    head = masthead.group(0)
    brand = re.search(r'<a class="brand feed-brand" id="brand" href="#top" aria-label="Halcyon, về đầu trang">'
                      r'(<img [^>]*>)(<img [^>]*>)<span class="brand-tag">[^<]*</span></a>', head)
    edition = re.search(r'<a class="ed-link" href="ban-tin\.html".*?</a>', head)
    theme = re.search(r'<button class="theme-btn" id="theme-btn".*?</button>', head, re.S)
    if not (brand and edition and theme and head.count('<div class="tool-launcher"></div>') == 1):
        raise ValueError('Unexpected masthead source')
    html = html.replace(head, TOP_ZONE, 1)
    html = replace_once(html, '<a class="bar-tile" href="#top" tabindex="-1" aria-hidden="true"><img src="logo.svg" width="32" height="32" alt=""></a>',
                        f'<a class="brand feed-brand bar-brand" id="brand" href="{LIVE}" aria-label="Halcyon, mở trang web">'
                        f'{brand.group(1)}{brand.group(2)}</a>')
    sort = re.search(r'\n    <div class="sort-switch" id="sort-switch".*?\n    </div>', html, re.S)
    if not sort:
        raise ValueError('Expected the sort switch')
    html = html.replace(sort.group(0), '', 1)
    html = replace_once(html, '\n    <div class="news-search" id="news-search">',
                        sort.group(0) + '\n    <div class="news-search" id="news-search">')
    html = replace_once(html, '<div class="ns-results" id="ns-results" hidden></div>\n    </div>',
                        '<div class="ns-results" id="ns-results" hidden></div>\n    </div>\n    '
                        + edition.group(0).replace('href="ban-tin.html"', f'href="{LIVE}ban-tin.html"')
                        + '\n    ' + theme.group(0))
    # The freshness line closes the page, as in mockup D; the heading above the bento stays for screen readers.
    html = replace_once(html, '\n    <p class="front-fresh" id="front-fresh"></p>', '')
    html = replace_once(html, '<p class="src-note" id="src-update"></p>',
                        '<p class="front-fresh" id="front-fresh"></p>\n    <p class="src-note" id="src-update"></p>')
    validate_html(html)
    return html


# The extension's own top rows (captain, 07/11 18:03 and 18:26): they replace the site masthead (adapt_html);
# vung-dau.js and newtab.js fill and drive them.
TOP_ZONE = '''<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <symbol id="w-clear-day" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></symbol>
  <symbol id="w-clear-night" viewBox="0 0 24 24"><path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10z"/></symbol>
  <symbol id="w-partly" viewBox="0 0 24 24"><path d="M8.5 4.5v1.2M3.6 9.5h1.2M5 6l.9.9M12 6l-.9.9"/><path d="M5.7 12.3a3.5 3.5 0 0 1 6.4-3.2"/><path d="M8 19.5h9a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6 1.4A2.8 2.8 0 0 0 8 19.5z"/></symbol>
  <symbol id="w-cloud" viewBox="0 0 24 24"><path d="M7 18.5h10.5a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.6A3.2 3.2 0 0 0 7 18.5z"/></symbol>
  <symbol id="w-fog" viewBox="0 0 24 24"><path d="M7 13.5h10.5a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.6A3.2 3.2 0 0 0 7 13.5z"/><path d="M5 17h14M7 20.5h10"/></symbol>
  <symbol id="w-rain" viewBox="0 0 24 24"><path d="M7 14.5h10.5a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.6A3.2 3.2 0 0 0 7 14.5z"/><path d="M8.5 17.5l-1 2.5M12.5 17.5l-1 2.5M16.5 17.5l-1 2.5"/></symbol>
  <symbol id="w-storm" viewBox="0 0 24 24"><path d="M7 14.5h10.5a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.6A3.2 3.2 0 0 0 7 14.5z"/><path d="M12.5 15.5l-2 3.5h3l-2 3.5"/></symbol>
  <symbol id="w-snow" viewBox="0 0 24 24"><path d="M7 14.5h10.5a4 4 0 0 0 .5-8 6 6 0 0 0-11.5 1.6A3.2 3.2 0 0 0 7 14.5z"/><path d="M9 18.5h.01M12 20.5h.01M15 18.5h.01"/></symbol>
</svg>
<!-- Rows 1 and 2 (mockup D; row 1 compacted 07/11 22:41): the Google shortcuts as one cluster of icons with every Google
     app behind the 9 dots, at the top right, then the Google search with the day line under it (date · lunar date ·
     weather). Row 3 is the news bar below. -->
<header class="masthead top" id="masthead">
  <div class="wrap g-row">
    <ul class="services" id="services" aria-label="Dịch vụ Google"></ul>
    <div class="tool-launcher"></div>
  </div>
  <div class="wrap hero" id="top-zone">
    <form id="web-search" class="web-search" role="search" aria-label="Tìm trên Google" action="https://www.google.com/search">
      <label class="web-field">
        <svg class="i" aria-hidden="true"><use href="#i-search"/></svg>
        <span class="sr">Tìm trên Google</span>
        <input id="web-query" name="q" type="search" placeholder="Tìm trên Google" autocomplete="off" enterkeyhint="search">
        <button class="go-btn" type="submit" aria-label="Tìm trên Google"><svg class="i" aria-hidden="true"><use href="#i-arrow"/></svg></button>
      </label>
    </form>
    <div class="dayline" id="dateline">
      <p class="day-date" id="day-date"></p>
      <span class="sep wx-sep" aria-hidden="true">·</span>
      <div class="wx weather" id="weather" aria-live="polite"><span class="wx-skel" aria-hidden="true"></span><span class="sr">Đang lấy thời tiết</span></div>
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
    feed = replace_once(feed, "const [, data, picks, fieldData] = await Promise.all([loadImages(), loadFirst(), loadPicks(), loadFieldRankings()]);",
                        'const [, data, picks] = await Promise.all([loadImages(), loadFirst(), loadPicks()]);\n    const fieldData = null;')
    feed = replace_once(feed, '  whenIdle().then(loadComplete);',
                        "  whenIdle().then(async () => {\n    if (!navigator.onLine) return;\n    await loadComplete();\n    FIELD_DATA = await loadFieldRankings();\n    if (FIELD_DATA && Array.isArray(FIELD_DATA.fields)) {\n      FIELD_MAP = new Map(FIELD_DATA.fields.map(f => [f.id, f]));\n      mergeFieldRepos();\n      if (filter === 'rankings') renderFeed();\n    }\n  });")
    feed = replace_once(feed, '  if (complete || !D) return Promise.resolve();',
                        '  if (complete || !D || !navigator.onLine) return Promise.resolve();')
    feed = replace_once(feed, '  if (document.hidden || !D) return;',
                        '  if (document.hidden || !D || !navigator.onLine) return;')
    feed = replace_count(feed, 'href="tin/', f'href="{LIVE}tin/', 3)
    feed = replace_once(feed, 'const targetUrl = `tin/${encodeURIComponent(id)}/`;',
                        'const targetUrl = `#tin/${encodeURIComponent(id)}`;')
    feed = replace_once(feed, "const u = location.origin + (location.pathname.replace(/\\/tin\\/[^/]+\\/?$/, '/') || '/') + 'tin/' + encodeURIComponent(currentModalStoryId) + '/';",
                        f"const u = '{LIVE}tin/' + encodeURIComponent(currentModalStoryId) + '/';")
    feed = replace_once(feed, 'href="nguon.html"', f'href="{LIVE}nguon.html"')
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
    story = replace_once(story, 'href="../../index.html"', f'href="{LIVE}index.html"')
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
    for name in ('tokens.css', 'feed.css', 'arena.css', 'story.css', 'trang-nhat.css',
                 'faces.js', 'time-text.js', 'words.js', 'titles.js', 'editorial-headline.js',
                 'calendar.js', 'worth-score.js', 'live.js', 'menu-cong-cu.css',
                 'feed-images.json', 'editor-picks.json',
                 'favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'logo.svg', 'wordmark.svg', 'wordmark-dark.svg'):
        shutil.copyfile(SITE / name, EXT / name)
    shutil.copytree(SITE / 'fonts', EXT / 'fonts', dirs_exist_ok=True)
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

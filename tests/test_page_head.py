"""Static checks for the production page: its <head> (CSP, canonical, referrer, how the snapshot and fonts load) and
the wiring of the fixes measured on the rendered page (story sheet as a modal dialog, upcoming events, touch areas,
stale-data line, phone lead, brand plates in dark mode).

The rendered behaviour itself is measured with headless Chrome (plans/reports/san-ui-claude.md); these tests keep
the pieces from silently disappearing.
"""

from pathlib import Path
from html.parser import HTMLParser
import base64
import hashlib
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def read(path):
    return path.read_text(encoding="utf-8")


def csp_directives(html):
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    if not meta:
        raise AssertionError("no CSP meta tag")
    out = {}
    for part in meta.group(1).split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


class ScriptSources(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sources = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.sources.extend(value for name, value in attrs if name == "src")


class PageHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read(SITE / "index.html")
        cls.head = cls.html.split("</head>")[0]
        cls.csp = csp_directives(cls.html)
        cls.app = read(SITE / "app.js")
        cls.css = read(SITE / "styles.css")

    def test_inline_script_is_allowed_by_its_hash(self):
        scripts = re.findall(r"<script>([\s\S]*?)</script>", self.html)
        self.assertEqual(len(scripts), 1, "one inline script, the theme-before-paint one")
        # One line, so the hash is the same whether the file is served with LF (git, Pages) or CRLF (a Windows checkout).
        self.assertNotIn("\n", scripts[0])
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", self.csp["script-src"])
        self.assertNotIn("'unsafe-inline'", self.csp["script-src"])
        self.assertLess(self.html.find("localStorage.getItem('air2:theme')"), self.html.find('<link rel="stylesheet"'))

    def test_policy_is_closed_by_default(self):
        self.assertEqual(self.csp["default-src"], ["'self'"])
        self.assertEqual(self.csp["object-src"], ["'none'"])
        self.assertEqual(self.csp["base-uri"], ["'self'"])
        self.assertEqual(self.csp["font-src"], ["'self'"])
        self.assertEqual(self.csp["form-action"], ["'none'"])
        # Ends with ";": security software that appends its own directives (Kaspersky's web scan does, measured on
        # this machine) then adds a new directive instead of polluting form-action 'none'.
        self.assertTrue(re.search(r'<meta http-equiv="Content-Security-Policy" content="[^"]+;">', self.html))

    def test_reader_has_one_cloudflare_module_after_the_policy(self):
        scripts = re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>", self.html)
        beacons = [(attrs, body) for attrs, body in scripts if "cloudflareinsights.com" in attrs]
        self.assertEqual(len(beacons), 1)
        attrs, body = beacons[0]
        self.assertIn("type='module'", attrs)
        self.assertIn("src='https://static.cloudflareinsights.com/beacon.min.js'", attrs)
        config = json.loads(re.search(r"data-cf-beacon='([^']+)'", attrs).group(1))
        self.assertEqual(set(config), {"token"})
        self.assertRegex(config["token"], r"^[a-f0-9]{32}$")
        # Pin the owner's public site tag without repeating its value in assertion failures.
        self.assertEqual(hashlib.sha256(config["token"].encode()).hexdigest(),
                         "ac50ff27adef59eaf1754c2f483debe1e7045b503e0486ea84015ad83590749f")
        self.assertEqual(body, "")
        self.assertEqual(self.html.count("data-cf-beacon="), 1)
        self.assertIn(attrs, self.head)
        self.assertLess(self.head.index('http-equiv="Content-Security-Policy"'), self.head.index(attrs))
        self.assertLess(self.head.index('src="app.js"'), self.head.index(attrs))
        self.assertLess(self.head.rindex('rel="modulepreload"'), self.head.index(attrs))

    def test_reader_loads_no_other_script_sources(self):
        self.assertEqual(ScriptSources(self.html).sources, [
            "app.js", "https://static.cloudflareinsights.com/beacon.min.js",
        ])

    def test_cloudflare_permissions_do_not_broaden_script_or_connection_sources(self):
        inline = re.search(r"<script>([\s\S]*?)</script>", self.html).group(1)
        digest = base64.b64encode(hashlib.sha256(inline.encode("utf-8")).digest()).decode()
        self.assertEqual(set(self.csp["script-src"]), {
            "'self'", f"'sha256-{digest}'", "https://static.cloudflareinsights.com/beacon.min.js",
        })
        self.assertEqual(set(self.csp["connect-src"]), {
            "'self'", "https://hn.algolia.com", "https://huggingface.co", "https://cloudflareinsights.com",
        })

    def test_cloudflare_is_only_on_reader_pages(self):
        for path in (SITE / "brand" / "index.html", ROOT / "design" / "tokens.html"):
            self.assertNotIn("cloudflareinsights.com", read(path), path)
            self.assertNotIn("data-cf-beacon", read(path), path)

    def test_every_host_the_code_calls_is_allowed(self):
        js = {name: read(SITE / name) for name in ("app.js", "faces.js", "live.js")}
        fetched = set()
        for text in js.values():
            fetched |= set(re.findall(r"(?:fetch|getJSON)\([`'\"]https://([a-z0-9.-]+)/", text))
        self.assertEqual(fetched, {"hn.algolia.com", "huggingface.co"})
        for host in fetched:
            self.assertIn(f"https://{host}", self.csp["connect-src"], host)
        images = set(re.findall(r"imgSrc\(`https://([a-z0-9.-]+)/", js["app.js"] + js["faces.js"]))
        # Hugging Face avatar URLs come from its API and are accepted only on this host (okHF in faces.js).
        if r"^https:\/\/cdn-avatars\.huggingface\.co\/" in js["faces.js"]:
            images.add("cdn-avatars.huggingface.co")
        self.assertTrue({"avatars.githubusercontent.com", "i.ytimg.com", "cdn-avatars.huggingface.co"} <= images, images)
        for host in images:
            self.assertIn(f"https://{host}", self.csp["img-src"], host)

    def test_canonical_and_referrer(self):
        self.assertIn('<link rel="canonical" href="https://dootan2020.github.io/ai-radar/">', self.head)
        self.assertIn('<meta name="referrer" content="strict-origin-when-cross-origin">', self.head)

    def test_snapshot_starts_with_the_html_and_the_page_takes_that_request_over(self):
        self.assertIn('<link rel="preload" href="data/radar-ui.json" as="fetch" crossorigin>', self.head)
        # A preload is only reused by a request with the same mode and cache setting: the first fetch adds none.
        self.assertIn("loadSnapshot(DATA_URL, FALLBACK_URL).then(", self.app)
        self.assertNotIn("cache:'no-store'", self.app)
        self.assertIn("loadSnapshot(DATA_URL, FALLBACK_URL, {cache:'no-cache'})", self.app)

    def test_fonts_are_served_from_the_site(self):
        for path in (SITE / "index.html", SITE / "styles.css", ROOT / "design" / "tokens.html"):
            self.assertNotIn("fonts.googleapis.com", read(path), path)
            self.assertNotIn("fonts.gstatic.com", read(path), path)
        faces = re.findall(r"@font-face\{[^}]*\}", self.css)
        self.assertEqual(len(faces), 12)
        for face in faces:
            self.assertIn("font-display:swap", face)
            self.assertTrue((SITE / re.search(r"url\((fonts/[^)]+)\)", face).group(1)).is_file(), face)
        self.assertTrue((SITE / "fonts" / "OFL.txt").is_file())
        # Per weight the vietnamese face is declared last, so ă đ ơ ư (also in latin-ext's range) never load latin-ext.
        order = [re.search(r"-(latin-ext|latin|vietnamese)\.woff2", f).group(1) for f in faces]
        self.assertEqual(order, ["latin-ext", "latin", "vietnamese"] * 4)

    def test_design_showcase_is_not_published(self):
        # Pages uploads site/; the token showcase lives in design/ (owner, 03/10 18:05) and still reads the live files.
        self.assertFalse((SITE / "tokens.html").exists())
        self.assertFalse((SITE / "tokens.js").exists())
        self.assertNotIn('href="tokens.html"', self.app)
        showcase = read(ROOT / "design" / "tokens.html")
        for ref in ('href="../site/tokens.css"', 'href="../site/styles.css"', 'src="tokens.js"', '<meta name="robots" content="noindex">'):
            self.assertIn(ref, showcase)
        js = read(ROOT / "design" / "tokens.js")
        for ref in ("from '../site/faces.js'", "from '../site/calendar.js'", "from '../site/words.js'", "fetch('../site/data/radar.json'"):
            self.assertIn(ref, js)

    def test_lead_enters_without_going_transparent(self):
        # An element animated from opacity 0 is not an LCP candidate; the lead's headline must be one.
        self.assertIn(".board.ready > .t-lead{animation-name:lead-in}", self.css)
        keyframes = re.search(r"@keyframes lead-in\{(.*?)\}\}", self.css).group(1)
        self.assertNotIn("opacity", keyframes)

    def test_third_party_calls_wait_for_the_first_screen(self):
        self.assertNotIn("import { startLive }", self.app)
        self.assertIn("const { startLive } = await import('./live.js');", self.app)
        self.assertIn("function hydrateVisible(){ if (thirdPartyReady) hydrateHF(document); }", self.app)
        self.assertIn("setDeferImages(true);", self.app)
        self.assertIn("loadDeferredImages();", self.app)


class RenderedFixWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read(SITE / "index.html")
        cls.app = read(SITE / "app.js")
        cls.css = read(SITE / "styles.css")

    def test_story_sheet_is_a_modal_dialog(self):
        self.assertRegex(self.html, r'<aside class="sheet" id="sheet" role="dialog" aria-modal="true"[^>]*aria-labelledby="sheet-h"')
        self.assertEqual(self.app.count('<h2 id="sheet-h">'), 2, "story and repository details both name the dialog")
        self.assertIn("const BACKGROUND = ['.skip', '#bar', '#fresh', 'main', '#tabs'];", self.app)
        self.assertIn("backgroundInert(true);", self.app)
        self.assertIn("backgroundInert(false);", self.app)
        self.assertIn("focusSheet();", self.app)
        # Under reduced motion every element got a 150 ms "all" transition, which kept the close button hidden.
        self.assertIn(".sheet *{transition-property:none !important}", self.css)

    def test_upcoming_events_put_the_calendar_under_the_title(self):
        self.assertIn('`<div class="ev-item">${r}${cal ? calButtons(', self.app)
        self.assertIn("eventRange(e.start_date, e.end_date)", self.app)
        self.assertIn(".ev-list{gap:var(--space-8);container-type:inline-size}", self.css)
        self.assertIn("@container (max-width: 440px)", self.css)

    def test_source_rows_are_44px_targets(self):
        self.assertIn(".srow{position:relative;min-height:var(--btn-h)}", self.css)
        self.assertIn('.srow a::after{content:"";position:absolute;inset:0', self.css)

    def test_tablet_bar_keeps_the_theme_button_on_screen(self):
        self.assertIn("@media (min-width: 768px) and (max-width: 1099px){\n    .bar{gap:var(--space-16)}\n    .src-state .w{display:none}".replace("\n", "\r\n" if "\r\n" in self.css else "\n"), self.css)

    def test_stale_line(self):
        self.assertIn('<p class="stale" id="stale" role="status" hidden></p>', self.html)
        self.assertIn("freshnessText(freshness(D.generated_at, D.sources), D.generated_at)", self.app)
        self.assertIn("renderStale(); }, 60_000);", self.app)

    def test_phone_lead_keeps_its_summary_behind_a_button(self):
        self.assertIn('<h2 class="lead-title-wrap">', self.app)
        self.assertNotIn("<h3", self.app)
        self.assertIn('data-lead-sum aria-controls="lead-sum" aria-expanded="${leadOpen}"', self.app)
        self.assertIn(".lead-sum:not(.is-open){display:-webkit-box;-webkit-line-clamp:3", self.css)

    def test_long_lists_build_only_the_rows_they_show(self):
        self.assertIn("function capList(owner, cap, items, draw){", self.app)
        self.assertIn("l.insertAdjacentHTML('beforeend', rest());", self.app)
        self.assertNotIn("kids.slice(cap).forEach(k => k.hidden = true)", self.app)

    def test_brand_light_plates_keep_light_ink_in_dark_mode(self):
        for path in (ROOT / "brand" / "index.html", SITE / "brand" / "index.html"):
            self.assertIn(".on-light,.on-white{--color-ink:var(--gray-21);--color-ink-2:var(--gray-44);--color-ink-3:var(--gray-51)",
                          read(path), path)
            # The safe-area label sits on a fixed light chip, so its ink is the light accent in both modes (2.26:1 before).
            self.assertIn("color:var(--blue-53);background:var(--gray-99)", read(path), path)

    def test_story_kind_is_a_tag_with_its_own_shape(self):
        # Owner, 03/10 ~18:05: a story's kind must read at a glance, never by colour alone.
        words = read(SITE / "words.js")
        kinds = re.findall(r"(\w+):'", re.search(r"export const KIND = \{([^}]*)\}", words).group(1))
        icons = dict(re.findall(r"(\w+):'(i-[\w-]+)'", re.search(r"const KIND_ICON = \{([^}]*)\}", self.app).group(1)))
        self.assertEqual(set(icons), set(kinds), "every kind has a shape")
        self.assertEqual(len(set(icons.values())), len(icons), "no two kinds share a shape")
        for symbol in icons.values():
            self.assertIn(f'<symbol id="{symbol}"', self.html, symbol)
        self.assertEqual(self.app.count("${kindTag(st)}"), 3, "row meta, lead label and the sheet's facts")
        self.assertEqual(self.app.count("${kindName(st)}"), 1, "the plain word is used only inside kindTag")
        self.assertIn(".kind{display:inline-flex", self.css)

    def test_new_count_left_the_header_for_the_new_tile(self):
        # Owner, 03/10 ~18:05: the "N tin mới" counter crowded the header. The count stays in the tile's keynote and
        # the tab badge; marking as seen moved into the same tile.
        bar = re.search(r'<header class="bar" id="bar">[\s\S]*?</header>', self.html).group(0)
        self.assertNotIn('id="since"', bar)
        self.assertNotIn("since-n", self.app)
        self.assertNotIn(".since", self.css)
        tile = re.search(r"function newTile\(shown\)\{[\s\S]*?\n\}", self.app).group(0)
        self.assertIn('<button class="btn-quiet" id="mark" aria-keyshortcuts="M"', tile)
        self.assertIn("data-count=", tile)
        self.assertIn("b.getAttribute('aria-disabled') !== 'true'", self.app)

    def test_chapter_count_sits_inside_its_heading(self):
        self.assertNotIn('class="ch-n"', self.app)
        self.assertIn('<h2 id="h-${id}">${title} <span class="ch-c">${count}</span></h2>', self.app)
        self.assertEqual(self.app.count("${chHead("), 3, "saved, every topic chapter, and sources")

    def test_translated_chip_uses_google_translate_colours(self):
        tokens = read(SITE / "tokens.css")
        self.assertIn("--gt-blue-700: #1967d2; --gt-blue-50: #e8f0fe; --gt-blue-300: #8ab4f8; --gt-blue-night: #283a57;", tokens)
        self.assertEqual(tokens.count("--color-mt-ink:"), 3, "light, dark and system-dark")
        self.assertIn("background:var(--color-mt-bg);color:var(--color-mt-ink)", self.css)


if __name__ == "__main__":
    unittest.main()

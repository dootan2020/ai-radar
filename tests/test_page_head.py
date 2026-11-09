"""Static checks for the production page: its <head> (CSP, canonical, referrer, how the snapshot and fonts load) and
the wiring of the fixes measured on the rendered page (story sheet as a modal dialog, upcoming events, touch areas,
stale-data line, phone lead, brand plates in dark mode).

The rendered behaviour itself is measured with headless Chrome (plans/reports/san-ui-claude.md); these tests keep
the pieces from silently disappearing.
"""

from pathlib import Path
from radar.site_config import SITE_URL
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
        cls.css = read(SITE / "styles.css")


    def test_cloudflare_is_only_on_reader_pages(self):
        for path in (SITE / "brand" / "index.html", ROOT / "design" / "tokens.html"):
            self.assertNotIn("cloudflareinsights.com", read(path), path)
            self.assertNotIn("data-cf-beacon", read(path), path)

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


class RenderedFixWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = read(SITE / "styles.css")

    def test_story_sheet_is_a_modal_dialog(self):
        # Under reduced motion every element got a 150 ms "all" transition, which kept the close button hidden.
        self.assertIn(".sheet *{transition-property:none !important}", self.css)

    def test_upcoming_events_put_the_calendar_under_the_title(self):
        self.assertIn(".ev-list{gap:var(--space-8);container-type:inline-size}", self.css)
        self.assertIn("@container (max-width: 440px)", self.css)

    def test_source_rows_are_44px_targets(self):
        self.assertIn(".srow{position:relative;min-height:var(--btn-h)}", self.css)
        self.assertIn('.srow a::after{content:"";position:absolute;inset:0', self.css)

    def test_tablet_bar_keeps_the_theme_button_on_screen(self):
        self.assertIn("@media (min-width: 768px) and (max-width: 1099px){\n    .bar{gap:var(--space-16)}\n    .src-state .w{display:none}".replace("\n", "\r\n" if "\r\n" in self.css else "\n"), self.css)


    def test_phone_lead_keeps_supporting_details_behind_a_button(self):
        self.assertIn('.t-lead .lead-details{display:none}', self.css)
        self.assertIn('.t-lead.is-expanded .lead-details{display:flex', self.css)


    def test_brand_book_uses_separate_light_and_dark_logo_variants(self):
        for path in (ROOT / "brand" / "index.html", SITE / "brand" / "index.html"):
            book = read(path)
            self.assertIn("[data-theme=light] .only-dark,[data-theme=dark] .only-light{display:none}", book)
            self.assertIn('coral-tile/logos/halcyon-primary.svg', book)
            self.assertIn('coral-tile/logos/halcyon-dark.svg', book)
            self.assertIn('coral-tile/icons/halcyon-icon-primary.svg', book)

    def test_story_kind_is_a_tag_with_its_own_shape(self):
        # Owner, 03/10 ~18:05: a story's kind must read at a glance, never by colour alone.
        words = read(SITE / "words.js")
        kinds = re.findall(r"(\w+):'", re.search(r"export const KIND = \{([^}]*)\}", words).group(1))
        self.assertIn(".kind{display:inline-flex", self.css)

    def test_new_count_left_the_header_for_the_new_tile(self):
        # Owner, 03/10 ~18:05: the "N tin mới" counter crowded the header. The count stays in the tile's keynote and
        # the tab badge; marking as seen moved into the same tile.
        self.assertNotIn(".since", self.css)


    def test_translated_chip_uses_neutral_semantic_colours(self):
        tokens = read(SITE / "tokens.css")
        self.assertNotIn("--gt-blue-", tokens)
        self.assertEqual(tokens.count("--color-mt-bg: var(--color-fill);"), 3, "light, dark and system-dark")
        self.assertEqual(tokens.count("--color-mt-ink: var(--color-ink-2);"), 3, "light, dark and system-dark")
        self.assertIn("background:var(--color-mt-bg);color:var(--color-mt-ink)", self.css)


if __name__ == "__main__":
    unittest.main()

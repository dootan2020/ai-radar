"""The pages beside the front page wear its shell, and the 404 page works at any depth.

Captain, 16/11 ("Duyệt theo em"): Bản tin, Nguồn tin, a story's page, Chính sách and the 404 page share the front page's
top row, panel and cards (site/trang-phu.css, site/trang-phu.js); light and dark live in "Tùy chỉnh", never in the
header; reduced motion keeps fades and drops movement. The UI audit of 16/11 (w2) found a missing 404 page (unknown
addresses showed a broken front page) and a policy page built on tokens that do not exist.
"""

import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SHELL_PAGES = {
    "ban-tin.html": SITE / "ban-tin.html",
    "nguon.html": SITE / "nguon.html",
    "chinh-sach-rieng-tu.html": SITE / "chinh-sach-rieng-tu.html",
    "404.html": SITE / "404.html",
    "tin/_sample/index.html": SITE / "tin" / "_sample" / "index.html",
    "story_page_template.html": ROOT / "radar" / "story_page_template.html",
}


def read(path):
    return path.read_text(encoding="utf-8")


def defined_tokens():
    names = set()
    for sheet in ("tokens.css", "fonts.css"):
        names |= set(re.findall(r"(--[\w-]+)\s*:", read(SITE / sheet)))
    return names


class SubPageShellTests(unittest.TestCase):
    def test_every_sub_page_wears_the_front_page_shell(self):
        for name, path in SHELL_PAGES.items():
            html = read(path)
            with self.subTest(page=name):
                self.assertIn('class="masthead phu-top"', html)
                self.assertIn('id="phu-tc"', html)
                self.assertIn('class="phu-panel', html)
                self.assertIn('class="brand-tile"', html)
                self.assertIn('class="brand-name"', html)
                self.assertIn("trang-phu.css", html)
                self.assertIn("trang-phu.js", html)
                # The site font: fonts.css, or feed.css, which carries the same @font-face rules.
                self.assertTrue("fonts.css" in html or "feed.css" in html)
                self.assertEqual(html.count('<div class="tool-launcher"></div>'), 1)
                # Light and dark are chosen in "Tùy chỉnh" (captain, 11/11 13:54), and the 160 px wordmark of 04/11 left
                # with the old header.
                for retired in ('id="theme-btn"', 'id="theme"', "wordmark.svg", 'class="feed-bar"', 'class="bt-bar"'):
                    self.assertNotIn(retired, html)

    def test_the_settings_sheet_carries_the_theme_and_the_two_pages(self):
        script = read(SITE / "trang-phu.js")
        self.assertIn("export const THEME_KEY = 'air2:theme'", script)
        self.assertIn("['light', 'Sáng'], ['dark', 'Tối'], ['system', 'Theo máy']", script)
        self.assertIn("['nguon.html', 'Nguồn tin'], ['chinh-sach-rieng-tu.html', 'Chính sách riêng tư']", script)

    def test_sub_page_styles_use_only_tokens_that_exist(self):
        # The policy page used --size-24, --size-20 and --space-20; none exists, so its title fell to 16 px and its
        # callout lost its padding (w2). Every custom property a sub-page reads must be defined somewhere it loads.
        tokens = defined_tokens()
        sources = {"trang-phu.css": read(SITE / "trang-phu.css"), "ban-tin.css": read(SITE / "ban-tin.css")}
        for name in ("chinh-sach-rieng-tu.html", "404.html", "nguon.html"):
            styles = re.findall(r"<style>(.*?)</style>", read(SHELL_PAGES[name]), re.S)
            sources[name] = "\n".join(styles)
        for name, css in sources.items():
            local = set(re.findall(r"(--[\w-]+)\s*:", css))
            used = set(re.findall(r"var\((--[\w-]+)\s*\)", css))   # a var() with a fallback is set per element
            with self.subTest(sheet=name):
                self.assertEqual(sorted(used - tokens - local), [])

    def test_policy_page_reads_as_a_document(self):
        html = read(SITE / "chinh-sach-rieng-tu.html")
        self.assertNotIn("🇻🇳", html)
        self.assertNotIn("🇬🇧", html)
        self.assertIn('<h1 class="policy-title">Chính sách quyền riêng tư / Privacy Policy</h1>', html)
        self.assertIn("<h2>1. Cam kết quyền riêng tư cốt lõi</h2>", html)
        self.assertNotIn("<h2>1. Cam Kết", html)
        self.assertIn(".policy-body { max-width: 60ch; }", html)
        self.assertIn("min-height: var(--btn-h)", html)
        # The theme switch left with the header, so the page needs no inline script beyond the first-paint one.
        self.assertNotIn("'unsafe-inline' https://static.cloudflareinsights.com", html)


class NotFoundPageTests(unittest.TestCase):
    def setUp(self):
        self.html = read(SITE / "404.html")

    def test_not_found_page_is_served_at_any_depth(self):
        # Cloudflare Pages serves site/404.html, with status 404, for any address it has no file for, /tin/<old id>/
        # included; every address in it is absolute, and the base gives menu-cong-cu.js's relative dock links the root.
        self.assertIn('<base href="/">', self.html)
        self.assertIn('<meta name="robots" content="noindex">', self.html)
        for attr, value in re.findall(r'\b(href|src)="([^"]*)"', self.html):
            with self.subTest(value=value):
                self.assertTrue(value.startswith(("/", "#", "https://")), value)

    def test_not_found_page_says_so_and_offers_a_way_on(self):
        self.assertIn("Không tìm thấy trang này", self.html)
        self.assertIn('href="/">Về trang nhất</a>', self.html)
        self.assertIn("data-tim-tin", self.html)
        self.assertIn('href="/ban-tin.html"', self.html)

    def test_inline_script_is_allowed_by_its_hash(self):
        script = re.search(r"<script>(.*?)</script>", self.html, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", self.html)
        self.assertNotIn("'unsafe-inline' https://static", self.html)


class MotionTests(unittest.TestCase):
    def test_reduced_motion_keeps_the_fade_and_drops_the_slide(self):
        story = read(SITE / "story.css")
        block = story.split("@media (prefers-reduced-motion: reduce) {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("animation: storyFadeIn var(--duration-150)", block)
        self.assertNotIn("animation: none", block)
        fade = story.split("@keyframes storyFadeIn {", 1)[1].split("}\n}", 1)[0]
        self.assertNotIn("transform", fade)
        ban_tin = read(SITE / "ban-tin.css")
        self.assertNotIn("transition-duration: 0.01ms", ban_tin)

    def test_card_lift_answers_a_mouse_only(self):
        css = read(SITE / "ban-tin.css")
        hover = css.split("@media (hover: hover) and (pointer: fine) {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(":hover", hover)
        self.assertIn("translateY(var(--tile-hover-lift))", hover)
        self.assertEqual(len(re.findall(r"^\.bt-tile:hover", css, re.M)), 0)

    def test_small_audit_fixes(self):
        story = read(SITE / "story.css")
        kbd = story.split(".story-close-kbd {", 1)[1].split("}", 1)[0]
        self.assertIn("color: var(--color-ink-2)", kbd)
        css = read(SITE / "ban-tin.css")
        back = css.split(".bt-back-to-top {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: var(--btn-h)", back)
        kind = css.split(".bt-story-kind {", 1)[1].split("}", 1)[0]
        self.assertIn("color: var(--color-ink-2)", kind)
        # Phone story headlines at the front page's phone card sizes (captain 16/11, decision 6).
        phone = css.split("@media (max-width: 767px) {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(".bt-story-title {\n    font-size: var(--text-title);", phone)
        self.assertIn(".bt-tile-lead .bt-story-title {\n    font-size: var(--text-tile);", phone)


SCRIPT_HARNESS = """
import {{ searchHref, readTheme, saveTheme }} from {trang_phu};
const nguon = {nguon_src};
const body = nguon.split('export function displayName(s) {{')[1].split('\\n}}\\n')[0];
const nameOf = s => s.name || s.id;
const displayName = new Function('nameOf', 's', body);
const store = new Map();
const storage = {{ getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k) }};
saveTheme(storage, 'dark');
const dark = readTheme(storage);
saveTheme(storage, 'system');
process.stdout.write(JSON.stringify({{
  search: searchHref('  chat gpt '),
  empty: searchHref(''),
  dark, system: readTheme(storage), stored: store.size,
  names: [
    displayName(nameOf, {{ name: 'Anthropic News (nguồn cộng đồng gftdon)', id: 'a' }}),
    displayName(nameOf, {{ name: '🚨 AI News | TestingCatalog (@testingcatalog)', id: 'b' }}),
    displayName(nameOf, {{ name: 'Kevin Weil 🇺🇸 (@kevinweil)', id: 'c' }}),
    displayName(nameOf, {{ name: '🚨', id: 'only-emoji' }}),
  ],
}}));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class ShellScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(SCRIPT_HARNESS.format(
                trang_phu=json.dumps((SITE / "trang-phu.js").as_uri()),
                nguon_src=json.dumps(read(SITE / "nguon.js").replace("\r\n", "\n"))), encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                    timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout)

    def test_search_goes_to_the_front_page_search(self):
        self.assertTrue(self.out["search"].endswith("/site/?q=chat%20gpt"), self.out["search"])
        self.assertTrue(self.out["empty"].endswith("/site/#tim"), self.out["empty"])

    def test_theme_choice_is_the_front_page_key(self):
        self.assertEqual(self.out["dark"], "dark")
        self.assertEqual(self.out["system"], "system")
        self.assertEqual(self.out["stored"], 0)

    def test_source_names_drop_desk_notes_and_emoji(self):
        self.assertEqual(self.out["names"], [
            "Anthropic News", "AI News | TestingCatalog (@testingcatalog)", "Kevin Weil (@kevinweil)", "only-emoji"])


if __name__ == "__main__":
    unittest.main()

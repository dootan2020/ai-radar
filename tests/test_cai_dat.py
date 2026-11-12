"""The extension's invitation on hco.news (captain, 11/11 23:55: "extension được duyệt rồi, đưa nó lên web cho mọi người có
thể tải về"; "làm gọn gàng, tinh tế cho anh"): a quiet tile beside "Tùy chỉnh" and a line inside it, only on a desktop
Chromium browser, never in the extension's own new tab; the link goes through /cai-dat/, which forwards to the Store."""
import base64
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"
STORE = "https://chromewebstore.google.com/detail/halcyon/bmjpihjkbkjjfhghelmgmnehnmfdhhad"

PROBE = r"""
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const tt = await import(pathToFileURL(path.resolve('site/thanh-tren.js')).href);
const loc = protocol => ({ protocol });
const fine = q => ({ matches: q === '(pointer: fine)' });
const coarse = () => ({ matches: false });
const ua = (mobile, brands) => ({ userAgentData: { mobile, brands: brands.map(brand => ({ brand, version: '142' })) } });
const desktop = ua(false, ['Chromium', 'Google Chrome', 'Not_A Brand']);
const memory = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)) }; };
const broken = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); } };
const s = memory();
const before = tt.offerHidden(s);
const saved = tt.hideOffer(s);
console.log(JSON.stringify({
  chrome: tt.canInstall(desktop, loc('https:'), fine),
  edge: tt.canInstall(ua(false, ['Chromium', 'Microsoft Edge']), loc('https:'), fine),
  coccoc: tt.canInstall(ua(false, ['Chromium', 'CocCoc']), loc('https:'), fine),
  phone: tt.canInstall(ua(true, ['Chromium', 'Google Chrome']), loc('https:'), fine),
  tablet: tt.canInstall(desktop, loc('https:'), coarse),
  firefox: tt.canInstall({}, loc('https:'), fine),
  newTab: tt.canInstall(desktop, loc('chrome-extension:'), fine),
  before, saved, after: tt.offerHidden(s), brokenHidden: tt.offerHidden(broken), brokenSaved: tt.hideOffer(broken),
  key: tt.OFFER_KEY, href: tt.OFFER_HREF,
}));
"""


def read(path):
    return path.read_text(encoding="utf-8")


class InvitationRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "--input-type=module", "-e", PROBE], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
        if run.returncode != 0:
            raise AssertionError(run.stderr)
        cls.r = json.loads(run.stdout.strip().splitlines()[-1])

    def test_only_a_desktop_chromium_browser_with_a_mouse_is_invited(self):
        for name in ("chrome", "edge", "coccoc"):
            self.assertTrue(self.r[name], name)
        for name in ("phone", "tablet", "firefox", "newTab"):
            self.assertFalse(self.r[name], name)

    def test_dismissing_stays_in_this_browser_and_failing_storage_never_throws(self):
        self.assertFalse(self.r["before"])
        self.assertTrue(self.r["saved"])
        self.assertTrue(self.r["after"])
        self.assertFalse(self.r["brokenHidden"])
        self.assertFalse(self.r["brokenSaved"])
        self.assertEqual(self.r["key"], "halcyon:cai-tien-ich")

    def test_the_link_goes_through_the_counting_page_in_a_new_tab(self):
        self.assertEqual(self.r["href"], "/cai-dat/")
        js = read(SITE / "thanh-tren.js")
        self.assertIn('target="_blank" rel="noopener"', js)
        self.assertNotIn("chromewebstore", js)   # one Store address, kept in the forwarding page

    def test_the_new_tab_carries_no_invitation_markup(self):
        self.assertEqual(read(SITE / "thanh-tren.js"), read(EXT / "thanh-tren.js"))
        self.assertEqual(read(SITE / "trang-msn.css"), read(EXT / "trang-msn.css"))
        newtab = read(EXT / "newtab.html")
        self.assertNotIn("cai-offer", newtab)
        self.assertNotIn("cai-dat", newtab)


class InvitationStyle(unittest.TestCase):
    def test_the_card_sits_in_the_bottom_right_corner_only_on_a_desktop_window_with_a_mouse(self):
        css = read(SITE / "trang-msn.css")
        self.assertIn(".cai-widget { display: none; }", css)
        block = css[css.index(".cai-widget { display: none; }"):css.index(".cai-go:focus-visible")]
        self.assertIn("@media (min-width: 1024px) and (pointer: fine) {", block)
        self.assertIn("position: fixed; z-index: 70; right: var(--space-24); bottom: var(--space-24);", block)
        self.assertIn("transform-origin: bottom right;", block)
        # The page's toasts use the same corner (feed.css): while the card shows they stand above it.
        self.assertIn("bottom: var(--space-24); right: var(--space-24);", read(SITE / "feed.css"))
        self.assertIn(":root[data-cai] .toast-container { bottom: calc(var(--space-24) + var(--cai-h) + var(--space-12)); }", block)
        self.assertNotIn("border:", block.replace("border: 0;", ""))   # no outline (captain's standing taste)
        rules = re.sub(r"@media[^{]*\{", "", block)   # a breakpoint is not a design value
        self.assertNotRegex(rules, r"(?<![\w-])\d+px")   # every value from tokens

    def test_the_old_top_row_tile_is_gone(self):
        for path in (SITE / "thanh-tren.js", SITE / "trang-msn.css"):
            code = re.sub(r"/\*.*?\*/", "", read(path), flags=re.S)   # comments may quote the captain
            self.assertNotIn("cai-offer", code, path.name)
            self.assertNotIn("thẻ mới", code, path.name)   # captain 12/11: readers say "tab", never "thẻ mới"


class InvitationWords(unittest.TestCase):
    """Captain, 12/11 09:20: "mọi người hay quen là tab, extension"."""

    @classmethod
    def setUpClass(cls):
        probe = r"""
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const tt = await import(pathToFileURL(path.resolve('site/thanh-tren.js')).href);
const nav = (...brands) => ({ userAgentData: { mobile: false, brands: brands.map(brand => ({ brand, version: '142' })) } });
console.log(JSON.stringify({
  chrome: tt.offerWords(tt.browserName(nav('Chromium', 'Google Chrome', 'Not_A Brand'))),
  edge: tt.offerWords(tt.browserName(nav('Chromium', 'Microsoft Edge'))),
  coccoc: tt.offerWords(tt.browserName(nav('Chromium', 'CocCoc'))),
  other: tt.offerWords(tt.browserName(nav('Chromium'))),
  delay: tt.OFFER_DELAY,
}));
"""
        run = subprocess.run(["node", "--input-type=module", "-e", probe], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
        if run.returncode != 0:
            raise AssertionError(run.stderr)
        cls.w = json.loads(run.stdout.strip().splitlines()[-1])

    def test_the_card_names_the_tab_and_the_extension_and_the_store_s_own_button(self):
        self.assertEqual(self.w["chrome"], {"title": "Tin AI trên mỗi tab mới", "line": "Extension miễn phí cho Chrome",
                                            "go": "Thêm vào Chrome"})
        self.assertEqual(self.w["edge"]["go"], "Thêm vào Edge")
        self.assertEqual(self.w["coccoc"]["go"], "Thêm vào Cốc Cốc")
        self.assertEqual(self.w["other"], {"title": "Tin AI trên mỗi tab mới", "line": "Extension miễn phí cho trình duyệt",
                                           "go": "Cài extension"})

    def test_the_card_waits_a_moment_and_has_a_visible_hide_button(self):
        self.assertGreaterEqual(self.w["delay"], 2000)
        js = read(SITE / "thanh-tren.js")
        self.assertIn('<button class="cai-x" type="button" aria-label="Ẩn gợi ý cài extension">Ẩn</button>', js)
        self.assertIn("<span>Extension Halcyon cho tab mới</span>", js)   # the permanent line in "Tùy chỉnh"


class ForwardingPage(unittest.TestCase):
    def setUp(self):
        self.html = read(SITE / "cai-dat" / "index.html")

    def test_it_forwards_to_the_store_and_nowhere_else(self):
        urls = set(re.findall(r"https://chromewebstore\.google\.com/[^'\"\s]*", self.html))
        self.assertEqual(urls, {STORE})
        self.assertIn(f'<meta http-equiv="refresh" content="3; url={STORE}">', self.html)
        self.assertIn('<meta name="robots" content="noindex">', self.html)

    def test_its_one_inline_script_is_allowed_by_its_hash_and_waits_for_the_load_event(self):
        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        self.assertEqual(len(scripts), 1)
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", self.html)
        self.assertTrue(scripts[0].startswith("addEventListener('load'"), scripts[0])
        self.assertIn("location.replace(", scripts[0])

    def test_it_adds_no_tracking_beyond_the_site_s_own_page_counts(self):
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', self.html).group(1)
        hosts = set(re.findall(r"https://[\w.-]+", csp))
        self.assertEqual(hosts, {"https://static.cloudflareinsights.com", "https://cloudflareinsights.com"})
        self.assertNotIn("<script src", self.html)
        self.assertNotIn("cookie", self.html.lower())


if __name__ == "__main__":
    unittest.main()

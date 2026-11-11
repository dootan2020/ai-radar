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
    def test_the_tile_shows_only_on_a_wide_window_with_a_mouse(self):
        css = read(SITE / "trang-msn.css")
        self.assertIn(".msn-top .cai-offer { display: none; }", css)
        self.assertIn("@media (min-width: 1366px) and (pointer: fine) {", css)
        self.assertIn(":root:not([data-nen=\"off\"]) .msn-top .cai-offer {", css)   # the tiles' material on the picture
        rules = css[css.index(".msn-top .cai-offer { display: none; }"):css.index(".cai-go:focus-visible")]
        rules = re.sub(r"@media[^{]*\{", "", rules)   # a breakpoint is not a design value
        self.assertNotRegex(rules, r"(?<![\w-])\d+px")   # every value from tokens


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
